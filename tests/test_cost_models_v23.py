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


def test_holdernum_history_cost_scales_with_periods():
    """户数历史：8 期冷 ≈2,000 / 95 期冷 ≈1.6 万，按返回期数线性（2026-11-23 实测）。"""
    small = _est("equity.query_holdernum_history", {"symbol": "600036", "limit": 8})
    big = _est("equity.query_holdernum_history", {"symbol": "601318", "limit": 500})
    assert small["ec_hi"] == 800 + 170 * 8, small
    assert big["ec_hi"] == 800 + 170 * 500, big
    assert "指纹缓存" in small["note"]


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


def test_futures_bars_cost_store_rows_and_version_cache():
    """store 直读：冷 ≈190+126×行、同日复跑版本键缓存 ≈135（2026-11-23 实测）。"""
    est = _est("futures.bars", {"fut_code": "AL.SHF", "n": 20, "freq": "d"})
    assert est["ec_lo"] == 135 and est["ec_hi"] == 190 + 126 * 20, est
    assert "版本键缓存" in est["note"]
    win = _est("futures.bars", {"fut_code": "AL.SHF", "freq": "m",
                                "begin": "2026-01-01", "end": "2026-12-31"})
    assert win["ec_hi"] == 190 + 126 * (365 // 30 + 1), win
    snap = _est("futures.snapshot", {})
    assert snap["ec_lo"] == 135 and snap["ec_hi"] == 320, snap


def test_pdf_doc_search_scales_with_rows():
    small = _est("pdf_doc.search", {"limit": 5})
    big = _est("pdf_doc.search", {"limit": 40})
    assert big["ec_lo"] > small["ec_hi"], (small, big)  # 按行线性放大


@pytest.mark.parametrize("name", ["pdf_doc.read_text", "pdf_doc.status",
                                  "pdf_doc.find_by_key", "pdf_doc.read_markdown"])
def test_pdf_doc_single_doc_points(name):
    est = _est(name, {"file_key": "x"})
    assert est["ec_hi"] <= 1_500, est


def test_daily_basic_multi_scales_with_symbol_count():
    """多票按票计价：票数翻倍预估必须跟着翻倍。

    2026-11-19 live 实测（18 天窗口，``metering.ec_cost``）：1→674、5→2,858、
    10→5,588、30→16,521、50→26,625，即 ≈128 + 546×票数（边际 ≈550 EC/票）。
    此前 ``estimate_cost`` 的 ``startswith("valuation.daily_basic")`` 分支只看
    begin/end、完全忽略 ``syms``，多票预估算出来的是单票价（低估一个数量级以上）。
    预估失真比没有预估更危险——用户会据此放心拉大清单。
    """
    params = {"begin": "2026-11-01", "end": "2026-11-18"}
    one = _est("valuation.daily_basic_multi", {"syms": ["600519"], **params})
    many = _est("valuation.daily_basic_multi",
                {"syms": [f"60{i:04d}" for i in range(50)], **params})
    assert many["ec_lo"] >= one["ec_lo"] * 40, (one, many)   # 按票线性
    # 实测 50 票 = 26,625：上界必须覆盖实测值，下界不能低到离谱
    assert many["ec_hi"] >= 26_625, many
    assert many["ec_lo"] <= 26_625 <= many["ec_hi"], many
    assert "按票计价" in many["note"] and "不省算力" in many["note"]


def test_daily_basic_single_symbol_cost_unchanged():
    """单票（无 syms/1 票）不得被多票逻辑放大——回归保护。"""
    plain = _est("valuation.daily_basic", {"begin": "2026-11-01", "end": "2026-11-18"})
    assert plain["ec_lo"] < 5_000, plain
    assert "多票" not in plain["note"]
    # 实测单日 578 / 13 日 962 必须落在区间内
    one_day = _est("valuation.daily_basic", {"begin": "2026-11-18", "end": "2026-11-18"})
    assert one_day["ec_lo"] <= 578 <= one_day["ec_hi"], one_day
    thirteen = _est("valuation.daily_basic", {"begin": "2026-11-06", "end": "2026-11-18"})
    assert thirteen["ec_lo"] <= 962 <= thirteen["ec_hi"], thirteen
