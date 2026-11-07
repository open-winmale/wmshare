"""cb.rules 规则内核测试：闸门、状态机、事件索引、日历。

重点守三类历史事故：
1. 事件索引被截断（曾只存 200 条，下修状态错 22 只）；
2. 强赎计数按正股键控（同发行人双债互串）；
3. 计数达标 + 不赎回公告两事实并存时不许合成「已豁免」结论。
"""
from __future__ import annotations

import pytest

from wmshare.cb import rules as R


def _row(**kw):
    base = {
        "bondCode": "127061", "bondName": "美锦转债", "stockCode": "000723",
        "stockName": "美锦能源", "bondPrice": 97.5, "premiumRatio": 0.0442,
        "remainSize": 2.77e9, "issueScale": 3.0e9, "expireDate": "2028-04-20",
        "redeemTrig": 13.0, "stockPrice": 9.4, "convertPrice": 10.0,
        "redeemValue": 118.0, "couponIr": 0.025, "couponExplain": "第一年 0.30%",
        "resetFloor": 8.5, "asOf": "2026-11-06",
    }
    base.update(kw)
    return base


def _ev(**kw):
    base = {"bond_code": "127061", "bond_name": "美锦转债", "deal_type": "redeem",
            "announce_date": "2026-10-01", "title": "关于提前赎回的公告",
            "stock_code": "000723"}
    base.update(kw)
    return base


# ---------------- 闸门 ----------------
def test_gate_passes_clean_bond():
    rows = [_row()]
    by_bond, _ = R.build_event_index([], rows)
    assert R.gate_row(rows[0], by_bond, "2026-11-06") == []


@pytest.mark.parametrize("kw,reason", [
    ({"bondPrice": None}, "g1_no_price"),
    ({"bondPrice": 0}, "g1_no_price"),
    ({"remainSize": 0}, "g1_no_size"),
    ({"expireDate": "2026-04-09"}, "g1_expired"),
    ({"stockName": "ST美锦"}, "g2_st"),
    ({"stockName": "*ST美锦"}, "g2_st"),
    ({"expireDate": "2027-04-01"}, "g3_near_expiry"),   # 剩余 < 182 天
])
def test_gate_reasons(kw, reason):
    row = _row(**kw)
    by_bond, _ = R.build_event_index([], [row])
    hits = R.gate_row(row, by_bond, "2026-11-06")
    assert hits and hits[0][0] == reason


def test_gate_met15_when_hits_reach_threshold():
    row = _row(callHits=R.CALL_HITS_THRESHOLD)
    by_bond, _ = R.build_event_index([], [row])
    assert [h[0] for h in R.gate_row(row, by_bond, "2026-11-06")] == ["g3_met15"]


def test_gate_redeem_announcement_removes_bond():
    rows = [_row()]
    by_bond, _ = R.build_event_index(
        [_ev(deal_type="redeem", announce_date="2026-08-01")], rows)
    assert [h[0] for h in R.gate_row(rows[0], by_bond, "2026-11-06")] == ["g3_redeem"]


def test_gate_records_first_hit_only_but_all_hits_available():
    row = _row(bondPrice=None, stockName="ST美锦")
    by_bond, _ = R.build_event_index([], [row])
    hits = R.gate_row(row, by_bond, "2026-11-06")
    assert [h[0] for h in hits] == ["g1_no_price", "g2_st"]


def test_evaluate_counts_sum_to_excluded():
    rows = [_row(), _row(bondCode="110001", bondName="到期债",
                         expireDate="2025-01-01"),
            _row(bondCode="110002", bondName="ST债", stockName="ST某某")]
    by_bond, _ = R.build_event_index([], rows)
    out = R.evaluate(rows, by_bond, "2026-11-06")
    assert out["stats"]["excludedN"] == 2
    assert out["stats"]["passedN"] == 1
    assert sum(out["ruleHits"].values()) == out["stats"]["excludedN"]
    assert set(out["ruleHits"]) == {"g1_expired", "g2_st"}


def test_evaluate_sorts_passed_by_double_low():
    rows = [_row(bondCode="1", bondPrice=110.0, premiumRatio=0.10),
            _row(bondCode="2", bondPrice=100.0, premiumRatio=0.02)]
    by_bond, _ = R.build_event_index([], rows)
    out = R.evaluate(rows, by_bond, "2026-11-06")
    assert [p["bondCode"] for p in out["passed"]] == ["2", "1"]


# ---------------- 事件索引 ----------------
def test_event_index_keeps_events_beyond_any_page_size():
    """280 条干扰事件后仍有老的下修公告——索引必须全量，不能按页截断。"""
    events = [_ev(bond_code="999999", announce_date=f"2026-10-{d:02d}",
                  deal_type="price_adj") for d in range(1, 29) for _ in range(10)]
    events.append(_ev(deal_type="no_reset", announce_date="2026-08-20"))
    rows = [_row()]
    by_bond, stats = R.build_event_index(events, rows)
    rs = R.reset_state(rows[0], by_bond, "2026-11-06")
    assert rs["key"] == "no_reset"
    assert stats["total"] == len(events)


