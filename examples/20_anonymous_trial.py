"""匿名试用：零配置拿到真实数据（免注册，一次性额度）。

前提：能访问 api.winmale.com（服务端已开启匿名试用）
运行：python examples/20_anonymous_trial.py
学到：from_env() 的自动匿名回落、Client.anonymous() 显式申领、匿名额度边界
文档：README「零凭证先试」；docs/GUIDE.md（配置凭证）
"""
from __future__ import annotations

from wmshare import Client
from wmshare.errors import AuthError


def main(cli: Client | None = None) -> None:
    if cli is None:
        # from_env() 就是免注册入口：无凭据时 SDK 自动领取匿名试用额度；
        # 本地已有匿名凭据则直接复用，不再消耗当日发放名额。
        try:
            cli = Client.from_env()
        except AuthError as exc:
            print(f"匿名试用不可用：{exc}")
            print("请到 https://open.winmale.com 注册免费账号获取凭据。")
            return

    source = "匿名试用" if getattr(cli, "anon_credentials_path", None) else "付费凭据"
    print(f"客户端已就绪（{source}；client_id={cli.client_id}）")

    # 匿名与付费走完全相同的接口，只是额度是一次性的。
    bar = cli.kline.last("600519")
    print(f"600519 最新收盘 {bar.get('close')}")

    dy = cli.dividend.yield_ttm("600519")
    print(f"股息率 TTM {dy:.2%}")

    print(
        "\n注意：匿名额度为该应用的一次性配额（用完即止，服务端不周补满）。\n"
        "需要长期稳定额度，请注册 open.winmale.com 免费账号后配置凭证。\n"
        "不想自动匿名可设 WMSHARE_DISABLE_ANON=1（恢复报错引导）。"
    )


if __name__ == "__main__":
    main()
