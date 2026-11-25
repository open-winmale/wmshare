"""IndicatorAdapter 离线合同：组合边界、扁平化、请求数、错误隔离。"""
from __future__ import annotations

import inspect

import pytest

from wmshare.catalog import load
from wmshare.errors import CatalogError, UsageError
from wmshare.indicator_adapter import IndicatorAdapter


class FakeIndicator:
    def __init__(self, fail: tuple[str, ...] = ()):
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = set(fail)

    def metrics(self, symbol: str, codes: list[str]) -> dict:
        self.calls.append((symbol, list(codes)))
        if any(code in self.fail for code in codes):
            raise RuntimeError("injected failure")
        return {code: 10.0 for code in codes}


class FakeCli:
    def __init__(self, market: str = "cn", fail: tuple[str, ...] = ()):
        self.market = market
        self.catalog = load()
        self.indicator = FakeIndicator(fail)


def _adapter(market: str = "cn", fail: tuple[str, ...] = ()) -> tuple[IndicatorAdapter, FakeCli]:
    cli = FakeCli(market=market, fail=fail)
    return IndicatorAdapter(cli), cli


def test_same_group_codes_are_combined_into_one_call():
    ad, cli = _adapter()
    rows = ad.table("600519", [
        "$PE_TTM_LAST", "$PS_TTM_LAST", "$PB_NOGW_LAST",
        "$PCT_PE_TTM_10Y_LAST",
    ])
    assert len(cli.indicator.calls) == 3
    assert cli.indicator.calls[0] == ("600519", ["$PE_TTM_LAST", "$PS_TTM_LAST"])
    by_code = {row["code"]: row for row in rows}
    assert by_code["$PE_TTM_LAST"]["combinable"] is True
    assert by_code["$PS_TTM_LAST"]["combinable"] is True
    assert by_code["$PB_NOGW_LAST"]["combinable"] is False
    assert by_code["$PCT_PE_TTM_10Y_LAST"]["combinable"] is False
    assert by_code["$PE_TTM_LAST"]["group_id"] == "multiple|ttm|none|-|shared"
    assert by_code["$PB_NOGW_LAST"]["group_id"] == (
        "multiple|latest_report|none|parent|shared")


def test_flat_unknown_unit_is_fetched_individually():
    ad, cli = _adapter()
    rows = ad.table("600519", ["$AVG_NR_DAY"])
    assert len(cli.indicator.calls) == 1
    row = rows[0]
    assert row["status"] == "active"
    assert row["combinable"] is False
    assert row["group_id"] is None
    assert row["reason"] == "unit_kind=unknown"
    assert row["value"] == 10.0


def test_dead_code_is_excluded_without_request():
    ad, cli = _adapter()
    rows = ad.table("600519", ["$CLOSE_LIVE"])
    assert cli.indicator.calls == []
    assert rows[0]["status"] == "excluded"
    assert rows[0]["reason"] == "dead"
    assert rows[0]["value"] is None


def test_market_mismatch_is_excluded_on_cn_but_fetched_on_hk():
    cn, cn_cli = _adapter("cn")
    cn_row = cn.table("600519", ["$LD"])[0]
    assert cn_cli.indicator.calls == []
    assert cn_row["status"] == "excluded"
    assert "仅 hk" in cn_row["reason"]

    hk, hk_cli = _adapter("hk")
    hk_row = hk.table("00700", ["$LD"])[0]
    assert len(hk_cli.indicator.calls) == 1
    assert hk_row["status"] == "active"
    assert hk_row["value"] == 10.0


def test_on_error_skip_keeps_rows_and_raise_propagates():
    ad, _ = _adapter(fail=("$PE_TTM_LAST",))
    rows = ad.table("600519", ["$PE_TTM_LAST", "$PS_TTM_LAST"],
                    on_error="skip")
    assert all(row["error"] == "injected failure" for row in rows)
    assert all(row["group_id"] == "multiple|ttm|none|-|shared" for row in rows)
    with pytest.raises(RuntimeError, match="injected failure"):
        ad.table("600519", ["$PE_TTM_LAST"], on_error="raise")


def test_table_returns_rows_in_input_order():
    ad, _ = _adapter()
    codes = ["$PCT_PE_TTM_10Y_LAST", "$PE_TTM_LAST", "$PB_NOGW_LAST"]
    rows = ad.table("600519", codes)
    assert [row["code"] for row in rows] == codes


