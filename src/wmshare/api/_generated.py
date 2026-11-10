# -*- coding: utf-8 -*-
"""自动生成：目录驱动的类型化命名空间门面 —— 勿手改。

由 tools/gen_typed_api.py 从数据目录生成；方法签名与 docstring 来自目录合同，
运行时统一委托 ``client.call()``（参数校验、max_limit 上限、normalize_with
规范化均在该层生效）。重新生成：

  python3 tools/gen_typed_api.py

命名解析优先级：友好层（wmshare.api 手写类）> 本层 > 通用 _Namespace。
"""
from __future__ import annotations

from typing import Any



class _Ns:
    """类型化命名空间基类。"""

    def __init__(self, client: Any) -> None:
        self._client = client


class BonusNS(_Ns):
    """分红（disc.bonus）"""

    def query_list(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """分红历史明细

:param sym: 6 位裸码
:param limit: 条数

:returns: ARR · 分红行（announce/ex_date/pay/dps/total/content/sas/payout_ratio）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("bonus.query_list", **kw, _raw=_raw, _df=_df)

    def query_last(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最近一次分红

:returns: 分红行 MAP 或 nil
        """
        return self._client.call("bonus.query_last", sym=sym, _raw=_raw, _df=_df)

    def query_at_sas(self, sym: str, sas: str, _raw: bool = False, _df: bool = False) -> Any:
        """指定报告期分红

:param sas: 报告期，如 "2024-Q4"

:returns: 分红行 MAP 或 nil
        """
        return self._client.call("bonus.query_at_sas", sym=sym, sas=sas, _raw=_raw, _df=_df)

    def dps_rpt(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """财报期每股分红

:returns: float · 财报期每股分红（元/股）
        """
        return self._client.call("bonus.dps_rpt", sym=sym, _raw=_raw, _df=_df)

    def dps_rpt_asof(self, rows: list, asof: str, _raw: bool = False, _df: bool = False) -> Any:
        """财报期每股分红（截至日）

:param rows: dps_rpt 结果
:param asof: 截至日期

:returns: 截至日的 DPS
        """
        return self._client.call("bonus.dps_rpt_asof", rows=rows, asof=asof, _raw=_raw, _df=_df)

    def query_dps_window(self, sym: str, window: str, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内每股股利合计

:param window: 窗口（如 3y）

:returns: float · 元/股
        """
        return self._client.call("bonus.query_dps_window", sym=sym, window=window, _raw=_raw, _df=_df)

    def query_total_window(self, sym: str, window: str, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内总分红

:returns: float · 元
        """
        return self._client.call("bonus.query_total_window", sym=sym, window=window, _raw=_raw, _df=_df)

    def query_count_window(self, sym: str, window: str, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内分红次数

:returns: int
        """
        return self._client.call("bonus.query_count_window", sym=sym, window=window, _raw=_raw, _df=_df)

    def query_valid(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """有效分红序列（过滤无效行）

:returns: ARR · 分红行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("bonus.query_valid", **kw, _raw=_raw, _df=_df)

    def snapshot(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股息快照

:returns: MAP · 股息/率快照
        """
        return self._client.call("bonus.snapshot", sym=sym, _raw=_raw, _df=_df)

    def snapshot_yield_ttm(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """LTM 股息率

:returns: float · 小数（0.0396 = 3.96%）
        """
        return self._client.call("bonus.snapshot_yield_ttm", sym=sym, _raw=_raw, _df=_df)

    def snapshot_payout_ttm(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """TTM 派息率

:returns: float · 小数（0.799 = 79.9%）
        """
        return self._client.call("bonus.snapshot_payout_ttm", sym=sym, _raw=_raw, _df=_df)

    def screen_active(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """近年有分红"""
        return self._client.call("bonus.screen_active", sym=sym, _raw=_raw, _df=_df)

    def screen_has_dividend(self, sym: str, min_yield: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """有分红记录"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return self._client.call("bonus.screen_has_dividend", **kw, _raw=_raw, _df=_df)

    def screen_high_yield(self, sym: str, min_yield: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """高股息"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return self._client.call("bonus.screen_high_yield", **kw, _raw=_raw, _df=_df)

    def screen_ample_payout(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """慷慨派息"""
        return self._client.call("bonus.screen_ample_payout", sym=sym, _raw=_raw, _df=_df)

    def screen_danger_payout(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """派息不可持续"""
        return self._client.call("bonus.screen_danger_payout", sym=sym, _raw=_raw, _df=_df)

    def screen_quality(self, sym: str, min_yield: Any | None = None, payout_min: Any | None = None, payout_max: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """分红质量优"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if payout_min is not None:
            kw["payout_min"] = payout_min
        if payout_max is not None:
            kw["payout_max"] = payout_max
        return self._client.call("bonus.screen_quality", **kw, _raw=_raw, _df=_df)

    def screen_stable_yield(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股息稳定"""
        return self._client.call("bonus.screen_stable_yield", sym=sym, _raw=_raw, _df=_df)

    def screen_improving_yield(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股息改善"""
        return self._client.call("bonus.screen_improving_yield", sym=sym, _raw=_raw, _df=_df)

    def screen_trend_ok(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """分红趋势健康"""
        return self._client.call("bonus.screen_trend_ok", sym=sym, _raw=_raw, _df=_df)

    def screen_declining_yield(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股息下滑"""
        return self._client.call("bonus.screen_declining_yield", sym=sym, _raw=_raw, _df=_df)

    def screen_undervalued_yield(self, sym: str, min_yield: Any | None = None, min_pct: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """低估+高股息"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if min_pct is not None:
            kw["min_pct"] = min_pct
        return self._client.call("bonus.screen_undervalued_yield", **kw, _raw=_raw, _df=_df)

    def index_where_active(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·有分红"""
        return self._client.call("bonus.index_where_active", _raw=_raw, _df=_df)

    def index_where_no_dividend(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·无分红"""
        return self._client.call("bonus.index_where_no_dividend", _raw=_raw, _df=_df)

    def index_where_has_dividend(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·有记录"""
        return self._client.call("bonus.index_where_has_dividend", _raw=_raw, _df=_df)

    def index_where_high_yield(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·高股息"""
        return self._client.call("bonus.index_where_high_yield", _raw=_raw, _df=_df)

    def index_where_high_yield_5(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·连续5年高股息"""
        return self._client.call("bonus.index_where_high_yield_5", _raw=_raw, _df=_df)

    def index_where_ample_payout(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·慷慨派息"""
        return self._client.call("bonus.index_where_ample_payout", _raw=_raw, _df=_df)

    def index_where_danger_payout(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·派息危险"""
        return self._client.call("bonus.index_where_danger_payout", _raw=_raw, _df=_df)

    def index_where_quality(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·质量"""
        return self._client.call("bonus.index_where_quality", _raw=_raw, _df=_df)

    def index_where_stable(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·稳定"""
        return self._client.call("bonus.index_where_stable", _raw=_raw, _df=_df)

    def index_where_improving(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·改善"""
        return self._client.call("bonus.index_where_improving", _raw=_raw, _df=_df)

    def index_where_declining(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·下滑"""
        return self._client.call("bonus.index_where_declining", _raw=_raw, _df=_df)

    def index_where_trend_up(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·趋势向上"""
        return self._client.call("bonus.index_where_trend_up", _raw=_raw, _df=_df)

    def index_where_undervalued(self, _raw: bool = False, _df: bool = False) -> Any:
        """where·低估"""
        return self._client.call("bonus.index_where_undervalued", _raw=_raw, _df=_df)

    def index_yield_bin_expr(self, _raw: bool = False, _df: bool = False) -> Any:
        """股息率分桶 where 表达式"""
        return self._client.call("bonus.index_yield_bin_expr", _raw=_raw, _df=_df)

    def index_field_load(self, idx: Any, fields: list, _raw: bool = False, _df: bool = False) -> Any:
        """分红索引字段预加载"""
        return self._client.call("bonus.index_field_load", idx=idx, fields=fields, _raw=_raw, _df=_df)

    def index_field_load_analysis(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """分红分析字段预加载"""
        return self._client.call("bonus.index_field_load_analysis", idx=idx, _raw=_raw, _df=_df)

    def index_fields_basic(self, _raw: bool = False, _df: bool = False) -> Any:
        """分红基础字段列表"""
        return self._client.call("bonus.index_fields_basic", _raw=_raw, _df=_df)

    def index_fields_analysis(self, _raw: bool = False, _df: bool = False) -> Any:
        """分红分析字段列表"""
        return self._client.call("bonus.index_fields_analysis", _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """分红行规范化

:returns: ARR · 规范化分红行
        """
        return self._client.call("bonus.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_lines(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """分红文本行"""
        return self._client.call("bonus.fmt_lines", rows=rows, _raw=_raw, _df=_df)

    def fmt_line(self, row: Any, _raw: bool = False, _df: bool = False) -> Any:
        """单条分红文本"""
        return self._client.call("bonus.fmt_line", row=row, _raw=_raw, _df=_df)

    def fmt_snapshot_line(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股息快照一行文本"""
        return self._client.call("bonus.fmt_snapshot_line", sym=sym, _raw=_raw, _df=_df)

class CbondNS(_Ns):
    """可转债（market.cbond）"""

    def board(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债全市场面板（快照+最新事件+盘中价+callHits+下修地板价）

:returns: ARR · 转债面板行（快照行 + event/resetEvent/outstanding/callHits/resetFloor 等）
        """
        return self._client.call("cbond.board", _raw=_raw, _df=_df)

    def quote_list(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债合约快照全表

:returns: ARR · 原始快照行（snake_case，未规范化）
        """
        return self._client.call("cbond.quote_list", _raw=_raw, _df=_df)

    def latest_quotes(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债最新快照

:returns: ARR · 规范化快照行（每债取 asOf 最新一行）
        """
        return self._client.call("cbond.latest_quotes", _raw=_raw, _df=_df)

    def of_stock(self, stk: Any, _raw: bool = False, _df: bool = False) -> Any:
        """正股关联转债

:returns: ARR · 该公司全部转债快照行（含已到期历史债，按 outstanding 过滤）
        """
        return self._client.call("cbond.of_stock", stk=stk, _raw=_raw, _df=_df)

    def fmt_quote(self, row: dict, _raw: bool = False, _df: bool = False) -> Any:
        """快照行规范化

:returns: MAP · 规范化快照行
        """
        return self._client.call("cbond.fmt_quote", row=row, _raw=_raw, _df=_df)

    def event_list(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债条款事件列表"""
        return self._client.call("cbond.event_list", _raw=_raw, _df=_df)

    def event_rows_of(self, sym: Any, _raw: bool = False, _df: bool = False) -> Any:
        """单标的条款事件"""
        return self._client.call("cbond.event_rows_of", sym=sym, _raw=_raw, _df=_df)

    def query(self, sym: Any, _raw: bool = False, _df: bool = False) -> Any:
        """按标的查条款事件"""
        return self._client.call("cbond.query", sym=sym, _raw=_raw, _df=_df)

    def fmt_event(self, row: dict, _raw: bool = False, _df: bool = False) -> Any:
        """条款事件行规范化"""
        return self._client.call("cbond.fmt_event", row=row, _raw=_raw, _df=_df)

    def call_hits(self, code: Any, trig: Any, _raw: bool = False, _df: bool = False) -> Any:
        """强赎触发计数

:returns: int · 近 30 个交易日正股收盘 ≥ 触发价的天数
        """
        return self._client.call("cbond.call_hits", code=code, trig=trig, _raw=_raw, _df=_df)

    def kline_window(self, code: Any, n: Any, _raw: bool = False, _df: bool = False) -> Any:
        """转债日K窗口"""
        return self._client.call("cbond.kline_window", code=code, n=n, _raw=_raw, _df=_df)

    def min1_live(self, code: Any, _raw: bool = False, _df: bool = False) -> Any:
        """转债盘中1分钟"""
        return self._client.call("cbond.min1_live", code=code, _raw=_raw, _df=_df)

    def min1_meta(self, code: Any, _raw: bool = False, _df: bool = False) -> Any:
        """转债盘中元信息"""
        return self._client.call("cbond.min1_meta", code=code, _raw=_raw, _df=_df)

    def universe_codes(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债代码全集"""
        return self._client.call("cbond.universe_codes", _raw=_raw, _df=_df)

class EquityNS(_Ns):
    """股东与股本（corp.equity）"""

    def query_holder10(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新一期十大股东"""
        return self._client.call("equity.query_holder10", sym=sym, _raw=_raw, _df=_df)

    def query_holdernum(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新股东户数"""
        return self._client.call("equity.query_holdernum", sym=sym, _raw=_raw, _df=_df)

    def query_pledge_detail(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """主要股东质押明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_pledge_detail", **kw, _raw=_raw, _df=_df)

    def query_pledge_summary(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """公司质押比例"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_pledge_summary", **kw, _raw=_raw, _df=_df)

    def query_pledge_market(self, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """市场整体质押"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_pledge_market", **kw, _raw=_raw, _df=_df)

    def query_pledge_industry(self, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """行业质押比例"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_pledge_industry", **kw, _raw=_raw, _df=_df)

    def query_pledge_org(self, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """质押机构分布"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_pledge_org", **kw, _raw=_raw, _df=_df)

    def query_institution_detail(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """机构持股明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_institution_detail", **kw, _raw=_raw, _df=_df)

    def query_institution_summary(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """机构持仓占比"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_institution_summary", **kw, _raw=_raw, _df=_df)

    def query_hgt(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """沪港通持股"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_hgt", **kw, _raw=_raw, _df=_df)

    def query_national_team(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """国家队持股"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_national_team", **kw, _raw=_raw, _df=_df)

    def query_release(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """限售解禁日程"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_release", **kw, _raw=_raw, _df=_df)

    def query_buyback_plan(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """回购方案全览"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_buyback_plan", **kw, _raw=_raw, _df=_df)

    def query_buyback_detail(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """回购执行明细"""
        return self._client.call("equity.query_buyback_detail", sym=sym, _raw=_raw, _df=_df)

    def query_reorg(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """并购重组"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_reorg", **kw, _raw=_raw, _df=_df)

    def query_related_trade(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """关联交易"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_related_trade", **kw, _raw=_raw, _df=_df)

    def query_concert(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """一致行动人"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_concert", **kw, _raw=_raw, _df=_df)

    def query_guarantee(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """对外担保"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_guarantee", **kw, _raw=_raw, _df=_df)

    def query_litigation(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """诉讼记录"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_litigation", **kw, _raw=_raw, _df=_df)

    def query_violation(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """违规处罚"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("equity.query_violation", **kw, _raw=_raw, _df=_df)

    def query_executives(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """高管名册"""
        return self._client.call("equity.query_executives", sym=sym, _raw=_raw, _df=_df)

    def query_exec_change(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """高管增减持最新"""
        return self._client.call("equity.query_exec_change", sym=sym, _raw=_raw, _df=_df)

    def query_exec_change_at(self, sym: str, annual: int, sampling: str, _raw: bool = False, _df: bool = False) -> Any:
        """指定报告期增减持"""
        return self._client.call("equity.query_exec_change_at", sym=sym, annual=annual, sampling=sampling, _raw=_raw, _df=_df)

    def query_capital_change(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """股本结构最新"""
        return self._client.call("equity.query_capital_change", sym=sym, _raw=_raw, _df=_df)

    def query_capital_change_at(self, sym: str, annual: int, sampling: str, _raw: bool = False, _df: bool = False) -> Any:
        """指定报告期股本"""
        return self._client.call("equity.query_capital_change_at", sym=sym, annual=annual, sampling=sampling, _raw=_raw, _df=_df)

    def fmt_holder10(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """十大股东行规范化"""
        return self._client.call("equity.fmt_holder10", rows=rows, _raw=_raw, _df=_df)

    def fmt_holdernum(self, props: Any, _raw: bool = False, _df: bool = False) -> Any:
        """股东户数规范化"""
        return self._client.call("equity.fmt_holdernum", props=props, _raw=_raw, _df=_df)

    def fmt_pledge_detail(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """质押明细规范化"""
        return self._client.call("equity.fmt_pledge_detail", rows=rows, _raw=_raw, _df=_df)

    def fmt_pledge_summary(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """质押比例规范化"""
        return self._client.call("equity.fmt_pledge_summary", rows=rows, _raw=_raw, _df=_df)

    def fmt_pledge_market(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """市场质押规范化"""
        return self._client.call("equity.fmt_pledge_market", rows=rows, _raw=_raw, _df=_df)

    def fmt_pledge_industry(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """行业质押规范化"""
        return self._client.call("equity.fmt_pledge_industry", rows=rows, _raw=_raw, _df=_df)

    def fmt_pledge_org(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """质押机构分布规范化"""
        return self._client.call("equity.fmt_pledge_org", rows=rows, _raw=_raw, _df=_df)

    def fmt_institution_detail(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """机构明细规范化"""
        return self._client.call("equity.fmt_institution_detail", rows=rows, _raw=_raw, _df=_df)

    def fmt_institution_summary(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """机构占比规范化"""
        return self._client.call("equity.fmt_institution_summary", rows=rows, _raw=_raw, _df=_df)

    def fmt_hgt(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """沪港通行规范化"""
        return self._client.call("equity.fmt_hgt", rows=rows, _raw=_raw, _df=_df)

    def fmt_national_team(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """国家队行规范化"""
        return self._client.call("equity.fmt_national_team", rows=rows, _raw=_raw, _df=_df)

    def fmt_release(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """解禁行规范化"""
        return self._client.call("equity.fmt_release", rows=rows, _raw=_raw, _df=_df)

    def fmt_buyback_plan(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """回购方案行规范化"""
        return self._client.call("equity.fmt_buyback_plan", rows=rows, _raw=_raw, _df=_df)

    def fmt_buyback_detail(self, props: Any, _raw: bool = False, _df: bool = False) -> Any:
        """回购明细规范化"""
        return self._client.call("equity.fmt_buyback_detail", props=props, _raw=_raw, _df=_df)

    def fmt_reorg(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """重组行规范化"""
        return self._client.call("equity.fmt_reorg", rows=rows, _raw=_raw, _df=_df)

    def fmt_related_trade(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """关联交易行规范化"""
        return self._client.call("equity.fmt_related_trade", rows=rows, _raw=_raw, _df=_df)

    def fmt_concert(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """一致行动人行规范化"""
        return self._client.call("equity.fmt_concert", rows=rows, _raw=_raw, _df=_df)

    def fmt_guarantee(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """担保行规范化"""
        return self._client.call("equity.fmt_guarantee", rows=rows, _raw=_raw, _df=_df)

    def fmt_litigation(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """诉讼行规范化"""
        return self._client.call("equity.fmt_litigation", rows=rows, _raw=_raw, _df=_df)

    def fmt_violation(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """处罚行规范化"""
        return self._client.call("equity.fmt_violation", rows=rows, _raw=_raw, _df=_df)

    def fmt_executives(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """高管行规范化"""
        return self._client.call("equity.fmt_executives", rows=rows, _raw=_raw, _df=_df)

    def fmt_exec_change(self, props: Any, _raw: bool = False, _df: bool = False) -> Any:
        """增减持行规范化"""
        return self._client.call("equity.fmt_exec_change", props=props, _raw=_raw, _df=_df)

    def fmt_capital_change(self, props: Any, _raw: bool = False, _df: bool = False) -> Any:
        """股本行规范化"""
        return self._client.call("equity.fmt_capital_change", props=props, _raw=_raw, _df=_df)

    def fmt_lines(self, maps: list, _raw: bool = False, _df: bool = False) -> Any:
        """规范化行转文本"""
        return self._client.call("equity.fmt_lines", maps=maps, _raw=_raw, _df=_df)

class EstimatesNS(_Ns):
    """盈利预测与研报（fund.estimates）"""

    def query_forecast(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """机构盈利预测"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("estimates.query_forecast", **kw, _raw=_raw, _df=_df)

    def query_forecast_detail(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """盈利预测明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("estimates.query_forecast_detail", **kw, _raw=_raw, _df=_df)

    def query_rating(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """评级统计"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("estimates.query_rating", **kw, _raw=_raw, _df=_df)

    def query_reports(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """个股研报"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("estimates.query_reports", **kw, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """预测行规范化"""
        return self._client.call("estimates.fmt_maps", rows=rows, _raw=_raw, _df=_df)

class FilingsNS(_Ns):
    """定期报告清单（disc.filings）"""

    def query(self, sym: str, type_key: str = 'all', limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """定期报告列表

:param sym: 6 位裸码

:returns: ARR · 报告行（报告期/类型/标题/PDF 链接）
        """
        kw: dict[str, Any] = {"sym": sym}
        if type_key is not None:
            kw["type_key"] = type_key
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("filings.query", **kw, _raw=_raw, _df=_df)

    def latest(self, sym: str, type_key: str = 'all', _raw: bool = False, _df: bool = False) -> Any:
        """最新一条定期报告

:returns: 报告行 MAP 或 nil
        """
        kw: dict[str, Any] = {"sym": sym}
        if type_key is not None:
            kw["type_key"] = type_key
        return self._client.call("filings.latest", **kw, _raw=_raw, _df=_df)

    def type_zh(self, type_key: str, _raw: bool = False, _df: bool = False) -> Any:
        """type_key 转中文"""
        return self._client.call("filings.type_zh", type_key=type_key, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """报告行规范化列表"""
        return self._client.call("filings.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_map(self, row: dict, _raw: bool = False, _df: bool = False) -> Any:
        """单条报告规范化"""
        return self._client.call("filings.fmt_map", row=row, _raw=_raw, _df=_df)

    def fmt_date_short(self, raw: str, _raw: bool = False, _df: bool = False) -> Any:
        """日期缩短 YYYY-MM-DD"""
        return self._client.call("filings.fmt_date_short", raw=raw, _raw=_raw, _df=_df)

class ForecastNS(_Ns):
    """业绩披露事件（disc.events）"""

    def yjyg_rows(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """业绩预告历史

:param sym: 6 位裸码
:param limit: 条数

:returns: ARR · 预告行（报告期/类型/净利与扣非区间/同比/修正轨迹）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("forecast.yjyg_rows", **kw, _raw=_raw, _df=_df)

    def yjyg_latest(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新业绩预告

:returns: 预告行 MAP 或 nil
        """
        return self._client.call("forecast.yjyg_latest", sym=sym, _raw=_raw, _df=_df)

    def yjkb_rows(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """业绩快报历史

:returns: ARR · 快报行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("forecast.yjkb_rows", **kw, _raw=_raw, _df=_df)

    def yjkb_latest(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新业绩快报

:returns: 快报行 MAP 或 nil
        """
        return self._client.call("forecast.yjkb_latest", sym=sym, _raw=_raw, _df=_df)

    def disclosure_rows(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """财报预约披露历史

:returns: ARR · 预约披露行（报告期/计划披露日）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("forecast.disclosure_rows", **kw, _raw=_raw, _df=_df)

    def disclosure_next(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """下次财报披露

:returns: 预约披露行 MAP 或 nil
        """
        return self._client.call("forecast.disclosure_next", sym=sym, _raw=_raw, _df=_df)

    def snapshot(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """业绩披露快照（预告+快报+日历合并视图）

:returns: MAP · 快照
        """
        return self._client.call("forecast.snapshot", sym=sym, _raw=_raw, _df=_df)

    def fmt_line(self, row: Any, _raw: bool = False, _df: bool = False) -> Any:
        """预告文本行"""
        return self._client.call("forecast.fmt_line", row=row, _raw=_raw, _df=_df)

    def fmt_lines(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """预告文本行列表"""
        return self._client.call("forecast.fmt_lines", rows=rows, _raw=_raw, _df=_df)

class IndicesNS(_Ns):
    """指数（market.index）"""

    def keys(self, _raw: bool = False, _df: bool = False) -> Any:
        """指数键列表"""
        return self._client.call("indices.keys", _raw=_raw, _df=_df)

    def members(self, key: str, sort_by: str | None = None, top_n: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指数成分"""
        kw: dict[str, Any] = {"key": key}
        if sort_by is not None:
            kw["sort_by"] = sort_by
        if top_n is not None:
            kw["top_n"] = top_n
        return self._client.call("indices.members", **kw, _raw=_raw, _df=_df)

    def weights(self, key: str, top_n: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指数权重股"""
        kw: dict[str, Any] = {"key": key}
        if top_n is not None:
            kw["top_n"] = top_n
        return self._client.call("indices.weights", **kw, _raw=_raw, _df=_df)

    def valuation(self, key: str, points: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指数估值时序"""
        kw: dict[str, Any] = {"key": key}
        if points is not None:
            kw["points"] = points
        return self._client.call("indices.valuation", **kw, _raw=_raw, _df=_df)

    def trend(self, key: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指数估值趋势(周频整体法)"""
        kw: dict[str, Any] = {"key": key}
        if window is not None:
            kw["window"] = window
        return self._client.call("indices.trend", **kw, _raw=_raw, _df=_df)

    def universe_keys(self, group: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指数域可用键"""
        kw: dict[str, Any] = {}
        if group is not None:
            kw["group"] = group
        return self._client.call("indices.universe_keys", **kw, _raw=_raw, _df=_df)

class IntlNS(_Ns):
    """港美股披露（market.intl）"""

    def query_ccass(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """港股CCASS持仓"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("intl.query_ccass", **kw, _raw=_raw, _df=_df)

    def query_shareholders(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """港股主要股东"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("intl.query_shareholders", **kw, _raw=_raw, _df=_df)

    def query_org_rating(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """港股机构评级"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("intl.query_org_rating", **kw, _raw=_raw, _df=_df)

    def query_profit_forecast(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """港股盈利预测"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("intl.query_profit_forecast", **kw, _raw=_raw, _df=_df)

    def query_sellshort(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """港美沽空"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("intl.query_sellshort", **kw, _raw=_raw, _df=_df)

    def issue_info(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """美股发行信息"""
        return self._client.call("intl.issue_info", sym=sym, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """港美股行规范化"""
        return self._client.call("intl.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_issue(self, props: Any, _raw: bool = False, _df: bool = False) -> Any:
        """发行行规范化"""
        return self._client.call("intl.fmt_issue", props=props, _raw=_raw, _df=_df)

class KlineNS(_Ns):
    """行情K线（market.kline）"""

    def query_bars(self, sym: str, limit: int = 120, _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线

:param sym: 6 位裸码（自动剥 cn./sh. 前缀与 .SH/.SZ/.BJ 后缀）
:param limit: 根数，默认 120

:returns: ARR · bars（date/open/high/low/close/volume/amount/percent）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("kline.query_bars", **kw, _raw=_raw, _df=_df)

    def query_bars_period(self, sym: str, limit: int = 120, period: str = 'D', _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线（周/月周期）

:param sym: 标的裸码（A股 6 位 / 港股 5 位 / 美股 ticker）
:param limit: 根数（按所选周期计），默认 120
:param period: 周期 D=日 / W=周 / M=月（未知值按 D）

:returns: ARR · bars（date/open/high/low/close/volume/amount/percent）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        if period is not None:
            kw["period"] = period
        return self._client.call("kline.query_bars_period", **kw, _raw=_raw, _df=_df)

    def query_bars_period_adj(self, sym: str, limit: int = 120, period: str = 'D', adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线（周/月周期·复权）

:param sym: 标的裸码
:param limit: 根数（按所选周期计）
:param period: 周期 D/W/M
:param adj: 复权口径 nr(不复权,默认)/qfq(前复权)/hfq(后复权)

:returns: ARR · bars（字段同 query_bars_period）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        if period is not None:
            kw["period"] = period
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_bars_period_adj", **kw, _raw=_raw, _df=_df)

    def query_last(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新一根 K 线

:param sym: 6 位裸码

:returns: MAP · bar 或 nil
        """
        return self._client.call("kline.query_last", sym=sym, _raw=_raw, _df=_df)

    def is_etf(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """是否场内 ETF

:returns: bool · true=场内 ETF
        """
        return self._client.call("kline.is_etf", sym=sym, _raw=_raw, _df=_df)

    def query_last_live(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """盘中日K快照

:returns: MAP · 盘中 bar（date/ohlcv/amount/percent/mv/source）
        """
        return self._client.call("kline.query_last_live", sym=sym, _raw=_raw, _df=_df)

    def query_last_live_many(self, syms: list, _raw: bool = False, _df: bool = False) -> Any:
        """盘中日K批量快照

:param syms: 裸码列表

:returns: MAP · symbol → bar
        """
        return self._client.call("kline.query_last_live_many", syms=syms, _raw=_raw, _df=_df)

    def query_bars_live(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """盘中拉最近 n 根日K（外部行情源 HTTP，≠分时）

:param limit: 最近 n 个交易日

:returns: ARR · bars
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("kline.query_bars_live", **kw, _raw=_raw, _df=_df)

    def query_min1_live(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """当日 1 分钟分时（有损滚桶）

:returns: MAP · 分时包 {trading_day, bars:[t,hm,close,volume,amount,...], bar_n}；休市读上一交易日
        """
        return self._client.call("kline.query_min1_live", sym=sym, _raw=_raw, _df=_df)

    def query_min1_live_meta(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """分时头（无 bars）

:returns: MAP · {trading_day, updated_at, bar_n}
        """
        return self._client.call("kline.query_min1_live_meta", sym=sym, _raw=_raw, _df=_df)

    def snapshot(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """单股行情快照

:returns: MAP · {symbol, close, percent, chg_20d}
        """
        return self._client.call("kline.snapshot", sym=sym, _raw=_raw, _df=_df)

    def screen_above_ma20(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """收盘价在 MA20 之上

:returns: bool
        """
        return self._client.call("kline.screen_above_ma20", sym=sym, _raw=_raw, _df=_df)

    def screen_momentum_20d(self, sym: str, min_chg: float, _raw: bool = False, _df: bool = False) -> Any:
        """近 20 日涨幅达标

:param min_chg: 如 0.1 = 10%

:returns: bool
        """
        return self._client.call("kline.screen_momentum_20d", sym=sym, min_chg=min_chg, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """K 线规范化 MAP 列表

:param rows: query_bars 等返回的 bars

:returns: ARR · 规范化 bar MAP
        """
        return self._client.call("kline.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_lines(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """K 线文本行

:returns: ARR · 文本
        """
        return self._client.call("kline.fmt_lines", rows=rows, _raw=_raw, _df=_df)

    def index_breadth_summary(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """全市场涨跌全景

:param idx: 服务端索引键（动态解析、无稳定字面量；推荐经 cli.screener 门面免传）

:returns: MAP · 涨跌统计
        """
        return self._client.call("kline.index_breadth_summary", idx=idx, _raw=_raw, _df=_df)

    def index_top_movers(self, idx: Any, limit: int | None = None, desc: bool | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌榜

:param desc: true=涨幅榜

:returns: ARR · 行
        """
        kw: dict[str, Any] = {"idx": idx}
        if limit is not None:
            kw["limit"] = limit
        if desc is not None:
            kw["desc"] = desc
        return self._client.call("kline.index_top_movers", **kw, _raw=_raw, _df=_df)

    def index_pct_bin_expr(self, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌幅分桶 where 表达式

:returns: string · 可用于 INDEX_QUERY where
        """
        return self._client.call("kline.index_pct_bin_expr", _raw=_raw, _df=_df)

    def query_bars_adj(self, sym: str, limit: int, adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_bars_adj", **kw, _raw=_raw, _df=_df)

    def query_bars_props(self, sym: str, limit: int, props: list | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线（指定字段）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if props is not None:
            kw["props"] = props
        return self._client.call("kline.query_bars_props", **kw, _raw=_raw, _df=_df)

    def query_bars_props_adj(self, sym: str, limit: int, props: list, adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """历史 K 线（字段+复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit, "props": props}
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_bars_props_adj", **kw, _raw=_raw, _df=_df)

    def query_last_adj(self, sym: str, adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """最新一根 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym}
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_last_adj", **kw, _raw=_raw, _df=_df)

    def query_valid(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """有效 K 线序列（过滤停牌空bar）"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("kline.query_valid", **kw, _raw=_raw, _df=_df)

    def query_valid_adj(self, sym: str, limit: int, adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """有效 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_valid_adj", **kw, _raw=_raw, _df=_df)

    def query_at_anchor(self, sym: str, limit: int, anchor_date: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """锚点日前 K 线"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if anchor_date is not None:
            kw["anchor_date"] = anchor_date
        return self._client.call("kline.query_at_anchor", **kw, _raw=_raw, _df=_df)

    def query_at_anchor_adj(self, sym: str, limit: int, anchor_date: str, adj: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """锚点日前 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit, "anchor_date": anchor_date}
        if adj is not None:
            kw["adj"] = adj
        return self._client.call("kline.query_at_anchor_adj", **kw, _raw=_raw, _df=_df)

    def snapshot_close(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新收盘价"""
        return self._client.call("kline.snapshot_close", sym=sym, _raw=_raw, _df=_df)

    def snapshot_percent(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新涨跌幅"""
        return self._client.call("kline.snapshot_percent", sym=sym, _raw=_raw, _df=_df)

    def snapshot_chg_20d(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """近 20 日涨跌幅"""
        return self._client.call("kline.snapshot_chg_20d", sym=sym, _raw=_raw, _df=_df)

    def screen_above_ma60(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """收盘价在 MA60 之上"""
        return self._client.call("kline.screen_above_ma60", sym=sym, _raw=_raw, _df=_df)

    def screen_above_ma120(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """收盘价在 MA120 之上"""
        return self._client.call("kline.screen_above_ma120", sym=sym, _raw=_raw, _df=_df)

    def screen_breakout_ma20(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """突破 MA20"""
        return self._client.call("kline.screen_breakout_ma20", sym=sym, _raw=_raw, _df=_df)

    def screen_ma60_up(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """MA60 上行"""
        return self._client.call("kline.screen_ma60_up", sym=sym, _raw=_raw, _df=_df)

    def screen_active(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """当日有成交"""
        return self._client.call("kline.screen_active", sym=sym, _raw=_raw, _df=_df)

    def screen_up_today(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """今日上涨"""
        return self._client.call("kline.screen_up_today", sym=sym, _raw=_raw, _df=_df)

    def screen_down_today(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """今日下跌"""
        return self._client.call("kline.screen_down_today", sym=sym, _raw=_raw, _df=_df)

    def screen_flat_today(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """今日平盘"""
        return self._client.call("kline.screen_flat_today", sym=sym, _raw=_raw, _df=_df)

    def screen_limit_up(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """涨停"""
        return self._client.call("kline.screen_limit_up", sym=sym, _raw=_raw, _df=_df)

    def screen_limit_down(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """跌停"""
        return self._client.call("kline.screen_limit_down", sym=sym, _raw=_raw, _df=_df)

    def screen_pullback_20d(self, sym: str, min_chg: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """近 20 日回撤可控"""
        kw: dict[str, Any] = {"sym": sym}
        if min_chg is not None:
            kw["min_chg"] = min_chg
        return self._client.call("kline.screen_pullback_20d", **kw, _raw=_raw, _df=_df)

    def screen_volume_spike(self, sym: str, min_ratio: Any | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """放量"""
        kw: dict[str, Any] = {"sym": sym}
        if min_ratio is not None:
            kw["min_ratio"] = min_ratio
        return self._client.call("kline.screen_volume_spike", **kw, _raw=_raw, _df=_df)

    def query_index_last_live(self, key: str, _raw: bool = False, _df: bool = False) -> Any:
        """指数盘中点位"""
        return self._client.call("kline.query_index_last_live", key=key, _raw=_raw, _df=_df)

    def query_index_last_live_many(self, keys: list, _raw: bool = False, _df: bool = False) -> Any:
        """指数盘中点位批量"""
        return self._client.call("kline.query_index_last_live_many", keys=keys, _raw=_raw, _df=_df)

    def query_index_min1_live(self, key: str, _raw: bool = False, _df: bool = False) -> Any:
        """指数盘中 1 分钟分时"""
        return self._client.call("kline.query_index_min1_live", key=key, _raw=_raw, _df=_df)

    def query_index_min1_live_meta(self, key: str, _raw: bool = False, _df: bool = False) -> Any:
        """指数分时头"""
        return self._client.call("kline.query_index_min1_live_meta", key=key, _raw=_raw, _df=_df)

    def index_breadth_bins(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌幅分桶结果"""
        return self._client.call("kline.index_breadth_bins", idx=idx, _raw=_raw, _df=_df)

    def index_breadth_bin_industries(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """分桶行业分布"""
        return self._client.call("kline.index_breadth_bin_industries", idx=idx, _raw=_raw, _df=_df)

    def index_field_load(self, idx: Any, fields: list, _raw: bool = False, _df: bool = False) -> Any:
        """索引字段预加载"""
        return self._client.call("kline.index_field_load", idx=idx, fields=fields, _raw=_raw, _df=_df)

    def index_field_load_analysis(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """分析字段预加载"""
        return self._client.call("kline.index_field_load_analysis", idx=idx, _raw=_raw, _df=_df)

    def index_field_load_breadth(self, idx: Any, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌全景字段预加载"""
        return self._client.call("kline.index_field_load_breadth", idx=idx, _raw=_raw, _df=_df)

    def index_fields_basic(self, _raw: bool = False, _df: bool = False) -> Any:
        """基础字段列表"""
        return self._client.call("kline.index_fields_basic", _raw=_raw, _df=_df)

    def index_fields_analysis(self, _raw: bool = False, _df: bool = False) -> Any:
        """分析字段列表"""
        return self._client.call("kline.index_fields_analysis", _raw=_raw, _df=_df)

    def index_fields_breadth(self, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌全景字段列表"""
        return self._client.call("kline.index_fields_breadth", _raw=_raw, _df=_df)

    def fmt_line(self, row: Any, _raw: bool = False, _df: bool = False) -> Any:
        """单根 K 线文本"""
        return self._client.call("kline.fmt_line", row=row, _raw=_raw, _df=_df)

    def fmt_snapshot_line(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """快照一行文本"""
        return self._client.call("kline.fmt_snapshot_line", sym=sym, _raw=_raw, _df=_df)

    def fmt_bins(self, bins_raw: Any, total_count: int, _raw: bool = False, _df: bool = False) -> Any:
        """涨跌幅分桶格式化"""
        return self._client.call("kline.fmt_bins", bins_raw=bins_raw, total_count=total_count, _raw=_raw, _df=_df)

class MacroNS(_Ns):
    """宏观（market.macro）"""

    def query(self, code: str, n: int = 4, _raw: bool = False, _df: bool = False) -> Any:
        """宏观时序

:param code: 指标码或名称（$CPI / cpi 均可，服务端自动归一为 $CPI 形态）
:param n: 期数（1–48，超出按边界取）

:returns: MAP · ok/metric/store/frequency/periods/latest/series（series 每点含 sas/annual/sampling/value）
        """
        kw: dict[str, Any] = {"code": code}
        if n is not None:
            kw["n"] = n
        return self._client.call("macro.query", **kw, _raw=_raw, _df=_df)

    def asof(self, code: str, _raw: bool = False, _df: bool = False) -> Any:
        """宏观 as-of 单点

:param code: 指标码或名称（同 query；人口类序列勿用）

:returns: 最新一期原生值（无数据返回 nil）
        """
        return self._client.call("macro.asof", code=code, _raw=_raw, _df=_df)

    def spots(self, code: str, n: int = 4, _raw: bool = False, _df: bool = False) -> Any:
        """宏观原生点列

:param code: 指标码或名称
:param n: 期数（1–48）

:returns: ARR · 原生采样期点
        """
        kw: dict[str, Any] = {"code": code}
        if n is not None:
            kw["n"] = n
        return self._client.call("macro.spots", **kw, _raw=_raw, _df=_df)

    def sampling_of(self, code: str, _raw: bool = False, _df: bool = False) -> Any:
        """宏观指标原生采样频率

:param code: 指标码或名称

:returns: "month"/"quarter"/"year"/"day"（无法判定时回退 "month"）
        """
        return self._client.call("macro.sampling_of", code=code, _raw=_raw, _df=_df)

    def bond_curve(self, curve_name: str, tenor: str, _raw: bool = False, _df: bool = False) -> Any:
        """中债收益率按曲线名+期限

:param curve_name: 曲线披露名（如「中债国债收益率曲线」）
:param tenor: 期限列名（如「10年」「1年」）

:returns: 该曲线该期限的最新收益率原值
        """
        return self._client.call("macro.bond_curve", curve_name=curve_name, tenor=tenor, _raw=_raw, _df=_df)

    def nev_monthly(self, brand: str, field: str, _raw: bool = False, _df: bool = False) -> Any:
        """新势力月交付

:param brand: 品牌披露名（如「零跑」「小米」）
:param field: 取值列（sales/rank）

:returns: 当月单值（掉榜返回 nil）
        """
        return self._client.call("macro.nev_monthly", brand=brand, field=field, _raw=_raw, _df=_df)

    def nev_weekly(self, brand: str, field: str, _raw: bool = False, _df: bool = False) -> Any:
        """新势力周销量

:param brand: 品牌披露名
:param field: 取值列（sales/rank）

:returns: 当周单值（掉榜返回 nil）
        """
        return self._client.call("macro.nev_weekly", brand=brand, field=field, _raw=_raw, _df=_df)

    def avc_monthly(self, category: str, field: str, _raw: bool = False, _df: bool = False) -> Any:
        """奥维家电品类月度

:param category: 品类披露名（如「消费级摄像头」）
:param field: 取值列（volume/volume_yoy/value/value_yoy）

:returns: 当月单值（掉榜返回 nil）
        """
        return self._client.call("macro.avc_monthly", category=category, field=field, _raw=_raw, _df=_df)

    def chinaiol_monthly(self, category: str, field: str, _raw: bool = False, _df: bool = False) -> Any:
        """家电产销月度

:param category: 品类披露名（如「洗衣机」）
:param field: 取值列（volume=内销量/volume_yoy/value=内销额/value_yoy）

:returns: 当月单值（掉榜返回 nil）
        """
        return self._client.call("macro.chinaiol_monthly", category=category, field=field, _raw=_raw, _df=_df)

    def cpca_top(self, manufacturer: str, field: str, _raw: bool = False, _df: bool = False) -> Any:
        """乘联会厂商排行

:param manufacturer: 厂商披露名（如「比亚迪汽车」）
:param field: 取值列（如 wholesale/retail）

:returns: 当月单值（掉榜返回 nil）
        """
        return self._client.call("macro.cpca_top", manufacturer=manufacturer, field=field, _raw=_raw, _df=_df)

    def phone_share(self, brand: str, field: str = 'share', _raw: bool = False, _df: bool = False) -> Any:
        """手机品牌周份额

:param brand: 品牌披露名（如「小米」）
:param field: 取值列（share/rank）

:returns: 当周单值（掉榜返回 nil）
        """
        kw: dict[str, Any] = {"brand": brand}
        if field is not None:
            kw["field"] = field
        return self._client.call("macro.phone_share", **kw, _raw=_raw, _df=_df)

class MarginNS(_Ns):
    """融资融券（market.margin）"""

    def query(self, sym: str, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """个股融资融券"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("margin.query", **kw, _raw=_raw, _df=_df)

    def latest(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新两融"""
        return self._client.call("margin.latest", sym=sym, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: Any, _raw: bool = False, _df: bool = False) -> Any:
        """两融行规范化"""
        return self._client.call("margin.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_line(self, row: Any, _raw: bool = False, _df: bool = False) -> Any:
        """两融单行文本"""
        return self._client.call("margin.fmt_line", row=row, _raw=_raw, _df=_df)

class MoneyflowNS(_Ns):
    """资金流向（market.moneyflow）"""

    def query_bars(self, sym: str, limit: int = 20, _raw: bool = False, _df: bool = False) -> Any:
        """资金流向历史

:param sym: 6 位裸码
:param limit: 根数，默认 20

:returns: ARR · 资金流行（date/net_mf/elg_net/lg_net/md_net/sm_net）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("moneyflow.query_bars", **kw, _raw=_raw, _df=_df)

    def query_last(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新资金流向

:returns: 资金流行 MAP 或 nil
        """
        return self._client.call("moneyflow.query_last", sym=sym, _raw=_raw, _df=_df)

    def query_valid(self, sym: str, limit: int = 20, _raw: bool = False, _df: bool = False) -> Any:
        """有效资金流向（过滤空行）

:returns: ARR · 资金流行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("moneyflow.query_valid", **kw, _raw=_raw, _df=_df)

    def query_last_live(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """资金流当日读数（外部源）

:returns: MAP · 资金流快照
        """
        return self._client.call("moneyflow.query_last_live", sym=sym, _raw=_raw, _df=_df)

    def snapshot(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """资金流向快照

:returns: MAP · 快照
        """
        return self._client.call("moneyflow.snapshot", sym=sym, _raw=_raw, _df=_df)

    def snapshot_net_mf(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """最新主力净流入

:returns: float · 主力净流入（元）
        """
        return self._client.call("moneyflow.snapshot_net_mf", sym=sym, _raw=_raw, _df=_df)

    def board(self, _raw: bool = False, _df: bool = False) -> Any:
        """全市场资金流快照

:returns: ARR · 资金流行（symbol/name/net_mf/net_mv_ratio/lg_net/elg_net/md_net/sm_net/industry，按主力净流入降序）
        """
        return self._client.call("moneyflow.board", _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """资金流行规范化"""
        return self._client.call("moneyflow.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_lines(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """资金流文本行"""
        return self._client.call("moneyflow.fmt_lines", rows=rows, _raw=_raw, _df=_df)

    def fmt_line(self, row: Any, _raw: bool = False, _df: bool = False) -> Any:
        """单条资金流文本"""
        return self._client.call("moneyflow.fmt_line", row=row, _raw=_raw, _df=_df)

    def fmt_snapshot_line(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """资金流快照一行文本"""
        return self._client.call("moneyflow.fmt_snapshot_line", sym=sym, _raw=_raw, _df=_df)

class NoticeNS(_Ns):
    """公告（disc.notice）"""

    def query_by_symbol(self, sym: str, window: str | None = None, type_regex: str | None = None, limit: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """单票公告列表

:param sym: 6 位裸码（港股 5 位）
:param window: 时间窗
:param type_regex: 类型正则

:returns: ARR · 公告行（date/title/type/url/pdf_url）
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if limit is not None:
            kw["limit"] = limit
        return self._client.call("notice.query_by_symbol", **kw, _raw=_raw, _df=_df)

    def query_recent(self, window: str | None = None, type_regex: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """近期公告（全市场）

:param market: 缺省 cn

:returns: ARR · 公告行（date/title/type/url/pdf_url）
        """
        kw: dict[str, Any] = {}
        if window is not None:
            kw["window"] = window
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if limit is not None:
            kw["limit"] = limit
        if market is not None:
            kw["market"] = market
        return self._client.call("notice.query_recent", **kw, _raw=_raw, _df=_df)

    def query_by_category(self, category: str, window: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """按类别查公告

:returns: ARR · 公告行（date/title/type/url/pdf_url）
        """
        kw: dict[str, Any] = {"category": category}
        if window is not None:
            kw["window"] = window
        if limit is not None:
            kw["limit"] = limit
        if market is not None:
            kw["market"] = market
        return self._client.call("notice.query_by_category", **kw, _raw=_raw, _df=_df)

    def query_on_date(self, date: str, type_regex: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指定日期公告

:returns: ARR · 公告行（date/title/type/url/pdf_url）
        """
        kw: dict[str, Any] = {"date": date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if limit is not None:
            kw["limit"] = limit
        if market is not None:
            kw["market"] = market
        return self._client.call("notice.query_on_date", **kw, _raw=_raw, _df=_df)

    def query_find(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """按日期区间查公告

:returns: ARR · 公告行（date/title/type/url/pdf_url）
        """
        kw: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if stock_code is not None:
            kw["stock_code"] = stock_code
        if limit is not None:
            kw["limit"] = limit
        if market is not None:
            kw["market"] = market
        return self._client.call("notice.query_find", **kw, _raw=_raw, _df=_df)

    def signal_has_buyback(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否有回购公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_has_buyback", **kw, _raw=_raw, _df=_df)

    def signal_has_reduction(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否有减持公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_has_reduction", **kw, _raw=_raw, _df=_df)

    def signal_has_insider_buy(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否有增持公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_has_insider_buy", **kw, _raw=_raw, _df=_df)

    def signal_has_equity_incentive(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否有股权激励公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_has_equity_incentive", **kw, _raw=_raw, _df=_df)

    def signal_evidence_rows(self, sym: str, type_regex: str, window: str | None = None, lim: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """信号证据（原始公告行）

:returns: ARR · 公告行
        """
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if lim is not None:
            kw["lim"] = lim
        return self._client.call("notice.signal_evidence_rows", **kw, _raw=_raw, _df=_df)

    def signal_evidence_buyback(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """回购证据（规范化行）

:returns: ARR · 规范化证据行
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_evidence_buyback", **kw, _raw=_raw, _df=_df)

    def signal_evidence_reduction(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """减持证据（规范化行）

:returns: ARR · 规范化证据行
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_evidence_reduction", **kw, _raw=_raw, _df=_df)

    def signal_has(self, sym: str, type_regex: str, window: str | None = None, anchor_date: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否匹配类型正则"""
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if anchor_date is not None:
            kw["anchor_date"] = anchor_date
        return self._client.call("notice.signal_has", **kw, _raw=_raw, _df=_df)

    def signal_has_category(self, sym: str, category: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否有指定类别"""
        kw: dict[str, Any] = {"sym": sym, "category": category}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_has_category", **kw, _raw=_raw, _df=_df)

    def signal_no_reduction(self, sym: str, window: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """窗口内是否无减持"""
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return self._client.call("notice.signal_no_reduction", **kw, _raw=_raw, _df=_df)

    def signal_evidence(self, sym: str, type_regex: str, window: str | None = None, lim: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """信号证据（规范化）"""
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if lim is not None:
            kw["lim"] = lim
        return self._client.call("notice.signal_evidence", **kw, _raw=_raw, _df=_df)

    def query_symbols_on_date(self, date: str, type_regex: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """指定日期出现公告的代码列表"""
        kw: dict[str, Any] = {"date": date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        return self._client.call("notice.query_symbols_on_date", **kw, _raw=_raw, _df=_df)

    def query_stats_recent(self, window: str, _raw: bool = False, _df: bool = False) -> Any:
        """近期公告类别计数"""
        return self._client.call("notice.query_stats_recent", window=window, _raw=_raw, _df=_df)

    def query_build(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """构建公告 Mongo filter"""
        kw: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if stock_code is not None:
            kw["stock_code"] = stock_code
        return self._client.call("notice.query_build", **kw, _raw=_raw, _df=_df)

    def query_build_visible(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """构建可见日公告 filter"""
        kw: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if stock_code is not None:
            kw["stock_code"] = stock_code
        return self._client.call("notice.query_build_visible", **kw, _raw=_raw, _df=_df)

    def query_date_range(self, from_date: str, to_date: str, _raw: bool = False, _df: bool = False) -> Any:
        """日期区间条件"""
        return self._client.call("notice.query_date_range", from_date=from_date, to_date=to_date, _raw=_raw, _df=_df)

    def query_ts_range(self, from_date: str, to_date: str, _raw: bool = False, _df: bool = False) -> Any:
        """入库时间区间条件"""
        return self._client.call("notice.query_ts_range", from_date=from_date, to_date=to_date, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """公告行规范化"""
        return self._client.call("notice.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_lines(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """公告文本行"""
        return self._client.call("notice.fmt_lines", rows=rows, _raw=_raw, _df=_df)

    def fmt_line(self, row: dict, _raw: bool = False, _df: bool = False) -> Any:
        """单条公告文本"""
        return self._client.call("notice.fmt_line", row=row, _raw=_raw, _df=_df)

    def fmt_count_by_type(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """按类型计数"""
        return self._client.call("notice.fmt_count_by_type", rows=rows, _raw=_raw, _df=_df)

class RptdomNS(_Ns):
    """财务报表（fund.statements）"""

    def statement(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """三报表科目×期次透视

:param sym: 6 位裸码
:param opts: {scope: 合并|母公司(默认合并), n: 期数(默认5), years: 年份数组}

:returns: ARR · 科目行（科目代码/中文名×期次列）
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("rptdom.statement", **kw, _raw=_raw, _df=_df)

    def statement_years(self, sym: str, domain: str, _raw: bool = False, _df: bool = False) -> Any:
        """报表可用年报（Q4 档，降序）

:returns: ARR · 年份
        """
        return self._client.call("rptdom.statement_years", sym=sym, domain=domain, _raw=_raw, _df=_df)

    def statement_compare(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """合并 vs 母公司报表比较

:param opts: 同 statement（差额/差额占比%为派生计算）

:returns: ARR · 科目行 + 合并/母公司/差额/差额占比
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("rptdom.statement_compare", **kw, _raw=_raw, _df=_df)

    def statement_tree(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """三表目录树视图（树序 + 比率/占比行）

:param opts: 同 statement

:returns: ARR · 树序科目行；含派生比率行（LD/IBD_RATE/GM 等 pct 行）
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("rptdom.statement_tree", **kw, _raw=_raw, _df=_df)

    def statement_audit(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """审计意见（Q4 年轴）

:returns: MAP · {年份: 审计意见}
        """
        return self._client.call("rptdom.statement_audit", sym=sym, _raw=_raw, _df=_df)

class SegmentsNS(_Ns):
    """经营分部（fund.segments）"""

    def query_products(self, sym: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """产品/商品分部

:param sym: 6 位裸码
:param opts: {source: clean|raw, limit: 条数}

:returns: ARR · 分部行（名称/收入/成本/毛利率）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("segments.query_products", **kw, _raw=_raw, _df=_df)

    def query_business(self, sym: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """业务线分部

:param opts: 同 query_products

:returns: ARR · 分部行（结构同 query_products）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("segments.query_business", **kw, _raw=_raw, _df=_df)

    def query_income(self, sym: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """主营标签占比

:param opts: {limit: 条数}（source 不适用，固定标签口径）

:returns: ARR · 分部行（name + ratio 占比，小数；tr/cost 恒 0，margin 为 nil）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("segments.query_income", **kw, _raw=_raw, _df=_df)

    def query_region(self, sym: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """地区/境内外分部

:param opts: {source: clean|raw, limit: 条数}

:returns: MAP · clean 口径 {domestic, overseas, report_sas}（境内/外 各含 tr/pct/margin/yoy）； raw 返回 ARR 明细；无数据 nil
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("segments.query_region", **kw, _raw=_raw, _df=_df)

    def snapshot(self, sym: str, opts: dict | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """经营分部截面快照

:param opts: 同 query_products

:returns: MAP · 快照 {overview, income, region, product, business, coverage}
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return self._client.call("segments.snapshot", **kw, _raw=_raw, _df=_df)

    def coverage(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """分部披露覆盖度

:returns: MAP · 各维是否有数据（has_income/has_region/has_products/has_business）
        """
        return self._client.call("segments.coverage", sym=sym, _raw=_raw, _df=_df)

    def list_sas(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """可用报告期

:returns: MAP · {clean_last, clean_last_q4} 清洗口径锚点报告期
        """
        return self._client.call("segments.list_sas", sym=sym, _raw=_raw, _df=_df)

    def fmt_maps(self, rows: list, _raw: bool = False, _df: bool = False) -> Any:
        """分部行规范化

:param rows: 分部行列表

:returns: ARR · 规范化分部行
        """
        return self._client.call("segments.fmt_maps", rows=rows, _raw=_raw, _df=_df)

    def fmt_item(self, row: dict, _raw: bool = False, _df: bool = False) -> Any:
        """单条分部规范化

:returns: MAP · 规范化分部行
        """
        return self._client.call("segments.fmt_item", row=row, _raw=_raw, _df=_df)

class StocksNS(_Ns):
    """证券与行业基础（market.stocks）"""

    def query_list(self, _raw: bool = False, _df: bool = False) -> Any:
        """全市场证券列表"""
        return self._client.call("stocks.query_list", _raw=_raw, _df=_df)

    def industry_list(self, level: int | None = None, _raw: bool = False, _df: bool = False) -> Any:
        """行业目录"""
        kw: dict[str, Any] = {}
        if level is not None:
            kw["level"] = level
        return self._client.call("stocks.industry_list", **kw, _raw=_raw, _df=_df)

    def industry_members(self, ind: str, _raw: bool = False, _df: bool = False) -> Any:
        """行业成分股"""
        return self._client.call("stocks.industry_members", ind=ind, _raw=_raw, _df=_df)

class WorkoutNS(_Ns):
    """契约套利（disc.workout）"""

    def board(self, _raw: bool = False, _df: bool = False) -> Any:
        """进行中契约套利看板"""
        return self._client.call("workout.board", _raw=_raw, _df=_df)

    def query(self, sym: str, _raw: bool = False, _df: bool = False) -> Any:
        """单票契约套利条款"""
        return self._client.call("workout.query", sym=sym, _raw=_raw, _df=_df)

NAMESPACES: dict[str, type[_Ns]] = {
    "bonus": BonusNS,
    "cbond": CbondNS,
    "equity": EquityNS,
    "estimates": EstimatesNS,
    "filings": FilingsNS,
    "forecast": ForecastNS,
    "indices": IndicesNS,
    "intl": IntlNS,
    "kline": KlineNS,
    "macro": MacroNS,
    "margin": MarginNS,
    "moneyflow": MoneyflowNS,
    "notice": NoticeNS,
    "rptdom": RptdomNS,
    "segments": SegmentsNS,
    "stocks": StocksNS,
    "workout": WorkoutNS,
}
