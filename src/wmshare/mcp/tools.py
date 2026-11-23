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
    BACKTEST_RULES,
    COMPANY_BLOCKS,
    CORPORATE_ACTIONS,
    DIVIDEND_ACTIONS,
    ESTIMATE_ACTIONS,
    ETF_ACTIONS,
    FUTURES_ACTIONS,
    INCOME_ACTIONS,
    INTL_ACTIONS,
    FX_ACTIONS,
    MACRO_ACTIONS,
    MARKET_ACTIONS,
    MARKET_DOMAINS,
    MAX_ROWS,
    NOTICE_ACTIONS,
    PDF_ACTIONS,
    SEGMENT_ACTIONS,
    TOPLIST_ACTIONS,
    TOOL_NAMES,
    STATEMENT_ACTIONS,
    VALUATION_ACTIONS,
    VALUATION_METRICS,
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
    stats = wmshare.load().stats()
    data = {
        "server_version": wmshare.__version__,
        "market": runtime.market,
        "credentials": creds,
        "catalog": stats,
        "capabilities": {
            "friendly_apis": route_count(),
            "api_gateway": "wmshare_call(mode='api')",
            "cost_gateway": "wmshare_call(mode='cost', target=…, arguments={…})",
            "batchable_catalog_functions": len(batchable_catalog_functions()),
            "first_class_tools": len(TOOL_NAMES),
            "excluded_from_mcp": ["notice_poller", "长驻订阅"],
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
    # 指标命中行并入目录元数据（group/markets/量级界/unit）——「检索即带口径」：
    # 模型拿到码的同时拿到量级界，省一次 contract 往返（字段缺失留空不伪造）。
    for row in hits:
        if isinstance(row, dict) and row.get("kind") == "metric" and "group" not in row:
            meta = cat.metric(str(row.get("code") or ""))
            if meta:
                row["group"] = meta.get("group")
                row["markets"] = meta.get("markets")
                row["range"] = meta.get("range")
                if meta.get("unit"):
                    row["unit"] = meta["unit"]
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
    where: str | None = None,
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
    elif action == "query":
        if not where:
            raise ValueError("action=query 需要 where（如 \"$ROE_TTM_LAST > 0.15\"）")
        data = cli.screener.query(
            where, order=p.get("order"), desc=bool(p.get("desc", desc)),
            limit=int(limit), offset=int(p.get("offset") or 0),
            fields=p.get("fields"), idx=idx,
        )
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
                           raw=raw, units=units,
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
                   raw=raw, units=units,
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
        # 事后计量：把单次消耗暴露给 LLM，并让超预算调用显式报错。
        # 上限由部署方通过 WMSHARE_MCP_MAX_EC 设定，不是 tool 参数。
        ec_cost = getattr(cli, "last_ec_cost", None)
        if isinstance(ec_cost, int) and ec_cost > runtime.max_ec_per_call:
            raise LimitError(
                f"{target} 单次消耗 {ec_cost} EC，超过 MCP 单次上限 "
                f"{runtime.max_ec_per_call}；请缩小范围或改用本地 SDK",
                code="ec_budget")
        return success(runtime, data, output=output, max_rows=max_rows,
                       target=str(target), mode=mode, raw=raw, units=units,
                       market=selected_market, ec_cost=ec_cost)
    if mode == "cost":
        # 2.0 计费透明度：调用前预估 EC 区间（估算值；不发起取数请求）。
        est = runtime.client(market).cost_estimate(str(target), **args)
        return success(runtime, est, output="sample", max_rows=100,
                       target=str(target), mode=mode, market=selected_market)
    if mode != "catalog":
        raise ValueError("mode 只支持 catalog/api/cost")
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
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """Fetch curated statement views: three statements + audit (fin_* wide tables)."""
    if action not in STATEMENT_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(STATEMENT_ACTIONS)}")
    selected_market = _market(market or runtime.market)
    cli = runtime.client(market)
    if action in {"income", "balance", "cashflow", "indicators"}:
        data = getattr(cli.statements, action)(str(symbol), years=int(years))
    else:
        data = cli.statements.audit(_symbol(action, symbol))
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
    # meta.source 是信封的数据源标记（SOURCE 常量），不能被 segments 的
    # 清洗口径参数 source="clean"/"raw" 覆盖；回显改用 segment_source。
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol_value, segment_source=source,
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
    src: str | None = None,
    date: str | None = None,
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
        data = cli.index.trend(key, window=window)
    elif domain == "index" and action == "universe_keys":
        data = cli.index.universe_keys()
    elif domain == "valuation":
        data = cli.valuation.hist_stats(
            _symbol(action, symbol), metric=metric, window=window
        )
    elif domain == "stocks" and action == "limit_price":
        data = cli.stocks.limit_price(_symbol(action, symbol))
    elif domain == "stocks" and action == "limit_prices":
        data = cli.stocks.limit_prices()
    elif domain == "board":
        board_src = src or "ths_concept"
        if board_src not in ("ths_concept", "ths_industry", "dc"):
            raise ValueError("src 只支持 ths_concept/ths_industry/dc")
        if action == "moneyflow":
            if not date:
                raise ValueError("board.moneyflow 需要 date（交易日 YYYY-MM-DD）")
            data = cli.board.moneyflow(board_src, date, limit=n or 100)
        else:
            data = cli.board.moneyflow_last(board_src, limit=n or 100)
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


def income(
    runtime: MCPRuntime,
    action: str,
    symbols: Sequence[str] | None = None,
    top_n: int = 20,
    grade: str | None = None,
    industry: str | None = None,
    min_yield: float | None = None,
    begin: str | None = None,
    end: str | None = None,
    years: int = 10,
    include_history: bool = False,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """收息闭环（仅 A 股）：全市场排行、批量诊断、分红日历、N 年持有收益拆解。

    rating ≈15k~70k EC，榜单由 cron 物化（16:50/19:40）——冷缓存返回 ok=false
    时如实转述稍后重试，勿现场重算全市场评分；diagnose 原生批量 ≈10k EC/票，
    include_history=True 是 deep 档（+18k EC/票）。
    """
    if action not in INCOME_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(INCOME_ACTIONS)}")
    cli = runtime.client("cn")           # disc.income 仅 A 股
    top_n = _optional_limit(top_n, 200)
    if action == "rating":
        data = cli.dividend.rating(top_n=top_n, grade=grade,
                                   industry=industry, min_yield=min_yield)
    elif action == "diagnose":
        data = cli.dividend.diagnose(_unique_symbols(symbols or []),
                                     include_history=bool(include_history))
    elif action == "calendar":
        data = cli.dividend.calendar(begin, end)
    else:
        if not 1 <= int(years) <= 10:
            raise ValueError("years 只支持 1~10（口径 3/5/10 年）")
        data = cli.dividend.decomp(_unique_symbols(symbols or []), years=int(years))
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, market="cn")


