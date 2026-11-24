# -*- coding: utf-8 -*-
"""自动生成：目录驱动的类型化命名空间门面 —— 勿手改。

由 tools/gen_typed_api.py 从数据目录生成；方法签名与 docstring 来自目录合同，
运行时统一委托 ``client.call()``（参数校验、max_limit 上限、normalize_with
规范化均在该层生效）。2.0 返回契约：行数组默认经 ``to_output_frame`` 转
DataFrame（``_raw=True`` 透传原始行）。重新生成：

  python3 tools/gen_typed_api.py

命名解析优先级：友好层（wmshare.api 手写类）> 本层 > 通用 _Namespace。
"""
from __future__ import annotations

from typing import Any


def _out(value: Any, raw: bool) -> Any:
    """2.0 返回收口：行数组默认转 DataFrame（与友好门面同一函数）。"""
    if raw:
        return value
    from wmshare.client import to_output_frame
    return to_output_frame(value)



class _Ns:
    """类型化命名空间基类。"""

    def __init__(self, client: Any) -> None:
        self._client = client


class BlocktradeNS(_Ns):
    """大宗交易（market.blocktrade）"""

    def by_date(self, trade_date: str, limit: int = 100, _raw: bool = False) -> Any:
        """指定交易日大宗交易

:param trade_date: 交易日 YYYY-MM-DD 或 YYYYMMDD
:param limit: 返回前 N 条（成交额降序）

:returns: ARR · 大宗交易行（成交额降序）
        """
        kw: dict[str, Any] = {"trade_date": trade_date}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("blocktrade.by_date", **kw, _raw=_raw), _raw)

    def by_symbol(self, sym: str, limit: int = 100, _raw: bool = False) -> Any:
        """单票大宗交易历史

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀
:param limit: 最近 N 条事件

:returns: ARR · 单票大宗事件行（date 升序；字段同 blocktrade.by_date）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("blocktrade.by_symbol", **kw, _raw=_raw), _raw)

class BoardNS(_Ns):
    """板块资金流（market.board）"""

    def moneyflow(self, src: str, trade_date: str, limit: int = 100, _raw: bool = False) -> Any:
        """指定交易日板块资金流

:param src: ths_concept / ths_industry / dc
:param trade_date: 交易日 YYYY-MM-DD 或 YYYYMMDD
:param limit: 返回前 N 个板块（按主力净流入降序）

:returns: ARR · 板块资金流行（净额降序；单位见域说明）
        """
        kw: dict[str, Any] = {"src": src, "trade_date": trade_date}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("board.moneyflow", **kw, _raw=_raw), _raw)

    def moneyflow_last(self, src: str, limit: int = 100, _raw: bool = False) -> Any:
        """最新交易日板块资金流

:param src: ths_concept / ths_industry / dc
:param limit: 返回前 N 个板块（按主力净流入降序）

:returns: ARR · 最新交易日板块资金流行（净额降序；其余字段同 board.moneyflow）
        """
        kw: dict[str, Any] = {"src": src}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("board.moneyflow_last", **kw, _raw=_raw), _raw)

    def concepts_of(self, sym: str, _raw: bool = False) -> Any:
        """单票概念标签

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀

:returns: MAP · symbol/name/tags（未收录返回 nil）
        """
        return _out(self._client.call("board.concepts_of", sym=sym, _raw=_raw), _raw)

    def concept_members(self, name: str, limit: int = 100, _raw: bool = False) -> Any:
        """概念成份股

:param name: 概念名（名称包含匹配，如 白酒/机器人）
:param limit: 返回前 N 只（按代码升序截断）

:returns: ARR · 成份行（代码升序）
        """
        kw: dict[str, Any] = {"name": name}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("board.concept_members", **kw, _raw=_raw), _raw)

    def concept_list(self, limit: int = 0, _raw: bool = False) -> Any:
        """概念板块目录

:param limit: 返回前 N 个概念（按成员数降序）；0 或缺省=全量

:returns: ARR · 概念行（成员数降序，同数按概念名升序）
        """
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("board.concept_list", **kw, _raw=_raw), _raw)

class BonusNS(_Ns):
    """分红（disc.bonus）"""

    def query_list(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """分红历史明细

:param sym: 6 位裸码
:param limit: 条数

:returns: ARR · 分红行（announce/ex_date/pay/dps/total/content/sas/payout_ratio/bonus_share/record_date）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("bonus.query_list", **kw, _raw=_raw), _raw)

    def query_last(self, sym: str, _raw: bool = False) -> Any:
        """最近一次分红

:returns: 分红行 MAP 或 nil
        """
        return _out(self._client.call("bonus.query_last", sym=sym, _raw=_raw), _raw)

    def query_at_sas(self, sym: str, sas: str, _raw: bool = False) -> Any:
        """指定报告期分红

:param sas: 报告期，如 "2024-Q4"

:returns: 分红行 MAP 或 nil
        """
        return _out(self._client.call("bonus.query_at_sas", sym=sym, sas=sas, _raw=_raw), _raw)

    def dps_rpt(self, sym: str, _raw: bool = False) -> Any:
        """财报期每股分红

:returns: float · 财报期每股分红（元/股）
        """
        return _out(self._client.call("bonus.dps_rpt", sym=sym, _raw=_raw), _raw)

    def dps_rpt_asof(self, rows: list, asof: str, _raw: bool = False) -> Any:
        """财报期每股分红（截至日）

:param rows: dps_rpt 结果
:param asof: 截至日期

:returns: 截至日的 DPS
        """
        return _out(self._client.call("bonus.dps_rpt_asof", rows=rows, asof=asof, _raw=_raw), _raw)

    def query_dps_window(self, sym: str, window: str, _raw: bool = False) -> Any:
        """窗口内每股股利合计

:param window: 窗口（如 3y）

:returns: float · 元/股
        """
        return _out(self._client.call("bonus.query_dps_window", sym=sym, window=window, _raw=_raw), _raw)

    def query_total_window(self, sym: str, window: str, _raw: bool = False) -> Any:
        """窗口内总分红

:returns: float · 元
        """
        return _out(self._client.call("bonus.query_total_window", sym=sym, window=window, _raw=_raw), _raw)

    def query_count_window(self, sym: str, window: str, _raw: bool = False) -> Any:
        """窗口内分红次数

:returns: int
        """
        return _out(self._client.call("bonus.query_count_window", sym=sym, window=window, _raw=_raw), _raw)

    def query_valid(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """有效分红序列（过滤无效行）

:returns: ARR · 分红行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("bonus.query_valid", **kw, _raw=_raw), _raw)

    def snapshot(self, sym: str, _raw: bool = False) -> Any:
        """股息快照（比率均为小数：yield_ttm=0.036 即 3.6%）

:returns: MAP · 股息/率快照
        """
        return _out(self._client.call("bonus.snapshot", sym=sym, _raw=_raw), _raw)

    def snapshot_yield_ttm(self, sym: str, _raw: bool = False) -> Any:
        """LTM 股息率

:returns: float · 小数（0.0396 = 3.96%）
        """
        return _out(self._client.call("bonus.snapshot_yield_ttm", sym=sym, _raw=_raw), _raw)

    def snapshot_payout_ttm(self, sym: str, _raw: bool = False) -> Any:
        """TTM 派息率

:returns: float · 小数（0.799 = 79.9%）
        """
        return _out(self._client.call("bonus.snapshot_payout_ttm", sym=sym, _raw=_raw), _raw)

    def screen_active(self, sym: str, _raw: bool = False) -> Any:
        """近年有分红"""
        return _out(self._client.call("bonus.screen_active", sym=sym, _raw=_raw), _raw)

    def screen_has_dividend(self, sym: str, min_yield: Any | None = None, _raw: bool = False) -> Any:
        """有分红记录"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return _out(self._client.call("bonus.screen_has_dividend", **kw, _raw=_raw), _raw)

    def screen_high_yield(self, sym: str, min_yield: Any | None = None, _raw: bool = False) -> Any:
        """高股息"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return _out(self._client.call("bonus.screen_high_yield", **kw, _raw=_raw), _raw)

    def screen_ample_payout(self, sym: str, _raw: bool = False) -> Any:
        """慷慨派息"""
        return _out(self._client.call("bonus.screen_ample_payout", sym=sym, _raw=_raw), _raw)

    def screen_danger_payout(self, sym: str, _raw: bool = False) -> Any:
        """派息不可持续"""
        return _out(self._client.call("bonus.screen_danger_payout", sym=sym, _raw=_raw), _raw)

    def screen_quality(self, sym: str, min_yield: Any | None = None, payout_min: Any | None = None, payout_max: Any | None = None, _raw: bool = False) -> Any:
        """分红质量优"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if payout_min is not None:
            kw["payout_min"] = payout_min
        if payout_max is not None:
            kw["payout_max"] = payout_max
        return _out(self._client.call("bonus.screen_quality", **kw, _raw=_raw), _raw)

    def screen_stable_yield(self, sym: str, _raw: bool = False) -> Any:
        """股息稳定"""
        return _out(self._client.call("bonus.screen_stable_yield", sym=sym, _raw=_raw), _raw)

    def screen_improving_yield(self, sym: str, _raw: bool = False) -> Any:
        """股息改善"""
        return _out(self._client.call("bonus.screen_improving_yield", sym=sym, _raw=_raw), _raw)

    def screen_trend_ok(self, sym: str, _raw: bool = False) -> Any:
        """分红趋势健康"""
        return _out(self._client.call("bonus.screen_trend_ok", sym=sym, _raw=_raw), _raw)

    def screen_declining_yield(self, sym: str, _raw: bool = False) -> Any:
        """股息下滑"""
        return _out(self._client.call("bonus.screen_declining_yield", sym=sym, _raw=_raw), _raw)

    def screen_undervalued_yield(self, sym: str, min_yield: Any | None = None, min_pct: Any | None = None, _raw: bool = False) -> Any:
        """低估+高股息"""
        kw: dict[str, Any] = {"sym": sym}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if min_pct is not None:
            kw["min_pct"] = min_pct
        return _out(self._client.call("bonus.screen_undervalued_yield", **kw, _raw=_raw), _raw)

    def index_where_active(self, _raw: bool = False) -> Any:
        """where·有分红"""
        return _out(self._client.call("bonus.index_where_active", _raw=_raw), _raw)

    def index_where_no_dividend(self, _raw: bool = False) -> Any:
        """where·无分红"""
        return _out(self._client.call("bonus.index_where_no_dividend", _raw=_raw), _raw)

    def index_where_has_dividend(self, _raw: bool = False) -> Any:
        """where·有记录"""
        return _out(self._client.call("bonus.index_where_has_dividend", _raw=_raw), _raw)

    def index_where_high_yield(self, _raw: bool = False) -> Any:
        """where·高股息"""
        return _out(self._client.call("bonus.index_where_high_yield", _raw=_raw), _raw)

    def index_where_high_yield_5(self, _raw: bool = False) -> Any:
        """where·连续5年高股息"""
        return _out(self._client.call("bonus.index_where_high_yield_5", _raw=_raw), _raw)

    def index_where_ample_payout(self, _raw: bool = False) -> Any:
        """where·慷慨派息"""
        return _out(self._client.call("bonus.index_where_ample_payout", _raw=_raw), _raw)

    def index_where_danger_payout(self, _raw: bool = False) -> Any:
        """where·派息危险"""
        return _out(self._client.call("bonus.index_where_danger_payout", _raw=_raw), _raw)

    def index_where_quality(self, _raw: bool = False) -> Any:
        """where·质量"""
        return _out(self._client.call("bonus.index_where_quality", _raw=_raw), _raw)

    def index_where_stable(self, _raw: bool = False) -> Any:
        """where·稳定"""
        return _out(self._client.call("bonus.index_where_stable", _raw=_raw), _raw)

    def index_where_improving(self, _raw: bool = False) -> Any:
        """where·改善"""
        return _out(self._client.call("bonus.index_where_improving", _raw=_raw), _raw)

    def index_where_declining(self, _raw: bool = False) -> Any:
        """where·下滑"""
        return _out(self._client.call("bonus.index_where_declining", _raw=_raw), _raw)

    def index_where_trend_up(self, _raw: bool = False) -> Any:
        """where·趋势向上"""
        return _out(self._client.call("bonus.index_where_trend_up", _raw=_raw), _raw)

    def index_where_undervalued(self, _raw: bool = False) -> Any:
        """where·低估"""
        return _out(self._client.call("bonus.index_where_undervalued", _raw=_raw), _raw)

    def index_yield_bin_expr(self, _raw: bool = False) -> Any:
        """股息率分桶 where 表达式"""
        return _out(self._client.call("bonus.index_yield_bin_expr", _raw=_raw), _raw)

    def index_field_load(self, idx: Any, fields: list, _raw: bool = False) -> Any:
        """分红索引字段预加载"""
        return _out(self._client.call("bonus.index_field_load", idx=idx, fields=fields, _raw=_raw), _raw)

    def index_field_load_analysis(self, idx: Any, _raw: bool = False) -> Any:
        """分红分析字段预加载"""
        return _out(self._client.call("bonus.index_field_load_analysis", idx=idx, _raw=_raw), _raw)

    def index_fields_basic(self, _raw: bool = False) -> Any:
        """分红基础字段列表"""
        return _out(self._client.call("bonus.index_fields_basic", _raw=_raw), _raw)

    def index_fields_analysis(self, _raw: bool = False) -> Any:
        """分红分析字段列表"""
        return _out(self._client.call("bonus.index_fields_analysis", _raw=_raw), _raw)

class BuybackNS(_Ns):
    """股东与股本（corp.equity）"""

    def snapshot(self, sym: str, _raw: bool = False) -> Any:
        """回购六口径快照

:param sym: 6 位裸码；港股 5 位需 market=hk 客户端（plan_* 为 nil，仅 exec_* 明细口径）

:returns: MAP · 回购六口径（元/原币；无数据源字段 nil，不伪造 0）
        """
        return _out(self._client.call("buyback.snapshot", sym=sym, _raw=_raw), _raw)

class CalendarNS(_Ns):
    """交易日历（market.calendar）"""

    def days(self, begin: str, end: str, limit: int | None = None, _raw: bool = False) -> Any:
        """交易日历区间"""
        kw: dict[str, Any] = {"begin": begin, "end": end}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("calendar.days", **kw, _raw=_raw), _raw)

    def is_open(self, date: str, _raw: bool = False) -> Any:
        """是否交易日"""
        return _out(self._client.call("calendar.is_open", date=date, _raw=_raw), _raw)

    def next(self, date: str, n: int | None = None, _raw: bool = False) -> Any:
        """之后 N 个交易日"""
        kw: dict[str, Any] = {"date": date}
        if n is not None:
            kw["n"] = n
        return _out(self._client.call("calendar.next", **kw, _raw=_raw), _raw)

