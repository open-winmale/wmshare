"""收息流投研闭环：排行 → 批量诊断 → 日历 → 拆解。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/19_income_rating.py
学到：dividend.rating 全市场一次取数（勿现场重算评分）、diagnose 原生批量
      （勿逐票循环）、COLD_CACHE 与冷首查尖刺的处理姿势
文档：docs/GUIDE.md「收息场景」节 · 目录 `cat.function("income.rating_rows")`
"""

from __future__ import annotations

from typing import Any


def main(cli: Any = None) -> None:
    import wmshare

    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 发现：全市场收息排行（四维评分 + 档位 + 资格门，一次取数） ==")
    env = _safe(cli.dividend.rating, top_n=5, grade="strong")
    if env is None:
        return
    if not env.get("ok"):
        print("  COLD_CACHE：收息榜 cron 未就绪（16:50/19:40 物化），稍后重试")
        return
    for row in env["data"]["rows"]:
        sc = row["score"]
        print(f"  #{row['rank']} {row['symbol']} {row['name']}  "
              f"TTM息率={row['yield_ttm']:.2%}  档位={sc['grade']}({sc['total']}分)  "
              f"股息分={row['dividend_score']:.4f}  过门={row['gate_pass']}  "
              f"flags={sc['flags'] or '—'}")

    print("== 2. 研判：批量收息诊断（一次调用，勿逐票循环） ==")
    picks = [r["symbol"] for r in env["data"]["rows"][:3]]
    diag = _safe(cli.dividend.diagnose, picks)
    if diag is None:
        return
    for it in diag["data"]["items"]:
        sc = it.get("score") or {}
        rank = (it.get("rank") or {}).get("rank")
        print(f"  {it['symbol']} {it.get('name')}  档位={sc.get('grade')}({sc.get('total')}分)  "
              f"榜内第{rank}名  flags={sc.get('flags') or '—'}")
        fx = it.get("floor_explain") or {}
        if fx.get("residual") is not None and abs(float(fx["residual"])) > 0.002:
            print(f"    静态下限复原残差 {fx['residual']:+.4f}（走了通用档，gate_uncertain）")

    print("== 3. 跟踪：分红日历（本月，自选过滤） ==")
    import datetime as _dt

    today = _dt.date.today()
    cal = _safe(cli.dividend.calendar, today.strftime("%Y-%m-01"),
                today.strftime("%Y-%m-%d"), codes=picks[:2])
    if cal is None:
        return
    events = (cal.get("data") or {}).get("events") or []
    print(f"  本月命中 {cal['data'].get('count')} 个事件（含公告/登记/除息/到账四类日期）")
    for ev in events[:3]:
        print(f"    {ev.get('stock_code')} ex_date={ev.get('ex_date')} "
              f"announce={ev.get('announce_date')}")

    print("== 4. 验证：N 年拿息收益拆解（总收益 = 价格 + 股息贡献，差值口径） ==")
    dc = _safe(cli.dividend.decomp, picks[:2], years=3)
    if dc is None:
        return
    for it in (dc.get("data") or {}).get("items") or []:
        if not it.get("ok"):
            print(f"  {it.get('code')}：K 线覆盖不足（次新股），如实跳过")
            continue
        print(f"  {it['code']} 近3年：总 {it['total_return']:+.2%} = "
              f"价格 {it['price_return']:+.2%} + 股息 {it['dividend_return']:+.2%}  "
              f"股息CAGR {it.get('cagr_dividend') or 0:+.2%}")

    print("提示：档位/单位口径与网页收息榜逐字一致；flags 硬修正必须透传，"
          "不得静默改述。成本口径见 cli.cost_estimate('dividend.rating')。")


def _safe(fn, *args, **kwargs):
    """数据面缺失显式降级（不伪造数据）；真实故障原样抛出。"""
    import wmshare

    try:
        return fn(*args, **kwargs)
    except wmshare.WmshareError as e:
        if getattr(e, "code", "") == "replay_unsupported":
            print(f"[跳过] {e}")
            return None
        raise


if __name__ == "__main__":
    main()
