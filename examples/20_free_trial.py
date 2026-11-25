"""免注册试用：不配置凭证、不注册，直接取真实数据。

前提：能访问 api.winmale.com（无需凭证）
运行：python examples/20_free_trial.py
学到：from_env() 的免注册回落、auth_mode 判别访问方式、免注册访问的边界与升级路径
文档：README「零凭证先试」；docs/LIMITS.md（限流与配额）；docs/GUIDE.md（配置凭证）
"""
from __future__ import annotations

from wmshare import Client
from wmshare.errors import AuthError, WmshareError


def main(cli: Client | None = None) -> None:
    if cli is None:
        # from_env() 就是免注册入口：没配置凭证时直接构造免注册客户端，不申领、
        # 不落盘任何凭据；设了 WMSHARE_DISABLE_ANON=1 则回到「缺少凭证」报错。
        try:
            cli = Client.from_env()
        except AuthError as exc:
            print(f"免注册试用不可用：{exc}")
            print("请到 https://open.winmale.com 注册免费账号并配置凭证。")
            return

    mode = getattr(cli, "auth_mode", "credentials")
    print(f"访问方式：{mode}" + ("（未配置凭证，免注册）" if mode == "public_pool" else "（自有应用凭证）"))

    # 免注册与凭证走完全相同的接口、拿到相同的数据，区别只在额度和频次怎么算。
    try:
        bar = cli.kline.last("600519")
        print(f"600519 最新收盘 {bar.get('close')}（{bar.get('date')}）")
        dy = cli.dividend.yield_ttm("600519")
        print(f"股息率 TTM {dy:.2%}")
    except WmshareError as exc:
        # 免注册访问的拒绝都是终态，SDK 不会自动重试：
        #   ip_rate_limited / ip_banned   本网络的免注册请求次数到顶 / 本网络被封禁
        #   EC_BALANCE_EXHAUSTED 等       共享的免注册额度用完
        #   pool_unavailable              服务端暂停了免注册额度
        print(f"取数被拒（{exc.code}）：{exc}")
        return

    print(
        "\n注意：免注册访问不持有任何凭据，服务端按来源网络记账——额度与频次由全体免注册用户\n"
        "共享，同一网络下多人同时使用会互相挤占。需要独立、稳定的额度，请到 open.winmale.com\n"
        "注册免费账号并配置凭证。不想自动免注册可设 WMSHARE_DISABLE_ANON=1（恢复报错引导）。"
    )


if __name__ == "__main__":
    main()
