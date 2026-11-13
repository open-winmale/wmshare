"""指标分类 sidecar 的结构/分组合同（离线，不联网）。"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

import wmshare
from wmshare.indicator_adapter import IndicatorAdapter

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"
SIDECAR = CATALOG / "generated" / "metric_taxonomy.json"
METRICS = CATALOG / "generated" / "metrics.json"
TAXONOMY = CATALOG / "taxonomy.yaml"
CURATED = CATALOG / "domains" / "fund.indicators.yaml"

EXPECTED = {
    "$PE_TTM_LAST": ("stock", "valuation", "ttm", "none", [], "multiple"),
    "$PS_TTM_LAST": ("stock", "valuation", "ttm", "none", [], "multiple"),
    "$PB_NOGW_LAST": ("stock", "valuation", "latest_report", "none",
                      ["parent"], "multiple"),
    "$PCT_PE_TTM_10Y_LAST": ("stock", "valuation", "ttm", "10y", [], "percentile"),
    "$ROE_AVG3": ("stock", "profitability", "annual", "3y", ["parent"], "ratio"),
    "$ROE_TTM_LAST": ("stock", "profitability", "ttm", "none", [], "ratio"),
    "$TR_TTM_YOY_LAST": ("stock", "growth", "ttm", "none", [], "ratio"),
    "$BONUS_RATE_TTM_LAST": ("stock", "dividend", "ttm", "none", [], "ratio"),
    "$DPS_TTM_LAST": ("stock", "dividend", "ttm", "none", [], "per_share"),
    "$MV_LAST": ("stock", "quote", "snapshot", "none", ["total"], "money"),
    "$MV_FREE_LAST": ("stock", "quote", "snapshot", "none", ["free_float"], "money"),
    "$ID_ROE_TTM": ("industry", "profitability", "ttm", "none", ["overall"], "ratio"),
    "$CPI": ("macro", "macro", "monthly", "none", [], "index_point"),
    "$BOND_ISSUE_COUPON_IR": ("cbond", "terms", "snapshot", "none", [], "ratio"),
    "$PS_CR": ("stock", "scale", "latest_report", "none", [], "per_share"),
    "$ADP_DAYS": ("stock", "efficiency", "latest_report", "none", [], "days"),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _taxonomy() -> dict:
    return _load(SIDECAR)


def test_sidecar_is_one_to_one_with_metrics():
    tax = _taxonomy()
    metrics = {m["code"] for m in _load(METRICS)["metrics"]}
    rows = tax["metrics"]
    codes = [r["code"] for r in rows]
    assert tax["schema_version"] == 1
    assert tax["stats"]["count"] == len(rows) == 2752
    assert len(codes) == len(set(codes))
    assert set(codes) == metrics


def test_all_fields_use_closed_enums():
    cfg = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    enums = {key: set((cfg.get(key) or {}).keys()) for key in
             ("scopes", "topics", "periods", "windows", "unit_kinds", "calibers")}
    for row in _taxonomy()["metrics"]:
        assert row["scope"] in enums["scopes"], row
        assert row["topic"] in enums["topics"], row
        assert row["period"] in enums["periods"], row
        assert row["window"] in enums["windows"], row
        assert row["unit_kind"] in enums["unit_kinds"], row
        assert isinstance(row["caliber"], list)
        assert set(row["caliber"]) <= enums["calibers"], row
        assert row["status"] in ("active", "dead")


def test_representative_period_and_caliber_are_locked():
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    for code, expected in EXPECTED.items():
        row = by_code[code]
        actual = (row["scope"], row["topic"], row["period"], row["window"],
                  row["caliber"], row["unit_kind"])
        assert actual == expected, f"{code}: {actual} != {expected}"


def test_curated_groups_match_sidecar():
    cfg = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    group_topics = cfg["group_topics"]
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    curated = yaml.safe_load(CURATED.read_text(encoding="utf-8"))
    count = 0
    for group in curated.get("metric_groups") or []:
        scope, topic = group_topics[group["id"]]
        for metric in group.get("metrics") or []:
            row = by_code[metric["code"]]
            assert (row["scope"], row["topic"]) == (scope, topic)
            count += 1
    assert count == 78


def test_dead_codes_are_exactly_drop_stubs():
    metrics = {m["code"]: m for m in _load(METRICS)["metrics"]}
    tax = {r["code"]: r for r in _taxonomy()["metrics"]}
    expected = {code for code, m in metrics.items() if m.get("cn") == "drop stub"}
    actual = {code for code, row in tax.items() if row["status"] == "dead"}
    assert actual == expected
    assert len(actual) == 20


def test_quality_thresholds():
    stats = _taxonomy()["stats"]
    assert stats["other"] <= 0.05
    assert stats["caliber_unknown"] <= 0.30
    # unit unknown 不作为硬门禁，但必须被显式记录，便于后续收紧。
    assert 0 <= stats["unit_unknown"] <= 1


def test_all_codes_are_grouped_or_flat_exactly_once():
    ad = IndicatorAdapter(wmshare.demo_client())
    result = ad.combinable_groups()
    grouped = [code for group in result["groups"] for code in group["codes"]]
    flat = [row["code"] for row in result["flat"]]
    all_codes = [r["code"] for r in _taxonomy()["metrics"]]
    assert len(grouped) + len(flat) == len(all_codes)
    assert len(set(grouped) | set(flat)) == len(all_codes)
    assert not (set(grouped) & set(flat))


def test_unknown_fields_never_enter_groups():
    ad = IndicatorAdapter(wmshare.demo_client())
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    for group in ad.combinable_groups()["groups"]:
        for code in group["codes"]:
            row = by_code[code]
            assert row["period"] != "unknown", code
            assert row["window"] != "unknown", code
            assert row["unit_kind"] != "unknown", code
            assert "unknown" not in row["caliber"], code
            assert row["status"] == "active", code


def test_group_id_is_recomputable():
    ad = IndicatorAdapter(wmshare.demo_client())
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    for group in ad.combinable_groups()["groups"]:
        example = by_code[group["codes"][0]]
        caliber = "+".join(sorted(example["caliber"])) or "-"
        expected = (f"{example['unit_kind']}|{example['period']}|"
                    f"{example['window']}|{caliber}|{group['market']}")
        assert group["group_id"] == expected
        assert group["count"] == len(group["codes"])


def test_market_restricted_code_is_partitioned_by_market():
    ad = IndicatorAdapter(wmshare.demo_client())
    cn = ad.combinable_groups(scope="stock", topic="solvency", market="cn")
    hk = ad.combinable_groups(scope="stock", topic="solvency", market="hk")
    cn_codes = {code for group in cn["groups"] for code in group["codes"]}
    hk_codes = {code for group in hk["groups"] for code in group["codes"]}
    assert "$LD" not in cn_codes
    assert "$LD" in hk_codes
    assert "$LD" not in {row["code"] for row in cn["flat"]}
    assert "$LD" not in {row["code"] for row in hk["flat"]}


def test_ps_per_share_is_not_confused_with_ps_ttm():
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    assert by_code["$PS_CR"]["topic"] == "scale"
    assert by_code["$PS_CR"]["unit_kind"] == "per_share"
    assert by_code["$PS_TTM_LAST"]["topic"] == "valuation"
    assert by_code["$PS_TTM_LAST"]["unit_kind"] == "multiple"


def test_yoy_is_ratio_not_money():
    by_code = {r["code"]: r for r in _taxonomy()["metrics"]}
    for code in ("$TR_TTM_YOY_LAST", "$NPTS_TTM_YOY_LAST"):
        assert by_code[code]["unit_kind"] == "ratio", code
