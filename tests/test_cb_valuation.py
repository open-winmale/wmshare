"""cb.valuation 口径测试：税后 YTM、分年票息、赎回价、债性分类。

这些断言的数字都能手算复核，故意写成"算得出来的期望值"而不是快照值——
口径一旦被改动，测试要能说清错在哪一步。
"""
from __future__ import annotations

import pytest

from wmshare.cb import valuation as V


def test_coupon_schedule_parses_yearly_table():
    explain = ("第一年 0.30%、第二年 0.40%、第三年 0.80%、第四年 1.60%、"
               "第五年 2.50%、第六年 3.00%")
    # 返回的是「百分比数值」（0.3 表示 0.30%），与 couponExplain 原文同单位
    assert V.coupon_schedule(explain) == [0.3, 0.4, 0.8, 1.6, 2.5, 3.0]


def test_coupon_schedule_rejects_partial_table():
    """只给后半段（从第三年起）无法对齐剩余年限，必须整体放弃。"""
    assert V.coupon_schedule("第三年 1.00%、第四年 1.50%") == []
    assert V.coupon_schedule("") == []
    assert V.coupon_schedule(None) == []


def test_coupon_schedule_stops_at_break():
    """缺一段即停：第一、二年有、第三年缺，只认前两年。"""
    assert V.coupon_schedule("第一年 0.20%、第二年 0.40%、第四年 1.00%") == [0.2, 0.4]


@pytest.mark.parametrize("row,expected", [
    ({"redeemValue": 110}, 110.0),
    ({"redeemValue": 0}, None),          # 0 不是有效赎回价
    ({"redeemValue": 500}, None),        # 超出合理区间，视为脏值
    ({"couponExplain": "到期赎回价为 112 元"}, 112.0),
    ({"couponExplain": "到期赎回价为面值的 108%"}, None),  # 百分比口径不当元用
    ({}, None),
])
def test_redeem_value(row, expected):
    assert V.redeem_value(row) == expected


def test_remaining_years_and_floor():
    assert V.remaining_years("2028-04-20", "2026-11-06") == pytest.approx(1.45, abs=0.01)
    assert V.remaining_years("", "2026-11-06") is None
    assert V.remaining_years("2026-11-06", "2026-11-06") == 0.0


def test_ytm_floor_matches_hand_calc():
    """下限口径：面值 100 + 当期票息×(1-20%)×年数。"""
    y = V.ytm_floor(97.5, 0.025, 1.45)
    flows_cash = 100 + 1.45 * 0.025 * 100 * 0.8
    assert y == pytest.approx((flows_cash - 97.5) / 97.5 / 1.45, abs=1e-9)


def test_ytm_after_tax_uses_coupon_table_and_redeem_value():
    """美锦转债实测：分年票息表 + 赎回价 118 → 税后 17% 量级。"""
    row = {
        "bondPrice": 97.5, "couponIr": 0.025, "redeemValue": 118,
        "expireDate": "2028-04-20",
        "couponExplain": ("第一年 0.30%、第二年 0.40%、第三年 0.80%、"
                          "第四年 1.60%、第五年 2.50%、第六年 3.00%"),
    }
    y = V.ytm_after_tax(row, "2026-11-06")
    assert y["basis"] == "schedule"
    assert y["redeem"] == 118
    assert 0.15 < y["ytm"] < 0.19
    assert y["ytm_floor"] is not None and 0.0 < y["ytm_floor"] < 0.06


def test_ytm_after_tax_falls_back_to_constant_coupon():
    row = {"bondPrice": 100.0, "couponIr": 0.02, "redeemValue": 110,
           "expireDate": "2028-11-06", "couponExplain": ""}
    y = V.ytm_after_tax(row, "2026-11-06")
    assert y["basis"] == "constant"
    # 100 买、两年后 110 赎回、每年 2% 票息（税后 1.6%）→ 约 6.8%
    assert y["ytm"] == pytest.approx(0.068, abs=0.005)


def test_ytm_after_tax_returns_none_for_short_remainder():
    """剩余不足 0.5 年不年化：收益是确定的一次性兑付，年化会放大成假高收益。"""
    row = {"bondPrice": 99.0, "couponIr": 0.02, "redeemValue": 108,
           "expireDate": "2027-01-01", "couponExplain": "第一年 2.00%"}
    y = V.ytm_after_tax(row, "2026-11-06")
    assert y["ytm"] is None and y["basis"] is None
    assert y["years"] is not None and y["years"] < 0.5


def test_nature_class_thresholds():
    assert V.nature_class(100.0, 5.0, 0.02) == "偏债"      # 有正收益 → 偏债优先
    assert V.nature_class(135.0, 10.0, -0.05) == "偏股"
    assert V.nature_class(135.0, 20.0, -0.05) == "平衡"     # 溢价高，不是偏股
    assert V.nature_class(120.0, 30.0, None) == "平衡"


def test_double_low_and_premium_are_percent_numbers():
    """面板的 premiumRatio 已被 units 层换成小数（0.0442），展示时 ×100。"""
    row = {"bondPrice": 97.5, "premiumRatio": 0.0442}
    assert V.premium_pct(row) == pytest.approx(4.42)
    assert V.double_low(row) == pytest.approx(101.92)
    assert V.double_low({"bondPrice": None, "premiumRatio": 1.0}) is None


# ---------------- v4 新增：债底 / 税前 YTM / 波动率 / 换手率 ----------------
# 期望值同样手算：现金流贴现有封闭式，波动率用一个两点的退化案例。