def backtest(
    runtime: MCPRuntime,
    symbol: str,
    rule: str = "ma_cross",
    fast: int | None = None,
    slow: int | None = None,
    buy: float | None = None,
    sell: float | None = None,
    begin: str | None = None,
    end: str | None = None,
    adj: str | None = None,
    output: str = "sample",
    max_rows: int = 100,
) -> dict[str, Any]:
    """单股买卖点回测（仅 A 股）：均线金叉/死叉或估值阈值 → 成交明细+净值/回撤/胜率。

    固定口径：次日开盘成交、T+1、100 股整手、佣金/印花固定、初始资金 100 万；
    全历史估值回测可达 ~40 万 EC——先用 wmshare_call(mode='cost') 预估再跑。
    """
    if rule not in BACKTEST_RULES:
        raise ValueError(f"rule 只支持 {'/'.join(BACKTEST_RULES)}")
    begin, end = _required_date_pair(begin, end)
    cli = runtime.client("cn")
    kwargs: dict[str, Any] = {"rule": str(rule)}
    if fast is not None:
        kwargs["fast"] = int(fast)
    if slow is not None:
        kwargs["slow"] = int(slow)
    if buy is not None:
        kwargs["buy"] = float(buy)
    if sell is not None:
        kwargs["sell"] = float(sell)
    if adj is not None:
        kwargs["adj"] = str(adj)
    if begin:
        kwargs["begin"], kwargs["end"] = begin, end
    data = cli.backtest.run(_symbol("backtest", symbol), **kwargs)
    return success(runtime, data, output=output, max_rows=max_rows,
                   symbol=_symbol("backtest", symbol), rule=str(rule), market="cn")