def test_event_index_claims_missing_bond_code_by_unique_stock():
    rows = [_row()]
    ev = _ev(bond_code="", stock_code="000723", deal_type="no_reset",
             announce_date="2026-10-01")
    by_bond, stats = R.build_event_index([ev], rows)
    assert "127061" in by_bond
    assert stats["ambiguous_stock"] == 0


def test_event_index_refuses_ambiguous_double_bond_issuer():
    """同一正股两只债、事件缺 bond_code → 不认领（宁可漏挂也不挂错）。"""
    rows = [_row(bondCode="113615", bondName="金诚转债", stockCode="603979"),
            _row(bondCode="113699", bondName="金25转债", stockCode="603979")]
    ev = _ev(bond_code="", stock_code="603979", deal_type="no_redeem")
    by_bond, stats = R.build_event_index([ev], rows)
    assert stats["ambiguous_stock"] == 1
    assert not any("113615" in v or "113699" in v for v in [list(by_bond)])


def test_event_index_dedupes_event_and_reset_event_slots():
    """board 行上的 event 与 resetEvent 可能是同一条，索引需去重。"""
    ev = _ev(deal_type="reset_proposal", announce_date="2026-10-20")
    row = _row(event=ev, resetEvent=ev)
    by_bond, _ = R.build_event_index([], [row])
    assert len(by_bond["127061"]) == 1


# ---------------- 状态机 ----------------
def test_call_state_idle_when_below_trigger():
    rows = [_row(stockPrice=5.0, redeemTrig=13.0)]
    by_bond, _ = R.build_event_index([], rows)
    st = R.call_state(rows[0], by_bond, "2026-11-06")
    assert st["key"] == "idle"


def test_call_state_met15_keeps_waiver_as_parallel_fact():
    """达标 + 不赎回公告：两个事实并列，不合成「已豁免」。"""
    rows = [_row(callHits=30, stockPrice=14.0)]
    ev = _ev(deal_type="no_redeem", announce_date="2026-10-31",
             title="关于不提前赎回的公告")
    by_bond, _ = R.build_event_index([ev], rows)
    st = R.call_state(rows[0], by_bond, "2026-11-06")
    assert st["key"] == "met15"
    assert st["no_redeem_since"] == "2026-10-31"
    assert st["no_redeem_days"] == 6
    assert "不赎回" in st["state"]
    # 措辞红线：不许替发行人下「豁免/解除」结论
    assert "豁免" not in st["state"] and "解除" not in st["state"]


def test_call_state_met15_without_waiver_has_no_waiver_fields():
    rows = [_row(callHits=30, stockPrice=14.0)]
    by_bond, _ = R.build_event_index([], rows)
    st = R.call_state(rows[0], by_bond, "2026-11-06")
    assert st["key"] == "met15"
    assert not st.get("no_redeem_since")


def test_waiver_outside_window_not_attached():
    rows = [_row(callHits=30, stockPrice=14.0)]
    ev = _ev(deal_type="no_redeem", announce_date="2025-01-01")
    by_bond, _ = R.build_event_index([ev], rows)
    st = R.call_state(rows[0], by_bond, "2026-11-06")
    assert not st.get("no_redeem_since")


def test_reset_state_proposal_pending():
    rows = [_row()]
    ev = _ev(deal_type="reset_proposal", announce_date="2026-10-20",
             meeting_date="2026-11-20")
    by_bond, _ = R.build_event_index([ev], rows)
    st = R.reset_state(rows[0], by_bond, "2026-11-06")
    assert st["key"] in ("proposed", "proposal_pending")
    assert st["floor"] == pytest.approx(8.5)


def test_reset_state_none_without_events():
    rows = [_row()]
    by_bond, _ = R.build_event_index([], rows)
    st = R.reset_state(rows[0], by_bond, "2026-11-06")
    assert st["key"] in ("none", "")


# ---------------- 日历 ----------------
def test_calendar_keeps_new_today_and_next_30d():
    rows = [_row(redeemTrig=13.0)]
    events = [
        _ev(deal_type="reset_proposal", announce_date="2026-11-06",
            title="董事会提议向下修正", meeting_date="2026-11-20"),
        _ev(deal_type="put", announce_date="2026-09-01", put_start="2026-11-10",
            put_end="2026-11-16", title="回售"),
    ]
    by_bond, _ = R.build_event_index(events, rows)
    cal = R.calendar(by_bond, rows, "2026-11-06")
    assert len(cal["newToday"]) == 1
    assert cal["newToday"][0]["type"] == "reset_proposal"
    dates = [c["date"] for c in cal["next30d"]]
    assert dates == sorted(dates)
    assert all(d >= "2026-11-06" for d in dates)
    assert any(c["type"] == "shareholder_meeting" for c in cal["next30d"])


def test_days_to_expire_and_in_market_base():
    row = _row(expireDate="2026-11-16")
    assert R.days_to_expire(row, "2026-11-06") == 10
    # 基座只认"有溢价率"（上游对已退出合约不给该字段）；可交易性交给 G1
    assert R.in_market_base(row)
    assert not R.in_market_base(_row(premiumRatio=None))
    assert R.in_market_base(_row(bondPrice=None))


def test_is_st_name_recognizes_prefix_and_suffix():
    assert R.is_st_name("ST某某")
    assert R.is_st_name("*ST某某")
    assert R.is_st_name("某某退")
    assert not R.is_st_name("某某股份")
    assert not R.is_st_name(None)