class CbondNS(_Ns):
    """可转债（market.cbond）"""

    def board(self, _raw: bool = False) -> Any:
        """转债全市场面板（快照+最新事件+盘中价+callHits+下修地板价）

:returns: ARR · 转债面板行（快照行 + event/resetEvent/outstanding/callHits/resetFloor 等）
        """
        return _out(self._client.call("cbond.board", _raw=_raw), _raw)

    def quote_list(self, _raw: bool = False) -> Any:
        """转债合约快照全表

:returns: ARR · 原始快照行（snake_case，未规范化）
        """
        return _out(self._client.call("cbond.quote_list", _raw=_raw), _raw)

    def latest_quotes(self, _raw: bool = False) -> Any:
        """转债最新快照

:returns: ARR · 规范化快照行（每债取 asOf 最新一行）
        """
        return _out(self._client.call("cbond.latest_quotes", _raw=_raw), _raw)

    def of_stock(self, stk: Any, _raw: bool = False) -> Any:
        """正股关联转债

:returns: ARR · 该公司全部转债快照行（含已到期历史债，按 outstanding 过滤）
        """
        return _out(self._client.call("cbond.of_stock", stk=stk, _raw=_raw), _raw)

    def event_list(self, _raw: bool = False) -> Any:
        """转债条款事件列表"""
        return _out(self._client.call("cbond.event_list", _raw=_raw), _raw)

    def event_rows_of(self, sym: Any, _raw: bool = False) -> Any:
        """单标的条款事件"""
        return _out(self._client.call("cbond.event_rows_of", sym=sym, _raw=_raw), _raw)

    def query(self, sym: Any, limit: Any | None = None, _raw: bool = False) -> Any:
        """按标的查条款事件"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("cbond.query", **kw, _raw=_raw), _raw)

    def call_hits(self, code: Any, trig: Any, _raw: bool = False) -> Any:
        """强赎触发计数

:returns: int · 近 30 个交易日正股收盘 ≥ 触发价的天数
        """
        return _out(self._client.call("cbond.call_hits", code=code, trig=trig, _raw=_raw), _raw)

    def kline_window(self, code: Any, n: Any, _raw: bool = False) -> Any:
        """转债日K窗口"""
        return _out(self._client.call("cbond.kline_window", code=code, n=n, _raw=_raw), _raw)

    def min1_live(self, code: Any, _raw: bool = False) -> Any:
        """转债盘中1分钟"""
        return _out(self._client.call("cbond.min1_live", code=code, _raw=_raw), _raw)

    def min1_meta(self, code: Any, _raw: bool = False) -> Any:
        """转债盘中元信息"""
        return _out(self._client.call("cbond.min1_meta", code=code, _raw=_raw), _raw)

    def universe_codes(self, _raw: bool = False) -> Any:
        """转债代码全集"""
        return _out(self._client.call("cbond.universe_codes", _raw=_raw), _raw)

    def card(self, code: Any, _raw: bool = False) -> Any:
        """转债个券详情（一次全量返回九键；退市/停牌债 quote 为空、counts 为 nil，其余按债键照常返回）

:returns: MAP · {quote, terms, counts, region, concepts, projects, share, holders, institution}
        """
        return _out(self._client.call("cbond.card", code=code, _raw=_raw), _raw)

    def one_quote(self, code: Any, _raw: bool = False) -> Any:
        """单债最新快照（只 fmt 命中行）"""
        return _out(self._client.call("cbond.one_quote", code=code, _raw=_raw), _raw)

    def terms(self, code: Any, _raw: bool = False) -> Any:
        """转债条款档案（条款原文/评级/担保）"""
        return _out(self._client.call("cbond.terms", code=code, _raw=_raw), _raw)

    def terms_list(self, _raw: bool = False) -> Any:
        """转债条款档案全表（terms DAG 未跑返回空）"""
        return _out(self._client.call("cbond.terms_list", _raw=_raw), _raw)

    def counts(self, code: Any, _raw: bool = False) -> Any:
        """强赎/下修/回售三项计数与窗口"""
        return _out(self._client.call("cbond.counts", code=code, _raw=_raw), _raw)

    def count_hits(self, code: Any, trig: Any, window: Any, _raw: bool = False) -> Any:
        """正股收盘≥触发价天数（按交易日窗）"""
        return _out(self._client.call("cbond.count_hits", code=code, trig=trig, window=window, _raw=_raw), _raw)

    def count_below(self, code: Any, trig: Any, window: Any, _raw: bool = False) -> Any:
        """正股收盘<触发价天数（下修/回售用）"""
        return _out(self._client.call("cbond.count_below", code=code, trig=trig, window=window, _raw=_raw), _raw)

    def history(self, code: Any, n: Any, _raw: bool = False) -> Any:
        """转债近 N 日历史（快照+债 K；快照上线前区间自动补齐）

:returns: ARR · 转债历史行
        """
        return _out(self._client.call("cbond.history", code=code, n=n, _raw=_raw), _raw)

    def notices(self, code: Any, limit: Any, _raw: bool = False) -> Any:
        """正股近 5 年转债相关公告（上限 200）"""
        return _out(self._client.call("cbond.notices", code=code, limit=limit, _raw=_raw), _raw)

    def market(self, _raw: bool = False) -> Any:
        """转债市场截面（价格/溢价中位数与折价只数）"""
        return _out(self._client.call("cbond.market", _raw=_raw), _raw)

    def concepts_of(self, stk: Any, _raw: bool = False) -> Any:
        """正股概念标签（精确题材匹配前 12）"""
        return _out(self._client.call("cbond.concepts_of", stk=stk, _raw=_raw), _raw)

    def holders(self, code: Any, _raw: bool = False) -> Any:
        """十大持有人最新报告"""
        return _out(self._client.call("cbond.holders", code=code, _raw=_raw), _raw)

    def holders_list(self, code: Any, _raw: bool = False) -> Any:
        """十大持有人报告序列"""
        return _out(self._client.call("cbond.holders_list", code=code, _raw=_raw), _raw)

    def institution(self, code: Any, _raw: bool = False) -> Any:
        """机构持仓（基金数与持仓市值下限）"""
        return _out(self._client.call("cbond.institution", code=code, _raw=_raw), _raw)

    def fund_hold_of(self, code: Any, _raw: bool = False) -> Any:
        """机构持仓聚合（底层读取）"""
        return _out(self._client.call("cbond.fund_hold_of", code=code, _raw=_raw), _raw)

    def latest_share(self, code: Any, _raw: bool = False) -> Any:
        """最新转股结果（剩余规模与已转股比例）"""
        return _out(self._client.call("cbond.latest_share", code=code, _raw=_raw), _raw)

    def share_list(self, code: Any, _raw: bool = False) -> Any:
        """转股结果公告序列（约 24 份覆盖 6 年）"""
        return _out(self._client.call("cbond.share_list", code=code, _raw=_raw), _raw)

    def projects(self, code: Any, _raw: bool = False) -> Any:
        """转债募集资金投向"""
        return _out(self._client.call("cbond.projects", code=code, _raw=_raw), _raw)

    def project_of(self, code: Any, _raw: bool = False) -> Any:
        """募集资金投向档案（底层读取）"""
        return _out(self._client.call("cbond.project_of", code=code, _raw=_raw), _raw)

class EquityNS(_Ns):
    """股东与股本（corp.equity）"""

    def query_holder10(self, sym: str, _raw: bool = False) -> Any:
        """最新一期十大股东"""
        return _out(self._client.call("equity.query_holder10", sym=sym, _raw=_raw), _raw)

    def query_holdernum(self, sym: str, _raw: bool = False) -> Any:
        """最新股东户数"""
        return _out(self._client.call("equity.query_holdernum", sym=sym, _raw=_raw), _raw)

    def query_holdernum_history(self, sym: str, limit: int = 40, _raw: bool = False) -> Any:
        """股东户数历史序列

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀
:param limit: 最近 N 期（40 期≈10 年；上限 500）

