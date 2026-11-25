"""可转债规则内核：在市基座、三道闸、强赎/下修状态机、条款事件日历。

纯函数，无 IO、无网络——同一套规则被 ``cb.daily``、``cb.article`` 与测试共用，
避免「话术一套规则、代码另一套」。

三道闸按序判定、命中即剔除，理由唯一（便于计数核对）：

====  ======================  ================================
闸门  理由码                  判据
====  ======================  ================================
G1    ``g1_expired``          到期日已过但仍在快照
G1    ``g1_no_price``         无有效报价
G1    ``g1_no_size``          剩余规模为 0
G2    ``g2_st``               正股为 ST / *ST / 退市整理
G3    ``g3_redeem``           已公告强赎
G3    ``g3_met15``            强赎计数已达 15/30
G3    ``g3_near_expiry``      剩余年限 < 0.5 年（持有到期为负收益）
====  ======================  ================================
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable, TypeGuard

__all__ = [
    "CALL_HITS_THRESHOLD",
    "CALENDAR_DAYS",
    "GATE_DETAIL",
    "GATE_LABEL",
    "GRAY_EXPIRY_DAYS",
    "NEAR_EXPIRY_DAYS",
    "NO_REDEEM_WINDOW_DAYS",
    "REDEEM_WINDOW_DAYS",
    "RESET_WINDOW_DAYS",
    "build_event_index",
    "calendar",
    "call_state",
    "days_between",
    "days_to_expire",
    "evaluate",
    "gate_row",
    "in_market_base",
    "is_st_name",
    "norm_event",
    "recent_events",
    "reset_state",
]

# ---- 阈值（各债条款细则可能不同，这里是市场惯例值，可由调用方覆盖）----
CALL_HITS_THRESHOLD = 15      # 「连续 30 个交易日中至少 15 日」的惯例门槛
NEAR_EXPIRY_DAYS = 182        # <0.5 年 → G3 剔除
GRAY_EXPIRY_DAYS = 365        # 0.5–1 年 → 保留入榜但灰标
REDEEM_WINDOW_DAYS = 365      # 强赎公告回溯窗
NO_REDEEM_WINDOW_DAYS = 180   # 「公告不强赎」有效期
RESET_WINDOW_DAYS = 90        # 下修事件回溯窗
CALENDAR_DAYS = 30            # 事件日历前瞻窗

_RE_ST_NAME = re.compile(r"(^|\*)ST|退")

GATE_DETAIL = {
    "g1_expired": "到期日 {d} 已过、仍在快照（未摘牌/未兑付）",
    "g1_no_price": "无有效报价",
    "g1_no_size": "剩余规模为 0（已全部转股/赎回）",
    "g2_st": "正股 {name} 为风险警示/退市整理",
    "g3_redeem": "已公告强赎（{d}）",
    "g3_met15": "已满足强赎条件 {hits}/30",
    "g3_near_expiry": "剩余 {x} 年，价格 {p} 元——持有到期为负收益",
}

GATE_LABEL = {
    "g1_expired": "G1 到期未摘牌",
    "g1_no_price": "G1 无有效报价",
    "g1_no_size": "G1 剩余规模为 0",
    "g2_st": "G2 正股 ST/退市风险",
    "g3_redeem": "G3 已公告强赎",
    "g3_met15": "G3 已满足强赎条件",
    "g3_near_expiry": "G3 剩余年限 <0.5 年",
}


def num(v: Any) -> TypeGuard[float]:
    """可用数值（排除 bool / None / 字符串 / NaN）；TypeGuard——守卫通过后可安全 float()。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def as_float(v: Any) -> float | None:
    """已过 ``num`` 门的值转 float；否则 None（mypy 不认 num 的类型收窄）。"""
    return float(v) if num(v) else None


def as_int(v: Any) -> int | None:
    return int(v) if num(v) else None


