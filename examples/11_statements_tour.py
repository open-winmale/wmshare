"""财务报表：三大报表多期科目行（cn/hk/us 全市场宽表）+ 审计意见。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/11_statements_tour.py
学到：报表行结构（k 科目键=披露科目原文/cn 同列名/vals 各期值，金额=披露原币）；period="quarter" 取季报全档；审计意见按年报
文档：docs/GUIDE.md（单票菜谱·三大报表）
"""
import sys
import wmshare

SYMBOL = "600519"


def main(cli=None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            cli = wmshare.Client.from_env()

    # ---- 三大报表：科目行 {k 科目键, cn 同列名, vals:{年份: 值}}，金额=披露原币 ----
    for kind, title in (("income", "利润表"), ("balance", "资产负债表"),
                        ("cashflow", "现金流量表")):
        df = getattr(cli.statements, kind)(SYMBOL, years=1)
        first = next(r for r in df.to_dict("records") if r.get("vals"))
        y, v = next(iter(first["vals"].items()))
        print(f"{title}：{len(df)} 行科目；如「{first['k']}」（{y}）= {v:,.0f}")

    # ---- 季报全档：period="quarter"，期次键 "2026-Q1" 形式（2.0 连字符口径） ----
    q_rows = cli.statements.income(SYMBOL, years=1, period="quarter")
    q_first = next((r for r in q_rows.to_dict("records") if r.get("vals")), None)
    if q_first:
        qk = sorted(q_first["vals"], reverse=True)[:3]
        print(f"季报档（近 3 期）：{qk}")

    # ---- 审计意见（按年报，cn）----
    audit = cli.statements.audit(SYMBOL)
    for y in sorted(audit, reverse=True)[:2]:
        print(f"{y} 年审计意见：{audit[y]}")


if __name__ == "__main__":
    demo = "--demo" in sys.argv
    main(demo=demo)
