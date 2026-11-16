"""红利排雷：市赚率(PRR)+现金流覆盖三维筛选——硬卡点全压一条 screener.query，本地补打分。

前提：需真实凭证（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包罐头数据走通全流程（非真实行情）
运行：python examples/17_prr_dividend_screen.py
学到：估值/分红/偿债硬卡点一次压进 where（count=真命中数）；fields 一次带回打分列；本地补行业剔除、现金流覆盖与 CHI 排名
文档：docs/GUIDE.md（单票菜谱）
"""
import sys
from datetime import date
from typing import Any

import wmshare
from wmshare import WmshareError

# ---- 三维硬卡点（阈值均在服务端 where 里，count 即全市场真命中数）----
WHERE = (
    "$PR_LAST < 1.2"                        # 维度一 估值：市赚率 <1.2（PE/ROE，越低越便宜）
    " && $BONUS_RATE_3Y_AVG_LAST > 0.045"   # 维度二 分红：股息率 3 年均值 ≥4.5%（防单年高息）
    " && $BONUS_TTM_RATE_LAST > 0.30"       # 维度二 分红：支付率下限 30%（太低说明分红意愿弱）
    " && $BONUS_TTM_RATE_LAST < 0.75"       #                 上限 75%（太高是透支）
    " && $IBD_RATE_LAST < 0.55"             # 维度三 安全垫：有息负债率 ≤55%（非金融口径）
    " && !$IS_ST && !$IS_SUSPEND"           # 排雷底线：剔 ST / 停牌
)
# 打分所需列一次带回（fields 传了会替代默认列集合；symbol/name 恒在）
FIELDS = ["$PR_LAST", "$BONUS_RATE_3Y_AVG_LAST", "$BONUS_TTM_RATE_LAST",
          "$NCFO_TTM_LAST", "$BONUS_TTM", "$IBD_RATE_LAST", "$CSRC_INDUSTRY_NAME"]

QUERY_LIMIT = 200          # 候选池上限；count 与 limit 无关，只影响带回行数
COVERAGE_MIN = 1.3         # 维度三：经营现金流 / 分红总额 ≥1.3 倍（本地卡点，where 不支持列间除法）
PCT_PR_MAX = 0.5           # 维度一：PRR 3 年分位 ≤50%（hist_stats 上限 3 年，逐票补）
PAYOUT_GOLD_LO, PAYOUT_GOLD_HI = 0.40, 0.60   # 支付率黄金区间（满分），向 30%/75% 线性衰减
W_VALUATION, W_DIVIDEND, W_CASHFLOW = 0.35, 0.35, 0.30  # CHI 三维权重