def test_many_counts_one_request_per_group_per_symbol():
    ad, cli = _adapter()
    result = ad.many(["600519", "000001"], ["$PE_TTM_LAST", "$PS_TTM_LAST"])
    assert result.requested == 2
    assert result.requests == 2
    assert len(cli.indicator.calls) == 2
    assert result.results["600519"] == {"$PE_TTM_LAST": 10.0, "$PS_TTM_LAST": 10.0}
    assert result.metric_meta["$PE_TTM_LAST"]["group_id"] == (
        "multiple|ttm|none|-|shared")


def test_many_mixed_groups_counts_each_group():
    ad, cli = _adapter()
    result = ad.many(["600519", "000001"],
                     ["$PE_TTM_LAST", "$PB_NOGW_LAST"])
    assert result.requests == 4
    assert len(cli.indicator.calls) == 4
    assert set(result.results["600519"]) == {"$PE_TTM_LAST", "$PB_NOGW_LAST"}


def test_group_is_chunked_when_over_eval_limit(monkeypatch):
    import wmshare.indicator_adapter as module

    monkeypatch.setattr(module, "_MAX_CODES_PER_EVAL", 1)
    ad, cli = _adapter()
    rows = ad.table("600519", ["$PE_TTM_LAST", "$PS_TTM_LAST"])
    assert len(cli.indicator.calls) == 2
    assert all(row["group_id"] == "multiple|ttm|none|-|shared" for row in rows)
    assert all(row["combinable"] is True for row in rows)


def test_many_errors_are_collected_on_skip():
    ad, _ = _adapter(fail=("$PE_TTM_LAST",))
    result = ad.many(["600519"], ["$PE_TTM_LAST"], on_error="skip")
    assert result.results["600519"] == {}
    assert result.errors == [{
        "symbol": "600519", "code": "$PE_TTM_LAST",
        "error": "injected failure",
    }]


def test_many_validates_arguments():
    ad, _ = _adapter()
    with pytest.raises(UsageError, match="symbols"):
        ad.many([], ["$PE_TTM_LAST"])
    with pytest.raises(UsageError, match="batch_size"):
        ad.many(["600519"], ["$PE_TTM_LAST"], batch_size=0)


def test_table_validates_codes_and_on_error():
    ad, _ = _adapter()
    with pytest.raises(UsageError, match="codes"):
        ad.table("600519", [])
    with pytest.raises(CatalogError, match="未知指标"):
        ad.table("600519", ["$NO_SUCH_CODE"])
    with pytest.raises(UsageError, match="on_error"):
        ad.table("600519", ["$PE_TTM_LAST"], on_error="ignore")


def test_metrics_by_filters_and_joins_catalog_fields():
    ad, _ = _adapter()
    rows = ad.metrics_by(scope="stock", topic="valuation", unit_kind="multiple")
    assert rows and all(row["unit_kind"] == "multiple" for row in rows)
    pe = next(row for row in rows if row["code"] == "$PE_TTM_LAST")
    assert pe["cn"] == "PE(TTM)"
    assert pe["period"] == "ttm"


def test_adapter_signatures_stay_small():
    assert list(inspect.signature(IndicatorAdapter.table).parameters) == [
        "self", "symbol", "codes", "_df", "on_error"]
    assert list(inspect.signature(IndicatorAdapter.many).parameters) == [
        "self", "symbols", "codes", "batch_size", "on_error"]
    assert list(inspect.signature(IndicatorAdapter.metrics_by).parameters) == [
        "self", "scope", "topic", "period", "window", "unit_kind",
        "market", "status"]


def test_missing_sidecar_raises_catalog_error(tmp_path):
    class EmptyCatalog:
        root = tmp_path

        def metric(self, code):  # pragma: no cover - 不会走到
            return None

    with pytest.raises(CatalogError, match="metric_taxonomy.json"):
        IndicatorAdapter(FakeCli(), catalog=EmptyCatalog())


def test_df_outputs():
    pd = pytest.importorskip("pandas")
    ad, _ = _adapter()
    df = ad.table("600519", ["$PE_TTM_LAST", "$PB_NOGW_LAST"], _df=True)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == [
        "code", "value", "scope", "topic", "period", "window", "caliber",
        "stat", "unit_kind", "native_unit", "min_history", "status", "group_id",
        "combinable", "reason", "error"]
    result = ad.many(["600519"], ["$PE_TTM_LAST"])
    wide = result.to_df()
    assert isinstance(wide, pd.DataFrame)
    assert list(wide.columns) == ["symbol", "$PE_TTM_LAST"]
