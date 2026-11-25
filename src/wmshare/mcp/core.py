"""Tool implementations.  Protocol serialization lives in ``server.py``."""

from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import wmshare
from wmshare._credentials import read_credentials_file
from wmshare.client import BatchResult, Client
from wmshare.errors import (
    AuthError,
    CatalogError,
    LimitError,
    UsageError,
    WmshareError,
)
from wmshare.mcp.constants import (
    COMPANY_BLOCKS,
    CONSOLE_URL,
    CREDENTIAL_PATH,
    DEFAULT_MARKET,
    DOCS_URL,
    MARKETS,
    MAX_ROWS,
    SOURCE,
)


@dataclass
class MCPRuntime:
    """Process-local runtime.  Clients are created lazily and reused."""

    market: str = DEFAULT_MARKET
    # 单次 MCP 调用的 EC 事后上限。不是 LLM 可传参数，只能由部署方通过
    # WMSHARE_MCP_MAX_EC 收紧/放宽；超限时抛 LimitError(code="ec_budget")。
    max_ec_per_call: int = 200_000
    _clients: dict[str, Client | Any] | None = None

    def __post_init__(self) -> None:
        self.market = _market(self.market)
        raw = os.getenv("WMSHARE_MCP_MAX_EC", "").strip()
        if raw:
            try:
                self.max_ec_per_call = max(1, int(raw))
            except ValueError:
                pass  # 非法配置沿用默认值，不因环境变量让 MCP 起不来
        self._clients = {}

    def client(self, market: str | None = None) -> Client | Any:
        market = _market(market or self.market)
        assert self._clients is not None
        if market not in self._clients:
            client = Client.from_env(market=market)
            headers = getattr(client.session, "headers", None)
            if headers is not None:
                headers["User-Agent"] = f"wmshare-mcp/{wmshare.__version__}"
                headers["X-WM-Client"] = f"wmshare-mcp/{wmshare.__version__}"
            self._clients[market] = client
        return self._clients[market]


def _market(value: str | None) -> str:
    market = str(value or DEFAULT_MARKET).strip().lower()
    if market not in MARKETS:
        raise ValueError(f"market 只支持 cn/hk/us，收到 {market!r}")
    return market


def _links() -> dict[str, str]:
    return {"console": CONSOLE_URL, "docs": DOCS_URL}


def _provenance(runtime: MCPRuntime | None) -> dict[str, Any]:
    """返回溯源信息，让调用方知道数据是什么时候取的。"""
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_freshness": ("unknown" if runtime is None else "live"),
    }


def _meta(
    runtime: MCPRuntime,
    *,
    units: str = "base",
    row_count: int = 0,
    rows_total: int = 0,
    truncated: bool = False,
    next_action: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "market": runtime.market,
        "source": SOURCE,
        "units": units,
        "row_count": row_count,
        "rows_total": rows_total,
        "truncated": truncated,
        "next_action": next_action,
    }
    out.update(_provenance(runtime))
    out.update(extra)
    # 守护关闭必须在信封里可见：raw=True 跳过规范化与单位换算，units=native
    # 保留脚本原值。LLM 不能把这类诊断结果当已守护数据做数值结论。
    # 只在关闭时新增键，正常路径的信封保持字节级兼容。
    if bool(out.get("raw", False)) or out.get("units") == "native":
        out["guards_off"] = True
        out["guard_note"] = (
            "raw=True / units=native 已关闭 SDK 单位换算与量级、不变量校验；"
            "结果仅供口径诊断，禁止直接用于数值结论或跨单位比较"
        )
    return out


