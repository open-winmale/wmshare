"""历史涨跌停价规则引擎（纯函数，不触网）。

口径（2026-11-24 live 实测，见 ``tests/test_live.py::test_limit_price_history_*``）：

* 主板 ST 5%：2003-2018 年 172 个涨跌停样本全部命中 5% 档、10% 档 0 命中；
  2019-2025 年样本仍 5%（max |pct| ≤5.08%）；**2026-05-06 起主板 ST 改为
  10%**（2026 年样本 max 10.59%、10% 档命中；603021/600340 的 *ST 段正好从
  2026-05-06 起）。创业板 2020-08-24 后 ST 仍 20%（样本命中 20% 档）。
  ST 判定 = 简称含 ``ST``（覆盖 ST/*ST/SST/S*ST）**或以 ``*`` 开头**
  （``*欣泰``/``*金亚`` 这类历史风险警示简称不含 ST 子串，实测漏判）。
* 除权参考价：库内 ``percent``/``chg`` 均相对**未调整**前收盘（600519
  2024-06-19 除息 30.876 元，``close/(1+percent)`` 得 1521.5 而非交易所
  参考价 1490.62）。用后复权/不复权 close 比值 ``f`` 还原：
  ``pre_close_t = prev_nr_close × f_{t-1} / f_t``（实测 1490.616，到分一致）。
  后复权缺失时回退 ``close/(1+percent)``（非除权日等价）。

本模块只做规则计算；取数、简称段、上市首根判定由 ``api.StocksApi`` 负责。
"""
from __future__ import annotations

import math
from bisect import bisect_right
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Sequence

# 制度日期（交易所规则切换日）
MAIN_LIMIT_START = "1996-12-16"   # 沪深主板统一 10% 涨跌幅
ST_10PCT_START = "2026-05-06"     # 主板 ST 涨跌幅 5% → 10%（2026 年实测切换日）
GEM_REFORM_START = "2020-08-24"   # 创业板注册制改革：20%
BSE_START = "2020-07-27"          # 精选层开市 30%（北交所 2021-11-15 沿用）
MAIN_REG_IPO_START = "2023-04-10"  # 主板注册制首批：上市前 5 日无涨跌幅

_EPS = 1e-9
_FAR = "9999-12-31"


