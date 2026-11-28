"""股东增减持：cli.holdertrade.by_date / by_symbol（2026-11 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/35_holder_trade.py
学到：上游不返回交易发生日，行只有公告日 ann_date；方向见 direction（增持/减持）；
      量=股、率=小数（上游百分数已 ×0.01）、价=元；holder_type 中文对照
      （G=高管/C=大股东/P=机构投资者）以源披露为准；单日榜按变动股数降序，
      单票历史 date 升序；高管口径的持股变动另见 equity.query_exec_change
文档：docs/GUIDE.md「行情」节 · API.md「股东增减持」章
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 单票增减持历史（600519 最近 5 条，date 升序） ==")
    hist = cli.holdertrade.by_symbol("600519", 5)
    rows = hist.to_dict("records") if hasattr(hist, "to_dict") else list(hist)
    if not rows:
        print("  暂无数据（采集上线回补后可用）")
    for r in rows:
        ratio = f"{r['change_ratio'] * 100:.2f}%" if r["change_ratio"] else "缺"
        print(f"  {r['date']} {r['direction']} {r['holder_role'] or '未知'} "
              f"{r['change_vol'] / 1e4:.0f} 万股（占总股本 {ratio}）")

    print("== 2. 某公告日全市场前 5（变动股数降序） ==")
    day = cli.holdertrade.by_date("2026-11-27", 5)
    day_rows = day.to_dict("records") if hasattr(day, "to_dict") else list(day)
    if not day_rows:
        print("  该日暂无数据（回补后可用）")
    for r in day_rows:
        vol = f"{r['change_vol'] / 1e4:.0f} 万股"
        print(f"  {r['symbol']} {r['direction']} {vol} {r['holder'][:18]}")

    print("== 3. 自检：单票历史 date 升序（SDK 门面统一翻序） ==")
    dates = [r["date"] for r in rows]
    print(f"  dates 升序={dates == sorted(dates)}（{dates}）")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