def to_date(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def days_between(d1, d2) -> int | None:
    a, b = to_date(d1), to_date(d2)
    return (b - a).days if a and b else None


def days_to_expire(row: dict, as_of: str) -> int | None:
    return days_between(as_of, row.get("expireDate"))


def is_st_name(name: str | None) -> bool:
    return bool(_RE_ST_NAME.search(str(name or "")))


def in_market_base(row: dict) -> bool:
    """在市基座：只要有溢价率即算在标。

    上游对已退出合约不给 ``premiumRatio``，所以这个判据天然剔掉退市档案行；
    严格的可交易性交给 G1，不在基座里做——否则闸门命中数无从核对。

    注意 ``outstanding`` 字段（上游新给）与这里语义不同：它判「未转股余额 > 0
    且未到期」，是发行人视角的存续性；基座是行情视角的「有没有价格」。两者
    都要用，但不要互相替代。
    """
    return num(row.get("premiumRatio"))


# ---------------- 事件规整与索引 ----------------
def norm_event(e: dict) -> dict:
    """把两类事件行（event_list 蛇形 / board 行内事件驼峰）统一成一种形状。"""
    def g(*ks):
        return next((e[k] for k in ks if e.get(k) not in (None, "")), None)

    return {
        "deal_type": g("deal_type", "dealType"),
        "bond_code": str(g("bond_code", "bondCode") or ""),
        "bond_name": g("bond_name", "bondName") or "",
        "stock_code": str(g("stock_code", "stockCode") or ""),
        "announce_date": str(g("announce_date", "announceDate") or "")[:10],
        "meeting_date": str(g("meeting_date", "meetingDate") or "")[:10],
        "redeem_qty": g("redeem_qty", "redeemQty"),
        "put_start": str(g("put_start", "putStart") or "")[:10],
        "put_end": str(g("put_end", "putEnd") or "")[:10],
        "put_price": g("put_price", "putPrice"),
        "convert_price_old": g("convert_price_old", "convertPriceOld"),
        "convert_price_new": g("convert_price_new", "convertPriceNew"),
        "title": str(g("title", "meetingTitle") or ""),
        "source_url": g("source_url", "pageUrl", "meetingUrl") or "",
    }


def build_event_index(events: Iterable[dict], base_rows: list[dict]
                      ) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """按 bondCode 归档事件，返回 ``(by_bond, stats)``。

    缺 ``bondCode`` 的公告用 ``stockCode`` 反查债券，**仅当该正股在在市集合中
    只对应一只债**时才认领。同一发行人发过多只债（全市场 90+ 组）时不猜——
    按正股聚合的转债指标串行过一次（callHits 曾按 stockCode 键控），同一类
    错误不该在事件归属上重演。

    ``board`` 行内的 ``event`` 是「该债最近一条条款事件」，也补进索引（按
    deal_type + 日期 + 标题去重）。注意它可能是与 ``resetEvent`` 不同的另一
    条公告，两者都要看。
    """
    stk_to_bonds: dict[str, list[str]] = {}
    for r in base_rows:
        stk = str(r.get("stockCode") or "")
        if stk:
            stk_to_bonds.setdefault(stk, []).append(str(r.get("bondCode") or ""))

    by_bond: dict[str, list[dict]] = {}
    stats = {"total": 0, "keyed_by_bond": 0, "keyed_by_stock": 0,
             "ambiguous_stock": 0, "unkeyed": 0}
    for raw in events:
        e = norm_event(raw)
        if not e["deal_type"]:
            continue
        stats["total"] += 1
        bc = e["bond_code"]
        if not bc:
            cands = [c for c in stk_to_bonds.get(e["stock_code"], []) if c]
            if len(cands) == 1:
                bc = cands[0]
                stats["keyed_by_stock"] += 1
            elif len(cands) > 1:
                stats["ambiguous_stock"] += 1
                continue
            else:
                stats["unkeyed"] += 1
                continue
        else:
            stats["keyed_by_bond"] += 1
        by_bond.setdefault(bc, []).append(e)

    for r in base_rows:
        for key in ("event", "resetEvent"):
            ev = r.get(key)
            if not isinstance(ev, dict):
                continue
            e = norm_event(ev)
            e["bond_code"] = str(r.get("bondCode") or "")
            bc = e["bond_code"]
            if not bc or not e["deal_type"]:
                continue
            seen = {(x["deal_type"], x["announce_date"], x["title"])
                    for x in by_bond.get(bc, [])}
            if (e["deal_type"], e["announce_date"], e["title"]) in seen:
                continue
            by_bond.setdefault(bc, []).append(e)

    for bc in by_bond:
        by_bond[bc].sort(key=lambda x: x["announce_date"], reverse=True)
    return by_bond, stats


def recent_events(by_bond: dict, bc: str, deal_types: Iterable[str],
                  as_of: str, window_days: int) -> list[dict]:
    """某债在 ``[as_of - window_days, as_of]`` 内的指定类型事件（新→旧）。"""
    out = []
    for e in by_bond.get(bc, []):
        if e["deal_type"] not in deal_types:
            continue
        dd = days_between(e["announce_date"], as_of)
        if dd is None or dd < 0 or dd > window_days:
            continue
        out.append(e)
    return out


# ---------------- 强赎状态机 ----------------
def call_state(row: dict, by_bond: dict, as_of: str) -> dict[str, Any]:
    """强赎六态：已强赎 / 强赎公告 / 已满足条件 / 公告不强赎 / 计数中 / 未触发。

    ``callHits`` 是服务端给的「正股无复权收盘 ≥ 强赎触发价的近 30 个交易日
    天数」，**只在股价已跨触发价时返回**——没有这个字段不等于计数为 0，只
    等于「还没跨线，服务端没算」。所以 ``hits=None`` 与 ``hits=0`` 要分开表达。

    「计数达标 + 有不赎回公告」两个事实会同时成立（2026-11-06 实测 28 只达标
    里 21 只有公告）。这里**不合成「已豁免」结论**：上游事件不给豁免有效期
    （公告通常写「未来 3/6 个月不赎回」，本模块不解析原文），无法判断豁免此刻
    是否仍生效。两个事实并列呈现，判断留给读者查公告原文。
    """
    bc = str(row.get("bondCode") or "")
    hits = as_int(row.get("callHits"))
    window = as_int(row.get("callWindow")) or 30

    red = recent_events(by_bond, bc, ("redeem",), as_of, REDEEM_WINDOW_DAYS)
    red_qty = [e for e in red if num(e.get("redeem_qty")) and e["redeem_qty"] > 0]
    if red_qty:
        return {"state": "已公告强赎", "key": "redeemed", "hits": hits, "window": window,
                "since": red_qty[0]["announce_date"], "days_to_15": 0, "detail": "赎回已实施"}
    if red:
        return {"state": "强赎公告", "key": "redeem_announced", "hits": hits, "window": window,
                "since": red[0]["announce_date"], "days_to_15": 0, "detail": "公告已发布"}

    nored = recent_events(by_bond, bc, ("no_redeem",), as_of, NO_REDEEM_WINDOW_DAYS)
    met = hits is not None and hits >= CALL_HITS_THRESHOLD
    waiver = ({"no_redeem_since": nored[0]["announce_date"],
               "no_redeem_days": days_between(nored[0]["announce_date"], as_of),
               "no_redeem_title": nored[0]["title"]} if nored else {})
    if met:
        tail = (f"（{waiver['no_redeem_days']} 日前公告不赎回）"
                if waiver and waiver.get("no_redeem_days") is not None else "")
        return {"state": f"已满足条件 {hits}/{window}{tail}", "key": "met15", "hits": hits,
                "window": window, "since": "", "days_to_15": 0,
                "detail": "计数已达标；另有不赎回公告，有效期需查原文", **waiver}
    if nored:
        return {"state": "公告不强赎", "key": "no_redeem", "hits": hits, "window": window,
                "since": nored[0]["announce_date"], "days_to_15": None,
                "detail": "有效期内不赎", **waiver}
    if hits is not None and hits > 0:
        return {"state": f"计数 {hits}/{window}（距 {CALL_HITS_THRESHOLD} 差 "
                         f"{CALL_HITS_THRESHOLD - hits} 日）",
                "key": "counting", "hits": hits, "window": window, "since": "",
                "days_to_15": max(0, CALL_HITS_THRESHOLD - hits), "detail": ""}
    return {"state": "未触发", "key": "idle", "hits": hits, "window": window,
            "since": "", "days_to_15": None, "detail": ""}


# ---------------- 下修状态机 ----------------
def reset_state(row: dict, by_bond: dict, as_of: str) -> dict[str, Any]:
    """下修五态：已提议·X月X日表决 / 下修提案（待表决）/ 公告不下修 / 已下修 / 无。

    下修信息取自 ``resetEvent``（仍在进行中的提议），**不是** ``event``——后者
    只保留最新一条公告，回售或转股结果会把它挤掉（123154 火星转债实证）。
    """
    bc = str(row.get("bondCode") or "")
    floor = row.get("resetFloor")
    meetings = recent_events(by_bond, bc, ("reset_proposal",), as_of, RESET_WINDOW_DAYS)
    upcoming = [e for e in meetings
                if e.get("meeting_date") and (days_between(as_of, e["meeting_date"]) or -1) >= 0]
    fv = as_float(floor)
    base = {"floor": round(fv, 3) if fv is not None else None,
            "estimate": row.get("resetEstimate"), "waive": row.get("resetWaive"),
            "meeting": str(row.get("resetMeeting") or ""),
            "family": row.get("resetFamily") or ""}
    if upcoming:
        md = to_date(upcoming[0]["meeting_date"])
        if md is not None:
            return dict(base, state=f"已提议·{md.month}月{md.day}日表决", key="proposed",
                        since=upcoming[0]["announce_date"], days_to_meeting=days_between(as_of, md))
    if meetings:
        return dict(base, state="下修提案（待表决）", key="proposal_pending",
                    since=meetings[0]["announce_date"], days_to_meeting=None)
    nored = recent_events(by_bond, bc, ("no_reset",), as_of, RESET_WINDOW_DAYS)
    if nored:
        return dict(base, state="公告不下修", key="no_reset",
                    since=nored[0]["announce_date"], days_to_meeting=None)
    done = recent_events(by_bond, bc, ("reset",), as_of, RESET_WINDOW_DAYS)
    if done:
        return dict(base, state="已下修", key="reset_done",
                    since=done[0]["announce_date"], days_to_meeting=None)
    return dict(base, state="无", key="none", since="", days_to_meeting=None)


# ---------------- 三道闸 ----------------
def gate_row(row: dict, by_bond: dict, as_of: str) -> list[tuple[str, str]]:
    """返回命中的 ``[(reason_code, detail)]``，按 G1→G2→G3 顺序；空列表 = 过闸。

    全部命中的理由都返回（不只第一个），由 ``evaluate`` 取首个作为唯一剔除理由
    ——这样「某债同时因 ST 和到期被剔」在明细里看得见，但计数不重复。
    """
    hits: list[tuple[str, str]] = []
    bc = str(row.get("bondCode") or "")
    exp = to_date(row.get("expireDate"))
    a = to_date(as_of)

    # G1 可交易
    if exp and a and exp < a:
        hits.append(("g1_expired", GATE_DETAIL["g1_expired"].format(d=row.get("expireDate"))))
    pxv = as_float(row.get("bondPrice"))
    if pxv is None or pxv <= 0:
        hits.append(("g1_no_price", GATE_DETAIL["g1_no_price"]))
    size = as_float(row.get("remainSize"))
    if size is None or size <= 0:
        hits.append(("g1_no_size", GATE_DETAIL["g1_no_size"]))

    # G2 信用
    if is_st_name(row.get("stockName")):
        hits.append(("g2_st", GATE_DETAIL["g2_st"].format(name=row.get("stockName"))))

    # G3 条款
    red = recent_events(by_bond, bc, ("redeem",), as_of, REDEEM_WINDOW_DAYS)
    if red:
        hits.append(("g3_redeem", GATE_DETAIL["g3_redeem"].format(d=red[0]["announce_date"])))
    ch = as_int(row.get("callHits"))
    if ch is not None and ch >= CALL_HITS_THRESHOLD:
        hits.append(("g3_met15", GATE_DETAIL["g3_met15"].format(hits=ch)))
    dte = days_to_expire(row, as_of)
    if dte is not None and dte < NEAR_EXPIRY_DAYS:
        hits.append(("g3_near_expiry",
                     GATE_DETAIL["g3_near_expiry"].format(
                         x=round(dte / 365.0, 2),
                         p=round(pxv, 2) if pxv is not None else "-")))
    return hits


def evaluate(rows: list[dict], by_bond: dict, as_of: str) -> dict[str, Any]:
    """对在市基座逐行过闸，返回 ``{passed, excluded, rule_hits, by_reason, stats}``。

    ``passed`` 按双低升序（缺双低的排最后）。``rule_hits`` 按「首个命中理由」
    计数，故其和等于 ``excluded`` 条数——这是可核对性要求的，明细见
    ``excluded[i].gate_hits``。
    """
    from .valuation import double_low

    base = [r for r in rows if in_market_base(r)]
    passed, excluded = [], []
    rule_hits: dict[str, int] = {}
    by_reason: dict[str, list[dict]] = {}
    for r in base:
        hits = gate_row(r, by_bond, as_of)
        rec = {
            "bondCode": str(r.get("bondCode") or ""),
            "bondName": r.get("bondName") or "",
            "doubleLow": double_low(r),
            "price": round(float(r["bondPrice"]), 3) if num(r.get("bondPrice")) else None,
            "gateReasons": [h[0] for h in hits],
            "gateHits": [{"reason": h[0], "detail": h[1]} for h in hits],
        }
        if hits:
            first = hits[0][0]
            rule_hits[first] = rule_hits.get(first, 0) + 1
            by_reason.setdefault(first, []).append(
                {"bondCode": rec["bondCode"], "bondName": rec["bondName"], "detail": hits[0][1]})
            excluded.append(dict(rec, reason=first, reasonLabel=GATE_LABEL.get(first, ""),
                                 detail=hits[0][1]))
        else:
            passed.append(dict(rec))
    passed.sort(key=lambda x: (x["doubleLow"] if x["doubleLow"] is not None else 9e9,
                               x["bondCode"]))
    stats = {"baseN": len(base), "passedN": len(passed), "excludedN": len(excluded),
             "sumRuleHits": sum(rule_hits.values())}
    return {"passed": passed, "excluded": excluded, "ruleHits": rule_hits,
            "byReason": by_reason, "stats": stats}


# ---------------- 条款事件日历 ----------------
def calendar(by_bond: dict, base_rows: list[dict], as_of: str) -> dict[str, Any]:
    """条款事件日历：当日新增 + 未来 30 日待办（股东会/回售起止/到期）。"""
    names = {str(r.get("bondCode") or ""): (r.get("bondName") or "") for r in base_rows}
    new_today: list[dict] = []
    next_30d: list[dict] = []
    for bc, evs in by_bond.items():
        for e in evs:
            item = {"date": e["announce_date"], "type": e["deal_type"], "bondCode": bc,
                    "bondName": e["bond_name"] or names.get(bc, ""), "title": e["title"],
                    "url": e["source_url"]}
            if e["announce_date"] == as_of:
                new_today.append(item)
            for key, typ in (("meeting_date", "shareholder_meeting"),
                             ("put_start", "put_start"), ("put_end", "put_end")):
                d = e.get(key) or ""
                delta = days_between(as_of, d) if d else None
                if delta is not None and 0 <= delta <= CALENDAR_DAYS:
                    next_30d.append(dict(item, date=d, type=typ,
                                         title=e["title"] or f"{typ} {d}"))
    for r in base_rows:
        dte = days_to_expire(r, as_of)
        if dte is not None and 0 <= dte <= CALENDAR_DAYS:
            next_30d.append({"date": str(r.get("expireDate"))[:10], "type": "expiry",
                             "bondCode": str(r.get("bondCode") or ""),
                             "bondName": r.get("bondName") or "",
                             "title": f"{r.get('bondName')} 到期",
                             "url": r.get("detailUrl") or ""})

    def uniq(items: list[dict]) -> list[dict]:
        seen, out = set(), []
        for x in items:
            k = (x["date"], x["type"], x["bondCode"])
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    new_today = sorted(uniq(new_today), key=lambda x: (x["type"], x["bondCode"]))
    next_30d = sorted(uniq(next_30d), key=lambda x: (x["date"], x["type"], x["bondCode"]))
    counts: dict[str, int] = {}
    for x in new_today:
        counts[x["type"]] = counts.get(x["type"], 0) + 1
    return {"asOf": as_of, "newToday": new_today, "next30d": next_30d,
            "countsByType": counts}
