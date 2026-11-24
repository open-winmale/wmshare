"""外汇与官方储备：cli.fx / cli.macro.reserves（2026-11 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/23_fx_reserves.py
学到：人民币中间价「每 1 单位外币」口径（上游原始是每 100 外币，SDK 已 /100 归一）、
      中间价 vs 中行牌价的区别、储备值是美元数值（非亿元/非亿美元）且黄金是市值口径
文档：docs/GUIDE.md「外汇与官方储备」节 · API.md「宏观」章 · estimate_cost('fx.history')
"""

from __future__ import annotations

import sys
from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（store 直读，成本随根数线性、无逐行规范化放大） ==")
    est = cli.cost_estimate("fx.history", n=30)
    print(f"  日线 n=30 预估：{est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）")

    print("== 2. 美元中间价最新值（每 1 单位外币折人民币，约 7.1） ==")
    snap = cli.fx.rate("USD")
    if snap:
        print(f"  {snap['date']}  中间价={snap['middle']}  汇买价={snap['buy']}")
        print(f"  自查：数值应在 6~8 区间；若看到 600+ 说明读的是未归一的每 100 外币原值")
    else:
        print("  无数据（币种不在库）")

    print("== 3. 多币种横向对比（日元/港币量级差异很大，正是归一的意义） ==")
    for ccy in ("USD", "EUR", "JPY", "HKD"):
        r = cli.fx.rate(ccy)
        if r:
            print(f"  {ccy}: {r['middle']:.6g} @ {r['date']}")

    print("== 4. 在库币种清单（哪些币种有数据） ==")
    df = cli.fx.list()
    try:
        print(f"  共 {len(df)} 个币种")
        print(df.head(8).to_string(index=False))
    except AttributeError:
        print(f"  共 {len(df)} 个币种")

    print("== 5. 美元中间价近 10 个交易日（date 升序，旧→新） ==")
    hist = cli.fx.history("USD", n=10)
    try:
        print(hist.to_string(index=False))
        last = float(hist["middle"].iloc[-1])
    except (AttributeError, IndexError, KeyError, TypeError):
        last = None
    if last is not None:
        print(f"  最新中间价 {last}（若有 600+ 量级说明口径未归一）")

    print("== 6. 官方储备：清单 + 时序（值=美元数值，黄金是市值口径非吨数） ==")
    items = cli.macro.reserves()
    try:
        print(items.to_string(index=False))
    except AttributeError:
        print(items)

    fx_df = cli.macro.reserves_history("forex", n=6)
    try:
        print("\n  外汇储备近 6 期（单位：美元；除以 1e12 得万亿美元）：")
        print(fx_df.to_string(index=False))
        latest = float(fx_df["value"].iloc[-1]) / 1e12
        print(f"  最新 ≈ {latest:.3f} 万亿美元")
    except (AttributeError, IndexError, KeyError, TypeError, ZeroDivisionError):
        print(fx_df)

    gold = cli.macro.reserves_asof("gold")
    if gold:
        print(f"\n  黄金储备最新：{gold['date']} {gold['value'] / 1e8:.0f} 亿美元（市值口径）")
    sdr = cli.macro.reserves_asof("sdr")
    print(f"  SDR：{'无数据（上游无生产者，清单里 available=False）' if sdr is None else sdr}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as e:  # 凭证/额度/网络等统一异常
        print(f"运行失败：{e}", file=sys.stderr)
        raise SystemExit(1) from e
