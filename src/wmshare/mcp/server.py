"""FastMCP protocol adapter.  All data rules live in ``core``/``tools``."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

import wmshare
from wmshare.mcp import apis
from wmshare.mcp.constants import DEFAULT_MARKET, MARKETS, MAX_ROWS, SOURCE, TOOL_NAMES
from wmshare.mcp.core import MCPRuntime, credential_values, error
from wmshare.mcp import tools

OutputMode = Literal["sample", "count", "summary"]
MarketName = Literal["cn", "hk", "us"]
MarketArg = Annotated[MarketName | None, Field(description="目标市场 cn/hk/us；缺省用 server 配置市场")]
OutputArg = Annotated[OutputMode, Field(description="sample 返回样例；count 只返回计数；summary 返回压缩摘要")]
MaxRowsArg = Annotated[int, Field(ge=1, le=MAX_ROWS, description="单次返回的最大行数，硬上限 200")]
LimitArg = Annotated[int, Field(ge=1, le=100, description="返回条数上限")]
DateArg = Annotated[str | None, Field(description="日期，格式 YYYY-MM-DD")]

StatementAction = Literal[
    "income", "balance", "cashflow", "indicators", "audit"
]
SegmentAction = Literal[
    "business", "products", "region", "income", "coverage", "periods", "snapshot"
]
DividendAction = Literal[
    "history", "last", "dps", "yield_ttm", "payout_ttm", "window_stats",
    "screen_quality", "screen_high_yield", "screen_undervalued_yield",
]
EstimateAction = Literal[
    "forecast", "forecast_detail", "rating", "reports", "disclosure_history",
    "next_disclosure", "yjkb", "yjkb_latest", "yjyg", "yjyg_latest",
]
CorporateAction = Literal[
    "query_buyback_detail", "query_buyback_plan", "query_capital_change",
    "query_capital_change_at", "query_concert", "query_exec_change",
    "query_exec_change_at", "query_executives", "query_guarantee", "query_hgt",
    "query_holder10", "query_holdernum", "query_institution_detail",
    "query_institution_summary", "query_litigation", "query_national_team",
    "query_pledge_detail", "query_pledge_industry", "query_pledge_market",
    "query_pledge_org", "query_pledge_summary", "query_related_trade",
    "query_release", "query_reorg", "query_violation",
]
MarketDomain = Literal[
    "kline", "moneyflow", "margin", "cbond", "index", "valuation", "stocks"
]
IntlAction = Literal[
    "query_ccass", "query_shareholders", "query_org_rating",
    "query_profit_forecast", "query_sellshort", "issue_info",
]
NoticeAction = Literal[
    "list", "recent", "find", "by_category", "on_date",
    "has_buyback", "has_reduction",
]
IncomeAction = Literal["rating", "diagnose", "calendar", "decomp"]
BacktestRule = Literal["ma_cross", "pe", "pb", "ps", "pr"]
EtfAction = Literal[
    "card", "nav", "share", "div", "portfolio",
    "profile", "premium", "asset", "rank",
]
MacroAction = Literal["query", "asof", "sampling", "reserve", "reserve_history"]
FxAction = Literal["rate", "history", "bars", "list"]
ValuationAction = Literal[
    "hist_stats", "daily_basic", "daily_basic_multi", "daily_basic_coverage"
]
ValuationMetric = Literal["pe", "pb", "ps", "pr"]
ToplistAction = Literal["by_date", "by_symbol"]
FuturesAction = Literal["get", "mapping", "snapshot", "bars"]
PdfAction = Literal["search", "read_markdown", "status"]
CompanyBlock = Literal[
    "profile", "income", "balance", "cashflow", "indicators", "dividend", "notices"
]
# 必须与 constants.MARKET_ACTIONS 的并集等量（见
# tests/test_mcp_apis.py::test_domain_action_enums_are_machine_readable）。
# 这里刻意保持静态 Literal：动态生成会同时踩 3.10 语法、mypy [valid-type]
# 与 FastMCP import 期 get_type_hints 求值三个坑。
MarketAction = Literal[
    "minute", "is_etf", "bars", "last", "live", "query", "latest", "universe",
    "latest_quotes", "of_stock", "call_hits", "kline_window", "keys", "members",
    "weights", "valuation", "hist_stats", "list", "trend", "universe_keys",
]


def runtime_from_env() -> MCPRuntime:
    market = credential_values()["WMSHARE_MARKET"] or DEFAULT_MARKET
    return MCPRuntime(market=market)


def build_server(runtime: MCPRuntime | None = None) -> FastMCP:
    """Create an MCP server.  Call ``run('stdio')`` in a CLI process."""
    rt = runtime or runtime_from_env()
    mcp = FastMCP(
        "wmshare",
        instructions=(
            f"{SOURCE}：29 个 task tools 覆盖高频与结论级数据面；长尾 friendly API 用 "
            "wmshare_call(mode='api')，目录函数批量用 wmshare_batch(params=...)。"
            "先离线 search/contract，再取数；多标的不要逐票循环。"
            "按意图选工具：估值分位→wmshare_metrics($PCT_*)或 "
            "wmshare_valuation(action='hist_stats')；指数估值→wmshare_market"
            "(domain='index')；全市场选股→wmshare_screen(action='query')；"
            "收息排行/诊断→wmshare_income；单股回测→wmshare_backtest；"
            "ETF 净值/溢价/持仓→wmshare_etf；宏观时序→wmshare_macro；"
            "龙虎榜→wmshare_toplist；期货主力→wmshare_futures；"
            "公告 PDF 结构化→wmshare_pdf；名字/代码不确定→先 "
            "wmshare_search/wmshare_symbols。"
            "比率/涨跌幅/分位默认小数（0.0396=3.96%），金额=元，量=股；"
            "screener 宽度接口的 *_pct 字段是百分数数值（80.3=80.3%）。"
            "DataError 是数据守护报警，不要静默忽略。"
        ),
    )

    def protocol(tool_fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(tool_fn)
        def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return tool_fn(*args, **kwargs)
            except Exception as exc:  # MCP boundary converts failures to data.
                return error(exc, rt)
        return wrapped

    @mcp.tool()
    @protocol
    def wmshare_status(
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 50,
    ) -> dict[str, Any]:
        """查看版本、市场、凭证、目录、能力覆盖和配置指引（零凭证可用）。"""
        return tools.status(rt, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_search(
        query: Annotated[str, Field(description="中文关键词、英文函数名、指标码、标的名或代码")],
        kind: Annotated[
            Literal["all", "function", "metric", "symbol", "api"],
            Field(description=f"检索类型；api 搜索 {apis.route_count()} 个 SDK friendly API"),
        ] = "all",
        market: MarketArg = None,
        limit: Annotated[int, Field(ge=1, le=50, description="最多返回条数")] = 10,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 20,
    ) -> dict[str, Any]:
        """离线搜索函数、指标码、friendly API 和标的；任何名字/代码先查这里。"""
        return tools.search(rt, query, kind=kind, market=market, limit=limit,
                            output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_contract(
        name: Annotated[str, Field(description="目录函数名、指标码或 friendly API target")],
        kind: Annotated[
            Literal["function", "metric", "api"],
            Field(description="合同类型：catalog function、指标码或 SDK friendly API"),
        ] = "function",
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 50,
    ) -> dict[str, Any]:
        """查询函数、指标或 friendly API 合同：参数、返回、单位、示例、推荐 tool。"""
        return tools.contract(rt, name, kind=kind, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_symbols(
        query: Annotated[str, Field(description="公司名、拼音、别名或证券代码")],
        market: MarketArg = None,
        limit: Annotated[int, Field(ge=1, le=50, description="最多返回标的数")] = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 20,
    ) -> dict[str, Any]:
        """把公司名、拼音、别名或代码解析为 SDK 标的代码。"""
        return tools.symbols(rt, query, market=market, limit=limit,
                             output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_quote(
        symbols: Annotated[list[str], Field(description="同市场标的列表；多只自动批量，不要逐票循环")],
        market: MarketArg = None,
        live: Annotated[bool, Field(description="true=盘中最新；false=最近快照")] = True,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 50,
    ) -> dict[str, Any]:
        """取一只或多只同市场标的的最新/盘中报价；多只自动批量。"""
        return tools.quote(rt, symbols, market=market, live=live,
                           output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_history(
        symbol: Annotated[str, Field(description="标的代码；先用 wmshare_symbols 解析")],
        market: MarketArg = None,
        n: Annotated[int | None, Field(ge=1, le=10000, description="最近 K 线根数；与 begin/end 二选一")] = None,
        adj: Annotated[Literal["qfq", "hfq"] | None, Field(description="复权：qfq 前复权或 hfq 后复权")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取个股日 K：支持 n、前/后复权和 begin/end 区间；begin/end 必须成对。"""
        return tools.history(rt, symbol, market=market, n=n, adj=adj,
                             begin=begin, end=end, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_metrics(
        symbol: Annotated[str, Field(description="标的代码")],
        codes: Annotated[list[str], Field(description="离线目录中真实存在的指标码；先 search 再调用")],
        market: MarketArg = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """先校验指标码存在，再批量取一只标的的多个指标当前值。"""
        return tools.metrics(rt, symbol, codes, market=market,
                             output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_company(
        symbol: Annotated[str, Field(description="标的代码")],
        market: MarketArg = None,
        include: Annotated[list[CompanyBlock] | None, Field(description="公司研究包含的块；缺省取高频研究包")] = None,
        years: Annotated[int, Field(ge=1, le=10, description="报表年份数")] = 3,
        limit: Annotated[int, Field(ge=1, le=100, description="分红/公告等块条数")] = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取公司研究包：档案、报表、指标、分红、公告等可选块。"""
        return tools.company(rt, symbol, market=market, include=include,
                             years=years, limit=limit, output=output,
                             max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_screen(
        action: Annotated[
            Literal[
                "boolean", "breadth_summary", "breadth_bins", "breadth_industries",
                "top_movers", "industries", "industry_members", "query",
            ],
            Field(description="筛选动作；boolean 需要 symbol/test，query 需要 where"),
        ],
        symbol: Annotated[str | None, Field(description="单票筛选用的标的代码")] = None,
        test: Annotated[
            Literal[
                "limit_up", "limit_down", "above_ma20", "ma60_up", "breakout_ma20",
                "momentum_20d", "pullback_20d", "volume_spike",
            ] | None,
            Field(description="action=boolean 时的筛选器"),
        ] = None,
        params: Annotated[dict[str, Any] | None, Field(description="筛选器额外参数，如 min_chg/min_ratio；query 可带 order/offset/fields")] = None,
        idx: Annotated[str | None, Field(description="宽度/涨跌榜/条件选股的服务端索引键")] = None,
        industry: Annotated[str | None, Field(description="industry_members 需要的行业 id")] = None,
        limit: LimitArg = 20,
        desc: Annotated[bool, Field(description="top_movers / query 的 order 是否降序")] = True,
        where: Annotated[str | None, Field(description="action=query 的条件表达式（$码 用 && / || / !，比率=小数）")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 100,
    ) -> dict[str, Any]:
        """取单票筛选、全市场条件选股、宽度、行业分布、涨跌榜或行业成分。

        示例：action='query', where='$ROE_TTM_LAST>0.15', limit=20（全市场条件选股，
        data.count=真实命中数）；action='breadth_summary'（涨跌全景）；
        action='boolean', symbol='600519', test='above_ma20'（单票筛选）。"""
        return tools.screen(rt, action, symbol=symbol, test=test, params=params,
                            idx=idx, industry=industry, limit=limit, desc=desc,
                            where=where, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_disclosures(
        kind: Annotated[
            Literal["notice", "filing", "forecast", "dividend", "workout"],
            Field(description="披露族；高级公告查询请用 wmshare_notice"),
        ] = "notice",
        symbol: Annotated[str | None, Field(description="单票查询标的；部分全市场查询可空")] = None,
        market: MarketArg = None,
        window: Annotated[str, Field(description="相对窗口，如 3m/6m/1y 或正整数天数")] = "3m",
        keyword: Annotated[str, Field(description="公告标题关键词")] = "",
        begin: DateArg = None,
        end: DateArg = None,
        limit: LimitArg = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 100,
    ) -> dict[str, Any]:
        """取公告、定期报告、业绩事件、分红历史或契约套利事件。

        示例：kind='notice', symbol='600519', window='3m'（近三个月公告）；
        kind='filing'（定期报告清单）；kind='dividend', symbol='600519'（分红历史）。
        公告 PDF 正文结构化请用 wmshare_pdf。"""
        return tools.disclosures(rt, kind, symbol=symbol, market=market,
                                 window=window, keyword=keyword, begin=begin,
                                 end=end, limit=limit, output=output,
                                 max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_statement(
        action: Annotated[StatementAction, Field(description="报表动作")],
        symbol: Annotated[str | None, Field(description="标的代码；所有 action 都需要")] = None,
        market: MarketArg = None,
        years: Annotated[int, Field(ge=1, le=10, description="报表期数")] = 5,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取三大报表（cn/hk/us 宽表）或审计意见。"""
        return tools.statement(rt, action, symbol=symbol, market=market,
                               years=years, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_segments(
        action: Annotated[SegmentAction, Field(description="经营分部动作")],
        symbol: Annotated[str | None, Field(description="标的代码；所有 action 都需要")] = None,
        market: MarketArg = None,
        source: Annotated[
            Literal["clean", "raw"],
            Field(description="分部数据源：clean 规范视图或 raw 原始视图"),
        ] = "clean",
        limit: LimitArg = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取经营分部的业务、产品、区域、收入、覆盖期、期间或四维快照。"""
        return tools.segments(rt, action, symbol=symbol, market=market,
                              source=source, limit=limit, output=output,
                              max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_dividend(
        action: Annotated[DividendAction, Field(description="分红动作")],
        symbol: Annotated[str | None, Field(description="标的代码；所有 action 都需要")] = None,
        market: MarketArg = None,
        limit: Annotated[int | None, Field(ge=1, le=1000, description="history 返回条数")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        window: Annotated[str, Field(description="window_stats 窗口，如 3y/5y")] = "3y",
        min_yield: Annotated[float | None, Field(description="最低股息率，小数；0.03=3%")] = None,
        payout_min: Annotated[float | None, Field(description="派息率下限，小数")] = None,
        payout_max: Annotated[float | None, Field(description="派息率上限，小数")] = None,
        min_pct: Annotated[float | None, Field(description="低估高分红的估值分位门槛，小数")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取分红历史、DPS、TTM 指标、窗口统计和质量筛选；率值均为小数。

        示例：action='yield_ttm', symbol='600519'（TTM 股息率 0.0396=3.96%）；
        action='screen_quality', symbol='600519'（单票质量筛选）。
        全市场收息排行/单票诊断请用 wmshare_income。"""
        return tools.dividend(rt, action, symbol=symbol, market=market,
                              limit=limit, begin=begin, end=end, window=window,
                              min_yield=min_yield, payout_min=payout_min,
                              payout_max=payout_max, min_pct=min_pct,
                              output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_income(
        action: Annotated[IncomeAction, Field(description="rating=全市场排行 / diagnose=批量诊断 / calendar=分红日历 / decomp=N 年持有收益拆解")],
        symbols: Annotated[list[str] | None, Field(description="diagnose/decomp 需要的标的列表（decomp ≤10 只）")] = None,
        top_n: Annotated[int, Field(ge=1, le=200, description="rating 排行条数")] = 20,
        grade: Annotated[str | None, Field(description="rating 评级过滤（如 strong）")] = None,
        industry: Annotated[str | None, Field(description="rating 行业过滤")] = None,
        min_yield: Annotated[float | None, Field(description="rating 最低股息率，小数；0.04=4%")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        years: Annotated[int, Field(ge=1, le=10, description="decomp 持有年数（口径 3/5/10）")] = 10,
        include_history: Annotated[bool, Field(description="diagnose deep 档：带分红史与方案（+18k EC/票）")] = False,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """收息闭环（仅 A 股）：全市场排行、批量诊断、分红日历、N 年持有收益拆解。

        rating ≈15k~70k EC 且榜单由 cron 物化（16:50/19:40）——冷缓存返回
        ok=false 时如实转述稍后重试，勿现场重算全市场评分。
        """
        return tools.income(rt, action, symbols=symbols, top_n=top_n,
                            grade=grade, industry=industry, min_yield=min_yield,
                            begin=begin, end=end, years=years,
                            include_history=include_history,
                            output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_estimates(
        action: Annotated[EstimateAction, Field(description="盈利预测/评级/研报/披露日动作")],
        symbol: Annotated[str | None, Field(description="标的代码；所有 action 都需要")] = None,
        market: MarketArg = None,
        limit: LimitArg = 8,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取机构盈利预测、预测明细、评级、研报和财报披露日程。

        示例：action='forecast', symbol='600519'（逐年 EPS/PE）；
        action='next_disclosure', symbol='600519'（下次披露日）；
        action='yjkb_latest'（最新业绩快报）。"""
        return tools.estimates(rt, action, symbol=symbol, market=market,
                               limit=limit, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_corporate(
        action: Annotated[CorporateAction, Field(description="公司治理/股权/质押/增减持动作")],
        symbol: Annotated[str | None, Field(description="标的代码；全市场质押汇总 actions 可空")] = None,
        market: MarketArg = None,
        limit: LimitArg = 20,
        annual: Annotated[int | None, Field(description="*_at 查询的年报年度，如 2024")] = None,
        sampling: Annotated[str | None, Field(description="*_at 查询的报告期采样，如 Q4")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取股东、股本、增减持、质押、回购、高管、担保、诉讼、违规和机构持仓。

        示例：action='query_holder10', symbol='600519'（十大股东）；
        action='query_pledge_summary', symbol='600519'（质押汇总）；
        action='query_release', symbol='600519'（解禁排期）。"""
        return tools.corporate(rt, action, symbol=symbol, market=market,
                               limit=limit, annual=annual, sampling=sampling,
                               output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_market(
        domain: Annotated[
            MarketDomain,
            Field(description="市场数据域：分钟/资金流/两融/转债/指数/估值/证券全集"),
        ],
        action: Annotated[MarketAction, Field(description="domain 下的动作；运行时会校验合法组合")],
        symbol: Annotated[str | None, Field(description="标的代码；全集/转债全市场/指数 keys 可空")] = None,
        market: MarketArg = None,
        key: Annotated[str | None, Field(description="指数键；members/weights/valuation 需要")] = None,
        n: Annotated[int | None, Field(ge=1, le=10000, description="历史窗口条数")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        points: Annotated[int | None, Field(ge=1, le=1000, description="指数估值时序采样点数")] = None,
        sort_by: Annotated[str | None, Field(description="指数成分排序字段")] = None,
        top_n: Annotated[int | None, Field(ge=1, le=200, description="指数成员/权重返回条数")] = None,
        metric: Annotated[
            Literal["pe", "pb", "ps", "pr"],
            Field(description="估值历史指标；金融/亏损股建议 pb"),
        ] = "pe",
        window: Annotated[str, Field(description="估值历史窗口，最大 3y")] = "3y",
        level: Annotated[int | None, Field(ge=1, le=3, description="行业目录层级")] = None,
        trig: Annotated[float | None, Field(description="可转债强赎触发价，元")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取 1 分钟分时、资金流、两融、可转债、指数、估值历史和证券全集。

        示例：domain='index', action='trend', key='index.hs300'（PE/PB 历史分位）；
        domain='cbond', action='latest_quotes'（转债全市场面板）；
        domain='moneyflow', action='bars', symbol='600519', n=20（主力资金流）。"""
        return tools.market(rt, domain, action, symbol=symbol, market=market,
                            key=key, n=n, begin=begin, end=end, points=points,
                            sort_by=sort_by, top_n=top_n, metric=metric,
                            window=window, level=level, trig=trig,
                            output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_valuation(
        action: Annotated[ValuationAction, Field(description="hist_stats=历史分位统计 / daily_basic=单票基础指标 / daily_basic_multi=多票 / daily_basic_coverage=覆盖面")],
        symbol: Annotated[str | None, Field(description="标的代码；daily_basic_multi 用 symbols")] = None,
        symbols: Annotated[list[str] | None, Field(description="daily_basic_multi 需要的标的列表")] = None,
        metric: Annotated[ValuationMetric, Field(description="hist_stats 指标；金融/亏损股建议 pb")] = "pe",
        window: Annotated[str, Field(description="hist_stats 窗口 3y/5y/10y（未知窗口显式报错）")] = "3y",
        begin: DateArg = None,
        end: DateArg = None,
        fields: Annotated[str | None, Field(description="daily_basic 列投影，逗号分隔")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """估值历史统计与基础指标（仅 A 股）：PE/PB/PS/PR 的均值/中位/分位与多日多票面板。

        示例：action='hist_stats', symbol='600519', metric='pe', window='5y'；
        action='daily_basic_multi', symbols=['600519','000001'], begin=..., end=...。
        指数/行业的估值分位走 wmshare_market(domain='index', action='trend')。
        """
        return tools.valuation(rt, action, symbol=symbol, symbols=symbols,
                               metric=metric, window=window, begin=begin,
                               end=end, fields=fields, output=output,
                               max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_etf(
        action: Annotated[EtfAction, Field(description="card=一页档案 / nav=净值 / share=份额 / div=分红 / portfolio=持仓 / profile=产品档案 / premium=折溢价 / asset=资产配置 / rank=榜单指标")],
        symbol: Annotated[str, Field(description="ETF 场内代码，如 510300.SH 或裸码")],
        mode: Annotated[
            Literal["latest", "series"],
            Field(description="latest=当前值；series=时序（card/nav/share/premium 支持）"),
        ] = "latest",
        limit: Annotated[int | None, Field(ge=1, le=200, description="rank 返回条数")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """ETF 九视图（仅 A 股场内）：档案/净值/份额/分红/持仓/折溢价/资产配置/榜单一次取齐。

        示例：action='card', symbol='510300'（九路数据合一页）；
        action='premium', symbol='510300', mode='series'（折溢价时序）；
        action='portfolio', symbol='510300'（最新季前十大持仓）。
        """
        return tools.etf(rt, action, symbol=symbol, mode=mode, limit=limit,
                         output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_backtest(
        symbol: Annotated[str, Field(description="标的代码（仅 A 股）")],
        rule: Annotated[BacktestRule, Field(description="ma_cross=均线金叉/死叉；pe/pb/ps/pr=估值阈值")] = "ma_cross",
        fast: Annotated[int | None, Field(ge=2, le=250, description="ma_cross 快线周期")] = None,
        slow: Annotated[int | None, Field(ge=2, le=250, description="ma_cross 慢线周期")] = None,
        buy: Annotated[float | None, Field(description="估值规则买入阈值（pe/pb 为倍数）")] = None,
        sell: Annotated[float | None, Field(description="估值规则卖出阈值")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        adj: Annotated[str | None, Field(description="复权 qfq/hfq；缺省 qfq")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 100,
    ) -> dict[str, Any]:
        """单股买卖点回测（仅 A 股）：成交明细 + 净值/回撤/胜率，固定口径次日开盘、T+1、整手。

        固定参数不可调：初始资金 100 万、佣金/印花固定、100 股整手。
        全历史估值回测可达 ~40 万 EC——先用 wmshare_call(mode='cost') 预估再跑。
        """
        return tools.backtest(rt, symbol, rule=rule, fast=fast, slow=slow,
                              buy=buy, sell=sell, begin=begin, end=end,
                              adj=adj, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_macro(
        action: Annotated[MacroAction, Field(description="query=近 n 期时序 / asof=最新一期值 / sampling=采样频率 / reserve=储备项清单 / reserve_history=储备时序（code 传 forex 或 gold）")],
        code: Annotated[str, Field(description="宏观指标码，如 $CPI/$GDP/$M2；先 wmshare_search 查码")],
        n: Annotated[int, Field(ge=1, le=100, description="query 返回期数")] = 6,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """宏观指标时序/最新值/采样频率（上游原值口径：价格指数=点、流量存量=元、收益率=小数）。

        示例：action='query', code='$CPI', n=6（近 6 个月 CPI）；
        action='asof', code='$GDP'（最新一期 GDP）；action='sampling', code='$CPI'；
        action='reserve', code='forex'（储备项清单，含 sdr 不可用标注）；
        action='reserve_history', code='forex', n=12（近 12 个月储备时序）。
        储备值单位：美元数值（外汇≈3.4e12、黄金≈3.1e11），非亿元/非亿美元。
        """
        return tools.macro(rt, action, code=code, n=n, output=output,
                           max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_fx(
        action: Annotated[FxAction, Field(description="rate=最新汇率 / history=日线 / bars=区间日线 / list=在库币种")],
        ccy: Annotated[str, Field(description="币种 ISO 代码，如 USD/EUR/JPY/HKD；list 时可留空")] = "USD",
        n: Annotated[int, Field(ge=1, le=500, description="history 返回根数")] = 30,
        begin: Annotated[str | None, Field(description="bars 起始日 YYYY-MM-DD")] = None,
        end: Annotated[str | None, Field(description="bars 结束日 YYYY-MM-DD")] = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """人民币外汇汇率（央行中间价 + 中行牌价，日频；每 1 单位外币折人民币）。

        middle/buy 均为「每 1 单位外币折人民币」（USD≈7.1、JPY≈0.042、HKD≈0.86）；
        上游原始中间价是每 100 外币口径（美元≈710），SDK 已统一 /100 归一。
        middle=央行中间价（缺失前向填充、连续）；buy=中行汇买价（仅发布日写入、可能有缺口）。

        示例：action='rate', ccy='USD'（最新美元中间价）；
        action='history', ccy='USD', n=30（近 30 个交易日）；action='list'（在库币种）。
        """
        return tools.fx(rt, action, ccy=ccy, n=n, begin=begin, end=end,
                        output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_toplist(
        action: Annotated[ToplistAction, Field(description="by_date=按交易日全榜 / by_symbol=按标的上榜历史")],
        symbol: Annotated[str | None, Field(description="by_symbol 需要的标的代码")] = None,
        trade_date: Annotated[str | None, Field(description="by_date 需要的交易日 YYYY-MM-DD")] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="返回条数")] = 100,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """龙虎榜（仅 A 股）：按交易日取全榜或按标的取上榜历史。

        成本实测：冷查 ≈12,837 EC、热查 ≈154 EC——用近期交易日更省。
        示例：action='by_date', trade_date='2026-11-20'；
        action='by_symbol', symbol='600519'。
        """
        return tools.toplist(rt, action, symbol=symbol, trade_date=trade_date,
                             limit=limit, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_futures(
        action: Annotated[FuturesAction, Field(description="get=合约字段取值 / mapping=主力连续映射 / snapshot=合约快照 / bars=主力连续历史K线")],
        code: Annotated[str | None, Field(description="get/snapshot/bars 需要的主力连续代码，如 AL.SHF / RB.SHF / global.CL")] = None,
        symbol: Annotated[str | None, Field(description="mapping 需要的品种代码，如 RB")] = None,
        field: Annotated[str, Field(description="get 的字段（close/open/…）")] = "close",
        freq: Annotated[str | None, Field(description="频率 d/w/m；snapshot/bars 缺省 d")] = None,
        native: Annotated[bool, Field(description="get=true 保留上游原值口径")] = False,
        n: Annotated[int | None, Field(description="bars 取最近 n 根（日频为交易日根数；默认 120；与 begin/end 二选一）")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """期货主力数据（74 商品+8 金融）：合约字段、主力连续映射、合约快照、历史K线。

        get/snapshot/bars 走 store 直读（交易日行、最新一根随上游日更；snapshot
        输出含 date）。mapping 冷查实测 ≈21.4 万 EC、热查 ≈141 EC——先
        wmshare_call(mode='cost') 预估；begin/end 需成对提供。bars 按行计费
        （冷 ≈190+126 EC/行、同日复跑版本键缓存 ≈135 EC；行数硬顶 d 3000/w 600/m 300），
        长区间建议 freq='m'；周/月线为上游周期 bar（不做二次聚合）。
        """
        return tools.futures(rt, action, code=code, symbol=symbol, field=field,
                             freq=freq, native=native, n=n, begin=begin, end=end,
                             output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_pdf(
        action: Annotated[PdfAction, Field(description="search=检索公告文件 / read_markdown=正文结构化为 Markdown / status=解析状态")],
        stock_code: Annotated[str | None, Field(description="search/read_markdown 的标的代码")] = None,
        title: Annotated[str | None, Field(description="search 的标题关键词")] = None,
        begin: DateArg = None,
        end: DateArg = None,
        kind: Annotated[str | None, Field(description="search 的公告类别过滤")] = None,
        file_key: Annotated[str | None, Field(description="read_markdown/status 的文件键（search 结果里拿）")] = None,
        source_url: Annotated[str | None, Field(description="read_markdown/status 的公告原文 URL")] = None,
        period: Annotated[str | None, Field(description="read_markdown 的报告期，如 2025-12-31（配 stock_code 直取定期报告）")] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="search 返回条数")] = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """公告 PDF 结构化（仅 A 股，wmshare 独有面）：检索→状态→正文 Markdown。

        示例：action='search', stock_code='600519'（该司可解析公告）；
        action='read_markdown', stock_code='600519', period='2025-12-31'
        （年报正文结构化）；action='read_markdown', file_key=...。
        报告正文结构化走这里，不要用 wmshare_notice 拿原文链接。
        """
        return tools.pdf(rt, action, stock_code=stock_code, title=title,
                         begin=begin, end=end, kind=kind, file_key=file_key,
                         source_url=source_url, period=period, limit=limit,
                         output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_intl(
        action: Annotated[IntlAction, Field(description="港美股专项动作")],
        symbol: Annotated[str, Field(description="港股或美股标的代码")],
        market: MarketArg = None,
        limit: LimitArg = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取 CCASS、主要股东、评级、盈利预测、沽空或美股发行信息；market 必须 hk/us。"""
        return tools.intl(rt, action, symbol=symbol, market=market,
                          limit=limit, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_notice(
        action: Annotated[NoticeAction, Field(description="公告高级查询动作")],
        symbol: Annotated[str | None, Field(description="标的代码；recent/by_category/on_date 可空")] = None,
        market: MarketArg = None,
        category: Annotated[str | None, Field(description="by_category 需要的公告类别")] = None,
        date: Annotated[str | None, Field(description="on_date 需要的 YYYY-MM-DD 日期")] = None,
        window: Annotated[str, Field(description="相对窗口，如 3m/6m/1y")] = "3m",
        keyword: Annotated[str, Field(description="公告标题关键词")] = "",
        begin: DateArg = None,
        end: DateArg = None,
        limit: LimitArg = 20,
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """取公告列表、按类别/日期查询、单票区间和回购/减持布尔信号。"""
        return tools.notice(rt, action, symbol=symbol, market=market,
                            category=category, date=date, window=window,
                            keyword=keyword, begin=begin, end=end,
                            limit=limit, output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_batch(
        function: Annotated[str, Field(description="目录函数名；先用 search/contract 确认")],
        symbols: Annotated[list[str], Field(description="同市场标的列表；不要混合 cn/hk/us")],
        market: MarketArg = None,
        batch_size: Annotated[int | None, Field(ge=1, le=500, description="每批标的数")] = None,
        on_batch_error: Annotated[
            Literal["raise", "skip"],
            Field(description="批级错误策略；skip 仍会记录失败批"),
        ] = "skip",
        params: Annotated[dict[str, Any] | None, Field(description="透传给 batch_iter 的目录函数参数")] = None,
        raw: Annotated[bool, Field(description="true 跳过单位规范化，仅诊断用")] = False,
        units: Annotated[
            Literal["base", "native"],
            Field(description="base 保持 SDK 单位守护；native 保留脚本原值"),
        ] = "base",
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = MAX_ROWS,
    ) -> dict[str, Any]:
        """批量调用目录函数；支持 params，返回请求数、错误和 429 续跑位置。"""
        return tools.batch(rt, function, symbols, market=market,
                           batch_size=batch_size, on_batch_error=on_batch_error,
                           params=params, raw=raw, units=units,
                           output=output, max_rows=max_rows)

    @mcp.tool()
    @protocol
    def wmshare_call(
        target: Annotated[str, Field(description="catalog function 或 friendly API 的 domain.method")],
        arguments: Annotated[dict[str, Any] | None, Field(description="目标函数/method 的公开参数")] = None,
        market: MarketArg = None,
        mode: Annotated[
            Literal["catalog", "api", "cost"],
            Field(description="catalog=目录函数；api=SDK friendly API；cost=成本估算（不发请求）"),
        ] = "catalog",
        raw: Annotated[bool, Field(description="true 跳过单位规范化，仅诊断用")] = False,
        units: Annotated[
            Literal["base", "native"],
            Field(description="base 保持 SDK 单位守护；native 保留脚本原值"),
        ] = "base",
        output: OutputArg = "sample",
        max_rows: MaxRowsArg = 100,
    ) -> dict[str, Any]:
        """受控通用网关：目录函数和全部 friendly API 的长尾兜底；禁止 _df。

        cbond.figures / cbond.article 会写任意路径，网关不开放（改本地 SDK）；
        单次调用 EC 超过部署上限（WMSHARE_MCP_MAX_EC）会报 ec_budget。
        """
        return tools.call(rt, target, arguments=arguments, market=market,
                          mode=mode, raw=raw, units=units,
                          output=output, max_rows=max_rows)

    _add_resources(mcp, rt)
    _add_prompts(mcp)
    return mcp


def _add_resources(mcp: FastMCP, rt: MCPRuntime) -> None:
    @mcp.resource("wmshare://overview")
    def overview() -> str:
        stats = wmshare.load().stats()
        return (
            f"{SOURCE} v{wmshare.__version__}；市场 {rt.market}。"
            f"目录：{stats['domains']} 个数据域、{stats['functions']} 个底层函数；"
            f"friendly API {apis.route_count()} 个。先用 search/contract，"
            "再用 task tools / batch / call。"
        )

    @mcp.resource("wmshare://setup")
    def setup() -> str:
        return (
            "真实取数需要开放平台 AppID。打开 open.winmale.com 登录 → "
            "右上角「我的」→「开放平台」→「我的应用」，复制 client_id 与 api-key；"
            "然后运行 wmshare-mcp setup --client-id <CLIENT_ID> "
            "--client-secret-stdin --market cn，再运行 wmshare-mcp doctor。"
            "凭证只写入 ~/.wmshare/credentials.env；零凭证可用 status/search/contract。"
        )

    @mcp.resource("wmshare://units")
    def units() -> str:
        return (
            "基础单位：比率/涨跌幅/分位=小数（0.0396=3.96%，0.42=42% 分位）；"
            "金额/价格/市值=元；股数/成交量=股。唯一常见例外是 screener 宽度接口"
            "的 *_pct/pct_of_total（80.3 表示 80.3%），median_pct 与涨跌幅仍是小数。"
            "units=native 仅用于诊断，会绕开默认规范化；raw=True（SDK 侧 _raw）同理，"
            "两者都会在返回信封里标出 meta.guards_off=true，禁止把诊断结果当已守护数据。"
        )

    @mcp.resource("wmshare://limits")
    def limits() -> str:
        return (
            "批量走 wmshare_batch，A 股全市场约 12 次请求；一个批次只能一个市场。"
            "429 返回 partial=true、error.kind=LimitError、retry_after_seconds、"
            "completed、resume_start 和 resume_symbols；不要重试已完成部分。"
            "等待限流窗口后用 symbols[resume_start:] 或 resume_symbols 续跑。"
            "单次 MCP 输出最多 200 行，超限时用 summary/count 或缩小范围。"
        )

    @mcp.resource("wmshare://coverage")
    def coverage() -> str:
        routes = apis.api_routes()
        by_domain: dict[str, int] = {}
        for route in routes:
            by_domain[route.domain] = by_domain.get(route.domain, 0) + 1
        payload = {
            "catalog_functions": wmshare.load().stats().get("functions"),
            "friendly_apis": len(routes),
            "friendly_apis_by_domain": dict(sorted(by_domain.items())),
            "first_class_tools": len(TOOL_NAMES),
            "api_gateway": "wmshare_call(mode='api')",
            "catalog_gateway": "wmshare_call(mode='catalog')",
            "cost_gateway": "wmshare_call(mode='cost')",
            "batchable_catalog_functions": len(apis.batchable_catalog_functions()),
            "excluded_from_mcp": ["pandas DataFrame / _df=True", "notice_poller", "长驻订阅"],
            "contract_paths": [
                "wmshare_search(kind='api')",
                "wmshare_contract(kind='api')",
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @mcp.resource("wmshare://routing")
    def routing() -> str:
        payload = {
            "workflow": [
                "wmshare_status 查看凭证与能力",
                "wmshare_symbols/wmshare_search 解析标的、函数、指标或 API",
                "wmshare_contract 查参数与单位",
                "优先用 task tool；多标的用 wmshare_batch",
                "长尾用 wmshare_call(mode='catalog' 或 'api')；"
                "调用前估算 EC 用 wmshare_call(mode='cost', target=..., arguments={...})",
            ],
            "task_tools": list(TOOL_NAMES),
            "generic_modes": {
                "catalog": "目录函数；参数必须匹配离线目录合同",
                "api": "SDK friendly API；参数必须匹配真实方法签名",
            },
            "context_guard": "长结果先 output=summary/count，再按需 sample",
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @mcp.resource("wmshare://catalog/function/{name}")
    def function_contract(name: str) -> str:
        data = wmshare.load().function(name)
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    @mcp.resource("wmshare://api/{target}")
    def api_contract(target: str) -> str:
        return json.dumps(apis.route_contract(target), ensure_ascii=False, sort_keys=True)


def _add_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def wmshare_quick_analysis(symbol: str) -> str:
        return (
            f"请分析 {symbol}：先用 wmshare_symbols 确认代码，再用 wmshare_history 取近 120 根日 K、"
            "wmshare_metrics 取 PE_TTM 和 TTM 股息率相关目录码，wmshare_notice(action='list') 取近 3 个月公告；"
            "所有率/分位按基础单位读数，最终给出事实和风险。"
        )

    @mcp.prompt()
    def wmshare_fundamental_report(symbol: str) -> str:
        return (
            f"请用 wmshare_company 分析 {symbol}：包含 profile、income、balance、cashflow、"
            "indicators、dividend、notices；用 wmshare_statement/segments 补深挖视图，"
            "先用 output=summary 概览，再对需要的块取 sample。"
        )

    @mcp.prompt()
    def wmshare_market_screen() -> str:
        return (
            "请先用 wmshare_screen(action='breadth_summary') 判断市场宽度，"
            "再看 top_movers 或 industry_members；候选标的用 wmshare_batch 批量核对，"
            "不要逐票循环请求。"
        )


__all__ = ["build_server", "runtime_from_env", "MARKETS"]
