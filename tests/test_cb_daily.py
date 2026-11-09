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


class FakeMacro:
    """假 macro 命名空间：固定曲线点，记录调用（失败曲线用于验证降级）。"""

    def __init__(self, value: float = 0.02, fail: tuple[str, ...] = ()):
        self.value = value
        self.fail = set(fail)
        self.calls: list[tuple[str, str]] = []

    def bond_curve(self, curve_name, tenor):
        self.calls.append((curve_name, tenor))
        if curve_name in self.fail:
            raise RuntimeError("曲线不可用")
        return self.value


class FakeBatch:
    def __init__(self, results):
        self.results = results


class FakeCli:
    """假客户端：cbond + macro + call_batch。

    ``call_batch`` 必须与真实实现同构（返回 ``{code: 降序窗口}``），否则
    「批量富化」这条链路在测试里永远走不到，等于没测。
    """

    def __init__(self, cbond, macro=None):
        self.cbond = cbond
        self.macro = macro or FakeMacro()
        self.batch_calls: list[tuple[str, list[str], int | None]] = []

    def call_batch(self, name, symbols, **kw):
        self.batch_calls.append((name, list(symbols), kw.get("n")))
        windows = getattr(self.cbond, "windows", {}) or {}

        class _R:
            pass

        r = _R()
        r.results = {c: windows.get(c, {}) for c in symbols}
        return r


def _window(dates, closes, amounts=None):
    """上游是降序（新→旧），含 samplingName / close / amount 三列。"""
    w = {"samplingName": list(dates)[::-1], "close": list(closes)[::-1]}
    if amounts is not None:
        w["amount"] = list(amounts)[::-1]
    return w


def test_fetch_snapshot_uses_three_calls_for_three_featured():
    cb = FakeCbond(
        [_row("110001"), _row("110002"), _row("110003")],
        windows={c: _window(["2026-11-06"], [100.0])
                 for c in ("110001", "110002", "110003")},
    )
    cli = FakeCli(cb)
    # 关掉富化与曲线，只测 featured 通道拨测的请求数
    snap = D.fetch_snapshot(cli, config=D.DailyConfig(enrich=False, curves=False))
    assert cb.calls.count("board") == 1
    assert cb.calls.count("event_list") == 1
    assert snap["coverage"]["requests_made"] == 5      # 2 + 3 只 featured
    assert snap["coverage"]["budget"] == D.DEFAULT_BUDGET
    assert snap["asOf"] == "2026-11-06"
    assert cli.batch_calls == [] and cli.macro.calls == []


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
    # 保存的是函数本身，不是调用结果——原实现存了字符串，restore 时把
    # D._today 换成 str，后续任何测试都会 TypeError。
    prev = D._today
    try:
        D._today = lambda: "2026-11-06"       # 让「今天」等于快照日
        cb = FakeCbond([_row()])
        payload = D.run_daily(FakeCli(cb),
                              config=D.DailyConfig(enrich=False, curves=False))
        assert payload["coverage"]["requests_made"] == 3   # 面板 + 事件 + 1 只 featured
        assert "intraday_risk" in payload
    finally:
        D._today = prev


def test_batch_enrichment_covers_all_in_market_bonds_in_one_call():
    """全表富化必须是「一次批量」，逐票循环会先撞 429 再被 EC 账单教育。"""
    codes = [f"11000{i}" for i in range(1, 6)]
    cb = FakeCbond([_row(c) for c in codes],
                   windows={c: _window(["2026-11-05", "2026-11-06"], [100.0, 101.0],
                                       amounts=[1.0e7, 2.0e7]) for c in codes})
    cli = FakeCli(cb)
    snap = D.fetch_snapshot(cli, config=D.DailyConfig(curves=False))
    assert len(cli.batch_calls) == 1                       # 5 只一批
    name, syms, n = cli.batch_calls[0]
    assert name == "cbond.kline_window" and sorted(syms) == codes
    assert n == D.KLINE_BARS
    assert len(snap["enrichment"]) == 5
    assert snap["enrichment"]["110001"]["closes"] == [100.0, 101.0]
    assert snap["enrichment"]["110001"]["amount"] == 2.0e7   # 取最新一根


def test_curve_points_are_collected_and_bad_points_dropped():
    cb = FakeCbond([_row()])
    macro = FakeMacro()
    snap = D.fetch_snapshot(FakeCli(cb, macro),
                            config=D.DailyConfig(enrich=False))
    assert set(snap["curves"]) == {"aaa", "gov"}
    assert len(snap["curves"]["aaa"]) == len(D.CURVE_TENORS)
    assert len(macro.calls) == 2 * len(D.CURVE_TENORS)
    # 只给了 1 个点的曲线不足以插值，整档丢弃
    assert snap["coverage"]["curve_points"] == {"aaa": 5, "gov": 5}


def test_curve_failure_degrades_without_killing_the_run():
    cb = FakeCbond([_row()])
    macro = FakeMacro(fail=(D.CURVES["aaa"],))
    snap = D.fetch_snapshot(FakeCli(cb, macro), config=D.DailyConfig(enrich=False))
    assert "aaa" not in snap["curves"] and "gov" in snap["curves"]


def test_data_date_and_requested_date_are_both_reported():
    """数据日与请求日必须同时可见：调用方拿它决定产物命名与是否拒绝出稿。"""
    cb = FakeCbond([_row()])          # _row 的 asOf 是 2026-11-06
    snap = D.fetch_snapshot(FakeCli(cb), as_of="2026-11-07",
                            config=D.DailyConfig(enrich=False, curves=False))
    assert snap["data_date"] == "2026-11-06"
    assert snap["requested_date"] == "2026-11-07"
    assert snap["date_mismatch_days"] == -1        # 数据比请求日早 1 天
    assert snap["coverage"]["data_date"] == "2026-11-06"
    assert snap["coverage"]["date_mismatch_days"] == -1


def test_same_day_run_has_no_mismatch():
    cb = FakeCbond([_row()])
    snap = D.fetch_snapshot(FakeCli(cb), as_of="2026-11-06",
                            config=D.DailyConfig(enrich=False, curves=False))
    assert snap["date_mismatch_days"] is None
    assert snap["data_date"] == snap["requested_date"] == "2026-11-06"


def test_run_daily_propagates_date_fields_to_payload():
    cb = FakeCbond([_row()])
    payload = D.run_daily(FakeCli(cb), as_of="2026-11-07",
                          config=D.DailyConfig(enrich=False, curves=False))
    assert payload["data_date"] == "2026-11-06"
    assert payload["requested_date"] == "2026-11-07"
    assert payload["date_mismatch_days"] == -1


def test_resale_window_gates_put_distance():
    """剩余 >2 年时回售条款未生效，不能给出「距离」。"""
    long_row = _row("110001", expireDate="2031-11-06", resaleTrig=7.0)
    short_row = _row("110002", expireDate="2027-06-06", resaleTrig=7.0)
    payload = D.run_daily(FakeCli(FakeCbond([long_row, short_row])),
                          as_of="2026-11-06",
                          config=D.DailyConfig(enrich=False, curves=False))
    st = {s["bondCode"]: s for s in payload["states"]}
    assert st["110001"]["resale_window"] == "not_yet"
    assert st["110001"]["put_dist_pct"] is None
    assert st["110001"]["resale_trig"] == 7.0        # 触发价本身仍保留
    assert st["110002"]["resale_window"] == "open"
    assert st["110002"]["put_dist_pct"] is not None
