"""单股回测引擎：均线买卖点 → 成交明细/费用/整手/顺延/汇总（纯计算，离线）。"""
from __future__ import annotations

import datetime as dt

import pytest

from wmshare.backtest import (
    ma_cross_signals,
    run_backtest,
    valuation_by_date,
    valuation_signals,
)


def _bars(closes, opens=None, volumes=None):
    """构造升序日 K：默认 open=close、volume=1e5、high/low 各让 1 元。"""
    out = []
    day = dt.date(2024, 1, 1)
    for i, close in enumerate(closes):
        open_ = close if opens is None else opens[i]
        out.append({
            "date": (day + dt.timedelta(days=i)).isoformat(),
            "open": float(open_), "high": float(max(open_, close) + 1),
            "low": float(min(open_, close) - 1), "close": float(close),
            "volume": 100_000.0 if volumes is None else float(volumes[i]),
        })
    return out


def _sma(values, n):
    return [None if i < n - 1 else sum(values[i - n + 1:i + 1]) / n
            for i in range(len(values))]


def _crosses(closes, fast, slow):
    """独立算金叉/死叉下标（测试预期，不调用被测实现）。"""
    f, s = _sma(closes, fast), _sma(closes, slow)
    golden, death = [], []
    for i in range(1, len(closes)):
        if None in (f[i], s[i], f[i - 1], s[i - 1]):
            continue
        if f[i] > s[i] and f[i - 1] <= s[i - 1]:
            golden.append(i)
        elif f[i] < s[i] and f[i - 1] >= s[i - 1]:
            death.append(i)
    return golden, death


# 平 → 跳升（金叉）→ 回落（死叉）；fast=2/slow=3 → 金叉 i=6、死叉 i=8
CLOSES = [10.0] * 6 + [12.0] + [12.0] + [8.0] * 4
GOLDEN, DEATH = _crosses(CLOSES, 2, 3)


def _run(cash=10_000, closes=None, **overrides):
    closes = list(CLOSES if closes is None else closes)
    opens = list(closes)
    opens[GOLDEN[0] + 1] = 10.0          # 买入成交价固定 10 元
    if DEATH:
        opens[DEATH[0] + 1] = 9.0        # 卖出成交价固定 9 元
    bars = _bars(closes, opens)
    for index, patch in overrides.get("bars", {}).items():
        bars[index].update(patch)
    signals = ma_cross_signals(bars, 2, 3)
    return bars, run_backtest(bars, signals, cash=cash, rule="ma_cross(fast=2, slow=3)")


def test_cross_points_on_fixture():
    assert GOLDEN == [6] and DEATH == [8]


def test_ma_cross_buys_next_open_and_sells():
    bars, res = _run()
    assert res["rule"] == "ma_cross(fast=2, slow=3)"
    assert res["period"]["bars"] == len(bars)
    buy, sell = res["trades"][0], res["trades"][1]
    assert buy["side"] == "buy" and buy["reason"] == "金叉"
    assert buy["date"] == bars[GOLDEN[0] + 1]["date"]        # 次日开盘成交
    assert buy["price"] == 10.0
    assert sell["side"] == "sell" and sell["reason"] == "死叉"
    assert sell["date"] == bars[DEATH[0] + 1]["date"]
    assert sell["price"] == 9.0
    assert sell["hold_days"] == (DEATH[0] + 1) - (GOLDEN[0] + 1)


def test_lot_size_and_fees():
    bars, res = _run(cash=1_100)
    buy = res["trades"][0]
    assert buy["shares"] == 100                              # 1100 元 / 10 元 → 1 手
    assert buy["amount"] == pytest.approx(1_000.0)
    assert buy["fee"] == pytest.approx(5.0)                  # 0.3% < 5 元下限
    sell = res["trades"][1]
    assert sell["amount"] == pytest.approx(900.0)
    expected_fee = max(900.0 * 0.0003, 5.0) + 900.0 * 0.0005
    assert sell["fee"] == pytest.approx(round(expected_fee, 2))
    cost = buy["amount"] + buy["fee"]
    assert sell["pnl"] == pytest.approx(round(sell["amount"] - sell["fee"] - cost, 2))
    assert sell["ret"] == pytest.approx(sell["pnl"] / cost, rel=1e-4)
    assert sell["pnl"] < 0                                   # 10 元买、9 元卖


def test_one_word_bar_defers_fill():
    gap = GOLDEN[0] + 1
    bars, res = _run(bars={gap: {"open": 12.0, "high": 12.0, "low": 12.0,
                                 "close": 12.0}})
    assert res["caliber"]["skipped"] >= 1
    assert res["trades"][0]["date"] == bars[gap + 1]["date"]


def test_zero_volume_bar_defers_fill():
    gap = GOLDEN[0] + 1
    bars, res = _run(bars={gap: {"volume": 0.0}})
    assert res["caliber"]["skipped"] >= 1
    assert res["trades"][0]["date"] == bars[gap + 1]["date"]


