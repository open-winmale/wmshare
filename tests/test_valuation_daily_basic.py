"""valuation.daily_basic 门面契约（服务端物化 alt.valuation_daily，仅 CN）。

覆盖：字段校验/归一、信封直通、目录注册（units/ranges 可审计）、
estimate_cost cached_eval 档、demo 显式 demo_unsupported（不伪造）。
"""
from __future__ import annotations

import pytest

from wmshare.catalog import load
from wmshare.client import Client, estimate_cost
from wmshare.errors import UsageError

ENVELOPE = {
    "ok": True,
    "as_of": "2026-11-16",
    "data": [
        {"date": "2026-11-14", "symbol": "600519", "field": "pe_ttm", "value": 21.4},
        {"date": "2026-11-14", "symbol": "600519", "field": "total_mv", "value": 2.69e12},
    ],
    "meta": {"fields": ["pe_ttm", "total_mv"], "count": 2,
             "requested_unknown": [], "db": "alt.valuation_daily"},
}


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}
        self.text = "{}"

    def json(self):
        return self._body


class _CannedSession:
    """eval 每次返回 result 的深拷贝（同 test_units.CannedSession 口径）。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        if url.endswith("/v1/oauth/token"):
            return _Resp({"data": {"access_token": "tok", "expires_in": 3600}})
        import copy
        return _Resp({"success": True, "data": {"result": copy.deepcopy(self.result)}})


def make(result, **kw):
    s = _CannedSession(result)
    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=s, **kw)
    return c, s


# ---- 目录注册 ----

def test_daily_basic_registered_in_catalog():
    cat = load()
    fn = cat.function("valuation.daily_basic")
    assert fn["name"] == "valuation.daily_basic"
    dom = cat.domains["fund.valuation"]
    assert dom["category"] == "fundamentals"
    # 8 字段全部有量级声明（audit_units / guard_manifest 依赖）
    ranges = (fn.get("ranges") or dom.get("ranges") or {})
    assert set(ranges) >= {
        "pe_ttm", "pb", "ps", "pr", "total_mv", "circ_mv",
        "turnover_rate", "dv_ttm"}


# ---- 门面：字段校验与调用构造 ----

def test_daily_basic_default_all_fields_passthrough():
    c, s = make(dict(ENVELOPE))
    out = c.valuation.daily_basic("600519", begin="2026-01-01", end="2026-11-16")
    assert out == ENVELOPE  # 信封直通，不二次包装
    body = s.calls[-1]["json"]["xs_lines"]
    assert body[-1] == ('return valuation.daily_basic("600519", "2026-01-01", "2026-11-16", '
                        '["pe_ttm", "pb", "ps", "pr", "total_mv", "circ_mv", '
                        '"turnover_rate", "dv_ttm"])')


def test_daily_basic_fields_forms_and_dedup():
    c, s = make(dict(ENVELOPE))
    c.valuation.daily_basic("600519", fields="pe_ttm, total_mv")     # 逗号串 + 空格
    assert '["pe_ttm", "total_mv"]' in s.calls[-1]["json"]["xs_lines"][-1]
    c.valuation.daily_basic("600519", fields=["total_mv", "pe_ttm", "total_mv"])  # list 去重保序
    assert '["total_mv", "pe_ttm"]' in s.calls[-1]["json"]["xs_lines"][-1]
    with pytest.raises(UsageError, match="未知字段"):
        c.valuation.daily_basic("600519", fields="pe_ttm,not_a_field")
    with pytest.raises(UsageError, match="fields"):
        c.valuation.daily_basic("600519", fields=123)


# ---- estimate_cost：实测档（2026-11-18 生产 probe，非缓存） ----

def test_daily_basic_estimate_cost_measured():
    est = estimate_cost("valuation.daily_basic")
    assert est["model"] == "measured"
    # 单日地板 1,707 / 全史 18,317（实测端点）
    assert est["ec_lo"] == 1_707 and est["ec_hi"] == 18_317
    assert "非缓存" in est["note"]

    # 传窗口：地板 + ≈23 EC/自然日
    est2 = estimate_cost("valuation.daily_basic",
                         {"begin": "2026-11-01", "end": "2026-11-17"})
    assert est2["model"] == "measured"
    assert est2["ec_lo"] == 1_707
    assert est2["ec_hi"] == 1_707 + 23 * 17


# ---- demo：显式 demo_unsupported（诚实契约，无罐头不伪造） ----

def test_demo_daily_basic_unsupported():
    from wmshare._demo import demo_client

    c = demo_client()
    with pytest.raises(UsageError, match="demo_unsupported|demo 快照未收录"):
        c.valuation.daily_basic("600519")
