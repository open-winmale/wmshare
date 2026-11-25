"""单位契约一致性回归（默认离线、零凭证可跑）。

运行：
    PYTHONPATH=src python -m pytest -q tests/test_unit_contract.py

联网冒烟（需凭证，收盘后运行）：
    WMSHARE_LIVE_SMOKE=1 PYTHONPATH=src python -m pytest -q tests/test_unit_contract.py

背景：同一根日 K 曾在不同入口返回三套单位——last()/live() 给「股 + 小数」，
batch_live()/snapshot() 给「手 + 小数」，query_last_adj 给「手 + 百分数」，
且不抛任何错；equity.query_holdernum 的户数变化率下界写成 0，默认调用抛 DataError。
本文件把这些口径钉到目录声明与运行时结果上，防止再次漂移。
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
import yaml

import wmshare
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import DataError
from wmshare.units import apply_units

SYM = "300058"
LIVE_SMOKE = pytest.mark.skipif(os.getenv("WMSHARE_LIVE_SMOKE") != "1",
                                reason="设置 WMSHARE_LIVE_SMOKE=1 才联网")

# 所有返回 A 股 bar 且 volume 上游为「手」的已发布函数；缺任一条即会静默差 100 倍
LOT_FUNCS = {
    "kline.query_bars", "kline.query_bars_period", "kline.query_bars_adj",
    "kline.query_bars_period_adj", "kline.query_last", "kline.query_last_live",
    "kline.query_last_live_many", "kline.query_last_adj", "kline.snapshot",
    "kline.query_min1_live",
}
# 这两个函数上游 percent 仍是百分数，其余 bar 入口由上游格式化层改成小数
PERCENT_FUNCS = {"kline.query_last", "kline.query_last_adj"}

LIVE_BAR = {
    "date": "2026-11-13", "open": 14.29, "high": 14.58, "low": 13.63,
    "close": 13.63, "volume": 5239008, "amount": 7328118768.01,
    "percent": -0.0766,
}


class FakeSession:
    """复现 OpenAPI 合同：/v1/oauth/token + /v1/analysis/xs/eval，不联网。"""

    def __init__(self):
        self.calls = []
        self.eval_result = {"ok": True}

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})

        class R:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True, "data": {"result": self._cls.eval_result}}

        R._cls = self
        return R()


@pytest.fixture()
def client():
    return Client(base_url="https://test-api.winmale.com", client_id="id",
                  client_secret="sec", catalog=load(), session=FakeSession(),
                  market="cn")


# ---- 1. 目录声明本身（离线）----

def test_every_bar_entry_declares_lot_volume():
    cat = load()
    missing = {n for n in LOT_FUNCS
               if (cat.function(n).get("units") or {}).get("volume") != "lot"}
    assert not missing, f"这些 bar 入口缺 units.volume=lot：{sorted(missing)}"


def test_percent_declarations_match_upstream_scale():
    cat = load()
    for n in PERCENT_FUNCS:
        assert (cat.function(n).get("units") or {}).get("percent") == "percent"
    # 实时源上游已是小数，不能再声明 percent（否则会再除 100）
    for n in ("kline.query_last_live", "kline.query_last_live_many",
              "kline.snapshot", "kline.query_min1_live"):
        assert "percent" not in (cat.function(n).get("units") or {}), n


def test_live_single_and_batch_share_volume_unit():
    cat = load()
    one = cat.function("kline.query_last_live").get("units") or {}
    many = cat.function("kline.query_last_live_many").get("units") or {}
    assert one.get("volume") == many.get("volume") == "lot"


def test_change_rate_ranges_allow_legitimate_negative():
    """变化率/预告幅度可为远低于 -1 的合法负值，range 下界不能误杀默认调用。"""
    cat = load()
    fn = cat.function("equity.query_holdernum")
    assert fn["ranges"]["total_num_ratio"][0] <= -1
    row = {"total_num_ratio": -0.060863}
    apply_units(row, fn, fname="equity.query_holdernum")
    assert row["total_num_ratio"] == pytest.approx(-0.060863)

    # 净利由盈转亏，实测 native -443.09%（百分数）→ 换算后 -4.4309（小数）
    for name in ("forecast.yjyg_rows", "forecast.yjyg_latest", "forecast.snapshot",
                 "forecast.yjkb_rows", "forecast.yjkb_latest"):
        rng = cat.function(name)["ranges"]
        for field in ("np_amp_lower", "np_amp_upper", "rev_amp_lower",
                      "rev_amp_upper", "np_yoy", "rev_yoy"):
            if field in rng:
                assert rng[field][0] <= -4.4309, f"{name}.{field} 下界过紧"

    fn = cat.function("forecast.yjyg_rows")
    row = {"np_amp_lower": -443.09}
    apply_units(row, fn, fname="forecast.yjyg_rows")
    assert row["np_amp_lower"] == pytest.approx(-4.4309)


# ---- 2. 运行时换算（离线，覆盖 MAP 嵌套下探）----

def test_batch_live_converts_nested_bar_volume(client):
    client.session.eval_result = {SYM: dict(LIVE_BAR)}
    bar = client.kline.batch_live([SYM])[SYM]
    assert bar["volume"] == 523900800.0
    assert bar["percent"] == pytest.approx(-0.0766)


def test_snapshot_and_adj_convert_single_bar(client):
    client.session.eval_result = dict(LIVE_BAR)
    snap = client.kline.snapshot(SYM)
    assert snap["volume"] == 523900800.0
    assert snap["percent"] == pytest.approx(-0.0766)

    client.session.eval_result = dict(LIVE_BAR, percent=-7.6558)
    adj = client.call("kline.query_last_adj", sym=SYM)
    assert adj["volume"] == 523900800.0
    assert adj["percent"] == pytest.approx(-0.076558)


def test_min1_converts_each_bar_in_list(client):
    client.session.eval_result = {
        "trading_day": "2026-11-13", "bar_n": 1,
        "bars": [{"close": 14.35, "volume": 325006, "amount": 465026996}],
    }
    out = client.kline.min1(SYM)
    bar = out["bars"][0]
    assert bar["volume"] == 32500600.0
    assert bar["amount"] / bar["volume"] == pytest.approx(14.3083, abs=0.01)


# ---- 3. 联网冒烟（需凭证 + 显式开关）----

@LIVE_SMOKE
def test_live_smoke_five_entries_share_volume_and_vwap():
    cli = wmshare.Client.from_env()
    for sym in (SYM, "600519"):
        volumes = [
            cli.kline.last(sym)["volume"],
            cli.kline.live(sym)["volume"],
            cli.kline.batch_live([sym])[sym]["volume"],
            cli.kline.snapshot(sym)["volume"],
            cli.call("kline.query_last_adj", sym=sym)["volume"],
        ]
        assert len({round(v) for v in volumes}) == 1, f"{sym}: {volumes}"
        bar = cli.kline.live(sym)
        assert -1 <= bar["percent"] <= 1
        assert bar["low"] <= bar["amount"] / bar["volume"] <= bar["high"]


@LIVE_SMOKE
def test_live_smoke_declared_functions_default_call_no_data_error():
    """已发布且带单位/量级声明的函数，默认调用不得被量级守护误杀。

    只统计 DataError；参数填充造成的 UsageError / 上游 ServerError 不属于本条守护范围。
    """
    cli = wmshare.Client.from_env()
    cat = cli.catalog
    bad = []
    for p in sorted((Path(wmshare.__file__).parent / "_catalog" / "domains").glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for f in doc.get("functions") or []:
            if not (f.get("units") or f.get("ranges")):
                continue
            name = f["name"]
            fn = cat.function(name)
            params = fn.get("params") or cat.inventory_params(name)
            example = fn.get("example") or fn.get("inventory_example") or ""
            m = re.search(r"\((.*)\)\s*$", example)
            values = []
            if m:
                try:
                    values = list(ast.literal_eval("(" + m.group(1) + ","))
                except (ValueError, SyntaxError):
                    values = []
            kwargs = {}
            for i, param in enumerate(params):
                if not param.get("required"):
                    continue
                v = values[i] if i < len(values) else None
                n = param["name"]
                if v is None:
                    v = (SYM if n in ("sym", "symbol", "stk") else
                         [SYM] if n == "syms" else
                         "index.hs300" if n == "key" else
                         "113050" if n == "code" else
                         2 if n in ("limit", "n", "top_n") else "")
                kwargs[n] = v
            try:
                cli.call(name, **kwargs)
            except DataError as e:
                bad.append(f"{name}: {str(e).splitlines()[0][:120]}")
    assert not bad, "默认调用被量级守护误杀：" + "; ".join(bad)
