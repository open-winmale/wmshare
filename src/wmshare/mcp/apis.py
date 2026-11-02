"""Friendly-API route registry for the MCP generic gateway.

The registry is introspected from the SDK's stable ``FRIENDLY_NAMESPACES`` so the
catalog and MCP capability matrix cannot silently drift from the Python API.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from wmshare.api import FRIENDLY_NAMESPACES

_SYMBOL_NAMES = {"symbol", "sym", "stk", "code"}
_SPECIAL_CATALOG: dict[tuple[str, str], str | None] = {
    ("valuation", "hist_stats"): None,
    ("screener", "index_top_movers"): "kline.index_top_movers",
}


@dataclass(frozen=True)
class ApiRoute:
    """One invokable friendly-API method exposed through ``wmshare_call``."""

    target: str
    domain: str
    method: str
    description: str
    signature: str
    parameters: tuple[str, ...]
    example: str
    recommended_tool: str
    catalog_function: str | None
    supports_raw: bool
    supports_units: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "domain": self.domain,
            "method": self.method,
            "description": self.description,
            "signature": self.signature,
            "parameters": list(self.parameters),
            "example": self.example,
            "recommended_tool": self.recommended_tool,
            "catalog_function": self.catalog_function,
            "supports_raw": self.supports_raw,
            "supports_units": self.supports_units,
        }


def _is_route_method(owner: type, name: str, func: Callable[..., Any]) -> bool:
    if name.startswith("_"):
        return False
    # Exclude helpers inherited from the private facade base class.
    owner_func = inspect.getattr_static(owner, name, None)
    return owner_func is not None and inspect.isfunction(owner_func)


def _recommended_tool(domain: str, method: str) -> str:
    if domain == "kline":
        if method == "bars":
            return "wmshare_history"
        if method in {"last", "live", "snapshot", "batch_live"}:
            return "wmshare_quote"
        return "wmshare_market"
    if domain == "screener":
        return "wmshare_screen"
    if domain in {"moneyflow", "margin", "cbond", "index", "valuation"}:
        return "wmshare_market"
    if domain == "stocks":
        return "wmshare_market" if method == "list" else "wmshare_screen"
    if domain == "statements":
        return "wmshare_statement"
    if domain == "segments":
        return "wmshare_segments"
    if domain == "estimates":
        return "wmshare_estimates"
    if domain == "indicator":
        return "wmshare_metrics"
    if domain == "notice":
        return "wmshare_notice"
    if domain in {"filings", "workout"}:
        return "wmshare_disclosures"
    if domain == "forecast":
        return "wmshare_estimates"
    if domain == "dividend":
        return "wmshare_dividend"
    if domain == "info":
        return "wmshare_company"
    if domain == "equity":
        return "wmshare_corporate"
    if domain == "intl":
        return "wmshare_intl"
    return "wmshare_call"


def _example(target: str, params: list[inspect.Parameter]) -> str:
    parts: list[str] = []
    for param in params:
        if param.name in _SYMBOL_NAMES:
            parts.append(f'{param.name}="600519"')
        elif param.default is inspect.Parameter.empty:
            parts.append(f'{param.name}=<REQUIRED>')
    args = ", ".join(parts)
    return f'{target}({args})'


def _catalog_function(domain: str, method: str, func: Callable[..., Any]) -> str | None:
    if (domain, method) in _SPECIAL_CATALOG:
        return _SPECIAL_CATALOG[(domain, method)]
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return None
    match = re.search(
        r'(?:\.call|\.call_batch)\(\s*["\']([a-z][a-z0-9_]*\.[A-Za-z0-9_]+)["\']',
        source,
    )
    return match.group(1) if match else None


@lru_cache(maxsize=1)
def api_routes() -> tuple[ApiRoute, ...]:
    """Return every public friendly-API method in stable order."""
    routes: list[ApiRoute] = []
    for domain, cls in FRIENDLY_NAMESPACES.items():
        for name, func in inspect.getmembers(cls, inspect.isfunction):
            if not _is_route_method(cls, name, func):
                continue
            sig = inspect.signature(func)
            public_params = [
                param for param in sig.parameters.values()
                if param.name != "self" and not param.name.startswith("_")
            ]
            doc = inspect.getdoc(func) or "SDK friendly API"
            target = f"{domain}.{name}"
            routes.append(ApiRoute(
                target=target,
                domain=domain,
                method=name,
                description=doc.splitlines()[0].strip(),
                signature=str(sig),
                parameters=tuple(param.name for param in public_params),
                example=_example(target, public_params),
                recommended_tool=_recommended_tool(domain, name),
                catalog_function=_catalog_function(domain, name, func),
                supports_raw="_raw" in sig.parameters,
                supports_units="_units" in sig.parameters,
            ))
    return tuple(routes)


def route_count() -> int:
    return len(api_routes())


def find_route(target: str) -> ApiRoute:
    """Find one friendly route or raise a prescriptive ValueError."""
    clean = str(target).strip()
    parts = clean.split(".")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("target 需为 friendly API 的 domain.method 格式")
    for route in api_routes():
        if route.target == clean:
            return route
    known = "、".join(sorted(FRIENDLY_NAMESPACES))
    raise ValueError(f"未知 friendly API {clean!r}；domain 可选 {known}；先用 wmshare_search(kind='api')")


def search_routes(query: str, limit: int) -> list[dict[str, Any]]:
    needle = str(query).strip().casefold()
    rows: list[dict[str, Any]] = []
    for route in api_routes():
        haystack = " ".join((
            route.target, route.domain, route.method, route.description,
            route.recommended_tool,
        )).casefold()
        if needle in haystack:
            row = route.as_dict()
            row["kind"] = "api"
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def route_contract(target: str) -> dict[str, Any]:
    route = find_route(target)
    data = route.as_dict()
    data.update({
        "kind": "api",
        "units": "返回单位由 SDK 规范化；比率/分位默认小数，金额/价格=元，量=股",
        "batch": "friendly API 本身不走 wmshare_batch；多标的优先查同名目录函数并用 batch",
        "allowed_arguments": list(route.parameters),
    })
    return data


def batchable_catalog_functions() -> tuple[str, ...]:
    """Return catalog functions that can batch symbols without required extra params."""
    import wmshare

    cat = wmshare.load()
    functions = cat.inventory.get("functions") or []
    symbol_names = {"sym", "symbol", "stk"}
    out: list[str] = []
    for item in functions:
        name = item.get("name")
        if not name:
            continue
        params = cat.inventory_params(name) or []
        if not any(
            param.get("type") == "string" and param.get("name") in symbol_names
            for param in params
        ):
            continue
        if any(
            param.get("required") and param.get("name") not in symbol_names
            for param in params
        ):
            continue
        out.append(str(name))
    return tuple(sorted(out))


def invoke_api(
    client: Any,
    target: str,
    arguments: dict[str, Any] | None,
    *,
    market: str,
    raw: bool,
    units: str,
) -> Any:
    """Invoke one friendly API with MCP-safe argument validation."""
    route = find_route(target)
    if route.domain == "intl" and market not in {"hk", "us"}:
        raise ValueError(
            "intl API 需要港/美市场客户端：market 只支持 hk/us；"
            "不要用 cn client 调港美股专项数据"
        )
    args = dict(arguments or {})
    forbidden = sorted(set(args) & {"_df", "_raw", "_units"})
    if forbidden:
        raise ValueError(f"禁止通过 arguments 传入 SDK 私有选项 {forbidden}；请使用 tool 的 raw/units")
    fn = getattr(client, route.domain)
    fn = getattr(fn, route.method)
    # Validate against introspected class metadata, not arbitrary doubles/spies.
    allowed = set(route.parameters)
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(
            f"未知参数 {unknown}；{route.target} 允许 {sorted(allowed)}"
        )
    call_args = dict(args)
    if raw:
        if not route.supports_raw:
            raise ValueError(f"{route.target} 不支持 raw=True")
        call_args["_raw"] = True
    if units != "base":
        if not route.supports_units:
            raise ValueError(f"{route.target} 不支持 units={units!r}")
        call_args["_units"] = units
    return fn(**call_args)


__all__ = [
    "ApiRoute",
    "api_routes",
    "batchable_catalog_functions",
    "find_route",
    "invoke_api",
    "route_contract",
    "route_count",
    "search_routes",
]
