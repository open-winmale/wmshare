"""指标适配层：按分类找码、只组合同口径的码、扁平码单独看。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/16_metric_adapter.py
学到：scopes/topics 发现、combinable_groups 组合边界、table 长表、many 多标的小列表
文档：docs/METRIC_ADAPTER.md
"""
import sys

import wmshare
from wmshare.indicator_adapter import IndicatorAdapter


def main(cli=None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            cli = wmshare.Client.from_env()
    ad = IndicatorAdapter(cli)
    SYM = "600519"

    # ---- ① 分类发现：先看数据对象，再看主题（纯本地，零网络零额度） ----
    scopes = ad.scopes()
    print("指标 scope：" + "、".join(f"{s['id']}({s['cn']})" for s in scopes[:5]))
    topics = ad.topics("stock")
    print(f"stock topic {len(topics)} 个：" +
          "、".join(t["id"] for t in topics[:6]))

    # ---- ② 看组合边界：同 unit/period/window/caliber/market 才能同组 ----
    val = ad.combinable_groups(scope="stock", topic="valuation")
    print(f"\nvaluation：可组合组 {len(val['groups'])} 个，"
          f"扁平码 {len(val['flat'])} 个")
    if val["groups"]:
        g = next((x for x in val["groups"] if "$PE_TTM_LAST" in x["codes"]),
                 val["groups"][0])
        print(f"  组 {g['group_id']}：{g['count']} 码，示例 {g['codes'][:3]}")

    # ---- ③ 长表：同组一次取，flat 码逐个取，一行一个码 ----
    codes = ["$PE_TTM_LAST", "$ROE_TTM_LAST",
             "$PCT_PE_TTM_10Y_LAST", "$CUR_IND_ROE_PCT_LAST"]
    rows = ad.table(SYM, codes)
    print(f"\n{SYM} 适配长表（{len(rows)} 行）：")
    for row in rows:
        value = row["value"]
        shown = "—" if value is None else f"{value:.4f}"
        print(f"  {row['code']:<28} {shown:>10}  "
              f"{row['period']}/{row['window']}/{row['unit_kind']}  "
              f"group={row['group_id'] or 'flat'}")

    # ---- ④ 多标的：只对小列表做客户端 fan-out，requests 如实计数 ----
    res = ad.many([SYM, "000001"], ["$PE_TTM_LAST", "$ROE_TTM_LAST"])
    print(f"\n多标的小列表：{res.requested} 标的 / {res.requests} 次 eval")
    for symbol, values in res.results.items():
        print(f"  {symbol}: {values}")

    # ---- ⑤ 全市场截面不走 many：交给 screener.query 一次查完 ----
    print("\n全市场截面：cli.screener.query(fields=codes, _df=True)"
          "（服务端索引，不是逐票 many）")


if __name__ == "__main__":
    try:
        main(demo="--demo" in sys.argv)
    except wmshare.WmshareError as e:
        print(f"取数失败：{e}")
        raise SystemExit(1)
