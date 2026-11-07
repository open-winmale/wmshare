"""cb.daily 取数编排测试：请求记账、快照日校验、日 K 陈旧跳过、预算硬顶。

用假客户端核算「发了几个请求」，因为免费档限流按请求数计——编排层多发的
每一个请求都是真实成本，也是「换个账号就撞 429」的常见来源。
"""
from __future__ import annotations

import pytest

from wmshare.cb import daily as D


def _row(code="110001", **kw):
    base = {
        "bondCode": code, "bondName": f"债{code}", "stockCode": "600000",
        "stockName": "浦发银行", "bondPrice": 100.0, "premiumRatio": 0.05,
        "remainSize": 5.0e9, "issueScale": 6.0e9, "expireDate": "2029-11-06",
        "redeemTrig": 13.0, "stockPrice": 10.0, "convertPrice": 10.0,
        "redeemValue": 110.0, "couponIr": 0.015, "asOf": "2026-11-06",
    }
    base.update(kw)
    return base


class FakeCbond:
    """记录调用次数的假 cbond 命名空间。"""

    def __init__(self, rows, events=None, windows=None, fail_kline=()):
        self.rows = rows
        self.events = events if events is not None else []
        self.windows = windows or {}
        self.fail_kline = set(fail_kline)
        self.calls: list[str] = []

    def board(self):
        self.calls.append("board")
        return self.rows

    def event_list(self):
        self.calls.append("event_list")
        return self.events

    def kline_window(self, code, n):
        self.calls.append(f"kline:{code}")
        if code in self.fail_kline:
            raise RuntimeError("上游超时")
        return self.windows.get(code, {})


class FakeCli:
    def __init__(self, cbond):
        self.cbond = cbond


def _window(dates, closes):
    """上游是降序（新→旧），含 samplingName 与 close 两列。"""
    return {"samplingName": list(dates)[::-1], "close": list(closes)[::-1]}


def test_fetch_snapshot_uses_three_calls_for_three_featured():
    cb = FakeCbond(
        [_row("110001"), _row("110002"), _row("110003")],
        windows={c: _window(["2026-11-06"], [100.0])
                 for c in ("110001", "110002", "110003")},
    )
    snap = D.fetch_snapshot(FakeCli(cb))
    assert cb.calls.count("board") == 1
    assert cb.calls.count("event_list") == 1
    assert snap["coverage"]["requests_made"] == 5      # 2 + 3 只 featured
    assert snap["coverage"]["budget"] == 30
    assert snap["asOf"] == "2026-11-06"


def test_featured_klines_are_flipped_ascending():
    """上游 close 降序；通道图要按时间升序画，否则曲线左右颠倒。"""
    cb = FakeCbond([_row("110001")],
                   windows={"110001": _window(
                       ["2026-11-04", "2026-11-05", "2026-11-06"], [101.0, 102.0, 103.0])})
    snap = D.fetch_snapshot(FakeCli(cb))
    k = snap["featured_klines"]["110001"]
    assert k["dates"] == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert k["closes"] == [101.0, 102.0, 103.0]
    assert k["last_bar_date"] == "2026-11-06"


def test_single_kline_failure_does_not_break_the_run():
    cb = FakeCbond([_row("110001"), _row("110002")], fail_kline={"110001"},
                   windows={"110002": _window(["2026-11-06"], [99.0])})
    snap = D.fetch_snapshot(FakeCli(cb))
    assert "error" in snap["featured_klines"]["110001"]
    assert snap["featured_klines"]["110002"]["closes"] == [99.0]


def test_empty_window_recorded_as_error():
    cb = FakeCbond([_row("110001")], windows={"110001": {}})
    snap = D.fetch_snapshot(FakeCli(cb))
    assert snap["featured_klines"]["110001"]["error"] == "空窗口"


def test_budget_is_a_hard_cap():
    cb = FakeCbond([_row(f"11000{i}") for i in range(1, 6)],
                   windows={f"11000{i}": _window(["2026-11-06"], [100.0])
                            for i in range(1, 6)})
    with pytest.raises(RuntimeError, match="超出本期预算"):
        D.fetch_snapshot(FakeCli(cb), config=D.DailyConfig(budget=3))


def test_empty_board_refuses_to_publish():
    with pytest.raises(RuntimeError, match="返回空"):
        D.fetch_snapshot(FakeCli(FakeCbond([])))


def test_as_of_far_from_snapshot_is_rejected():
    cb = FakeCbond([_row()])
    with pytest.raises(RuntimeError, match="相差超过 1 天"):
        D.fetch_snapshot(FakeCli(cb), as_of="2026-10-01")


def test_as_of_one_day_behind_is_tolerated():
    """盘前跑时快照仍是上一交易日，允许 T-1。"""
    snap = D.fetch_snapshot(FakeCli(FakeCbond([_row()])), as_of="2026-11-07")
    assert snap["asOf"] == "2026-11-06"


def test_run_daily_accepts_precomputed_snapshot():
    """重跑成稿时不应二次取数。"""
    cb = FakeCbond([_row()])
    snap = {"asOf": "2026-11-06", "rows": cb.rows, "events": [],
            "featured_klines": {}, "coverage": {"requests_made": 0},
            "intraday_risk": False}
    payload = D.run_daily(FakeCli(cb), snapshot=snap)
    assert cb.calls == []                     # 一次请求都没发
    assert payload["snapshot_asOf"] == "2026-11-06"
    assert payload["top"]


def test_run_daily_records_coverage_and_intraday_flag():
    prev = D._today()
    try:
        D._today = lambda: "2026-11-06"       # 让「今天」等于快照日
        cb = FakeCbond([_row()])
        payload = D.run_daily(FakeCli(cb))
        assert payload["coverage"]["requests_made"] == 3   # 面板 + 事件 + 1 只 featured
        assert "intraday_risk" in payload
    finally:
        D._today = prev