:returns: ARR · 户数历史行（END_DATE 升序，最近 N 期）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_holdernum_history", **kw, _raw=_raw), _raw)

    def query_pledge_detail(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """主要股东质押明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_pledge_detail", **kw, _raw=_raw), _raw)

    def query_pledge_summary(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """公司质押比例"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_pledge_summary", **kw, _raw=_raw), _raw)

    def query_pledge_market(self, limit: int | None = None, _raw: bool = False) -> Any:
        """市场整体质押"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_pledge_market", **kw, _raw=_raw), _raw)

    def query_pledge_industry(self, limit: int | None = None, _raw: bool = False) -> Any:
        """行业质押比例"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_pledge_industry", **kw, _raw=_raw), _raw)

    def query_pledge_org(self, limit: int | None = None, _raw: bool = False) -> Any:
        """质押机构分布"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_pledge_org", **kw, _raw=_raw), _raw)

    def query_institution_detail(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """机构持股明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_institution_detail", **kw, _raw=_raw), _raw)

    def query_institution_summary(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """机构持仓占比"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_institution_summary", **kw, _raw=_raw), _raw)

    def query_hgt(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """沪港通持股"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_hgt", **kw, _raw=_raw), _raw)

    def query_national_team(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """国家队持股"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_national_team", **kw, _raw=_raw), _raw)

    def query_release(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """限售解禁日程"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_release", **kw, _raw=_raw), _raw)

    def query_buyback_plan(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """回购方案全览"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_buyback_plan", **kw, _raw=_raw), _raw)

    def query_buyback_detail(self, sym: str, _raw: bool = False) -> Any:
        """回购执行明细"""
        return _out(self._client.call("equity.query_buyback_detail", sym=sym, _raw=_raw), _raw)

    def query_reorg(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """并购重组"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_reorg", **kw, _raw=_raw), _raw)

    def query_related_trade(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """关联交易"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_related_trade", **kw, _raw=_raw), _raw)

    def query_concert(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """一致行动人"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_concert", **kw, _raw=_raw), _raw)

    def query_guarantee(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """对外担保"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_guarantee", **kw, _raw=_raw), _raw)

    def query_litigation(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """诉讼记录"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_litigation", **kw, _raw=_raw), _raw)

    def query_violation(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """违规处罚"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("equity.query_violation", **kw, _raw=_raw), _raw)

    def query_executives(self, sym: str, _raw: bool = False) -> Any:
        """高管名册"""
        return _out(self._client.call("equity.query_executives", sym=sym, _raw=_raw), _raw)

    def query_exec_change(self, sym: str, _raw: bool = False) -> Any:
        """高管增减持最新"""
        return _out(self._client.call("equity.query_exec_change", sym=sym, _raw=_raw), _raw)

    def query_exec_change_at(self, sym: str, annual: int, sampling: str, _raw: bool = False) -> Any:
        """指定报告期增减持"""
        return _out(self._client.call("equity.query_exec_change_at", sym=sym, annual=annual, sampling=sampling, _raw=_raw), _raw)

    def query_capital_change(self, sym: str, _raw: bool = False) -> Any:
        """股本结构最新"""
        return _out(self._client.call("equity.query_capital_change", sym=sym, _raw=_raw), _raw)

    def query_capital_change_at(self, sym: str, annual: int, sampling: str, _raw: bool = False) -> Any:
        """指定报告期股本"""
        return _out(self._client.call("equity.query_capital_change_at", sym=sym, annual=annual, sampling=sampling, _raw=_raw), _raw)

class EstimatesNS(_Ns):
    """盈利预测与研报（fund.estimates）"""

    def query_forecast(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """机构盈利预测"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("estimates.query_forecast", **kw, _raw=_raw), _raw)

    def query_forecast_detail(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """盈利预测明细"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("estimates.query_forecast_detail", **kw, _raw=_raw), _raw)

    def query_rating(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """评级统计"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("estimates.query_rating", **kw, _raw=_raw), _raw)

    def query_reports(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """个股研报"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("estimates.query_reports", **kw, _raw=_raw), _raw)

class FilingsNS(_Ns):
    """定期报告清单（disc.filings）"""

    def query(self, sym: str, type_key: str = 'all', limit: int | None = None, _raw: bool = False) -> Any:
        """定期报告列表

:param sym: 6 位裸码

:returns: ARR · 报告行（报告期/类型/标题/PDF 链接）
        """
        kw: dict[str, Any] = {"sym": sym}
        if type_key is not None:
            kw["type_key"] = type_key
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("filings.query", **kw, _raw=_raw), _raw)

    def latest(self, sym: str, type_key: str = 'all', _raw: bool = False) -> Any:
        """最新一条定期报告

:returns: 报告行 MAP 或 nil
        """
        kw: dict[str, Any] = {"sym": sym}
        if type_key is not None:
            kw["type_key"] = type_key
        return _out(self._client.call("filings.latest", **kw, _raw=_raw), _raw)

    def type_zh(self, type_key: str, _raw: bool = False) -> Any:
        """type_key 转中文"""
        return _out(self._client.call("filings.type_zh", type_key=type_key, _raw=_raw), _raw)

class ForecastNS(_Ns):
    """业绩披露事件（disc.events）"""

    def yjyg_rows(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """业绩预告历史

:param sym: 6 位裸码
:param limit: 条数

:returns: ARR · 预告行（报告期/类型/净利与扣非区间/同比/修正轨迹）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("forecast.yjyg_rows", **kw, _raw=_raw), _raw)

    def yjyg_latest(self, sym: str, _raw: bool = False) -> Any:
        """最新业绩预告

:returns: 预告行 MAP 或 nil
        """
        return _out(self._client.call("forecast.yjyg_latest", sym=sym, _raw=_raw), _raw)

    def yjkb_rows(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """业绩快报历史

:returns: ARR · 快报行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("forecast.yjkb_rows", **kw, _raw=_raw), _raw)

    def yjkb_latest(self, sym: str, _raw: bool = False) -> Any:
        """最新业绩快报

:returns: 快报行 MAP 或 nil
        """
        return _out(self._client.call("forecast.yjkb_latest", sym=sym, _raw=_raw), _raw)

    def disclosure_rows(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """财报预约披露历史

:returns: ARR · 预约披露行（报告期/计划披露日）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("forecast.disclosure_rows", **kw, _raw=_raw), _raw)

    def disclosure_next(self, sym: str, _raw: bool = False) -> Any:
        """下次财报披露

:returns: 预约披露行 MAP 或 nil
        """
        return _out(self._client.call("forecast.disclosure_next", sym=sym, _raw=_raw), _raw)

    def snapshot(self, sym: str, _raw: bool = False) -> Any:
        """业绩披露快照（预告+快报+日历合并视图）

:returns: MAP · 快照
        """
        return _out(self._client.call("forecast.snapshot", sym=sym, _raw=_raw), _raw)

class FredNS(_Ns):
    """美宏观（market.us_macro）"""

    def topics(self, _raw: bool = False) -> Any:
        """精选主题树

:returns: ARR · 主题行（topic/name/series）；11 主题合计 88 条序列
        """
        return _out(self._client.call("fred.topics", _raw=_raw), _raw)

    def search(self, keyword: str, limit: int | None = None, _raw: bool = False) -> Any:
        """精选序列检索

:param keyword: 关键词（匹配序列 id / 中文名 / 一句话说明；空串返回全部精选）
:param limit: 返回条数，缺省 20，上限 88

:returns: ARR · 命中行（id/title_zh/blurb_zh/topic）
        """
        kw: dict[str, Any] = {"keyword": keyword}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("fred.search", **kw, _raw=_raw), _raw)

    def series_meta(self, id: str, _raw: bool = False) -> Any:
        """序列元信息

:param id: 序列 id（如 GDP、UNRATE、DGS10；大写，自动归一）

:returns: MAP · 元信息（id/title/title_zh/blurb_zh/units/frequency_short/release_name/status/has_data/series_url/citation/hint）
        """
        return _out(self._client.call("fred.series_meta", id=id, _raw=_raw), _raw)

    def points_asc(self, id: str, begin: str | None = None, end: str | None = None, limit: int | None = None, _raw: bool = False) -> Any:
        """序列点（date 升序）

:param id: 序列 id（如 GDP、UNRATE、DGS10）
:param begin: 开始日期 YYYY-MM-DD（可空=全历史）
:param end: 结束日期 YYYY-MM-DD（可空）
:param limit: 根数（截最新 N 个点）。两层上限：Client 默认 max_limit=500（要更多须 Client(max_limit=None)），服务端 store 硬顶 10000；更长历史按 begin/end 分段各取一次

:returns: ARR · 点（id/date/value；date 升序，空值已跳过）
        """
        kw: dict[str, Any] = {"id": id}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("fred.points_asc", **kw, _raw=_raw), _raw)

class FuturesNS(_Ns):
    """期货（market.futures）"""

    def mapping(self, sym: str, begin: str | None = None, end: str | None = None, _raw: bool = False) -> Any:
        """主力换月映射

:param sym: 主力连续码（品种.交易所，如 RB.SHF）
:param begin: 开始日期 YYYY-MM-DD（可空=全历史）
:param end: 结束日期 YYYY-MM-DD（可空）

:returns: ARR · 映射行（date 升序；换月事件≈每年 4-6 次）
        """
        kw: dict[str, Any] = {"sym": sym}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        return _out(self._client.call("futures.mapping", **kw, _raw=_raw), _raw)

    def query_bars(self, sym: str, begin: str | None = None, end: str | None = None, limit: int | None = None, period: str = 'D', _raw: bool = False) -> Any:
        """主力连续历史 K 线（store 直读）

:param sym: 主力连续码（品种.交易所，如 RB.SHF；自动补 cn. 前缀；郑商所后缀 .ZCE；外盘用 global.CL）
:param begin: 开始日期 YYYY-MM-DD（可空=全历史；含）
:param end: 结束日期 YYYY-MM-DD（可空；**开区间**，要含当日请传次日）
:param limit: 根数，缺省取满（日 5500/周 1200/月 360）
:param period: 周期 D/W/M（也收 day/week/month）

:returns: ARR · bars（date 升序；date/symbol/open/high/low/close/settle/pre_settle/volume/amount/oi/oi_chg/percent）
        """
        kw: dict[str, Any] = {"sym": sym}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        if limit is not None:
            kw["limit"] = limit
        if period is not None:
            kw["period"] = period
        return _out(self._client.call("futures.query_bars", **kw, _raw=_raw), _raw)

