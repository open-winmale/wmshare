"""匿名试用：领取一次性小配额凭据并落盘。

与付费凭据的隔离是本模块的核心约束：

- 付费凭据在 ``~/.wmshare/credentials.env``（``_credentials.DEFAULT_CREDENTIAL_PATH``）。
- 匿名凭据在 ``~/.wmshare/anon_credentials.env``，**永不写入前者**。

原因：``_credentials._parse`` 是 ``KEY=VALUE`` 平铺解析、不分段，两个身份的凭据
写进同一文件必然互相覆盖 —— 用户试过 ``anonymous()`` 之后，``from_env()`` 就会
拿到额度只有 50 万的匿名 app，且无从察觉。因此匿名走独立文件 + 独立环境变量
``WMSHARE_CREDENTIALS`` 指向该文件，其余解析逻辑完全复用。

与 1.7.0 下线的「内置体验 AppID」的区别（防回潮门禁关注的语义差别）：

- 下线的那套是**打包进 wheel 的一份共享凭据**，所有人共用、无归属、无配额上限；
- 这里每次领取都由服务端新建一个独立 app（``anon_open_*``），带 50 万 EC 一次性
  额度、不参与周补满、受单 IP 与日活上限约束。凭据不进入分发包。
"""
from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from wmshare._credentials import DEFAULT_CREDENTIAL_PATH
from wmshare.errors import AuthError, TransportError

#: 匿名凭据文件（与付费凭据分离，见模块 docstring）。
ANON_CREDENTIAL_PATH = Path.home() / ".wmshare" / "anon_credentials.env"

#: 申领端点路径。
ANON_CREDENTIALS_PATH = "/v1/oauth/anon-credentials"

_DEFAULT_BASE_URL = "https://api.winmale.com"


def anon_credentials_path() -> Path:
    """匿名凭据文件路径（可用 ``WMSHARE_ANON_CREDENTIALS`` 覆盖，便于测试）。"""
    override = os.environ.get("WMSHARE_ANON_CREDENTIALS", "").strip()
    return Path(override) if override else ANON_CREDENTIAL_PATH


def request_anon_credentials(
    base_url: str | None = None,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """向服务端申领一份匿名试用凭据。

    返回 ``{"client_id", "client_secret", "ec_balance", ...}``。
    服务端未开启该功能时返回 404（视同功能不存在），此处转成明确的
    ``AuthError``，并在文案里指向注册路径。
    """
    base = (base_url or os.environ.get("WMSHARE_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
    url = base + ANON_CREDENTIALS_PATH
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"Accept": "application/json", "User-Agent": "wmshare-py/anon"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = str(body.get("error", {}).get("message") or body.get("message") or "")
        except Exception:  # 响应体不是 JSON 时忽略，用状态码兜底
            detail = ""
        if exc.code == 404:
            raise AuthError(
                "该服务端未开放匿名试用；请到 https://open.winmale.com 注册免费账号"
                "（免费档 500 次/小时、5,000 次/日）获取凭据",
                code="anon_unavailable",
            ) from None
        if exc.code == 429:
            raise AuthError(
                "匿名试用今日名额已满（或本网络领取次数已达上限）；"
                "请到 https://open.winmale.com 注册免费账号继续",
                code="anon_quota",
            ) from None
        raise AuthError(
            f"匿名凭据申领失败（HTTP {exc.code}）{('：' + detail) if detail else ''}",
            code="anon_failed",
        ) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransportError(f"匿名凭据申领网络失败：{exc}") from None

    # 服务端统一信封 {ok, as_of, data, meta}；也兼容直接返回裸对象。
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict) or not data.get("client_id") or not data.get("client_secret"):
        raise AuthError("匿名凭据响应缺少 client_id/client_secret", code="anon_bad_response")
    return data


def save_anon_credentials(
    creds: dict[str, Any],
    path: Path | None = None,
) -> Path:
    """把匿名凭据写入独立文件（0600，原子替换）。

    刻意不覆盖付费凭据文件：路径不同 + 显式断言，双保险。
    """
    target = path or anon_credentials_path()
    if target.resolve() == DEFAULT_CREDENTIAL_PATH.resolve():
        raise AuthError(
            "匿名凭据不得写入付费凭据文件，请使用独立路径", code="config")
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# wmshare 匿名试用凭据（一次性小配额，用完即止）",
        f"WMSHARE_CLIENT_ID={creds['client_id']}",
        f"WMSHARE_CLIENT_SECRET={creds['client_secret']}",
        "WMSHARE_ANON=1",
    ]
    if creds.get("ec_balance") is not None:
        lines.append(f"WMSHARE_ANON_EC_BALANCE={creds['ec_balance']}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600，先收紧再替换
    os.replace(tmp, target)
    return target


def load_anon_credentials(path: Path | None = None) -> dict[str, Any] | None:
    """读取已存的匿名凭据；不存在或缺字段返回 ``None``。"""
    target = path or anon_credentials_path()
    if not target.is_file():
        return None
    out: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, _, value = clean.partition("=")
        out[key.strip()] = value.strip()
    cid = out.get("WMSHARE_CLIENT_ID", "")
    sec = out.get("WMSHARE_CLIENT_SECRET", "")
    if not cid or not sec:
        return None
    return {
        "client_id": cid,
        "client_secret": sec,
        "ec_balance": out.get("WMSHARE_ANON_EC_BALANCE"),
        "path": str(target),
    }


__all__ = [
    "ANON_CREDENTIAL_PATH",
    "ANON_CREDENTIALS_PATH",
    "anon_credentials_path",
    "load_anon_credentials",
    "request_anon_credentials",
    "save_anon_credentials",
]
