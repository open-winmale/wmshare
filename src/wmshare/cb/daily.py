"""可转债日更取数编排：一次快照 + 条款事件 + 若干条日 K，压成事实包。

请求预算被显式记账（``coverage.requests_made``）——免费档限流按请求次数算，
一条链路悄悄多发 10 个请求，换个账号额度就见底了。默认预算 30。

取数纪律：

- 面板走一次 ``cbond.board()``（1066 行含已退出档案行），不要逐票拉。
- 条款事件走 ``cbond.event_list()``，**全量**入索引。曾把它截断到 200 条，
  状态机因此少看 522 条事件，下修状态错了 22 只。
- 日 K 只为少数 featured 债拉，且逐只校验末根是否等于快照日（停牌/退市债
  的日 K 会陈旧，拿旧序列做通道判断等于篡改）。
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from . import facts as F
from . import rules as R


__all__ = ["DailyConfig", "fetch_snapshot", "run_daily"]

DEFAULT_BUDGET = 30


class DailyConfig:
    """一期日更的取数与选样参数。

    :param top_n: 榜单条数
    :param budget: 单期请求上限（超出即中止，不静默降级）
    :param price_bins: 价格分区边界（元）
    :param ytm_tax: 利息税率
    :param featured: 要拨测价格通道的个券（缺省取榜单前三）
    :param band_bars: 通道窗口交易日数
    """

    def __init__(self, *, top_n: int = 20, budget: int = DEFAULT_BUDGET,
                 price_bins: tuple[float, float, float] = (100.0, 110.0, 130.0),
                 ytm_tax: float = 0.20, featured: list[str] | None = None,
                 band_bars: int = 250) -> None:
        self.top_n = top_n
        self.budget = budget
        self.price_bins = price_bins
        self.ytm_tax = ytm_tax
        self.featured = featured
        self.band_bars = band_bars


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
    if as_of and snap_asof and as_of != snap_asof:
        # 允许 T-1：盘前跑时快照仍是上一交易日
        if abs((datetime.strptime(as_of, "%Y-%m-%d").date()
                - datetime.strptime(snap_asof, "%Y-%m-%d").date()).days) > 1:
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
        try:
            kw = cli.cbond.kline_window(code, cfg.band_bars)
            spend()
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
                "picks": len(picks), "rows": len(rows), "events": len(events)}
    return {"asOf": snap_asof, "rows": rows, "events": events,
            "featured_klines": featured_klines, "coverage": coverage,
            "intraday_risk": intraday}


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
    )
    payload["coverage"] = snap["coverage"]
    payload["intraday_risk"] = snap["intraday_risk"]
    payload["snapshot_asOf"] = snap["asOf"]
    return payload
