"""pandas 分析：门面默认返回 DataFrame，直接做研究计算。

前提：pandas 为 2.0 硬依赖（随包安装）；凭证可选——无凭证自动免注册免费试用（需网络）
运行：python examples/08_pandas_analysis.py
学到：门面 DataFrame 默认（date 升序，无需再排序）；MA20/动量/资金流合计/分红历史表
文档：docs/GUIDE.md（pandas）
"""
import wmshare
from wmshare import Client


def main(cli=None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()
    SYMBOL = "600519"

    # ---- 日 K → DataFrame：2.0 起默认 DataFrame 且 date 升序（旧→新），直接算指标 ----
    # 1.x 需要手动 sort_values 的「降序返回」坑已移除；iloc[-1] 就是最新一根。
    df = cli.kline.bars(SYMBOL, n=120)
    df["ma20"] = df["close"].rolling(20).mean()
    df["mom_20d"] = df["close"].pct_change(20)
    last = df.iloc[-1]
    print(f"{SYMBOL}  收盘={last['close']:.2f}  MA20={last['ma20']:.2f}  "
          f"20日动量={last['mom_20d']:.2%}")
    above = bool(last["close"] > last["ma20"])
    print(f"站上 MA20：{above}")

    # ---- 资金流 → DataFrame：近 20 日主力净流入合计 ----
    mf = cli.moneyflow.bars(SYMBOL, n=20)
    print(f"近 20 日主力净流入合计：{mf['net_mf'].sum():,.0f} 元")

    # ---- 分红历史 → DataFrame：股息可持续性速览 ----
    div = cli.dividend.history(SYMBOL, limit=10)
    cols = [c for c in ("ex_div", "dps", "payout_ratio") if c in div.columns]
    print("\n近 10 次分红：")
    print(div[cols].to_string(index=False))


if __name__ == "__main__":
    main()
