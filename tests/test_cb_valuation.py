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
