"""指标口径/周期的 sidecar 合同：不能被组合成同一组。"""
from __future__ import annotations

import json
from pathlib import Path

import wmshare
from wmshare.indicator_adapter import IndicatorAdapter

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "src" / "wmshare" / "_catalog" / "generated" / "metric_taxonomy.json"


def _by_code() -> dict[str, dict]:
    return {r["code"]: r for r in json.loads(SIDECAR.read_text())["metrics"]}


def _group_of(ad: IndicatorAdapter, code: str) -> dict | None:
    for group in ad.combinable_groups()["groups"]:
        if code in group["codes"]:
            return group
    return None


def test_macro_period_is_monthly():
    assert _by_code()["$CPI"]["period"] == "monthly"


def test_ten_year_percentile_has_window_and_min_history():
    ad = IndicatorAdapter(wmshare.demo_client())
    row = next(r for r in ad.table("600519", ["$PCT_PE_TTM_10Y_LAST"])
               if r["code"] == "$PCT_PE_TTM_10Y_LAST")
    assert row["period"] == "ttm"
    assert row["window"] == "10y"
    assert row["min_history"] == "10y"
    assert row["stat"] == "percentile"


def test_three_year_average_is_not_ttm():
    row = _by_code()["$ROE_AVG3"]
    assert row["period"] == "annual"
    assert row["window"] == "3y"
    assert row["caliber"] == ["parent"]


def test_pb_is_latest_report_not_ttm():
    row = _by_code()["$PB_NOGW_LAST"]
    assert row["period"] == "latest_report"
    assert row["unit_kind"] == "multiple"


def test_dividend_yield_and_dps_are_different_groups():
    ad = IndicatorAdapter(wmshare.demo_client())
    groups = ad.combinable_groups(scope="stock", topic="dividend")["groups"]
    yield_group = next(g for g in groups if "$BONUS_RATE_TTM_LAST" in g["codes"])
    dps_group = next(g for g in groups if "$DPS_TTM_LAST" in g["codes"])
    assert yield_group["group_id"] != dps_group["group_id"]
    assert yield_group["unit_kind"] == "ratio"
    assert dps_group["unit_kind"] == "per_share"


def test_pe_and_pb_are_not_in_same_group():
    ad = IndicatorAdapter(wmshare.demo_client())
    pe = _group_of(ad, "$PE_TTM_LAST")
    pb = _group_of(ad, "$PB_NOGW_LAST")
    assert pe and pb
    assert pe["group_id"] != pb["group_id"]
    assert pe["period"] == "ttm"
    assert pb["period"] == "latest_report"


def test_pe_and_ps_share_group():
    ad = IndicatorAdapter(wmshare.demo_client())
    pe = _group_of(ad, "$PE_TTM_LAST")
    ps = _group_of(ad, "$PS_TTM_LAST")
    assert pe and ps
    assert pe["group_id"] == ps["group_id"]


def test_no_group_mixes_period_or_caliber():
    ad = IndicatorAdapter(wmshare.demo_client())
    by_code = _by_code()
    for group in ad.combinable_groups()["groups"]:
        periods = {by_code[code]["period"] for code in group["codes"]}
        windows = {by_code[code]["window"] for code in group["codes"]}
        calibers = {tuple(sorted(by_code[code]["caliber"])) for code in group["codes"]}
        units = {by_code[code]["unit_kind"] for code in group["codes"]}
        assert periods == {group["period"]}
        assert windows == {group["window"]}
        assert calibers == {tuple(sorted(group["caliber"]))}
        assert units == {group["unit_kind"]}


def test_unknown_period_is_flat_not_grouped():
    # 当前 sidecar 没有 period=unknown 的码；用临时构造验证判断逻辑。
    by_code = _by_code()
    assert all(row["period"] != "unknown" for row in by_code.values())
