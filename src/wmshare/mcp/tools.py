"""Pure tool functions registered by :mod:`wmshare.mcp.server`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import wmshare
from wmshare.client import BatchResult
from wmshare.errors import CatalogError, LimitError
from wmshare.mcp.apis import (
    batchable_catalog_functions,
    invoke_api,
    route_contract,
    route_count,
    search_routes,
)
from wmshare.mcp.constants import (
    COMPANY_BLOCKS,
    CORPORATE_ACTIONS,
    DIVIDEND_ACTIONS,
    ESTIMATE_ACTIONS,
    INTL_ACTIONS,
    MARKET_ACTIONS,
    MARKET_DOMAINS,
    MAX_ROWS,
    NOTICE_ACTIONS,
    SEGMENT_ACTIONS,
    TOOL_NAMES,
    STATEMENT_ACTIONS,
)
from wmshare.mcp.core import (
    MCPRuntime,
    _market,
    batch_meta,
    credential_status,
    flatten_batch,
    success,
)


def status(
    runtime: MCPRuntime,
    output: str = "sample",
    max_rows: int = 50,
) -> dict[str, Any]:
    """Return runtime, credentials, and catalog facts without reading secrets."""
    creds = credential_status()
    data = {
        "server_version": wmshare.__version__,
        "market": runtime.market,
        "demo": runtime.demo,
        "demo_notice": "非实时、固定快照，仅用于调用面验证" if runtime.demo else None,
        "credentials": creds,
        "catalog": wmshare.load().stats(),
        "capabilities": {
            "friendly_apis": route_count(),
            "api_gateway": "wmshare_call(mode='api')",
            "batchable_catalog_functions": len(batchable_catalog_functions()),
            "first_class_tools": len(TOOL_NAMES),
            "excluded_from_mcp": ["pandas/_df", "notice_poller", "长驻订阅"],
        },
        "setup": {
            "console": "open.winmale.com 开放平台 → 我的应用",
            "command": "wmshare-mcp setup --client-id ... --client-secret-stdin --market cn",
            "credential_path": creds["credential_path"],
        },
    }
    return success(runtime, data, output=output, max_rows=max_rows)


def search(
    runtime: MCPRuntime,
    query: str,
    kind: str = "all",
    market: str | None = None,
    limit: int = 10,
    output: str = "sample",
    max_rows: int = 20,
) -> dict[str, Any]:
    """Search offline catalog functions, metric codes, and symbols."""
    query = str(query).strip()
    if not query:
        raise ValueError("query 不能为空")
    if kind not in ("all", "function", "metric", "symbol", "api"):
        raise ValueError("kind 只支持 all/function/metric/symbol/api")
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit 只支持 1~50")
    selected_market = _market(market or runtime.market)
    cat = wmshare.load()
    hits: list[dict[str, Any]] = []
    if kind in ("all", "function", "metric"):
        hits.extend(cat.search(query, kind="all" if kind == "all" else kind, limit=int(limit)))
    if kind in ("all", "api"):
        hits.extend(search_routes(query, int(limit)))
    if kind in ("all", "symbol"):
        for row in cat.symbols_search(query, market=market or runtime.market,
                                      limit=int(limit)):
            hits.append({"kind": "symbol", **row})
    hits = hits[:int(limit)]
    return success(runtime, hits, output=output, max_rows=max_rows,
                   query=query, kind=kind, market=selected_market)


def contract(
    runtime: MCPRuntime,
    name: str,
    kind: str = "function",
    output: str = "sample",
    max_rows: int = 50,
) -> dict[str, Any]:
    """Return the offline contract for a function or curated metric code."""
    cat = wmshare.load()
    if kind == "function":
        data = cat.function(str(name))
    elif kind == "api":
        data = route_contract(str(name))
    elif kind == "metric":
        code = str(name)
        metric = cat.metric(code)
        if metric is None:
            raise CatalogError(f"未知指标 {code!r}；请先用 wmshare_search 查询指标码")
        data = {"meta": cat.metric_meta(code) or {}, **metric}
    else:
        raise ValueError("kind 只支持 function/metric/api")
    return success(runtime, data, output=output, max_rows=max_rows,
                   target_kind=kind, name=str(name))


def symbols(
    runtime: MCPRuntime,
    query: str,
    market: str | None = None,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = 20,
) -> dict[str, Any]:
    """Resolve company names, pinyin, aliases, or codes to symbols."""
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit 只支持 1~50")
    selected_market = _market(market or runtime.market)
    rows = wmshare.load().symbols_search(
        str(query), market=selected_market, limit=int(limit)
    )
    return success(runtime, rows, output=output, max_rows=max_rows,
                   query=str(query), market=selected_market)


def quote(
    runtime: MCPRuntime,
    symbols: list[str],
    market: str | None = None,
    live: bool = True,
    output: str = "sample",
    max_rows: int = 50,
) -> dict[str, Any]:
    """Fetch one or more latest/realtime quotes without per-symbol loops."""
    symbols = _unique_symbols(symbols)
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    meta: dict[str, Any] = {}
    if len(symbols) == 1:
        if live:
            data = cli.kline.live(symbols[0])
        else:
            data = cli.kline.snapshot(symbols[0])
    elif live:
        raw = cli.kline.batch_live(symbols)
        data = [
            {"symbol": symbol, **value} if isinstance(value, dict)
            else {"symbol": symbol, "value": value}
            for symbol, value in raw.items()
        ]
        meta = {"requests": 1, "requested": len(symbols)}
    else:
        result = cli.call_batch("kline.snapshot", symbols)
        data = flatten_batch(result)
        meta = batch_meta(result)
    return success(runtime, data, output=output, max_rows=max_rows,
                   live=live, market=selected_market, **meta)


def history(
    runtime: MCPRuntime,
    symbol: str,
    market: str | None = None,
    n: int | None = None,
    adj: str | None = None,
    begin: str | None = None,
    end: str | None = None,
    output: str = "sample",
    max_rows: int = 200,
) -> dict[str, Any]:
    """Fetch a daily bar series with SDK date/unit guards preserved."""
    if adj not in (None, "qfq", "hfq"):
        raise ValueError("adj 只支持 None/qfq/hfq")
    if n is not None and (isinstance(n, bool) or not 1 <= int(n) <= 10000):
        raise ValueError("n 只支持 1~10000")
    cli = runtime.client(market)
    data = cli.kline.bars(
        str(symbol), n=None if n is None else int(n), adj=adj,
        begin=begin, end=end,
    )
    return success(runtime, data, output=output, max_rows=max_rows,
                   symbol=str(symbol), adj=adj, begin=begin, end=end,
                   market=_market(market or runtime.market))


def metrics(
    runtime: MCPRuntime,
    symbol: str,
    codes: list[str],
    market: str | None = None,
    output: str = "sample",
    max_rows: int = 200,
) -> dict[str, Any]:
    """Validate curated metric codes against the offline catalog, then fetch."""
    codes = list(dict.fromkeys(str(code) for code in codes if str(code).strip()))
    if not codes:
        raise ValueError("codes 不能为空")
    if len(codes) > 100:
        raise ValueError("单次最多取 100 个指标码；更多请分批")
    cat = wmshare.load()
    missing = [code for code in codes if cat.metric(code) is None]
    if missing:
        raise CatalogError(f"未知指标 {missing}；先用 wmshare_search 确认指标码")
    data = runtime.client(market).indicator.metrics(str(symbol), codes)
    return success(runtime, data, output=output, max_rows=max_rows,
                   symbol=str(symbol), codes=codes,
                   market=_market(market or runtime.market))


def company(
    runtime: MCPRuntime,
    symbol: str,
    market: str | None = None,
    include: Sequence[str] | None = None,
    years: int = 3,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = 200,
) -> dict[str, Any]:
    """Fetch a compact research package from high-level friendly APIs."""
    include = list(include or ["profile", "income", "indicators", "dividend", "notices"])
    unknown = [item for item in include if item not in COMPANY_BLOCKS]
    if unknown:
        raise ValueError(f"include 不支持 {unknown}；可选 {COMPANY_BLOCKS}")
    if not 1 <= int(years) <= 10:
        raise ValueError("years 只支持 1~10")
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit 只支持 1~100")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    blocks: dict[str, Any] = {}
    if "profile" in include:
        blocks["profile"] = cli.info.profile(str(symbol))
    if "income" in include:
        blocks["income"] = cli.statements.income(str(symbol), years=int(years))
    if "balance" in include:
        blocks["balance"] = cli.statements.balance(str(symbol), years=int(years))
    if "cashflow" in include:
        blocks["cashflow"] = cli.statements.cashflow(str(symbol), years=int(years))
    if "indicators" in include:
        codes = ["$PE_TTM_LAST", "$BONUS_TTM_RATE_LAST"]
        blocks["indicators"] = cli.indicator.metrics(str(symbol), codes)
    if "dividend" in include:
        blocks["dividend"] = cli.dividend.history(str(symbol), limit=int(limit))
    if "notices" in include:
        blocks["notices"] = cli.notice.list(str(symbol), limit=int(limit))
    data = {"symbol": str(symbol), "blocks": blocks}
    return success(runtime, data, output=output, max_rows=max_rows,
                   symbol=str(symbol), include=include, market=selected_market)


def screen(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    test: str | None = None,
    params: dict[str, Any] | None = None,
    idx: str | None = None,
    industry: str | None = None,
    limit: int = 20,
    desc: bool = True,
    output: str = "sample",
    max_rows: int = 100,
) -> dict[str, Any]:
    """Expose screener facts without turning Agent output into local loops."""
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit 只支持 1~100")
    cli = runtime.client()
    p = dict(params or {})
    if action == "boolean":
        tests = {
            "limit_up": cli.screener.screen_limit_up,
            "limit_down": cli.screener.screen_limit_down,
            "above_ma20": cli.screener.screen_above_ma20,
            "ma60_up": cli.screener.screen_ma60_up,
            "breakout_ma20": cli.screener.screen_breakout_ma20,
            "momentum_20d": cli.screener.screen_momentum_20d,
            "pullback_20d": cli.screener.screen_pullback_20d,
            "volume_spike": cli.screener.screen_volume_spike,
        }
        if test not in tests:
            raise ValueError(f"test 只支持 {sorted(tests)}")
        if symbol is None:
            raise ValueError("action=boolean 需要 symbol")
        data = {"symbol": str(symbol), "test": test, "value": tests[test](str(symbol), **p)}
    elif action == "breadth_summary":
        data = cli.screener.index_breadth_summary(idx=idx)
    elif action == "breadth_bins":
        data = cli.screener.index_breadth_bins(idx=idx)
    elif action == "breadth_industries":
        data = cli.screener.index_breadth_bin_industries(idx=idx)
    elif action == "top_movers":
        data = cli.screener.index_top_movers(limit=int(limit), desc=desc, idx=idx)
    elif action == "industries":
        data = cli.stocks.industries()
    elif action == "industry_members":
        if industry is None:
            raise ValueError("action=industry_members 需要 industry")
        data = cli.stocks.industry_members(industry, top_n=int(limit))
    else:
        raise ValueError("action 不受支持")
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, test=test)


def disclosures(
    runtime: MCPRuntime,
    kind: str = "notice",
    symbol: str | None = None,
    market: str | None = None,
    window: str = "3m",
    keyword: str = "",
    begin: str | None = None,
    end: str | None = None,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = 100,
) -> dict[str, Any]:
    """Fetch disclosure families through their curated friendly APIs."""
    if kind not in ("notice", "filing", "forecast", "dividend", "workout"):
        raise ValueError("kind 只支持 notice/filing/forecast/dividend/workout")
    if bool(begin) != bool(end):
        raise ValueError("begin 与 end 需同时提供")
    if (begin or end) and (kind != "notice" or not symbol):
        raise ValueError("begin/end 目前只支持单票 notice 查询")
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit 只支持 1~100")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if kind == "notice":
        if symbol:
            if begin and end:
                data = cli.notice.find(str(symbol), str(begin), str(end),
                                       keyword=keyword, limit=int(limit))
            else:
                data = cli.notice.list(str(symbol), window=window, keyword=keyword,
                                       limit=int(limit))
        else:
            data = cli.notice.recent(window=window, keyword=keyword, limit=int(limit))
    elif kind == "filing":
        if symbol:
            data = cli.filings.list(str(symbol), limit=int(limit))
        else:
            raise ValueError("filing 查询需要 symbol")
    elif kind == "forecast":
        if not symbol:
            raise ValueError("forecast 查询需要 symbol")
        data = cli.forecast.yjyg(str(symbol), limit=int(limit))
    elif kind == "dividend":
        if not symbol:
            raise ValueError("dividend 查询需要 symbol")
        data = cli.dividend.history(str(symbol), limit=int(limit))
    else:
        data = cli.workout.query(str(symbol)) if symbol else cli.workout.board()
    return success(runtime, data, output=output, max_rows=max_rows,
                   kind=kind, symbol=symbol, window=window,
                   market=selected_market)


def batch(
    runtime: MCPRuntime,
    function: str,
    symbols: list[str],
    market: str | None = None,
    batch_size: int | None = None,
    on_batch_error: str = "skip",
    params: dict[str, Any] | None = None,
    raw: bool = False,
    units: str = "base",
    output: str = "sample",
    max_rows: int = 200,
) -> dict[str, Any]:
    """Batch a catalog function while preserving per-batch progress on 429."""
    symbols = _unique_symbols(symbols)
    if not symbols:
        raise ValueError("symbols 不能为空")
    if on_batch_error not in ("raise", "skip"):
        raise ValueError("on_batch_error 只支持 raise/skip")
    if batch_size is not None and (isinstance(batch_size, bool) or not 1 <= int(batch_size) <= 500):
        raise ValueError("batch_size 只支持 1~500")
    wmshare.load().function(str(function))  # fail before any network request
    if units not in ("base", "native"):
        raise ValueError("units 只支持 base/native")
    batch_params = dict(params or {})
    forbidden = sorted(set(batch_params) & {"_df", "_raw", "_units"})
    if forbidden:
        raise ValueError(f"禁止通过 params 传入 SDK 私有选项 {forbidden}；请使用 tool 的 raw/units")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    collected = BatchResult()
    done = 0
    try:
        for part in cli.batch_iter(
            str(function), symbols, batch_size=batch_size,
            on_batch_error=on_batch_error,
            _raw=raw,
            _units=units,
            **batch_params,
        ):
            collected.results.update(part.results)
            collected.errors.update(part.errors)
            collected.error_details.update(part.error_details)
            collected.requests += part.requests
            collected.requested += part.requested
            done += part.requested
    except LimitError as exc:
        retry_after = getattr(exc, "retry_after", None)
        resume = symbols[done:] if 0 <= done <= len(symbols) else symbols
        resume_truncated = len(resume) > MAX_ROWS
        meta_extra = {
            "completed": min(done, len(symbols)),
            "resume_symbols_total": len(resume),
            "resume_start": min(done, len(symbols)),
            "resume_symbols_truncated": resume_truncated,
            "resume_symbols": resume[:MAX_ROWS],
            "retry_after_seconds": retry_after,
            "next_action": (
                "等待限流窗口后用 symbols[resume_start:] 或 resume_symbols 从失败位置续跑；"
                "不要无脑重试整批"
            ),
        }
        response = success(runtime, collected, output=output, max_rows=max_rows,
                           function=str(function), market=selected_market,
                           **batch_meta(collected), **meta_extra)
        response["ok"] = False
        response["partial"] = True
        response["error"] = {
            "kind": "LimitError",
            "code": "rate_limited",
            "message": str(exc),
            "fix": ["等待后从 resume_start 续跑剩余标的，不要重试已完成部分"],
        }
        return response
    return success(runtime, collected, output=output, max_rows=max_rows,
                   function=str(function), market=selected_market,
                   **batch_meta(collected))


def call(
    runtime: MCPRuntime,
    target: str,
    arguments: dict[str, Any] | None = None,
    market: str | None = None,
    mode: str = "catalog",
    raw: bool = False,
    units: str = "base",
    output: str = "sample",
    max_rows: int = 100,
) -> dict[str, Any]:
    """Controlled fallback for catalog functions and all friendly SDK APIs."""
    selected_market = _market(market or runtime.market)
    if units not in ("base", "native"):
        raise ValueError("units 只支持 base/native")
    args = dict(arguments or {})
    if mode == "api":
        cli = runtime.client(market)
        data = invoke_api(
            cli, str(target), args, market=selected_market,
            raw=raw, units=units,
        )
        return success(runtime, data, output=output, max_rows=max_rows,
                       target=str(target), mode=mode, raw=raw, units=units,
                       market=selected_market)
    if mode != "catalog":
        raise ValueError("mode 只支持 catalog/api")
    fn = wmshare.load().function(str(target))
    allowed = {
        item["name"] for item in (
            fn.get("params") or wmshare.load().inventory_params(str(target)) or []
        )
    }
    forbidden = sorted(set(args) & {"_df", "_raw", "_units"})
    if forbidden:
        raise ValueError(f"禁止通过 arguments 传入 SDK 私有选项 {forbidden}；请使用 tool 的 raw/units")
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(f"未知参数 {unknown}；目录合同参数为 {sorted(allowed)}")
    data = runtime.client(market).call(
        str(target), _raw=raw, _units=units, **args
    )
    return success(runtime, data, output=output, max_rows=max_rows,
                   target=str(target), mode=mode, raw=raw, units=units,
                   market=selected_market)



def _optional_limit(value: int, upper: int = 100) -> int:
    if isinstance(value, bool) or not 1 <= int(value) <= upper:
        raise ValueError(f"limit 只支持 1~{upper}")
    return int(value)


def _required_date_pair(begin: str | None, end: str | None) -> tuple[str | None, str | None]:
    if bool(begin) != bool(end):
        raise ValueError("begin 与 end 需同时提供")
    return begin, end


def statement(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    kind: str = "income",
    years: int = 5,
    scope: str = "合并",
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch curated statement views: three statements, audit, compare, tree, years."""
    if action not in STATEMENT_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(STATEMENT_ACTIONS)}")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if action in {"income", "balance", "cashflow"}:
        data = getattr(cli.statements, action)(str(symbol), years=int(years), scope=scope)
    elif action == "audit":
        data = cli.statements.audit(_symbol(action, symbol))
    elif action in {"compare", "tree"}:
        data = getattr(cli.statements, action)(
            _symbol(action, symbol), kind=kind, years=int(years), scope=scope
        )
    else:
        data = cli.statements.years(_symbol(action, symbol), kind=kind)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, kind=kind, symbol=symbol,
                   market=selected_market)