def test_pending_buy_cancelled_by_death_cross():
    # 跳升当天金叉、次日崩盘死叉：买入挂单被撤，一笔都不成交
    closes = [10.0] * 6 + [12.0, 6.0] + [6.0] * 4
    golden, death = _crosses(closes, 2, 3)
    assert golden == [6] and death == [7]
    bars = _bars(closes)
    bars[golden[0] + 1]["volume"] = 0.0
    res = run_backtest(bars, ma_cross_signals(bars, 2, 3), cash=10_000,
                       rule="ma_cross(fast=2, slow=3)")
    assert res["trades"] == []
    assert res["caliber"]["skipped"] == 1
    assert res["summary"]["total_return"] == 0


def test_insufficient_cash_warns():
    closes = [10.0] * 6 + [12.0] * 6
    bars = _bars(closes)                                     # 次日开盘 12 元
    res = run_backtest(bars, ma_cross_signals(bars, 2, 3), cash=1_000,
                       rule="ma_cross(fast=2, slow=3)")   # 一手要 1200 元
    assert res["trades"] == []
    assert any("现金不足一手" in w for w in res["warnings"])


def test_force_close_at_end():
    closes = [10.0] * 6 + [12.0] * 6                         # 只金叉、不死叉
    bars = _bars(closes)
    res = run_backtest(bars, ma_cross_signals(bars, 2, 3), cash=10_000,
                       rule="ma_cross(fast=2, slow=3)")
    last = res["trades"][-1]
    assert last["side"] == "sell" and last["reason"] == "期末平仓"
    assert res["summary"]["n_trades"] == 1
    assert res["equity"][-1]["nav"] == pytest.approx(10_000 + last["pnl"], abs=0.01)


def test_unfillable_last_bar_keeps_position():
    closes = [10.0] * 6 + [12.0] * 6
    bars = _bars(closes)
    bars[-1].update({"open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0})
    res = run_backtest(bars, ma_cross_signals(bars, 2, 3), cash=10_000,
                       rule="ma_cross(fast=2, slow=3)")
    assert all(t["side"] == "buy" for t in res["trades"])
    assert any("未平仓" in w for w in res["warnings"])
    assert res["summary"]["n_trades"] == 0


def test_summary_math():
    bars, res = _run()
    navs = [row["nav"] for row in res["equity"]]
    summary = res["summary"]
    assert summary["total_return"] == pytest.approx(round(navs[-1] / 10_000 - 1, 6))
    closes = [b["close"] for b in bars]
    assert summary["buy_hold_return"] == pytest.approx(round(closes[-1] / closes[0] - 1, 6))
    assert summary["max_drawdown"] <= 0
    assert summary["n_trades"] == len([t for t in res["trades"] if t["side"] == "sell"])
    assert summary["avg_hold_days"] == pytest.approx(
        sum(t["hold_days"] for t in res["trades"] if t["side"] == "sell")
        / summary["n_trades"])
    assert summary["win_rate"] in (0.0, 1.0)


def test_rejects_bad_params():
    bars = _bars(CLOSES)
    with pytest.raises(ValueError, match="周期不合法"):
        ma_cross_signals(bars, fast=5, slow=5)
    with pytest.raises(ValueError, match="行情不足"):
        ma_cross_signals(_bars([10.0] * 4), 2, 3)
    with pytest.raises(ValueError, match="cash"):
        run_backtest(bars, ma_cross_signals(bars, 2, 3), cash=0)
    with pytest.raises(ValueError, match="信号长度"):
        run_backtest(bars, [None], cash=10_000)


def test_valuation_by_date_uses_exchange_local_day():
    # 2024-01-02 00:00 +08:00 = 2024-01-01 16:00 UTC
    ts = int(dt.datetime(2024, 1, 2, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp())
    values = valuation_by_date([[ts, 12.5], [ts + 86_400, None], ["bad", 1.0]])
    assert values == {"2024-01-02": 12.5}


def test_valuation_signals_thresholds_and_missing():
    bars = _bars([10.0, 10.0, 10.0, 10.0])
    values = {"2024-01-01": 15.0, "2024-01-02": 25.0, "2024-01-04": 45.0}
    signals, missing = valuation_signals(bars, values, buy=20, sell=40)
    assert signals == ["buy", None, None, "sell"]
    assert missing == 1                                   # 2024-01-03 没有估值
    with pytest.raises(ValueError, match="阈值不合法"):
        valuation_signals(bars, values, buy=40, sell=20)


def test_valuation_rule_end_to_end():
    bars = _bars([10.0] * 8)
    values = {"2024-01-01": 25.0, "2024-01-02": 18.0, "2024-01-03": 19.0,
              "2024-01-04": 30.0, "2024-01-05": 45.0, "2024-01-06": 50.0,
              "2024-01-07": 50.0, "2024-01-08": 50.0}
    signals, missing = valuation_signals(bars, values, buy=20, sell=40)
    res = run_backtest(bars, signals, cash=10_000, rule="pe(buy=20, sell=40)")
    assert res["rule"] == "pe(buy=20, sell=40)"
    buy, sell = res["trades"][0], res["trades"][1]
    assert buy["reason"] == "买点" and buy["date"] == bars[2]["date"]   # 01-02 收盘出信号 → 次日
    assert sell["reason"] == "卖点" and sell["date"] == bars[5]["date"]
    assert missing == 0
