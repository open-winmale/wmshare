"""OpenAPI 客户端：OAuth(client_credentials) + /v1/analysis/xs/eval（mode=call）。

  POST {base}/v1/oauth/token        form: grant_type/client_id/client_secret[+scope]
  POST {base}/v1/analysis/xs/eval   JSON: {symbol, xs_lines, args, script_files, market?, mode}
                                    Bearer token；mode=call → 顶层 return 值在 data.result
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, NoReturn

import requests

if TYPE_CHECKING:  # 前向引用：运行时惰性导入，避免潜在环
    from wmshare.notice_stream import NoticePoller

from wmshare.catalog import Catalog, load
from wmshare.errors import (
    APPID_GUIDANCE, ApiError, AuthError, CatalogError, WmshareError, LimitError,
    ServerError, TransportError, UsageError,
)
from wmshare.units import apply_units

DEFAULT_BASE_URL = "https://api.winmale.com"

# 无标的参数函数的求值锚点：网关按注册表校验 symbol 与 market 匹配，
# 固定 A 股锚点在 hk/us 客户端会 MARKET_MISMATCH（400）。
DEFAULT_SYMBOLS = {"cn": "600519", "hk": "00700", "us": "AAPL"}


_SYM_PREFIX = re.compile(r"^(?:cn|sh|sz|bj)\.", re.IGNORECASE)
_SYM_SUFFIX = re.compile(r"\.(?:SH|SZ|BJ)$", re.IGNORECASE)
# 美股：交易所后缀（AAPL.O=纳斯达克、BRK.N=纽交所 …）与类别股分隔符。
# 上游 symbol 注册表只有裸代码（AAPL、BRK_B）：带后缀的代码会被网关当作宏观序列
# （SYMBOL_TYPE_MACRO），跳过 SETCURSOR，指标脚本里的 symbol 变量因此未绑定——
# _LAST 族 500、分位族静默返 0（2026-10-30 实测 AAPL.O；AAPL 正常）。
_US_EXCH_SUFFIX = re.compile(r"^(?P<base>[A-Z][A-Z0-9]*)[.\-](?:O|N|A|K|P|OQ|NQ|US)$")
_US_CLASS_SEP = re.compile(r"^(?P<base>[A-Z][A-Z0-9]*)[.\-](?P<cls>[A-Z])$")


def _normalize_us(s: str, catalog: "Catalog | None") -> str:
    """美股代码归一：仅在离线代码表能确认时改写，避免误伤真实代码（如 ``O``）。"""
    if not s or catalog is None:
        return s
    try:
        universe = catalog.symbols_set("us")
    except Exception:  # 代码表缺失/损坏时不改写，交由上游报错
        return s
    if not universe or s in universe:
        return s
    # 类别股优先：BRK.B / BRK-B → BRK_B（注册表用下划线分类别）
    m = _US_CLASS_SEP.match(s)
    if m:
        candidate = f"{m.group('base')}_{m.group('cls')}"
        if candidate in universe:
            return candidate
    # 交易所后缀：AAPL.O / AAPL.N → AAPL
    m = _US_EXCH_SUFFIX.match(s)
    if m and m.group("base") in universe:
        return m.group("base")
    return s


def normalize_symbol(symbol: str, *, market: str | None = None,
                     catalog: "Catalog | None" = None) -> str:
    """标的代码归一：去 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀，字母转大写。

    传 ``market="us"`` + ``catalog`` 时，再按随包美股代码表消解交易所后缀与类别股
    写法：``AAPL.O`` → ``AAPL``、``BRK.B``／``BRK-B`` → ``BRK_B``。改名仅在代码表
    命中时发生（未命中保持原样，不猜）。

    例：``sh.600519.SH`` → ``600519``；``cn.000001`` → ``000001``；``aapl`` → ``AAPL``。
    """
    s = str(symbol).strip()
    s = _SYM_PREFIX.sub("", s)
    s = _SYM_SUFFIX.sub("", s)
    s = s.upper()
    if str(market or "").lower() == "us":
        s = _normalize_us(s, catalog)
    return s


@dataclass
class BatchResult:
    """批量调用结果：成功项与错误（票级或批级，视调用入口而定）。

    requests 记录本次共发出多少次 HTTP 请求——批量解决 429 的关键指标
    （429 按请求次数限流，免费档 500 次/小时、5000 次/日）。
    """

    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    requests: int = 0

    def to_df(self) -> Any:
        """转长表 DataFrame：每标的一行（值为 MAP 时字段展平，symbol 列在最前）。

        errors 中的失败标的不进表；results 为空时返回空表。
        """
        rows = []
        for sym, v in self.results.items():
            rows.append({"symbol": sym, **v} if isinstance(v, dict)
                        else {"symbol": sym, "value": v})
        return _to_dataframe(rows)


def _chunked(seq: list[Any], size: int) -> Iterator[list[Any]]:
    """把序列切成 size 大小的连续片（保序）。"""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _xs_literal(v: Any) -> str:
    """Python 值 → XS 字面量。

    XS 的空值是 ``nil``（不接受 JSON 的 ``null``），因此 None 必须单独映射；
    其余 string/number/bool/array/map 与 JSON 字面量一致。
    """
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_xs_literal(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_xs_literal(str(k))}: {_xs_literal(x)}"
                               for k, x in v.items()) + "}"
    return json.dumps(v, ensure_ascii=False)


def _to_dataframe(result: Any) -> Any:
    try:
        import pandas as pd  # optional dependency
    except ImportError as e:  # pragma: no cover
        raise UsageError("_df=True 需要安装 pandas：pip install pandas", code="pandas") from e
    if isinstance(result, list):
        return pd.DataFrame(result)
    if isinstance(result, dict):
        return pd.DataFrame([result])
    raise UsageError(f"结果类型 {type(result).__name__} 无法转 DataFrame", code="dataframe")


def _legacy_finpipe_hints() -> str:
    """检测旧版 finpipe 的配置残留（本项目更名前的 env 前缀与凭证路径）。

    只用于在缺凭证报错时指路迁移，不读取、不映射旧配置（更名即全面切新名）。
    """
    found = [k for k in ("FINPIPE_CLIENT_ID", "FINPIPE_CLIENT_SECRET")
             if os.environ.get(k)]
    legacy_file = Path.home() / ".finpipe" / "credentials.env"
    if legacy_file.is_file():
        found.append(str(legacy_file))
    return "、".join(found)


class Client:
    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        market: str = "cn",
        catalog: Catalog | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        max_limit: int | None = 500,
        retries: int = 2,
        backoff: float = 0.5,
        validate: bool = True,
    ):
        market = str(market or "cn").strip().lower()
        if market not in ("cn", "hk", "us"):
            raise UsageError(
                f"market 只支持 cn/hk/us，收到 {market!r}", code="market")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise UsageError("base_url 必须是非空 URL", code="config")
        if base_url is not None:
            parsed = urlsplit(base_url.strip())
            host = (parsed.hostname or "").lower()
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not (
                    parsed.scheme == "http" and host in local_hosts):
                raise UsageError(
                    "base_url 必须使用 HTTPS；本地网关可用 http://localhost、"
                    "http://127.0.0.1 或 http://[::1]", code="config")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
                or not float(timeout) > 0 or not math.isfinite(float(timeout)):
            raise UsageError("timeout 必须为正有限秒数", code="config")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise UsageError("retries 必须为非负整数", code="config")
        if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) \
                or not float(backoff) >= 0 or not math.isfinite(float(backoff)):
            raise UsageError("backoff 必须为非负有限秒数", code="config")
        if max_limit is not None and (isinstance(max_limit, bool)
                                      or not isinstance(max_limit, int) or max_limit <= 0):
            raise UsageError("max_limit 必须为正整数或 None", code="config")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        if bool(self.client_id) != bool(self.client_secret):
            raise AuthError(
                "client_id 与 client_secret 需成对提供。"
                f"不配置则无法取数——{APPID_GUIDANCE}", code="config")
        if not self.client_id:
            legacy = _legacy_finpipe_hints()
            raise AuthError(
                "缺少凭证：SDK 不再内置体验 AppID，请先配置自己的开放平台凭证"
                "（构造参数 / WMSHARE_* 环境变量 / ~/.wmshare/credentials.env 任一）。"
                + (f"\n检测到旧版 finpipe 配置（{legacy}）：本项目已更名 wmshare，"
                   "凭证配置同步改为 WMSHARE_* 环境变量 / ~/.wmshare/credentials.env，"
                   "旧配置不再被读取，请迁移。\n" if legacy else "\n")
                + f"{APPID_GUIDANCE}",
                code="config")
        self.market = market
        self.catalog = catalog or load()
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_limit = max_limit
        self.retries = max(0, int(retries))
        self.backoff = backoff
        self._validate = validate  # False=关闭单位量级/不变量校验（换算仍执行）
        self._sleep = time.sleep  # 测试注入点：不真实等待
        self._token: str = ""
        self._token_exp: float = 0.0

    # ---- 凭证 ----
    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **kw: Any) -> "Client":
        e = dict(os.environ if env is None else env)
        cred_file = Path(e.get("WMSHARE_CREDENTIALS", Path.home() / ".wmshare" / "credentials.env"))
        if cred_file.is_file():
            for line in cred_file.read_text(encoding="utf-8").splitlines():
                line = line.strip().removeprefix("export ").strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    e.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        base = e.get("WMSHARE_BASE_URL") or e.get("OPEN_PLATFORM_BASE_URL")
        cid = e.get("WMSHARE_CLIENT_ID") or e.get("OPEN_PLATFORM_CLIENT_ID")
        sec = e.get("WMSHARE_CLIENT_SECRET") or e.get("OPEN_PLATFORM_CLIENT_SECRET")
        # 环境变量只在显式参数缺省时注入；凭证成对性由 __init__ 校验（部分配置报错），
        # 全部缺省时 __init__ 报错并给出申请指引（SDK 不再内置体验 AppID）
        if base:
            kw.setdefault("base_url", base)
        if cid:
            kw.setdefault("client_id", cid)
        if sec:
            kw.setdefault("client_secret", sec)
        return cls(**kw)

    # ---- 传输 ----
    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def _delay(self, attempt: int, resp: requests.Response | None) -> float:
        """退避秒数：优先 Retry-After，其次指数退避（封顶 10s）。"""
        if resp is not None:
            ra = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
            if ra:
                try:
                    return min(10.0, max(0.0, float(ra)))
                except (TypeError, ValueError):
                    pass
        return min(10.0, self.backoff * (2 ** attempt))

    def _request(self, url: str, **kw: Any) -> requests.Response:
        """POST + 429/5xx 指数退避重试；网络异常同样重试并在耗尽后转 WmshareError。"""
        attempts = self.retries + 1
        last: requests.Response | None = None
        for i in range(attempts):
            try:
                resp = self.session.post(url, **kw)
            except requests.RequestException as e:
                if i == attempts - 1:
                    raise TransportError(
                        f"网络请求失败（已重试 {self.retries} 次）：{e}。"
                        "请检查网络连接与代理设置（国内直连不稳定时可配置 HTTPS_PROXY）。",
                        code="network") from e
                self._sleep(self._delay(i, None))
                continue
            last = resp
            if resp.status_code in self.RETRY_STATUS and i < attempts - 1:
                self._sleep(self._delay(i, resp))
                continue
            return resp
        assert last is not None  # 循环必然 return 或 raise
        return last

    @staticmethod
    def _error_detail(resp: requests.Response) -> tuple[str, str]:
        """从错误响应中尽力提取服务端 code/message（OAuth 与网关两种格式）。"""
        try:
            doc = resp.json()
        except ValueError:
            return "", (resp.text or "")[:300]
        if not isinstance(doc, dict):
            return "", (resp.text or "")[:300]
        err = doc.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or "")
            msg = str(err.get("message") or err.get("error_description") or "")
            if code or msg:
                return code, msg
        # OAuth 规范风格：{"error": "invalid_client", "error_description": "..."}
        if isinstance(err, str):
            return err, str(doc.get("error_description") or doc.get("message") or "")
        return "", (resp.text or "")[:300]

    def _raise_http_error(self, resp: requests.Response, *, stage: str) -> NoReturn:
        """把 OAuth/eval 的非 200 响应统一映射为 WmshareError，并附 AppID 引导。"""
        status = resp.status_code
        code, detail = self._error_detail(resp)
        label = f"HTTP {status}" + (f"，{code}" if code else "")
        suffix = f"：{detail}" if detail else ""
        if status == 429:
            retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
            wait = f"（建议 {retry_after} 秒后重试）" if retry_after else ""
            raise LimitError(
                f"请求被限流（{label}）{wait}{suffix}。请稍后重试，或申请自己的 AppID 提升额度。"
                f"{APPID_GUIDANCE}",
                code="rate_limited", status=status)
        if stage == "oauth" and status in (400, 401, 403):
            raise AuthError(
                f"OAuth 认证失败（{label}）{suffix}。"
                f"当前 client_id/client_secret 无效。"
                f"{APPID_GUIDANCE}",
                code=code or "oauth_denied", status=status)
        if status in (401, 403):
            if status == 403 and (code == "POLICY_DENIED" or "策略拒绝" in (detail or "")):
                raise AuthError(
                    f"服务端策略拒绝该调用（{label}）{suffix}。"
                    f"这是 AppID 的接口权限范围限制，与额度/凭证无关，换 AppID 不解决，"
                    f"勿反复重试：请到 open.winmale.com 开放平台检查应用权限，"
                    f"或改用无此权限要求的其他接口。",
                    code=code or "policy_denied", status=status)
            raise AuthError(
                f"认证或权限被拒绝（{label}）{suffix}。"
                f"请检查凭证配置；如未申请，按上方指引注册开放平台领取。"
                f"{APPID_GUIDANCE}",
                code=code or "denied", status=status)
        if status >= 500:
            raise ServerError(
                f"服务端错误（HTTP {status}）{suffix}。已自动重试仍失败，请稍后重试；"
                "若持续出现请携带时间与请求名到项目 issues 反馈。",
                code=code or "server", status=status)
        raise ApiError(f"HTTP {status}{suffix}", code=code or "http", status=status)

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        resp = self._request(
            f"{self.base_url}/v1/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            self._raise_http_error(resp, stage="oauth")
        try:
            doc = resp.json()
        except ValueError as e:
            raise ApiError(
                f"OAuth 响应不是合法 JSON（HTTP {resp.status_code}）：{resp.text[:200]}",
                code="oauth_response", status=resp.status_code) from e
        if not isinstance(doc, dict):
            raise ApiError(f"OAuth 响应格式异常：{json.dumps(doc, ensure_ascii=False)[:300]}",
                           code="oauth_response", status=resp.status_code)
        data = doc.get("data") or doc
        if not isinstance(data, dict):
            data = {}
        token = data.get("access_token")
        if not token:
            raise AuthError(
                f"OAuth 未返回 access_token：{json.dumps(doc, ensure_ascii=False)[:300]}。"
                f"{APPID_GUIDANCE}",
                code="oauth", status=resp.status_code)
        self._token = token
        self._token_exp = time.time() + float(data.get("expires_in", 3600))
        return token

    def _post_authed(self, path: str, body: dict[str, Any]) -> requests.Response:
        """带 OAuth Bearer 的 POST；401 清令牌刷新后重试一次（仅一次，避免环路）。"""
        url = f"{self.base_url}{path}"

        def call_once() -> requests.Response:
            return self._request(url, json=body, timeout=self.timeout,
                                 headers={"Authorization": f"Bearer {self._get_token()}"})

        resp = call_once()
        if resp.status_code == 401:
            # 令牌可能已失效：清缓存强制刷新后重试一次（仅一次，避免环路）
            self._token = ""
            self._token_exp = 0.0
            resp = call_once()
        return resp

    # ---- eval ----
    def eval(self, xs: str | list[str], *, symbol: str | None = None,
             args: dict | None = None, market: str | None = None,
             mode: str = "call") -> dict:
        """执行 XS，返回完整响应 doc（成功时 data.result 为顶层 return 值）。

        symbol 为求值锚点代码；None 时按客户端市场取默认锚点
        （cn=600519 / hk=00700 / us=AAPL，防 MARKET_MISMATCH）。
        """
        lines = xs if isinstance(xs, list) else [ln for ln in xs.splitlines() if ln.strip()]
        mk = str(market or self.market or "cn").lower()
        anchor = normalize_symbol(symbol, market=mk, catalog=self.catalog) \
            if symbol is not None else DEFAULT_SYMBOLS.get(mk, "600519")
        body: dict[str, Any] = {
            "symbol": anchor,
            "xs_lines": lines,
            "args": {"print.plain": True, **(args or {})},
            "script_files": {},
            "mode": mode,
        }
        if market := (market or self.market):
            body["market"] = market
        resp = self._post_authed("/v1/analysis/xs/eval", body)
        if resp.status_code != 200:
            self._raise_http_error(resp, stage="eval")
        try:
            doc = resp.json()
        except ValueError as e:
            raise ApiError(
                f"eval 响应不是合法 JSON（HTTP {resp.status_code}）：{resp.text[:200]}",
                code="response", status=resp.status_code) from e
        if not isinstance(doc, dict):
            raise ApiError(f"eval 响应格式异常：{json.dumps(doc, ensure_ascii=False)[:300]}",
                           code="response", status=resp.status_code)
        if not doc.get("success", True):
            err = doc.get("error") or {}
            code = str(err.get("code") or "eval")
            message = str(err.get("message") or json.dumps(doc, ensure_ascii=False)[:200])
            if "RATE" in code.upper() or "QUOTA" in code.upper():
                raise LimitError(
                    f"eval 失败：{code} {message}。"
                    f"请稍后重试，或申请自己的 AppID 提升额度。"
                    f"{APPID_GUIDANCE}", code=code, status=resp.status_code)
            raise ApiError(f"eval 失败: {code} {message}", code=code,
                           status=resp.status_code)
        return doc

    def eval_result(self, xs: str | list[str], **kw: Any) -> Any:
        doc = self.eval(xs, **kw)
        data = doc.get("data") or {}
        return data.get("result")

    # ---- 目录驱动的调用门面 ----
    def _canon_symbol(self, symbol: str) -> str:
        """标的代码归一：按客户端市场消解美股交易所后缀与类别股写法（见 normalize_symbol）。"""
        return normalize_symbol(symbol, market=self.market, catalog=self.catalog)

    def _resolve_function(self, name: str) -> dict:
        """目录函数查找；把「指标码当函数名」误用补成可执行的指引。"""
        try:
            return self.catalog.function(name)
        except CatalogError as e:
            if name.split(".", 1)[0] == "indicator":
                raise CatalogError(
                    f"{e}\n提示：调用入口只接受目录函数名（cat.functions_by_domain() 可查）；"
                    "指标码不是函数名——一票多码用 cli.indicator.metrics(sym, codes)，"
                    "全市场指标请逐票调用。", code="function") from e
            raise

    def _require_lines(self, name: str) -> list[str]:
        """函数命名空间不在 sys/init 预载链时，自动补 xs.require（幂等）。"""
        ns = name.split(".", 1)[0]
        inv = self.catalog.inventory
        if ns in (inv.get("preloaded_libs") or []):
            return []
        entry = (inv.get("domains") or {}).get(ns, {}).get("entry")
        return [f'xs.require("{entry}")'] if entry else []

    # 标的参数自动归一；stock_code 用于 notice.query_find 等底层函数。
    # 批量识别只用 BATCH_SYMBOL_PARAMS，避免把 stock_code 误当成可批量首个参数。
    SYMBOL_PARAMS = ("sym", "symbol", "stk", "stock_code")
    BATCH_SYMBOL_PARAMS = ("sym", "symbol", "stk")

    def _build_call_line(self, name: str, params: list[dict], kwargs: dict[str, Any],
                         *, sym_override: str | None = None,
                         sym_param: str | None = None) -> str:
        """校验参数并生成单次调用字面量（含标的一体化归一）。"""
        def _validate(p: dict, value: Any) -> None:
            kind = p.get("type", "any")
            valid = True
            if kind == "string":
                valid = isinstance(value, str)
            elif kind == "int":
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif kind == "float":
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(float(value)))
            elif kind == "bool":
                valid = isinstance(value, bool)
            elif kind == "array":
                valid = isinstance(value, (list, tuple))
            elif kind == "object":
                valid = isinstance(value, dict)
            if not valid:
                raise UsageError(
                    f"{name}: 参数 {p['name']} 需要 {kind}，收到 {type(value).__name__}",
                    code="params")
            allowed = p.get("enum")
            if allowed is not None and value not in allowed:
                raise UsageError(
                    f"{name}: 参数 {p['name']}={value!r} 不在允许值 {allowed} 内",
                    code="params")

        known = {p["name"] for p in params}
        unknown = set(kwargs) - known
        if unknown:
            raise UsageError(f"{name}: 未知参数 {sorted(unknown)}；合法参数 {sorted(known)}",
                             code="params")
        for p in params:
            provided = p["name"] in kwargs or (sym_override is not None and p["name"] == sym_param)
            if p["name"] in kwargs:
                _validate(p, kwargs[p["name"]])
            if not provided and "default" not in p and p.get("required"):
                raise UsageError(f"{name}: 缺少必填参数 {p['name']}", code="params")
        if self.max_limit is not None:
            for p in params:
                if p["name"] in ("limit", "lim") and p["type"] == "int":
                    v = kwargs.get(p["name"], p.get("default"))
                    if isinstance(v, int) and not isinstance(v, bool) and v > self.max_limit:
                        raise LimitError(
                            f"{name}: {p['name']}={v} 超过单次请求上限 {self.max_limit}"
                            "（防止单次拉取过大；可在 Client(max_limit=...) 调整，设 None 关闭）",
                            code="limit")
        def _provided(p: dict) -> bool:
            return p["name"] in kwargs or (sym_override is not None and p["name"] == sym_param)

        last_provided = max((i for i, p in enumerate(params) if _provided(p)), default=-1)
        args = []
        for i, p in enumerate(params):
            if sym_override is not None and p["name"] == sym_param:
                args.append(_xs_literal(self._canon_symbol(sym_override)))
            elif p["name"] in kwargs:
                v = kwargs[p["name"]]
                if p.get("type") == "string" and p["name"] in self.SYMBOL_PARAMS:
                    v = self._canon_symbol(v)
                args.append(_xs_literal(v))
            elif "default" in p:
                args.append(_xs_literal(p["default"]))
            elif i < last_provided:
                # 中段未传且无目录 default：补 nil 保位。调用字面量按位置绑定，
                # 跳过中段参数会把后值错绑到前槽（曾把 payout_max 绑进 payout_min）。
                args.append("nil")
        return f"{name}({', '.join(args)})"

    def call(self, name: str, /, _raw: bool = False, _df: bool = False,
             _units: str = "base", **kwargs: Any) -> Any:
        """按目录合同调用目录内函数：校验参数 → 生成 XS（自动 require + 规范化）→ eval(call)。

        选项以下划线开头，避免与 XS 参数名（如 etf_build 的 raw）冲突：
          _raw=True        跳过 normalize_with 与单位换算，返回 store 原始 Unit
          _units="native"  保留脚本输出的原有单位（字段名仍规范化）；默认 "base" 把
                           目录声明的非基础单位换算为小数/元/股，并做量级与不变量校验
          _df=True         结果为 list[dict] 时转 pandas.DataFrame（需安装 pandas）
        参数合同：优先用域目录精修 params；L1 精简条目回退到 inventory 的签名参数。
        标的参数（sym/symbol/stk）自动归一：去 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀。
        """
        if _units not in ("base", "native"):
            raise UsageError('_units 只支持 "base"（默认，换算基础单位）或 "native"（脚本原值）',
                             code="units")
        fn = self._resolve_function(name)
        params = fn.get("params") or self.catalog.inventory_params(name)
        # 传列表即批量：标的参数收到 list/tuple 自动转 call_batch
        # （≤500，超限 LimitError；语义与显式 call_batch 一致）。
        for p in params:
            v = kwargs.get(p["name"])
            if (p.get("type") == "string" and p["name"] in self.BATCH_SYMBOL_PARAMS
                    and isinstance(v, (list, tuple))):
                rest = {k: w for k, w in kwargs.items() if k != p["name"]}
                return self.call_batch(name, list(v), _raw=_raw, _df=_df,
                                       _units=_units, **rest)
        call_line = self._build_call_line(name, params, kwargs)
        normalizer = fn.get("normalize_with")
        if normalizer and not _raw:
            lines = [f"__r := {call_line}", f"return {normalizer}(__r)"]
        else:
            lines = [f"return {call_line}"]
        xs = self._require_lines(name) + lines
        symbol = DEFAULT_SYMBOLS.get(str(self.market or "cn").lower(), "600519")
        for p in params:
            if p["name"] in kwargs and p["type"] == "string" and p["name"] in self.SYMBOL_PARAMS:
                symbol = self._canon_symbol(str(kwargs[p["name"]]))
                break
        result = self.eval_result(xs, symbol=symbol)
        if not _raw and _units == "base":
            result = apply_units(result, fn, fname=name, validate=self._validate,
                                 market=self.market)
        return _to_dataframe(result) if _df else result

    def call_batch(self, name: str, symbols: list[str], /, on_error: str = "raise",
                   _raw: bool = False, _df: bool = False, _units: str = "base",
                   **kwargs: Any) -> BatchResult:
        """同一目录函数在多个标的上的批量调用。

        on_error="raise"（默认）：把所有标的组装成**一次** eval（map 字面量），单次 HTTP；
        任一标的失败则整体抛出（服务端无 try/catch，无法在单次请求内隔离）。
        on_error="skip"：逐标的调用并捕获错误，成功项进 results、失败项进 errors（N 次 HTTP）。
        _raw/_df/_units 语义与 call() 一致（_units="native" 时跳过单条 HTTP 路径的单位换算）。
        """
        if on_error not in ("raise", "skip"):
            raise UsageError('on_error 只支持 "raise" 或 "skip"', code="params")
        if _units not in ("base", "native"):
            raise UsageError('_units 只支持 "base"（默认，换算基础单位）或 "native"（脚本原值）',
                             code="units")
        fn = self._resolve_function(name)
        params = fn.get("params") or self.catalog.inventory_params(name)
        sym_param = next((p["name"] for p in params
                          if p.get("type") == "string" and p["name"] in self.BATCH_SYMBOL_PARAMS), None)
        if sym_param is None:
            raise UsageError(f"{name}: 没有标的参数（sym/symbol/stk），不支持批量调用",
                             code="params")
        if sym_param in kwargs:
            raise UsageError(f"{name}: 批量调用请用 symbols 指定标的，不要在 kwargs 传 {sym_param}",
                             code="params")
        syms = list(dict.fromkeys(self._canon_symbol(s) for s in symbols))
        if not syms:
            return BatchResult()
        self._assert_same_market(name, syms)
        if self.max_limit is not None and len(syms) > self.max_limit:
            raise LimitError(
                f"{name}: 批量标的数 {len(syms)} 超过上限 {self.max_limit}"
                f"（请分批，如 codes[i:i+{self.max_limit}]；"
                "或直接用 batch_all() 自动分批、batch_iter() 逐批处理）",
                code="limit")
        if on_error == "skip":
            results: dict[str, Any] = {}
            errors: dict[str, str] = {}
            for s in syms:
                try:
                    results[s] = self.call(name, _raw=_raw, _df=_df, _units=_units,
                                           **kwargs, **{sym_param: s})
                except WmshareError as e:
                    errors[s] = str(e)
            # skip 模式逐票请求：N 个标的 = N 次请求（会快速耗尽限流额度）
            return BatchResult(results=results, errors=errors, requests=len(syms))

        normalizer = fn.get("normalize_with")
        pairs = []
        for s in syms:
            line = self._build_call_line(name, params, kwargs, sym_override=s, sym_param=sym_param)
            pairs.append(f'{_xs_literal(s)}: {normalizer}({line})' if normalizer and not _raw
                         else f"{_xs_literal(s)}: {line}")
        xs = self._require_lines(name) + [f"return {{{', '.join(pairs)}}}"]
        result = self.eval_result(xs, symbol=syms[0])
        if not isinstance(result, dict):
            raise ApiError(f"{name}: 批量返回不是 MAP（{type(result).__name__}）", code="batch")
        if not _raw and _units == "base":
            for s, v in result.items():
                result[s] = apply_units(v, fn, fname=name, validate=self._validate,
                                        market=self.market)
        if _df:
            result = {k: _to_dataframe(v) for k, v in result.items()}
        # raise 模式把 N 个标的压进一次 eval：1 次请求
        return BatchResult(results=result, requests=1)

    # ---- 分批执行器（批量绕开 429 的正式入口） ----
    def _assert_same_market(self, name: str, syms: list[str]) -> None:
        """批量代码必须同属客户端市场——跨市场混批会取到错误数据。

        实测（2026-10-29）：cn 客户端批量混入 00700 不报错，但该港股标的的 close/percent
        与 hk 客户端结果不符（387.6 vs 377.6、+0.62% vs -2.58%，连涨跌方向都相反）——
        网关只校验请求锚点（xs_eval_target.go 的 checkMarketMatch），xs_lines 内代码
        不校验，本市场引擎上下文解析他市场符号会走错数据管线。

        仅当代码出现在**其他市场代码表**时报错；代码表里都没有（新股/ETF）放行，
        不误伤。常规同市场批量只加载本市场代码表（毫秒级、带缓存）。
        """
        mk = str(self.market or "cn").lower()
        if mk not in ("cn", "hk", "us"):
            return
        try:
            own = self.catalog.symbols_set(mk)
        except CatalogError:
            return
        missing = [s for s in syms if s not in own]
        if not missing:
            return
        foreign: list[tuple[str, str]] = []
        for om in ("cn", "hk", "us"):
            if om == mk:
                continue
            try:
                other = self.catalog.symbols_set(om)
            except CatalogError:
                continue
            foreign.extend((x, om) for x in missing if x in other)
        if not foreign:
            return
        langs = {"cn": "A 股", "hk": "港股", "us": "美股"}
        sample = "、".join(f"{c}（{langs[m]}）" for c, m in foreign[:5])
        extra = f" 等 {len(foreign)} 个" if len(foreign) > 5 else ""
        raise UsageError(
            f"{name}: 代码 {sample}{extra} 不属于当前市场（Client market={mk}）。"
            "批量不支持跨市场混批——网关只校验请求锚点，他市场代码会在本市场引擎上下文"
            "里走错数据管线，返回的 close/涨跌幅等数值不可信。"
            f"请按市场分别调用 Client(market=\"cn\"/\"hk\"/\"us\")："
            "A 股全市场 12 批 + 港股 6 批 + 美股 11 批 = 29 次请求。",
            code="market")

    def _batch_size(self, batch_size: int | None, name: str) -> int:
        size = int(batch_size) if batch_size is not None else (self.max_limit or 500)
        if size <= 0:
            raise UsageError(f"{name}: batch_size 必须为正整数，收到 {size}", code="params")
        if self.max_limit is not None and size > self.max_limit:
            raise UsageError(
                f"{name}: batch_size={size} 超过单批上限 {self.max_limit}"
                f"（单批最大 {self.max_limit} 个标的；可调 Client(max_limit=...)）",
                code="params")
        return size

    def batch_iter(self, name: str, symbols: Any, /, batch_size: int | None = None,
                   on_batch_error: str = "raise", _raw: bool = False,
                   _units: str = "base", **kwargs: Any) -> Iterator[BatchResult]:
        """分批执行器（逐批产出）：N 个标的切成 ⌈N/batch_size⌉ 批，每批一次 HTTP。

        解决 429 的正解——服务端按**请求次数**限流（免费档 500 次/小时、
        5000 次/日），逐票取全市场（A 股 5691 家）必然撞墙；分批后只需 12 次请求。
        逐批 yield 便于边取边落盘、显示进度、随时中断（``break`` 即可）。

        :param name: 目录函数名（如 ``"kline.snapshot"``），**位置参数**
        :param symbols: 标的代码序列，**位置参数**（如 ``[r["symbol"] for r in cli.stocks.list()]``）。
            必须同属 ``Client(market=...)`` 的市场——跨市场混批会报 ``UsageError``
            （他市场代码在本市场引擎上下文里会取到错误数值）；跨市场请分别建 Client。
        :param batch_size: 每批标的数，默认 ``Client(max_limit=500)``；须 ≤ max_limit
        :param on_batch_error: **批级**容错（与 ``call_batch`` 的票级 ``on_error`` 不同）：
            ``"raise"``（默认）任一批失败即抛；``"skip"`` 跳过失败批继续
            （失败批记进 ``errors``，键形如 ``batch#3[1000:1500]``）。
        :param _raw: 跳过规范化与单位换算，返回上游原始行
        :param _units: ``"base"``（默认，换算基础单位并校验）/ ``"native"``（脚本原值）
        :returns: 逐批 ``BatchResult``（``requests`` 恒为 1）

        限流（HTTP 429）在任何模式下都**停止并给出续跑位置**（消息含已完成标的数与
        ``codes[done:]`` 切片）——配额是时间窗口，继续跑只会连续失败。
        参数错误在**调用时**立即抛出（不等待首次迭代）。
        """
        if on_batch_error not in ("raise", "skip"):
            raise UsageError('on_batch_error 只支持 "raise" 或 "skip"', code="params")
        if "_df" in kwargs:
            raise UsageError(
                f"{name}: 批量入口不支持 _df——它会让每标的值变成 DataFrame，"
                "聚合后 to_df() 长表失真。长表请用 BatchResult.to_df()（每标的一行），"
                "单标的多行结果读 BatchResult.results[代码]。", code="params")
        size = self._batch_size(batch_size, name)
        syms = list(dict.fromkeys(self._canon_symbol(s) for s in symbols))
        self._assert_same_market(name, syms)
        return self._batch_iter(name, syms, size, on_batch_error,
                                _raw=_raw, _units=_units, **kwargs)

    def _batch_iter(self, name: str, syms: list[str], size: int,
                    on_batch_error: str, *, _raw: bool = False,
                    _units: str = "base", **kwargs: Any) -> Iterator[BatchResult]:
        """batch_iter 的生成器实体（参数已在外壳校验，错误早暴露）。"""
        if not syms:
            return
        total = (len(syms) + size - 1) // size
        for idx, chunk in enumerate(_chunked(syms, size), start=1):
            start = (idx - 1) * size
            try:
                # 批内必须是 raise 模式：整批压进一次请求
                yield self.call_batch(name, chunk, on_error="raise",
                                      _raw=_raw, _units=_units, **kwargs)
            except LimitError as e:
                if getattr(e, "code", "") == "rate_limited" or getattr(e, "status", None) == 429:
                    raise LimitError(
                        f"{name}: 第 {idx}/{total} 批触发限流（已完成 {start} / {len(syms)} 个标的）。"
                        "服务端按请求次数限流（免费档 500 次/小时、5000 次/日）；"
                        f"请稍后续跑：batch_all({name!r}, codes[{start}:])；"
                        "或调大 batch_size 减少请求次数、申请更高档位。"
                        f"原始错误：{e}", code="rate_limited", status=429) from e
                raise
            except WmshareError as e:
                if on_batch_error == "skip":
                    key = f"batch#{idx}[{start}:{start + len(chunk)}]"
                    yield BatchResult(errors={key: str(e)}, requests=1)
                    continue
                raise

    def batch_all(self, name: str, symbols: Any, /, batch_size: int | None = None,
                  on_batch_error: str = "raise", _raw: bool = False,
                  _units: str = "base", **kwargs: Any) -> BatchResult:
        """一站式分批取数：自动切片并聚合为单个 ``BatchResult``。

        ``cli.batch_all("kline.snapshot", [r["symbol"] for r in cli.stocks.list()])``
        → A 股 5691 家只花 12 次请求（而非 5691 次），一次跑完不撞限流。

        :param name: 目录函数名，**位置参数**
        :param symbols: 标的代码序列，**位置参数**（须同属客户端市场，跨市场混批报错）
        :param batch_size: 每批标的数，默认 ``Client(max_limit=500)``
        :param on_batch_error: **批级**容错（``"skip"`` 跳过失败批），与 ``batch_iter`` 一致
        :param _raw: 跳过规范化与单位换算
        :param _units: ``"base"``（默认）/ ``"native"``
        :returns: ``BatchResult``——``results`` 聚合全部批次、``errors`` 含失败批、
            ``requests`` 为实际请求次数（可直接对比标的数看省了多少次配额）

        长表用 ``.to_df()``（每标的一行）；多行历史类数据（``bars``/``history``）
        建议改用 ``batch_iter`` 边取边落盘，或读 ``results[代码]``。
        """
        out = BatchResult()
        for part in self.batch_iter(name, symbols, batch_size=batch_size,
                                    on_batch_error=on_batch_error, _raw=_raw,
                                    _units=_units, **kwargs):
            out.results.update(part.results)
            out.errors.update(part.errors)
            out.requests += part.requests
        return out

    def notice_poller(self, *, group: str, consumer: str, on_events: Any = None,
                      **kw: Any) -> "NoticePoller":
        """公告变更订阅轮询器：本地定时器轮询探针，有新公告才拉取、回调、确认。

        消费进度按 (group, consumer) 标识存在服务端，ack 前崩溃会重投
        （at-least-once）。详见 ``wmshare.notice_stream.NoticePoller``。
        """
        from wmshare.notice_stream import NoticePoller
        return NoticePoller(self, group=group, consumer=consumer,
                            on_events=on_events, **kw)

    # ---- 生命周期 ----
    def close(self) -> None:
        """关闭底层 HTTP 会话；调用方注入的 session 由调用方自行管理。"""
        if not self._owns_session:
            return
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __dir__(self) -> list[str]:
        """IDE 补全/交互式探索可见全部命名空间：友好门面 + 类型化门面 + 底层目录。"""
        from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
        return sorted({*super().__dir__(), *FRIENDLY_NAMESPACES,
                       *GENERATED_NAMESPACES, *self.catalog.namespaces()})

    def __getattr__(self, ns: str) -> Any:
        """client.bonus.query_list(...) —— 友好 API 优先，其次类型化门面，最后通用门面。"""
        if ns.startswith("_"):
            raise AttributeError(ns)
        from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
        cls = FRIENDLY_NAMESPACES.get(ns)
        if cls is not None:
            return cls(self)
        gcls = GENERATED_NAMESPACES.get(ns)
        if gcls is not None:
            return gcls(self)
        if ns not in self.catalog.namespaces():
            raise AttributeError(
                f"命名空间 {ns!r} 不在目录中；可用友好入口 "
                f"{sorted(FRIENDLY_NAMESPACES)} 或底层命名空间 {sorted(self.catalog.namespaces())}")
        return _Namespace(self, ns)


class _Namespace:
    def __init__(self, client: Client, ns: str):
        self._client = client
        self._ns = ns

    def __getattr__(self, fname: str) -> Any:
        if fname.startswith("_"):
            raise AttributeError(fname)
        return lambda **kw: self._client.call(f"{self._ns}.{fname}", **kw)