def segments(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    source: str = "clean",
    limit: int = 20,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch business/product/region/income/coverage/period/snapshot segment views."""
    if action not in SEGMENT_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(SEGMENT_ACTIONS)}")
    if action in {"business", "products", "region", "income", "snapshot"}:
        limit = _optional_limit(limit)
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    symbol_value = _symbol(action, symbol, allow_empty=False)
    if action in {"business", "products", "region", "income"}:
        data = getattr(cli.segments, action)(
            symbol_value, source=source, limit=limit
        )
    elif action == "snapshot":
        data = cli.segments.snapshot(symbol_value, source=source)
    elif action == "coverage":
        data = cli.segments.coverage(symbol_value)
    elif action == "periods":
        data = cli.segments.periods(symbol_value)
    else:  # pragma: no cover
        raise AssertionError(action)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol_value, source=source,
                   market=selected_market)


def dividend(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    limit: int | None = None,
    begin: str | None = None,
    end: str | None = None,
    window: str = "3y",
    min_yield: float | None = None,
    payout_min: float | None = None,
    payout_max: float | None = None,
    min_pct: float | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch dividend history, TTM metrics, window stats, and quality screens."""
    if action not in DIVIDEND_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(DIVIDEND_ACTIONS)}")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if action == "history":
        begin, end = _required_date_pair(begin, end)
        if limit is not None:
            _optional_limit(limit, 1000)
        data = cli.dividend.history(
            _symbol(action, symbol), limit=limit, begin=begin, end=end
        )
    elif action == "last":
        data = cli.dividend.last(_symbol(action, symbol))
    elif action == "dps":
        data = cli.dividend.dps(_symbol(action, symbol))
    elif action == "yield_ttm":
        data = cli.dividend.yield_ttm(_symbol(action, symbol))
    elif action == "payout_ttm":
        data = cli.dividend.payout_ttm(_symbol(action, symbol))
    elif action == "window_stats":
        data = cli.dividend.window_stats(_symbol(action, symbol), window=window)
    elif action == "screen_quality":
        data = cli.dividend.screen_quality(
            _symbol(action, symbol), min_yield=min_yield,
            payout_min=payout_min, payout_max=payout_max,
        )
    elif action == "screen_high_yield":
        data = cli.dividend.screen_high_yield(
            _symbol(action, symbol), min_yield=min_yield
        )
    else:
        data = cli.dividend.screen_undervalued_yield(
            _symbol(action, symbol), min_yield=min_yield, min_pct=min_pct
        )
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol, window=window,
                   market=selected_market)


