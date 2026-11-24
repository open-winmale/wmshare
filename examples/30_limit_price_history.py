"""历史涨跌停价：cli.stocks.limit_price_history（3.4 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/30_limit_price_history.py
学到：逐日规则价；basis 是交易所除权参考前收（用 hfq/nr 因子还原，除权日
      不能用原始前收）；主板 ST 5%（2026-05-06 前）/10%（之后）、创业板
      2020-08-24 前 10% 后 20%；rule=ipo/unbounded/no_price 时价格为空，
      不要当 0
文档：docs/API.md「证券与行业基础」章 · estimate_cost('stocks.limit_price_history')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（不复权+后复权两档 + 简称史；n 越小越省） ==")
    est = cli.cost_estimate("stocks.limit_price_history", n=60)
    lo, hi = est["ec_lo"], est["ec_hi"]
    if lo is None:
        print("  无成本模型（如实返回 None）")
    else:
        print(f"  n=60：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 600519 最近 60 个交易日：逐日规则价（元） ==")
    df = cli.stocks.limit_price_history("600519", n=60)
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    for r in rows[-5:]:
        print(f"  {r['date']} 收={r['close']} 前收={r['basis']} "
              f"涨停={r['limit_up']} 跌停={r['limit_down']} rule={r['rule']}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["rule"]] = counts.get(r["rule"], 0) + 1
    print("  rule 分布：" + "、".join(f"{k}={v}" for k, v in sorted(counts.items())))
    up = [r for r in rows if r["limit_up"] is not None and r["close"] == r["limit_up"]]
    down = [r for r in rows if r["limit_down"] is not None and r["close"] == r["limit_down"]]
    print(f"  封板：涨停 {len(up)} 日 · 跌停 {len(down)} 日")

    print("== 3. 历史 ST：*ST天龙 2003-05（主板 ST 5%，不是 10%） ==")
    st = cli.stocks.limit_price_history("600234", begin="2003-05-12", end="2003-05-16")
    for r in st.to_dict("records"):
        print(f"  {r['date']} {r['name']} 收={r['close']} 前收={r['basis']} "
              f"涨停={r['limit_up']} 跌停={r['limit_down']} "
              f"band={r['band']} rule={r['rule']}")

    print("== 4. 创业板改革：2020-08-24 起 10% → 20% ==")
    gem = cli.stocks.limit_price_history("300750", begin="2020-08-21",
                                         end="2020-08-24")
    for r in gem.to_dict("records"):
        print(f"  {r['date']} 前收={r['basis']} 涨停={r['limit_up']} "
              f"跌停={r['limit_down']} band={r['band']} rule={r['rule']}")

    print("== 5. 自检：ipo/unbounded/no_price 时价格为空（不猜） ==")
    for r in rows:
        if r["rule"] in {"ipo", "unbounded", "no_price"}:
            print(f"  {r['date']} rule={r['rule']} 涨停={r['limit_up']}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
