"""P1 #11/#12 回归：返回形态与指数键路由的坑必须显式标注，不得静默。

上游行为（单 MAP、错误 key 500、冷缓存空数组、指数键无数据）本仓不能改，
因此把口径写进域 YAML notes（域级进 docs/API.md + llms-full.txt，函数级进
cat.function 合同），并钉住「SDK 不自动改写路由、不把空结果当 0」的决策。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import wmshare
from wmshare.api import KlineApi

REPO = Path(__file__).resolve().parents[1]

KLINE_NOTES = ("冷缓存返回空数组", "不得把空数组当 0", "query_index_last_live",
               "不得解读为")
MONEYFLOW_NOTES = ("NotSupportedType", "不静默转空", "query_bars(limit=1)")
INDEX_NOTES = ("indices.weights", "HTTP 500", "不降级为空数组")


def _notes(obj: dict) -> str:
    return " ".join(obj.get("notes") or [])


def test_kline_domain_notes_cover_cold_cache_and_index_routing():
    cat = wmshare.load()
    text = _notes(cat.domain("market.kline"))
    for kw in KLINE_NOTES:
        assert kw in text, kw


def test_function_level_notes_are_queryable():
    cat = wmshare.load()
    assert "冷缓存" in _notes(cat.function("kline.query_bars_live"))
    assert "NotSupportedType" in _notes(cat.function("moneyflow.query_last"))
    assert "ServerError" in _notes(cat.function("moneyflow.query_last"))


def test_moneyflow_and_index_domain_notes_cover_shape_failures():
    cat = wmshare.load()
    mf = _notes(cat.domain("market.moneyflow"))
    idx = _notes(cat.domain("market.index"))
    for kw in MONEYFLOW_NOTES:
        assert kw in mf, kw
    for kw in INDEX_NOTES:
        assert kw in idx, kw


def test_notes_reach_public_docs_and_llms():
    """域级 notes 必须出现在对外文档里，否则 Agent 从工具清单看不到坑。"""
    for name in ("docs/API.md", "llms-full.txt"):
        text = (REPO / name).read_text(encoding="utf-8")
        for kw in ("冷缓存返回空数组", "NotSupportedType", "indices.weights 传入未注册"):
            assert kw in text, (name, kw)


def test_index_live_entrypoints_are_discoverable():
    """上游四个指数盘中入口须在目录中可见（供调用方显式选路）。"""
    cat = wmshare.load()
    names = set(cat.functions_by_domain()["market.kline"])
    expected = {"kline.query_index_last_live", "kline.query_index_last_live_many",
                "kline.query_index_min1_live", "kline.query_index_min1_live_meta"}
    assert expected <= names


def test_sdk_does_not_silently_rewrite_index_route():
    """决策：不自动把个股 live 入口改写成指数入口（避免破坏兼容与口径）。"""
    for method in ("live", "batch_live", "min1"):
        src = inspect.getsource(getattr(KlineApi, method))
        assert "query_index_" not in src, method