def etf(
    runtime: MCPRuntime,
    action: str,
    symbol: str,
    mode: str = "latest",
    limit: int | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """ETF 九视图（仅 A 股场内）：一页档案/净值/份额/分红/持仓/溢价/资产配置/榜单。

    mode='series' 取时序（card/nav/share/premium 支持）；rank 是单票榜单指标。
    """
    if action not in ETF_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(ETF_ACTIONS)}")
    cli = runtime.client("cn")
    fn = getattr(cli.etf, action)
    kwargs: dict[str, Any] = {"mode": str(mode)}
    if action == "rank" and limit is not None:
        kwargs["limit"] = _optional_limit(limit, 200)
    data = fn(_symbol(action, symbol), **kwargs)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=_symbol(action, symbol), mode=str(mode),
                   market="cn")


def macro(
    runtime: MCPRuntime,
    action: str,
    code: str,
    n: int = 6,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """宏观指标时序/最新值/采样频率（$CPI/$GDP/$M2 …；码先 wmshare_search 查）。

    query 取近 n 期时序（date 升序），asof 取最新一期值，sampling 查该码的
    采样频率——返回值是上游原值口径（价格指数=点、流量存量=元、收益率=小数）。
    reserve 列储备项、reserve_history 取储备时序（元/美元数值，见返回 units）。
    us_topics/us_search/us_series 走美宏观序列（code 传序列 id 如 GDP/DGS10）：
    **单位随序列而变**，先 us_series 读 units 再解读数值。
    实测成本（2026-11-23）：us_topics ≈408 EC、us_search ≈1,324 EC；
    us_series 冷态 ≈150 EC/行（323 行约 4.7 万、10000 行约 46.8 万），
    **复跑恒定 ≈92 EC**——长历史先读一次再复算，或缩小 n。
    n 受 Client 默认 max_limit=500 约束（要更多须 Client(max_limit=None)），
    服务端 store 硬顶 10000；更长历史用 cli.us_macro.points(begin/end) 分段取。
    """
    if action not in MACRO_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(MACRO_ACTIONS)}")
    cli = runtime.client("cn")
    # 美宏观三 action 走 fred 命名空间（code 是序列 id，不是指标码）
    if action in ("us_topics", "us_search", "us_series"):
        if action == "us_topics":
            data = cli.us_macro.topics()
            return success(runtime, data, output=output, max_rows=max_rows,
                           action=action, market="cn")
        code_value = _symbol(action, code, allow_empty=False)
        if action == "us_search":
            data = cli.us_macro.search(code_value, limit=_optional_limit(n, 88))
        else:
            data = cli.us_macro.points(code_value, limit=_optional_limit(n, 500))
        return success(runtime, data, output=output, max_rows=max_rows,
                       action=action, code=code_value, market="cn")
    # 储备两 action 不消费 code（用 kind），先分流
    if action in ("reserve", "reserve_history"):
        kind = _symbol(action, code, allow_empty=False)
        if action == "reserve":
            data = cli.macro.reserves()
        else:
            data = cli.macro.reserves_history(kind, n=_optional_limit(n, 48))
        return success(runtime, data, output=output, max_rows=max_rows,
                       action=action, kind=kind, market="cn")
    code_value = _symbol(action, code, allow_empty=False)
    if action == "query":
        data = cli.macro.query(code_value, n=_optional_limit(n, 100))
    elif action == "asof":
        data = cli.macro.asof(code_value)
    else:
        data = cli.macro.sampling_of(code_value)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, code=code_value, market="cn")


