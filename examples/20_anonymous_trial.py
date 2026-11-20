"""匿名试用：免注册拿到真实数据（一次性小配额）。

前提：能访问 api.winmale.com（服务端已开启匿名试用）
运行：python examples/20_anonymous_trial.py
学到：Client.anonymous() 的用法、匿名额度边界、何时该换成注册账号
文档：README「零凭证先试」；docs/GUIDE.md（配置凭证）
"""
from __future__ import annotations

from wmshare import Client
from wmshare.errors import AuthError


def main(cli: Client | None = None) -> None:
    if cli is None:
        try:
            cli = Client.anonymous()
        except AuthError as exc:
            print(f"匿名试用不可用：{exc}")
            print("请到 https://open.winmale.com 注册免费账号获取凭据。")
            return

    print(f"匿名客户端已就绪（client_id={cli.client_id}）")

    # 匿名与付费走完全相同的接口，只是额度是一次性的。
    bar = cli.kline.last("600519")
    print(f"600519 最新收盘 {bar.get('close')}")

    dy = cli.dividend.yield_ttm("600519")
    print(f"股息率 TTM {dy:.2%}")

    print(
        "\n注意：匿名额度为该应用的一次性小配额（50 万 EC，用完即止，不重置）。\n"
        "需要长期稳定额度，请注册 open.winmale.com 免费账号（500 次/小时、5,000 次/日）。"
    )


if __name__ == "__main__":
    main()
