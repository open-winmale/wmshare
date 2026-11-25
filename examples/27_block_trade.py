"""大宗交易：cli.blocktrade.by_date / by_symbol（2026-11 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/27_block_trade.py
学到：大宗行只带证券代码（无简称），要名称需 join stocks/info；额=元、量=股、
      价=元（上游万元/万股已换算）；单日榜按成交额降序，单票历史 date 升序；
      同一天同票可有多笔（不同价格/买卖方），各占一行
文档：docs/GUIDE.md「行情」节 · API.md「大宗交易」章 · estimate_cost('blocktrade.by_date')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（单日一档全市场明细，按行数线性） ==")
    for name in ("blocktrade.by_date", "blocktrade.by_symbol"):
        est = cli.cost_estimate(name, limit=50)
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 单票大宗历史（最近 5 笔，amount 元→亿元展示） ==")
    hist = cli.blocktrade.by_symbol("000001", 5)
    rows = hist.to_dict("records") if hasattr(hist, "to_dict") else list(hist)
    if not rows:
        print("  暂无数据（采集上线后回补即出）")
    for r in rows:
        print(f"  {r['date']} 价 {r['price']} 元 量 {r['volume']} 股 "
              f"额 {r['amount'] / 1e8:.2f} 亿元 买方={r['buyer']}")

    print("== 3. 某交易日全市场前 5（成交额降序） ==")
    day = cli.blocktrade.by_date("2026-11-20", 5)
    day_rows = day.to_dict("records") if hasattr(day, "to_dict") else list(day)
    if not day_rows:
        print("  该日暂无数据（回补后可用）")
    for r in day_rows:
        print(f"  {r['symbol']} 额 {r['amount'] / 1e8:.2f} 亿元 "
              f"价 {r['price']} 量 {r['volume']}")

    print("== 4. 自检：成交额 ≈ 价 × 量（万元/万股同时换算后仍成立） ==")
    for r in day_rows:
        implied = r["price"] * r["volume"]
        diff = abs(r["amount"] - implied) / max(implied, 1)
        print(f"  {r['symbol']} amount={r['amount']:.0f} vs price×vol={implied:.0f} "
              f"（偏差 {diff * 100:.4f}%）")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
