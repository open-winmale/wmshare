"""财报附注与会计政策：cli.statements.notes / notes_index / policies（4.4 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络；仅 A 股）
运行：python examples/34_financial_notes_policy.py
学到：附注按「科目 × 报告期」点查（code 认目录码也认中文名，found=false =
      未入库、覆盖以返回为准勿外推）；notes_index 先探覆盖再查明细；会计
      政策卡当期含 quote 原文、hist 不含 quote（车道按期解析，可安全跨期 diff）
文档：docs/API.md「财务基本面」章 · examples/README.md 课程表
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()
    symbol = "600519"

    print("== 1. 附注覆盖角标：该司哪些科目哪些期有货（code/cn/period） ==")
    idx = cli.statements.notes_index(symbol)
    rows = idx.to_dict("records") if hasattr(idx, "to_dict") else list(idx)
    if not rows:
        print("  空角标 = 该司尚未入附注库")
        return
    for r in rows[:5]:
        print(f"  {r['code']}  {r['cn']}  {r['period']}")

    print("== 2. 附注明细：目录码 + 中文名两路（单段卡片=一张披露表） ==")
    for key in ("IO", "货币资金"):
        card = cli.statements.notes(symbol, key)
        if not card.get("found"):
            print(f"  {key}: found=false（该科目该期未入附注库，勿外推）")
            continue
        print(f"  {key} → {card['cn']} @ {card['period']}"
              f"（车道 {card['source']}，{len(card['sections'])} 段）")
        sec = card["sections"][0]
        print(f"    首段《{sec['title']}》：{len(sec['rows'])} 行 × "
              f"{len(sec['columns'])} 列（page {sec.get('page', '')}，"
              f"{sec.get('unit_note', '')}）")

    print("== 3. 会计政策卡：当期含 quote 原文，hist 不含（跨期 diff 底稿） ==")
    doc = cli.statements.policies(symbol, hist_years=2)
    head = " → ".join(doc["periods"][:3])
    print(f"  年报期：{head}（当期 {doc['period']}）")
    for c in doc["cards"][:3]:
        quote = c.get("quote", "")
        print(f"  [{c['policy_id']}] {c['asset_class']}"
              f"（{c['scope']}，P{c['page_start']}-{c['page_end']}）")
        if quote:
            print(f"    原文：{quote[:40]}……")
    print(f"  hist {len(doc['hist'])} 张（不含 quote；车道已按期解析，"
          f"两线卡不混，diff 不出假变更）")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
