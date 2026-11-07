"""可转债双低榜：board 全市场面板一次取全（快照+事件+强赎/下修观测），客户端算双低。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；演示快照不含 cbond 域，故无 --demo
运行：python examples/14_cbond_double_low.py
学到：cbond.board 单次全市场面板；双低=价格+溢价率×100（小数口径）；强赎/下修观测行内直读
文档：docs/GUIDE.md（单票菜谱·可转债）、docs/notebooks/cb_double_low.ipynb（完整实战）
"""
import sys

import wmshare
from wmshare import WmshareError

TOP_N = 20  # 双低榜行数


def main(cli=None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    # ---- 一次调用 = 全市场面板 ----
    try:
        rows = cli.cbond.board()
    except (AttributeError, WmshareError) as e:
        # 演示快照不含 cbond 域；此处需真实凭证
        print(f"cbond 域不可用（{e}）：本示例需真实凭证（WMSHARE_CLIENT_ID/SECRET）")
        return
    rows = rows if isinstance(rows, list) else rows.get("rows", [])

    traded = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        px, prem = r.get("bondPrice"), r.get("premiumRatio")
        if isinstance(px, (int, float)) and px and isinstance(prem, (int, float)):
            r = dict(r)
            r["_price"] = float(px)
            r["_prem_pct"] = float(prem) * 100            # premiumRatio 小数 → 百分数展示
            r["_dl"] = r["_price"] + r["_prem_pct"]       # 双低 = 价格 + 溢价率×100
            traded.append(r)
    traded.sort(key=lambda r: r["_dl"])

    asof = max((str(r.get("asOf"))[:10] for r in rows if isinstance(r, dict) and r.get("asOf")),
               default="")
    print(f"board 全表 {len(rows)} 行 · 在市 {len(traded)} 只 · 数据截至 {asof}")
    print("口径：双低 = 价格(元) + 转股溢价率(小数)×100；正股简称含 ST 即风险警示")

    # ---- 双低榜前 20 ----
    print(f"\n--- 双低榜前 {TOP_N}（先看警示列再看排名：低价的来源可能是信用风险而不是便宜）---")
    for r in traded[:TOP_N]:
        st = "ST" if "ST" in str(r.get("stockName") or "") else "—"
        print(f"  {r.get('bondName') or '':<8} {r.get('bondCode')}  "
              f"价格={r['_price']:.2f}元  溢价率={r['_prem_pct']:.2f}%  "
              f"双低={r['_dl']:.2f}  正股={r.get('stockName') or '—'}  警示={st}")

    mean_dl = sum(r["_dl"] for r in traded) / len(traded)
    srt = sorted(r["_dl"] for r in traded)
    n = len(srt)
    median_dl = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    print(f"\n全市场双低均值 {mean_dl:.2f} · 中位数 {median_dl:.2f}（元+%，两数对照防极值误导）")

    # ---- 强赎观测（board 行内直读，服务端 30 交易日窗计数）----
    active = sorted([r for r in traded if isinstance(r.get("callHits"), (int, float))
                     and r["callHits"] > 0], key=lambda r: -r["callHits"])
    print(f"\n--- 强赎观测（callHits = 近窗满足天数；勿以单日价判定已满足，15/30 规则另行判读）---")
    print(f"  近窗已满足天数 >0 的 {len(active)} 只")
    for r in active[:5]:
        print(f"    {r.get('bondName')}（{r['bondCode']}）{int(r['callHits'])} 天（触发价 {r.get('redeemTrig')}）")

    # ---- 下修观测（board 行内直读地板价测算）----
    floors = [r for r in traded if r.get("resetFloor") is not None]
    print(f"\n--- 下修观测（resetFloor = 条款测算的下修地板价，测算中 {len(floors)} 只）---")
    for r in floors[:5]:
        print(f"    {r.get('bondName')}（{r['bondCode']}）地板价 {r['resetFloor']:.2f} 元"
              f"（现价 {r['_price']:.2f} 元）")

    print("\n完整实战（价差图/估值通道拨测/事件流）：docs/notebooks/cb_double_low.ipynb")
    print("全部输出为数据整理与研究参考，不构成任何投资建议。")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as e:
        print(f"[wmshare] {e}", file=sys.stderr)
        sys.exit(1)
