"""全市场代码目录（_catalog/symbols/）离线测试 —— 不联网、不耗额度。"""
from __future__ import annotations

import pytest

from wmshare import load
from wmshare.errors import CatalogError


@pytest.fixture(scope="module")
def cat():
    return load()


# ---- 基础完备性 ----


def test_symbols_markets_present(cat):
    """三个市场的代码表必须随包存在且非空。"""
    stats = cat.stats()
    assert stats["symbols"]["cn"] > 5000   # A股全量约 5300+
    assert stats["symbols"]["hk"] > 2000
    assert stats["symbols"]["us"] > 5000


def test_symbol_exact_lookup(cat):
    got = cat.symbol("cn", "600519")
    assert got == {"market": "cn", "code": "600519", "name": "贵州茅台",
                   "pinyin": "guizhoumaotai", "abbr": "gzmt"}


def test_symbol_hk_padded_code(cat):
    """港股代码是 5 位补零格式。"""
    got = cat.symbol("hk", "00700")
    assert got is not None and got["name"] == "腾讯控股"


def test_symbol_us_cn_name(cat):
    got = cat.symbol("us", "ADBE")
    assert got is not None and got["name"]      # 中文名回退非空


def test_symbol_miss_returns_none(cat):
    assert cat.symbol("cn", "999999") is None


# ---- 搜索 ----


def test_search_by_exact_code(cat):
    hits = cat.symbols_search("600519", "cn")
    assert hits and hits[0]["code"] == "600519"
    assert hits[0]["name"] == "贵州茅台"


def test_search_by_code_prefix(cat):
    hits = cat.symbols_search("60051", "cn", limit=10)
    assert len(hits) > 1
    assert all(h["code"].startswith("60051") for h in hits)


def test_search_by_name_prefix_and_contains(cat):
    prefix = cat.symbols_search("贵州", "cn", limit=5)
    assert any(h["code"] == "600519" for h in prefix)
    contains = cat.symbols_search("银行", "cn", limit=10)
    assert len(contains) == 10
    assert all("银行" in h["name"] for h in contains)


def test_search_by_pinyin_and_abbr(cat):
    full = cat.symbols_search("changjiangdianli", "cn")
    assert any(h["code"] == "600900" for h in full)
    abbr = cat.symbols_search("gzmt", "cn")
    assert abbr and abbr[0]["code"] == "600519"


def test_search_pinyin_substring(cat):
    """全拼允许任意子串：maotai 命中 guizhoumaotai（贵州茅台）。

    用户几乎不会记得全拼开头，按词中段搜才是常态。
    """
    hits = cat.symbols_search("maotai", "cn", limit=10)
    assert hits, "拼音子串必须可命中"
    assert any(h["code"] == "600519" for h in hits)
    # 精确缩写仍应排在子串结果前面
    first = cat.symbols_search("gzmt", "cn")
    assert first[0]["code"] == "600519"


def test_search_ranking_exact_code_first(cat):
    """精确代码命中必须排第一，即使其他票名称也含该串。"""
    hits = cat.symbols_search("600519", "cn")
    assert hits[0]["rank" if False else "code"] == "600519"


def test_search_empty_query(cat):
    assert cat.symbols_search("", "cn") == []
    assert cat.symbols_search("   ", "cn") == []


def test_search_other_markets(cat):
    # 「数据服务商」为 vendor-comparison 时代遗留关键词——离线目录按名称/拼音
    # 无法命中 00700（1.8.0 发布时该用例已红）。按公司名检索修复。
    hk = cat.symbols_search("腾讯", "hk", limit=5)
    assert hk and hk[0]["code"] == "00700"
    us = cat.symbols_search("奥多比", "us")
    assert us and us[0]["code"] == "ADBE"


def test_search_limit(cat):
    assert len(cat.symbols_search("a", "us", limit=3)) <= 3


# ---- 错误处理 ----


def test_unknown_market_raises_catalog_error(cat):
    with pytest.raises(CatalogError) as ei:
        cat.symbols_search("x", "uk")
    assert "未知市场" in str(ei.value)
    with pytest.raises(CatalogError):
        cat.symbol("uk", "0001")


def test_symbols_data_shape_invariant(cat):
    """行内字段必须非空且 code 全数字（cn/hk）——数据质量守卫。"""
    for row in cat._symbols_market("cn")[:100]:
        assert len(row) == 4
        assert row[0].isdigit() and row[1]


# ---- 新鲜度 ----


def test_freshness_manifest(cat):
    """manifest 必须存在且覆盖三个市场（防"忘了写新鲜度"回归）。"""
    fresh = cat.symbols_freshness()
    assert fresh["as_of"] is not None
    assert set(fresh["markets"]) == {"cn", "hk", "us"}
    assert all(fresh["markets"].values())


def test_freshness_per_market(cat):
    assert cat.symbols_freshness("cn") == {"as_of": "2026-06-10"}
    assert cat.symbols_freshness("us")["as_of"] == "2026-08-10"
    with pytest.raises(CatalogError):
        cat.symbols_freshness("uk")