def fx(
    runtime: MCPRuntime,
    action: str,
    ccy: str = "USD",
    n: int = 30,
    begin: str | None = None,
    end: str | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """人民币外汇汇率（央行中间价 + 中行牌价，日频）。

    rate=最新汇率快照（ccy/date/middle/buy/cash_buy），history=日线（date 升序），
    bars=区间日线（begin/end），list=在库币种清单。
    **口径**：middle/buy 均为「每 1 单位外币折人民币」（USD≈7.1、JPY≈0.042）；
    上游原始中间价是每 100 外币口径，SDK 已统一 /100 归一。
    """
    if action not in FX_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(FX_ACTIONS)}")
    cli = runtime.client("cn")
    code = _symbol(action, ccy, allow_empty=False)
    if action == "rate":
        data = cli.fx.rate(code)
    elif action == "history":
        data = cli.fx.history(code, n=_optional_limit(n, 500))
    elif action == "bars":
        data = cli.fx.bars(code, begin=begin, end=end)
    else:
        data = cli.fx.list()
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, ccy=code, market="cn")


def valuation(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    symbols: Sequence[str] | None = None,
    metric: str = "pe",
    window: str = "3y",
    begin: str | None = None,
    end: str | None = None,
    fields: str | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """估值历史统计与基础指标：hist_stats 分位、daily_basic 多日/多票/覆盖面。

    hist_stats(metric=pe/pb/ps/pr, window=3y/5y/10y) 返回均值/中位/分位；
    daily_basic_* 的 fields 用逗号分隔列名；窗口上限与覆盖面以返回的
    coverage/窗口白名单为准（未知窗口显式报错，不静默降 30 天）。
    """
    if action not in VALUATION_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(VALUATION_ACTIONS)}")
    if str(metric) not in VALUATION_METRICS:
        raise ValueError(f"metric 只支持 {'/'.join(VALUATION_METRICS)}")
    cli = runtime.client("cn")
    begin, end = _required_date_pair(begin, end)
    if action == "hist_stats":
        data = cli.valuation.hist_stats(_symbol(action, symbol),
                                        metric=str(metric), window=str(window))
    elif action == "daily_basic":
        data = cli.valuation.daily_basic(_symbol(action, symbol), begin=begin,
                                         end=end, fields=fields)
    elif action == "daily_basic_multi":
        data = cli.valuation.daily_basic_multi(_unique_symbols(symbols or []),
                                               begin=begin, end=end, fields=fields)
    else:
        data = cli.valuation.daily_basic_coverage(_symbol(action, symbol),
                                                  begin=begin, end=end)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol, metric=str(metric),
                   window=str(window), market="cn")


def toplist(
    runtime: MCPRuntime,
    action: str,
    symbol: str | None = None,
    trade_date: str | None = None,
    limit: int = 100,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """龙虎榜（仅 A 股）：按交易日取全榜，或按标的取上榜历史。

    成本实测：冷查 ≈12,837 EC、热查 ≈154 EC——日期用近期交易日更省。
    """
    if action not in TOPLIST_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(TOPLIST_ACTIONS)}")
    limit = _optional_limit(limit, 200)
    cli = runtime.client("cn")
    if action == "by_date":
        if not trade_date:
            raise ValueError("toplist.by_date 需要 trade_date（YYYY-MM-DD）")
        data = cli.toplist.by_date(str(trade_date), limit=limit)
    else:
        data = cli.toplist.by_symbol(_symbol(action, symbol), limit=limit)
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, symbol=symbol, trade_date=trade_date, market="cn")


