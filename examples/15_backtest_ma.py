"""单股回测：均线金叉买、死叉卖，看逐笔成交明细与净值汇总。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据（120 根，非实时）
运行：python examples/15_backtest_ma.py
学到：backtest.run 一条调用出成交明细；口径固定（次日开盘、T+1、整手、佣金/印花）
文档：docs/GUIDE.md（单票菜谱·单股回测）
"""
import sys

import wmshare
from wmshare import WmshareError

SYMBOL = "600519"        # 换成你的标的
FAST, SLOW = 5, 20


def _pct(value, sign="+"):
    return "—" if value is None else f"{value:{sign}.2%}"


def main(cli=None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            # 回测要取全历史日 K：默认 max_limit=500 根不够长区间
            cli = wmshare.Client.from_env(max_limit=None)
    try:
        res = cli.backtest.run(SYMBOL, fast=FAST, slow=SLOW)
    except WmshareError as e:
        print(f"回测跳过：code={e.code} {e}")
        return

    period = res["period"]
    print(f"{res['symbol']}  {res['rule']}  "
          f"{period['start']} → {period['end']}（{period['bars']} 根）")

    print("\n--- 成交明细（每笔买/卖；卖出带本轮盈亏）---")
    for t in res["trades"][:8]:
        tail = "" if t["side"] == "buy" else (
            f"  pnl={t['pnl']:+.2f} ret={_pct(t['ret'])} 持有 {t['hold_days']} 日")
        print(f"  {t['date']}  {t['side']:<4} {t['price']:>9.2f} × {t['shares']:>5}"
              f"  fee={t['fee']:>8.2f}  {t['reason']}{tail}")

    s = res["summary"]
    print("\n--- 汇总 ---")
    print(f"  收益 {_pct(s['total_return'])}  年化 {_pct(s['cagr'])}  "
          f"最大回撤 {_pct(s['max_drawdown'], '')}  夏普 {s['sharpe']}")
    print(f"  交易 {s['n_trades']} 笔  胜率 {_pct(s['win_rate'], '')}  "
          f"平均持有 {s['avg_hold_days']} 交易日  买入持有 {_pct(s['buy_hold_return'])}")
    print(f"  口径：{res['caliber']}")
    for warning in res["warnings"]:
        print(f"  提示：{warning}")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
