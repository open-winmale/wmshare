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
    demo: bool = False
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
        if self.demo:
            return wmshare.demo_client()
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


def _demo_as_of() -> str | None:
    """演示快照的冻结日期；不 import 包以外依赖，失败时返回 None。"""
    try:
        from wmshare import _demo

        return getattr(_demo, "_AS_OF", None)
    except ImportError:  # pragma: no cover - 裁剪安装包场景
        return None


def _provenance(runtime: MCPRuntime | None) -> dict[str, Any]:
    """LLM 必须能区分「实时数据」与「罐头快照」，避免把 demo 当行情用。"""
    demo = runtime.demo if runtime is not None else None
    return {
        "demo": demo,
        "as_of": _demo_as_of() if demo else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_freshness": ("unknown" if runtime is None
                           else ("snapshot" if demo else "live")),
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
    data = _plain(data)
    rows_total = _row_count(data)
    shown: Any = data
    truncated = False
    if output == "count":
        shown = None
    elif output == "summary":
        shown = _summary(data)
    elif isinstance(data, list) and len(data) > max_rows:
        shown = data[:max_rows]
        truncated = True
        meta.setdefault(
            "next_action",
            f"提高 max_rows（<= {MAX_ROWS}）、缩小筛选范围，或改用 output=summary/count",
        )
    elif isinstance(data, dict):
        shown, dict_truncated = _limit_tree(data, max_rows)
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
    if isinstance(value, BatchResult):
        return flatten_batch(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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


def _limit_tree(data: Any, max_rows: int) -> tuple[Any, bool]:
    """Apply the output cap to list values in dict/block payloads."""
    if isinstance(data, list) and len(data) > max_rows:
        return data[:max_rows], True
    if isinstance(data, dict) and isinstance(data.get("blocks"), dict):
        limited: dict[str, Any] = {"symbol": data.get("symbol")}
        truncated = False
        for key, value in data["blocks"].items():
            value, value_truncated = _limit_tree(value, max_rows)
            limited[key] = value
            truncated = truncated or value_truncated
        return {"blocks": limited}, truncated
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        truncated = False
        for key, value in data.items():
            if isinstance(value, list) and len(value) > max_rows:
                out[key] = value[:max_rows]
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
