"""全市场代码池 → 行业成分 → 批量取数：绕开 429 的一条龙完整链路。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；；`--demo` 用随包演示数据零凭证试跑
      本示例对全市场遍历两遍（batch_all + batch_iter），约消耗 25 次请求、十几秒
运行：python examples/07_stocks_industry_batch.py
学到：stocks.list/industries/industry_members；batch_all/batch_iter/call_batch 三入口分工
文档：docs/GUIDE.md（全市场与行业、批量取数）

可选环境变量：
    WMSHARE_MARKET=cn|hk|us   # 缺省 cn（港/美同样出全表；美股行业目录树暂缺）
    BANK_HINT=银行            # 行业名或行业代码（如 S48 / industry.S48）
"""
import os

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

    # ---- 1) 证券列表（真实 Client 全市场；demo 为演示宇宙） ----
    rows = cli.stocks.list()
    scope = "演示宇宙" if demo else "全市场"
    print(f"{scope}共 {len(rows)} 家（字段：{sorted(rows[0].keys())}）")

    # ---- 2) 行业目录 + 行业成分（中文名/代码皆可） ----
    hint = os.environ.get("BANK_HINT", "银行")
    l1 = cli.stocks.industries(1)
    print(f"一级行业 {len(l1)} 个，如："
          + "、".join(f"{r['symbol']} {r['name']}" for r in l1[:5]) + " …")
    try:
        members = cli.stocks.industry_members(hint)
        print(f"「{hint}」成分 {len(members)} 家，前 5 家：")
        for r in members[:5]:
            print(f"  {r['symbol']}  {r['name']}  {r.get('industry_name', '')}"
                  f"  上市 {r.get('listed') or '—'}")
    except wmshare.WmshareError as e:
        # 未命中/多候选时错误消息会列出候选行业；改用候选里的代码重试即可
        print(f"行业解析失败：{e}")
        return

    # ---- 3) 批量取数：真实全市场分批；demo 是演示宇宙一次批量 ----
    all_codes = [r["symbol"] for r in rows]
    res = cli.batch_all("kline.snapshot", all_codes)
    naive = len(all_codes)
    print(f"{scope} {len(res.results)} 家：批量 {res.requests} 次请求"
          f"（逐票需 {naive} 次，免费档 500 次/小时 → 省 {naive // max(res.requests, 1)} 倍配额）")
    if res.errors:
        print(f"失败批 {len(res.errors)}：{list(res.errors)[:3]}")

    # ---- 4) 逐批：长任务边取边处理（此处只打印批大小，实际可 to_df().to_parquet） ----
    for i, part in enumerate(cli.batch_iter("kline.snapshot", all_codes), 1):
        print(f"  第 {i} 批 {len(part.results)} 家", end="\r" if i % 3 else "\n")
    print()

    # ---- 5) 行业维度聚合（单批 ≤500 也可直接用 call_batch） ----
    codes = [r["symbol"] for r in members[: min(500, len(members))]]
    one = cli.call_batch("kline.snapshot", codes)
    df = one.to_df()  # 需要 pandas（pip install "wmshare[dataframe]"）
    print(f"「{hint}」{len(df)} 行快照（symbol 列在前）：")
    print(df.head().to_string(index=False))


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
