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
``ytm_pretax``     同一骨架去掉利息税——只为与第三方的「到期税前收益」可比。
``ytm_floor``      下限口径：赎回价按面值 100、票息按当年票息恒定、单利年化。
                   真值恒 ≥ 此下限（赎回价 ≥ 面值），数学严格但会低估。
``pure_bond_value`` 债底：同一份现金流按传入收益率曲线贴现。票息与赎回价都不
                   扣利息税（「纯债价值」的通行定义）；曲线由调用方传入，
                   本模块不内置利率常量、不取数。
``annualized_vol`` 转债自身近 20 日年化波动率——「这只债弹不弹」的直接观测。
``turnover_pct``   换手率 = 成交额 / 转债流通市值（剩余规模×价格/100，不是面值规模）。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

__all__ = [
    "COUPON_TAX_RATE",
    "annualized_vol",
    "coupon_schedule",
    "double_low",
    "interp_curve",
    "nature_class",
    "premium_pct",
    "pure_bond_value",
    "redeem_value",
    "remaining_years",
    "turnover_pct",
    "ytm_after_tax",
    "ytm_floor",
    "ytm_pretax",
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


def _periods(years: float, available: int = 0) -> int:
    """剩余年限内的付息期数；``available`` >0 时不超过可用票息表长度。"""
    whole = int(years) if abs(years - round(years)) < 1e-9 else int(years) + 1
    n = max(1, whole)
    return min(n, available) if available else n


def _flows(row: dict, years: float, redeem: float,
           tax: float) -> tuple[list[tuple[float, float]], str | None]:
    """剩余期现金流 ``[(年, 金额)]`` 与口径来源（``schedule`` / ``constant``）。

    YTM 与纯债价值共用这一份现金流模型：两处各写一遍，改一处忘一处就会让
    「债底」和「到期收益」互相不自洽。
    """
    sched = coupon_schedule(row.get("couponExplain"))
    if len(sched) >= 2:
        n = _periods(years, len(sched))
        rates = sched[len(sched) - n:]
        times = [years - (len(rates) - 1 - i) for i in range(len(rates))]
        flows = [(float(t), 100.0 * r / 100.0 * (1 - tax)) for t, r in zip(times, rates[:-1])]
        flows.append((years, redeem + 100.0 * rates[-1] / 100.0 * (1 - tax)))
        return flows, "schedule"
    cur = row.get("couponIr")
    if _num(cur) and _f(cur) > 0:
        n = _periods(years)
        coupon_yuan = 100.0 * _f(cur) * (1 - tax)
        flows = [(float(t), coupon_yuan) for t in range(1, n)]
        flows.append((years, redeem + coupon_yuan))
        return flows, "constant"
    return [], None


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
    flows, flow_basis = _flows(row, years, rv, tax)
    if flow_basis == "schedule":
        sched_irr = _irr(_f(pxv), flows)
        if sched_irr is not None:
            out.update(ytm=sched_irr, basis="schedule")
            return out
        base = None
    elif flow_basis == "constant":
        base = _irr(_f(pxv), flows)
    else:
        base = None

    if base is not None:
        out.update(ytm=base, basis="constant")
    elif floor is not None:
        out.update(ytm=floor, basis="floor")
    return out


def ytm_pretax(row: dict, as_of: str) -> dict:
    """税前到期收益率（同一 IRR 骨架，只把利息税置 0）。

    税后是我们的对外口径；税前存在的唯一理由是**与集思录「到期税前收益」
    可比**——读者拿两个数对不上时，得能说清差的是税，不是算错。
    """
    return ytm_after_tax(row, as_of, tax=0.0)


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


def interp_curve(curve: dict[float, float], years: float) -> float | None:
    """在 ``{期限(年): 收益率(小数)}`` 上线性插值，两端平推（不外推斜率）。

    平推而不是外推：剩余 0.4 年的债用 1 年期，剩余 8 年的债用最长档。外推会
    凭斜率造出一个市场上并不存在的利率，债底就变成算出来的幻觉。
    """
    if not curve:
        return None
    pts = sorted((float(k), float(v)) for k, v in curve.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not pts:
        return None
    if years <= pts[0][0]:
        return pts[0][1]
    if years >= pts[-1][0]:
        return pts[-1][1]
    for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
        if t0 <= years <= t1:
            if t1 == t0:
                return r0
            return r0 + (r1 - r0) * (years - t0) / (t1 - t0)
    return pts[-1][1]


def pure_bond_value(row: dict, as_of: str, curve: dict[float, float], *,
                    redeem_fallback: float = 100.0) -> dict | None:
    """纯债价值（债底）：把剩余票息与赎回价按收益率曲线逐笔贴现。

    口径（写死在此，别处别再实现一遍）：

    * 现金流与 ``ytm_after_tax`` 共用 ``_flows``，**票息与赎回价都不扣利息税**
      ——这是「纯债价值」的通行定义。个人实际到手略低，与税后 YTM 并列看时
      要知道这一层差。
    * 贴现率取**外部传入的曲线**（本模块不取数，也不内置任何常量）：无评级
      输入时只能用统一曲线，评级更低的债真实债底**低于**本值。因此对外必须
      标「统一曲线贴现、自算口径」，不得宣称与任何第三方同口径。
    * 剩余年限 ≤0 或现金流建不起来时返回 None，不拿面值 100 兜底（那不是债底）。

    :returns: ``{"value", "basis", "redeem", "years", "curve_rate"}``
    """
    years = remaining_years(row.get("expireDate"), as_of)
    if years is None or years <= 0:
        return None
    redeem = redeem_value(row)
    rv = redeem if redeem is not None else redeem_fallback
    flows, basis = _flows(row, years, rv, 0.0)
    if not flows:
        return None
    pv = 0.0
    rate_first = None
    for t, amt in flows:
        r = interp_curve(curve, t)
        if r is None:
            return None
        if rate_first is None:
            rate_first = r
        pv += amt / (1.0 + r) ** t
    return {"value": round(pv, 3), "basis": basis, "redeem": round(rv, 2),
            "years": round(years, 3),
            "curve_rate": round(rate_first * 100, 3) if rate_first is not None else None}


def annualized_vol(closes: list[float], *, window: int = 20,
                   periods: int = 252) -> float | None:
    """近 ``window`` 个交易日的年化波动率（%，对数收益标准差 × √252）。

    转债价格的波动率是「这只债弹不弹」的直接观测，比拿正股波动率代跑更贴
    持有人的体验。样本不足（次新债）返回 None——不插补、不用不足的窗口硬算。
    """
    px = [float(c) for c in closes if isinstance(c, (int, float)) and c > 0]
    if len(px) < window + 1:
        return None
    seg = px[-(window + 1):]
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg))]
    if len(rets) < max(2, window // 2):
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var * periods) * 100, 2)


def turnover_pct(amount: float | None, float_size: float | None,
                 price: float | None = None) -> float | None:
    """转债换手率（%）= 当日成交额 / 转债流通市值。

    分母是**市值**（剩余规模 × 价格/100），不是面值规模：主流第三方列表均用市值
    口径，用面值会把高价债的换手率整体放大（价格 500 元的债虚高 5 倍），看起来
    像「被爆炒」，实际很正常。已用第三方列表的内部算术反推验证（成交额 ÷ 剩余
    规模 ÷ 价格 = 其换手率列）。
    """
    if not _num(amount) or not _num(float_size) or not _num(price):
        return None
    if _f(float_size) <= 0 or _f(price) <= 0:
        return None
    market_value = _f(float_size) * _f(price) / 100.0
    if market_value <= 0:
        return None
    return round(_f(amount) / market_value * 100, 2)
