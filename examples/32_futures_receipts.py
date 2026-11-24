"""交易所仓单快照：cli.futures.receipts（3.6 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/32_futures_receipts.py
学到：仓单=交易所注册仓单量（吨/张逐行，看 unit 字段），不是成交量/持仓量；
      覆盖 SHFE/CZCE/GFEX 三所，DCE 反爬未采；**按月口径**——上游按月 REPLACE，
      只保留当月最后一天快照，不是逐日历史（逐日序列要等上游改按日分档）
文档：docs/API.md「期货」章 · estimate_cost('futures.receipts')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（按月单 doc 点查，月键 memo 命中后近乎免费） ==")
    est = cli.cost_estimate("futures.receipts")
    if est["ec_lo"] is None:
        print(f"  无成本模型（如实返回 None）：{est['note']}")
    else:
        print(f"  {est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）· {est['note']}")

    print("== 2. 最新月快照：仓单量最大的 8 个品种 ==")
    df = cli.futures.receipts()
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        print("  该月无数据（上游按月 REPLACE，可能是月初未抓取）")
        return
    top = sorted(rows, key=lambda r: -abs(float(r["qty"] or 0)))[:8]
    for r in top:
        print(f"  {r['period']}  {r['exchange']:5s} {r['variety_name']}: "
              f"{r['qty']:,.0f} {r['unit']}（较上日 {r['change']:+,.0f}）")

    print("== 3. 按交易所聚合：三所覆盖与仓单总量 ==")
    agg: dict[str, list[float]] = {}
    for r in rows:
        agg.setdefault(str(r["exchange"]), []).append(float(r["qty"] or 0))
    for ex, vals in sorted(agg.items()):
        print(f"  {ex}: {len(vals)} 个品种，合计 {sum(vals):,.0f}")

    print("== 4. 自检：单位字段齐全、title 去重键唯一 ==")
    assert all(r["unit"] for r in rows), "每行都应有 unit（吨/张）"
    titles = [r["title"] for r in rows]
    assert len(titles) == len(set(titles)), "title 应唯一（{exchange}.{code} 去重键）"
    print(f"  共 {len(rows)} 行，{len(agg)} 个交易所，自检通过")

    print("== 5. 口径提醒 ==")
    print("  这是「当月最后一次抓取那天」的快照；要逐日序列需上游改按日分档（尚未提供）")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
