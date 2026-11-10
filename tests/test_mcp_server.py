"""MCP tool registry, offline contracts, envelopes, and error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterator

import pytest

pytest.importorskip("mcp")

from wmshare.client import BatchResult
from wmshare.errors import (
    AuthError,
    CatalogError,
    DataError,
    LimitError,
    UsageError,
)
from wmshare.mcp.constants import TOOL_NAMES
from wmshare.mcp.core import MCPRuntime, error
from wmshare.mcp.server import build_server
from wmshare.mcp import tools


class FakeClient:
    market = "cn"

    def __init__(self) -> None:
        self.kline = SimpleNamespace(
            last=lambda symbol: {"symbol": symbol, "close": 100.0, "percent": 0.01},
            live=lambda symbol: {"symbol": symbol, "close": 101.0, "percent": 0.02},
            snapshot=lambda symbol: {"symbol": symbol, "close": 100.0, "percent": 0.01},
            batch_live=lambda symbols: {s: {"symbol": s, "close": 101.0} for s in symbols},
            bars=lambda symbol, n=None, adj=None, begin=None, end=None: [
                {"date": "2026-10-30", "close": 100.0, "percent": 0.01},
                {"date": "2026-10-31", "close": 101.0, "percent": 0.01},
            ],
        )
        self.stocks = SimpleNamespace(
            industries=lambda: [{"id": "S48", "name": "银行"}],
            industry_members=lambda industry, top_n=None: [
                {"symbol": "600519", "name": "贵州茅台"}
            ],
        )
        self.screener = SimpleNamespace(
            screen_limit_up=lambda symbol: True,
            screen_limit_down=lambda symbol: False,
            screen_above_ma20=lambda symbol: True,
            screen_ma60_up=lambda symbol: True,
            screen_breakout_ma20=lambda symbol: False,
            screen_momentum_20d=lambda symbol, min_chg=0.10: False,
            screen_pullback_20d=lambda symbol, min_chg=-0.10: False,
            screen_volume_spike=lambda symbol, min_ratio=1.5: False,
            index_breadth_summary=lambda idx=None: {"total": 2, "up": 1, "down": 1},
            index_breadth_bins=lambda idx=None: [{"label": "up", "count": 1}],
            index_breadth_bin_industries=lambda idx=None: [{"industry": "银行", "count": 1}],
            index_top_movers=lambda limit=20, desc=True, idx=None: [
                {"symbol": "600519", "percent": 0.02}
            ],
            query=lambda where, order=None, desc=True, limit=50, offset=0,
            fields=None, idx=None: {"count": 108, "rows": [
                {"symbol": "900948", "name": "伊泰B股", "$ROE_TTM_LAST": 0.1631}
            ]},
        )
        self.indicator = SimpleNamespace(
            metrics=lambda symbol, codes: {code: 0.42 for code in codes},
        )
        self.info = SimpleNamespace(
            profile=lambda symbol: {"symbol": symbol, "name": "贵州茅台"},
        )
        self.statements = SimpleNamespace(
            income=lambda symbol, years=3: [{"period": "2025-Q4", "amount": 1.0}],
            balance=lambda symbol, years=3: [{"period": "2025-Q4", "amount": 2.0}],
            cashflow=lambda symbol, years=3: [{"period": "2025-Q4", "amount": 3.0}],
        )
        self.dividend = SimpleNamespace(
            history=lambda symbol, limit=None: [{"date": "2025-06-01", "dps": 0.1}],
        )
        self.notice = SimpleNamespace(
            list=lambda symbol, window="3m", keyword="", limit=20: [
                {"title": "公告", "url": "https://example.com/a"}
            ],
            recent=lambda window="7d", keyword="", limit=50: [
                {"title": "全市场公告", "url": "https://example.com/b"}
            ],
        )
        self.filings = SimpleNamespace(
            list=lambda symbol, kind="all", limit=10: [{"title": "年报"}],
        )
        self.forecast = SimpleNamespace(
            yjyg=lambda symbol, limit=8: [{"net_profit_low": 1.0}],
        )
        self.workout = SimpleNamespace(
            query=lambda symbol: [{"event": "offer"}],
            board=lambda: [{"symbol": "600519"}],
        )

    def call_batch(self, function: str, symbols: list[str], **kwargs: Any) -> BatchResult:
        assert function == "kline.snapshot"
        return BatchResult(
            results={s: {"close": 100.0} for s in symbols},
            requests=1,
            requested=len(symbols),
        )

    def call(self, function: str, **kwargs: Any) -> Any:
        assert function == "kline.snapshot"
        return {"symbol": kwargs["sym"], "close": 100.0}

    def batch_iter(self, function: str, symbols: list[str], **kwargs: Any) -> Iterator[BatchResult]:
        if len(symbols) == 1:
            yield BatchResult(
                results={symbols[0]: {"close": 100.0}},
                requests=1,
                requested=1,
            )
            return
        yield BatchResult(
            results={symbols[0]: {"close": 100.0}},
            requests=1,
            requested=1,
        )
        raise LimitError("rate limited", code="rate_limited", status=429, retry_after=3)


@pytest.fixture()
def runtime() -> MCPRuntime:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": FakeClient()}
    return rt


def test_registry_has_twenty_tools() -> None:
    server = build_server(MCPRuntime(demo=True))
    response = server.list_tools()
    if hasattr(response, "__await__"):
        response = __import__("asyncio").run(response)
    assert {item.name for item in response} == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 20
    descriptions = [item.description for item in response]
    assert all(descriptions)


def test_status_and_offline_discovery(runtime: MCPRuntime) -> None:
    status = tools.status(runtime)
    assert status["ok"] is True
    assert status["data"]["catalog"]["functions"] > 0
    assert "secret=" not in str(status["data"]["credentials"]).lower()

    hits = tools.search(runtime, "股息", limit=5)
    assert hits["data"]
    assert any(row["kind"] == "function" for row in hits["data"])

    contract = tools.contract(runtime, "bonus.snapshot_yield_ttm")
    assert contract["data"]["name"] == "bonus.snapshot_yield_ttm"
    assert contract["data"]["params"]

    symbols = tools.symbols(runtime, "茅台", limit=1)
    assert symbols["data"][0]["code"] == "600519"


def test_quote_history_metrics_company(runtime: MCPRuntime) -> None:
    one = tools.quote(runtime, ["600519"], live=True)
    assert one["data"]["close"] == 101.0
    many = tools.quote(runtime, ["600519", "000001"], live=False)
    assert many["meta"]["requests"] == 1
    assert many["meta"]["rows_total"] == 2
    one_snapshot = tools.quote(runtime, ["600519"], live=False)
    assert one_snapshot["data"]["close"] == 100.0

    bars = tools.history(runtime, "600519", n=2, adj="qfq")
    assert len(bars["data"]) == 2
    assert bars["meta"]["units"] == "base"

    vals = tools.metrics(runtime, "600519", ["$PE_TTM_LAST", "$PE_TTM_LAST"])
    assert vals["data"] == {"$PE_TTM_LAST": 0.42}


def test_market_metadata_reflects_requested_market(runtime: MCPRuntime) -> None:
    runtime._clients = {"cn": FakeClient(), "hk": FakeClient()}
    quote = tools.quote(runtime, ["00700"], market="hk")
    assert quote["meta"]["market"] == "hk"

    bars = tools.history(runtime, "00700", market="hk", n=2)
    assert bars["meta"]["market"] == "hk"

    card = tools.company(runtime, "600519", include=["profile", "income", "notices"])
    assert card["data"]["blocks"]["profile"]["name"] == "贵州茅台"
    assert card["meta"]["row_count"] >= 3


def test_screen_and_disclosures(runtime: MCPRuntime) -> None:
    flag = tools.screen(runtime, "boolean", symbol="600519", test="limit_up")
    assert flag["data"]["value"] is True
    breadth = tools.screen(runtime, "breadth_summary")
    assert breadth["data"]["total"] == 2
    picked = tools.screen(runtime, "query", where="$ROE_TTM_LAST > 0.15", limit=10)
    assert picked["data"]["count"] == 108
    assert picked["data"]["rows"][0]["symbol"] == "900948"

    notices = tools.disclosures(runtime, "notice", symbol="600519", limit=1)
    assert notices["data"][0]["title"] == "公告"
    filing = tools.disclosures(runtime, "filing", symbol="600519", limit=1)
    assert filing["data"][0]["title"] == "年报"


def test_batch_success_and_rate_limit_resume(runtime: MCPRuntime) -> None:
    ok = tools.batch(runtime, "kline.snapshot", ["600519"], params={"limit": 2}, raw=False, units="base")
    assert ok["ok"] is True
    assert ok["meta"]["requests"] == 1

    limited = tools.batch(runtime, "kline.snapshot", ["600519", "000001"])
    assert limited["ok"] is False
    assert limited["partial"] is True
    assert limited["error"]["code"] == "rate_limited"
    assert limited["meta"]["resume_start"] == 1
    assert limited["meta"]["retry_after_seconds"] == 3
    assert limited["meta"]["resume_symbols"] == ["000001"]
    assert limited["data"][0]["symbol"] == "600519"


def test_generic_call_contract(runtime: MCPRuntime) -> None:
    result = tools.call(runtime, "kline.snapshot", {"sym": "600519"})
    assert result["data"]["symbol"] == "600519"
    assert result["meta"]["mode"] == "catalog"
    assert result["meta"]["units"] == "base"
    with pytest.raises(ValueError, match="未知参数"):
        tools.call(runtime, "kline.snapshot", {"bad": 1})
    with pytest.raises(ValueError, match="私有选项"):
        tools.call(runtime, "kline.snapshot", {"_df": True})


def test_output_modes_and_limits(runtime: MCPRuntime) -> None:
    rows = [{"symbol": str(i), "close": float(i)} for i in range(10)]
    shaped = _shape_rows(runtime, rows, output="sample", max_rows=3)
    assert shaped["meta"]["truncated"] is True
    assert len(shaped["data"]) == 3
    assert shaped["meta"]["rows_total"] == 10

    counted = _shape_rows(runtime, rows, output="count")
    assert counted["data"] is None
    assert counted["meta"]["row_count"] == 10

    summary = _shape_rows(runtime, rows, output="summary")
    assert summary["data"]["numeric_stats"]["close"]["max"] == 9.0


@pytest.mark.parametrize(
    "exc,kind",
    [
        (AuthError("missing credentials", code="config"), "AuthError"),
        (LimitError("rate", code="rate_limited", status=429), "LimitError"),
        (CatalogError("unknown"), "CatalogError"),
        (UsageError("bad param", code="params"), "UsageError"),
        (DataError("bad units", code="range"), "DataError"),
    ],
)
def test_error_envelopes(exc: Exception, kind: str) -> None:
    result = error(exc)
    assert result["ok"] is False
    assert result["error"]["kind"] == kind
    assert result["error"]["fix"]
    assert result["links"]["console"]


def test_value_error_maps_to_usage_error() -> None:
    result = error(ValueError("bad enum"))
    assert result["error"]["kind"] == "UsageError"
    assert result["error"]["code"] == "params"


def test_block_output_is_truncated(runtime: MCPRuntime) -> None:
    card = tools.company(runtime, "600519", include=["income"])
    card["data"]["blocks"]["income"] = [
        {"period": str(i), "amount": float(i)} for i in range(10)
    ]
    shaped = _shape_rows(runtime, card["data"], output="sample", max_rows=3)
    assert shaped["meta"]["truncated"] is True
    assert len(shaped["data"]["blocks"]["income"]) == 3


def test_real_client_user_agent_is_mcp_attributed(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import wmshare
    from wmshare.mcp import core

    captured: dict[str, str] = {}

    class FakeSdkClient:
        market = "cn"
        session = SimpleNamespace(headers=captured)

    def fake_from_env(*_args: Any, **_kwargs: Any) -> FakeSdkClient:
        return FakeSdkClient()

    monkeypatch.setattr(core.Client, "from_env", fake_from_env)
    rt = MCPRuntime(market="cn", demo=False)
    rt.client()
    assert captured["User-Agent"] == f"wmshare-mcp/{wmshare.__version__}"
    assert captured["X-WM-Client"] == f"wmshare-mcp/{wmshare.__version__}"


def test_protocol_call_tool_returns_tool_envelope() -> None:
    server = build_server(MCPRuntime(market="cn", demo=True))
    result = __import__("asyncio").run(server.call_tool("wmshare_status", {}))
    assert isinstance(result, tuple)
    assert result[1]["ok"] is True
    assert result[1]["meta"]["source"] == "wmshare MCP"


def _shape_rows(runtime: MCPRuntime, rows: list[dict[str, Any]], *, output: str,
                max_rows: int = 200) -> dict[str, Any]:
    from wmshare.mcp.core import success

    return success(runtime, rows, output=output, max_rows=max_rows)