# 演示罐头 7 行（非真实行情；方向与 live 一致：PRR 越低 / 覆盖越高得分越高）
DEMO_ROWS: list[dict[str, Any]] = [
    dict(symbol="600519", name="贵州茅台", **{"$PR_LAST": 0.55, "$BONUS_RATE_3Y_AVG_LAST": 0.062,
         "$BONUS_TTM_RATE_LAST": 0.52, "$NCFO_TTM_LAST": 9.2e10, "$BONUS_TTM": 3.4e10,
         "$IBD_RATE_LAST": 0.12, "$CSRC_INDUSTRY_NAME": "制造业-酒、饮料和精制茶制造业", "_demo_pct": 0.22}),
    dict(symbol="000333", name="美的集团", **{"$PR_LAST": 0.75, "$BONUS_RATE_3Y_AVG_LAST": 0.055,
         "$BONUS_TTM_RATE_LAST": 0.48, "$NCFO_TTM_LAST": 4.0e10, "$BONUS_TTM": 1.8e10,
         "$IBD_RATE_LAST": 0.20, "$CSRC_INDUSTRY_NAME": "制造业-电气机械和器材制造业", "_demo_pct": 0.35}),
    dict(symbol="601088", name="中国神华", **{"$PR_LAST": 0.90, "$BONUS_RATE_3Y_AVG_LAST": 0.058,
         "$BONUS_TTM_RATE_LAST": 0.62, "$NCFO_TTM_LAST": 8.0e10, "$BONUS_TTM": 5.0e10,
         "$IBD_RATE_LAST": 0.18, "$CSRC_INDUSTRY_NAME": "采矿业-煤炭开采和洗选业", "_demo_pct": 0.48}),
    dict(symbol="600036", name="招商银行", **{"$PR_LAST": 0.60, "$BONUS_RATE_3Y_AVG_LAST": 0.060,
         "$BONUS_TTM_RATE_LAST": 0.35, "$NCFO_TTM_LAST": 1.0e11, "$BONUS_TTM": 3.0e10,
         "$IBD_RATE_LAST": 0.50, "$CSRC_INDUSTRY_NAME": "金融业-货币金融服务", "_demo_pct": 0.30}),
    dict(symbol="601318", name="中国平安", **{"$PR_LAST": 0.50, "$BONUS_RATE_3Y_AVG_LAST": 0.055,
         "$BONUS_TTM_RATE_LAST": 0.45, "$NCFO_TTM_LAST": 5.0e10, "$BONUS_TTM": 2.0e10,
         "$IBD_RATE_LAST": 0.40, "$CSRC_INDUSTRY_NAME": "金融业-保险业", "_demo_pct": 0.15}),
    dict(symbol="000651", name="格力电器", **{"$PR_LAST": 0.70, "$BONUS_RATE_3Y_AVG_LAST": 0.072,
         "$BONUS_TTM_RATE_LAST": 0.55, "$NCFO_TTM_LAST": 2.0e10, "$BONUS_TTM": 2.5e10,
         "$IBD_RATE_LAST": 0.30, "$CSRC_INDUSTRY_NAME": "制造业-电气机械和器材制造业", "_demo_pct": 0.40}),
    dict(symbol="600276", name="恒瑞医药", **{"$PR_LAST": 0.85, "$BONUS_RATE_3Y_AVG_LAST": 0.050,
         "$BONUS_TTM_RATE_LAST": 0.50, "$NCFO_TTM_LAST": 7.0e10, "$BONUS_TTM": 3.0e10,
         "$IBD_RATE_LAST": 0.10, "$CSRC_INDUSTRY_NAME": "制造业-医药制造业", "_demo_pct": 0.81}),
]


def payout_score(payout: float) -> float:
    """支付率合理性得分：40%~60% 黄金区间满分，向 30%/75% 两个硬边界线性衰减到 0。"""
    if PAYOUT_GOLD_LO <= payout <= PAYOUT_GOLD_HI:
        return 1.0
    if payout < PAYOUT_GOLD_LO:
        return max(0.0, (payout - 0.30) / (PAYOUT_GOLD_LO - 0.30))
    return max(0.0, (0.75 - payout) / (0.75 - PAYOUT_GOLD_HI))


def cash_coverage(ncfo: Any, bonus: Any) -> float | None:
    """现金分红覆盖倍数 = 经营现金流净额TTM / 分红股息TTM（均为元）；分红缺失返回 None。"""
    if not ncfo or not bonus or bonus <= 0:
        return None
    return ncfo / bonus