class FxNS(_Ns):
    """外汇汇率（market.fx）"""

    def rate(self, ccy: str, _raw: bool = False) -> Any:
        """最新汇率

:param ccy: 币种 ISO 代码（USD/EUR/JPY/HKD；RMB/CNH 归一为 CNY）

:returns: MAP · 汇率快照（ccy/date/middle/buy/cash_buy/currency；无数据返回 nil）
        """
        return _out(self._client.call("fx.rate", ccy=ccy, _raw=_raw), _raw)

    def history(self, ccy: str, n: int = 30, _raw: bool = False) -> Any:
        """汇率日线序列

:param ccy: 币种 ISO 代码（同 rate）
:param n: 根数（1..2000；n<=0 归一到 30——不是「取全部」，全历史请用 query_bars 的 begin/end）

:returns: ARR · 汇率日线（date 升序；date/ccy/middle/buy）
        """
        kw: dict[str, Any] = {"ccy": ccy}
        if n is not None:
            kw["n"] = n
        return _out(self._client.call("fx.history", **kw, _raw=_raw), _raw)

    def list(self, _raw: bool = False) -> Any:
        """在库币种清单

:returns: ARR · 在库币种（ccy/date/middle；按候选清单探测，无数据的币种不出现）
        """
        return _out(self._client.call("fx.list", _raw=_raw), _raw)

    def query_bars(self, ccy: str, begin: str | None = None, end: str | None = None, limit: int = 500, _raw: bool = False) -> Any:
        """汇率区间日线

:param ccy: 币种 ISO 代码
:param begin: 开始日期 YYYY-MM-DD（可空）
:param end: 结束日期 YYYY-MM-DD（可空）
:param limit: 根数上限（1..500，Client 单次上限）

:returns: ARR · 汇率日线（date 升序；date/ccy/middle/buy）
        """
        kw: dict[str, Any] = {"ccy": ccy}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("fx.query_bars", **kw, _raw=_raw), _raw)

class IncomeNS(_Ns):
    """收息（disc.income）"""

    def rating_rows(self, top_n: int | None = None, grade: str | None = None, industry: str | None = None, min_yield: float | None = None, gates: bool | None = None, _raw: bool = False) -> Any:
        """全市场收息排行（四维评分+档位+股息分排序）

:param top_n: 返回条数，默认 20，上限 100
:param grade: 档位过滤 strong/good/watch/avoid
:param industry: 行业：industry.SXX / SXX / 申万一级中文名
:param min_yield: TTM 股息率下限（小数 0.04=4%）
:param gates: 资格门开关，默认 true

:returns: MAP · 收息榜（rows 含 rank/symbol/name/industry/四维 score/dividend_score/gate_pass，facets_industries 全集，asof/universe/missing_slices 元数据；COLD_CACHE 时 ok=false）
        """
        kw: dict[str, Any] = {}
        if top_n is not None:
            kw["top_n"] = top_n
        if grade is not None:
            kw["grade"] = grade
        if industry is not None:
            kw["industry"] = industry
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if gates is not None:
            kw["gates"] = gates
        return _out(self._client.call("income.rating_rows", **kw, _raw=_raw), _raw)

    def diagnose(self, symbols: list, include_history: bool | None = None, _raw: bool = False) -> Any:
        """收息诊断（原生批量：评分逐项解释+静态下限复原+榜内位置）

:param symbols: A 股代码数组（原生批量，一次 eval 按票计价；也接受单码带后缀写法）
:param include_history: 默认 false 只回评分/档位/flags/榜内 rank；true 才逐票带分红史+方案（批量不要开）

:returns: MAP · items[]（symbol/found/score{total,grade,dimensions,max,flags,parts}/floor_explain/rank/bond_yield_10y；include_history 时另带 dividend_history/dps_rpt）
        """
        kw: dict[str, Any] = {"symbols": symbols}
        if include_history is not None:
            kw["include_history"] = include_history
        return _out(self._client.call("income.diagnose", **kw, _raw=_raw), _raw)

    def calendar_events(self, cal_from: str | None = None, cal_to: str | None = None, cal_codes: list | None = None, _raw: bool = False) -> Any:
        """分红日历（窗口查全市场分红事件）

:param cal_from: YYYY-MM-DD，缺省当月 1 日
:param cal_to: YYYY-MM-DD，缺省当月末
:param cal_codes: 可选代码过滤

:returns: MAP · events（一个事件含公告/登记/除息/到账四日期，窗口内任一命中即返回；stocks 为名称/股息率/市值 enrich）
        """
        kw: dict[str, Any] = {}
        if cal_from is not None:
            kw["cal_from"] = cal_from
        if cal_to is not None:
            kw["cal_to"] = cal_to
        if cal_codes is not None:
            kw["cal_codes"] = cal_codes
        return _out(self._client.call("income.calendar_events", **kw, _raw=_raw), _raw)

    def decomp(self, symbols: list, years: int | None = None, _raw: bool = False) -> Any:
        """收益拆解（≤10 票批量：总收益=价格+股息贡献）

:param symbols: A 股代码数组，≤10（超出截断并标 truncated）
:param years: 持有年限 3/5/10，默认 10

:returns: MAP · items[]（total_return/price_return/dividend_return/cagr_*/monthly 月末累计序列/yearly 逐年表/attribution EPS×PE 归因；ok=false 为 K 线覆盖不足）
        """
        kw: dict[str, Any] = {"symbols": symbols}
        if years is not None:
            kw["years"] = years
        return _out(self._client.call("income.decomp", **kw, _raw=_raw), _raw)

    def decomp_one(self, sym: str, years: int | None = None, _raw: bool = False) -> Any:
        """收益拆解（单票）

:param years: 3/5/10，默认 10

:returns: MAP · 单票拆解包（同 income.decomp items[] 元素）
        """
        kw: dict[str, Any] = {"sym": sym}
        if years is not None:
            kw["years"] = years
        return _out(self._client.call("income.decomp_one", **kw, _raw=_raw), _raw)

    def dividend_score(self, v: dict, _raw: bool = False) -> Any:
        """股息分 = 0.6×TTM 股息率 + 0.4×近 3 年最低（缺项重归一，双缺 nil）

:param v: 指标字段行（$FIELD 键或 memo 紧凑行）

:returns: float · 小数排序分（非股息率，勿当收益率表述）
        """
        return _out(self._client.call("income.dividend_score", v=v, _raw=_raw), _raw)

    def gate(self, v: dict, _raw: bool = False) -> Any:
        """资格门五条（连续分红/流动性≥5000万/可交易/支付率(0,1]/近5年扣非ROE>0）

:returns: MAP · 各门布尔 + pass（缺失不拦：缺数据 ≠ 危险）
        """
        return _out(self._client.call("income.gate", v=v, _raw=_raw), _raw)

    def grade_of(self, total: int, _raw: bool = False) -> Any:
        """总分→档位

:returns: string · strong(≥75)/good(≥60)/watch(≥45)/avoid
        """
        return _out(self._client.call("income.grade_of", total=total, _raw=_raw), _raw)

    def score(self, v: dict, bond: float | None = None, _raw: bool = False) -> Any:
        """四维收息评分（紧凑：tot/gr/dims/fl 硬修正标记）

:param v: 指标字段行
:param bond: 十年国债收益率（小数，利差腿参照）

:returns: MAP · tot 0~100 / gr 档位 / dims[收益,持续,稳定,成长] / fl 硬修正
        """
        kw: dict[str, Any] = {"v": v}
        if bond is not None:
            kw["bond"] = bond
        return _out(self._client.call("income.score", **kw, _raw=_raw), _raw)

    def score_explain(self, v: dict, bond: float | None = None, _raw: bool = False) -> Any:
        """四维收息评分（含 parts 逐项加减分解释，诊断用）

:param v: 指标字段行
:param bond: 十年国债收益率（小数，利差腿参照）

:returns: MAP · tot/gr/dims 同 income.score，另带 parts[4]（dim/score/max/items[{label,delta}]）
        """
        kw: dict[str, Any] = {"v": v}
        if bond is not None:
            kw["bond"] = bond
        return _out(self._client.call("income.score_explain", **kw, _raw=_raw), _raw)

    def rating_all(self, grade: str | None = None, industry: str | None = None, min_yield: float | None = None, gates: bool | None = None, _raw: bool = False) -> Any:
        """全市场收息排行·全量（无 top_n 上限）

:param grade: 档位过滤 strong/good/watch/avoid
:param industry: 行业：industry.SXX / SXX / 申万一级中文名
:param min_yield: TTM 股息率下限（小数 0.04=4%）
:param gates: 资格门开关，默认 true

:returns: MAP · 与 rating_rows 同结构，rows 为全量不截断；facets_industries/facets_grades 为全集计数
        """
        kw: dict[str, Any] = {}
        if grade is not None:
            kw["grade"] = grade
        if industry is not None:
            kw["industry"] = industry
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if gates is not None:
            kw["gates"] = gates
        return _out(self._client.call("income.rating_all", **kw, _raw=_raw), _raw)

    def diag_fields(self, _raw: bool = False) -> Any:
        """收息取数字段包（27 字段）

:returns: ARR · 字段名数组（$FIELD 形态，供 INDEX_ROW_VALUES_MANY_SPEC）
        """
        return _out(self._client.call("income.diag_fields", _raw=_raw), _raw)

    def floor_explain(self, v: dict, _raw: bool = False) -> Any:
        """静态收益下限双腿复原（扣非盈利腿×PE 分位门 + 可持续股息腿×质量门）

:param v: 兼容原始 $FIELD 行与 memo 紧凑行（dp/pd/q5/b5/r5/fy）

:returns: MAP · ey_raw/pe_gate/ey_leg/dy_leg/composite/actual/residual/gate_uncertain
        """
        return _out(self._client.call("income.floor_explain", v=v, _raw=_raw), _raw)

class IndicesNS(_Ns):
    """指数（market.index）"""

    def keys(self, _raw: bool = False) -> Any:
        """指数键列表"""
        return _out(self._client.call("indices.keys", _raw=_raw), _raw)

    def members(self, key: str, sort_by: str | None = None, top_n: int | None = None, _raw: bool = False) -> Any:
        """指数成分"""
        kw: dict[str, Any] = {"key": key}
        if sort_by is not None:
            kw["sort_by"] = sort_by
        if top_n is not None:
            kw["top_n"] = top_n
        return _out(self._client.call("indices.members", **kw, _raw=_raw), _raw)

    def weights(self, key: str, top_n: int | None = None, _raw: bool = False) -> Any:
        """指数权重股"""
        kw: dict[str, Any] = {"key": key}
        if top_n is not None:
            kw["top_n"] = top_n
        return _out(self._client.call("indices.weights", **kw, _raw=_raw), _raw)

    def members_daily(self, key: str, begin: str, end: str | None = None, _raw: bool = False) -> Any:
        """指数成分日快照（前向 PIT：begin 时点的成分名单）

:param key: 指数键（如 index.hs300）
:param begin: 起始日 YYYY-MM-DD
:param end: 截止日，缺省最新

:returns: MAP · 成分快照信封
        """
        kw: dict[str, Any] = {"key": key, "begin": begin}
        if end is not None:
            kw["end"] = end
        return _out(self._client.call("indices.members_daily", **kw, _raw=_raw), _raw)

    def valuation(self, key: str, points: int | None = None, _raw: bool = False) -> Any:
        """指数估值时序（key 为指数键，如 index.hs300；可用键由 indices.universe_keys 枚举）

:param key: 指数键（index.hs300 等，用 indices.universe_keys 枚举）
:param points: 季采样点数；series 可自行算分位

:returns: MAP · 估值序列
        """
        kw: dict[str, Any] = {"key": key}
        if points is not None:
            kw["points"] = points
        return _out(self._client.call("indices.valuation", **kw, _raw=_raw), _raw)

    def trend(self, key: str, window: str | None = None, _raw: bool = False) -> Any:
        """指数估值趋势(周频整体法)"""
        kw: dict[str, Any] = {"key": key}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("indices.trend", **kw, _raw=_raw), _raw)

    def universe_keys(self, group: str | None = None, _raw: bool = False) -> Any:
        """指数域可用键"""
        kw: dict[str, Any] = {}
        if group is not None:
            kw["group"] = group
        return _out(self._client.call("indices.universe_keys", **kw, _raw=_raw), _raw)

