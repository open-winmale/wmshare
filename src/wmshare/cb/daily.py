"""可转债日更取数编排：一次快照 + 条款事件 + 批量日 K + 收益率曲线，压成事实包。

请求预算被显式记账（``coverage.requests_made``）——免费档限流按请求次数算，
一条链路悄悄多发 10 个请求，换个账号额度就见底了。

取数纪律：

- 面板走一次 ``cbond.board()``（1066 行含已退出档案行），不要逐票拉。
- 条款事件走 ``cbond.event_list()``，**全量**入索引。曾把它截断到 200 条，
  状态机因此少看 522 条事件，下修状态错了 22 只。
- 全表日 K 走 ``call_batch``（一次 eval 拼成 MAP，每批 ≤120 只 = 1 次 HTTP）。
  逐票循环 311 次会先撞限流，再被 EC 账单教育；批量省的是请求次数，不省 EC。
- 收益率曲线走 ``macro.bond_curve``，**不在代码里内置任何利率常量**：曲线变了
  债底就该跟着变，写死的数字会让"债底"变成一个不随市场更新的幻觉。
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from . import facts as F
from . import rules as R


__all__ = ["DailyConfig", "fetch_snapshot", "run_daily", "CURVES"]

DEFAULT_BUDGET = 60

#: 纯债价值的贴现曲线。主口径用中债 AAA 中短期票据曲线（实测该曲线名可用），
#: 国债曲线作上界——两档都给，读者能看到「信用利差吃掉多少债底」，而不是一个
#: 不知从哪来的单点。曲线名必须逐字匹配上游披露名：写成「中债企业债收益率曲线(AAA)」
#: 会静默返回 None（2026-11-09 实测），债底整列消失且不报错。
CURVES: dict[str, str] = {
    "aaa": "中债中短期票据收益率曲线(AAA)",
    "gov": "中债国债收益率曲线",
}
CURVE_TENORS: dict[float, str] = {1.0: "1年", 3.0: "3年", 5.0: "5年",
                                  7.0: "7年", 10.0: "10年"}
#: 单批日 KB 标的数。整批超过这个量，单次 eval 的响应体会大到不可控。
KLINE_BATCH = 120
#: 拉多少根日 K：20 日波动率要 21 根，前后各留余量。
KLINE_BARS = 25


class DailyConfig:
    """一期日更的取数与选样参数。

    :param top_n: 榜单条数
    :param budget: 单期请求上限（超出即中止，不静默降级）
    :param price_bins: 价格分区边界（元）
    :param ytm_tax: 利息税率
    :param featured: 要拨测价格通道的个券（缺省取榜单前三）
    :param band_bars: 通道窗口交易日数
    :param enrich: 是否对全表拉批量日 K（成交额/换手率/波动率）
    :param curves: 是否取收益率曲线（纯债价值）
    """

    def __init__(self, *, top_n: int = 20, budget: int = DEFAULT_BUDGET,
                 price_bins: tuple[float, float, float] = (100.0, 110.0, 130.0),
                 ytm_tax: float = 0.20, featured: list[str] | None = None,
                 band_bars: int = 250, enrich: bool = True,
                 curves: bool = True) -> None:
        self.top_n = top_n
        self.budget = budget
        self.price_bins = price_bins
        self.ytm_tax = ytm_tax
        self.featured = featured
        self.band_bars = band_bars
        self.enrich = enrich
        self.curves = curves


def _today() -> str:
    return date.today().isoformat()


def fetch_snapshot(cli: Any, *, config: DailyConfig | None = None,
                   as_of: str | None = None) -> dict[str, Any]:
    """取一次面板 + 全量条款事件，并顺带拨测 featured 债的日 K 通道。

    返回 ``{asOf, rows, events, featured_klines, coverage, intraday_risk}``。
    ``asOf`` 取自面板的 ``asOf`` 字段（快照日），不是运行日——两者在盘前
    与节假日不同，混用会让"今天新增"整段失真。
    """
    cfg = config or DailyConfig()
    made = 0

    def spend(n: int = 1) -> None:
        nonlocal made
        made += n
        if made > cfg.budget:
            raise RuntimeError(f"请求数 {made} 超出本期预算 {cfg.budget}")

    rows = cli.cbond.board()
    spend()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("cbond.board() 返回空——快照可能未更新，本期不出稿")

    snap_asof = max((str(r.get("asOf"))[:10] for r in rows if r.get("asOf")), default="")
    # 数据日与请求日必须同时对外可见：曾经只做「±1 天」容差而不上报，调用方
    # 就拿 11-08 的数据按 11-09 命名出稿，档案与正文的「数据截至」全部错位。
    date_mismatch = None
    if as_of and snap_asof and as_of != snap_asof:
        date_mismatch = (datetime.strptime(snap_asof, "%Y-%m-%d").date()
                         - datetime.strptime(as_of, "%Y-%m-%d").date()).days
        # 允许 T-1：盘前跑时快照仍是上一交易日；超过 1 天则拒绝出稿
        if abs(date_mismatch) > 1:
            raise RuntimeError(f"快照日 {snap_asof} 与请求日 {as_of} 相差超过 1 天")

    events = cli.cbond.event_list()
    spend()
    if not isinstance(events, list):
        events = []

    today = _today()
    intraday = snap_asof == today and datetime.now().hour < 15

    # featured：缺省取过闸后双低最低的几只（此时还没算 YTM，双低已足够选样）
    base = [r for r in rows if R.in_market_base(r)]
    by_bond, _ = R.build_event_index(events, rows)
    gate = R.evaluate(rows, by_bond, snap_asof)
    picks = cfg.featured if cfg.featured is not None else \
        [p["bondCode"] for p in gate["passed"][:3]]

    featured_klines: dict[str, dict] = {}
    name_by_code = {str(r.get("bondCode") or ""): (r.get("bondName") or "")
                    for r in base}
    for code in picks:
        # 预算先记账再发请求，且**必须在 try 之外**：曾经把 spend() 写在
        # try 里，预算耗尽的 RuntimeError 被"单只失败不拖垮整期"吞掉，
        # 整期继续超预算取数，请求记账形同虚设。
        spend()
        try:
            kw = cli.cbond.kline_window(code, cfg.band_bars)
        except Exception as e:  # 单只失败不拖垮整期
            featured_klines[code] = {"name": name_by_code.get(code, code), "error": str(e)}
            continue
        if not isinstance(kw, dict) or not kw.get("close"):
            featured_klines[code] = {"name": name_by_code.get(code, code),
                                     "error": "空窗口"}
            continue
        # 上游 samplingName / close 都是降序（新→旧），客户端转升序
        dates = list(kw.get("samplingName") or [])[::-1]
        closes = [float(c) for c in (kw.get("close") or [])][::-1]
        featured_klines[code] = {
            "name": name_by_code.get(code, code),
            "dates": dates, "closes": closes, "n_bars": len(closes),
            "last_bar_date": dates[-1] if dates else "",
        }

    coverage = {"requests_made": made, "budget": cfg.budget,
                "picks": len(picks), "rows": len(rows), "events": len(events),
                "data_date": snap_asof, "requested_date": as_of or "",
                "date_mismatch_days": date_mismatch}

    # ---- 全表批量日 K：成交额 / 换手率 / 波动率都从这一次取数里来 ----
    enrichment: dict[str, dict] = {}
    if cfg.enrich:
        codes = [str(r.get("bondCode") or "") for r in base if r.get("bondCode")]
        enrichment = _fetch_bond_klines(cli, codes, spend)
        coverage["kline_batches"] = (len(codes) + KLINE_BATCH - 1) // KLINE_BATCH
        coverage["kline_rows"] = len(enrichment)

    # ---- 收益率曲线：纯债价值的贴现率，改市场就跟着改 ----
    curves: dict[str, dict[float, float]] = {}
    if cfg.curves:
        curves = _fetch_curves(cli, spend)
        coverage["curve_points"] = {k: len(v) for k, v in curves.items()}

    coverage["requests_made"] = made
    return {"asOf": snap_asof, "rows": rows, "events": events,
            # 数据日（快照 asOf）与请求日分开给：产物命名、正文「数据截至」、
            # 门禁比对都必须用 data_date，不能拿请求日冒充。
            "data_date": snap_asof, "requested_date": as_of or "",
            "date_mismatch_days": date_mismatch,
            "featured_klines": featured_klines, "coverage": coverage,
            "enrichment": enrichment, "curves": curves,
            "intraday_risk": intraday}


def _fetch_bond_klines(cli: Any, codes: list[str], spend) -> dict[str, dict]:
    """批量拉全表转债日 K，压成 ``{code: {closes, amount, dates, last_bar_date}}``。

    用 ``call_batch``（一次 eval 拼 MAP）而不是循环：311 只逐票 = 311 次请求，
    必然先撞 500 次/小时的限流。单批失败只丢这一批，整期继续——少一块富化
    数据比整期不出稿好，缺的那部分由 ``coverage.kline_rows`` 暴露。
    """
    out: dict[str, dict] = {}
    for i in range(0, len(codes), KLINE_BATCH):
        part = codes[i:i + KLINE_BATCH]
        spend()  # 先记账再发请求，且不放在 try 里（预算耗尽的异常不能被吞）
        try:
            res = cli.call_batch("cbond.kline_window", part, n=KLINE_BARS)
        except Exception:
            continue
        for code, kw in (getattr(res, "results", None) or {}).items():
            if not isinstance(kw, dict) or not kw.get("close"):
                continue
            # 上游 samplingName / close / amount 都是降序（新→旧），转升序
            dates = list(kw.get("samplingName") or [])[::-1]
            closes = [float(c) for c in (kw.get("close") or [])][::-1]
            amounts = [float(a) for a in (kw.get("amount") or [])][::-1] \
                if kw.get("amount") else []
            out[str(code)] = {
                "dates": dates, "closes": closes,
                "amount": amounts[-1] if amounts else None,
                "last_bar_date": dates[-1] if dates else "",
            }
    return out


def _fetch_curves(cli: Any, spend) -> dict[str, dict[float, float]]:
    """取 AAA / 国债两档收益率曲线的 1/3/5/7/10 年点。

    单点失败只丢该点（插值会自动平推相邻档），整条曲线失败则该档不参与债底
    计算——宁可不给，也不拿别的期限冒充。
    """
    out: dict[str, dict[float, float]] = {}
    for key, name in CURVES.items():
        pts: dict[float, float] = {}
        for years, tenor in CURVE_TENORS.items():
            spend()
            try:
                v = cli.macro.bond_curve(name, tenor)
            except Exception:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < float(v) < 0.2:
                pts[float(years)] = float(v)
        if len(pts) >= 2:
            out[key] = pts
    return out


def run_daily(cli: Any, *, as_of: str | None = None, config: DailyConfig | None = None,
              hist_means: list[float] | None = None,
              snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """走完取数 → 事实，返回事实包（不含成稿与图）。

    ``snapshot`` 可传入已取好的面板（重跑成稿时避免二次取数）。
    """
    cfg = config or DailyConfig()
    snap = snapshot or fetch_snapshot(cli, config=cfg, as_of=as_of)
    payload = F.build_facts(
        snap["rows"], snap["events"], snap["asOf"],
        tax=cfg.ytm_tax, top_n=cfg.top_n, price_bins=cfg.price_bins,
        hist_means=hist_means, featured_klines=snap["featured_klines"],
        enrichment=snap.get("enrichment"), curves=snap.get("curves"),
        curve_asof=snap["asOf"],
    )
    payload["coverage"] = snap["coverage"]
    payload["intraday_risk"] = snap["intraday_risk"]
    payload["snapshot_asOf"] = snap["asOf"]
    # 数据日与请求日一并带出，供调用方决定产物命名与是否拒绝出稿
    payload["data_date"] = snap.get("data_date") or snap["asOf"]
    payload["requested_date"] = snap.get("requested_date") or ""
    payload["date_mismatch_days"] = snap.get("date_mismatch_days")
    return payload
