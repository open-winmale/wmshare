"""打包 demo 快照的合同：真实来源、固定日期、内容 hash、体积与关键不变量。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

import wmshare
from wmshare._demo import DEMO_SNAPSHOT_PROVENANCE, load_demo_snapshot

REPO = Path(__file__).resolve().parents[1]
DATA_PATH = REPO / "src" / "wmshare" / "_demo_data.json"
AS_OF = DEMO_SNAPSHOT_PROVENANCE["as_of"]
UNIVERSE = [
    "600519", "000858", "601088", "600900", "601318",
    "000001", "600036", "000333", "300750", "688981",
]


@pytest.fixture(scope="module")
def document():
    return json.loads(DATA_PATH.read_bytes())


def test_demo_data_does_not_trip_leak_gate():
    spec = importlib.util.spec_from_file_location(
        "check_leak_gate", REPO / "tools" / "check_leak.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rel = DATA_PATH.relative_to(REPO).as_posix()
    assert rel in module.THIRDPARTY_SKIP_PREFIXES
    assert not [finding for finding in module.scan() if rel in finding]


def test_snapshot_header_and_size(document):
    assert DATA_PATH.stat().st_size <= 512 * 1024
    assert document["schema_version"] == 1
    assert document["as_of"] == AS_OF
    assert document["market"] == "cn"
    # 溯源口径由 _demo.py 的 DEMO_SNAPSHOT_PROVENANCE 单一事实源给出（重拍即跟随）
    assert document["sdk_version"] == DEMO_SNAPSHOT_PROVENANCE["snapshot_sdk_version"]
    assert document["catalog_rev"] == DEMO_SNAPSHOT_PROVENANCE["snapshot_catalog_rev"]
    assert document["sdk_version"] == wmshare.__version__
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
        assert dates == sorted(dates)   # 2.0 全库升序（旧→新）
        # 日 K 结算面到 AS_OF 当日或之前最近交易日（盘中拍摄时是上一交易日）
        assert dates[-1] <= AS_OF
        assert all(date <= AS_OF for date in dates)
        for row in bars:
            assert math.isfinite(row["close"])
            assert math.isfinite(row["volume"]) and row["volume"] >= 0
            assert math.isfinite(row["amount"]) and row["amount"] >= 0
            assert abs(row["percent"]) <= 1
        # 快照=拍摄日盘中价，日 K 到上一交易日：同量级（±20%）即同标的同单位
        assert math.isclose(
            data["kline_snapshot"][symbol]["close"], bars[-1]["close"], rel_tol=0.20,
        )
    # examples/07 会对银行成分做 kline.snapshot 批量。
    bank_symbols = {row["symbol"] for row in data["industry_members_bank"]}
    assert bank_symbols.issubset(data["kline_snapshot"])


def test_units_and_statements(document):
    data = document["data"]
    assert 0 <= data["dividend"]["yield_ttm"]["600519"] < 1
    # 上游「最近一条」可能是零派息期中记录；单位口径看历史最大 dps（元/股）
    hist = data["dividend"]["history"]["600519"]
    assert hist and max(float(r["dps"]) for r in hist) > 1
    for symbol in UNIVERSE:
        if data["moneyflow_last"][symbol] is not None:
            assert math.isfinite(data["moneyflow_last"][symbol]["net_mf"])
        for row in data["moneyflow_bars"][symbol]:
            assert math.isfinite(row["net_mf"])

    statements = data["statements"]
    for kind in ("income", "balance", "cashflow"):
        assert statements[kind] and any(row.get("vals") for row in statements[kind])
        # vals 年份键必须是 4 位年字符串（升序无关紧要，集合口径）
        for row in statements[kind]:
            for year in (row.get("vals") or {}):
                assert len(str(year)) == 4 and str(year).isdigit(), year
    assert isinstance(statements["audit"], dict)


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
