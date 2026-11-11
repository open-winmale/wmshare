"""R1 / M1：mcp/tools.py 表驱动补测——按运行时常量枚举全部分支路由。

不校验业务数值（那是 live 测试的事），只保证每个 action 都能穿过参数校验、
正确分派到 cli.<ns>.<method>()、并产出结构完整的成功信封。
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from wmshare import api as _api
from wmshare.api import _generated
from wmshare.client import BatchResult
from wmshare.mcp import tools
from wmshare.mcp.constants import (
    COMPANY_BLOCKS,
    CORPORATE_ACTIONS,
    DIVIDEND_ACTIONS,
    ESTIMATE_ACTIONS,
    INTL_ACTIONS,
    MARKET_ACTIONS,
    NOTICE_ACTIONS,
    SEGMENT_ACTIONS,
    STATEMENT_ACTIONS,
)
from wmshare.mcp.core import MCPRuntime
from wmshare.mcp.server import build_server


def _friendly_methods() -> frozenset[str]:
    """真实 friendly API 的方法名集合，用来锚定 tools.py 的分派目标。

    假对象若对任意方法名都返回样本，把 cli.kline.bars 改成 bars_TYPO
    也能 153 例全绿；这里让未知方法直接 AttributeError，分派目标必须
    在真实门面里存在才算通过。
    """
    names: set[str] = set()
    for mod in (_generated, _api):
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            names |= {name for name, _ in inspect.getmembers(cls, inspect.isfunction)
                      if not name.startswith("_")}
    return frozenset(names)


LEGAL_METHODS = _friendly_methods()


class _NS:
    """只接受真实 friendly API 方法名，返回可序列化的小样本。"""

    def __init__(self, ns: str) -> None:
        self.ns = ns

    def __getattr__(self, method: str):
        if method.startswith("_") or method not in LEGAL_METHODS:
            raise AttributeError(
                f"cli.{self.ns}.{method}() 不是真实 friendly API 方法；"
                "tools.py 的分派目标被改动或已失效")
        def call(*args, **kwargs):
            if method == "batch_live":
                return {"600519": {"close": 1.0}}
            return [{"ns": self.ns, "method": method, "close": 1.0}]
        return call


class _MatrixClient:
    last_ec_cost = 1

    def __init__(self) -> None:
        for ns in ("kline", "moneyflow", "margin", "cbond", "index", "valuation",
                   "stocks", "info", "statements", "indicator", "dividend", "notice",
                   "screener", "filings", "forecast", "workout", "intl", "segments",
                   "estimates", "equity"):
            setattr(self, ns, _NS(ns))

    def call(self, name, **kwargs):
        return [{"name": name, "close": 1.0}]

    def call_batch(self, name, symbols, **kwargs):
        return BatchResult(results={s: {"close": 1.0} for s in symbols},
                           requests=1, requested=len(symbols))

    def batch_iter(self, name, symbols, **kwargs):
        yield BatchResult(results={s: {"close": 1.0} for s in symbols},
                          requests=1, requested=len(symbols))


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(MCPRuntime, "client", lambda self, market=None: _MatrixClient())
    return MCPRuntime(demo=False)


def _ok(result, **meta_keys):
    assert result["ok"] is True
    assert result["meta"]["source"] == "wmshare MCP"
    for key, value in meta_keys.items():
        assert result["meta"][key] == value, f"meta.{key}"


# ---- company：每个 block 单独走一遍，覆盖 7 条 if 分支 ----
@pytest.mark.parametrize("block", list(COMPANY_BLOCKS))
def test_company_every_block(runtime, block):
    result = tools.company(runtime, "600519", include=[block])
    _ok(result, include=[block])
    assert block in result["data"]["blocks"]


def test_company_default_include(runtime):
    result = tools.company(runtime, "600519")
    _ok(result)
    # _limit_tree 会把 symbol 并进 blocks 字典，故用子集断言
    assert {"profile", "income", "indicators", "dividend", "notices"} <= set(
        result["data"]["blocks"])


@pytest.mark.parametrize("kwargs,match", [
    ({"include": ["nope"]}, "include 不支持"),
    ({"years": 0}, "years"),
    ({"limit": 101}, "limit"),
])
def test_company_invalid_params(runtime, kwargs, match):
    with pytest.raises(ValueError, match=match):
        tools.company(runtime, "600519", **kwargs)


# ---- market：MARKET_ACTIONS 全展开，覆盖 20+ 条 elif ----
def _market_cases():
    return [pytest.param(domain, action,
                         {"symbol": "600519", "key": "index.hs300", "trig": 110.0,
                          "n": 5, "points": 10, "sort_by": "weight", "top_n": 5},
                         id=f"{domain}.{action}")
            for domain, actions in MARKET_ACTIONS.items() for action in actions]


@pytest.mark.parametrize("domain,action,kwargs", _market_cases())
def test_market_every_action(runtime, domain, action, kwargs):
    result = tools.market(runtime, domain, action, **kwargs)
    _ok(result, domain=domain, action=action)


@pytest.mark.parametrize("domain,action,kwargs,match", [
    ("nope", "x", {}, "domain 只支持"),
    ("kline", "nope", {}, "action 只支持"),
    ("cbond", "call_hits", {"symbol": "600519"}, "需要 trig"),
    ("cbond", "kline_window", {"symbol": "600519"}, "需要 n"),
    ("index", "members", {}, "需要 key"),
    ("index", "valuation", {}, "需要 key"),
    ("index", "trend", {}, "需要 key"),
])
def test_market_invalid_params(runtime, domain, action, kwargs, match):
    with pytest.raises(ValueError, match=match):
        tools.market(runtime, domain, action, **kwargs)


def test_market_index_trend_passes_window(runtime):
    """``index.trend`` 必须把 MCP 的 window 透传给 SDK。

    旧实现写死 ``cli.index.trend(key)``，经 MCP 永远只能拿默认 5y 分位——而 MCP 的
    ``window`` 参数默认值又是 3y，两边不一致且调用方无法察觉。

    这里用 spy 客户端直接观察 SDK 收到什么，避免被 ``success()`` 的字典截断
    （>max_rows 时 points 被裁剪）干扰断言。
    """
    received: list[dict] = []

    class _SpyIndex:
        def __getattr__(self, name):
            def _fn(*a, **kw):
                received.append({"fn": name, "args": a, **kw})
                return {"ok": True, "key": "index.hs300", "window": kw.get("window"),
                        "points": [], "pct": {}}
            return _fn

    class _SpyClient:
        index = _SpyIndex()

    original = runtime.client
    runtime.client = lambda market=None: _SpyClient()
    try:
        for w in ("3y", "5y"):
            tools.market(runtime, "index", "trend", key="index.hs300", window=w)
    finally:
        runtime.client = original
    got = [c.get("window") for c in received]
    assert got == ["3y", "5y"], f"window 未透传给 cli.index.trend：{received}"


# ---- screen：boolean 8 个 + 其余 7 个 action ----
BOOLEAN_TESTS = ("limit_up", "limit_down", "above_ma20", "ma60_up",
                 "breakout_ma20", "momentum_20d", "pullback_20d", "volume_spike")
SCREEN_ACTIONS = (
    [("boolean", {"symbol": "600519", "test": t}) for t in BOOLEAN_TESTS]
    + [("breadth_summary", {}), ("breadth_bins", {}), ("breadth_industries", {}),
       ("top_movers", {}), ("query", {"where": "$ROE_TTM_LAST > 0.15"}),
       ("industries", {}), ("industry_members", {"industry": "银行"})]
)


@pytest.mark.parametrize("action,kwargs", SCREEN_ACTIONS)
def test_screen_every_action(runtime, action, kwargs):
    _ok(tools.screen(runtime, action, **kwargs), action=action)


@pytest.mark.parametrize("action,kwargs,match", [
    ("nope", {}, "action 不受支持"),
    ("boolean", {"symbol": "600519", "test": "nope"}, "test 只支持"),
    ("boolean", {"test": "limit_up"}, "需要 symbol"),
    ("query", {}, "需要 where"),
    ("industry_members", {}, "需要 industry"),
])
def test_screen_invalid_params(runtime, action, kwargs, match):
    with pytest.raises(ValueError, match=match):
        tools.screen(runtime, action, **kwargs)


# ---- notice / intl ----
@pytest.mark.parametrize("action", list(NOTICE_ACTIONS))
def test_notice_every_action(runtime, action):
    result = tools.notice(runtime, action, symbol="600519", category="回购",
                          date="2026-10-30", begin="2026-10-01", end="2026-10-31")
    _ok(result, action=action)


@pytest.mark.parametrize("kwargs,match", [
    ({"action": "nope"}, "action 只支持"),
    ({"action": "by_category"}, "需要 category"),
    ({"action": "on_date"}, "需要 date"),
])
def test_notice_invalid_params(runtime, kwargs, match):
    with pytest.raises(ValueError, match=match):
        tools.notice(runtime, symbol="600519", **kwargs)


@pytest.mark.parametrize("action", list(INTL_ACTIONS))
def test_intl_every_action(runtime, action):
    _ok(tools.intl(runtime, action, "00700", market="hk"), action=action)


def test_intl_rejects_cn_market(runtime):
    with pytest.raises(ValueError, match="只支持 market=hk/us"):
        tools.intl(runtime, "query_ccass", "00700", market="cn")


# ---- statement / segments / dividend / estimates / corporate ----
@pytest.mark.parametrize("action", list(STATEMENT_ACTIONS))
def test_statement_every_action(runtime, action):
    _ok(tools.statement(runtime, action, symbol="600519"), action=action)


@pytest.mark.parametrize("action", list(SEGMENT_ACTIONS))
def test_segments_every_action(runtime, action):
    result = tools.segments(runtime, action, symbol="600519")
    _ok(result, action=action)
    # meta.source 必须始终是信封数据源，清洗口径另占一个键
    assert result["meta"]["segment_source"] == "clean"
    assert result["meta"]["source"] == "wmshare MCP"


@pytest.mark.parametrize("action", list(DIVIDEND_ACTIONS))
def test_dividend_every_action(runtime, action):
    _ok(tools.dividend(runtime, action, symbol="600519", limit=5,
                       begin="2026-01-01", end="2026-10-31"), action=action)


@pytest.mark.parametrize("action", list(ESTIMATE_ACTIONS))
def test_estimates_every_action(runtime, action):
    _ok(tools.estimates(runtime, action, symbol="600519"), action=action)


@pytest.mark.parametrize("action", list(CORPORATE_ACTIONS))
def test_corporate_every_action(runtime, action):
    _ok(tools.corporate(runtime, action, symbol="600519", limit=5,
                        annual=2025, sampling="2025-Q4"), action=action)


def test_corporate_at_action_needs_annual_and_sampling(runtime):
    with pytest.raises(ValueError, match="需要同时提供 annual 和 sampling"):
        tools.corporate(runtime, "query_capital_change_at", symbol="600519")


# ---- disclosures / quote / 基础工具 ----
@pytest.mark.parametrize("kind,kwargs", [
    ("notice", {}), ("notice", {"symbol": "600519"}),
    ("notice", {"symbol": "600519", "begin": "2026-10-01", "end": "2026-10-31"}),
    ("filing", {"symbol": "600519"}), ("forecast", {"symbol": "600519"}),
    ("dividend", {"symbol": "600519"}), ("workout", {}),
    ("workout", {"symbol": "600519"}),
])
def test_disclosures_every_kind(runtime, kind, kwargs):
    _ok(tools.disclosures(runtime, kind=kind, **kwargs), kind=kind)


def test_disclosures_rejects_bad_date_pair(runtime):
    with pytest.raises(ValueError, match="需同时提供"):
        tools.disclosures(runtime, begin="2026-10-01")


@pytest.mark.parametrize("symbols,live", [
    (["600519"], True), (["600519"], False),
    (["600519", "000001"], True), (["600519", "000001"], False),
])
def test_quote_all_branches(runtime, symbols, live):
    _ok(tools.quote(runtime, symbols, live=live), live=live)


def test_batch_and_call_paths(runtime):
    _ok(tools.batch(runtime, "kline.query_bars", ["600519", "000001"]))
    _ok(tools.call(runtime, "kline.bars", mode="api"), mode="api")
    _ok(tools.call(runtime, "kline.query_bars", arguments={"sym": "600519"},
                   mode="catalog"), mode="catalog")


def test_basic_discovery_tools(runtime):
    _ok(tools.status(runtime))
    _ok(tools.search(runtime, "PE"))
    _ok(tools.contract(runtime, "kline.query_bars"))
    _ok(tools.symbols(runtime, "贵州"))
    _ok(tools.history(runtime, "600519"))
    _ok(tools.metrics(runtime, "600519", ["$PE_TTM_LAST"]))


@pytest.mark.parametrize("tool,arguments", [
    ("wmshare_status", {}),
    ("wmshare_search", {"query": "PE"}),
    ("wmshare_company", {"symbol": "600519", "include": ["profile"]}),
])
def test_pydantic_boundary_via_call_tool(runtime, tool, arguments):
    server = build_server(MCPRuntime(market="cn", demo=True))
    result = asyncio.run(server.call_tool(tool, arguments))
    assert isinstance(result, tuple) and result[1]["ok"] is True