def success(
    runtime: MCPRuntime,
    data: Any,
    *,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
    **meta: Any,
) -> dict[str, Any]:
    output = _output(output)
    max_rows = _max_rows(max_rows)
    tail = _time_series_tail(data)
    tail_keys = _tail_keys(data)
    data = _plain(data)
    rows_total = _row_count(data)
    shown: Any = data
    truncated = False
    if output == "count":
        shown = None
    elif output == "summary":
        shown = _summary(data)
    elif isinstance(data, list) and len(data) > max_rows:
        shown = data[-max_rows:] if tail else data[:max_rows]
        truncated = True
        meta.setdefault(
            "next_action",
            (f"时间序列仅保留最近 {max_rows} 行；缩小查询区间或改用 output=summary/count"
             if tail else
             f"提高 max_rows（<= {MAX_ROWS}）、缩小筛选范围，或改用 output=summary/count"),
        )
    elif isinstance(data, dict):
        shown, dict_truncated = _limit_tree(data, max_rows, tail_keys)
        truncated = dict_truncated
        if truncated:
            meta.setdefault(
                "next_action",
                "结果包含超限的嵌套列表；缩小 include/查询范围，或改用 output=summary/count",
            )
    row_count = rows_total if output == "count" else _row_count(shown)
    return {
        "ok": True,
        "data": shown,
        "meta": _meta(runtime, row_count=row_count, rows_total=rows_total,
                      truncated=truncated, **meta),
        "links": _links(),
    }


def error(exc: Exception, runtime: MCPRuntime | None = None) -> dict[str, Any]:
    """错误信封同样带溯源标记；runtime 缺省可空，兼容所有旧调用点。"""
    kind = type(exc).__name__
    code = str(getattr(exc, "code", "") or kind.lower())
    message = str(exc)
    fix: list[str] = []
    if isinstance(exc, AuthError):
        kind = "AuthError"
        code = "credential_required" if "缺少凭证" in message else (code or "auth")
        fix = [
            f"打开 {_links()['console']} 获取 AppId/client_id 与 API Key/client_secret",
            "运行 wmshare-mcp setup --client-id ... --client-secret-stdin --market cn",
            "或设置 WMSHARE_CLIENT_ID / WMSHARE_CLIENT_SECRET",
        ]
    elif isinstance(exc, LimitError):
        kind = "LimitError"
        code = code or "limit"
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            fix.append(f"等待约 {retry_after:g} 秒后重试")
        fix.extend(["多标的改用 wmshare_batch", "缩小日期区间或标的数"])
    elif isinstance(exc, CatalogError):
        kind = "CatalogError"
        code = code or "catalog"
        fix = ["先调用 wmshare_search，再用 wmshare_contract 查参数"]
    elif isinstance(exc, UsageError):
        kind = "UsageError"
        code = code or "params"
        fix = ["参数不合法：用 wmshare_contract 查看参数合同后修正"]
    elif isinstance(exc, ValueError):
        kind = "UsageError"
        code = "params"
        fix = ["参数不合法：检查枚举值、日期/区间和行数限制"]
        if getattr(exc, "code", "") == "gateway_policy":
            code = "gateway_policy"
            fix = ["MCP 网关不开放该路由；改用本地 Python SDK 直接调用，"
                   "并在你自己的环境中控制输出路径"]
    elif isinstance(exc, WmshareError):
        fix = ["按 message 修正参数；参数合同用 wmshare_contract 查询"]
        if type(exc).__name__ == "DataError":
            fix = ["不要吞掉 DataError：先核对单位/量级与指标口径，再决定是否换接口"]
    else:
        kind = "ToolError"
        code = code or "tool"
        fix = ["先用 wmshare_status 检查配置，再缩小请求范围重试"]
    return {
        "ok": False,
        "error": {"kind": kind, "code": code, "message": message, "fix": fix},
        "meta": {
            "source": SOURCE,
            "next_action": fix[0] if fix else None,
            **_provenance(runtime),
        },
        "links": _links(),
    }


def _output(value: str) -> str:
    if value not in ("sample", "count", "summary"):
        raise ValueError("output 只支持 sample/count/summary")
    return value


def _max_rows(value: int) -> int:
    if isinstance(value, bool) or not 1 <= int(value) <= MAX_ROWS:
        raise ValueError(f"max_rows 只支持 1~{MAX_ROWS}")
    return int(value)


