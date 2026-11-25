"""指标码体系漫游：先查目录、再取数、率与分位一律读小数。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/06_indicator_tour.py
学到：cat.search 检索、指标组浏览、indicator.get 分位、valuation.hist_stats 历史统计
文档：docs/GUIDE.md（核心概念、故障排查）；docs/AI.md（目录先行纪律）
"""
import wmshare


def main(cli=None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()
    cat = wmshare.load()
    SYM = "600519"

    # ---- ① 目录先行：中文口语检索函数与指标码（纯本地，零网络零额度） ----
    hits = cat.search("股息")
    print(f'cat.search("股息") → {len(hits)} 条命中，前 3 条：')
    for h in hits[:3]:
        print(f"  [{h['kind']}] {h.get('name') or h.get('code')}  {h.get('cn', '')}")

    # ---- ② 指标组：精选指标按组浏览（写代码前先看有哪些码） ----
    groups = cat.metric_groups()
    print(f"\n指标组 {len(groups)} 个：{'、'.join(g['id'] for g in groups)}")

    # ---- ③ 当前值：TTM 股息率（小数口径，0.0396 = 3.96%） ----
    y = cli.dividend.yield_ttm(SYM)
    print(f"\nTTM 股息率 = {y:.4f}（{y:.2%}）" if y is not None else "TTM 股息率 = —")

    # ---- ④ 历史分位：PE(TTM) 近 10 年分位（0 = 十年最便宜，1 = 最贵） ----
    pct = cli.indicator.get(SYM, "$PCT_PE_TTM_10Y_LAST")
    print(f"PE(TTM) 近 10 年分位 = {pct}（{pct:.0%}）")

    # ---- ⑤ 行业内定位：ROE 同行业分位（1 = 同行业最高） ----
    ind = cli.indicator.get(SYM, "$CUR_IND_ROE_PCT_LAST")
    print(f"行业内 ROE 分位 = {ind}（1 = 同行业最高）")

    # ---- ⑥ 历史统计：PE 3 年窗口的高低与中位（pct 为小数分位） ----
    resp = cli.valuation.hist_stats(SYM, metric="pe", window="3y")
    st = resp["data"]          # 2.0：统一信封 {ok, as_of, data, meta}
    print("PE 3 年统计：当前={current:.1f}  中位={median:.1f}  "
          "区间=[{min:.1f}, {max:.1f}]  位置={pct:.0%}".format(**st))

    # ---- ⑦ 组内全量精选指标（cat.metrics_in_group 可编程取清单） ----
    div_metrics = cat.metrics_in_group("dividend")
    codes = "、".join(m["code"] for m in div_metrics[:6])
    print(f"\ndividend 组 {len(div_metrics)} 个精选指标：{codes} …")


if __name__ == "__main__":
    try:
        main()
    except wmshare.WmshareError as e:
        # 错误消息自带修复步骤（凭证/限流/参数合同），打印原文即可定位
        print(f"取数失败：{e}")
        raise SystemExit(1)