class IntlNS(_Ns):
    """港美股披露（market.intl）"""

    def query_ccass(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """港股CCASS持仓"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("intl.query_ccass", **kw, _raw=_raw), _raw)

    def query_shareholders(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """港股主要股东"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("intl.query_shareholders", **kw, _raw=_raw), _raw)

    def query_org_rating(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """港股机构评级"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("intl.query_org_rating", **kw, _raw=_raw), _raw)

    def query_profit_forecast(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """港股盈利预测"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("intl.query_profit_forecast", **kw, _raw=_raw), _raw)

    def query_sellshort(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """港美沽空"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("intl.query_sellshort", **kw, _raw=_raw), _raw)

    def issue_info(self, sym: str, _raw: bool = False) -> Any:
        """美股发行信息"""
        return _out(self._client.call("intl.issue_info", sym=sym, _raw=_raw), _raw)

class KlineNS(_Ns):
    """行情K线（market.kline）"""

    def query_bars(self, sym: str, limit: int = 120, _raw: bool = False) -> Any:
        """历史 K 线

:param sym: 6 位裸码（自动剥 cn./sh. 前缀与 .SH/.SZ/.BJ 后缀）
:param limit: 根数，默认 120

:returns: ARR · bars（date/open/high/low/close/volume/amount/percent）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("kline.query_bars", **kw, _raw=_raw), _raw)

    def query_bars_period(self, sym: str, limit: int = 120, period: str = 'D', _raw: bool = False) -> Any:
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
        return _out(self._client.call("kline.query_bars_period", **kw, _raw=_raw), _raw)

    def query_bars_period_adj(self, sym: str, limit: int = 120, period: str = 'D', adj: str | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("kline.query_bars_period_adj", **kw, _raw=_raw), _raw)

    def query_last(self, sym: str, _raw: bool = False) -> Any:
        """最新一根 K 线

:param sym: 6 位裸码

:returns: MAP · bar 或 nil
        """
        return _out(self._client.call("kline.query_last", sym=sym, _raw=_raw), _raw)

    def is_etf(self, sym: str, _raw: bool = False) -> Any:
        """是否场内 ETF

:returns: bool · true=场内 ETF
        """
        return _out(self._client.call("kline.is_etf", sym=sym, _raw=_raw), _raw)

    def query_last_live(self, sym: str, _raw: bool = False) -> Any:
        """盘中日K快照

:returns: MAP · 盘中 bar（date/ohlcv/amount/percent/mv/source）
        """
        return _out(self._client.call("kline.query_last_live", sym=sym, _raw=_raw), _raw)

    def query_last_live_many(self, syms: list, _raw: bool = False) -> Any:
        """盘中日K批量快照

:param syms: 裸码列表

:returns: MAP · symbol → bar
        """
        return _out(self._client.call("kline.query_last_live_many", syms=syms, _raw=_raw), _raw)

    def query_bars_live(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """盘中拉最近 n 根日K（外部行情源 HTTP，≠分时）

:param limit: 最近 n 个交易日

:returns: ARR · bars
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("kline.query_bars_live", **kw, _raw=_raw), _raw)

    def query_min1_live(self, sym: str, _raw: bool = False) -> Any:
        """当日 1 分钟分时（有损滚桶）

:returns: MAP · 分时包 {trading_day, bars:[t,hm,close,volume,amount,...], bar_n}；休市读上一交易日
        """
        return _out(self._client.call("kline.query_min1_live", sym=sym, _raw=_raw), _raw)

    def query_min1_live_meta(self, sym: str, _raw: bool = False) -> Any:
        """分时头（无 bars）

:returns: MAP · {trading_day, updated_at, bar_n}
        """
        return _out(self._client.call("kline.query_min1_live_meta", sym=sym, _raw=_raw), _raw)

    def snapshot(self, sym: str, _raw: bool = False) -> Any:
        """行情快照（单票 MAP；列表 ≥3 票自动路由批量）

:returns: MAP · 23 字段行情快照（价量/涨跌/均线/市值/标识）
        """
        return _out(self._client.call("kline.snapshot", sym=sym, _raw=_raw), _raw)

    def snapshot_batch(self, codes: list | None = None, _raw: bool = False) -> Any:
        """多标的行情快照（索引按量投影，60~90 EC/票）

:param codes: 标的代码数组；空/nil 返回全市场非停牌

:returns: ARR · 索引原始行 [{row, values}]；values 内为 $指标→值（21 个字段）
        """
        kw: dict[str, Any] = {}
        if codes is not None:
            kw["codes"] = codes
        return _out(self._client.call("kline.snapshot_batch", **kw, _raw=_raw), _raw)

    def screen_above_ma20(self, sym: str, _raw: bool = False) -> Any:
        """收盘价在 MA20 之上

:returns: bool
        """
        return _out(self._client.call("kline.screen_above_ma20", sym=sym, _raw=_raw), _raw)

    def screen_momentum_20d(self, sym: str, min_chg: float, _raw: bool = False) -> Any:
        """近 20 日涨幅达标

:param min_chg: 如 0.1 = 10%

:returns: bool
        """
        return _out(self._client.call("kline.screen_momentum_20d", sym=sym, min_chg=min_chg, _raw=_raw), _raw)

    def index_breadth_summary(self, idx: Any, _raw: bool = False) -> Any:
        """全市场涨跌全景

:param idx: 服务端索引键（动态解析、无稳定字面量；推荐经 cli.screener 门面免传）

:returns: MAP · 涨跌统计
        """
        return _out(self._client.call("kline.index_breadth_summary", idx=idx, _raw=_raw), _raw)

    def index_top_movers(self, idx: Any, limit: int | None = None, desc: bool | None = None, _raw: bool = False) -> Any:
        """涨跌榜

:param desc: true=涨幅榜

:returns: ARR · 行
        """
        kw: dict[str, Any] = {"idx": idx}
        if limit is not None:
            kw["limit"] = limit
        if desc is not None:
            kw["desc"] = desc
        return _out(self._client.call("kline.index_top_movers", **kw, _raw=_raw), _raw)

    def index_pct_bin_expr(self, _raw: bool = False) -> Any:
        """涨跌幅分桶 where 表达式

:returns: string · 可用于 INDEX_QUERY where
        """
        return _out(self._client.call("kline.index_pct_bin_expr", _raw=_raw), _raw)

    def query_bars_adj(self, sym: str, limit: int, adj: str | None = None, _raw: bool = False) -> Any:
        """历史 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if adj is not None:
            kw["adj"] = adj
        return _out(self._client.call("kline.query_bars_adj", **kw, _raw=_raw), _raw)

    def query_bars_props(self, sym: str, limit: int, props: list | None = None, _raw: bool = False) -> Any:
        """历史 K 线（指定字段）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if props is not None:
            kw["props"] = props
        return _out(self._client.call("kline.query_bars_props", **kw, _raw=_raw), _raw)

    def query_bars_props_adj(self, sym: str, limit: int, props: list, adj: str | None = None, _raw: bool = False) -> Any:
        """历史 K 线（字段+复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit, "props": props}
        if adj is not None:
            kw["adj"] = adj
        return _out(self._client.call("kline.query_bars_props_adj", **kw, _raw=_raw), _raw)

    def query_last_adj(self, sym: str, adj: str | None = None, _raw: bool = False) -> Any:
        """最新一根 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym}
        if adj is not None:
            kw["adj"] = adj
        return _out(self._client.call("kline.query_last_adj", **kw, _raw=_raw), _raw)

    def query_valid(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """有效 K 线序列（过滤停牌空bar）"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("kline.query_valid", **kw, _raw=_raw), _raw)

    def query_valid_adj(self, sym: str, limit: int, adj: str | None = None, _raw: bool = False) -> Any:
        """有效 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if adj is not None:
            kw["adj"] = adj
        return _out(self._client.call("kline.query_valid_adj", **kw, _raw=_raw), _raw)

    def query_at_anchor(self, sym: str, limit: int, anchor_date: str | None = None, _raw: bool = False) -> Any:
        """锚点日前 K 线"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if anchor_date is not None:
            kw["anchor_date"] = anchor_date
        return _out(self._client.call("kline.query_at_anchor", **kw, _raw=_raw), _raw)

    def query_at_anchor_adj(self, sym: str, limit: int, anchor_date: str, adj: str | None = None, _raw: bool = False) -> Any:
        """锚点日前 K 线（复权）"""
        kw: dict[str, Any] = {"sym": sym, "limit": limit, "anchor_date": anchor_date}
        if adj is not None:
            kw["adj"] = adj
        return _out(self._client.call("kline.query_at_anchor_adj", **kw, _raw=_raw), _raw)

    def snapshot_close(self, sym: str, _raw: bool = False) -> Any:
        """最新收盘价"""
        return _out(self._client.call("kline.snapshot_close", sym=sym, _raw=_raw), _raw)

    def snapshot_percent(self, sym: str, _raw: bool = False) -> Any:
        """最新涨跌幅"""
        return _out(self._client.call("kline.snapshot_percent", sym=sym, _raw=_raw), _raw)

    def snapshot_chg_20d(self, sym: str, _raw: bool = False) -> Any:
        """近 20 日涨跌幅"""
        return _out(self._client.call("kline.snapshot_chg_20d", sym=sym, _raw=_raw), _raw)

    def screen_above_ma60(self, sym: str, _raw: bool = False) -> Any:
        """收盘价在 MA60 之上"""
        return _out(self._client.call("kline.screen_above_ma60", sym=sym, _raw=_raw), _raw)

    def screen_above_ma120(self, sym: str, _raw: bool = False) -> Any:
        """收盘价在 MA120 之上"""
        return _out(self._client.call("kline.screen_above_ma120", sym=sym, _raw=_raw), _raw)

    def screen_breakout_ma20(self, sym: str, _raw: bool = False) -> Any:
        """突破 MA20"""
        return _out(self._client.call("kline.screen_breakout_ma20", sym=sym, _raw=_raw), _raw)

    def screen_ma60_up(self, sym: str, _raw: bool = False) -> Any:
        """MA60 上行"""
        return _out(self._client.call("kline.screen_ma60_up", sym=sym, _raw=_raw), _raw)

    def screen_active(self, sym: str, _raw: bool = False) -> Any:
        """当日有成交"""
        return _out(self._client.call("kline.screen_active", sym=sym, _raw=_raw), _raw)

    def screen_up_today(self, sym: str, _raw: bool = False) -> Any:
        """今日上涨"""
        return _out(self._client.call("kline.screen_up_today", sym=sym, _raw=_raw), _raw)

    def screen_down_today(self, sym: str, _raw: bool = False) -> Any:
        """今日下跌"""
        return _out(self._client.call("kline.screen_down_today", sym=sym, _raw=_raw), _raw)

    def screen_flat_today(self, sym: str, _raw: bool = False) -> Any:
        """今日平盘"""
        return _out(self._client.call("kline.screen_flat_today", sym=sym, _raw=_raw), _raw)

    def screen_limit_up(self, sym: str, _raw: bool = False) -> Any:
        """涨停"""
        return _out(self._client.call("kline.screen_limit_up", sym=sym, _raw=_raw), _raw)

    def screen_limit_down(self, sym: str, _raw: bool = False) -> Any:
        """跌停"""
        return _out(self._client.call("kline.screen_limit_down", sym=sym, _raw=_raw), _raw)

    def screen_pullback_20d(self, sym: str, min_chg: Any | None = None, _raw: bool = False) -> Any:
        """近 20 日回撤可控"""
        kw: dict[str, Any] = {"sym": sym}
        if min_chg is not None:
            kw["min_chg"] = min_chg
        return _out(self._client.call("kline.screen_pullback_20d", **kw, _raw=_raw), _raw)

    def screen_volume_spike(self, sym: str, min_ratio: Any | None = None, _raw: bool = False) -> Any:
        """放量"""
        kw: dict[str, Any] = {"sym": sym}
        if min_ratio is not None:
            kw["min_ratio"] = min_ratio
        return _out(self._client.call("kline.screen_volume_spike", **kw, _raw=_raw), _raw)

    def query_index_last_live(self, key: str, _raw: bool = False) -> Any:
        """指数盘中点位"""
        return _out(self._client.call("kline.query_index_last_live", key=key, _raw=_raw), _raw)

    def query_index_last_live_many(self, keys: list, _raw: bool = False) -> Any:
        """指数盘中点位批量"""
        return _out(self._client.call("kline.query_index_last_live_many", keys=keys, _raw=_raw), _raw)

    def query_index_min1_live(self, key: str, _raw: bool = False) -> Any:
        """指数盘中 1 分钟分时"""
        return _out(self._client.call("kline.query_index_min1_live", key=key, _raw=_raw), _raw)

    def query_index_min1_live_meta(self, key: str, _raw: bool = False) -> Any:
        """指数分时头"""
        return _out(self._client.call("kline.query_index_min1_live_meta", key=key, _raw=_raw), _raw)

    def index_breadth_bins(self, idx: Any, _raw: bool = False) -> Any:
        """涨跌幅分桶结果"""
        return _out(self._client.call("kline.index_breadth_bins", idx=idx, _raw=_raw), _raw)

    def index_breadth_bin_industries(self, idx: Any, _raw: bool = False) -> Any:
        """分桶行业分布"""
        return _out(self._client.call("kline.index_breadth_bin_industries", idx=idx, _raw=_raw), _raw)

    def index_field_load(self, idx: Any, fields: list, _raw: bool = False) -> Any:
        """索引字段预加载"""
        return _out(self._client.call("kline.index_field_load", idx=idx, fields=fields, _raw=_raw), _raw)

    def index_field_load_analysis(self, idx: Any, _raw: bool = False) -> Any:
        """分析字段预加载"""
        return _out(self._client.call("kline.index_field_load_analysis", idx=idx, _raw=_raw), _raw)

    def index_field_load_breadth(self, idx: Any, _raw: bool = False) -> Any:
        """涨跌全景字段预加载"""
        return _out(self._client.call("kline.index_field_load_breadth", idx=idx, _raw=_raw), _raw)

    def index_fields_basic(self, _raw: bool = False) -> Any:
        """基础字段列表"""
        return _out(self._client.call("kline.index_fields_basic", _raw=_raw), _raw)

    def index_fields_analysis(self, _raw: bool = False) -> Any:
        """分析字段列表"""
        return _out(self._client.call("kline.index_fields_analysis", _raw=_raw), _raw)

    def index_fields_breadth(self, _raw: bool = False) -> Any:
        """涨跌全景字段列表"""
        return _out(self._client.call("kline.index_fields_breadth", _raw=_raw), _raw)

class MacroNS(_Ns):
    """宏观（market.macro）"""

    def query(self, code: str, n: int = 4, _raw: bool = False) -> Any:
        """宏观时序

:param code: 指标码或名称（$CPI / cpi 均可，服务端自动归一为 $CPI 形态）
:param n: 期数（1–48，超出按边界取）

:returns: MAP · ok/metric/store/frequency/periods/latest/series（series 每点含 sas/annual/sampling/value）
        """
        kw: dict[str, Any] = {"code": code}
        if n is not None:
            kw["n"] = n
        return _out(self._client.call("macro.query", **kw, _raw=_raw), _raw)

    def asof(self, code: str, _raw: bool = False) -> Any:
        """宏观 as-of 单点

:param code: 指标码或名称（同 query；人口类序列勿用）

:returns: 最新一期原生值（无数据返回 nil）
        """
        return _out(self._client.call("macro.asof", code=code, _raw=_raw), _raw)

    def spots(self, code: str, n: int = 4, _raw: bool = False) -> Any:
        """宏观原生点列

:param code: 指标码或名称
:param n: 期数（1–48）

:returns: ARR · 原生采样期点
        """
        kw: dict[str, Any] = {"code": code}
        if n is not None:
            kw["n"] = n
        return _out(self._client.call("macro.spots", **kw, _raw=_raw), _raw)

    def sampling_of(self, code: str, _raw: bool = False) -> Any:
        """宏观指标原生采样频率

:param code: 指标码或名称

:returns: "month"/"quarter"/"year"/"day"（无法判定时回退 "month"）
        """
        return _out(self._client.call("macro.sampling_of", code=code, _raw=_raw), _raw)

    def bond_curve(self, curve_name: str, tenor: str, _raw: bool = False) -> Any:
        """中债收益率按曲线名+期限

:param curve_name: 曲线披露名（如「中债国债收益率曲线」）
:param tenor: 期限列名（如「10年」「1年」）

:returns: 该曲线该期限的最新收益率原值
        """
        return _out(self._client.call("macro.bond_curve", curve_name=curve_name, tenor=tenor, _raw=_raw), _raw)

    def nev_monthly(self, brand: str, field: str, _raw: bool = False) -> Any:
        """新势力月交付

:param brand: 品牌披露名（如「零跑」「小米」）
:param field: 取值列（sales/rank）

:returns: 当月单值（掉榜返回 nil）
        """
        return _out(self._client.call("macro.nev_monthly", brand=brand, field=field, _raw=_raw), _raw)

    def nev_weekly(self, brand: str, field: str, _raw: bool = False) -> Any:
        """新势力周销量

:param brand: 品牌披露名
:param field: 取值列（sales/rank）

:returns: 当周单值（掉榜返回 nil）
        """
        return _out(self._client.call("macro.nev_weekly", brand=brand, field=field, _raw=_raw), _raw)

    def avc_monthly(self, category: str, field: str, _raw: bool = False) -> Any:
        """奥维家电品类月度

:param category: 品类披露名（如「消费级摄像头」）
:param field: 取值列（volume/volume_yoy/value/value_yoy）

:returns: 当月单值（掉榜返回 nil）
        """
        return _out(self._client.call("macro.avc_monthly", category=category, field=field, _raw=_raw), _raw)

    def chinaiol_monthly(self, category: str, field: str, _raw: bool = False) -> Any:
        """家电产销月度

:param category: 品类披露名（如「洗衣机」）
:param field: 取值列（volume=内销量/volume_yoy/value=内销额/value_yoy）

:returns: 当月单值（掉榜返回 nil）
        """
        return _out(self._client.call("macro.chinaiol_monthly", category=category, field=field, _raw=_raw), _raw)

    def cpca_top(self, manufacturer: str, field: str, _raw: bool = False) -> Any:
        """乘联会厂商排行

:param manufacturer: 厂商披露名（如「比亚迪汽车」）
:param field: 取值列（如 wholesale/retail）

:returns: 当月单值（掉榜返回 nil）
        """
        return _out(self._client.call("macro.cpca_top", manufacturer=manufacturer, field=field, _raw=_raw), _raw)

    def phone_share(self, brand: str, field: str = 'share', _raw: bool = False) -> Any:
        """手机品牌周份额

:param brand: 品牌披露名（如「小米」）
:param field: 取值列（share/rank）

:returns: 当周单值（掉榜返回 nil）
        """
        kw: dict[str, Any] = {"brand": brand}
        if field is not None:
            kw["field"] = field
        return _out(self._client.call("macro.phone_share", **kw, _raw=_raw), _raw)

class MarginNS(_Ns):
    """融资融券（market.margin）"""

    def query(self, sym: str, limit: int | None = None, _raw: bool = False) -> Any:
        """个股融资融券"""
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("margin.query", **kw, _raw=_raw), _raw)

    def latest(self, sym: str, _raw: bool = False) -> Any:
        """最新两融"""
        return _out(self._client.call("margin.latest", sym=sym, _raw=_raw), _raw)

    def market_summary(self, limit: int | None = None, _raw: bool = False) -> Any:
        """市场级两融汇总"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("margin.market_summary", **kw, _raw=_raw), _raw)

    def universe(self, limit: Any | None = None, _raw: bool = False) -> Any:
        """两融标的名单"""
        kw: dict[str, Any] = {}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("margin.universe", **kw, _raw=_raw), _raw)

class MoneyflowNS(_Ns):
    """资金流向（market.moneyflow）"""

    def query_bars(self, sym: str, limit: int = 20, _raw: bool = False) -> Any:
        """资金流向历史

:param sym: 6 位裸码
:param limit: 根数，默认 20；单次上限 500（超限服务端拒绝，长历史走 bars 区间分页）

:returns: ARR · 资金流行（date/net_mf/elg_net/lg_net/md_net/sm_net）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("moneyflow.query_bars", **kw, _raw=_raw), _raw)

    def query_bars_anchor(self, sym: str, limit: int, anchor_date: str | None = None, _raw: bool = False) -> Any:
        """锚点前资金流

:returns: ARR · 资金流行（字段与 query_bars 一致）
        """
        kw: dict[str, Any] = {"sym": sym, "limit": limit}
        if anchor_date is not None:
            kw["anchor_date"] = anchor_date
        return _out(self._client.call("moneyflow.query_bars_anchor", **kw, _raw=_raw), _raw)

    def query_last(self, sym: str, _raw: bool = False) -> Any:
        """最新资金流向

:returns: 资金流行 MAP 或 nil
        """
        return _out(self._client.call("moneyflow.query_last", sym=sym, _raw=_raw), _raw)

    def query_valid(self, sym: str, limit: int = 20, _raw: bool = False) -> Any:
        """有效资金流向（过滤空行）

:param limit: 根数，默认 20；单次上限 500（随 query_bars，超限服务端拒绝）

:returns: ARR · 资金流行
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("moneyflow.query_valid", **kw, _raw=_raw), _raw)

    def query_last_live(self, sym: str, _raw: bool = False) -> Any:
        """资金流当日读数（外部源）

