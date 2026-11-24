"""期货持仓排名与结算参数：cli.futures.holding / settle（3.6 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/33_futures_holding.py
学到：持仓排名=期货公司会员的成交量/多空持仓（手/张，上游原值），按合约查才有
      排名；结算参数含结算价/手续费/保证金率，费率口径不统一（fee_rate 是 ‰，
      保证金率多为小数，settle 价格单位随合约），SDK 不做换算
文档：docs/API.md「期货」章 · estimate_cost('futures.holding' / 'futures.settle')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（给合约=先过滤再规范化；不给合约=按上游顺序截 limit） ==")
    est = cli.cost_estimate("futures.holding", contract="A2701", limit=20)
    if est["ec_lo"] is None:
        print(f"  无成本模型（如实返回 None）：{est['note']}")
    else:
        print(f"  {est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）· {est['note']}")

    print("== 2. 单合约持仓排名（按成交量降序，limit=10） ==")
    df = cli.futures.holding(contract="A2701", limit=10)
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        print("  该合约最新交易日无数据（可能已换月/非交易日），换一个合约再试")
    else:
        for r in rows[:5]:
            print(f"  {r['date']}  {r['contract']}  {r['broker']}: "
                  f"成交 {float(r['vol']):,.0f} 手，多单 {float(r['long_hld']):,.0f}，"
                  f"空单 {float(r['short_hld']):,.0f}")

    print("== 3. 品种结算参数（CU 前缀，展示前 5 个合约） ==")
    sdf = cli.futures.settle(contract="CU")
    srows = sdf.to_dict("records") if hasattr(sdf, "to_dict") else list(sdf)
    if not srows:
        print("  当日无结算参数（非交易日/上游未更新）")
        return
    for r in srows[:5]:
        print(f"  {r['date']}  {r['contract']}: 结算价 {float(r['settle']):,.1f}，"
              f"多头保证金率 {float(r['long_margin_rate'])}，手续费率 {float(r['fee_rate'])}")

    print("== 4. 自检：排名按成交量降序；结算合约前缀一致 ==")
    if len(rows) > 1:
        vols = [float(r["vol"]) for r in rows]
        assert vols == sorted(vols, reverse=True), "持仓排名应按成交量降序"
    assert all(str(r["contract"]).startswith("CU") for r in srows), "settle 前缀过滤应生效"
    print(f"  持仓 {len(rows)} 行、结算 {len(srows)} 行，自检通过")

    print("== 5. 口径提醒 ==")
    print("  量=手/张（随交易所惯例）；fee_rate 为 ‰ 原值，保证金率多为小数（0.11=11%），"
          "个别品种上游给 50；settle 价格单位随合约，跨品种比较前先看合约单位")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