def _plain(value: Any) -> Any:
    """把门面返回值收敛为 JSON 安全的行数组/标量。

    门面（``cli.ns.method``）2.0 起默认返回 pandas DataFrame；MCP 边界必须
    先转 records，否则 ``str(DataFrame)`` 会把截断后的 pandas 文本预览塞进
    ``data``（列被折断、row_count 误报 1、max_rows 失效）。
    """
    if isinstance(value, BatchResult):
        return flatten_batch(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # NaN/Inf 不是合法 JSON；pandas 缺失值在序列化层统一收敛为 null
        return value if math.isfinite(value) else None
    to_records = getattr(value, "to_dict", None)
    if callable(to_records):  # DataFrame → 行数组（Series 等非 records 形态走兜底）
        try:
            return _plain(to_records("records"))
        except (TypeError, ValueError):
            pass
    # pandas NA/NaT 既不是 float 也不能 JSON 序列化
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):  # datetime/date/Timestamp → ISO 字符串
        try:
            return isoformat()
        except (TypeError, ValueError):
            pass
    item = getattr(value, "item", None)  # numpy 标量 → 原生标量
    if callable(item) and not hasattr(value, "index"):
        try:
            return _plain(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _time_series_tail(value: Any) -> bool:
    """是否为升序时间序列 DataFrame（超限时保留最新行）。

    只认 ``date`` / ``sas`` 列且字符串升序；排名类 DataFrame（如龙虎榜）
    不含这两列，仍走头部截断。
    """
    to_records = getattr(value, "to_dict", None)
    columns = getattr(value, "columns", None)
    if not callable(to_records) or columns is None:
        return False
    names = {str(name) for name in columns}
    key = "date" if "date" in names else "sas" if "sas" in names else None
    if key is None:
        return False
    try:
        raw_values = value[key].tolist()
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    values: list[str] = []
    for item in raw_values:
        if item is None:
            continue
        token = str(item)
        # 缺失值在 str() 下会变成 "nan"/"NaT"/"None" 这类字面量；夹在中间会
        # 让排序判定失败，时间序列静默退回头部截断（保留最旧而非最新）。
        if token in {"nan", "NaT", "None", ""}:
            continue
        values.append(token)
    return bool(values) and values == sorted(values)


def _tail_keys(data: Any) -> dict[str, bool]:
    """顶层 dict/blocks 中值为时间序列 DataFrame 的键（须在 _plain 前判定）。"""
    if not isinstance(data, dict):
        return {}
    blocks = data.get("blocks")
    target = blocks if isinstance(blocks, dict) else data
    return {str(key): _time_series_tail(value) for key, value in target.items()}


def _row_count(data: Any) -> int:
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if data.get("blocks") and isinstance(data["blocks"], dict):
            return sum(_row_count(v) for v in data["blocks"].values())
        return 1
    return 1


def _summary(data: Any) -> dict[str, Any]:
    rows = data if isinstance(data, list) else None
    if rows is None and isinstance(data, dict):
        if data.get("blocks") and isinstance(data["blocks"], dict):
            return {
                "block_row_counts": {
                    name: _row_count(value) for name, value in data["blocks"].items()
                }
            }
        rows = data.get("rows") if isinstance(data.get("rows"), list) else None
    if rows is None:
        return {"row_count": _row_count(data)}
    numeric: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key == "symbol" or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                numeric.setdefault(str(key), []).append(float(value))
    return {
        "columns": sorted({k for row in rows if isinstance(row, dict) for k in row}),
        "numeric_stats": {
            key: {
                "count": len(values),
                "min": min(values),
                "median": statistics.median(values),
                "mean": statistics.fmean(values),
                "max": max(values),
            }
            for key, values in sorted(numeric.items())
        },
    }


def _limit_tree(data: Any, max_rows: int,
                tail_keys: dict[str, bool] | None = None,
                tail: bool = False) -> tuple[Any, bool]:
    """Apply the output cap to list values in dict/block payloads.

    ``tail_keys`` 标记顶层 dict/blocks 中的时间序列键：超限时保留尾部最新行；
    其余列表仍保留头部。更深层列表不追踪类型，维持原语义。
    """
    tail_keys = tail_keys or {}
    if isinstance(data, list) and len(data) > max_rows:
        return (data[-max_rows:] if tail else data[:max_rows]), True
    if isinstance(data, dict) and isinstance(data.get("blocks"), dict):
        blocks = data["blocks"]
        limited: dict[str, Any] = {}
        truncated = False
        for key, value in blocks.items():
            value, value_truncated = _limit_tree(
                value, max_rows, tail=tail_keys.get(str(key), False))
            limited[key] = value
            truncated = truncated or value_truncated
        # blocks 里只放块；其余顶层键（symbol 等）必须留在顶层。此前把 symbol
        # 塞进 blocks 会让 _row_count 把它当一行（wmshare_company 每次多报 1）、
        # _summary 的 block_row_counts 里出现伪块。
        rest = {key: value for key, value in data.items() if key != "blocks"}
        if rest:
            rest, rest_truncated = _limit_tree(rest, max_rows, tail_keys)
            truncated = truncated or rest_truncated
        payload: dict[str, Any] = dict(rest)
        payload["blocks"] = limited
        return payload, truncated
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        truncated = False
        for key, value in data.items():
            if isinstance(value, list) and len(value) > max_rows:
                out[key] = (value[-max_rows:] if tail_keys.get(str(key))
                            else value[:max_rows])
                truncated = True
            elif isinstance(value, dict):
                out[key], value_truncated = _limit_tree(value, max_rows)
                truncated = truncated or value_truncated
            else:
                out[key] = value
        return out, truncated
    return data, False


def flatten_batch(result: BatchResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, value in result.results.items():
        if isinstance(value, dict):
            rows.append({"symbol": symbol, **value})
        elif isinstance(value, list):
            rows.append({"symbol": symbol, "rows": value})
        else:
            rows.append({"symbol": symbol, "value": value})
    return rows


def batch_meta(result: BatchResult | None = None) -> dict[str, Any]:
    if result is None:
        return {}
    error_items = list(result.errors.items())
    detail_items = list(result.error_details.items())
    return {
        "requests": result.requests,
        "requested": result.requested,
        "error_count": len(result.errors),
        "errors_truncated": len(result.errors) > MAX_ROWS,
        "errors": dict(error_items[:MAX_ROWS]),
        "error_details_truncated": len(result.error_details) > MAX_ROWS,
        "error_details": [
            {
                "key": item.key,
                "message": item.message,
                "code": item.code,
                "status": item.status,
                "retryable": item.retryable,
            }
            for item in result.error_details.values()
        ][:MAX_ROWS],
    }


def credential_values() -> dict[str, str]:
    """Read exact SDK keys without exposing values; file values fill env gaps."""
    path = Path(os.getenv("WMSHARE_CREDENTIALS", CREDENTIAL_PATH)).expanduser()
    values = {
        "WMSHARE_CLIENT_ID": os.getenv("WMSHARE_CLIENT_ID")
        or os.getenv("OPEN_PLATFORM_CLIENT_ID") or "",
        "WMSHARE_CLIENT_SECRET": os.getenv("WMSHARE_CLIENT_SECRET")
        or os.getenv("OPEN_PLATFORM_CLIENT_SECRET") or "",
        "WMSHARE_MARKET": os.getenv("WMSHARE_MARKET") or "",
    }
    # 与 Client.from_env 共用解析 + 权限告警，避免两套实现各自漂移。
    file_values = read_credentials_file(path)
    for key in values:
        if not values[key] and file_values.get(key):
            values[key] = file_values[key]
    return values


def credential_status() -> dict[str, bool | str]:
    values = credential_values()
    cid = bool(values["WMSHARE_CLIENT_ID"])
    sec = bool(values["WMSHARE_CLIENT_SECRET"])
    market = values["WMSHARE_MARKET"] or DEFAULT_MARKET
    if market not in MARKETS:
        market = DEFAULT_MARKET
    path = Path(os.getenv("WMSHARE_CREDENTIALS", CREDENTIAL_PATH)).expanduser()
    return {
        "has_client_id": cid,
        "has_client_secret": sec,
        "configured": cid and sec,
        "credential_path": str(path),
        "market": market,
    }


def catalog_stats() -> dict[str, Any]:
    return wmshare.load().stats()
