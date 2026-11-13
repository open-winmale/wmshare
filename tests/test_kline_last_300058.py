"""300058 / cli.kline.last() 完整回归测试（默认离线、零凭证可跑）。

运行（项目根目录）：
    PYTHONPATH=src python -m pytest -q tests/test_kline_last_300058.py

联网冒烟（需 ~/.wmshare/credentials.env 或 WMSHARE_* 环境变量）：
    WMSHARE_LIVE_SMOKE=1 PYTHONPATH=src python -m pytest -q tests/test_kline_last_300058.py

覆盖：Client() 无参凭证错误、store.latest 取当日、9 字段/单位、数值锚点、
_raw 原生单位、批量、demo 显式报错、真实客户端新鲜度冒烟。
"""
from __future__ import annotations

import os
from datetime import date

import pytest

import wmshare
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import AuthError, UsageError

SYM = "300058"
FIELDS = {"sas", "date", "open", "high", "low", "close", "volume", "amount", "percent"}

# store.latest 原始行（2026-11-13 收盘 D317）：percent=百分数、volume=手、amount=元
RAW_LAST = {
    "annual": 2026, "sampling": "D317", "samplingTs": 1794499200,
    "open": 14.29, "high": 14.58, "low": 13.63, "close": 13.63,
    "volume": 5239008, "amount": 7328118768.01, "percent": -7.6558,
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


def last_xs(c):
    ev = [x for x in c.session.calls if x["url"].endswith("/xs/eval")][-1]
    return ev["json"]["xs_lines"]


# ---- 1. 用户那三行为什么跑不通 ----

def test_bare_client_raises_auth_error():
    """__init__ 不读环境变量 / 凭证文件，零参构造必然缺凭证。"""
    with pytest.raises(AuthError, match="缺少凭证"):
        wmshare.Client()
    # 正确姿势：wmshare.Client.from_env()，或显式 client_id/client_secret


# ---- 2. 修复点：last 走 store.latest，含当日已入库日 K ----

def test_last_uses_query_last_not_anchor_window(client):
    client.session.eval_result = dict(RAW_LAST)
    bar = client.kline.last(SYM)
    assert last_xs(client) == ['return kline.query_last("300058")']
    assert bar["date"] == "2026-11-13" and bar["sas"] == "2026:D317"


def test_query_last_default_call_no_range_error(client):
    """目录补 percent 单位声明后，默认调用不再被 ranges 误杀。"""
    client.session.eval_result = dict(RAW_LAST)
    out = client.call("kline.query_last", sym=SYM)
    assert out["percent"] == pytest.approx(-0.076558)
    assert out["volume"] == 523900800.0


def test_last_fields_and_units(client):
    client.session.eval_result = dict(RAW_LAST)
    bar = client.kline.last(SYM)
    assert set(bar) == FIELDS
    assert bar["close"] == 13.63
    assert bar["percent"] == pytest.approx(-0.076558)      # 百分数 → 小数
    assert bar["volume"] == 523900800.0                     # 手 → 股
    assert bar["amount"] == pytest.approx(7328118768.01)   # 元，不换算


def test_last_numeric_anchors(client):
    client.session.eval_result = dict(RAW_LAST)
    b = client.kline.last(SYM)
    assert b["low"] <= b["amount"] / b["volume"] <= b["high"]          # VWAP ∈ 当日振幅
    assert b["close"] / (1 + b["percent"]) == pytest.approx(14.76, abs=0.01)  # 前收
    assert 0.4 <= b["volume"] * b["close"] / b["amount"] <= 2.5       # volume_amount 守护


def test_last_raw_keeps_native_units(client):
    client.session.eval_result = dict(RAW_LAST)
    raw = client.kline.last(SYM, _raw=True)
    assert raw["percent"] == -7.6558 and raw["volume"] == 5239008
    assert raw["sampling"] == "D317" and "date" not in raw


def test_last_batch(client):
    client.session.eval_result = {SYM: dict(RAW_LAST), "600519": dict(RAW_LAST)}
    batch = client.kline.last([SYM, "600519"])
    assert set(batch.results) == {SYM, "600519"} and not batch.errors
    assert all(r["date"] == "2026-11-13" for r in batch.results.values())


def test_demo_rejects_unknown_symbol():
    """demo 快照不含 300058，必须显式报错而非返回 None 冒充成功。"""
    with pytest.raises(UsageError, match="演示宇宙"):
        wmshare.demo_client().kline.last(SYM)


# ---- 3. 联网冒烟（需凭证 + 显式开关；收盘后运行）----

@pytest.mark.skipif(os.getenv("WMSHARE_LIVE_SMOKE") != "1",
                    reason="设置 WMSHARE_LIVE_SMOKE=1 才联网")
def test_live_smoke_from_env():
    cli = wmshare.Client.from_env()
    bar = cli.kline.last(SYM)
    assert set(bar) == FIELDS
    assert bar["date"] <= date.today().isoformat()       # 不得是未来
    assert -1 <= bar["percent"] <= 1                     # 小数口径
    assert bar["low"] <= bar["amount"] / bar["volume"] <= bar["high"]
    # bars(n=1) 走回测锚点窗口，允许比 last 早，但字段集必须一致
    anchor = cli.kline.bars(SYM, n=1)[0]
    assert set(anchor) == FIELDS
    assert bar["date"] >= anchor["date"]
    # 收盘后实时快照应与 last 同日
    assert cli.kline.live(SYM)["date"] == bar["date"]