:returns: MAP · 资金流快照
        """
        return _out(self._client.call("moneyflow.query_last_live", sym=sym, _raw=_raw), _raw)

    def snapshot(self, sym: str, _raw: bool = False) -> Any:
        """资金流向快照（金额均为元；net_mv_ratio 为小数）

:returns: MAP · 快照
        """
        return _out(self._client.call("moneyflow.snapshot", sym=sym, _raw=_raw), _raw)

    def snapshot_net_mf(self, sym: str, _raw: bool = False) -> Any:
        """最新主力净流入

:returns: float · 主力净流入（元）
        """
        return _out(self._client.call("moneyflow.snapshot_net_mf", sym=sym, _raw=_raw), _raw)

    def board(self, _raw: bool = False) -> Any:
        """全市场资金流快照（金额均为元；net_mv_ratio 为小数）

:returns: ARR · 资金流行（symbol/name/net_mf/net_mv_ratio/lg_net/elg_net/md_net/sm_net/industry，按主力净流入降序）
        """
        return _out(self._client.call("moneyflow.board", _raw=_raw), _raw)

class NoticeNS(_Ns):
    """公告（disc.notice）"""

    def query_by_symbol(self, sym: str, window: str | None = None, type_regex: str | None = None, limit: int | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("notice.query_by_symbol", **kw, _raw=_raw), _raw)

    def query_recent(self, window: str | None = None, type_regex: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("notice.query_recent", **kw, _raw=_raw), _raw)

    def query_by_category(self, category: str, window: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("notice.query_by_category", **kw, _raw=_raw), _raw)

    def query_on_date(self, date: str, type_regex: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("notice.query_on_date", **kw, _raw=_raw), _raw)

    def query_find(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, limit: int | None = None, market: str | None = None, _raw: bool = False) -> Any:
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
        return _out(self._client.call("notice.query_find", **kw, _raw=_raw), _raw)

    def signal_has_buyback(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否有回购公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_has_buyback", **kw, _raw=_raw), _raw)

    def signal_has_reduction(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否有减持公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_has_reduction", **kw, _raw=_raw), _raw)

    def signal_has_insider_buy(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否有增持公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_has_insider_buy", **kw, _raw=_raw), _raw)

    def signal_has_equity_incentive(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否有股权激励公告

:returns: bool
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_has_equity_incentive", **kw, _raw=_raw), _raw)

    def signal_evidence_rows(self, sym: str, type_regex: str, window: str | None = None, lim: int | None = None, _raw: bool = False) -> Any:
        """信号证据（原始公告行）

