"""凭证文件读取：SDK 与 MCP 共用的一份解析 + POSIX 权限检查。

写端（``mcp/cli.py``）已经用 0600 原子替换，但用户手工创建的文件可能是
0644。这里在读端补告警；Windows / WSL / 某些挂载卷没有 POSIX 0600 语义，
因此**默认不硬拒绝**，只在 ``WMSHARE_STRICT_CRED_MODE=1`` 时抛错。
"""
from __future__ import annotations

import os
import stat
import warnings
from pathlib import Path

STRICT_CRED_MODE_ENV = "WMSHARE_STRICT_CRED_MODE"
DEFAULT_CREDENTIAL_PATH = Path.home() / ".wmshare" / "credentials.env"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _parse(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        clean = line.strip().removeprefix("export ").strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, _, raw = clean.partition("=")
        out[key.strip()] = raw.strip().strip('"').strip("'")
    return out


def read_credentials_file(
    path: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """解析 ``KEY=VALUE`` 凭证文件；文件不存在/读失败返回空 dict。

    ``env`` 为显式传入的环境快照（``Client.from_env(env={...})`` 场景），
    缺省时读 ``os.environ``，用于解析严格模式开关。
    """
    e = dict(os.environ if env is None else env)
    p = Path(path or DEFAULT_CREDENTIAL_PATH).expanduser()
    if not p.is_file():
        return {}
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except OSError:
        return {}
    if mode & 0o077:
        message = (
            f"凭证文件 {p} 权限为 {oct(mode)}，group/other 可读；建议 chmod 600。"
            f"设置 {STRICT_CRED_MODE_ENV}=1 可让 SDK 直接拒绝读取。"
        )
        if e.get(STRICT_CRED_MODE_ENV, "").strip().lower() in _TRUTHY:
            from wmshare.errors import UsageError

            raise UsageError(message, code="credential_mode")
        warnings.warn(message, stacklevel=2)
    try:
        return _parse(p.read_text(encoding="utf-8").splitlines())
    except OSError:
        return {}


__all__ = [
    "DEFAULT_CREDENTIAL_PATH",
    "STRICT_CRED_MODE_ENV",
    "read_credentials_file",
]
