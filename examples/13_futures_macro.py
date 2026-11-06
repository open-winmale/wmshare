"""期货主力连续与宏观时序：期货指标码（$FUT_CLOSE 等 FUT 前缀码）与 macro 域两个新数据面。

前提：凭证必填（export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...）；`--demo` 用随包演示数据零凭证试跑
运行：python examples/12_futures_macro.py
学到：期货指标码姿势（fut_symbol 换合约/外盘 global.*）、macro 时序/as-of/原生频率、中债收益率小数口径
文档：docs/API.md（期货、宏观两章）；docs/GUIDE.md §6.1
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

    # ---- ① 期货主力连续：FUT 前缀指标码（symbol 传任意 A 股代码绑定期间上下文） ----
    close = cli.indicator.get("600519", "$FUT_CLOSE")   # 缺省合约 cn.SR.ZCE（郑糖）
    print(f"郑糖主力收盘 = {close}（价=报价单位随品种、量=手、额=万元，原生口径）")
    wti = cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="global.CL")
    print(f"外盘 WTI = {wti}（global.* 前缀为外盘 V2 键）")
    batch = cli.indicator.metrics("600519", ["$FUT_CLOSE", "$FUT_VOLUME"],
                                  fut_symbol="cn.RB.SHF")
    print(f"螺纹钢主力 close/volume = {batch}（volume 单位=手）")

    # ---- ② 宏观时序：query 返回 {frequency, latest, series}，最新在前 ----
    cpi = cli.macro.query("$CPI", 3)
    latest = cpi["latest"]
    print(f"\n$CPI 频率={cpi['frequency']}，最新 {latest['sampling']} 期值 "
          f"{latest['value']}（价格指数点，上年同期=100）")

    # ---- ③ 宏观 as-of 与原生频率（原生口径：GDP/M2=元，勿套全库小数口径） ----
    gdp = cli.macro.asof("$GDP")
    freq = cli.macro.sampling_of("$GDP")
    print(f"$GDP 最新 = {gdp}（元 ≈ {gdp / 1e12:.1f} 万亿元），原生频率 {freq}")

    # ---- ④ 中债收益率（小数口径）与行业情报单值（披露名单精确匹配，掉榜返回 None） ----
    y10 = cli.macro.bond_curve("中债国债收益率曲线", "10年")
    print(f"中债国债 10 年 = {y10}（小数，即 {y10:.2%}）")
    print(f"新势力月交付（零跑）= {cli.macro.nev_monthly('零跑', 'sales')}（辆）")
    print(f"乘联会厂商批发（比亚迪汽车）= {cli.macro.cpca_top('比亚迪汽车', 'wholesale')}")
    print(f"手机周份额（小米）= {cli.macro.phone_share('小米', 'share')}")


if __name__ == "__main__":
    try:
        main(demo="--demo" in sys.argv)
    except wmshare.WmshareError as e:
        # 错误消息自带修复步骤（凭证/限流/参数合同），打印原文即可定位
        print(f"取数失败：{e}")
        raise SystemExit(1)