:returns: ARR · 公告行
        """
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if lim is not None:
            kw["lim"] = lim
        return _out(self._client.call("notice.signal_evidence_rows", **kw, _raw=_raw), _raw)

    def signal_evidence_buyback(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """回购证据（规范化行）

:returns: ARR · 规范化证据行
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_evidence_buyback", **kw, _raw=_raw), _raw)

    def signal_evidence_reduction(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """减持证据（规范化行）

:returns: ARR · 规范化证据行
        """
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_evidence_reduction", **kw, _raw=_raw), _raw)

    def signal_has(self, sym: str, type_regex: str, window: str | None = None, anchor_date: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否匹配类型正则"""
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if anchor_date is not None:
            kw["anchor_date"] = anchor_date
        return _out(self._client.call("notice.signal_has", **kw, _raw=_raw), _raw)

    def signal_has_category(self, sym: str, category: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否有指定类别"""
        kw: dict[str, Any] = {"sym": sym, "category": category}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_has_category", **kw, _raw=_raw), _raw)

    def signal_no_reduction(self, sym: str, window: str | None = None, _raw: bool = False) -> Any:
        """窗口内是否无减持"""
        kw: dict[str, Any] = {"sym": sym}
        if window is not None:
            kw["window"] = window
        return _out(self._client.call("notice.signal_no_reduction", **kw, _raw=_raw), _raw)

    def signal_evidence(self, sym: str, type_regex: str, window: str | None = None, lim: int | None = None, _raw: bool = False) -> Any:
        """信号证据（规范化）"""
        kw: dict[str, Any] = {"sym": sym, "type_regex": type_regex}
        if window is not None:
            kw["window"] = window
        if lim is not None:
            kw["lim"] = lim
        return _out(self._client.call("notice.signal_evidence", **kw, _raw=_raw), _raw)

    def query_symbols_on_date(self, date: str, type_regex: str | None = None, _raw: bool = False) -> Any:
        """指定日期出现公告的代码列表"""
        kw: dict[str, Any] = {"date": date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        return _out(self._client.call("notice.query_symbols_on_date", **kw, _raw=_raw), _raw)

    def query_stats_recent(self, window: str, _raw: bool = False) -> Any:
        """近期公告类别计数"""
        return _out(self._client.call("notice.query_stats_recent", window=window, _raw=_raw), _raw)

    def type_keys(self, _raw: bool = False) -> Any:
        """公告类目键列表

:returns: ARR · 类目键列表（reduction/insider_buy/buyback/equity_incentive/forecast/dividend/risk/mna/contract/pledge/issue/report/suspend/correct）
        """
        return _out(self._client.call("notice.type_keys", _raw=_raw), _raw)

    def type_regex(self, key: str, _raw: bool = False) -> Any:
        """公告类目匹配正则

:param key: 类目键；未知键原样透传（可直接传自定义正则）

:returns: string · NOTICE_TYPE 匹配正则
        """
        return _out(self._client.call("notice.type_regex", key=key, _raw=_raw), _raw)

    def query_build(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, _raw: bool = False) -> Any:
        """构建公告 Mongo filter"""
        kw: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if stock_code is not None:
            kw["stock_code"] = stock_code
        return _out(self._client.call("notice.query_build", **kw, _raw=_raw), _raw)

    def query_build_visible(self, from_date: str, to_date: str, type_regex: str | None = None, stock_code: str | None = None, _raw: bool = False) -> Any:
        """构建可见日公告 filter"""
        kw: dict[str, Any] = {"from_date": from_date, "to_date": to_date}
        if type_regex is not None:
            kw["type_regex"] = type_regex
        if stock_code is not None:
            kw["stock_code"] = stock_code
        return _out(self._client.call("notice.query_build_visible", **kw, _raw=_raw), _raw)

    def query_date_range(self, from_date: str, to_date: str, _raw: bool = False) -> Any:
        """日期区间条件"""
        return _out(self._client.call("notice.query_date_range", from_date=from_date, to_date=to_date, _raw=_raw), _raw)

    def query_ts_range(self, from_date: str, to_date: str, _raw: bool = False) -> Any:
        """入库时间区间条件"""
        return _out(self._client.call("notice.query_ts_range", from_date=from_date, to_date=to_date, _raw=_raw), _raw)

    def read_text(self, sym: str, date: str, url: str | None = None, full: bool | None = None, _raw: bool = False) -> Any:
        """公告正文读取（纯读，未就绪不入队）

:param sym: 6 位裸码/港股 5 位
:param date: YYYY-MM-DD；传 url 时可空串
:param url: PDF链接；空则由 sym+date 定位
:param full: false=前4000字预览，true=全量

:returns: MAP · 正文与状态
        """
        kw: dict[str, Any] = {"sym": sym, "date": date}
        if url is not None:
            kw["url"] = url
        if full is not None:
            kw["full"] = full
        return _out(self._client.call("notice.read_text", **kw, _raw=_raw), _raw)

class Pdf_docNS(_Ns):
    """公告 PDF 全文（disc.pdf_doc）"""

    def search(self, opts: dict | None = None, _raw: bool = False) -> Any:
        """PDF 文档检索

:param opts: {stock_code/symbol, title, announce_date_from/to, status, kind, limit, skip}

:returns: ARR · 命中文档元数据行（file_key/status/text_chars/source_url/oss_url/stock_code/announce_date/title/kind/has_markdown，不含正文）
        """
        kw: dict[str, Any] = {}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("pdf_doc.search", **kw, _raw=_raw), _raw)

    def read_text(self, file_key: str, source_url: str | None = None, _raw: bool = False) -> Any:
        """读 PDF 提取正文

:param file_key: 文档键；与 source_url 至少给一个
:param source_url: 原文链接

:returns: MAP · 正文与状态
        """
        kw: dict[str, Any] = {"file_key": file_key}
        if source_url is not None:
            kw["source_url"] = source_url
        return _out(self._client.call("pdf_doc.read_text", **kw, _raw=_raw), _raw)

    def read_markdown(self, file_key: str | None = None, source_url: str | None = None, stock_code: str | None = None, period: str | None = None, _raw: bool = False) -> Any:
        """读财报 markdown/经营评述

:param file_key: 文档键；与 source_url/stock_code 至少给一个
:param source_url: 原文链接
:param stock_code: 6 位裸码（定期报告定位用）
:param period: 报告期（如 2024）

:returns: MAP · markdown 挂接或经营评述正文
        """
        kw: dict[str, Any] = {}
        if file_key is not None:
            kw["file_key"] = file_key
        if source_url is not None:
            kw["source_url"] = source_url
        if stock_code is not None:
            kw["stock_code"] = stock_code
        if period is not None:
            kw["period"] = period
        return _out(self._client.call("pdf_doc.read_markdown", **kw, _raw=_raw), _raw)

    def status(self, file_key: str, source_url: str | None = None, _raw: bool = False) -> Any:
        """PDF 文档状态

:param file_key: 文档键；与 source_url 至少给一个
:param source_url: 原文链接

:returns: MAP · 转换状态
        """
        kw: dict[str, Any] = {"file_key": file_key}
        if source_url is not None:
            kw["source_url"] = source_url
        return _out(self._client.call("pdf_doc.status", **kw, _raw=_raw), _raw)

    def find_by_url(self, url: str, _raw: bool = False) -> Any:
        """按原文链接定位文档

:returns: MAP · 原始文档行或 nil
        """
        return _out(self._client.call("pdf_doc.find_by_url", url=url, _raw=_raw), _raw)

    def find_by_key(self, file_key: str, _raw: bool = False) -> Any:
        """按文档键定位文档

:returns: MAP · 原始文档行或 nil
        """
        return _out(self._client.call("pdf_doc.find_by_key", file_key=file_key, _raw=_raw), _raw)

class ReserveNS(_Ns):
    """宏观（market.macro）"""

    def list(self, _raw: bool = False) -> Any:
        """储备项清单

:returns: ARR · 储备项（kind/label/available/date/value/unit；缺生产者项 available=false）
        """
        return _out(self._client.call("reserve.list", _raw=_raw), _raw)

    def query(self, kind: str, n: int = 12, _raw: bool = False) -> Any:
        """储备时序

:param kind: 储备项（forex=国家外汇储备 / gold=黄金储备）
:param n: 期数（1..48，月频）

:returns: ARR · 储备时序（date 升序 YYYY-MM；date/kind/value）
        """
        kw: dict[str, Any] = {"kind": kind}
        if n is not None:
            kw["n"] = n
        return _out(self._client.call("reserve.query", **kw, _raw=_raw), _raw)

    def asof(self, kind: str, _raw: bool = False) -> Any:
        """储备最新值

:param kind: 储备项（forex / gold；sdr 无数据返回 nil）

:returns: MAP · 储备快照（kind/date/value/unit；无数据返回 nil）
        """
        return _out(self._client.call("reserve.asof", kind=kind, _raw=_raw), _raw)

class RptdomNS(_Ns):
    """财务报表（fund.statements）"""

    def statement(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """三报表科目×期次透视

:param sym: 6 位裸码
:param opts: {scope: 合并|母公司(默认合并), n: 期数(默认5), years: 年份数组}

:returns: ARR · 科目行（科目代码/中文名×期次列）
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("rptdom.statement", **kw, _raw=_raw), _raw)

    def statement_years(self, sym: str, domain: str, _raw: bool = False) -> Any:
        """报表可用年报（Q4 档，降序）

:returns: ARR · 年份
        """
        return _out(self._client.call("rptdom.statement_years", sym=sym, domain=domain, _raw=_raw), _raw)

    def statement_compare(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """合并 vs 母公司报表比较

:param opts: 同 statement（差额/差额占比%为派生计算）

:returns: ARR · 科目行 + 合并/母公司/差额/差额占比
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("rptdom.statement_compare", **kw, _raw=_raw), _raw)

    def statement_tree(self, sym: str, domain: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """三表目录树视图（树序 + 比率/占比行）

:param opts: 同 statement

:returns: ARR · 树序科目行；含派生比率行（LD/IBD_RATE/GM 等 pct 行）
        """
        kw: dict[str, Any] = {"sym": sym, "domain": domain}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("rptdom.statement_tree", **kw, _raw=_raw), _raw)

    def statement_audit(self, sym: str, _raw: bool = False) -> Any:
        """审计意见（Q4 年轴）

:returns: MAP · {年份: 审计意见}
        """
        return _out(self._client.call("rptdom.statement_audit", sym=sym, _raw=_raw), _raw)

class SegmentsNS(_Ns):
    """经营分部（fund.segments）"""

    def query_products(self, sym: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """产品/商品分部

:param sym: 6 位裸码
:param opts: {source: clean|raw, limit: 条数}

:returns: ARR · 分部行（名称/收入/成本/毛利率）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("segments.query_products", **kw, _raw=_raw), _raw)

    def query_business(self, sym: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """业务线分部

:param opts: 同 query_products

:returns: ARR · 分部行（结构同 query_products）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("segments.query_business", **kw, _raw=_raw), _raw)

    def query_income(self, sym: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """主营标签占比

:param opts: {limit: 条数}（source 不适用，固定标签口径）

:returns: ARR · 分部行（name + ratio 占比，小数；tr/cost 恒 0，margin 为 nil）
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("segments.query_income", **kw, _raw=_raw), _raw)

    def query_region(self, sym: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """地区/境内外分部

:param opts: {source: clean|raw, limit: 条数}

:returns: MAP · clean 口径 {domestic, overseas, report_sas}（境内/外 各含 tr/pct/margin/yoy）； raw 返回 ARR 明细；无数据 nil
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("segments.query_region", **kw, _raw=_raw), _raw)

    def snapshot(self, sym: str, opts: dict | None = None, _raw: bool = False) -> Any:
        """经营分部截面快照

:param opts: 同 query_products

:returns: MAP · 快照 {overview, income, region, product, business, coverage}
        """
        kw: dict[str, Any] = {"sym": sym}
        if opts is not None:
            kw["opts"] = opts
        return _out(self._client.call("segments.snapshot", **kw, _raw=_raw), _raw)

    def coverage(self, sym: str, _raw: bool = False) -> Any:
        """分部披露覆盖度

:returns: MAP · 各维是否有数据（has_income/has_region/has_products/has_business）
        """
        return _out(self._client.call("segments.coverage", sym=sym, _raw=_raw), _raw)

    def list_sas(self, sym: str, _raw: bool = False) -> Any:
        """可用报告期

:returns: MAP · {clean_last, clean_last_q4} 清洗口径锚点报告期
        """
        return _out(self._client.call("segments.list_sas", sym=sym, _raw=_raw), _raw)

class StocksNS(_Ns):
    """证券与行业基础（market.stocks）"""

    def query_list(self, _raw: bool = False) -> Any:
        """全市场证券列表"""
        return _out(self._client.call("stocks.query_list", _raw=_raw), _raw)

    def industry_list(self, level: int | None = None, _raw: bool = False) -> Any:
        """行业目录"""
        kw: dict[str, Any] = {}
        if level is not None:
            kw["level"] = level
        return _out(self._client.call("stocks.industry_list", **kw, _raw=_raw), _raw)

    def industry_members(self, ind: str, _raw: bool = False) -> Any:
        """行业成分股"""
        return _out(self._client.call("stocks.industry_members", ind=ind, _raw=_raw), _raw)

    def limit_prices(self, _raw: bool = False) -> Any:
        """全市场涨跌停价（当日快照）

:returns: ARR · 涨跌停价行（非停牌全市场，按代码升序）
        """
        return _out(self._client.call("stocks.limit_prices", _raw=_raw), _raw)

    def limit_price(self, sym: str, _raw: bool = False) -> Any:
        """单票涨跌停价（当日快照）

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀

:returns: MAP · 涨跌停价行（字段同 stocks.limit_prices；未收录/停牌返回 nil）
        """
        return _out(self._client.call("stocks.limit_price", sym=sym, _raw=_raw), _raw)

    def suspend_history(self, sym: str, begin: str = '', end: str = '', _raw: bool = False) -> Any:
        """单票停复牌事件

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀
:param begin: 起始日 YYYY-MM-DD（空=不限）
:param end: 结束日 YYYY-MM-DD（空=不限）

:returns: ARR · 停复牌事件行（date 升序）
        """
        kw: dict[str, Any] = {"sym": sym}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        return _out(self._client.call("stocks.suspend_history", **kw, _raw=_raw), _raw)

    def name_history(self, sym: str, _raw: bool = False) -> Any:
        """单票简称变更史

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀

:returns: ARR · 简称段行（按生效日升序）
        """
        return _out(self._client.call("stocks.name_history", sym=sym, _raw=_raw), _raw)

    def lifecycle(self, sym: str, _raw: bool = False) -> Any:
        """单票 ST/停复牌变动时间轴

:param sym: 6 位裸码或带 .SH/.SZ/.BJ 后缀

:returns: ARR · 时间轴事件行（date 升序）
        """
        return _out(self._client.call("stocks.lifecycle", sym=sym, _raw=_raw), _raw)

class ToplistNS(_Ns):
    """龙虎榜（market.toplist）"""

    def by_date(self, trade_date: str, limit: int = 100, _raw: bool = False) -> Any:
        """指定交易日龙虎榜

:param trade_date: 交易日（YYYY-MM-DD 或 YYYYMMDD）
:param limit: 条数上限

:returns: ARR · 榜单行（同票多上榜原因各一行）
        """
        kw: dict[str, Any] = {"trade_date": trade_date}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("toplist.by_date", **kw, _raw=_raw), _raw)

    def by_symbol(self, sym: str, limit: int = 100, _raw: bool = False) -> Any:
        """单票上榜历史

:param sym: 6 位裸码（自动拼交易所后缀）
:param limit: 最近事件条数

:returns: ARR · 上榜事件行（字段与 by_date 一致；按日期升序返回）
        """
        kw: dict[str, Any] = {"sym": sym}
        if limit is not None:
            kw["limit"] = limit
        return _out(self._client.call("toplist.by_symbol", **kw, _raw=_raw), _raw)

class ValuationNS(_Ns):
    """每日估值（fund.valuation）"""

    def daily_basic(self, sym: str, begin: str | None = None, end: str | None = None, fields: list | None = None, _raw: bool = False) -> Any:
        """个股每日估值序列

:param sym: 6 位裸码
:param begin: ISO 起日（含），""=开区间
:param end: ISO 止日（含），""=开区间
:param fields: 字段子集 ARR，nil/空=全部 8 个

:returns: MAP 信封 {ok, as_of, data, meta}；data=长表 [{date, symbol, field, value}] 升序
        """
        kw: dict[str, Any] = {"sym": sym}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        if fields is not None:
            kw["fields"] = fields
        return _out(self._client.call("valuation.daily_basic", **kw, _raw=_raw), _raw)

    def daily_basic_multi(self, syms: list, begin: str | None = None, end: str | None = None, fields: list | None = None, _raw: bool = False) -> Any:
        """多票每日估值序列

:param syms: 标的清单 ARR（≥1）
:param begin: ISO 起日（含），""=开区间
:param end: ISO 止日（含），""=开区间
:param fields: 字段子集 ARR，nil/空=全部 8 个

:returns: MAP 信封 {ok, as_of, data, meta}；data=多票长表 [{date, symbol, field, value}] 升序，meta.per_symbol 给每票 count/oldest_scanned/truncated
        """
        kw: dict[str, Any] = {"syms": syms}
        if begin is not None:
            kw["begin"] = begin
        if end is not None:
            kw["end"] = end
        if fields is not None:
            kw["fields"] = fields
        return _out(self._client.call("valuation.daily_basic_multi", **kw, _raw=_raw), _raw)

class WorkoutNS(_Ns):
    """契约套利（disc.workout）"""

    def board(self, _raw: bool = False) -> Any:
        """进行中契约套利看板"""
        return _out(self._client.call("workout.board", _raw=_raw), _raw)

    def query(self, sym: str, _raw: bool = False) -> Any:
        """单票契约套利条款"""
        return _out(self._client.call("workout.query", sym=sym, _raw=_raw), _raw)

NAMESPACES: dict[str, type[_Ns]] = {
    "blocktrade": BlocktradeNS,
    "board": BoardNS,
    "bonus": BonusNS,
    "buyback": BuybackNS,
    "calendar": CalendarNS,
    "cbond": CbondNS,
    "equity": EquityNS,
    "estimates": EstimatesNS,
    "filings": FilingsNS,
    "forecast": ForecastNS,
    "fred": FredNS,
    "futures": FuturesNS,
    "fx": FxNS,
    "income": IncomeNS,
    "indices": IndicesNS,
    "intl": IntlNS,
    "kline": KlineNS,
    "macro": MacroNS,
    "margin": MarginNS,
    "moneyflow": MoneyflowNS,
    "notice": NoticeNS,
    "pdf_doc": Pdf_docNS,
    "reserve": ReserveNS,
    "rptdom": RptdomNS,
    "segments": SegmentsNS,
    "stocks": StocksNS,
    "toplist": ToplistNS,
    "valuation": ValuationNS,
    "workout": WorkoutNS,
}
