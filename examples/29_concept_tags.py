"""概念标签：cli.board.concepts_of / concept_members / concept_list（2026-11 新面）。

前提：凭证可选——无凭证自动回落匿名试用（免注册、真实数据、需网络）
运行：python examples/29_concept_tags.py
学到：概念标签是全市场索引里的物化数组（$CONCEPT_TAGS），读面去 "s:" 前缀；
      概念名含指数/风格标签（HS300_/MSCI中国/融资融券），不做概念/风格分流；
      concept_members 是名称包含匹配（"白酒" 命中多个标签），按代码升序；
      当前截面无 PIT 历史——历史成份不可得，不要用它回测历史选股
文档：docs/GUIDE.md「行情」节 · API.md「板块」章 · estimate_cost('board.concept_members')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（索引全表扫描类接口冷态较贵，当日复跑走 memo） ==")
    for name, kw in (("board.concepts_of", {"symbol": "600519"}),
                     ("board.concept_members", {"name": "白酒", "limit": 10})):
        est = cli.cost_estimate(name, **kw)
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 单票概念标签 ==")
    info = cli.board.concepts_of("600519")
    if info is None:
        print("  未收录（索引未物化）")
    else:
        tags = info.get("tags") or []
        print(f"  {info.get('name')}：{len(tags)} 个标签")
        print("  " + "、".join(tags[:12]) + ("…" if len(tags) > 12 else ""))

    print("== 3. 概念成份（白酒，前 10 只） ==")
    members = cli.board.concept_members("白酒", 10)
    rows = members.to_dict("records") if hasattr(members, "to_dict") else list(members)
    for r in rows:
        pct = float(r.get("percent") or 0) * 100
        print(f"  {r['symbol']} {r['name']}  {r.get('close')} 元  {pct:+.2f}%")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
