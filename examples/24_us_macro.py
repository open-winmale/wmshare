"""美国宏观序列：cli.us_macro（2026-11 新面，精选 88 条 × 11 主题）。

前提：凭证可选——无凭证自动回落匿名试用（免注册、真实数据、需网络）
运行：python examples/24_us_macro.py
学到：单位随序列而变（百分数/十亿美元/千人）必须读 series_meta().units 再解读；
      点序列 date 升序（旧→新）、空值跳过不补 0；需授权序列 has_data=False 永不抓取
文档：docs/GUIDE.md「汇率、官方储备与美国宏观」节 · API.md「宏观」章 · estimate_cost('fred.points_asc')
"""

from __future__ import annotations

import sys
from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（主题树/检索是静态包，零 store 取数） ==")
    for name in ("fred.topics", "fred.search", "fred.points_asc"):
        est = cli.cost_estimate(name, **({"limit": 20} if name.endswith("asc") else {}))
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 主题树：11 主题 × 88 条精选序列（零取数成本） ==")
    topics = cli.us_macro.topics()
    try:
        total = sum(len(list(s)) for s in topics["series"])
        print(f"  共 {len(topics)} 个主题、{total} 条序列")
        for row in topics.to_dict("records")[:3]:
            print(f"  {row['topic']:12s} {row['name']}：{len(list(row['series']))} 条")
    except (AttributeError, KeyError, TypeError):
        print(f"  共 {len(topics)} 个主题")

    print("== 3. 中文检索（不必先知道英文 id） ==")
    hits = cli.us_macro.search("通胀", 5)
    try:
        for row in hits.to_dict("records"):
            print(f"  {row['id']:12s} {row['title_zh']}")
    except (AttributeError, KeyError, TypeError):
        print(hits)

    print("== 4. 元信息：单位必须读，否则量级必错 ==")
    for sid in ("GDP", "UNRATE", "PAYEMS"):
        meta = cli.us_macro.series_meta(sid)
        if meta:
            print(f"  {sid:8s} units={meta['units']:22s} freq={meta['frequency_short']} "
                  f"has_data={meta['has_data']}")

    print("== 5. 点序列：date 升序（旧→新），量级随单位而变 ==")
    for sid, lo, hi in (("GDP", 1e3, 1e5), ("UNRATE", 0.0, 30.0)):
        pts = cli.us_macro.points(sid, limit=12)
        if not len(pts):
            print(f"  {sid}：无数据")
            continue
        dates = list(pts["date"])
        vals = list(pts["value"])
        last = float(vals[-1])
        flag = "✓" if lo <= last <= hi else "✗ 量级异常"
        print(f"  {sid}: {dates[0]} → {dates[-1]} 末值={last:.4g} {flag}")
        print(f"    升序检查：{'✓ date 升序' if dates == sorted(dates) else '✗ 非升序'}")

    print("== 6. 需授权序列：has_data=False，永不抓取（版权硬停） ==")
    locked = cli.us_macro.series_meta("CSUSHPINSA")
    if locked:
        print(f"  CSUSHPINSA: status={locked['status']} has_data={locked['has_data']}")
        if locked.get("hint"):
            print(f"  说明：{locked['hint']}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as e:  # 凭证/额度/网络等统一异常
        print(f"运行失败：{e}", file=sys.stderr)
        raise SystemExit(1) from e
