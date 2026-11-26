"""A 股专用门面的市场前置校验与空值归一。

背景（2026-11-26 复核）：`equity.query_holder10` 对港股标的静默返回空表，
`query_buyback_detail/plan` 返回 ``None``（调用方 ``len()`` 直接崩）。仓内
`market.intl.yaml:18` 的约定是「A 股调港美股函数多返回空」，反方向（只有 A 股
数据的函数被港股调用）必须显式拒绝，否则用户分不清「不支持」与「没数据」。
"""

from __future__ import annotations

import copy

import pytest

from wmshare.api import _require_cn_market
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import UsageError


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}
        self.text = "{}"

    def json(self):
        return self._body


class _CannedSession:
    """eval 恒返回同一份罐头结果（与 tests/test_units.py 同款最小回放）。"""

    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append(url)
        if url.endswith("/v1/oauth/token"):
            return _Resp({"data": {"access_token": "tok", "expires_in": 3600}})
        return _Resp(
            {"success": True, "data": {"result": copy.deepcopy(self.result)}}
        )


def _client(result, **kw) -> Client:
    return Client(
        base_url="https://t",
        client_id="i",
        client_secret="s",
        catalog=load(),
        session=_CannedSession(result),
        **kw,
    )


def test_require_cn_market_passes_for_cn():
    class C:
        market = "cn"

    _require_cn_market(C(), "demo.fn")  # 不抛


def test_require_cn_market_rejects_hk_with_alt_hint():
    class C:
        market = "HK"  # 大小写不敏感

    with pytest.raises(UsageError) as ei:
        _require_cn_market(
            C(), "equity.query_holder10", alt="cli.intl.query_shareholders"
        )
    assert ei.value.code == "market"
    assert "仅支持 A 股" in str(ei.value)
    assert "query_shareholders" in str(ei.value)


def test_holder10_rejects_hk_client():
    c = _client([], market="hk")
    with pytest.raises(UsageError) as ei:
        c.equity.query_holder10("00700")
    assert ei.value.code == "market"


def test_buyback_detail_none_becomes_empty_list(monkeypatch):
    """港股无明细面时上游给 None；门面须归一为 []（返回形态仍是行数组，不变）。"""
    c = _client([])
    monkeypatch.setattr(c, "call", lambda *a, **k: None)
    assert c.equity.query_buyback_detail("600519") == []


def test_buyback_plan_none_becomes_empty_frame(monkeypatch):
    c = _client([])
    monkeypatch.setattr(c, "call", lambda *a, **k: None)
    out = c.equity.query_buyback_plan("600519")
    assert hasattr(out, "empty") and out.empty