def estimates(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    limit: int = 8,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch forecasts, ratings, reports, and scheduled disclosure events."""
    if action not in ESTIMATE_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(ESTIMATE_ACTIONS)}")
    limit = _optional_limit(limit)
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    symbol_value = _symbol(action, symbol, allow_empty=False)
    if action == "forecast":
        data = cli.estimates.query_forecast(symbol_value, limit=limit)
    elif action == "forecast_detail":
        data = cli.estimates.query_forecast_detail(symbol_value, limit=limit)
    elif action == "rating":
        data = cli.estimates.query_rating(symbol_value, limit=limit)
    elif action == "reports":
        data = cli.estimates.query_reports(symbol_value, limit=limit)
    elif action == "disclosure_history":
        data = cli.forecast.disclosure_history(symbol_value, limit=limit)
    elif action == "next_disclosure":
        data = cli.forecast.next_disclosure(symbol_value)
    elif action == "yjkb":
        data = cli.forecast.yjkb(symbol_value, limit=limit)
    elif action == "yjkb_latest":
        data = cli.forecast.yjkb_latest(symbol_value)
    elif action == "yjyg":
        data = cli.forecast.yjyg(symbol_value, limit=limit)
    else:
        data = cli.forecast.yjyg_latest(symbol_value)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol_value, market=selected_market)


def _corporate_call(cli: Any, action: str, symbol: str | None,
                    limit: int | None, annual: int | None, sampling: str | None) -> Any:
    fn = getattr(cli.equity, action)
    sig_kwargs: dict[str, Any] = {}
    if limit is not None:
        sig_kwargs["limit"] = limit
    if annual is not None:
        sig_kwargs["annual"] = annual
    if sampling is not None:
        sig_kwargs["sampling"] = sampling
    if symbol is not None:
        sig_kwargs["symbol"] = symbol
    try:
        return fn(**sig_kwargs)
    except TypeError as exc:
        raise ValueError(f"action={action} 参数组合不合法：{exc}") from exc


def corporate(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    limit: int = 20,
    annual: int | None = None,
    sampling: str | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch equity governance and ownership facts without inventing catalog names."""
    if action not in CORPORATE_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(CORPORATE_ACTIONS)}")
    limit = _optional_limit(limit)
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if action.endswith("_at"):
        if annual is None or sampling is None:
            raise ValueError(f"action={action} 需要同时提供 annual 和 sampling")
    elif action in {"query_pledge_industry", "query_pledge_market", "query_pledge_org"}:
        symbol = None
    else:
        symbol = _symbol(action, symbol, allow_empty=False)
    data = _corporate_call(cli, action, symbol, limit, annual, sampling)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol, market=selected_market)