_CURVE = {1.0: 0.02, 3.0: 0.02, 5.0: 0.02, 7.0: 0.02, 10.0: 0.02}
_ROW = {
    "bondPrice": 100.0, "couponIr": 0.02, "redeemValue": 100.0,
    "expireDate": "2028-11-06",
    "couponExplain": "第一年 2.00%、第二年 2.00%、第三年 2.00%",
}


def test_ytm_pretax_is_higher_than_after_tax():
    """税前只多了利息税那部分，方向与幅度都必须对。"""
    after = V.ytm_after_tax(_ROW, "2026-11-06")
    pre = V.ytm_pretax(_ROW, "2026-11-06")
    assert pre["ytm"] > after["ytm"]
    # 还剩 3 笔票息（含 1 天后到期那笔），税 20% → 总现金流少 1.2 元 / 约 2 年
    # ≈ 0.6pp；这就是税前与税后的真实差距，不是算法不同
    assert 0 < (pre["ytm"] - after["ytm"]) * 100 < 1.0
    assert (pre["ytm"] - after["ytm"]) * 100 == pytest.approx(0.62, abs=0.05)


def test_pure_bond_value_matches_closed_form():
    """与实现无关的封闭式复算：按实际天数折现，不依赖内部切片逻辑。

    到期日在两年后、但离下一次付息只差 1 天，所以仍有 3 笔票息；这也是
    「债底略高于面值」的真实原因，不是算错。
    """
    from datetime import date

    years = (date(2028, 11, 6).toordinal() - date(2026, 11, 6).toordinal()) / 365.0
    times = [years - 2, years - 1, years]
    expect = sum(2.0 / 1.02 ** t for t in times[:2]) + 102.0 / 1.02 ** times[2]
    pbv = V.pure_bond_value(_ROW, "2026-11-06", _CURVE)
    assert pbv["basis"] == "schedule"
    assert pbv["value"] == pytest.approx(expect, abs=0.01)
    assert pbv["redeem"] == 100.0


def test_pure_bond_value_uses_gross_coupons():
    """债底不扣利息税：票息 2% 全额入现金流，税后口径会明显低于面值。"""
    gross = V.pure_bond_value(_ROW, "2026-11-06", _CURVE)["value"]
    assert gross > 99.9            # 全额票息 + 面值赎回，贴现率等于票息 → 约等于面值
    lowered = V.pure_bond_value({**_ROW, "redeemValue": 100.0}, "2026-11-06",
                                {k: 0.05 for k in _CURVE})["value"]
    assert lowered < gross          # 贴现率上行 → 债底下行


def test_pure_bond_value_none_when_no_cashflow():
    """剩余年限已过或票息与当年票息都缺时，不能拿面值 100 假装债底。"""
    assert V.pure_bond_value({**_ROW, "expireDate": "2026-01-01"},
                             "2026-11-06", _CURVE) is None
    assert V.pure_bond_value({"expireDate": "2029-01-01"}, "2026-11-06", _CURVE) is None


@pytest.mark.parametrize("years,expected", [
    (0.4, 0.02),      # 期限短于最短档 → 平推最短档
    (2.0, 0.025),     # 1 年 2.0% 与 3 年 3.0% 的中点
    (99.0, 0.04),     # 超长 → 平推最长档，不外推斜率
])
def test_interp_curve_flat_ends(years, expected):
    curve = {1.0: 0.02, 3.0: 0.03, 10.0: 0.04}
    assert V.interp_curve(curve, years) == pytest.approx(expected)
    assert V.interp_curve({}, years) is None


def test_annualized_vol_needs_full_window():
    closes = [100.0 + i for i in range(20)]
    assert V.annualized_vol(closes) is None        # 20 个点只能算 19 个收益
    closes.append(120.0)
    v = V.annualized_vol(closes)
    assert v is not None and v > 0


def test_annualized_vol_scales_with_dispersion():
    calm = [100, 101] * 10 + [101]
    wild = [100, 110] * 10 + [110]
    assert V.annualized_vol(calm) < V.annualized_vol(wild)


def test_turnover_uses_market_value_not_par_size():
    """分母是转债流通市值（剩余规模×价格/100），不是面值规模。

    按面值算，5 亿规模价格 100 的债：1 亿成交 → 20%；同样规模价格 500 的债仍是
    20%，而市值口径只有 4%——高价债按面值算会虚高 5 倍，看起来像被爆炒。
    """
    assert V.turnover_pct(1.0e8, 5.0e8, 100.0) == pytest.approx(20.0)
    assert V.turnover_pct(1.0e8, 5.0e8, 500.0) == pytest.approx(4.0)
    # 返回值统一保留两位小数，期望值同步 round
    assert V.turnover_pct(1.0e8, 5.0e8, 133.0) == pytest.approx(
        round(1e8 / (5e8 * 1.33) * 100, 2))
    # 任一输入缺失都不能当成 0 或面值
    assert V.turnover_pct(1.0e8, 0, 100.0) is None
    assert V.turnover_pct(None, 5.0e8, 100.0) is None
    assert V.turnover_pct(1.0e8, 5.0e8, None) is None


def test_turnover_matches_third_party_row():
    """用第三方列表那一行的原始数反推，校验口径（广核：3.078亿 ÷(46.514亿×1.33)=4.98%）。"""
    assert V.turnover_pct(3.078e8, 46.514e8, 133.0) == pytest.approx(4.98, abs=0.01)
