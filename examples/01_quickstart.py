"""快速上手：四类数据一次过，全市场批量只花 12 次请求。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/01_quickstart.py
学到：行情/财务/披露/参考四类取数；批量绕开 429；错误消息自带申请步骤
文档：docs/GUIDE.md（安装与凭证、单票菜谱、批量取数）
"""
import sys
import wmshare


def main(cli=None, demo: bool = False) -> None:
    if cli is None:
        if demo:
            cli = wmshare.demo_client()
            print("(演示模式：随包罐头数据，非真实行情)")
            print()
        else:
            cli = wmshare.Client.from_env()
    SYMBOL = "600519"

    # ---- 市场行情 ----
    bars = cli.kline.bars(SYMBOL, n=5)
    print("最近 5 根日 K：")
    for bar in bars:
        print(f"  {bar['date']}  收盘 {bar['close']}  涨跌 {bar['percent']:.2%}")

    snapshot = cli.kline.snapshot(SYMBOL)
    print(f"行情摘要：收盘 {snapshot['close']}，近20日 {snapshot['chg_20d']:.2%}")

    mf = cli.moneyflow.last(SYMBOL)
    if mf:
        print(f"最新主力净流入：{mf.get('net_mf'):,.0f} 元")

    # ---- 财务基本面 ----
    income = cli.statements.income(SYMBOL, years=3)
    print(f"利润表（近 3 期）：{len(income)} 行科目")

    pe = cli.indicator.get(SYMBOL, "$PE_TTM_LAST")
    roe = cli.indicator.get(SYMBOL, "$ROE_TTM_LAST")
    print(f"PE(TTM)={pe}  ROE(TTM)={roe:.2%}" if roe is not None else f"PE(TTM)={pe}  ROE(TTM)=—")

    # ---- 信息披露 ----
    notices = cli.notice.list(SYMBOL, window="3m", limit=3)
    print(f"近 3 个月公告（前 3 条）：")
    for n in notices or []:
        print(f"  {n.get('date', '')}  {str(n.get('title', ''))[:40]}")

    div = cli.dividend.last(SYMBOL)
    if div:
        print(f"最近一次分红：除权 {div.get('ex_div')}  DPS {div.get('dps')}  "
              f"总额 {div.get('total')}")

    # ---- 参考数据 ----
    profile = cli.info.profile(SYMBOL)
    print(f"{profile.get('name')} · {profile.get('industry')} · 上市 {profile.get('listing_date')}")

    # ---- 批量取数：真实 Client 是全市场；demo 是 10 只演示宇宙 ----
    codes = [r["symbol"] for r in cli.stocks.list()]
    scope = "演示宇宙" if demo else "全市场"
    res = cli.batch_all("kline.snapshot", codes)
    print(f"{scope} {len(res.results)} 家：{res.requests} 次请求"
          f"（逐票需 {len(codes)} 次；免费档限额 500 次/小时）")
    # 逐批处理（长任务边取边落盘）：for part in cli.batch_iter("kline.snapshot", codes): ...

    # 进阶：DataFrame 见 examples/08_pandas_analysis.py；底层函数通用入口：
    cli.call("kline.query_bars", sym=SYMBOL, limit=5)


if __name__ == "__main__":
    try:
        main(demo="--demo" in sys.argv)
    except wmshare.WmshareError as e:
        # 401/403/429 等会在这里直接显示 AppID 申请步骤，而不是裸 traceback。
        print(f"取数失败：{e}")
        raise SystemExit(1)
