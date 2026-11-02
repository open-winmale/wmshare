"""Stable contracts shared by the tool registry, CLI, and tests."""

from __future__ import annotations

MAX_ROWS = 200
DEFAULT_MARKET = "cn"
MARKETS = ("cn", "hk", "us")
SOURCE = "wmshare MCP"
CONSOLE_URL = (
    "https://open.winmale.com/?utm_source=wmshare-mcp"
    "&utm_medium=mcp&utm_campaign=v1"
)
DOCS_URL = "https://github.com/open-winmale/wmshare/blob/main/docs/AI.md"
CREDENTIAL_PATH = "~/.wmshare/credentials.env"
TOOL_NAMES = (
    "wmshare_status",
    "wmshare_search",
    "wmshare_contract",
    "wmshare_symbols",
    "wmshare_quote",
    "wmshare_history",
    "wmshare_metrics",
    "wmshare_company",
    "wmshare_screen",
    "wmshare_disclosures",
    "wmshare_statement",
    "wmshare_segments",
    "wmshare_dividend",
    "wmshare_estimates",
    "wmshare_corporate",
    "wmshare_market",
    "wmshare_intl",
    "wmshare_notice",
    "wmshare_batch",
    "wmshare_call",
)
COMPANY_BLOCKS = (
    "profile",
    "income",
    "balance",
    "cashflow",
    "indicators",
    "dividend",
    "notices",
)
STATEMENT_ACTIONS = (
    "income", "balance", "cashflow", "audit", "compare", "tree", "years",
)
SEGMENT_ACTIONS = (
    "business", "products", "region", "income", "coverage", "periods", "snapshot",
)
DIVIDEND_ACTIONS = (
    "history", "last", "dps", "yield_ttm", "payout_ttm", "window_stats",
    "screen_quality", "screen_high_yield", "screen_undervalued_yield",
)
ESTIMATE_ACTIONS = (
    "forecast", "forecast_detail", "rating", "reports", "disclosure_history",
    "next_disclosure", "yjkb", "yjkb_latest", "yjyg", "yjyg_latest",
)
CORPORATE_ACTIONS = (
    "query_buyback_detail", "query_buyback_plan", "query_capital_change",
    "query_capital_change_at", "query_concert", "query_exec_change",
    "query_exec_change_at", "query_executives", "query_guarantee", "query_hgt",
    "query_holder10", "query_holdernum", "query_institution_detail",
    "query_institution_summary", "query_litigation", "query_national_team",
    "query_pledge_detail", "query_pledge_industry", "query_pledge_market",
    "query_pledge_org", "query_pledge_summary", "query_related_trade",
    "query_release", "query_reorg", "query_violation",
)
MARKET_DOMAINS = (
    "kline", "moneyflow", "margin", "cbond", "index", "valuation", "stocks",
)
MARKET_ACTIONS = {
    "kline": ("minute", "is_etf"),
    "moneyflow": ("bars", "last", "live"),
    "margin": ("query", "latest"),
    "cbond": ("universe", "latest_quotes", "of_stock", "query", "call_hits", "kline_window"),
    "index": ("keys", "members", "weights", "valuation"),
    "valuation": ("hist_stats",),
    "stocks": ("list",),
}
INTL_ACTIONS = (
    "query_ccass", "query_shareholders", "query_org_rating",
    "query_profit_forecast", "query_sellshort", "issue_info",
)
NOTICE_ACTIONS = (
    "list", "recent", "find", "by_category", "on_date",
    "has_buyback", "has_reduction",
)