def futures(
    runtime: MCPRuntime,
    action: str,
    code: str | None = None,
    symbol: str | None = None,
    field: str = "close",
    freq: str | None = None,
    native: bool = False,
    n: int | None = None,
    begin: str | None = None,
    end: str | None = None,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """期货主力：合约字段取值、主力连续映射、合约快照、历史K线（74 商品+8 金融）。

    code 是合约代码（如 RB2605.SHF）或主力连续；field 取 close/open/…；
    freq=d/w/m。mapping 冷查实测 ≈21.4 万 EC、热查 ≈141 EC——先 cost 预估。
    bars 走 store 直读，按**行数**计费（冷 ≈190+126 EC/行、同日复跑命中数据版本键
    缓存 ≈135 EC），长区间建议 freq='m'（行数省约 20 倍）。snapshot/get 单行 ≈135~320 EC。
    """
    if action not in FUTURES_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(FUTURES_ACTIONS)}")
    cli = runtime.client("cn")
    if action == "get":
        data = cli.futures.get(_symbol(action, code, allow_empty=False),
                               field=str(field),
                               freq=str(freq) if freq else None,
                               native=bool(native))
    elif action == "mapping":
        begin, end = _required_date_pair(begin, end)
        data = cli.futures.mapping(_symbol(action, symbol, allow_empty=False),
                                   begin=str(begin or ""), end=str(end or ""))
    elif action == "bars":
        if n is None and not (begin and end):
            raise ValueError("bars 需要 n（最近 n 个周期）或 begin+end 成对区间")
        data = cli.futures.bars(_symbol(action, code, allow_empty=False),
                                n=n,
                                begin=str(begin) if begin else None,
                                end=str(end) if end else None,
                                freq=str(freq) if freq else None)
    else:
        data = cli.futures.snapshot(_symbol(action, code, allow_empty=False),
                                    freq=str(freq or "d"))
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, code=code, symbol=symbol, market="cn")


def pdf(
    runtime: MCPRuntime,
    action: str,
    stock_code: str | None = None,
    title: str | None = None,
    begin: str | None = None,
    end: str | None = None,
    kind: str | None = None,
    file_key: str | None = None,
    source_url: str | None = None,
    period: str | None = None,
    limit: int = 20,
    output: str = "sample",
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """公告 PDF 结构化（仅 A 股，wmshare 独有面）：检索→状态→正文 Markdown。

    search 按代码/标题/公告日区间找文件；read_markdown 把公告正文抽成
    Markdown（需 file_key 或 source_url，或 stock_code+period 直取定期报告）；
    status 查解析状态。报告正文结构化走这里，不要用 wmshare_notice 拿原文链接。
    """
    if action not in PDF_ACTIONS:
        raise ValueError(f"action 只支持 {'/'.join(PDF_ACTIONS)}")
    limit = _optional_limit(limit, 100)
    cli = runtime.client("cn")
    if action == "search":
        begin, end = _required_date_pair(begin, end)
        data = cli.pdf_doc.search(
            stock_code=str(stock_code or ""), title=str(title or ""),
            announce_date_from=str(begin or ""), announce_date_to=str(end or ""),
            status="", kind=str(kind or ""), limit=limit)
    elif action == "read_markdown":
        if not any([file_key, source_url,
                    (stock_code and period)]):
            raise ValueError(
                "pdf.read_markdown 需要 file_key 或 source_url，或 stock_code+period")
        data = cli.pdf_doc.read_markdown(
            file_key=str(file_key or ""), source_url=str(source_url or ""),
            stock_code=str(stock_code or ""), period=str(period or ""))
    else:
        if not file_key and not source_url:
            raise ValueError("pdf.status 需要 file_key 或 source_url")
        data = cli.pdf_doc.status(file_key=str(file_key or ""),
                                  source_url=str(source_url or ""))
    return success(runtime, data, output=output, max_rows=max_rows,
                   action=action, stock_code=stock_code, market="cn")


def _symbol(context: str, value: str | None, *, allow_empty: bool = True) -> str:
    if value is None or not str(value).strip():
        if allow_empty:
            return ""
        raise ValueError(f"{context} 需要 symbol")
    return str(value).strip()



def _unique_symbols(values: Sequence[str]) -> list[str]:
    out = [str(value).strip() for value in values if str(value).strip()]
    if not out:
        raise ValueError("symbols 不能为空")
    return list(dict.fromkeys(out))


__all__ = [
    "backtest", "batch", "call", "company", "contract", "corporate",
    "disclosures", "dividend", "estimates", "etf", "futures", "history",
    "income", "intl", "macro", "market", "metrics", "notice", "pdf", "quote",
    "screen", "search", "segments", "statement", "status", "symbols", "toplist",
    "valuation",
]
