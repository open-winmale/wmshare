"""单股买卖点回测（纯计算，无网络、无第三方依赖）。

两种信号源，撮合只有一条路径：

- ``ma_cross``：收盘价 ``SMA(fast)`` 上穿 ``SMA(slow)`` 买、下穿卖（相等算穿，与平台
  ``fin.ta_cross`` 同语义）；预热期（``slow`` 根之前）不出信号；
- ``pe``/``pb``/``ps``/``pr``：估值序列（``cli.valuation.hist_stats``，≤3 年日频）
  当根值 ``<= buy`` 买、``>= sell`` 卖；估值缺失（亏损期/序列未覆盖）当日不出信号。

口径（``cli.backtest.run`` 的 docstring 与本模块保持一致，改一处必须同步另一处）：

- 成交：信号在当根**收盘后**确定，**次日开盘**成交（T+1）；100 股整手，不足一手的
  现金留在账上；
- 费用：佣金 0.03%（最低 5 元），卖出另收印花税 0.05%；
- 不可成交：``volume == 0``（停牌占位）或一字板（``open == high == low == close``）
  → 顺延到下一根，顺延次数计入 ``caliber.skipped``；
- 期末仍有持仓按最后一根收盘平仓（``reason="期末平仓"``），保证每笔交易都有闭环。

SMA 为什么在本地算：平台没有「指标序列」接口（``fin.ta_*`` 只能在内核 eval 里对
数组调用），而 SMA 就是收盘价算术平均，与平台 ``$MA_CLOSE_N`` 同式，不存在口径分叉；
PE/PB 序列则直接取平台 ``HIST_STATS``，本地只做阈值判定。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

LOT_SIZE = 100
FEE_RATE = 0.0003
MIN_FEE = 5.0
STAMP_DUTY = 0.0005
TRADING_DAYS_PER_YEAR = 244
VALUATION_RULES = ("pe", "pb", "ps", "pr")
_EXCHANGE_TZ = timezone(timedelta(hours=8))   # 估值序列时间戳按交易所本地日归集


def _sma(values: list[float], n: int) -> list[float | None]:
    """收盘价 n 日算术平均；前 n-1 个点为 None（与平台 fin.ta_sma 一致）。"""
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def ma_cross_signals(bars: list[dict[str, Any]], fast: int = 5,
                     slow: int = 20) -> list[str | None]:
    """均线金叉/死叉信号（与 bars 等长）：``"buy"`` / ``"sell"`` / ``None``。"""
    if fast < 1 or slow < 2 or fast >= slow:
        raise ValueError(f"周期不合法：需要 1 ≤ fast < slow，收到 fast={fast}, slow={slow}")
    if len(bars) < slow + 2:
        raise ValueError(
            f"行情不足：{fast}/{slow} 均线回测至少需要 {slow + 2} 根日 K，收到 {len(bars)} 根"
            "（演示快照只有 120 根，长周期请用真实客户端取数）")
    closes = [float(b["close"]) for b in bars]
    fast_ma, slow_ma = _sma(closes, fast), _sma(closes, slow)
    signals: list[str | None] = [None] * len(bars)
    for i in range(slow, len(bars)):
        f, s = fast_ma[i], slow_ma[i]
        pf, ps = fast_ma[i - 1], slow_ma[i - 1]
        if f is None or s is None or pf is None or ps is None:
            continue
        if f > s and pf <= ps:
            signals[i] = "buy"
        elif f < s and pf >= ps:
            signals[i] = "sell"
    return signals


def valuation_by_date(series: Any) -> dict[str, float]:
    """估值序列 ``[[unix 秒, 值], ...]`` → ``{"YYYY-MM-DD": 值}``。

    时间戳按 +08:00 归到交易日（服务器返回的是交易所本地零点，不是 UTC 零点）；
    空值/坏点跳过。
    """
    out: dict[str, float] = {}
    for point in series or []:
        try:
            ts, value = point[0], point[1]
        except (TypeError, IndexError, KeyError):
            continue
        if value is None:
            continue
        try:
            day = datetime.fromtimestamp(float(ts), _EXCHANGE_TZ).date().isoformat()
            out[day] = float(value)
        except (TypeError, ValueError, OSError):
            continue
    return out


def valuation_signals(bars: list[dict[str, Any]], values: dict[str, float],
                      buy: float, sell: float) -> tuple[list[str | None], int]:
    """估值阈值信号（与 bars 等长）与估值缺失根数。

    ``values`` 是 ``{"YYYY-MM-DD": 估值}``；当天没有估值就不出信号（亏损期 PE 无数据）。
    """
    if not (0 < buy < sell):
        raise ValueError(f"估值阈值不合法：需要 0 < buy < sell，收到 buy={buy}, sell={sell}")
    signals: list[str | None] = [None] * len(bars)
    missing = 0
    for i, bar in enumerate(bars):
        value = values.get(str(bar.get("date") or "")[:10])
        if value is None:
            missing += 1
        elif value <= buy:
            signals[i] = "buy"
        elif value >= sell:
            signals[i] = "sell"
    return signals, missing


def _unfillable(bar: dict[str, Any]) -> bool:
    """停牌占位（零量）或一字板：当日无法按开盘价成交。"""
    if float(bar.get("open") or 0) <= 0 or float(bar.get("close") or 0) <= 0:
        return True
    if float(bar.get("volume") or 0) <= 0:
        return True
    o, h = float(bar["open"]), float(bar["high"])
    low, c = float(bar["low"]), float(bar["close"])
    return o == h == low == c


def _fee(amount: float, *, sell: bool) -> float:
    fee = max(amount * FEE_RATE, MIN_FEE)
    return fee + amount * STAMP_DUTY if sell else fee


def _buy_shares(cash: float, price: float) -> int:
    """按整手买入：优先算最大手数，再回退到「成本+佣金 ≤ 现金」。"""
    if price <= 0:
        return 0
    shares = int(cash // (price * LOT_SIZE)) * LOT_SIZE
    while shares > 0 and shares * price + _fee(shares * price, sell=False) > cash:
        shares -= LOT_SIZE
    return max(shares, 0)


def run_backtest(bars: list[dict[str, Any]], signals: list[str | None],
                 cash: float = 1_000_000.0, rule: str = "") -> dict[str, Any]:
    """按信号序列跑一次单股回测（撮合/费用/净值只此一条路径）。

    :param bars: 升序日 K（``date/open/high/low/close/volume``），来自 ``cli.kline.bars``
    :param signals: 与 ``bars`` 等长的信号序列（``"buy"`` / ``"sell"`` / ``None``）
    :param cash: 初始资金（元），默认 100 万——高价股一手就要十几万，现金不足一手买不进
    :param rule: 规则标签，原样回传到结果里
    """
    if cash <= 0:
        raise ValueError(f"cash 必须为正数，收到 {cash!r}")
    if not bars:
        raise ValueError("bars 为空")
    if len(signals) != len(bars):
        raise ValueError(f"信号长度 {len(signals)} 与行情根数 {len(bars)} 不一致")

    cash_now = float(cash)
    shares = 0
    entry: dict[str, Any] | None = None   # {index, price, cash_out}
    pending: str | None = None            # "buy" / "sell"
    skipped = 0
    starved = 0
    trades: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []

    for i, bar in enumerate(bars):
        day = str(bar.get("date") or "")

        # 1) 先执行上一根（或更早）的挂单：次日开盘成交，天然 T+1
        if pending == "buy" and shares == 0:
            if _unfillable(bar):
                skipped += 1
            else:
                price = float(bar["open"])
                qty = _buy_shares(cash_now, price)
                if qty <= 0:
                    starved += 1             # 现金不足一手：放弃本次买入
                    pending = None
                else:
                    amount = qty * price
                    fee = _fee(amount, sell=False)
                    cash_now -= amount + fee
                    shares = qty
                    entry = {"index": i, "price": price, "cash_out": amount + fee}
                    trades.append({"date": day, "side": "buy", "price": round(price, 4),
                                   "shares": qty, "amount": round(amount, 2),
                                   "fee": round(fee, 2),
                                   "reason": "金叉" if rule.startswith("ma") else "买点"})
                    pending = None
        elif pending == "sell" and shares > 0:
            if _unfillable(bar):
                skipped += 1
            else:
                price = float(bar["open"])
                amount = shares * price
                fee = _fee(amount, sell=True)
                cash_now += amount - fee
                trades.append(_sell_row(day, price, shares, amount, fee, entry, i,
                                        "死叉" if rule.startswith("ma") else "卖点"))
                shares, entry, pending = 0, None, None

        # 2) 收盘后判定信号，挂到下一根开盘（信号源不同，撮合规则相同）
        signal = signals[i]
        if signal == "buy":
            if shares == 0:
                pending = "buy"
        elif signal == "sell":
            if shares > 0:
                pending = "sell"
            elif pending == "buy":
                pending = None                    # 买点还没成交就转卖点：撤单

        # 3) 收盘价记净值
        equity.append({"date": day, "nav": round(cash_now + shares * float(bar["close"]), 2)})

    # 期末平仓（买入当天不卖，守住 T+1；最后一根一字板/停牌则挂不掉）
    if shares > 0 and entry is not None and entry["index"] < len(bars) - 1 \
            and not _unfillable(bars[-1]):
        last = bars[-1]
        price = float(last["close"])
        amount = shares * price
        fee = _fee(amount, sell=True)
        cash_now += amount - fee
        trades.append(_sell_row(str(last.get("date") or ""), price, shares, amount, fee,
                                entry, len(bars) - 1, "期末平仓"))
        equity[-1]["nav"] = round(cash_now, 2)
        shares, entry = 0, None
        pending = None

    summary = _summary(bars, equity, trades, cash)
    warnings: list[str] = []
    if starved:
        warnings.append(f"{starved} 次买点因现金不足一手未买入（cash={cash:,.0f} 元，"
                        "高价股一手可能十几万，可调大 cash）")
    if pending is not None:
        warnings.append(f"期末仍有未成交的{'买入' if pending == 'buy' else '卖出'}挂单，已忽略")
    if shares > 0:
        warnings.append("期末持仓未平仓（最后一根买不进/卖不出，或最后一天才买入受 T+1 限制）："
                        "净值已含持仓市值，成交明细无对应卖出行")
    return {
        "rule": rule,
        "period": {"start": str(bars[0].get("date") or ""),
                   "end": str(bars[-1].get("date") or ""), "bars": len(bars)},
        "trades": trades,
        "summary": summary,
        "equity": equity,
        "caliber": {"execution": "next_open", "t_plus_1": True, "lot_size": LOT_SIZE,
                    "fee_rate": FEE_RATE, "min_fee": MIN_FEE, "stamp_duty": STAMP_DUTY,
                    "skipped": skipped},
        "warnings": warnings,
    }


def _sell_row(day: str, price: float, shares: int, amount: float, fee: float,
              entry: dict[str, Any] | None, index: int, reason: str) -> dict[str, Any]:
    """卖出成交行：带本轮已实现盈亏与持有交易日数。"""
    cost = float(entry["cash_out"]) if entry else 0.0
    pnl = amount - fee - cost
    return {"date": day, "side": "sell", "price": round(price, 4), "shares": shares,
            "amount": round(amount, 2), "fee": round(fee, 2), "pnl": round(pnl, 2),
            "ret": round(pnl / cost, 6) if cost > 0 else None,
            "hold_days": index - int(entry["index"]) if entry else None,
            "reason": reason}


def _summary(bars: list[dict[str, Any]], equity: list[dict[str, Any]],
             trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    navs = [float(row["nav"]) for row in equity]
    closed = [t for t in trades if t["side"] == "sell"]
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]

    total_return = navs[-1] / cash - 1 if navs and cash > 0 else None
    days = _calendar_days(str(bars[0].get("date") or ""), str(bars[-1].get("date") or ""))
    cagr = ((navs[-1] / cash) ** (365.0 / days) - 1) if days and days > 0 and navs else None

    peak, mdd = navs[0] if navs else 0.0, 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0:
            mdd = min(mdd, nav / peak - 1)

    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)) if navs[i - 1] > 0]
    sharpe = None
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        if std > 0:
            sharpe = mean / std * math.sqrt(TRADING_DAYS_PER_YEAR)

    closes = [float(b["close"]) for b in bars]
    holds = [t["hold_days"] for t in closed if t.get("hold_days") is not None]
    return {
        "total_return": _round(total_return),
        "cagr": _round(cagr),
        "max_drawdown": _round(mdd),
        "sharpe": _round(sharpe),
        "n_trades": len(closed),
        "win_rate": _round(len(wins) / len(closed)) if closed else None,
        "avg_hold_days": _round(sum(holds) / len(holds)) if holds else None,
        "buy_hold_return": _round(closes[-1] / closes[0] - 1) if closes and closes[0] > 0 else None,
    }


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _calendar_days(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return None
