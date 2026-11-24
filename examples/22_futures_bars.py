"""期货主力连续历史K线：cli.futures.bars（store 直读）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/22_futures_bars.py
学到：futures.bars 与 kline.bars 同形（date=周期起点、升序、DF 默认）；日频只含
      交易日、n=根数；周/月线是上游周期 bar（成交量=周期合计）；begin/end 与 n
      二选一（含端点）；成本按行计费、先估后取
文档：docs/GUIDE.md「宏观与期货」节 · API.md「期货」章 · estimate_cost('futures.bars')
"""

from __future__ import annotations

import sys
from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本再取数（store 直读按行计费：冷 ≈190+126×行） ==")
    est = cli.cost_estimate("futures.bars", n=12)
    print(f"  n=12 预估：{est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）；"
          "同日复跑命中版本键缓存 ≈135 EC")

    print("== 2. 沪铝主力 月K 近 6 个月（date=每月 1 日，升序） ==")
    df = cli.futures.bars("AL.SHF", n=6, freq="m")
    print(df[["date", "close", "settle", "volume"]].to_string(index=False))
    print("  单位：close/settle=元（期货原生口径）、volume=手（周期合计）")

    print("== 3. 日频区间：begin/end 成对（含端点，只含交易日） ==")
    df2 = cli.futures.bars("AL.SHF", begin="2026-11-01", end="2026-11-20")
    print(f"  2026-11-01 ~ 2026-11-20 共 {len(df2)} 个交易日；"
          f"末收 {df2['close'].iloc[-1]:.0f} 元")

    print("== 4. 纪律：长区间用月频（行数省 20 倍） ==")
    est_m = cli.cost_estimate("futures.bars", n=300, freq="m")
    print(f"  约 25 年月频 300 行 ≈{est_m['ec_lo']}~{est_m['ec_hi']} EC；"
          "同跨度日频约 6000 行，超硬顶（d 3000）会被拒")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as e:
        print(f"[{e.code}] {e}", file=sys.stderr)
        sys.exit(1)