def _rank_pct(values: list[float]) -> list[float]:
    """升序排名百分位（0=最小值，1=最大值）；单元素记 1.0。"""
    n = len(values)
    if n <= 1:
        return [1.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    for pos, i in enumerate(order):
        out[i] = pos / (n - 1)
    return out


def add_chi(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """红利健康指数 CHI = 0.35×估值 + 0.35×分红 + 0.30×现金流（候选集内 rank 标准化）。"""
    s_prr = [1.0 - v for v in _rank_pct([r["$PR_LAST"] for r in rows])]      # PRR 越低越好
    s_div = [0.5 * dv + 0.5 * payout_score(r["$BONUS_TTM_RATE_LAST"])
             for dv, r in zip(_rank_pct([r["$BONUS_RATE_3Y_AVG_LAST"] for r in rows]), rows)]
    s_cash = _rank_pct([r["coverage"] for r in rows])                          # 覆盖倍数越高越好
    out = []
    for r, v, d, c in zip(rows, s_prr, s_div, s_cash):
        out.append({**r, "chi": W_VALUATION * v + W_DIVIDEND * d + W_CASHFLOW * c})
    return out


def local_screen(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """本地排雷前两步：剔金融 → 现金流覆盖达标。返回（带 coverage 的行, 漏斗说明行）。"""
    non_fin = [r for r in rows
               if not str(r.get("$CSRC_INDUSTRY_NAME") or "").startswith("金融业")]
    kept = []
    for r in non_fin:
        cov = cash_coverage(r["$NCFO_TTM_LAST"], r["$BONUS_TTM"])
        if cov is not None and cov >= COVERAGE_MIN:
            kept.append({**r, "coverage": cov})
    funnel = [
        f"① 证监会门类剔金融业：-{len(rows) - len(non_fin)} 只 → {len(non_fin)}",
        f"② 经营现金流覆盖分红 ≥{COVERAGE_MIN} 倍："
        f"-{len(non_fin) - len(kept)} 只 → {len(kept)}",
    ]
    return kept, funnel


def enrich_percentiles(cli: Any, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """逐票补 PRR 3 年分位（hist_stats 的 pr 与 $PR_LAST 同为市赚率口径，实测茅台 0.7021 vs 0.7040）。

    返回（分位达标行, 被分位剔除数, 取数失败数）。取数失败显式计数并剔除，
    不静默当 0 分位（预热缓存会冷，不能拿缺失当数值）。
    """
    kept, dropped, skipped = [], 0, 0
    for r in rows:
        try:
            pct = r.get("_demo_pct")
            if pct is None:
                pct = cli.valuation.hist_stats(r["symbol"], metric="pr", window="3y")["pct"]
        except WmshareError:
            skipped += 1
            continue
        if pct <= PCT_PR_MAX:
            kept.append({**r, "pct_pr": pct})
        else:
            dropped += 1
    return kept, dropped, skipped


def main(cli: Any = None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            cli = wmshare.Client.from_env()

    print("--- 三维硬卡点（服务端一条表达式，count=真命中数，阈值均为小数）---")
    print("  PRR<1.2 · 股息率3Y均值≥4.5% · 支付率30%~75% · 有息负债率≤55% · 剔ST/停牌")
    print(f"  跑批日期：{date.today().isoformat()}（数据为日频 EOD 口径）")
    try:
        # 首跑会触发 EC 告警：fields 重列全市场物化是一次性成本，之后命中服务端缓存
        res = cli.screener.query(WHERE, fields=FIELDS, limit=QUERY_LIMIT)
        rows, count = res["rows"], res["count"]
    except WmshareError as e:
        if e.code != "demo_unsupported":       # 演示客户端无全市场索引列，换罐头行
            raise
        rows, count = [dict(r) for r in DEMO_ROWS], len(DEMO_ROWS)
    print(f"  全市场命中 {count} 只（下面进入本地排雷）")

    scored, funnel = local_screen(rows)
    scored, by_pct, skipped = enrich_percentiles(cli, scored)
    scored = sorted(add_chi(scored), key=lambda r: r["chi"], reverse=True)  # 只在最终候选集内打分
    print("--- 本地排雷三步 ---")
    for line in funnel:
        print(f"  {line}")
    print(f"  ③ PRR 3 年分位 ≤{PCT_PR_MAX:.0%}：-{by_pct} 只 → {len(scored)}"
          f"（hist_stats 取数失败跳过 {skipped} 只）")

    print("\n--- 红利健康指数 CHI 榜（0.35 估值 + 0.35 分红 + 0.30 现金流）---")
    print(f"  {'代码':<8}{'名称':<6}{'PRR':>6}{'分位':>6}{'股息率3Y':>9}"
          f"{'支付率':>8}{'覆盖':>6}{'有息负债':>8}{'CHI':>6}")
    for r in scored[:10]:
        print(f"  {r['symbol']:<8}{r['name']:<6}{r['$PR_LAST']:>6.2f}{r['pct_pr']:>6.0%}"
              f"{r['$BONUS_RATE_3Y_AVG_LAST']:>9.2%}{r['$BONUS_TTM_RATE_LAST']:>8.1%}"
              f"{r['coverage']:>6.2f}{r['$IBD_RATE_LAST']:>8.1%}{r['chi']:>6.2f}")
    if not scored:
        print("  （无票通过全部门槛——放宽硬卡点后重跑，或换个市场环境再看）")


if __name__ == "__main__":
    try:
        main(demo="--demo" in sys.argv)
    except WmshareError as e:
        print(f"取数失败：{e}")   # 错误消息自带修复步骤，打印原文即可
        raise SystemExit(1)