def cent(value: Any) -> float | None:
    """四舍五入到分（ROUND_HALF_UP）；``None``/非有限值返回 ``None``。

    与快照 ``ROUND(x, 2)`` 同口径，``+1e-9`` 复刻上游浮点补偿。
    """
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return float(Decimal(repr(x + _EPS)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def board_of(symbol: str) -> str:
    """6 位 A 股代码 → ``main``/``gem``/``star``/``bse``；非 6 位返回空串。"""
    s = str(symbol or "").strip()
    if len(s) != 6 or not s.isdigit():
        return ""
    p2 = s[:2]
    if p2 == "30":
        return "gem"
    if p2 == "68":
        return "star"
    if p2 in ("43", "83", "87", "88", "92"):
        return "bse"
    return "main"


def is_st_name(name: str) -> bool:
    """简称是否风险警示（含 ST 或以 ``*`` 开头）。"""
    n = str(name or "").strip().upper()
    return "ST" in n or n.startswith("*")


def band_at(symbol: str, day: str, is_st: bool = False) -> tuple[float | None, str]:
    """按板块+制度日期+ST 返回 ``(band, rule)``；``band=None`` 表示当日无涨跌幅限制。"""
    bd = board_of(symbol)
    d = str(day or "")[:10]
    if bd == "gem":
        if d >= GEM_REFORM_START:
            return 0.20, "gem20"
        return (0.05, "gem5") if is_st else (0.10, "gem10")
    if bd == "star":
        return 0.20, "star20"
    if bd == "bse":
        if d < BSE_START:
            return None, "unbounded"
        return 0.30, "bse30"
    if bd == "main":
        if d < MAIN_LIMIT_START:
            return None, "unbounded"
        if is_st and d < ST_10PCT_START:
            return 0.05, "main5"
        return 0.10, "main10"
    return None, "unbounded"


def ipo_len(symbol: str, listing_day: str) -> int:
    """上市无涨跌幅窗口的交易日数（旧制首日 44% 不建模，统一按首日无限制标注）。"""
    bd = board_of(symbol)
    d = str(listing_day or "")[:10]
    if bd == "star":
        return 5
    if bd == "gem":
        return 5 if d >= GEM_REFORM_START else 1
    if bd == "main":
        return 5 if d >= MAIN_REG_IPO_START else 1
    return 1


def merge_bars(nr_rows: Iterable[Mapping[str, Any]],
               hfq_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """不复权行 + 后复权 close → 带 ``factor``（hfq/nr）的升序行。

    ``factor`` 缺失（后复权档无该日）时为 ``None``，``build_rows`` 回退
    ``close/(1+percent)``。
    """
    hfq: dict[str, float] = {}
    for r in hfq_rows or []:
        d = str(r.get("date") or "")[:10]
        c = r.get("close")
        if d and c is not None:
            try:
                hfq[d] = float(c)
            except (TypeError, ValueError):
                continue
    out: list[dict[str, Any]] = []
    for r in nr_rows or []:
        d = str(r.get("date") or "")[:10]
        if not d:
            continue
        raw_close = r.get("close")
        try:
            close = float(raw_close) if raw_close is not None else None
        except (TypeError, ValueError):
            close = None
        factor = None
        if close and close > 0 and d in hfq and hfq[d] > 0:
            factor = hfq[d] / close
        out.append({
            "date": d,
            "close": close,
            "high": _float_or_none(r.get("high")),
            "low": _float_or_none(r.get("low")),
            "percent": _float_or_none(r.get("percent")),
            "factor": factor,
        })
    out.sort(key=lambda x: x["date"])
    return out


def st_segments(name_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """简称变更行 → 连续段 ``[{name,start,end,is_st}]``（按 start 升序）。"""
    segs: list[dict[str, Any]] = []
    for r in name_rows or []:
        start = str(r.get("start_date") or "")[:10]
        if not start:
            continue
        name = str(r.get("name") or "")
        segs.append({
            "name": name,
            "start": start,
            "end": str(r.get("end_date") or "")[:10] or _FAR,
            "is_st": is_st_name(name),
        })
    segs.sort(key=lambda x: x["start"])
    return segs


def _segment_at(segments: Sequence[Mapping[str, Any]], starts: Sequence[str],
                day: str) -> Mapping[str, Any] | None:
    idx = bisect_right(starts, day) - 1
    if idx < 0:
        return None
    seg = segments[idx]
    if day > str(seg.get("end") or _FAR):
        return None
    return seg


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def build_rows(symbol: str, bars: Sequence[Mapping[str, Any]],
               segments: Sequence[Mapping[str, Any]],
               first_is_listing: bool = False) -> list[dict[str, Any]]:
    """逐日生成涨跌停价行（date 升序）。

    ``bars`` 需含 ``date/close/high/low/percent/factor``（``merge_bars`` 输出）；
    ``segments`` 为 ``st_segments`` 输出；``first_is_listing`` 表示首根为上市首根。
    """
    if not bars:
        return []
    ipo_n = ipo_len(symbol, bars[0]["date"]) if first_is_listing else 0
    starts = [str(s["start"]) for s in segments]
    rows: list[dict[str, Any]] = []
    for i, b in enumerate(bars):
        day = str(b["date"])[:10]
        close = b.get("close")
        pct = b.get("percent")
        factor = b.get("factor")
        seg = _segment_at(segments, starts, day)
        is_st = bool(seg.get("is_st")) if seg else False
        name = str(seg.get("name") or "") if seg else ""
        band, rule = band_at(symbol, day, is_st)

        basis = None
        pct_basis = None
        if close and close > 0 and pct is not None and 1 + pct > 0.01:
            pct_basis = cent(close / (1 + pct))
        # 因子比值跳变（>0.01%）才视为除权日：hfq/nr 因子有 ~1e-6 浮点噪声，
        # 非除权日直接用比值会把 192.23 算成 192.22（±1 分），故平时用
        # close/(1+percent)（与当日快照同口径），仅在除权日切到因子还原。
        ratio = None
        if i > 0 and factor and bars[i - 1].get("factor"):
            try:
                ratio = float(factor) / float(bars[i - 1]["factor"])
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = None
        if ratio is not None and abs(ratio - 1) > 1e-4:
            try:
                basis = cent(float(bars[i - 1]["close"]) / ratio)
            except (TypeError, ValueError, ZeroDivisionError):
                basis = None
        if basis is None:
            basis = pct_basis

        up = dn = None
        if ipo_n and i < ipo_n:
            rule = "ipo"
            basis = None
        elif close is None or close <= 0 or pct is None or 1 + pct <= 0.01 or basis is None:
            rule = "no_price"
            basis = None
        elif band is None:
            rule = "unbounded"
            basis = None
        elif abs(pct) > band + 0.002:
            rule = "unbounded"
            basis = None
        else:
            up = cent(basis * (1 + band))
            dn = cent(basis * (1 - band))

        rows.append({
            "date": day,
            "name": name,
            "close": close,
            "high": b.get("high"),
            "low": b.get("low"),
            "percent": pct,
            "basis": basis,
            "limit_up": up,
            "limit_down": dn,
            "band": band,
            "rule": rule,
            "is_st": is_st,
        })
    return rows
