"""分红质量：高股息且派息可持续的单票筛选，call_batch 批量 TTM 股息率。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/05_dividend_screener.py
学到：screen_quality 窗口语义；call_batch 票级批量；底层函数属性直达
文档：docs/GUIDE.md（单票菜谱、批量取数）
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

    # ---- 单票质量筛选：分红质量优（高股息 + 派息可持续）----
    print("--- 分红质量筛选（质量优 = 通过）---")
    for sym in WATCHLIST:
        try:
            ok = cli.dividend.screen_quality(sym, min_yield=0.02, payout_max=1.2)
            y = cli.dividend.yield_ttm(sym)
            print(f"  {sym}  TTM股息率={y if y is not None else '—':<8} 质量优={ok}")
        except WmshareError as e:
            print(f"  {sym}  跳过：code={e.code} {e}")

    # ---- 批量调用：call_batch 单次 HTTP 返回 {symbol: 结果} ----
    # 注意目录名是 bonus.*（门面叫 dividend）——命名不必背，cat.search("股息") 一查即得
    print("\n--- call_batch：一次请求取全部自选股 TTM 股息率 ---")
    # on_error="skip" 是票级隔离：少量标的合适；全市场批量容错必须用
    # batch_all(on_batch_error="skip")（批级）——票级 skip 会把 11 批放大成 5,375 次请求
    batch = cli.call_batch("bonus.snapshot_yield_ttm", WATCHLIST, on_error="skip")
    for sym, val in sorted(batch.results.items(), key=lambda kv: -(kv[1] or 0)):
        print(f"  {sym}  {val:.2%}" if val is not None else f"  {sym}  —")
    if batch.errors:
        print(f"  错误隔离：{len(batch.errors)} 个失败 → {dict(list(batch.errors.items())[:3])}")

    # ---- 底层选股函数经属性直达（__getattr__ 兜底，252 个目录函数都能直达）----
    # 注意：index_where_* 返回的是服务端查询引擎的筛选条件表达式（非本地可执行的票池），
    # 供下游工具消费（如 big-winner）；SDK 不内置执行入口。
    print("\n--- 底层函数直达：cli.dividend.index_where_high_yield_5() ---")
    try:
        expr = cli.dividend.index_where_high_yield_5()  # 「连续 5 年高股息」筛选条件表达式
        print(f"  筛选表达式：{str(expr)[:80]}")
    except WmshareError as e:
        print(f"  跳过：code={e.code} {e}")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
