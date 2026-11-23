"""每日涨跌停价：cli.stocks.limit_price / limit_prices（2026-11 新面）。

前提：凭证可选——无凭证自动回落匿名试用（免注册、真实数据、需网络）
运行：python examples/25_limit_price.py
学到：涨跌停价是「前收盘 × (1±带宽)」的规则价（四舍五入到分），带宽只看代码
      号段（30x/68x=20%、北交所=30%、其余=10%）；rule=unbounded/delisting 时
      价格为空（新股无涨跌幅日/退市整理期），不要当 0
文档：docs/GUIDE.md「行情」节 · API.md「证券与行业基础」章 · estimate_cost('stocks.limit_prices')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（全市场索引一次投影，按自然日缓存） ==")
    for name in ("stocks.limit_prices", "stocks.limit_price"):
        est = cli.cost_estimate(name)
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 单票：前收盘/涨停价/跌停价（元，两位小数） ==")
    row = cli.stocks.limit_price("600519")
    if row:
        print(f"  {row['symbol']} {row['name']} 板块={row['board']} "
              f"收盘={row['close']} 前收={row['basis']} "
              f"涨停={row['limit_up']} 跌停={row['limit_down']} rule={row['rule']}")

    print("== 3. 全市场快照：按规则分组（停牌股不返回） ==")
    df = cli.stocks.limit_prices()
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["rule"]] = counts.get(r["rule"], 0) + 1
    for rule in sorted(counts):
        print(f"  {rule:10s} {counts[rule]:5d} 只")

    print("== 4. 当日封板：收盘价等于涨停/跌停价（规则价精确到分） ==")
    up = [r for r in rows if r["limit_up"] is not None and r["close"] == r["limit_up"]]
    down = [r for r in rows if r["limit_down"] is not None and r["close"] == r["limit_down"]]
    print(f"  涨停 {len(up)} 只 · 跌停 {len(down)} 只")
    for r in up[:5]:
        print(f"  涨停 {r['symbol']} {r['name']} {r['close']}（{r['percent'] * 100:.2f}%）")

    print("== 5. 自检：越界不猜（rule 非正常档时价格应为空） ==")
    for r in rows:
        if r["rule"] in {"unbounded", "delisting", "no_price"}:
            print(f"  {r['symbol']} {r['name']} rule={r['rule']} 价格={r['limit_up']}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