def market(
    runtime: MCPRuntime,
    domain: str,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    key: str | None = None,
    n: int | None = None,
    begin: str | None = None,
    end: str | None = None,
    points: int | None = None,
    sort_by: str | None = None,
    top_n: int | None = None,
    metric: str = "pe",
    window: str = "3y",
    level: int | None = None,
    trig: float | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch minute, moneyflow, margin, CBond, index, valuation, and universe facts."""
    if domain not in MARKET_DOMAINS:
        raise ValueError(f"domain 只支持 {'/'.join(MARKET_DOMAINS)}")
    allowed_actions = MARKET_ACTIONS[domain]
    if action not in allowed_actions:
        raise ValueError(f"domain={domain} 的 action 只支持 {'/'.join(allowed_actions)}")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if begin is not None or end is not None:
        begin, end = _required_date_pair(begin, end)
    if domain == "kline" and action == "minute":
        data = cli.kline.min1(_symbol(action, symbol))
    elif domain == "kline" and action == "is_etf":
        data = {"symbol": _symbol(action, symbol), "is_etf": bool(cli.kline.is_etf(_symbol(action, symbol)))}
    elif domain == "moneyflow" and action == "bars":
        data = cli.moneyflow.bars(_symbol(action, symbol), n=n, begin=begin, end=end)
    elif domain == "moneyflow":
        data = getattr(cli.moneyflow, action)(_symbol(action, symbol))
    elif domain == "margin" and action == "query":
        data = cli.margin.query(_symbol(action, symbol), limit=_optional_limit(n or 20))
    elif domain == "margin":
        data = cli.margin.latest(_symbol(action, symbol))
    elif domain == "cbond" and action == "universe":
        data = cli.cbond.universe_codes()
    elif domain == "cbond" and action == "latest_quotes":
        data = cli.cbond.latest_quotes()
    elif domain == "cbond" and action == "of_stock":
        data = cli.cbond.of_stock(_symbol(action, symbol))
    elif domain == "cbond" and action == "query":
        data = cli.cbond.query(_symbol(action, symbol))
    elif domain == "cbond" and action == "call_hits":
        if trig is None:
            raise ValueError("cbond.call_hits 需要 trig")
        data = cli.cbond.call_hits(_symbol(action, symbol), float(trig))
    elif domain == "cbond" and action == "kline_window":
        if n is None or isinstance(n, bool) or not 1 <= int(n) <= 10000:
            raise ValueError("cbond.kline_window 需要 n，且 n 只支持 1~10000")
        data = cli.cbond.kline_window(_symbol(action, symbol), n=int(n))
    elif domain == "index" and action == "keys":
        data = cli.index.keys()
    elif domain == "index" and action in {"members", "weights"}:
        if key is None:
            raise ValueError(f"index.{action} 需要 key；先用 action=keys 查可选值")
        data = getattr(cli.index, action)(key, sort_by=sort_by, top_n=top_n)             if action == "members" else cli.index.weights(key, top_n=top_n)
    elif domain == "index" and action == "valuation":
        if key is None:
            raise ValueError("index.valuation 需要 key；先用 action=keys 查可选值")
        data = cli.index.valuation(key, points=points)
    elif domain == "index" and action == "trend":
        if key is None:
            raise ValueError("index.trend 需要 key；先用 action=universe_keys 查可选值")
        data = cli.index.trend(key)
    elif domain == "index" and action == "universe_keys":
        data = cli.index.universe_keys()
    elif domain == "valuation":
        data = cli.valuation.hist_stats(
            _symbol(action, symbol), metric=metric, window=window
        )
    else:
        data = cli.stocks.list()
    return success(runtime, data, output=output, max_rows=max_rows,
                   domain=domain, action=action, symbol=symbol, key=key,
                   market=selected_market)


def intl(
    runtime: MCPRuntime,
    action: str,
    symbol: str,
    market: str | None = None,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch HK/US disclosure-facing international facts through the selected market."""
    if action not in INTL_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(INTL_ACTIONS)}")
    selected_market = _market(market or runtime.market)
    if selected_market not in {"hk", "us"}:
        raise ValueError("intl API 只支持 market=hk/us；不要用 cn client")
    limit = _optional_limit(limit)
    cli = runtime.client(market)
    fn = getattr(cli.intl, action)
    sig_kwargs: dict[str, Any] = {"symbol": str(symbol)}
    if action != "issue_info":
        sig_kwargs["limit"] = limit
    data = fn(**sig_kwargs)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=str(symbol), market=selected_market)


