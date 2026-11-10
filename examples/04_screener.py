"""选股与全景：全市场条件选股 + 单票筛选器 + 全市场涨跌宽度（服务端索引直出）。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/04_screener.py
学到：一条表达式全市场选股（count 是真命中数）；涨停/均线/放量单票筛选；全景/分桶/涨跌榜；*_pct 百分数例外口径
文档：docs/GUIDE.md（单票菜谱）
"""
import sys
import wmshare
from wmshare import Client, WmshareError

WATCHLIST = ["600519", "000858", "601088", "600900", "601318"]  # 自选股，换成你的


def main(cli=None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            cli = wmshare.Client.from_env()

    # ---- 单票一行布尔：涨停 / 站上 MA20 / 放量（停牌恒 False）----
    print("--- 单票筛选器（阈值均为小数：0.10 = 10%）---")
    for sym in WATCHLIST:
        try:
            print(f"  {sym}  涨停={cli.screener.screen_limit_up(sym)}"
                  f"  站上MA20={cli.screener.screen_above_ma20(sym)}"
                  f"  放量={cli.screener.screen_volume_spike(sym)}")
        except WmshareError as e:
            print(f"  {sym}  跳过：code={e.code} {e}")

    # ---- 全市场涨跌全景：服务端预计算索引直出，免本地扫描 ----
    print("\n--- 涨跌全景（*_pct 百分数数值，median_pct 小数）---")
    try:
        s = cli.screener.index_breadth_summary()
        print(f"  总数={s.get('total')}  涨={s.get('up')}({s.get('up_pct')}%)"
              f"  跌={s.get('down')}({s.get('down_pct')}%)  平={s.get('flat')}"
              f"  涨跌幅中位数={s.get('median_pct')}")
    except WmshareError as e:
        print(f"  跳过：code={e.code} {e}")

    # ---- 涨跌幅 9 档分桶：涨停档 / 大涨档家数一目了然 ----
    print("\n--- 涨跌幅分桶（前 3 档）---")
    try:
        for b in cli.screener.index_breadth_bins()[:3]:
            print(f"  {b['label']:<12} {b['count']:>5} 家（{b['pct_of_total']}%）")
    except WmshareError as e:
        print(f"  跳过：code={e.code} {e}")

    # ---- 涨跌榜：行含 symbol/name/percent（percent 为小数）----
    print("\n--- 涨幅榜 Top5 / 跌幅榜 Top3 ---")
    try:
        for r in cli.screener.index_top_movers(limit=5):
            print(f"  {r['symbol']}  {r['name']:<6} {r['percent']:+.2%}")
        print("  ---")
        for r in cli.screener.index_top_movers(limit=3, desc=False):
            print(f"  {r['symbol']}  {r['name']:<6} {r['percent']:+.2%}")
    except WmshareError as e:
        print(f"  跳过：code={e.code} {e}")

    # ---- 全市场条件选股：一条表达式，服务端索引直出（count 才是真命中数）----
    print("\n--- 全市场条件选股：三年股息均值 > 3% 且 ROE > 15% ---")
    try:
        res = cli.screener.query(
            "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15"
            " && !$IS_ST && !$IS_SUSPEND",
            order="$BONUS_RATE_3Y_AVG_LAST", limit=5,
        )
        print(f"  全市场命中 {res['count']} 只（下面只列前 {len(res['rows'])} 只）")
        for r in res["rows"]:
            print(f"  {r['symbol']}  {r['name']:<6}"
                  f"  三年股息率均值 {r['$BONUS_RATE_3Y_AVG_LAST']:.2%}"
                  f"  ROE {r['$ROE_TTM_LAST']:.2%}")
    except WmshareError as e:
        print(f"  跳过：code={e.code} {e}")

    # ---- 底层函数直达：门面不遮蔽目录函数，269 个都能经属性调用 ----
    print("\n--- 底层函数直达：cli.screener.screen_up_today(sym) ---")
    for sym in WATCHLIST[:2]:
        try:
            print(f"  {sym}  今日上涨={cli.screener.screen_up_today(sym)}")
        except WmshareError as e:
            print(f"  {sym}  跳过：code={e.code} {e}")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
