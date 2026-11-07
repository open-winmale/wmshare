"""可转债估值口径：双低、债性分类、税后到期收益率。

口径面对的三类数据缺口（2026-11 上游实测）：

* ``redeemValue`` 已由上游给出（面值的百分比数值，110 = 110 元），覆盖在标债
  88.6%；早期版本用正则从 ``couponExplain`` 文本抠「到期赎回…元」，覆盖率只有
  7%，把绝大多数债的赎回价当成面值 100，YTM 系统性偏低（220 只可比样本平均
  差 4.11pp，榜首美锦转债 3.81% → 16.79%）。
* ``couponIr`` 是**当年票息**不是恒定票息（按剩余年限分组中位数：剩 0–1 年
  2.00%、2 年 1.80%、3 年 1.50%、4 年 0.60%、5–6 年 0.20%）。把 6 年期的低
  票息当成全期票息，会再压低一截收益。
* ``couponExplain`` 里有完整分年票息表（覆盖率 87.9%），是逐笔现金流建模的
  依据；解析不到时退回「恒定票息」近似。

因此本模块给两个口径，都返回，让调用方自己选：

``ytm_after_tax``  逐笔现金流 IRR：按分年票息表 + 真实赎回价贴现，二分求根。
                   缺分年表时按当年票息恒定近似。
``ytm_floor``      下限口径：赎回价按面值 100、票息按当年票息恒定、单利年化。
                   真值恒 ≥ 此下限（赎回价 ≥ 面值），数学严格但会低估。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

__all__ = [
    "COUPON_TAX_RATE",
    "coupon_schedule",
    "double_low",
    "nature_class",
    "premium_pct",
    "redeem_value",
    "remaining_years",
    "ytm_after_tax",
    "ytm_floor",
]

#: 个人投资者利息税税率（利息部分按 20% 计，赎回价部分不计）
COUPON_TAX_RATE = 0.20

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_RE_COUPON = re.compile(r"第([一二三四五六七八九十]+)年\s*(\d+(?:\.\d+)?)\s*%")
_RE_REDEEM = re.compile(r"到期赎回[^。；]*?(\d{2,3}(?:\.\d+)?)\s*元")


def remaining_years(expire_date: str | None, as_of: str | None) -> float | None:
    """剩余年限（自然日 / 365）。任一日期缺失返回 None。"""
    from datetime import date, datetime

    def _d(s: str | None) -> date | None:
        if not s:
            return None
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    a, b = _d(as_of), _d(expire_date)
    if a is None or b is None:
        return None
    return (b - a).days / 365.0


def coupon_schedule(explain: str | None) -> list[float]:
    """从 ``couponExplain`` 解析分年票息表，返回百分比数值列表（升序年序）。

    ``"第一年 0.20%、第二年 0.40%……"`` → ``[0.2, 0.4, ...]``。解析不到返回空
    列表（调用方退回恒定票息近似）。只认连续从「第一年」开始的年份，缺段即放弃
    ——半张表比没有表更容易算出错数。
    """
    if not explain:
        return []
    found: dict[int, float] = {}
    for m in _RE_COUPON.finditer(str(explain)):
        raw = m.group(1)
        year = _CN_NUM.get(raw[0]) if len(raw) == 1 else None
        if year is None and raw.startswith("十"):
            tail = _CN_NUM.get(raw[1:], 0) if len(raw) > 1 else 0
            year = 10 + tail
        if year is None:
            continue
        found[year] = float(m.group(2))
    if not found or 1 not in found:
        return []
    out: list[float] = []
    year = 1
    while year in found:
        out.append(found[year])
        year += 1
    return out


def redeem_value(row: dict) -> float | None:
    """到期赎回价（元）。优先上游 ``redeemValue``，退回文本解析，最后 None。

    上游字段语义是「面值的百分比数值」：110 → 110 元。越界值（<100 或 >200）
    视为脏数据丢弃，交给调用方按面值 100 兜底。
    """
    rv = row.get("redeemValue")
    if isinstance(rv, (int, float)) and not isinstance(rv, bool) and 100 <= float(rv) <= 200:
        return float(rv)
    m = _RE_REDEEM.search(str(row.get("couponExplain") or ""))
    if m:
        v = float(m.group(1))
        if 100 <= v <= 200:
            return v
    return None


def premium_pct(row: dict) -> float | None:
    """转股溢价率（%）。SDK 已把上游百分数换成小数，故 ×100 展示。

    负值是有效状态（折价债），不吞。
    """
    v = row.get("premiumRatio")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) * 100
    return None


def double_low(row: dict) -> float | None:
    """双低 = 价格 + 转股溢价率×100（即溢价率的百分数）。

    价格与溢价率任一缺失返回 None——已退出合约上游不给溢价率，不能当成 0
    参与排序（那会让死债排到榜首）。
    """
    px = row.get("bondPrice")
    prem = row.get("premiumRatio")
    if not _num(px) or not _num(prem):
        return None
    return round(_f(px) + _f(prem) * 100, 3)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _f(v: Any) -> float:
    """把已过门（_num）的取值转 float；mypy 不认 _num 的类型收窄，故集中在此。"""
    return float(v)


def _irr(price: float, flows: list[tuple[float, float]]) -> float | None:
    """二分求到期收益率：price = Σ flow_i / (1+r)^t_i。

    现金流时间为正（年）。区间 [-0.99, 10]；端点同号则返回 None（无解或数据错）。
    """
    def pv(r: float) -> float:
        return sum(amt / (1.0 + r) ** t for t, amt in flows)

    lo, hi = -0.99, 10.0
    f_lo, f_hi = pv(lo) - price, pv(hi) - price
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if pv(mid) - price > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return (lo + hi) / 2


def ytm_after_tax(row: dict, as_of: str, *, tax: float = COUPON_TAX_RATE) -> dict:
    """税后到期收益率（逐笔现金流 IRR），返回三档口径。

    返回值字段：

    ``ytm``       首选值：有分年票息表用现金流 IRR，否则用恒定票息 IRR
    ``ytm_floor`` 下限口径（赎回价按面值 100、单利年化），真值 ≥ 它
    ``basis``     ``"schedule"`` / ``"constant"`` / ``"floor"`` —— ytm 的算法来源
    ``redeem``    实际采用的赎回价（元）
    ``coupons``   分年票息表（百分比数值，可能为空）
    ``years``     剩余年限

    剩余 < 0.5 年不年化（临近到期的年化值失真且无决策意义），此时 ``ytm``
    与 ``ytm_floor`` 均为 None，但 ``redeem`` / ``years`` 仍返回。
    """
    pxv = row.get("bondPrice")
    years = remaining_years(row.get("expireDate"), as_of)
    sched = coupon_schedule(row.get("couponExplain"))
    redeem = redeem_value(row)
    out: dict[str, Any] = {"ytm": None, "ytm_floor": None, "basis": None,
           "redeem": redeem, "coupons": sched, "years": years}
    if not _num(pxv) or _f(pxv) <= 0 or years is None:
        return out

    floor = ytm_floor(_f(pxv), row.get("couponIr"), years, tax=tax)
    out["ytm_floor"] = floor
    if years < 0.5:
        return out

    rv = redeem if redeem is not None else 100.0
    # 恒定票息近似：票息用当年票息，赎回价用真实值
    cur = row.get("couponIr")
    if _num(cur) and _f(cur) > 0:
        n = max(1, int(years) if abs(years - round(years)) < 1e-9 else int(years) + 1)
        # couponIr 是小数口径（0.02 = 2%），乘面值 100 得每年票息（元）
        coupon_yuan = 100.0 * _f(cur) * (1 - tax)
        constant: list[tuple[float, float]] = [(float(t), coupon_yuan) for t in range(1, n)]
        constant.append((years, rv + coupon_yuan))
        base = _irr(_f(pxv), constant)
    else:
        base = None

    if len(sched) >= 2:
        total_years = len(sched)
        n = max(1, min(total_years, int(years) if abs(years - round(years)) < 1e-9
                       else int(years) + 1))
        start = max(0, total_years - n)
        rates = sched[start:total_years]
        times = [years - (len(rates) - 1 - i) for i in range(len(rates))]
        flows: list[tuple[float, float]] = [(float(t), 100.0 * r / 100.0 * (1 - tax))
                                           for t, r in zip(times, rates[:-1])]
        flows.append((years, rv + 100.0 * rates[-1] / 100.0 * (1 - tax)))
        sched_irr = _irr(_f(pxv), flows)
        if sched_irr is not None:
            out.update(ytm=sched_irr, basis="schedule")
            return out

    if base is not None:
        out.update(ytm=base, basis="constant")
    elif floor is not None:
        out.update(ytm=floor, basis="floor")
    return out


def ytm_floor(price: float, coupon_ir: float | None, years: float,
              *, tax: float = COUPON_TAX_RATE, redemption: float | None = None) -> float | None:
    """简单年化收益（下限口径）：``(赎回价 + 票息合计 − 价格) / 价格 / 年限``。

    赎回价缺省按面值 100 —— 真实赎回价恒 ≥ 面值，故真实收益 ≥ 本值，是严格
    下限；票息按 ``couponIr`` 恒定（忽略分年递进）。剩余 < 0.5 年返回 None。
    """
    if coupon_ir is None or not price or years is None or years < 0.5:
        return None
    rv = redemption if redemption is not None else 100.0
    coupons = years * float(coupon_ir) * 100.0 * (1 - tax)
    return (rv + coupons - price) / price / years


def nature_class(price: float, premium: float, ytm: float | None) -> str:
    """债性三分类：偏债（税后收益为正）/ 偏股（高价低溢价）/ 平衡。"""
    if ytm is not None and ytm > 0:
        return "偏债"
    if price >= 130 and premium <= 15:
        return "偏股"
    return "平衡"
