"""打包 demo 快照的合同：真实来源、固定日期、内容 hash、体积与关键不变量。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from wmshare._demo import load_demo_snapshot

REPO = Path(__file__).resolve().parents[1]
DATA_PATH = REPO / "src" / "wmshare" / "_demo_data.json"
AS_OF = "2026-10-30"
UNIVERSE = [
    "600519", "000858", "601088", "600900", "601318",
    "000001", "600036", "000333", "300750", "688981",
]


@pytest.fixture(scope="module")
def document():
    return json.loads(DATA_PATH.read_bytes())


def test_snapshot_header_and_size(document):
    assert DATA_PATH.stat().st_size <= 512 * 1024
    assert document["schema_version"] == 1
    assert document["as_of"] == AS_OF
    assert document["market"] == "cn"
    assert document["sdk_version"] == "1.10.0"
    assert document["catalog_rev"] == "d9bbd944"
    assert isinstance(document["generated_at"], str) and document["generated_at"]
    assert isinstance(document["capture_requests"], int)
    assert document["capture_requests"] > 0
    canonical = json.dumps(
        document["data"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()
    assert document["content_hash"] == hashlib.sha256(canonical).hexdigest()
    # 加载时重复执行运行时合同，确保文件与代码约定的 schema 同步。
    assert load_demo_snapshot() == document


def test_universe_and_reference_rows(document):
    data = document["data"]
    assert data["universe"] == UNIVERSE
    assert [row["symbol"] for row in data["stocks_list"]] == UNIVERSE
    assert data["industries"]
    assert 1 <= len(data["industry_members_bank"]) <= 20


def test_market_data_snapshot_consistency(document):
    data = document["data"]
    assert set(data["kline_bars"]) == set(UNIVERSE)
    assert set(UNIVERSE).issubset(data["kline_snapshot"])
    for symbol in UNIVERSE:
        bars = data["kline_bars"][symbol]
        assert 20 <= len(bars) <= 120
        dates = [row["date"][:10] for row in bars]
        assert dates == sorted(dates, reverse=True)
        assert dates[0] == AS_OF
        assert all(date <= AS_OF for date in dates)
        for row in bars:
            assert math.isfinite(row["close"])
            assert math.isfinite(row["volume"]) and row["volume"] >= 0
            assert math.isfinite(row["amount"]) and row["amount"] >= 0
            assert abs(row["percent"]) <= 1
        assert math.isclose(
            data["kline_snapshot"][symbol]["close"], bars[0]["close"],
            rel_tol=0.0, abs_tol=1e-9,
        )
    # examples/07 会对银行成分做 kline.snapshot 批量。
    bank_symbols = {row["symbol"] for row in data["industry_members_bank"]}
    assert bank_symbols.issubset(data["kline_snapshot"])


def test_units_and_statements(document):
    data = document["data"]
    assert 0 <= data["dividend"]["yield_ttm"]["600519"] < 1
    assert data["dividend"]["last"]["600519"]["dps"] > 1
    for symbol in UNIVERSE:
        if data["moneyflow_last"][symbol] is not None:
            assert math.isfinite(data["moneyflow_last"][symbol]["net_mf"])
        for row in data["moneyflow_bars"][symbol]:
            assert math.isfinite(row["net_mf"])

    statements = data["statements"]
    assert statements["years"] == sorted(statements["years"], reverse=True)
    for kind in ("income", "balance", "cashflow"):
        assert any(row.get("vals") for row in statements[kind])
    for row in statements["compare"]:
        if not all(isinstance(row.get(k), dict) for k in ("c", "diff", "diffp")):
            continue
        for year, diff_value in row["diff"].items():
            if year not in row["diffp"] or year not in row["c"] or row["c"][year] == 0:
                continue
            expected = diff_value / row["c"][year]
            assert abs(row["diffp"][year] - expected) <= max(1e-9, abs(expected) * 1e-6)


def test_screener_and_indicator_units(document):
    data = document["data"]
    indicators = data["indicators"]
    assert set(indicators) == {
        "$PE_TTM_LAST", "$ROE_TTM_LAST",
        "$PCT_PE_TTM_10Y_LAST", "$CUR_IND_ROE_PCT_LAST",
    }
    assert -10 <= indicators["$PE_TTM_LAST"] <= 1000
    for code in ("$ROE_TTM_LAST", "$PCT_PE_TTM_10Y_LAST", "$CUR_IND_ROE_PCT_LAST"):
        assert 0 <= indicators[code] <= 1
    assert 0 <= data["valuation"]["pct"] <= 1

    summary = data["screener"]["breadth_summary"]
    assert summary["total"] > len(UNIVERSE)
    assert all(summary[key] >= 0 for key in ("up", "down", "flat", "up_pct", "down_pct", "flat_pct"))
    assert -1 <= summary["median_pct"] <= 1
    for row in data["screener"]["breadth_bins"]:
        assert row["pct_of_total"] >= 0
    for group in ("top_movers_up", "top_movers_down"):
        for row in data["screener"][group]:
            assert abs(row["percent"]) <= 1
