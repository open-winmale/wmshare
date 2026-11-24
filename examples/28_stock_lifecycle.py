"""ST/停复牌史：cli.stocks.lifecycle / suspend_history / name_history（2026-11 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/28_stock_lifecycle.py
学到：停复牌按交易日（S=停牌 / R=复牌）、简称变更按生效日，两源日期口径不同；
      lifecycle 由两者合并派生（rename/st_enter/st_exit/suspend/resume），
      ST 判定 = 简称含 ST（覆盖 ST/*ST/SST）；时间轴不含上市/退市事件
文档：docs/GUIDE.md「行情」节 · API.md「证券与行业基础」章 ·
      estimate_cost('stocks.lifecycle')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（单票点查，按票计费） ==")
    for name in ("stocks.suspend_history", "stocks.name_history",
                 "stocks.lifecycle"):
        est = cli.cost_estimate(name, symbol="000001")
        lo, hi = est["ec_lo"], est["ec_hi"]
        if lo is None:
            print(f"  {name}：无成本模型（如实返回 None，实测后回填）")
        else:
            print(f"  {name}：{lo}~{hi} EC（{est['model']}）")

    print("== 2. 简称变更史（含 ST 段标记） ==")
    names = cli.stocks.name_history("000001")
    name_rows = names.to_dict("records") if hasattr(names, "to_dict") else list(names)
    if not name_rows:
        print("  暂无数据（采集上线后回补即出）")
    for r in name_rows:
        flag = "ST" if r.get("is_st") else "  "
        print(f"  [{flag}] {r['start_date']} ~ {r.get('end_date') or '至今'}  "
              f"{r['name']}（{r.get('reason') or '-'}）")

    print("== 3. 停复牌事件（区间内，时间升序） ==")
    susp = cli.stocks.suspend_history("600519", "2010-01-01", "2026-11-23")
    susp_rows = susp.to_dict("records") if hasattr(susp, "to_dict") else list(susp)
    if not susp_rows:
        print("  区间内无停复牌事件")
    for r in susp_rows[:10]:
        label = "停牌" if r["type"] == "S" else "复牌"
        print(f"  {r['date']} {label} {r.get('timing') or ''}")

    print("== 4. 合并时间轴（前 10 条） ==")
    lc = cli.stocks.lifecycle("600519")
    events = lc.to_dict("records") if hasattr(lc, "to_dict") else list(lc)
    for r in events[:10]:
        print(f"  {r['date']} {r['kind']:<9} {r['detail']}")

    print("== 5. 自检：时间轴严格日期升序 ==")
    dates = [str(r["date"]) for r in events]
    print(f"  {len(dates)} 条事件 · 升序={dates == sorted(dates)}")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