def notice(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    market: str | None = None,
    category: str | None = None,
    date: str | None = None,
    window: str = "3m",
    keyword: str = "",
    begin: str | None = None,
    end: str | None = None,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch advanced notice lists, date/category queries, and boolean signals."""
    if action not in NOTICE_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(NOTICE_ACTIONS)}")
    limit = _optional_limit(limit)
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if action == "list":
        data = cli.notice.list(_symbol(action, symbol), window=window,
                               keyword=keyword, limit=limit)
    elif action == "recent":
        data = cli.notice.recent(window=window, keyword=keyword, limit=limit)
    elif action == "find":
        begin, end = _required_date_pair(begin, end)
        data = cli.notice.find(_symbol(action, symbol), str(begin), str(end),
                               keyword=keyword, limit=limit)
    elif action == "by_category":
        if category is None:
            raise ValueError("notice.by_category 需要 category")
        data = cli.notice.by_category(category, window=window, limit=limit)
    elif action == "on_date":
        if date is None:
            raise ValueError("notice.on_date 需要 date")
        data = cli.notice.on_date(date, keyword=keyword, limit=limit)
    elif action == "has_buyback":
        data = {"symbol": _symbol(action, symbol), "window": window,
                "value": bool(cli.notice.has_buyback(_symbol(action, symbol), window=window))}
    else:
        data = {"symbol": _symbol(action, symbol), "window": window,
                "value": bool(cli.notice.has_reduction(_symbol(action, symbol), window=window))}
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol, window=window,
                   market=selected_market)


def _symbol(context: str, value: str | None, *, allow_empty: bool = True) -> str:
    if value is None or not str(value).strip():
        if allow_empty:
            return ""
        raise ValueError(f"{context} 需要 symbol")
    return str(value).strip()



def _unique_symbols(values: list[str]) -> list[str]:
    out = [str(value).strip() for value in values if str(value).strip()]
    if not out:
        raise ValueError("symbols 不能为空")
    return list(dict.fromkeys(out))


__all__ = [
    "batch", "call", "company", "contract", "corporate", "disclosures",
    "dividend", "estimates", "history", "intl", "market", "metrics", "notice",
    "quote", "screen", "search", "segments", "statement", "status", "symbols",
]
