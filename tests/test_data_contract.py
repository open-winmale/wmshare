"""数据质量契约：方向/新鲜度/空值语义/跨接口一致性。

数据质量的两层防线：
1. 运行时守护（units.yaml ranges/checks）——覆盖换算与量级，见 tests/test_units.py；
2. 本文件——**契约测试**：乱序输入必须升序输出、日期不得未来、None/0 语义稳定、
   同一事实在不同接口的读数必须一致；回放夹具自身结构由
   必须过结构校验（此前完全不校验）。
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import pytest

from wmshare.catalog import load
from wmshare.client import Client

# ---------------------------------------------------------------- fixtures


class RoutedSession:
    """按 xs_lines 中出现的函数名/指标码路由 canned 结果（不联网）。"""

    def __init__(self, results: dict[str, Any]):
        self.results = results
        self.eval_lines: list[str] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        cls = self

        class R:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                lines = "\n".join((json or {}).get("xs_lines") or [])
                cls.eval_lines.append(lines)
                for key, payload in cls.results.items():
                    if key in lines:
                        return {"success": True, "data": {"result": payload}}
                return {"success": True, "data": {"result": {"ok": True}}}

        R._cls = cls
        return R()


def make_client(results: dict[str, Any]) -> Client:
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  catalog=load(), session=RoutedSession(results))


def _unsorted_bars() -> list[dict[str, Any]]:
    # 罐头是上游原生口径：volume=手（SDK 换算为股），amount=元
    # （换算后 volume(股)×close ≈ amount，满足 volume_amount 不变量）
    return [
        {"date": "2026-11-17", "close": 10.0, "volume": 100.0, "amount": 100000.0,
         "percent": 0.01},
        {"date": "2026-11-15", "close": 9.8, "volume": 90.0, "amount": 88200.0,
         "percent": -0.01},
        {"date": "2026-11-16", "close": 9.9, "volume": 95.0, "amount": 94050.0,
         "percent": 0.01},
    ]


# ---------------------------------------------------- 序列方向 / 日期不未来


def test_series_faces_output_ascending():
    cli = make_client({"kline.query_bars": _unsorted_bars(),
                       "moneyflow.query_bars": [
                           {"date": "2026-11-17", "net_mf": 3},
                           {"date": "2026-11-10", "net_mf": 1}],
                       "margin.market_summary": [
                           {"trade_date": "2026-11-17", "exchange": "SSE",
                            "fin_balance": 1.0},
                           {"trade_date": "2026-11-10", "exchange": "SSE",
                            "fin_balance": 2.0}],
                       })
    k = cli.kline.bars("600519")
    assert list(k["date"]) == sorted(k["date"])
    m = cli.moneyflow.bars("600519")
    assert list(m["date"]) == sorted(m["date"])
    s = cli.margin.market_summary(limit=6)
    assert list(s["trade_date"]) == sorted(s["trade_date"])


def test_series_dates_not_in_future():
    today = date.today().isoformat()
    rows = [{"date": today, "close": 10.0, "volume": 100.0, "amount": 100000.0}]
    cli = make_client({"kline.query_bars": rows})
    df = cli.kline.bars("600519")
    assert all(d <= today for d in df["date"])


# ---------------------------------------------------- None / 0 语义


def test_null_and_zero_semantics_preserved():
    rows = [{"date": "2026-11-17", "close": None, "percent": 0.0,
             "volume": 1000.0, "amount": 10000.0}]
    cli = make_client({"kline.query_bars": rows})
    df = cli.kline.bars("600519")
    # None 原样保留（缺失 ≠ 0）；0 是真实读数，不得被清洗掉
    assert df.iloc[0]["close"] is None or math.isnan(df.iloc[0]["close"])
    assert float(df.iloc[0]["percent"]) == 0.0


def test_none_passthrough_in_indicator_and_ledger():
    from wmshare.units import finish_metric, ledger_convert

    assert finish_metric(None, None, code="$X") is None
    assert ledger_convert("$RE_INVEST", None) is None
    assert ledger_convert("$RE_INVEST", 0) == 0  # 0 是真实读数


# ---------------------------------------------------- as_of 契约


def test_envelope_as_of_iso_and_not_future():
    today = date.today().isoformat()
    cli = make_client({
        "valuation.daily_basic": {
            "ok": True, "as_of": today,
            "data": [{"date": today, "symbol": "600519", "field": "pe_ttm",
                      "value": 12.5}],
            "meta": {},
        },
        "indices.trend": {
            "ok": True, "as_of": today, "data": {"points": [{"d": today, "pe": 12.0}]},
            "meta": {},
        },
    })
    for call in (
        cli.valuation.daily_basic("600519"),
        cli.index.trend("index.hs300", "5y"),
    ):
        assert call["ok"] is True
        as_of = call["as_of"]
        if as_of:
            assert len(as_of) == 10 and as_of <= today, f"as_of 非法或未来：{as_of}"


# ---------------------------------------------------- 跨接口一致性


def test_snapshot_close_matches_bars_close():
    """同一事实的两条读数路径必须一致：快照 close ≈ 日 K 最新 close。"""
    cli = make_client({
        "kline.snapshot": {"symbol": "600519", "close": 10.0, "percent": 0.01,
                           "volume": 1000.0, "amount": 10000.0},
        "kline.query_bars": _unsorted_bars(),
    })
    snap = cli.kline.snapshot("600519")
    bars = cli.kline.bars("600519")
    latest = float(bars.iloc[-1]["close"])
    assert math.isclose(float(snap["close"]), latest, rel_tol=0.25)


def test_dividend_yield_matches_indicator():
    """分红面 yield_ttm 与指标 $BONUS_RATE_TTM_LAST 是同一口径。"""
    cli = make_client({
        "bonus.snapshot_yield_ttm": 0.045,
        "$BONUS_RATE_TTM_LAST": 0.045,
    })
    via_face = cli.dividend.yield_ttm("600519")
    via_metric = cli.indicator.get("600519", "$BONUS_RATE_TTM_LAST")
    assert via_face is not None and via_metric is not None
    assert math.isclose(float(via_face), float(via_metric), rel_tol=0.02)


def test_daily_basic_sorts_long_table_ascending():
    """服务端按日期降序返回；门面必须按 (date, field) 升序（2.0 契约）。

    2026-11-24 live 实测：服务端返回 11-13 → 11-10（同日按字段），与 docstring
    「升序」相反；分页拼接也不能保证全局序，故门面必须最终排序。
    """
    rows = [
        {"date": "2026-11-13", "symbol": "600519", "field": "pb", "value": 8.1},
        {"date": "2026-11-12", "symbol": "600519", "field": "pe_ttm", "value": 21.3},
        {"date": "2026-11-13", "symbol": "600519", "field": "pe_ttm", "value": 21.5},
        {"date": "2026-11-12", "symbol": "600519", "field": "pb", "value": 8.0},
    ]
    cli = make_client({"valuation.daily_basic": {
        "ok": True, "as_of": "2026-11-13", "data": rows, "meta": {}}})
    env = cli.valuation.daily_basic("600519")
    got = [(r["date"], r["field"]) for r in env["data"]]
    assert got == sorted(got), got


def test_daily_basic_multi_sorts_symbol_date_field():
    """多票长表按 (symbol, date, field) 升序：每票内 date 升序、块间按代码。"""
    rows = [
        {"date": "2026-11-13", "symbol": "000001", "field": "pe_ttm", "value": 5.0},
        {"date": "2026-11-13", "symbol": "600519", "field": "pe_ttm", "value": 21.5},
        {"date": "2026-11-12", "symbol": "600519", "field": "pe_ttm", "value": 21.3},
        {"date": "2026-11-12", "symbol": "000001", "field": "pe_ttm", "value": 4.9},
    ]
    cli = make_client({"valuation.daily_basic_multi": {
        "ok": True, "as_of": "2026-11-13", "data": rows, "meta": {}}})
    env = cli.valuation.daily_basic_multi(["600519", "000001"])
    got = [(r["symbol"], r["date"], r["field"]) for r in env["data"]]
    assert got == sorted(got), got


def test_daily_basic_pe_matches_indicator():
    """valuation.daily_basic 的 pe_ttm 与指标 $PE_TTM_LAST 同口径（物化表 vs 现算）。"""
    today = date.today().isoformat()
    cli = make_client({
        "valuation.daily_basic": {
            "ok": True, "as_of": today,
            "data": [
                {"date": today, "symbol": "600519", "field": "pe_ttm", "value": 21.3},
                {"date": today, "symbol": "600519", "field": "pb", "value": 8.1},
            ],
            "meta": {},
        },
        "$PE_TTM_LAST": 21.3,
    })
    env = cli.valuation.daily_basic("600519", fields="pe_ttm")
    rows = [r for r in env["data"] if r["field"] == "pe_ttm"]
    assert rows and math.isclose(float(rows[0]["value"]),
                                 float(cli.indicator.get("600519", "$PE_TTM_LAST")),
                                 rel_tol=0.02)


