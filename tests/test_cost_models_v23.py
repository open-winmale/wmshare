"""2.3.0 新面的 EC 成本模型：档位来自 2026-11-19 live 实测，禁止拍脑袋标 cache_hit。

每个用例不只断言「有数字」，还断言档位与形态（冷热差 / 按票 vs 按行 / 窗口相关），
否则模型退化成常量也能过测试。
"""
from __future__ import annotations

import pytest

from wmshare.client import estimate_cost


def _est(name, params=None):
    est = estimate_cost(name, params or {})
    assert est["ec_lo"] is not None and est["ec_hi"] is not None, est
    assert est["ec_lo"] <= est["ec_hi"], est
    assert est["model"] == "measured", est  # 新面一律实测档，不许 cache_hit
    return est


def test_buyback_snapshot_per_symbol():
    """回购快照按票一次取数（实测 171~709），与有没有数据无关。"""
    est = _est("buyback.snapshot", {"symbol": "600519"})
    assert est["ec_lo"] >= 100
    assert est["ec_hi"] <= 1000
    assert "票" in est["note"]


def test_notice_category_static_tables_are_cheap():
    keys = _est("notice.type_keys")
    regex = _est("notice.type_regex", {"key": "reduction"})
    assert keys["ec_hi"] <= 20 and regex["ec_hi"] <= 25
    assert keys["ec_lo"] < regex["ec_lo"] + 10  # 都个位数~十几 EC


def test_toplist_by_date_cold_vs_warm():
    """整日榜单冷态逐行规范化 ≈1.3 万，复跑走指纹缓存 ≈175。"""
    est = _est("toplist.by_date", {"trade_date": "2026-11-18", "limit": 100})
    assert est["ec_hi"] >= 10_000, est       # 冷态上界必须覆盖逐行成本
    assert est["ec_lo"] <= 500, est          # 下界=缓存命中
    assert "缓存" in est["note"]


def test_toplist_by_symbol_cold_vs_warm():
    est = _est("toplist.by_symbol", {"symbol": "000530", "limit": 10})
    assert est["ec_hi"] >= 1_000, est
    assert est["ec_lo"] <= 500, est


def test_futures_mapping_warns_full_history_cost():
    """窗口 13 行 ≈833，全历史 4,287 行 ≈21.4 万——note 必须提示传窗口。"""
    est = _est("futures.mapping",
               {"symbol": "RB.SHF", "begin": "2026-11-01", "end": "2026-11-18"})
    assert est["ec_hi"] >= 1_000, est
    assert "窗口" in est["note"] and "万" in est["note"]


def test_pdf_doc_search_scales_with_rows():
    small = _est("pdf_doc.search", {"limit": 5})
    big = _est("pdf_doc.search", {"limit": 40})
    assert big["ec_lo"] > small["ec_hi"], (small, big)  # 按行线性放大


@pytest.mark.parametrize("name", ["pdf_doc.read_text", "pdf_doc.status",
                                  "pdf_doc.find_by_key", "pdf_doc.read_markdown"])
def test_pdf_doc_single_doc_points(name):
    est = _est(name, {"file_key": "x"})
    assert est["ec_hi"] <= 1_500, est
