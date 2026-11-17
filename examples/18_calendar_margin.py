"""交易日历与市场级两融：回测窗口的前置面 + 市场杠杆情绪观测。

前提：需真实凭证（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo`
  用随包快照（2026-11-17 重拍已覆盖 calendar/margin 市场面/futures）零凭证试跑
运行：python examples/18_calendar_margin.py
学到：calendar.days/next 供回测与窗口计算取交易日锚（此前靠日 K 存在性隐式判定的坑移除）；
  margin.market_summary 观测全市场融资余额（杠杆情绪）；margin.universe 判定标的资格；
  futures.snapshot 取期货连续合约快照（商品 RB / 金融 IF，中金所 CFX 也支持）
文档：docs/GUIDE.md（§批量与全市场）+ docs/API.md（market.calendar / market.margin）
"""
import sys
from typing import Any

import wmshare
from wmshare import UsageError, WmshareError


def main(cli: Any = None, demo: bool = False) -> None:
    if cli is None:
        cli = wmshare.demo_client() if demo else wmshare.Client.from_env()
    if demo:
        print("[演示模式] 随包快照回放（2026-11-17 拍摄，非实时）")

    _print("交易日历：2026-01 区间交易日（前 5 行）", _safe(lambda: cli.calendar.days("2026-01-01", "2026-01-31")))
    _print("日历：之后 3 个交易日（自最近已知日起）", _safe(lambda: cli.calendar.next("2026-01-30", 3)))
    _print("日历：2026-01-01 是否开市（节假日=False）", _safe(lambda: cli.calendar.is_open("2026-01-01")))
    _print("市场级两融汇总：最近 6 行（融资余额=全市场杠杆水位）", _safe(lambda: cli.margin.market_summary(limit=6)))
    _print("两融标的名单：前 5 行（out_date 空=当前生效）", _safe(lambda: cli.margin.universe(limit=5)))
    _print("期货快照：螺纹钢 rb（价格=元/量=手/金额=万元）", _safe(lambda: cli.futures.snapshot("RB.SHF")))
    _print("期货快照：沪深300股指 IF（中金所 CFX）", _safe(lambda: cli.futures.snapshot("IF.CFX")))


def _print(title: str, value: Any) -> None:
    print(f"\n== {title} ==")
    if value is None:
        return
    if hasattr(value, "head"):        # DataFrame：打印前几行 + 升序首尾
        print(value.head().to_string(index=False))
        return
    print(value)


def _safe(fn: Any) -> Any:
    """demo 快照不回放 2.0 新面时显式降级说明（不伪造数据）。"""
    try:
        return fn()
    except UsageError as e:
        if getattr(e, "code", "") == "demo_unsupported":
            print(f"[demo 跳过] {e}")
            return None
        raise
    except WmshareError as e:
        print(f"[取数失败] {e}")
        return None


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
