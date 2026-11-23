"""期货主力连续历史K线：cli.futures.bars（2026-11 新面）。

前提：需真实凭证（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo`
      模式下历史序列未回放（点读面按点×码计费），显式降级不伪造数据
运行：python examples/22_futures_bars.py [--demo]
学到：futures.bars 与 kline.bars 同形（date 升序/DF 默认）、freq 三档的点数
      经济学（长区间用 m 省 20 倍）、begin/end 与 n 二选一、成本预估先行
文档：docs/GUIDE.md「宏观与期货」节 · API.md「期货」章 · estimate_cost('futures.bars')
"""

from __future__ import annotations

import sys
from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None, demo: bool = False) -> None:
    if cli is None:
        cli = wmshare.demo_client() if demo else wmshare.Client.from_env()
    if demo:
        print("演示模式：固定快照回放，非实时数据（期货历史序列未回放，"
              "显式降级不伪造数据）")

    print("== 1. 先估成本再取数（点×码线性，暖态 ≈8-11 EC/点·码） ==")
    est = cli.cost_estimate("futures.bars", n=12)
    print(f"  月频 n=12 预估：{est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）")

    print("== 2. 沪铝主力 月K 近 6 个月（date=周期起点，升序） ==")
    try:
        df = cli.futures.bars("AL.SHF", n=6, freq="m")
    except wmshare.errors.WmshareError as e:
        if getattr(e, "code", "") == "demo_unsupported":
            print("  demo 未回放期货历史序列——真实取数请去掉 --demo（需凭证）")
            return
        raise
    print(df[["date", "close", "settle", "volume"]].to_string(index=False))
    print("  单位：close/settle=元（期货原生口径）、volume=手（一手=合约乘数）")

    print("== 3. 日频区间：begin/end 成对（客户端收口，含端点） ==")
    df2 = cli.futures.bars("AL.SHF", begin="2026-11-01", end="2026-11-20")
    print(f"  2026-11-01 ~ 2026-11-20 共 {len(df2)} 个交易日；"
          f"末收 {df2['close'].iloc[-1]:.0f} 元")

    print("== 4. 纪律：长区间用月频（点数省 20 倍） ==")
    est_m = cli.cost_estimate("futures.bars", n=300)
    print(f"  25 年月频 300 点 ≈{est_m['ec_lo']}~{est_m['ec_hi']} EC；"
          "同跨度日频需 6000 点，超硬顶（d 3000）会被拒")


if __name__ == "__main__":
    try:
        main(demo="--demo" in sys.argv)
    except WmshareError as e:
        print(f"[{e.code}] {e}", file=sys.stderr)
        sys.exit(1)
