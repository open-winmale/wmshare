"""可转债日更事实构建：把面板行 + 条款事件压成可核对的数字。

输入是一次快照（``cbond.board()`` 的行 + ``cbond.event_list()`` 的事件）与一个
交易日，输出是 facts / derived 两个平铺列表——每条事实带 ``id``、``metric``、
``value_text``、``value_num``、``unit``、``window``、``as_of``、``status``、
``sources``。成稿器只从这份产物取数：**缺条目就 refusal，不许现造数字**。

这层的纪律（写在这里，免得后续改动破坏）：

- 价格、溢价、双低、YTM 只由 ``cb.valuation`` 算，本模块不重复实现口径。
- 闸门与状态机只由 ``cb.rules`` 算，本模块负责把结果摊平成事实。
- 一切"多少只"都从同一份 ``states`` 数出来，不用第二个数据源交叉验证
  （单源时交叉验证只会自欺）。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from . import rules as R
from .valuation import (
    coupon_schedule,
    double_low,
    nature_class,
    premium_pct,
    remaining_years,
    ytm_after_tax,
    ytm_floor,
)

__all__ = ["build_facts", "fmt", "probe", "caliber_layers"]

EVENT_TYPE_CN = {
    "reset_proposal": "董事会下修提案",
    "reset": "下修实施",
    "no_reset": "承诺不下修",
    "price_adj": "除权除息调价",
    "redeem": "强赎",
    "no_redeem": "不行使强赎",
    "put": "回售相关",
    "convert_start": "进入转股期",
    "convert_result": "转股结果",
    "shareholder_meeting": "股东会表决",
    "put_start": "回售期开始",
    "put_end": "回售期结束",
    "expiry": "到期",
}

_RE_REDEEM = re.compile(r"到期赎回[^。；]*?(\d{2,3}(?:\.\d+)?)\s*元")


def fmt(x: Any, nd: int = 2) -> str:
    """千分位格式化；非数值原样转字符串（成稿器不接受 'nan'）。"""
    try:
        return f"{float(x):,.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def probe(closes: list[float], dates: list[str]) -> dict:
    """价格通道拨测：μ/σ/z/历史分位与 ±1σ/±2σ 通道边界。

    仅描述"当前价相对自身历史的位置"，不构成估值判断——三只债的 μ/σ 各自
    独立，横向比较谁"更便宜"没有意义。
    """
    n = len(closes)
    mu = sum(closes) / n
    var = sum((c - mu) ** 2 for c in closes) / max(1, n - 1)
    sd = var ** 0.5
    last = closes[-1]
    z = (last - mu) / sd if sd else 0.0
    pct = sum(1 for c in closes if c <= last) / n
    if z <= -2:
        zone, zone_cn = "lower2", "下轨外（-2σ 以下）"
    elif z <= -1:
        zone, zone_cn = "lower1", "下轨区（-2σ ~ -1σ）"
    elif z < 1:
        zone, zone_cn = "mid", "通道中区（-1σ ~ +1σ）"
    elif z < 2:
        zone, zone_cn = "upper1", "上轨区（+1σ ~ +2σ）"
    else:
        zone, zone_cn = "upper2", "上轨外（+2σ 以上）"
    i_min = min(range(n), key=lambda i: closes[i])
    i_max = max(range(n), key=lambda i: closes[i])
    return {
        "series_n": n, "avg": round(mu, 3), "sigma": round(sd, 3),
        "current": last, "z": round(z, 3), "pct": round(pct, 4),
        "lower2": round(mu - 2 * sd, 3), "lower1": round(mu - sd, 3),
        "upper1": round(mu + sd, 3), "upper2": round(mu + 2 * sd, 3),
        "zone": zone, "zone_cn": zone_cn, "coverage": 1.0,
        "min": min(closes), "max": max(closes),
        "min_date": dates[i_min] if dates else "", "max_date": dates[i_max] if dates else "",
        "first_date": dates[0] if dates else "", "last_date": dates[-1] if dates else "",
    }


def redeem_from_text(explain: str | None) -> float | None:
    """从票息说明文本解析到期赎回价（元）。命中率低，仅作 ``redeemValue`` 的兜底。"""
    if not explain:
        return None
    m = _RE_REDEEM.search(explain)
    if m and 100 <= float(m.group(1)) <= 200:
        return float(m.group(1))
    return None


def caliber_layers(rows: list[dict], as_of: str, passed_n: int) -> dict:
    """四层口径：总行 → 行情基座 → 闸门基座 → 在市 → 过闸。

    写清楚是因为这几个数看起来该相等、实际不等：快照含已退出的档案行，
    闸门基座比行情基座多 5 只"有溢价率但当日无报价"的债（它们要进闸门逐只
    判定，否则 G1 的 no_price/expired 永远不可见）。
    """
    quote_base = [r for r in rows if R.num(r.get("bondPrice")) and R.num(r.get("premiumRatio"))]
    gate_base = [r for r in rows if R.in_market_base(r)]
    in_market = [r for r in quote_base
                 if (R.days_to_expire(r, as_of) or -1) >= 0]
    return {
        "total_rows": len(rows),
        "quote_base": len(quote_base),
        "gate_base": len(gate_base),
        "in_market": len(in_market),
        "passed_gate": passed_n,
        "note": "quote_base=行情基座（价与溢价率均非空）；in_market=可交易口径"
                "（再叠 remainSize>0 且 expireDate≥asOf）；gate_base=闸门基座（含无报价行）",
    }


def _agg(fid: str, metric: str, vt: str, vn: Any, unit: str, used_in: list[str],
         *, as_of: str, sid: str, note: str = "", subject: str = "全市场转债",
         window: str = "快照", status: str = "DERIVED", bucket: list[dict]) -> dict:
    d = {"id": fid, "metric": metric, "subject": subject, "value_text": vt,
         "value_num": vn, "unit": unit, "window": window, "as_of": as_of,
         "status": status, "sources": [sid], "used_in": used_in}
    if note:
        d["note"] = note
    bucket.append(d)
    return d


def build_facts(rows: list[dict], events: Iterable[dict], as_of: str, *,
                source_id: str | None = None,
                tax: float = 0.20,
                top_n: int = 20,
                price_bins: tuple[float, float, float] = (100.0, 110.0, 130.0),
                hist_means: list[float] | None = None,
                featured_klines: dict[str, dict] | None = None) -> dict:
    """构建一期事实包：``{facts, derived, gates, states, top, scatter, calendar, ...}``。

    :param rows: 面板行（``cbond.board()`` 或 ``latest_quotes()`` 的行）
    :param events: 条款事件（``cbond.event_list()`` 的行）
    :param as_of: 快照交易日 ``YYYY-MM-DD``（不是运行日）
    :param hist_means: 历史各期双低均值，用于分位与星级；不足 10 期不给星级
    :param featured_klines: ``{code: {"name", "dates", "closes", "last_bar_date", "n_bars"}}``
    """
    sid = source_id or f"wmshare:cb-daily:{as_of}"
    bins = [float(x) for x in price_bins]
    facts: list[dict] = []
    derived: list[dict] = []

    by_bond, ev_stats = R.build_event_index(events, rows)
    gate = R.evaluate(rows, by_bond, as_of)
    base = [r for r in rows if R.in_market_base(r)]
    by_code = {str(r.get("bondCode") or ""): r for r in base}
    top_rows = [by_code[p["bondCode"]] for p in gate["passed"][:top_n] if p["bondCode"] in by_code]

    # ---- 逐债派生：税后 YTM（两口径）必须先算，状态与散点都要用 ----
    ytm_by_code: dict[str, dict] = {}
    ytms: list[float] = []
    for r in base:
        y = ytm_after_tax(r, as_of, tax=tax)
        ytm_by_code[str(r.get("bondCode") or "")] = y
        if y.get("ytm_floor") is not None:
            ytms.append(y["ytm_floor"])

    # ---- 逐债状态（在市基座全覆盖，供日历与看板）----
    states: list[dict] = []
    for r in base:
        bc = str(r.get("bondCode") or "")
        y = ytm_by_code[bc]
        cs = R.call_state(r, by_bond, as_of)
        rs = R.reset_state(r, by_bond, as_of)
        dte = R.days_to_expire(r, as_of)
        hit = R.gate_row(r, by_bond, as_of)
        px = float(r["bondPrice"]) if R.num(r.get("bondPrice")) else None
        pp = premium_pct(r)
        states.append({
            "bondCode": bc, "bondName": r.get("bondName") or "",
            "price": round(px, 3) if px is not None else None,
            "premium_pct": round(pp, 2) if pp is not None else None,
            "double_low": double_low(r),
            "call_state": cs["state"], "call_state_key": cs["key"], "call_hits": cs["hits"],
            "call_window": cs["window"], "days_to_call_15": cs["days_to_15"],
            # 计数达标但另有不赎回公告时的两个并列事实（不合成「已豁免」结论）
            "no_redeem_since": cs.get("no_redeem_since") or "",
            "no_redeem_days": cs.get("no_redeem_days"),
            "reset_state": rs["state"], "reset_state_key": rs["key"], "reset_floor": rs["floor"],
            "reset_meeting": rs["meeting"], "days_to_meeting": rs.get("days_to_meeting"),
            "days_to_expire": dte,
            "years_to_expire": round(dte / 365.0, 2) if dte is not None else None,
            "remain_size_yi": (round(float(r["remainSize"]) / 1e8, 2)
                               if R.num(r.get("remainSize")) else None),
            # 面板不含资产负债表字段，负债率类警示不提供（不猜）
            "stock_tl_rate_pct": None,
            "near_expiry": dte is not None and dte < R.GRAY_EXPIRY_DAYS,
            # 正股距强赎触发价还需上涨的幅度（%）：触发价/现价-1
            "redeem_dist_pct": (round((float(r["redeemTrig"]) / float(r["stockPrice"]) - 1) * 100, 1)
                                if R.num(r.get("redeemTrig")) and R.num(r.get("stockPrice"))
                                and float(r["stockPrice"]) > 0 else None),
            "gate_reasons": [h[0] for h in hit],
            "passed_gate": not hit,
            "is_st": bool(r.get("is_st")) or R.is_st_name(r.get("stockName")),
            "stockCode": r.get("stockCode") or "", "stockName": r.get("stockName") or "",
            "ytm": round(y["ytm"] * 100, 2) if y.get("ytm") is not None else None,
            "ytm_floor": round(y["ytm_floor"] * 100, 2) if y.get("ytm_floor") is not None else None,
            "ytm_basis": y.get("basis"),
            # 债性分类看"持有到期是否还有正收益"——用可达口径的税后 YTM，
            # 不取下限口径（下限口径故意保守，会把正收益债判成平衡，与表注矛盾）。
            "nature": nature_class(px or 0.0, pp or 0.0, y.get("ytm")),
        })
    st_by = {s["bondCode"]: s for s in states}
    cal = R.calendar(by_bond, base, as_of)

    # ---- 全市场横截面（行情基座，与历史各期可比）----
    stat_rows = [r for r in base if R.num(r.get("bondPrice")) and R.num(r.get("premiumRatio"))]
    prices = [float(r["bondPrice"]) for r in stat_rows]
    prems = [v for v in (premium_pct(r) for r in stat_rows) if v is not None]
    dls = [s["double_low"] for s in states if s["double_low"] is not None]
    mean_dl = sum(dls) / len(dls) if dls else 0.0
    srt = sorted(dls)
    n = len(srt)
    median_dl = (srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2) if n else 0.0
    bin_lt100 = sum(1 for p in prices if p < bins[0])
    bin_100_110 = sum(1 for p in prices if bins[0] <= p < bins[1])
    bin_110_130 = sum(1 for p in prices if bins[1] <= p < bins[2])
    bin_gt130 = sum(1 for p in prices if p >= bins[2])
    # 「YTM 为正」用可达口径（有分年票息表就用表），不取下限口径——下限口径
    # 故意保守（赎回价按面值），拿它数"几只正收益"会系统性少报。
    ytm_pos_n = sum(1 for st in states
                    if isinstance(st.get("ytm"), (int, float)) and st["ytm"] > 0)
    mean_prem = sum(prems) / len(prems) if prems else 0.0

    # ---- 榜内个债事实 ----
    for r in top_rows:
        code, name = str(r["bondCode"]), r.get("bondName") or ""
        price = float(r["bondPrice"])
        pp = premium_pct(r) or 0.0
        dl = double_low(r) or 0.0
        y = ytm_by_code[code]
        st = st_by.get(code, {})
        common = {"subject": name, "window": "快照", "as_of": as_of,
                  "sources": [sid], "used_in": ["双低榜"]}

        def add(fid: str, metric: str, vt: str, vn: Any, unit: str, *, note: str = "",
                status: str = "SINGLE_SOURCE", used_in: list[str] | None = None) -> None:
            d = dict(common, id=f"{fid}_{code}", metric=metric, value_text=vt, value_num=vn,
                     unit=unit, status=status)
            if used_in:
                d["used_in"] = used_in
            if note:
                d["note"] = note
            (facts if status == "SINGLE_SOURCE" else derived).append(d)

        add("price", "cb_price", fmt(price), round(price, 2), "元", )
        add("prem", "cb_premium_pct", fmt(pp) + "%", round(pp, 2), "percent",
            note="premiumRatio 为百分比数值，×100 展示；负值为折价")
        add("dl", "cb_double_low", fmt(dl), round(dl, 2), "元+%", status="DERIVED",
            used_in=["双低榜", "温度计"])
        if R.num(r.get("transferValue")):
            add("cv", "cb_convert_value", fmt(float(r["transferValue"])),
                round(float(r["transferValue"]), 2), "元")
        if y.get("ytm") is not None:
            note = {
                "schedule": "分年票息表 + 到期赎回价，税后 IRR",
                "constant": "当年票息恒定近似 + 到期赎回价，税后 IRR",
                "floor": "赎回价未知按面值 100 兑付（真值 ≥ 此下限），当期票息恒定",
            }.get(y.get("basis") or "", "")
            add("ytm", "cb_ytm_after_tax", fmt(y["ytm"] * 100) + "%",
                round(y["ytm"] * 100, 2), "percent", note=note, status="DERIVED",
                used_in=["双低榜", "债性分类"])
        if y.get("ytm_floor") is not None:
            add("ytmf", "cb_ytm_floor", fmt(y["ytm_floor"] * 100) + "%",
                round(y["ytm_floor"] * 100, 2), "percent", status="DERIVED",
                note="下限口径（赎回价按面值 100），与估算口径并列可见")
        add("nat", "cb_nature_class", st.get("nature") or "-", None, "enum", status="DERIVED")
        if st.get("redeem_dist_pct") is not None:
            add("rd", "cb_redeem_distance", fmt(st["redeem_dist_pct"], 1) + "%",
                st["redeem_dist_pct"], "percent", status="DERIVED", used_in=["强赎距离"],
                note="正股还需上涨幅度至强赎触发价；15/30 日计数规则另行判读")
        if R.num(r.get("remainSize")):
            add("rm", "cb_remain_size", fmt(float(r["remainSize"]) / 1e8),
                round(float(r["remainSize"]) / 1e8, 2), "亿元")
        if st.get("is_st"):
            add("st", "cb_stock_is_st", "ST", None, "flag")
        if st.get("days_to_expire") is not None:
            add("yrs", "cb_days_to_expire", fmt(st["days_to_expire"] / 365.0) + " 年",
                st["days_to_expire"], "日", status="DERIVED", used_in=["双低榜"],
                note="剩余年限 = expireDate − asOf（自然日 / 365）")
        add("cs", "cb_call_status", st.get("call_state") or "未触发", None, "enum",
            status="DERIVED", used_in=["双低榜", "强赎看板"],
            note="六态状态机；callHits 由服务端按债键控、仅跨线后返回")
        if st.get("call_hits") is not None:
            add("ch", "cb_call_hits", str(st["call_hits"]), int(st["call_hits"]), "日",
                status="DERIVED", used_in=["强赎观测"],
                note="正股无复权收盘 ≥ 强赎触发价的近窗交易日数")
        add("rs", "cb_reset_state", st.get("reset_state") or "无", None, "enum",
            status="DERIVED", used_in=["双低榜", "下修观测"], note="五态状态机")
        if R.num(st.get("reset_floor")):
            add("rf", "cb_reset_floor", fmt(st["reset_floor"]), st["reset_floor"], "元",
                status="DERIVED", used_in=["下修观测"],
                note=f"服务端测算（family {r.get('resetFamily') or '-'}）")

    # ---- 闸门 / 温度 / 口径层 ----
    # 七个闸门固定出条目（含计数为 0 的）：成稿的"排雷"段落要引用它们，
    # 某个闸门当天一只没剔就缺条目，会让整篇文章因为缺一个 0 而拒绝生成。
    for reason in R.GATE_LABEL:
        cnt = int(gate["ruleHits"].get(reason, 0))
        _agg(f"gate_{reason}", "cb_gate_excluded_n", str(cnt), cnt, "只", ["三道闸"],
             as_of=as_of, sid=sid, note=R.GATE_LABEL[reason], bucket=derived)
    _agg("gate_passed_n", "cb_gate_excluded_n", str(gate["stats"]["passedN"]),
         gate["stats"]["passedN"], "只", ["三道闸"], as_of=as_of, sid=sid,
         note="通过 G1–G3 的标的数（进榜候选池）", bucket=derived)
    _agg("excluded_total", "cb_gate_excluded_n", str(gate["stats"]["excludedN"]),
         gate["stats"]["excludedN"], "只", ["三道闸"], as_of=as_of, sid=sid,
         note="被剔除总数＝按首命中理由分组之和", bucket=derived)

    _agg("mean_dl", "cb_double_low_mean", fmt(mean_dl), round(mean_dl, 2), "元+%",
         ["温度计"], as_of=as_of, sid=sid, bucket=derived)
    _agg("median_dl", "cb_double_low_median", fmt(median_dl), round(median_dl, 2), "元+%",
         ["温度计"], as_of=as_of, sid=sid, bucket=derived)
    _agg("mean_prem", "cb_premium_mean", fmt(mean_prem) + "%", round(mean_prem, 2), "percent",
         ["温度计"], as_of=as_of, sid=sid, bucket=derived)
    for fid, metric, cnt, note in (
        ("bin_lt100", "cb_price_bin_lt100", bin_lt100, f"价格 <{bins[0]:.0f} 元（破面区）"),
        ("bin_100_110", "cb_price_bin_100_110", bin_100_110,
         f"价格 {bins[0]:.0f}–{bins[1]:.0f} 元（债性区）"),
        ("bin_110_130", "cb_price_bin_110_130", bin_110_130,
         f"价格 {bins[1]:.0f}–{bins[2]:.0f} 元（平衡区）"),
        ("bin_gt130", "cb_price_bin_gt130", bin_gt130, f"价格 ≥{bins[2]:.0f} 元（强赎区）"),
    ):
        _agg(fid, metric, str(cnt), cnt, "只", ["温度计", "价格分布"], as_of=as_of, sid=sid,
             note=note, bucket=derived)
    _agg("ytm_pos_n", "cb_ytm_positive_n", str(ytm_pos_n), ytm_pos_n, "只", ["温度计"],
         as_of=as_of, sid=sid,
         note="税后到期收益率 > 0 的在市转债数（可达口径：优先分年票息表 + 真实赎回价）",
         bucket=derived)

    layers = caliber_layers(rows, as_of, gate["stats"]["passedN"])
    _agg("traded_n", "cb_traded_n", str(layers["quote_base"]), layers["quote_base"], "只",
         ["导语"], as_of=as_of, sid=sid,
         note="行情基座：bondPrice 与 premiumRatio 均非空（横截面统计口径）", bucket=derived)
    _agg("gate_base_n", "cb_traded_n", str(layers["gate_base"]), layers["gate_base"], "只",
         ["三道闸"], as_of=as_of, sid=sid,
         note="闸门基座：premiumRatio 非空（含无有效报价行，使 G1 可见）", bucket=derived)
    _agg("total_n", "cb_total_n", str(len(rows)), len(rows), "行", ["口径说明"],
         as_of=as_of, sid=sid, note="快照总行数（含已退出档案行）", bucket=derived)

    # ---- 历史分位与星级（序列 ≥10 期才启用）----
    hist = list(hist_means or [])
    if hist:
        pct_hist = sum(1 for v in hist if v < mean_dl) / len(hist)
        _agg("dl_pct_hist", "cb_double_low_pct_hist", fmt(pct_hist * 100, 1) + "%",
             round(pct_hist * 100, 1), "percent", ["温度计"], as_of=as_of, sid=sid,
             note=f"双低均值在历史 {len(hist)} 期中的分位（自积累序列）", bucket=derived)
        stars = 1
        for th, s in ((0.2, 5), (0.4, 4), (0.6, 3), (0.8, 2)):
            if pct_hist <= th:
                stars = s
                break
        _agg("stars", "cb_star_rating", f"{stars} 星", stars, "星", ["导语"], as_of=as_of,
             sid=sid, note="双低均值历史分位 ≤20%→5星 … >80%→1星（≥10 期起启用）",
             bucket=derived)
        _agg("mean_delta", "cb_double_low_mean_delta",
             f"{mean_dl - hist[-1]:+.2f}", round(mean_dl - hist[-1], 2), "元+%",
             ["温度计"], as_of=as_of, sid=sid,
             note="与上一期双低均值之差（同口径可比时）", bucket=derived)
    else:
        _agg("dl_pct_hist", "cb_double_low_pct_hist", "序列积累中", None, "-", ["温度计"],
             as_of=as_of, sid=sid,
             note="首刊起逐日积累双低均值序列，10 期后开放分位与星级", bucket=derived)

    # ---- featured 债价格通道 ----
    featured_band: dict[str, dict] = {}
    for code, kl in (featured_klines or {}).items():
        if kl.get("error") or not kl.get("closes"):
            continue
        if kl.get("last_bar_date") != as_of:
            continue  # 日 K 陈旧（末根 ≠ 快照日）时不做通道判断，避免拿旧序列说今天
        ch = probe(list(kl["closes"]), list(kl.get("dates") or []))
        featured_band[code] = {"name": kl.get("name") or code, "channel": ch,
                               "n_bars": kl.get("n_bars") or len(kl["closes"])}
        subj = featured_band[code]["name"]
        win = f"上市以来 {featured_band[code]['n_bars']} 个交易日"
        _agg(f"fb_z_{code}", "cb_band_z", f"{ch['z']:+.2f}", round(ch["z"], 2), "σ",
             ["通道拨测"], as_of=as_of, sid=sid, subject=subj, window=win, bucket=derived)
        _agg(f"fb_pct_{code}", "cb_price_pct_hist", fmt(ch["pct"] * 100, 1) + "%",
             round(ch["pct"] * 100, 1), "percent", ["通道拨测"], as_of=as_of, sid=sid,
             subject=subj, window=win, bucket=derived)

    # ---- 事件日历 ----
    _agg("cal_new_n", "cb_event_new_today", str(len(cal["newToday"])), len(cal["newToday"]),
         "起", ["事件日历"], as_of=as_of, sid=sid,
         note="asOf 当日公告的条款事件数", bucket=derived)
    _agg("cal_next_n", "cb_event_next_30d", str(len(cal["next30d"])), len(cal["next30d"]),
         "起", ["事件日历"], as_of=as_of, sid=sid,
         note="未来 30 日内的股东会/回售起止/到期节点数", bucket=derived)
    for t, c in sorted(cal["countsByType"].items(), key=lambda kv: -kv[1]):
        _agg(f"caltype_{t}", "cb_event_new_today", str(c), c, "起", ["事件日历"],
             as_of=as_of, sid=sid, note=EVENT_TYPE_CN.get(t, t), bucket=derived)

    # ---- 异动观察 ----
    below = sorted([s for s in states if s["price"] is not None and s["price"] < bins[0]],
                   key=lambda s: s["price"])
    _agg("obs_lt100_names", "cb_price_bin_lt100",
         "、".join(s["bondName"] for s in below) or "无", len(below), "只", ["异动观察"],
         as_of=as_of, sid=sid,
         note="价格低于面值的在市转债（含被闸门剔除者）", bucket=derived)
    st_below = sum(1 for s in below if s["is_st"])
    _agg("obs_lt100_st_n", "cb_price_bin_lt100", str(st_below), st_below, "只", ["异动观察"],
         as_of=as_of, sid=sid, note="破面区中正股为 ST 的只数（低价≠便宜的直接证据）",
         bucket=derived)

    near_call = sorted([s for s in states if s["passed_gate"]
                        and isinstance(s.get("redeem_dist_pct"), (int, float))
                        and 0 < s["redeem_dist_pct"] <= 10],
                       key=lambda s: s["redeem_dist_pct"])
    _agg("obs_call_near_n", "cb_redeem_distance", str(len(near_call)), len(near_call), "只",
         ["异动观察"], as_of=as_of, sid=sid,
         note="通过闸门且正股距强赎触发价 0–10% 的只数（按快照价自算）", bucket=derived)
    _agg("obs_call_near_names", "cb_redeem_distance",
         "、".join(f"{s['bondName']} {s['redeem_dist_pct']:+.0f}%" for s in near_call[:6]) or "无",
         None, "-", ["异动观察"], as_of=as_of, sid=sid,
         note="上述个券的名称与距触发幅度（正数=还需上涨）", bucket=derived)

    stale_call = sorted([s for s in states
                         if isinstance(s.get("redeem_dist_pct"), (int, float))
                         and s["redeem_dist_pct"] <= 0 and (s.get("call_hits") or 0) < R.CALL_HITS_THRESHOLD],
                        key=lambda s: s["bondName"])
    _agg("obs_call_stale_n", "cb_call_hits", str(len(stale_call)), len(stale_call), "只",
         ["异动观察"], as_of=as_of, sid=sid,
         note="股价已不低于触发价、但服务端计数未达阈值的只数（口径存疑，逐只可核）",
         bucket=derived)
    _agg("obs_call_stale_names", "cb_call_hits",
         "、".join(s["bondName"] for s in stale_call[:5]) or "无", None, "-", ["异动观察"],
         as_of=as_of, sid=sid, note="上述个券名称，供人工复核服务端计数", bucket=derived)

    ytm_pos = [s for s in states if isinstance(s.get("ytm"), (int, float)) and s["ytm"] > 0]
    _agg("obs_ytm_pos_n", "cb_ytm_positive_n", str(len(ytm_pos)), len(ytm_pos), "只",
         ["异动观察"], as_of=as_of, sid=sid,
         note="税后 YTM 为正的在市债只数（可达口径）", bucket=derived)
    _agg("obs_ytm_pos_st_n", "cb_ytm_positive_n",
         str(sum(1 for s in ytm_pos if s["is_st"])), sum(1 for s in ytm_pos if s["is_st"]),
         "只", ["异动观察"], as_of=as_of, sid=sid,
         note="其中正股 ST（已被 G2 剔除）的只数", bucket=derived)
    _agg("obs_ytm_pos_passed_n", "cb_ytm_positive_n",
         str(sum(1 for s in ytm_pos if s["passed_gate"])),
         sum(1 for s in ytm_pos if s["passed_gate"]), "只", ["异动观察"], as_of=as_of, sid=sid,
         note="其中通过三道闸的只数（真正能进榜的偏债候选）", bucket=derived)

    state_n: dict[str, int] = {}
    for st0 in states:
        k0 = str(st0["call_state_key"])
        state_n[k0] = state_n.get(k0, 0) + 1
    for k, label in (("met15", "已满足强赎条件"), ("no_redeem", "公告不强赎"),
                     ("counting", "强赎计数中"), ("redeem_announced", "强赎公告"),
                     ("redeemed", "已实施强赎"), ("idle", "未触发")):
        c = state_n.get(k, 0)
        _agg(f"obs_call_{k}", "cb_call_status", str(c), c, "只", ["异动观察"],
             as_of=as_of, sid=sid, note=f"强赎状态为「{label}」的在市债只数", bucket=derived)

    nxt = cal["next30d"]
    for typ, label in (("shareholder_meeting", "股东会表决"), ("put_start", "回售期开始"),
                       ("put_end", "回售期结束"), ("expiry", "到期")):
        c = sum(1 for x in nxt if x["type"] == typ)
        _agg(f"obs_next_{typ}", "cb_event_next_30d", str(c), c, "个", ["事件日历"],
             as_of=as_of, sid=sid, note=f"未来 30 日内「{label}」节点数", bucket=derived)
    if nxt:
        first = nxt[0]
        _agg("obs_next_first", "cb_event_next_30d",
             f"{first['date']} {first['bondName']}", None, "-", ["事件日历"],
             as_of=as_of, sid=sid, note=f"最近的一个节点：{first['title'][:30]}", bucket=derived)

    # 计数达标 + 有不赎回公告：两个事实并列，不合成「已豁免」结论
    waived = [s for s in states if s.get("no_redeem_since") and s["call_state_key"] == "met15"]
    _agg("obs_call_met15_with_waiver", "cb_call_status", str(len(waived)), len(waived), "只",
         ["异动观察"], as_of=as_of, sid=sid,
         note="强赎计数已达标、同时有不赎回公告的只数（豁免是否生效需查公告原文）",
         bucket=derived)
    if waived:
        recent = sorted(waived, key=lambda s: s.get("no_redeem_since") or "", reverse=True)
        _agg("obs_call_met15_waiver_recent", "cb_call_status",
             "、".join(f"{s['bondName']}（{s.get('no_redeem_days') or 0} 天前）" for s in recent[:5]),
             None, "-", ["异动观察"], as_of=as_of, sid=sid,
             note="其中不赎回公告最新的五只及公告距今天数", bucket=derived)

    gray = sum(1 for s in states if s["passed_gate"] and s["near_expiry"])
    _agg("obs_gray_n", "cb_days_to_expire", str(gray), gray, "只", ["双低榜"],
         as_of=as_of, sid=sid,
         note="通过闸门但剩余 0.5–1 年、已在表中灰标的只数", bucket=derived)

    # ---- 强赎看板 ----
    watch = [{"bondCode": s["bondCode"], "bondName": s["bondName"], "hits": s["call_hits"],
              "days_to_15": s["days_to_call_15"], "state": s["call_state"],
              "key": s["call_state_key"]}
             for s in states
             if s["call_state_key"] in ("counting", "met15", "redeem_announced", "redeemed")]
    watch.sort(key=lambda x: (x["days_to_15"] if x["days_to_15"] is not None else 99,
                              x["bondCode"]))

    return {
        "source": "wmshare",
        "source_id": f"wmshare:cb-daily-facts:{as_of}",
        "date": as_of,
        "rules_version": "wmshare-cb-v1",
        "facts": facts,
        "derived": derived,
        "gates": {"rules_version": "wmshare-cb-v1", **gate["stats"],
                  "ruleHits": gate["ruleHits"], "ruleLabel": R.GATE_LABEL,
                  "excluded": gate["excluded"], "byReason": gate["byReason"]},
        "states": states,
        "top": [{k: st_by[r["bondCode"]][k] for k in (
            "bondCode", "bondName", "price", "premium_pct", "double_low", "ytm", "ytm_floor",
            "nature", "call_state", "call_state_key", "call_hits", "reset_state",
            "reset_state_key", "reset_floor", "days_to_expire", "years_to_expire",
            "remain_size_yi", "stock_tl_rate_pct", "near_expiry", "is_st",
            "stockCode", "stockName", "redeem_dist_pct")}
            for r in top_rows if r["bondCode"] in st_by],
        "scatter": [{"code": s["bondCode"], "name": s["bondName"], "price": s["price"],
                     "prem_pct": s["premium_pct"], "nature": s["nature"],
                     "call_state": s["call_state"], "near_expiry": s["near_expiry"],
                     "passed_gate": s["passed_gate"], "ytm": s["ytm"]}
                    for s in states if s["price"] is not None and s["premium_pct"] is not None],
        "calendar": cal,
        "call_watch": watch,
        "event_stats": ev_stats,
        "featured_band": featured_band,
        # 通道图要原始日 K：只带 μ/σ 统计量则 article()/figures() 依赖外部
        # 再次取数，事实包就不再是自足产物。只留画图必需的列。
        "featured_klines": {
            code: {"dates": list(kl.get("dates") or []),
                   "closes": list(kl.get("closes") or []),
                   "last_bar_date": kl.get("last_bar_date") or "",
                   "n_bars": kl.get("n_bars") or len(kl.get("closes") or [])}
            for code, kl in (featured_klines or {}).items()
            if not kl.get("error") and kl.get("closes")
        },
        "caliber_layers": layers,
        "hist_series_n": len(hist),
        "thresholds": {
            "double_low": "价格 + 转股溢价率×100（社区通行公式，独立计算）",
            "gates": "G1 可交易 → G2 信用 → G3 条款，按序判定、命中即剔除、理由唯一",
            "call": f"callHits ≥ {R.CALL_HITS_THRESHOLD} 视为已满足；15/30 为条款惯例阈值，"
                    f"各债细则不同，以募集说明书为准",
            "reset": "近 90 日事件 + 会议日；上游无下修触发比例字段，故不提供下修计数",
            "expiry": f"剩余 <{R.NEAR_EXPIRY_DAYS} 天剔除、<{R.GRAY_EXPIRY_DAYS} 天灰标",
            "ytm": "税后到期收益率：分年票息表 + 到期赎回价求 IRR，利息税 20%；"
                   "票息表或赎回价缺失时退化到下限口径（真值 ≥ 下限）",
            "disclaimer": "全部内容为数据整理与研究参考，不构成任何投资建议",
        },
    }


# 供外部复算/画图直接引用，避免二次实现
__all__ += ["coupon_schedule", "remaining_years", "ytm_floor", "double_low", "premium_pct"]
