"""板块资金流：cli.board.moneyflow / moneyflow_last（2026-11 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/26_board_moneyflow.py
学到：三源（ths 概念/行业、dc 概念+行业）各成一套板块体系，不做跨源映射；
      额统一为元（ths 原值亿元已换算）、比率统一为小数、板块指数是点位；
      榜单按主力净额降序，缺字段为空（ths 无四档单量、dc 无买卖总额）
文档：docs/GUIDE.md「行情」节 · API.md「板块资金流」章 · estimate_cost('board.moneyflow_last')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（单日一档 ≤1,081 行，按最新日期版本键缓存） ==")
    for name in ("board.moneyflow_last", "board.moneyflow"):
        est = cli.cost_estimate(name, limit=20)
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 三源最新交易日：主力净流入 Top 3（元） ==")
    latest_date = ""
    for src in ("ths_concept", "ths_industry", "dc"):
        df = cli.board.moneyflow_last(src, 3)
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
        if not rows:
            print(f"  {src}: 无数据")
            continue
        latest_date = rows[0]["date"]
        for r in rows:
            net = r["net_amount"]
            net_yi = "—" if net is None else f"{net / 1e8:.2f} 亿元"
            pct = r["pct_change"]
            pct_txt = "—" if pct is None else f"{pct * 100:+.2f}%"
            print(f"  {src:12s} {r['name'][:10]:10s} 净流入 {net_yi:>10s} 涨跌 {pct_txt}")

    print("== 3. 指定交易日回查：与最新榜单逐行一致（同排序） ==")
    if latest_date:
        top_last = cli.board.moneyflow_last("ths_concept", 5)
        top_day = cli.board.moneyflow("ths_concept", latest_date, 5)
        a = top_last.to_dict("records") if hasattr(top_last, "to_dict") else list(top_last)
        b = top_day.to_dict("records") if hasattr(top_day, "to_dict") else list(top_day)
        same = [x["code"] for x in a] == [x["code"] for x in b]
        print(f"  {latest_date} 前 5 板块与最新榜单一致：{same}")

    print("== 4. 字段边界：ths 有买卖总额，dc 有四档单量（缺失为空） ==")
    ths = cli.board.moneyflow_last("ths_concept", 1)
    dc = cli.board.moneyflow_last("dc", 1)
    for name, df in (("ths_concept", ths), ("dc", dc)):
        rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
        if rows:
            r = rows[0]
            print(f"  {name}: net_buy={r['net_buy']} buy_elg={r['buy_elg']} "
                  f"content_type={r['content_type']!r}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
