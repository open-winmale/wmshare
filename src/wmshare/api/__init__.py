"""友好 API：按四大类组织的推荐入口（行情 / 财务 / 披露 / 参考）。

设计约定：
  - 参数统一 ``symbol``（6 位裸码；自动归一 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀；
    港股 5 位、美股字母码）；
  - 方法名动宾化、可猜（bars/last/live/list/history/yield_ttm…）；
  - 返回 list[dict] / dict；返回列表的方法支持 ``_df=True`` 转 DataFrame，
    ``_raw=True`` 取未规范化原始行（仅部分方法）；
  - 本层是目录合同的薄翻译：高频方法显式包装；目录内其余函数经 ``__getattr__``
    属性直达（如 ``cli.kline.screen_above_ma20``、``cli.dividend.screen_quality``），
    目录之外的名字显式 AttributeError——269 个底层函数零遮蔽。
  - 选股能力集中在 ``cli.screener``：单票筛选器（bool）与全市场宽度（服务端
    预计算索引直出）显式包装，kline 目录的其余筛选函数经属性直达。

使用：
    cli = wmshare.Client.from_env()
    cli.kline.bars("600519", n=30)
    cli.statements.income("600519", years=5)
    cli.notice.list("600519", window="3m")
"""
from __future__ import annotations

import json
import re
import warnings
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from wmshare.errors import (
    CatalogError, DataError, LimitError, ServerError, UsageError, WmshareError)
from wmshare.units import finish_metric

# 服务端分桶 label 的排序前缀（如 i_涨停 / h_+5%~10%），单字母+下划线，对用户是噪音
_BIN_PREFIX = re.compile(r"^[a-z]_")


def _strip_bin_prefixes(rows: Any, key: str) -> Any:
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get(key), str):
                r[key] = _BIN_PREFIX.sub("", r[key])
    return rows

if TYPE_CHECKING:  # pragma: no cover
    from wmshare.client import Client

# 区间/窗口上限（与上游脚本仓对齐）：
#  - 上游 store 单次硬上限 10000 行（见 kernel vfunc_store_find.go）
#  - 分红命名窗口 token 最大 5y（sys/anchor.xs window_days）
#  - 上游未识别 token 会静默退化为 30 天，SDK 侧改为显式报错
MAX_RANGE_DAYS = 1825
WINDOW_DAYS = {"7d": 7, "1m": 30, "3m": 90, "6m": 180,
               "1y": 365, "3y": 1095, "5y": 1825}


def _range_bounds(begin: str, end: str) -> tuple[date, date]:
    try:
        b = date.fromisoformat(str(begin)[:10])
        e = date.fromisoformat(str(end)[:10])
    except ValueError:
        raise UsageError("begin/end 需为 YYYY-MM-DD 格式", code="range") from None
    if b > e:
        raise UsageError("begin 不能晚于 end", code="range")
    span = (e - b).days
    if span > MAX_RANGE_DAYS:
        raise LimitError(
            f"区间跨度 {span} 天超过上限 {MAX_RANGE_DAYS} 天（5 年）；"
            "更早数据请缩短区间或分批用 limit 获取", code="range")
    return b, e


_KLINE_FREQ_ALIASES = {
    None: "D", "": "D", "d": "D", "day": "D", "daily": "D",
    "w": "W", "week": "W", "weekly": "W",
    "m": "M", "month": "M", "monthly": "M",
}


def _kline_period_tag(freq: str | None) -> str:
    """freq 别名归一为脚本侧周期标签 D/W/M；未知值抛 UsageError（不静默降级）。"""
    key = None if freq is None else str(freq).strip().lower()
    try:
        return _KLINE_FREQ_ALIASES[key]
    except KeyError:
        raise UsageError(
            f'kline.bars: 不支持的 freq={freq!r}；可用 None/"D"（日）、"W"（周）、"M"（月）',
            code="freq") from None


def _filter_by_date(rows: Any, begin: str, end: str, key: str, limit: int) -> Any:
    """按日期列过滤（含端点）；行数已触顶且最早日期仍晚于 begin 时，说明区间未被覆盖。"""
    if not isinstance(rows, list):
        return rows
    b, e = _range_bounds(begin, end)
    out = []
    dates = []
    for r in rows:
        d = str(r.get(key) or "")[:10] if isinstance(r, dict) else ""
        if d:
            dates.append(d)
        if d and b.isoformat() <= d <= e.isoformat():
            out.append(r)
    if limit and len(rows) >= limit and dates and min(dates) > b.isoformat():
        raise LimitError(
            f"区间未被覆盖：单次返回 {len(rows)} 行（上限 {limit}），最早仅到 {min(dates)}；"
            "请缩小 begin/end 或调大 Client(max_limit=...)（上游单次硬上限 10000 行）",
            code="range")
    return out


def _window_days(window: str | int) -> int:
    if isinstance(window, int) or str(window).isdigit():
        days = int(window)
    elif window in WINDOW_DAYS:
        days = WINDOW_DAYS[window]
    else:
        raise UsageError(
            f"未知窗口 {window!r}；可选 {sorted(WINDOW_DAYS)} 或正整数天数"
            "（上游未知 token 会静默按 30 天处理，故此处显式报错）", code="window")
    if days <= 0 or days > MAX_RANGE_DAYS:
        raise LimitError(f"窗口 {days} 天超出支持范围 1~{MAX_RANGE_DAYS} 天（5 年）",
                         code="window")
    return days


def _to_df(result: Any) -> Any:
    from wmshare.client import _to_dataframe
    return _to_dataframe(result)


def _per_symbol(v: Any, fn: Any) -> Any:
    """批量结果逐标的映射 fn（errors 原样透传）；普通结果直接 fn(v)。

    供「传列表即批量」路径上需要后处理的显式包装方法复用（kline.last 等）。
    """
    from wmshare.client import BatchResult

    if isinstance(v, BatchResult):
        out = BatchResult(errors=v.errors)
        out.results = {s: fn(x) for s, x in v.results.items()}
        return out
    return fn(v)


def _finish_df(out: Any, df_flag: bool) -> Any:
    """_df 收口：批量结果逐标的转 DataFrame（与 call_batch(_df=True) 同语义）。"""
    if not df_flag:
        return out
    from wmshare.client import BatchResult

    if isinstance(out, BatchResult):
        out.results = {s: _to_df(x) for s, x in out.results.items()}
        return out
    return _to_df(out)


def _warn_large_moneyflow_list(symbol: Any) -> None:
    """全市场级资金流大列表的 EC 提示：批量按标的数逐票计价，逐票×全市场
    一轮就是百万级 EC（2026-11 事故：5,691 家 × 318 EC × 400 余遍 = 6 亿）。
    只提示不阻断——正确用法是分批 batch_iter 边取边落盘，而非放弃。"""
    if not isinstance(symbol, (list, tuple)):
        return
    n = len(symbol)
    if n >= 200:
        warnings.warn(
            f"moneyflow 大列表（{n} 只）走逐票批量：EC 按标的数逐票计价，"
            f"一轮约 {n * 318 // 10000} 万 EC 起步——批量省请求次数不省 EC。"
            "全市场最新资金流请用 cli.moneyflow.board()（服务端一次取数）；"
            "确需逐票历史请 batch_iter 分批边取边落盘。",
            stacklevel=3)


# 友好命名空间 → 目录（XS）命名空间。目录真实命名空间为
# bonus/cbond/equity/estimates/filings/forecast/index/intl/kline/margin/
# moneyflow/notice/rptdom/segments/workout；statements/indicator/info 是聚合层
# （indicator/info 走指标 eval，无目录函数）。
_FRIENDLY_NS_TO_CATALOG: dict[str, str] = {
    "kline": "kline",
    "screener": "kline",
    "moneyflow": "moneyflow",
    "statements": "rptdom",
    "notice": "notice",
    "filings": "filings",
    "forecast": "forecast",
    "dividend": "bonus",
    "equity": "equity",
    "margin": "margin",
    "estimates": "estimates",
    "cbond": "cbond",
    "workout": "workout",
    "index": "indices",
    "stocks": "stocks",
    "intl": "intl",
    "macro": "macro",
}


class _Api:
    def __init__(self, client: "Client"):
        self._c = client

    def __getattr__(self, name: str) -> Any:
        """目录感知兜底：友好类未显式定义的目录函数，委托 ``client.call(ns.name, ...)``。

        友好层只对高频方法做动宾化包装（bars/history/yield_ttm…）；目录内其余
        函数（筛选器 screen_*、全景 index_*、格式化 fmt_* 等）同样可经本属性
        直接调用，例如 ``cli.kline.screen_above_ma20("600519")``、
        ``cli.dividend.screen_quality("600519")``。非目录成员一律 AttributeError，
        且以双下划线开头的名称永不委托（避免干扰魔术方法解析）。
        """
        if name.startswith("__"):
            raise AttributeError(name)
        client = self._c
        ns = ""
        for cand, cls in FRIENDLY_NAMESPACES.items():
            if cls is type(self):
                ns = cand
                break
        catalog_ns = _FRIENDLY_NS_TO_CATALOG.get(ns, "")
        if not catalog_ns:
            raise AttributeError(name)  # indicator / info 等聚合层不提供目录委托
        qualified = f"{catalog_ns}.{name}"
        try:
            meta = client.catalog.function(qualified)
        except Exception:
            raise AttributeError(
                f"{type(self).__name__!s}.{name} 不存在；请查目录："
                f"cat.search({name!r}) 或 docs/API.md") from None
        params = meta.get("params") or client.catalog.inventory_params(qualified)
        param_names = [p["name"] for p in params]
        call = client.call

        def _delegate(*args: Any, **kwargs: Any) -> Any:
            if len(args) > len(param_names):
                raise UsageError(
                    f"{qualified}: 最多接受 {len(param_names)} 个位置参数，"
                    f"收到 {len(args)} 个；参数顺序 {param_names}", code="params")
            bound = dict(kwargs)
            for pname, value in zip(param_names, args):
                if pname in bound:
                    raise UsageError(
                        f"{qualified}: 参数 {pname!r} 同时以位置和关键字传入",
                        code="params")
                bound[pname] = value
            return call(qualified, **bound)

        _delegate.__name__ = name
        _delegate.__qualname__ = f"{type(self).__name__}.{name}"
        return _delegate


# ---------------------------------------------------------------- 行情 market
class KlineApi(_Api):
    """行情与 K 线。单位：价格=元，量=股(A股默认换算；`native` 保留手)，涨跌幅=小数。"""

    def bars(self, symbol: str, n: int | None = None, adj: str | None = None,
             begin: str | None = None, end: str | None = None,
             freq: str | None = None,
             _raw: bool = False, _df: bool = False) -> Any:
        """K 线序列（日/周/月，date/open/high/low/close/volume/amount/percent）。

        日 K 覆盖自上市首日起的全部交易日（最早 1991 年）；周/月 K 为服务端预派生
        （由日线先复权再聚合，date 为周期末交易日）。

        :param n: 根数（按所选周期计），默认 120；区间查询时默认取 max_limit（上限 10000）
        :param adj: None=不复权；"qfq"=前复权；"hfq"=后复权
        :param begin: 起始日期（含，YYYY-MM-DD），须与 end 同时提供；区间上限 5 年
        :param end: 结束日期（含）
        :param freq: None/"D"=日 K（默认）；"W"=周 K；"M"=月 K；指数只有日频，freq 非 D 返回空列表
        """
        period = _kline_period_tag(freq)
        period_args: dict[str, Any] = {} if period == "D" else {"period": period}
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            if _raw:
                raise UsageError("_raw=True 时不支持 begin/end（原始行无扁平日期字段）",
                                 code="range")
            limit = min(int(n) if n is not None else (self._c.max_limit or 10000), 10000)
            if adj is None:
                fn = "kline.query_bars_period" if period_args else "kline.query_bars"
            else:
                fn = ("kline.query_bars_period_adj" if period_args
                      else "kline.query_bars_adj")
            kwargs: dict[str, Any] = {"sym": symbol, "limit": limit, "_raw": _raw}
            if adj is not None:
                kwargs["adj"] = adj
            kwargs.update(period_args)
            rows = self._c.call(fn, **kwargs)
            out = _per_symbol(rows, lambda r: _filter_by_date(r, begin, end, "date", limit))
            return _finish_df(out, _df)
        limit = 120 if n is None else n
        if adj is None:
            fn = "kline.query_bars_period" if period_args else "kline.query_bars"
        else:
            fn = ("kline.query_bars_period_adj" if period_args
                  else "kline.query_bars_adj")
        kwargs = {"sym": symbol, "limit": limit, "_raw": _raw, "_df": _df}
        if adj is not None:
            kwargs["adj"] = adj
        kwargs.update(period_args)
        return self._c.call(fn, **kwargs)

    def last(self, symbol: str, _raw: bool = False) -> Any:
        """最新一根日 K（date/open/high/low/close/volume/amount/percent），无数据返回 None。

        经规范化序列取最新一行，字段与 ``bars()`` 一致；``_raw=True`` 时跳过规范化，
        返回上游原始行（字段名不同，含 CreatedAt/sampling 等）。
        """
        rows = self._c.call("kline.query_bars", sym=symbol, limit=1, _raw=_raw)
        return _per_symbol(rows, lambda r: r[0] if r else None)

    def live(self, symbol: str, _raw: bool = False) -> Any:
        """盘中最新快照（盘中 tip；休市返回最近收盘快照）。"""
        return self._c.call("kline.query_last_live", sym=symbol, _raw=_raw)

    def batch_live(self, symbols: list[str], _raw: bool = False) -> dict:
        """多标的盘中快照（单次请求，返回 {symbol: bar}）。

        :param symbols: 标的列表（自动去重与归一），单次上限同 ``Client(max_limit=...)``
        """
        if self._c.max_limit is not None and len(symbols) > self._c.max_limit:
            raise LimitError(
                f"kline.batch_live: 批量标的数 {len(symbols)} 超过上限 {self._c.max_limit}"
                "（请分批，如 symbols[i:i+500]；可在 Client(max_limit=...) 调整）",
                code="limit")
        # 跨市场混批会在本市场上下文里取到错值，与 call_batch/batch_all 同一条铁律
        self._c._assert_same_market("kline.batch_live",
                                    [self._c._canon_symbol(s) for s in symbols])
        return self._c.call("kline.query_last_live_many", syms=symbols, _raw=_raw)

    def min1(self, symbol: str) -> Any:
        """当日 1 分钟分时（有损合成采样，非逐笔；休市返回上一交易日）。

        美股仅在美股盘中时段（北京时间夏 21:30–04:00 / 冬 22:30–05:00）写入、
        保留 36 小时——北京白天查询为空属预期，取最新价量请用 ``live/snapshot``。
        """
        return self._c.call("kline.query_min1_live", sym=symbol)

    def snapshot(self, symbol: str) -> Any:
        """行情摘要（symbol/close/percent/chg_20d）。"""
        return self._c.call("kline.snapshot", sym=symbol)

    def is_etf(self, symbol: str) -> bool:
        """是否场内 ETF。"""
        return bool(self._c.call("kline.is_etf", sym=symbol))


class MoneyflowApi(_Api):
    """资金流向（日频：主力/超大单/大单/中单/小单净流入，单位=元；非逐笔 Level2）。"""

    def bars(self, symbol: str, n: int | None = None,
             begin: str | None = None, end: str | None = None,
             _raw: bool = False, _df: bool = False) -> Any:
        """资金流历史（date/net_mf/elg_net/lg_net/md_net/sm_net）。

        :param n: 条数，默认 20；区间查询时默认取 max_limit（上限 10000）
        :param begin: 起始日期（含，YYYY-MM-DD），须与 end 同时提供；区间上限 5 年
        :param end: 结束日期（含）
        """
        _warn_large_moneyflow_list(symbol)
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            if _raw:
                raise UsageError("_raw=True 时不支持 begin/end（原始行无扁平日期字段）",
                                 code="range")
            limit = min(int(n) if n is not None else (self._c.max_limit or 10000), 10000)
            rows = self._c.call("moneyflow.query_bars", sym=symbol, limit=limit, _raw=_raw)
            out = _per_symbol(rows, lambda r: _filter_by_date(r, begin, end, "date", limit))
            return _finish_df(out, _df)
        limit = 20 if n is None else n
        return self._c.call("moneyflow.query_bars", sym=symbol, limit=limit,
                            _raw=_raw, _df=_df)

    def last(self, symbol: str, _raw: bool = False) -> Any:
        """最新一行资金流（date/net_mf/elg_net/lg_net/md_net/sm_net），无数据返回 None。

        经规范化序列取最新一行，字段与 ``bars()`` 一致；``_raw=True`` 时返回 store
        原始行（净流入嵌在 props 下）。
        """
        _warn_large_moneyflow_list(symbol)
        rows = self._c.call("moneyflow.query_bars", sym=symbol, limit=1, _raw=_raw)
        return _per_symbol(rows, lambda r: r[0] if r else None)

    def live(self, symbol: str, _raw: bool = False) -> Any:
        """资金流当日读数（外部公开源、短 TTL、非盘中行情、仅 A 股）；无快照时返回 None。"""
        return self._c.call("moneyflow.query_last_live", sym=symbol, _raw=_raw)

    def board(self, _df: bool = False) -> Any:
        """全市场资金流快照：一次取数，按主力净流入降序（日频 EOD，仅 A 股非停牌）。

        字段 symbol/name/net_mf/net_mv_ratio/lg_net/elg_net/md_net/sm_net/industry，
        金额=元、占比=小数。服务端索引直出——替代「全市场逐票批量」的正解：
        EC 只花一次求值的计算量，不再是 标的数 × 单票成本。非交易日数据不变；
        当日读数用 ``live()``（外部公开源，非盘中行情）。
        """
        return self._c.call("moneyflow.board", _df=_df)

class MarginApi(_Api):
    """融资融券（个股日频）。

    融资买入/偿还/余额与融券卖出/偿还/余量；金额=元、量=股（与全库基础单位
    一致）。``latest`` 为最新一日单行；仅个股口径，市场级两融汇总上游无数据集。
    """

    def query(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """个股两融历史（trade_date/fin_buy_amt/fin_repay_amt/fin_balance/…）。

        :param limit: 条数，默认 20
        """
        return self._c.call("margin.query", sym=symbol, limit=limit, _df=_df)

    def latest(self, symbol: str) -> Any:
        """最新一日两融单行，字段同 ``query()``。"""
        return self._c.call("margin.latest", sym=symbol)


class CbondApi(_Api):
    """可转债——合约快照/条款事件/正股关联/强赎触发/独立日 K。

    价格为面值 100 口径（元）；转债无除权口径，日 K 不复权。``board`` 是
    全市场面板（快照 + 最新事件 + 盘中价 + callHits + resetFloor）；``call_hits``
    统计正股无复权收盘 ≥ 强赎触发价的近窗交易日数，勿以单日价判定已满足；
    ``kline_window`` 返回 store 列式窗口（open/close/high/low/volume/amount）。
    目录内其余函数（quote_list/event_list/min1_live 等）经属性直达。
    """

    def board(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债全市场面板：快照行 + 每债最新条款事件 + 盘中债价 overlay
        + 强赎触发计数（callHits）+ 下修地板价（resetFloor）。

        行为 latest_quotes 规范化行的超集（event/bondPercent/callHits/resetFloor）。
        注意：全市场重计算，openapi 沙箱（xs eval）有燃料上限，经 API 端点调用不受限。
        """
        return self._c.call("cbond.board", _raw=_raw, _df=_df)

    def latest_quotes(self, _raw: bool = False, _df: bool = False) -> Any:
        """全市场转债最新快照（按日更新；行字段经 fmt_quote 规范化）。"""
        return self._c.call("cbond.latest_quotes", _raw=_raw, _df=_df)

    def of_stock(self, symbol: str, _raw: bool = False, _df: bool = False) -> Any:
        """正股关联的转债快照行。

        :param symbol: 正股代码（6 位裸码）
        """
        return self._c.call("cbond.of_stock", stk=symbol, _raw=_raw, _df=_df)

    def query(self, symbol: str, _df: bool = False) -> Any:
        """按转债标的查条款事件（下修/回售/赎回等，规范化事件行）。

        :param symbol: 转债代码
        """
        return self._c.call("cbond.query", sym=symbol, _df=_df)

    def call_hits(self, symbol: str, trig: float) -> Any:
        """正股近窗收盘 ≥ 强赎触发价 trig 的交易日数（int）。

        :param symbol: 正股代码（6 位裸码）
        :param trig: 强赎触发价（元，面值 100 口径的正股价）
        """
        return self._c.call("cbond.call_hits", code=symbol, trig=trig)

    def kline_window(self, symbol: str, n: int) -> Any:
        """转债日 K 窗口（列式 MAP：open/close/high/low/volume/amount；不复权）。

        :param symbol: 转债代码
        :param n: 窗口根数
        """
        return self._c.call("cbond.kline_window", code=symbol, n=n)

    def universe_codes(self, _raw: bool = False, _df: bool = False) -> Any:
        """转债代码全集（与快照口径一致）。"""
        return self._c.call("cbond.universe_codes", _raw=_raw, _df=_df)

    # ---- 研究级组合接口：取数 → 规则 → 事实包 → 成稿/出图，一条链路。----
    # 这些方法**不是**目录函数的薄翻译，故不登记 FRIENDLY_INDEX（那张表是
    # 「核心接口 ↔ 底层目录函数」的一一映射，生成器靠它回溯 returns_shape）。
    def daily(self, as_of: str | None = None, top_n: int = 20,
              budget: int = 30) -> dict[str, Any]:
        """跑一期可转债日更，返回事实包（三层口径 + 三道闸 + 状态机 + 事件日历）。

        取数只发三次请求：全市场面板一次、条款事件一次、榜单前三各一次日 K
        通道；``budget`` 是硬上限，超出直接报错而不静默降级。

        返回 ``{facts, derived, gates, states, top, scatter, calendar,
        featured_band, caliber_layers, coverage}``。每个数字都带 ``sources``
        与 ``as_of``；口径见 ``wmshare.cb.facts`` 模块文档。

        :param as_of: 期望的快照日 ``YYYY-MM-DD``（缺省取面板自带 asOf）
        :param top_n: 榜单条数
        :param budget: 单期请求上限
        """
        from wmshare.cb import DailyConfig, run_daily

        return run_daily(self._c, as_of=as_of,
                         config=DailyConfig(top_n=top_n, budget=budget))

    def article(self, payload: dict[str, Any], date: str | None = None,
                campaign: str | None = None,
                fig_dir: str = "figs") -> dict[str, str]:
        """把事实包写成图文稿件：源稿 Markdown + 公众号适配稿 + 摘要。

        数字只从 ``payload`` 里拷贝，缺条目即抛 ``LookupError``——不补猜测值。

        :param payload: ``daily()`` 返回的事实包
        :param date: 文件名日期 ``YYYYMMDD``（缺省取事实包的快照日）
        :param campaign: UTM campaign（缺省 ``day{date}cb``）
        :param fig_dir: 正文图片链接前缀；正式发布用相对路径 ``figs``，
            演练写临时目录时传绝对路径，配图存在性校验才能定位到真实文件
        """
        from wmshare.cb import article as A

        d = date or str(payload.get("date") or "").replace("-", "")
        if not d:
            raise UsageError("缺少日期：请传 date=YYYYMMDD 或使用带 date 的事实包",
                             code="params")
        camp = campaign or f"day{d}cb"
        fa = A.Facts(payload)
        src = A.build_source(fa, d, str(payload.get("date") or ""), camp, fig_dir)
        summary = A.build_summary(fa)
        return {"source": src, "wechat": A.build_wechat(src, camp, summary),
                "summary": summary, "date": d, "campaign": camp}

    def figures(self, payload: dict[str, Any], out_dir: str,
                date: str | None = None,
                klines: dict[str, Any] | None = None) -> dict[str, str]:
        """出当期图：双低榜表格、全市场价差散点、候选个券价格通道。

        需要 matplotlib：``pip install "wmshare[figures]"``。

        :param payload: ``daily()`` 返回的事实包
        :param out_dir: 输出目录（不存在则创建）
        :param date: 文件名日期 ``YYYYMMDD``（缺省取事实包快照日）
        :param klines: 通道图用的日 K（缺省取事实包里的 featured_klines）
        """
        from wmshare.cb import article as A
        from wmshare.cb import figures as G

        d = date or str(payload.get("date") or "").replace("-", "")
        if not d:
            raise UsageError("缺少日期：请传 date=YYYYMMDD 或使用带 date 的事实包",
                             code="params")
        fa = A.Facts(payload)
        outs = G.render_all(fa, out_dir, date=d,
                            klines=klines or payload.get("featured_klines"))
        return {k: str(v) for k, v in outs.items()}


class IndexApi(_Api):
    """指数维度——指数键/成分股/权重股/宽基估值时序。

    ``key`` 为服务端指数键（先用 ``keys()`` 列出，形如 index.hs300，勿臆造）；
    成分行含市值与估值中枢（roe_ttm/pe_ttm 为指标层原值，SDK 不再换算）；
    权重为披露权重（已换算小数）；估值时序为整体法 PE/PB 季采样 + 当前值/股息率。
    指数行情（K 线/快照）走 ``cli.kline``。
    """

    def keys(self, _df: bool = False) -> Any:
        """可用指数键列表（``members``/``weights``/``valuation`` 的 key 取值域）。"""
        return self._c.call("indices.keys", _df=_df)

    def members(self, key: str, sort_by: str | None = None,
                top_n: int | None = None, _df: bool = False) -> Any:
        """指数成分股（含市值/估值中枢，可按 mv/pe/pb/roe/ps 排序）。

        :param key: 指数键（见 ``keys()``）
        :param sort_by: 排序字段（mv/pe/pb/roe/ps）
        :param top_n: 只取前 N 条
        """
        kw: dict[str, Any] = {"key": key}
        if sort_by is not None:
            kw["sort_by"] = sort_by
        if top_n is not None:
            kw["top_n"] = top_n
        return self._c.call("indices.members", **kw, _df=_df)

    def weights(self, key: str, top_n: int | None = None,
                _df: bool = False) -> Any:
        """指数权重股（披露权重降序；weight 为小数，0.071 = 7.1%）。

        :param key: 指数键（见 ``keys()``）
        :param top_n: 只取前 N 条
        """
        kw: dict[str, Any] = {"key": key}
        if top_n is not None:
            kw["top_n"] = top_n
        return self._c.call("indices.weights", **kw, _df=_df)

    def valuation(self, key: str, points: int | None = None) -> Any:
        """宽基估值时序（整体法 PE/PB 季采样点 d/pe/pb + 当前值/股息率）。

        :param key: 指数键（见 ``keys()``）
        :param points: 季采样点数；series 可自行算分位
        """
        kw: dict[str, Any] = {"key": key}
        if points is not None:
            kw["points"] = points
        return self._c.call("indices.valuation", **kw)

    def universe_keys(self, group: str = "broad") -> Any:
        """指数域可用键（榜单/估值场景的推荐取值域，按组返回）。

        与 ``keys()`` 的区别：keys() 返回服务端全部注册键，本方法只返回有名录
        支撑、可整体法估值或可算分位的键。

        :param group: ``broad``（默认，11 个宽基）/ ``industry``（申万一级）/
            ``dividend``（红利类 14 键）/ ``all``（三组并集）
        """
        try:
            return self._c.call("indices.universe_keys", group=group)
        except Exception:
            # 旧服务端只接受零参调用：降级为默认宽基组，分组能力等平台升级后自动生效
            if str(group or "broad").lower() in ("broad", ""):
                return self._c.call("indices.universe_keys")
            raise

    def trend(self, key: str, window: str = "5y") -> dict[str, Any]:
        """周频整体法估值趋势（平台预热缓存，指数估值分位的推荐基座）。

        返回 ``{ok, key, as_of, density, points, pe_pct, pb_pct, med, window,
        win_start, win_n, win_trunc, pct, pct_source, dv_has_history}``：

        - ``points`` 为 ``[{date, pe, pb}, ...]``，**降序（新→旧）**，
          ``points[0]`` 是最新点——服务端 ``cursor.ds`` 的原始顺序
        - ``pe_pct``/``pb_pct`` 是最新点在 ``window`` 窗口内的历史分位
          （0=最低，1=最高）；口径 ``rank0/(n-1)``、并列取中点，与前端一致
        - ``pct`` 给出 3y/5y/10y 三档：``{"pe": {...}, "pb": {...}, "pe_med": {...}}``，
          每档含 ``p``/``p3``/``p5``/``p10`` 与样本数 ``n3``/``n5``/``n10``
        - ``win_trunc=True`` 表示缓存序列盖不住所选窗口，此时相关分位为 None
          （**不拿短窗口冒充长窗口**）
        - ``dv_has_history=False``：股息率只有当前值，没有历史序列，不出分位

        :param key: 指数/行业/红利键（见 ``universe_keys()``）
        :param window: 分位窗口 ``3y``/``5y``/``10y``，默认 ``5y``
        """
        w = str(window or "5y").lower()
        if w not in ("3y", "5y", "10y"):
            w = "5y"
        try:
            raw = self._c.call("indices.trend", key=key, window=w)
        except Exception:
            # 旧服务端只接受 key 一参：退回单参调用并在客户端自算分位
            raw = self._c.call("indices.trend", key=key)
        if not isinstance(raw, dict):
            return {"ok": False, "key": key, "as_of": "", "density": "weekly",
                    "points": [], "pe_pct": None, "pb_pct": None, "med": [],
                    "window": w, "win_start": "", "win_n": 0, "win_trunc": True,
                    "pct": {}, "pct_source": "client", "dv_has_history": False}
        base = raw.get("base") or []
        pts = [{"date": str(p[0])[:10], "pe": p[1], "pb": p[2]}
               for p in base if isinstance(p, (list, tuple)) and len(p) >= 3]
        server_pct = raw.get("pct") or {}
        # 服务端 base 是「新→旧」：当前值就是 pts[0]。
        # 这里曾经写成 reversed(pts)，取到的是**最旧点**，把 2020 年的分位当今天用。
        last_pe = next((p["pe"] for p in pts
                        if isinstance(p.get("pe"), (int, float)) and p["pe"] > 0), None)
        last_pb = next((p["pb"] for p in pts
                        if isinstance(p.get("pb"), (int, float)) and p["pb"] > 0), None)

        def _pct(cur: float | None, vals: list[float]) -> float | None:
            """本地分位（服务端未部署 pct 时的兜底）：rank0/(n-1)，并列取中点。"""
            if cur is None or len(vals) < 60:
                return None
            ordered = sorted(vals)
            lo = sum(1 for v in ordered if v < cur)
            eq = sum(1 for v in ordered if v == cur)
            if eq <= 0 or len(ordered) < 2:
                return None
            return (lo + lo + eq - 1) / 2 / (len(ordered) - 1)

        def _cut(asof: str, years: int) -> str:
            """窗口下界：asof 回退 years 年（与前端 cutoffIso 同口径）。"""
            head = str(asof)[:4]
            if len(str(asof)) < 10 or not head.isdigit():
                return ""
            return f"{int(head) - years}{str(asof)[4:10]}"

        def _win(col: str, years: int) -> tuple[float | None, int, bool]:
            """按窗口取样本：返回 (最新点分位, 样本数, 是否因序列过短而截断)。

            序列盖不住窗口时返回 (None, n, True)——**不拿短窗口冒充长窗口**，
            与 XS 侧 ``indices.pct_window`` 的 trunc→nil 语义一致。
            """
            cur = last_pb if col == "pb" else last_pe
            cut = _cut(str(raw.get("asof") or ""), years)
            rows = [p for p in pts if p["date"] >= cut] if cut else list(pts)
            vals = [p[col] for p in rows
                    if isinstance(p.get(col), (int, float)) and p[col] > 0]
            earliest = min((p["date"] for p in pts if p["date"]), default="")
            trunc = bool(cut) and earliest > cut
            return (None if trunc else _pct(cur, vals)), len(vals), trunc

        def _server(col: str, field: str) -> float | None:
            node = server_pct.get(col)
            if not isinstance(node, dict):
                return None
            val = node.get(field)
            return val if isinstance(val, (int, float)) else None

        pe_pct = _server("pe", "p")
        pb_pct = _server("pb", "p")
        source = "server"
        win_n = int(raw.get("win_n") or 0)
        win_trunc = bool(raw.get("win_trunc", False))
        if pe_pct is None and pb_pct is None:
            # 旧服务端没有 pct/窗口：本地按同一口径补算，并如实标记截断
            years = int(w[:-1]) if w[:-1].isdigit() else 5
            pe_pct, pe_n, pe_trunc = _win("pe", years)
            pb_pct, pb_n, pb_trunc = _win("pb", years)
            win_n, win_trunc, source = max(pe_n, pb_n), (pe_trunc or pb_trunc), "client"
        return {"ok": bool(raw.get("ok")), "key": key,
                "as_of": str(raw.get("asof") or ""),
                "density": str(raw.get("density") or "weekly"),
                "n": len(pts), "points": pts,
                "pe_pct": pe_pct, "pb_pct": pb_pct,
                "med": raw.get("med") or [],
                "window": str(raw.get("window") or w),
                "win_start": str(raw.get("win_start") or ""),
                "win_n": win_n,
                "win_trunc": win_trunc,
                "pct": server_pct,
                "pct_source": source,
                "dv_has_history": bool(raw.get("dv_has_history", False))}


# ---------------------------------------------------------------- 证券基础 market
class StocksApi(_Api):
    """全市场证券列表与行业映射（代码池 / 行业成分；stocks 目录域）。

    证券行字段：symbol/name/exchange/industry(三级行业键)/industry_name/is_st/listed。
    美股：列表与个股行业码可用；行业目录树上游未灌数，``industries()`` 恒空。
    """

    def list(self, _df: bool = False) -> Any:
        """全市场证券列表（当前市场；A≈5.7k / 港≈2.8k / 美≈5.3k 行，排序不保证）。

        全表单次返回，无分页；随上游每日刷新（美股 universe 为手动刷新，有滞后）。
        """
        return self._c.call("stocks.query_list", _df=_df)

    def industries(self, level: int | None = None, _df: bool = False) -> Any:
        """行业目录（standard: sw2021 申万 | hsi 恒生）。

        :param level: None=全部层级；1..3=指定级
        行字段：symbol/name/level/parent/standard。
        """
        kw: dict[str, Any] = {}
        if level is not None:
            kw["level"] = int(level)
        return self._c.call("stocks.industry_list", _df=_df, **kw)

    def industry_members(self, industry: str, top_n: int | None = None,
                         _df: bool = False) -> Any:
        """行业成分股（任意层级节点；行字段同 ``list()``）。

        :param industry: 行业键 "industry.S48"、行业代码 "S48"、或中文名（如 "银行"；
            中文名未命中/多候选时报错并列出候选）
        :param top_n: 只取前 N 条（客户端截断；None=全量，单行业最大几百行）
        """
        ind = str(industry)
        try:
            rows = self._c.call("stocks.industry_members", ind=ind)
        except WmshareError:
            rows = self._c.call("stocks.industry_members",
                                ind=self._resolve_industry(ind))
        rows = rows if isinstance(rows, list) else []
        if top_n is not None:
            rows = rows[: max(int(top_n), 0)]
        if _df:
            from wmshare.client import _to_dataframe
            return _to_dataframe(rows)
        return rows

    def _resolve_industry(self, name: str) -> str:
        """中文名 → 行业键：唯一包含匹配直用；多候选/未命中报错列候选。"""
        catalog = self._c.call("stocks.industry_list") or []
        hits = [r for r in catalog if name in str(r.get("name") or "")]
        if len(hits) == 1:
            return "industry." + str(hits[0]["symbol"])
        if len(hits) > 1:
            sample = "、".join(f"{r.get('symbol')} {r.get('name')}" for r in hits[:8])
            raise UsageError(
                f"行业名 {name!r} 命中 {len(hits)} 个行业：{sample}；"
                "请改用行业代码（industries() 的 symbol 列）", code="params")
        raise UsageError(
            f"未找到行业 {name!r}；先调 industries() 查目录，或改用行业代码（如 S48）",
            code="params")


# ---------------------------------------------------------------- 选股 market
class ScreenerApi(_Api):
    """选股与全景：单票筛选器（bool）+ 全市场涨跌宽度（服务端预计算索引直出）。

    筛选阈值统一**小数**（0.10 = 10%）；事件筛选以「当日有成交」为前置
    （停牌恒 False）。全市场四件套（全景/分桶/行业分布/涨跌榜）由服务端索引
    聚合直出、免本地计算；``idx`` 不传时由服务端解析 A 股最新查询索引。
    口径注记：宽度返回中 ``up_pct``/``down_pct``/``flat_pct`` 与分桶
    ``pct_of_total`` 为百分数数值（52.3 = 52.3%），``median_pct`` 与涨跌幅为
    小数（0.01 = 1%）。kline 目录的其余筛选函数经属性直达
    （如 ``cli.screener.screen_up_today("600519")``），``cat.search("screen")``
    可查全部；股息质量筛选器见 ``cli.dividend.screen_*``。
    """

    # ---- 单票事件筛选 ----
    def screen_limit_up(self, symbol: str) -> bool:
        """今日涨停（涨幅 > 0.10；停牌返回 False）。"""
        return bool(self._c.call("kline.screen_limit_up", sym=symbol))

    def screen_limit_down(self, symbol: str) -> bool:
        """今日跌停（涨幅 < -0.10；停牌返回 False）。"""
        return bool(self._c.call("kline.screen_limit_down", sym=symbol))

    # ---- 单票均线/量能/动量筛选 ----
    def screen_above_ma20(self, symbol: str) -> bool:
        """收盘价站上 MA20（60/120 日线变体经属性直达 screen_above_ma60/ma120）。"""
        return bool(self._c.call("kline.screen_above_ma20", sym=symbol))

    def screen_ma60_up(self, symbol: str) -> bool:
        """MA60 上行（中期趋势向上）。"""
        return bool(self._c.call("kline.screen_ma60_up", sym=symbol))

    def screen_breakout_ma20(self, symbol: str) -> bool:
        """突破 MA20（站上 MA20 且 MA60 上行的组合确认）。"""
        return bool(self._c.call("kline.screen_breakout_ma20", sym=symbol))

    def screen_momentum_20d(self, symbol: str, min_chg: float = 0.10) -> bool:
        """近 20 日涨幅达标（动量强）。

        :param min_chg: 20 日累计涨幅下限（小数，0.10 = 10%）
        """
        return bool(self._c.call("kline.screen_momentum_20d", sym=symbol, min_chg=min_chg))

    def screen_pullback_20d(self, symbol: str, min_chg: float = -0.10) -> bool:
        """近 20 日涨幅低于上限（回撤/未过热）。

        :param min_chg: 20 日累计涨幅的**上限**（小数）：默认 -0.10（近 20 日
            跌超 10%，深度回撤）；传 0.10 表示剔除已涨超 10% 的标的
        """
        return bool(self._c.call("kline.screen_pullback_20d", sym=symbol, min_chg=min_chg))

    def screen_volume_spike(self, symbol: str, min_ratio: float = 1.5) -> bool:
        """放量（5 日量比超阈值）。

        :param min_ratio: 量比下限，默认 1.5（5 日均量的 1.5 倍）
        """
        return bool(self._c.call("kline.screen_volume_spike", sym=symbol,
                                 min_ratio=min_ratio))

    # ---- 全市场宽度（服务端索引直出，免本地计算）----
    # idx 不传时由服务端解析最新 A 股查询索引（LatestIndexKey，动态 cache_key，
    # 无稳定字面量——不要臆造 "index.cn.all" 之类的键，实测 500）。
    def _breadth(self, fn: str, idx: str | None, _df: bool,
                 label_key: str | None = None) -> Any:
        if idx is None:
            rows = self._c.eval_result(f"return {fn}(LatestIndexKey())")
        else:
            rows = self._c.call(fn, idx=idx)
        if label_key is not None:
            rows = _strip_bin_prefixes(rows, label_key)
        return _to_df(rows) if _df else rows

    def index_breadth_summary(self, idx: str | None = None) -> dict:
        """全市场涨跌全景（上涨/下跌/平盘家数、占比与涨跌幅中位数）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_summary", idx, _df=False)

    def index_breadth_bins(self, idx: str | None = None, _df: bool = False) -> Any:
        """涨跌幅 9 档分桶（涨停/±5%/±3%/平盘/…/跌停），行含 label/count/pct_of_total。

        label 已剥服务端排序前缀（上游 `i_涨停` → `涨停`）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_bins", idx, _df, label_key="label")

    def index_breadth_bin_industries(self, idx: str | None = None,
                                     _df: bool = False) -> Any:
        """涨跌幅分桶 × 一级行业分布（行含 bin/industry/count；bin 同样剥前缀）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_bin_industries", idx, _df,
                             label_key="bin")

    def index_top_movers(self, limit: int = 20, desc: bool = True,
                         idx: str | None = None, _df: bool = False) -> Any:
        """涨跌榜（按当日涨跌幅排序，行含 symbol/name/percent；percent 为小数）。

        :param limit: 条数，默认 20；受 Client(max_limit=...) 与单次 10000 行硬上限钳制
        :param desc: true=涨幅榜（默认）；false=跌幅榜
        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        cap = min(self._c.max_limit or 10000, 10000)
        if limit > cap:
            raise LimitError(
                f"index_top_movers: limit={limit} 超过单次上限 {cap}"
                "（防止单次拉取过大；可在 Client(max_limit=...) 调整，设 None 关闭）",
                code="limit")
        if idx is None:
            xs = (f"return kline.index_top_movers(LatestIndexKey(), {int(limit)}, "
                  f"{'true' if desc else 'false'})")
            rows = self._c.eval_result(xs)
        else:
            rows = self._c.call("kline.index_top_movers", idx=idx, limit=limit, desc=desc)
        return _to_df(rows) if _df else rows


# ---------------------------------------------------------------- 财务 fundamentals
class StatementsApi(_Api):
    """三大报表科目透视（披露原值；金额=报表原币）。

    各方法返回科目行列表（科目代码/中文名 × 期次列）；树视图另含派生比率行。
    ``kind`` 取值：``balance``（资产负债）/``income``（利润）/``cashflow``（现金流）。

    :param years: 期数（年报降序，默认 5）
    :param scope: "合并"（默认）或 "母公司"
    """

    _DOMAINS = {"balance": "fin.balance_sheet",
                "income": "fin.income_statement",
                "cashflow": "fin.cashflow_statement"}

    @classmethod
    def _domain(cls, kind: str) -> str:
        try:
            return cls._DOMAINS[kind]
        except KeyError:
            raise UsageError(f"未知报表 kind={kind!r}；可选 {sorted(cls._DOMAINS)}",
                             code="params") from None

    def balance(self, symbol: str, years: int = 5, scope: str = "合并",
                _raw: bool = False, _df: bool = False) -> Any:
        """资产负债表（fin.balance_sheet）。"""
        return self._c.call("rptdom.statement", sym=symbol, domain="fin.balance_sheet",
                            opts={"scope": scope, "n": years}, _raw=_raw, _df=_df)

    def income(self, symbol: str, years: int = 5, scope: str = "合并",
               _raw: bool = False, _df: bool = False) -> Any:
        """利润表（fin.income_statement，含费用四率原料行）。"""
        return self._c.call("rptdom.statement", sym=symbol, domain="fin.income_statement",
                            opts={"scope": scope, "n": years}, _raw=_raw, _df=_df)

    def cashflow(self, symbol: str, years: int = 5, scope: str = "合并",
                 _raw: bool = False, _df: bool = False) -> Any:
        """现金流量表（fin.cashflow_statement）。"""
        return self._c.call("rptdom.statement", sym=symbol, domain="fin.cashflow_statement",
                            opts={"scope": scope, "n": years}, _raw=_raw, _df=_df)

    def compare(self, symbol: str, kind: str = "income", years: int = 2,
                _raw: bool = False, _df: bool = False,
                _units: str = "base") -> Any:
        """合并 vs 母公司比较：科目行 + 合并值/母公司值/差额/差额占比。

        差额占比为**小数**（diffp = 差额 / 合并值，0.078 = 7.8%；SDK 自动由脚本
        的百分数口径换算，``_units="native"`` 可取原值）；母公司未披露的科目差额为空。
        """
        return self._c.call("rptdom.statement_compare", sym=symbol,
                            domain=self._domain(kind), opts={"n": years},
                            _raw=_raw, _df=_df, _units=_units)

    def tree(self, symbol: str, kind: str = "balance", years: int = 5,
             scope: str = "合并", _raw: bool = False, _df: bool = False) -> Any:
        """报表目录树视图：按树序输出科目行，含派生比率行（流动比率/资产负债率/毛利率等）。

        注意：派生行的数值口径按行内标记区分——``pct`` 行的 vals 为百分数（原生，
        未换算）、``fmt="x"`` 行为倍数、其余科目行为报表原币元；与 compare() 的统一
        小数口径不同，树视图适合展示/核对而非跨接口运算。
        """
        return self._c.call("rptdom.statement_tree", sym=symbol,
                            domain=self._domain(kind), opts={"scope": scope, "n": years},
                            _raw=_raw, _df=_df)

    def years(self, symbol: str, kind: str = "income", _df: bool = False) -> Any:
        """该报表可用的年报年份（降序）。"""
        return self._c.call("rptdom.statement_years", sym=symbol,
                            domain=self._domain(kind), _df=_df)

    def audit(self, symbol: str) -> Any:
        """审计意见（按年报，返回 {年份: 意见}）。"""
        return self._c.call("rptdom.statement_audit", sym=symbol)


class SegmentsApi(_Api):
    """经营分部：主营构成的多维分解（分产品 / 分业务 / 分区域 / 主营标签占比）。

    行结构统一 ``{name, tr, tr_text, cost, margin, ratio}``：收入/成本为**元**，
    毛利率与占比为**小数**（margin = (tr-cost)/tr，0.332 = 33.2%）；ratio 仅主营
    标签维填充、其余维为 0 占位。数据来自定期报告分部披露的平台清洗归一（clean
    口径，默认）；各维披露覆盖度先用 coverage() 探明。

    :param source: "clean"（默认，清洗归一）或 "raw"（披露明细）
    """

    def products(self, symbol: str, source: str = "clean", limit: int = 20,
                 _df: bool = False) -> Any:
        """分产品/商品收入构成（行按收入降序）。"""
        return self._c.call("segments.query_products", sym=symbol,
                            opts={"source": source, "limit": limit}, _df=_df)

    def business(self, symbol: str, source: str = "clean", limit: int = 20,
                 _df: bool = False) -> Any:
        """分业务线收入构成（行按收入降序）。"""
        return self._c.call("segments.query_business", sym=symbol,
                            opts={"source": source, "limit": limit}, _df=_df)

    def region(self, symbol: str, source: str = "clean", limit: int = 20,
               _df: bool = False) -> Any:
        """境内外分部。clean 口径返回 MAP（domestic/overseas 各含 tr/pct/margin/yoy），
        source="raw" 返回披露明细 ARR；无分部披露时为 None。"""
        return self._c.call("segments.query_region", sym=symbol,
                            opts={"source": source, "limit": limit}, _df=_df)

    def income(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """主营标签占比（name + ratio 小数；tr/cost 恒 0，margin 为 None）。"""
        return self._c.call("segments.query_income", sym=symbol,
                            opts={"limit": limit}, _df=_df)

    def snapshot(self, symbol: str, source: str = "clean", _df: bool = False) -> Any:
        """四维合并快照：{overview, income, region, product, business, coverage}。"""
        return self._c.call("segments.snapshot", sym=symbol,
                            opts={"source": source}, _df=_df)

    def coverage(self, symbol: str) -> Any:
        """各维是否有数据（has_income/has_region/has_products/has_business 布尔）。"""
        return self._c.call("segments.coverage", sym=symbol)

    def periods(self, symbol: str) -> Any:
        """清洗口径可用报告期（{clean_last, clean_last_q4}）。"""
        return self._c.call("segments.list_sas", sym=symbol)


class ValuationApi(_Api):
    """估值历史统计（与平台 web「估值通道」取数同源，宿主函数 HIST_STATS）。

    返回窗口内每日估值序列与统计量：``{avg, current, median, min, max, pct,
    count, series}``——pct 为当前值的历史分位（小数，0.42 = 42% 分位）；
    series 为 ``[[unix 秒, 值], ...]`` 升序；引擎不返回 stddev，需要通道带宽时
    由调用方按总体口径（÷N）自算。
    口径注记：亏损期 PE 无数据、净资产为负期间不参与统计（与平台免责一致）。
    """

    _METRICS = {"pe": "pe", "pb": "pb", "ps": "ps", "pr": "pr_base"}
    # 引擎支持 <数字><单位> 通用窗口（实测 6m 起可用）；上限 3 年
    _WINDOWS = ("6m", "1y", "2y", "3y")

    def hist_stats(self, symbol: str, metric: str = "pe", window: str = "3y") -> dict:
        """估值指标的历史统计与每日序列（PE=TTM 口径；pr=市赚率 pr_base）。

        :param metric: "pe" / "pb" / "ps" / "pr"
        :param window: "6m" / "1y" / "2y" / "3y"（上限 3 年）
        """
        if metric not in self._METRICS:
            raise UsageError(
                f"metric 只支持 {sorted(self._METRICS)}（pe=市盈率TTM、pb=市净率、"
                "ps=市销率、pr=市赚率；金融/亏损股建议用 pb）", code="params")
        if window not in self._WINDOWS:
            raise UsageError(
                f"window 只支持 {list(self._WINDOWS)}（上限 3 年）", code="params")
        return self._c.eval_result(
            f'return HIST_STATS("{window}", "{self._METRICS[metric]}")', symbol=symbol)


class EstimatesApi(_Api):
    """盈利预测与研报（卖方研究数据）。

    机构盈利预测逐年 EPS/PE（year_mark A=实际 E=预测，YEAR1..YEAR4 为预测年份
    序列）、预测明细（机构/研究员/归母净利/评级）、评级统计（综合评级与买卖
    家数按窗口）、个股研报列表（标题/机构/作者/行业/链接；研报正文不在接口
    范围）。EPS=元/股、金额=元、PE=倍。
    """

    def query_forecast(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """机构盈利预测（逐年 EPS/PE，A=实际 E=预测）。

        :param limit: 条数，默认 8
        """
        return self._c.call("estimates.query_forecast", sym=symbol, limit=limit, _df=_df)

    def query_forecast_detail(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """盈利预测明细（机构/研究员/归母净利/评级）。

        :param limit: 条数，默认 8
        """
        return self._c.call("estimates.query_forecast_detail", sym=symbol,
                            limit=limit, _df=_df)

    def query_rating(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """评级统计（综合评级与买卖家数按窗口）。

        :param limit: 条数，默认 8
        """
        return self._c.call("estimates.query_rating", sym=symbol, limit=limit, _df=_df)

    def query_reports(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """个股研报列表（标题/机构/作者/行业/报告链接）。

        :param limit: 条数，默认 8
        """
        return self._c.call("estimates.query_reports", sym=symbol, limit=limit, _df=_df)


class IndicatorApi(_Api):
    """平台指标（按指标代码寻址）。

    单位统一为基础单位：比率类为小数（ROE 0.332 = 33.2%）、金额/市值为元、
    分位为小数（0.42 = 42% 分位）；精选组声明过 range 的指标在返回前做量级守护
    （违例抛 DataError）。非精选代码按脚本原值返回（目录未声明单位的代码不做换算）。

    美股标的按随包代码表归一，``AAPL.O``/``BRK.B`` 与裸码 ``AAPL``/``BRK_B`` 等价
    （见 ``normalize_symbol``）；上游仍报 ``symbol`` 未绑定时翻译成带代码写法指引的
    DataError，而不是把引擎返回的 0 静默放行。

    期货指标码（``$FUT_*``）用 ``fut_symbol`` 指定合约键：国内带市场前缀
    （``cn.SR.ZCE`` 郑商所、``cn.RB.SHF`` 上期所；后缀不是 .CZCE），外盘用
    ``global.CL`` 等 V2 键；``symbol`` 传任意 A 股代码（绑定期期间上下文），
    缺省合约 ``cn.SR.ZCE``。eval 引擎须为 cn 客户端。
    """

    def get(self, symbol: str, code: str, fut_symbol: str | None = None) -> Any:
        """取单个指标当前值，如 cli.indicator.get("600519", "$PE_TTM_LAST")。

        期货码传 fut_symbol（如 "global.CL"），symbol 传任意 A 股代码。
        """
        meta = self._c.catalog.metric_meta(code)
        if meta is None and self._c.catalog.metric(code) is None:
            raise CatalogError(f"未知指标 {code!r}（防编造：code 必须在指标目录内）",
                               code="metric")
        value = self._eval_metric(f"return {code}", symbol=symbol, label=code,
                                  fut_symbol=fut_symbol)
        return finish_metric(value, meta, code=code, validate=self._c._validate)

    def metrics(self, symbol: str, codes: list[str],
                fut_symbol: str | None = None) -> dict:
        """批量取多个指标当前值，返回 {code: value}（精选代码带换算与量级守护）。

        期货码传 fut_symbol（如 "cn.SR.ZCE"），symbol 传任意 A 股代码。
        """
        missing = [c for c in codes if self._c.catalog.metric(c) is None]
        if missing:
            raise CatalogError(f"未知指标 {missing}（防编造：code 必须在指标目录内）",
                               code="metric")
        body = ", ".join(f'"{c}": {c}' for c in codes)
        values = self._eval_metric(f"return {{{body}}}", symbol=symbol,
                                   label=", ".join(codes),
                                   fut_symbol=fut_symbol) or {}
        if not isinstance(values, dict):  # 上游恒返回 MAP；异常形态原样透传
            return values
        return {c: finish_metric(v, self._c.catalog.metric_meta(c), code=c,
                                 validate=self._c._validate)
                for c, v in values.items()}

    def _eval_metric(self, xs: str, *, symbol: str, label: str,
                     fut_symbol: str | None = None) -> Any:
        """执行指标求值；把「标的没被识别成公司代码」的上游错误翻译成可执行的提示。"""
        try:
            return self._c.eval_result(xs, symbol=symbol,
                                       args=({"fut.symbol": fut_symbol}
                                             if fut_symbol else None))
        except ServerError as e:
            if 'undefined variable "symbol"' in str(e):
                mk = str(self._c.market or "cn").lower()
                hint = ("美股代码用裸代码（AAPL / BRK_B）：带交易所后缀（AAPL.O / BRK.N）"
                        "会被上游当成宏观序列，指标脚本里的 symbol 变量未绑定。"
                        if mk == "us" else
                        f"请确认代码与 market={mk!r} 匹配（代码表：cat.symbols_search）。")
                raise DataError(
                    f"指标 {label} 在当前市场（{mk}）求值失败：上游没有把标的绑定成公司"
                    f"代码（symbol 变量未设置）。{hint} 原始错误：{e}", code="symbol") from e
            raise


# ---------------------------------------------------------------- 披露 disclosure
class NoticeApi(_Api):
    """公告检索与信号。window 枚举 "7d"/"1m"/"3m"/"6m"/"1y"/"3y"/"5y" 或天数整数；keyword 为标题/类型正则（可空）。"""

    def list(self, symbol: str, window: str = "3m", keyword: str = "",
             limit: int = 20, _raw: bool = False, _df: bool = False) -> Any:
        """单票公告列表（date/title/type/url/pdf_url）。"""
        days = _window_days(window)
        return self._c.call("notice.query_by_symbol", sym=symbol, window=str(days),
                            type_regex=keyword, limit=limit, _raw=_raw, _df=_df)

    def recent(self, window: str = "7d", keyword: str = "", limit: int = 50,
               _raw: bool = False, _df: bool = False) -> Any:
        """全市场近期公告（按披露时间倒序）。

        :param window: 时间窗口，如 "7d"/"1m" 或天数
        :param keyword: 标题/类型正则（可空）
        """
        days = _window_days(window)
        return self._c.call("notice.query_recent", window=str(days), type_regex=keyword,
                            limit=limit, _raw=_raw, _df=_df)

    def by_category(self, category: str, window: str = "1m", limit: int = 20,
                    _raw: bool = False, _df: bool = False) -> Any:
        """按类别查公告（如 "回购"）。"""
        days = _window_days(window)
        return self._c.call("notice.query_by_category", category=category,
                            window=str(days), limit=limit, _raw=_raw, _df=_df)

    def find(self, symbol: str, begin: str, end: str, keyword: str = "",
             limit: int = 50, _raw: bool = False, _df: bool = False) -> Any:
        """按日期区间查单票公告（begin/end 均含当日，格式 YYYY-MM-DD）。

        :param begin: 起始日期（含）
        :param end: 结束日期（含）
        :param keyword: 标题/类型正则（可空）
        """
        return self._c.call("notice.query_find", from_date=begin, to_date=end,
                            type_regex=keyword, stock_code=symbol, limit=limit,
                            _raw=_raw, _df=_df)

    def on_date(self, date: str, keyword: str = "", limit: int = 50,
                _raw: bool = False, _df: bool = False) -> Any:
        """指定日期的全市场公告（date 格式 YYYY-MM-DD）。"""
        return self._c.call("notice.query_on_date", date=date, type_regex=keyword,
                            limit=limit, _raw=_raw, _df=_df)

    def has_buyback(self, symbol: str, window: str = "6m") -> bool:
        """窗口内是否有回购公告。"""
        return bool(self._c.call("notice.signal_has_buyback", sym=symbol,
                                 window=str(_window_days(window))))

    def has_reduction(self, symbol: str, window: str = "6m") -> bool:
        """窗口内是否有减持公告。"""
        return bool(self._c.call("notice.signal_has_reduction", sym=symbol,
                                 window=str(_window_days(window))))


class FilingsApi(_Api):
    """定期报告清单。kind = all | annual | semi | quarter。"""

    def list(self, symbol: str, kind: str = "all", limit: int = 10,
             _df: bool = False) -> Any:
        """定期报告列表（报告期/标题/PDF 链接）。"""
        return self._c.call("filings.query", sym=symbol, type_key=kind, limit=limit, _df=_df)

    def latest(self, symbol: str, kind: str = "all") -> Any:
        """最新一条定期报告。"""
        return self._c.call("filings.latest", sym=symbol, type_key=kind)


class ForecastApi(_Api):
    """业绩预告 / 快报 / 披露日历（正式报表发布前的披露文件结构化）。"""

    def yjyg(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """业绩预告历史（净利/扣非/营收区间 + 同比 + 修正轨迹）。"""
        return self._c.call("forecast.yjyg_rows", sym=symbol, limit=limit, _df=_df)

    def yjyg_latest(self, symbol: str) -> Any:
        """最新业绩预告。"""
        return self._c.call("forecast.yjyg_latest", sym=symbol)

    def yjkb(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """业绩快报历史。"""
        return self._c.call("forecast.yjkb_rows", sym=symbol, limit=limit, _df=_df)

    def yjkb_latest(self, symbol: str) -> Any:
        """最新业绩快报。"""
        return self._c.call("forecast.yjkb_latest", sym=symbol)

    def disclosure_history(self, symbol: str, limit: int = 8, _df: bool = False) -> Any:
        """历史财报预约披露（报告期/计划披露日/实际日）。"""
        return self._c.call("forecast.disclosure_rows", sym=symbol, limit=limit, _df=_df)

    def next_disclosure(self, symbol: str) -> Any:
        """下次财报预约披露。"""
        return self._c.call("forecast.disclosure_next", sym=symbol)


class WorkoutApi(_Api):
    """契约套利条款事件（要约收购/换股吸收合并/现金选择权等，披露原文提取）。

    ``board()`` 返回 {as_of, deals, quotes} 进行中看板；``query()`` 返回单票
    规范化条款行。价格为披露口径（公告对价/现价，元）；现价 < 公告对价的折价
    窗口由调用方自行判定，SDK 不内置收益测算（算法放工具仓）。同业数据商暂无
    对应接口，属平台独有面。
    """

    def board(self) -> Any:
        """进行中契约套利看板（{as_of, deals, quotes}）。"""
        return self._c.call("workout.board")

    def query(self, symbol: str, _df: bool = False) -> Any:
        """单票契约套利条款（规范化条款行）。"""
        return self._c.call("workout.query", sym=symbol, _df=_df)


class DividendApi(_Api):
    """分红。DPS 单位=元/股；股息率/派息率为小数（0.0396 = 3.96%）。

    除下方动宾化方法外，目录内全部 ``bonus.*`` 函数（含质量筛选器
    ``screen_quality`` / ``screen_high_yield`` / ``screen_undervalued_yield``…）
    经属性直达，如 ``cli.dividend.screen_quality("600519")``。
    """

    # 常用筛选器提为显式方法（docstring 在 IDE 可见；底层合同与目录一致）
    def screen_quality(self, symbol: str, min_yield: float | None = None,
                       payout_min: float | None = None,
                       payout_max: float | None = None, _raw: bool = False,
                       _df: bool = False) -> Any:
        """分红质量优（高股息 + 派息可持续，阈值可调）。

        :param min_yield: 最低股息率（小数，如 0.03 = 3%）
        :param payout_min: 派息率下限（小数）
        :param payout_max: 派息率上限（小数）
        """
        kw: dict[str, Any] = {"sym": symbol}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if payout_min is not None:
            kw["payout_min"] = payout_min
        if payout_max is not None:
            kw["payout_max"] = payout_max
        return self._c.call("bonus.screen_quality", **kw, _raw=_raw, _df=_df)

    def screen_high_yield(self, symbol: str, min_yield: float | None = None,
                          _raw: bool = False, _df: bool = False) -> Any:
        """高股息（min_yield 为小数，如 0.04 = 4%）。"""
        kw: dict[str, Any] = {"sym": symbol}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return self._c.call("bonus.screen_high_yield", **kw, _raw=_raw, _df=_df)

    def screen_undervalued_yield(self, symbol: str, min_yield: float | None = None,
                                 min_pct: float | None = None, _raw: bool = False,
                                 _df: bool = False) -> Any:
        """低估 + 高股息（min_yield 为小数；min_pct 为低估值百分位门槛）。"""
        kw: dict[str, Any] = {"sym": symbol}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if min_pct is not None:
            kw["min_pct"] = min_pct
        return self._c.call("bonus.screen_undervalued_yield", **kw, _raw=_raw, _df=_df)

    def history(self, symbol: str, limit: int | None = None,
                begin: str | None = None, end: str | None = None,
                _raw: bool = False, _df: bool = False) -> Any:
        """分红历史明细（announce/ex_date/pay/dps/total/content/sas/payout_ratio）。

        :param limit: 条数，默认 20；区间查询时默认取 max_limit（上限 10000）
        :param begin: 起始日期（含，YYYY-MM-DD，按除权日），须与 end 同时提供；上限 5 年
        :param end: 结束日期（含）
        """
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            if _raw:
                raise UsageError("_raw=True 时不支持 begin/end（原始行无扁平日期字段）",
                                 code="range")
            fetch = min(int(limit) if limit is not None else (self._c.max_limit or 10000),
                        10000)
            rows = self._c.call("bonus.query_list", sym=symbol, limit=fetch)
            out = _per_symbol(rows, lambda r: _filter_by_date(r, begin, end, "ex_div", fetch))
            return _finish_df(out, _df)
        limit = 20 if limit is None else limit
        return self._c.call("bonus.query_list", sym=symbol, limit=limit,
                            _raw=_raw, _df=_df)

    def last(self, symbol: str, _raw: bool = False) -> Any:
        """最近一次分红（announce/ex_date/pay/dps/total/content/sas/payout_ratio），无数据返回 None。

        复用规范化历史序列取最新一行，字段与 ``history(limit=1)[0]`` 一致；
        ``_raw=True`` 时返回上游原始行。
        """
        rows = self._c.call("bonus.query_list", sym=symbol, limit=1, _raw=_raw)
        return _per_symbol(rows, lambda r: r[0] if r else None)

    def dps(self, symbol: str) -> Any:
        """财报期每股分红（元/股）。"""
        return self._c.call("bonus.dps_rpt", sym=symbol)

    def window_stats(self, symbol: str, window: str = "3y") -> dict:
        """窗口统计（单次请求）：{"dps": 每股股利合计(元/股), "total": 总分红(元), "count": 次数}。

        窗口按**除权日**计、截至今天；命名窗口仅支持 7d/1m/3m/6m/1y/3y/5y（最大 5 年）
        或正整数天数。count 由 SDK 从规范化历史行统计——上游 count 聚合存在缺陷
        （同窗口 sum 正常、count 恒 0），故不经上游 count。

        :param window: 窗口字符串，如 "3y"/"5y"
        """
        days = _window_days(window)
        limit = min(self._c.max_limit or 10000, 10000)
        s = json.dumps(symbol, ensure_ascii=False)
        w = json.dumps(str(window), ensure_ascii=False)
        xs = (f"__r := bonus.query_list({s}, {limit})\n"
              f"__rows := bonus.fmt_maps(__r)\n"
              f'return {{"rows": __rows, '
              f'"dps": bonus.query_dps_window({s}, {w}), '
              f'"total": bonus.query_total_window({s}, {w})}}')
        res = self._c.eval_result(xs, symbol=symbol) or {}
        if not isinstance(res, dict):
            raise CatalogError(
                f"window_stats: 返回不是 MAP（{type(res).__name__}）", code="shape")
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        rows = res.pop("rows", []) or []
        count = sum(1 for r in rows if isinstance(r, dict)
                    and str(r.get("ex_div") or r.get("ex_date") or "")[:10] >= cutoff)
        return {"dps": res.get("dps"), "total": res.get("total"), "count": count}

    def yield_ttm(self, symbol: str) -> Any:
        """TTM 股息率（小数，0.0396 = 3.96%；= TTM 分红总额 / 最新市值）。"""
        return self._c.call("bonus.snapshot_yield_ttm", sym=symbol)

    def payout_ttm(self, symbol: str) -> Any:
        """TTM 派息率（小数，0.799 = 79.9%；= TTM 分红 / 归母净利 TTM）。"""
        return self._c.call("bonus.snapshot_payout_ttm", sym=symbol)


# ---------------------------------------------------------------- 参考 reference
class InfoApi(_Api):
    """公司档案与参考信息。"""

    _PROFILE_CODES = ["$NAME", "$INDUSTRY_CUR", "$STYLE_INDUSTRY",
                      "$ORG_ORGTYPE", "$ORG_LISTINGDATE"]
    _PROFILE_KEYS = ["name", "industry", "style_industry", "org_type", "listing_date"]

    def profile(self, symbol: str) -> dict:
        """公司档案摘要（名称/行业/组织类型/上市日期）。"""
        body = ", ".join(f'"{k}": {c}' for k, c in
                         zip(self._PROFILE_KEYS, self._PROFILE_CODES))
        return self._c.eval_result(f"return {{{body}}}", symbol=symbol) or {}


class EquityApi(_Api):
    """股东治理与股本——十大股东/质押/解禁/机构/高管/回购/重组/担保/诉讼。

    披露原值直采；比例字段（*_ratio/*_tsr/hold_ratio 等）由百分数口径换算为
    **小数**（0.0522 = 5.22%，换算字段清单见目录 units 声明）；持股数=股、
    金额=元。市场级质押三件套（pledge_market/industry/org）不传标的；
    ``*_at`` 变体按报告期取数（annual 如 2024、sampling 如 "Q4"）。
    目录内全部 ``equity.*`` 函数（含 fmt_* 规范化工具）经属性直达。
    """

    # ---- 股东 ----
    def query_holder10(self, symbol: str, _df: bool = False) -> Any:
        """最新一期十大股东（holder_name/hold_num/hold_num_ratio）。"""
        return self._c.call("equity.query_holder10", sym=symbol, _df=_df)

    def query_holdernum(self, symbol: str) -> Any:
        """最新股东户数（end_date/hold_focus/avg_hold_amt 单行）。"""
        return self._c.call("equity.query_holdernum", sym=symbol)

    # ---- 质押 ----
    def query_pledge_detail(self, symbol: str, limit: int = 20,
                            _df: bool = False) -> Any:
        """主要股东质押明细（质押家数/数量/比例/状态）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_pledge_detail", sym=symbol,
                            limit=limit, _df=_df)

    def query_pledge_summary(self, symbol: str, limit: int = 20,
                             _df: bool = False) -> Any:
        """公司质押比例时序（trade_date/pledge_ratio/质押股数/质押市值）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_pledge_summary", sym=symbol,
                            limit=limit, _df=_df)

    def query_pledge_market(self, limit: int = 20, _df: bool = False) -> Any:
        """市场整体质押（全市场两融式时序，不传标的）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_pledge_market", limit=limit, _df=_df)

    def query_pledge_industry(self, limit: int = 20, _df: bool = False) -> Any:
        """行业质押比例（全市场按行业，不传标的）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_pledge_industry", limit=limit, _df=_df)

    def query_pledge_org(self, limit: int = 20, _df: bool = False) -> Any:
        """质押机构分布（质权人类型维度，不传标的）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_pledge_org", limit=limit, _df=_df)

    # ---- 机构 ----
    def query_institution_detail(self, symbol: str, limit: int = 20,
                                 _df: bool = False) -> Any:
        """机构持股明细（机构 × 报告期持股数/市值/占比）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_institution_detail", sym=symbol,
                            limit=limit, _df=_df)

    def query_institution_summary(self, symbol: str, limit: int = 20,
                                  _df: bool = False) -> Any:
        """机构持仓占比时序（机构家数/合计占比/环比变动）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_institution_summary", sym=symbol,
                            limit=limit, _df=_df)

    def query_hgt(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """沪港通持股（机构/持股数/市值/占比变动）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_hgt", sym=symbol, limit=limit, _df=_df)

    def query_national_team(self, symbol: str, limit: int = 20,
                            _df: bool = False) -> Any:
        """国家队持股（证券主体 × 报告期持股占比）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_national_team", sym=symbol,
                            limit=limit, _df=_df)

    # ---- 治理事件 ----
    def query_release(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """限售解禁日程（解禁日期/数量/占比/类型）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_release", sym=symbol, limit=limit, _df=_df)

    def query_buyback_plan(self, symbol: str, limit: int = 20,
                           _df: bool = False) -> Any:
        """回购方案全览（进度/价格上限/金额上限/起始日）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_buyback_plan", sym=symbol,
                            limit=limit, _df=_df)

    def query_buyback_detail(self, symbol: str) -> Any:
        """回购执行明细单行（已回购股数/金额/公告日）。"""
        return self._c.call("equity.query_buyback_detail", sym=symbol)

    def query_reorg(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """并购重组（进度/交易金额/公告日）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_reorg", sym=symbol, limit=limit, _df=_df)

    def query_related_trade(self, symbol: str, limit: int = 20,
                            _df: bool = False) -> Any:
        """关联交易（关联方/交易金额/公告日）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_related_trade", sym=symbol,
                            limit=limit, _df=_df)

    def query_concert(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """一致行动人（组合名称/合计持股比例）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_concert", sym=symbol, limit=limit, _df=_df)

    def query_guarantee(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """对外担保（担保方/金额/是否履行完毕）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_guarantee", sym=symbol, limit=limit, _df=_df)

    def query_litigation(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """诉讼记录（案名/涉案金额/原告/被告）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_litigation", sym=symbol, limit=limit, _df=_df)

    def query_violation(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """违规处罚（类型/处分/罚款金额）。

        :param limit: 条数，默认 20
        """
        return self._c.call("equity.query_violation", sym=symbol, limit=limit, _df=_df)

    # ---- 高管与股本 ----
    def query_executives(self, symbol: str, _df: bool = False) -> Any:
        """高管名册（姓名/职务/薪酬/持股）。"""
        return self._c.call("equity.query_executives", sym=symbol, _df=_df)

    def query_exec_change(self, symbol: str) -> Any:
        """高管增减持最新一行（日期/高管/变动股数/均价）。"""
        return self._c.call("equity.query_exec_change", sym=symbol)

    def query_exec_change_at(self, symbol: str, annual: int, sampling: str) -> Any:
        """指定报告期的高管增减持单行。

        :param annual: 年报年度（如 2024）
        :param sampling: 报告期采样（如 "Q4"）
        """
        return self._c.call("equity.query_exec_change_at", sym=symbol,
                            annual=annual, sampling=sampling)

    def query_capital_change(self, symbol: str) -> Any:
        """股本结构最新一行（总股本/流通股本）。"""
        return self._c.call("equity.query_capital_change", sym=symbol)

    def query_capital_change_at(self, symbol: str, annual: int, sampling: str) -> Any:
        """指定报告期的股本结构单行。

        :param annual: 年报年度（如 2024）
        :param sampling: 报告期采样（如 "Q4"）
        """
        return self._c.call("equity.query_capital_change_at", sym=symbol,
                            annual=annual, sampling=sampling)


class IntlApi(_Api):
    """港美股披露——CCASS 持仓/主要股东/机构评级/盈利预测/沽空/美股发行。

    需用对应市场的客户端调用（``Client(market="hk")`` / ``Client(market="us")``）：
    网关按标的注册市场校验，cn 客户端调港美股代码会被拒（400 market mismatch）。
    函数内部再按标的代码路由到港美数据族；A 股标的调用多返回空。占比字段已由
    百分数换算为**小数**；价格为披露币种原值（不做汇率换算）；港股盈利预测行
    保留披露原文中文键。
    """

    def query_ccass(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """港股 CCASS 经纪持仓（经纪商/持股数/占发行股比）。

        :param limit: 条数，默认 20
        """
        return self._c.call("intl.query_ccass", sym=symbol, limit=limit, _df=_df)

    def query_shareholders(self, symbol: str, limit: int = 20,
                           _df: bool = False) -> Any:
        """港股主要股东/董事权益（股东/持股数/占总股比）。

        :param limit: 条数，默认 20
        """
        return self._c.call("intl.query_shareholders", sym=symbol, limit=limit, _df=_df)

    def query_org_rating(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """港股机构评级（机构/评级/目标价，披露币种）。

        :param limit: 条数，默认 20
        """
        return self._c.call("intl.query_org_rating", sym=symbol, limit=limit, _df=_df)

    def query_profit_forecast(self, symbol: str, limit: int = 20,
                              _df: bool = False) -> Any:
        """港股盈利预测（披露原文中文键：财政年度/纯利/每股盈利等）。

        :param limit: 条数，默认 20
        """
        return self._c.call("intl.query_profit_forecast", sym=symbol,
                            limit=limit, _df=_df)

    def query_sellshort(self, symbol: str, limit: int = 20, _df: bool = False) -> Any:
        """港美沽空（沽空量/占比，shares=股）。

        :param limit: 条数，默认 20
        """
        return self._c.call("intl.query_sellshort", sym=symbol, limit=limit, _df=_df)

    def issue_info(self, symbol: str) -> Any:
        """美股发行信息快照（发行价/数量/日期，以披露源为准）。"""
        return self._c.call("intl.issue_info", sym=symbol)


class MacroApi(_Api):
    """宏观与行业时序。

    覆盖宏观指标时序/as-of/采样频率、中债收益率、行业情报单值。宏观数值为
    上游原生口径（非全库小数比率口径）：$CPI 等价格指数=点（上年同期=100）、
    $GDP/$M2 等流量存量=元；bond_curve 收益率为小数（0.0168 = 1.68%）。
    指标码层等价物：``cli.indicator.get(sym, "$CPI")`` 与 ``asof`` 同源
    （指标码层走单位换算管线）。时序最新在前。
    """

    def query(self, code: str, n: int = 6) -> Any:
        """宏观指标时序：{frequency, periods, latest, series[{sas, annual, sampling, value}]}。

        :param code: 指标码或名称（``$CPI`` / ``cpi`` 均可，服务端归一）
        :param n: 期数（1–48）
        """
        return self._c.call("macro.query", code=code, n=n)

    def asof(self, code: str) -> Any:
        """宏观指标最新一期原生值（无数据返回 None；人口类序列勿用）。"""
        return self._c.call("macro.asof", code=code)

    def spots(self, code: str, n: int = 4) -> Any:
        """宏观指标原生采样期点（降序，如 ["2026:M09", "2026:M08"]）。"""
        return self._c.call("macro.spots", code=code, n=n)

    def sampling_of(self, code: str) -> Any:
        """宏观指标原生采样频率："month"/"quarter"/"year"/"day"。"""
        return self._c.call("macro.sampling_of", code=code)

    def bond_curve(self, curve_name: str, tenor: str) -> Any:
        """中债收益率按曲线名+期限取最新值（小数口径，0.0168 = 1.68%）。

        :param curve_name: 曲线披露名（如「中债国债收益率曲线」）
        :param tenor: 期限列名（如「10年」「1年」）
        """
        return self._c.call("macro.bond_curve", curve_name=curve_name, tenor=tenor)

    def nev_monthly(self, brand: str, field: str) -> Any:
        """新势力月交付按品牌取值（field=sales/rank；掉榜返回 None）。"""
        return self._c.call("macro.nev_monthly", brand=brand, field=field)

    def nev_weekly(self, brand: str, field: str) -> Any:
        """新势力周销量按品牌取值（field=sales/rank；当期无行返回 None）。"""
        return self._c.call("macro.nev_weekly", brand=brand, field=field)

    def avc_monthly(self, category: str, field: str) -> Any:
        """奥维家电品类月度取值（field=volume/volume_yoy/value/value_yoy）。

        品类名须与披露名单精确匹配，名单不含/掉榜返回 None。
        """
        return self._c.call("macro.avc_monthly", category=category, field=field)

    def chinaiol_monthly(self, category: str, field: str) -> Any:
        """家电产销月度取值（field=volume=内销量/volume_yoy/value=内销额/value_yoy）。

        品类名须与披露名单精确匹配，名单不含/掉榜返回 None。
        """
        return self._c.call("macro.chinaiol_monthly", category=category, field=field)

    def cpca_top(self, manufacturer: str, field: str) -> Any:
        """乘联会厂商排行取值（如 field=wholesale；掉榜返回 None）。"""
        return self._c.call("macro.cpca_top", manufacturer=manufacturer, field=field)

    def phone_share(self, brand: str, field: str = "share") -> Any:
        """手机品牌周份额取值（field=share/rank，披露原值；掉榜返回 None）。"""
        return self._c.call("macro.phone_share", brand=brand, field=field)


# 组合接口：跨多个目录函数的研究级封装（取数 → 规则 → 事实包 → 成稿/出图）。
# 不登记 FRIENDLY_INDEX（那张表是「核心接口 ↔ 底层目录函数」的一一映射）；
# 文档在 docs/API.md 的「组合接口」小节单独成文。
COMPOSITE_METHODS: dict[str, set[str]] = {
    "cbond": {"daily", "article", "figures"},
}

FRIENDLY_NAMESPACES: dict[str, type[_Api]] = {
    "kline": KlineApi,
    "screener": ScreenerApi,
    "moneyflow": MoneyflowApi,
    "margin": MarginApi,
    "cbond": CbondApi,
    "index": IndexApi,
    "stocks": StocksApi,
    "statements": StatementsApi,
    "segments": SegmentsApi,
    "valuation": ValuationApi,
    "estimates": EstimatesApi,
    "indicator": IndicatorApi,
    "notice": NoticeApi,
    "filings": FilingsApi,
    "forecast": ForecastApi,
    "workout": WorkoutApi,
    "dividend": DividendApi,
    "info": InfoApi,
    "equity": EquityApi,
    "intl": IntlApi,
    "macro": MacroApi,
}

# 文档索引用注册表：(category, namespace, method, cn, 底层函数)
FRIENDLY_INDEX: list[tuple[str, str, str, str, str]] = [
    ("market", "kline", "bars", "日 K 序列", "kline.query_bars[_adj]"),
    ("market", "kline", "last", "最新一根日 K", "kline.query_bars"),
    ("market", "kline", "live", "盘中最新快照", "kline.query_last_live"),
    ("market", "kline", "batch_live", "多标的盘中快照", "kline.query_last_live_many"),
    ("market", "kline", "min1", "当日 1 分钟分时", "kline.query_min1_live"),
    ("market", "kline", "snapshot", "行情摘要", "kline.snapshot"),
    ("market", "kline", "is_etf", "是否场内 ETF", "kline.is_etf"),
    ("market", "moneyflow", "bars", "资金流历史", "moneyflow.query_bars"),
    ("market", "moneyflow", "last", "最新资金流", "moneyflow.query_bars"),
    ("market", "moneyflow", "board", "全市场资金流快照", "moneyflow.board"),
    ("market", "moneyflow", "live", "资金流当日读数", "moneyflow.query_last_live"),
    ("market", "screener", "screen_limit_up", "今日涨停筛选", "kline.screen_limit_up"),
    ("market", "screener", "screen_limit_down", "今日跌停筛选", "kline.screen_limit_down"),
    ("market", "screener", "screen_above_ma20", "站上 MA20 筛选", "kline.screen_above_ma20"),
    ("market", "screener", "screen_ma60_up", "MA60 上行筛选", "kline.screen_ma60_up"),
    ("market", "screener", "screen_breakout_ma20", "突破 MA20 筛选", "kline.screen_breakout_ma20"),
    ("market", "screener", "screen_momentum_20d", "20 日动量筛选", "kline.screen_momentum_20d"),
    ("market", "screener", "screen_pullback_20d", "20 日回撤筛选", "kline.screen_pullback_20d"),
    ("market", "screener", "screen_volume_spike", "放量筛选", "kline.screen_volume_spike"),
    ("market", "screener", "index_breadth_summary", "全市场涨跌全景",
     "kline.index_breadth_summary"),
    ("market", "screener", "index_breadth_bins", "涨跌幅分桶", "kline.index_breadth_bins"),
    ("market", "screener", "index_breadth_bin_industries", "分桶行业分布",
     "kline.index_breadth_bin_industries"),
    ("market", "screener", "index_top_movers", "涨跌榜", "kline.index_top_movers"),
    ("market", "margin", "query", "个股融资融券历史", "margin.query"),
    ("market", "margin", "latest", "最新两融单行", "margin.latest"),
    ("market", "cbond", "board", "转债全市场面板", "cbond.board"),
    ("market", "cbond", "latest_quotes", "转债最新快照", "cbond.latest_quotes"),
    ("market", "cbond", "of_stock", "正股关联转债", "cbond.of_stock"),
    ("market", "cbond", "query", "按标的查条款事件", "cbond.query"),
    ("market", "cbond", "call_hits", "强赎触发计数", "cbond.call_hits"),
    ("market", "cbond", "kline_window", "转债日K窗口", "cbond.kline_window"),
    ("market", "cbond", "universe_codes", "转债代码全集", "cbond.universe_codes"),
    ("market", "index", "keys", "指数键列表", "indices.keys"),
    ("market", "index", "members", "指数成分", "indices.members"),
    ("market", "index", "weights", "指数权重股", "indices.weights"),
    ("market", "index", "valuation", "指数估值时序", "indices.valuation"),
    ("market", "index", "trend", "指数估值趋势(周频)", "indices.trend"),
    ("market", "index", "universe_keys", "指数域可用键", "indices.universe_keys"),
    ("market", "stocks", "list", "全市场证券列表", "stocks.query_list"),
    ("market", "stocks", "industries", "行业目录", "stocks.industry_list"),
    ("market", "stocks", "industry_members", "行业成分股", "stocks.industry_members"),
    ("fundamentals", "statements", "balance", "资产负债表", "rptdom.statement"),
    ("fundamentals", "statements", "income", "利润表", "rptdom.statement"),
    ("fundamentals", "statements", "cashflow", "现金流量表", "rptdom.statement"),
    ("fundamentals", "statements", "compare", "合并 vs 母公司比较", "rptdom.statement_compare"),
    ("fundamentals", "statements", "tree", "报表目录树视图", "rptdom.statement_tree"),
    ("fundamentals", "statements", "years", "报表可用年份", "rptdom.statement_years"),
    ("fundamentals", "statements", "audit", "审计意见", "rptdom.statement_audit"),
    ("fundamentals", "indicator", "get", "取单个指标", "指标代码直查"),
    ("fundamentals", "indicator", "metrics", "批量取指标", "指标代码批量直查"),
    ("fundamentals", "segments", "products", "分产品收入构成", "segments.query_products"),
    ("fundamentals", "segments", "business", "分业务收入构成", "segments.query_business"),
    ("fundamentals", "segments", "region", "境内外分部", "segments.query_region"),
    ("fundamentals", "segments", "income", "主营标签占比", "segments.query_income"),
    ("fundamentals", "segments", "snapshot", "分部截面快照", "segments.snapshot"),
    ("fundamentals", "segments", "coverage", "分部披露覆盖度", "segments.coverage"),
    ("fundamentals", "segments", "periods", "分部可用报告期", "segments.list_sas"),
    ("fundamentals", "valuation", "hist_stats", "估值历史统计", "组合接口（宿主 HIST_STATS）"),
    ("fundamentals", "estimates", "query_forecast", "机构盈利预测", "estimates.query_forecast"),
    ("fundamentals", "estimates", "query_forecast_detail", "盈利预测明细",
     "estimates.query_forecast_detail"),
    ("fundamentals", "estimates", "query_rating", "评级统计", "estimates.query_rating"),
    ("fundamentals", "estimates", "query_reports", "个股研报", "estimates.query_reports"),
    ("disclosure", "notice", "list", "单票公告列表", "notice.query_by_symbol"),
    ("disclosure", "notice", "recent", "全市场近期公告", "notice.query_recent"),
    ("disclosure", "notice", "by_category", "按类别查公告", "notice.query_by_category"),
    ("disclosure", "notice", "find", "按日期区间查公告", "notice.query_find"),
    ("disclosure", "notice", "on_date", "指定日期全市场公告", "notice.query_on_date"),
    ("disclosure", "notice", "has_buyback", "窗口内有回购", "notice.signal_has_buyback"),
    ("disclosure", "notice", "has_reduction", "窗口内有减持", "notice.signal_has_reduction"),
    ("disclosure", "filings", "list", "定期报告列表", "filings.query"),
    ("disclosure", "filings", "latest", "最新定期报告", "filings.latest"),
    ("disclosure", "forecast", "yjyg", "业绩预告历史", "forecast.yjyg_rows"),
    ("disclosure", "forecast", "yjyg_latest", "最新业绩预告", "forecast.yjyg_latest"),
    ("disclosure", "forecast", "yjkb", "业绩快报历史", "forecast.yjkb_rows"),
    ("disclosure", "forecast", "yjkb_latest", "最新业绩快报", "forecast.yjkb_latest"),
    ("disclosure", "forecast", "disclosure_history", "历史预约披露", "forecast.disclosure_rows"),
    ("disclosure", "forecast", "next_disclosure", "下次预约披露", "forecast.disclosure_next"),
    ("disclosure", "workout", "board", "进行中契约套利看板", "workout.board"),
    ("disclosure", "workout", "query", "单票契约套利条款", "workout.query"),
    ("disclosure", "dividend", "history", "分红历史", "bonus.query_list"),
    ("disclosure", "dividend", "last", "最近一次分红", "bonus.query_list"),
    ("disclosure", "dividend", "dps", "财报期每股分红", "bonus.dps_rpt"),
    ("disclosure", "dividend", "window_stats", "窗口分红统计", "bonus.query_*_window"),
    ("disclosure", "dividend", "yield_ttm", "TTM 股息率", "bonus.snapshot_yield_ttm"),
    ("disclosure", "dividend", "payout_ttm", "TTM 派息率", "bonus.snapshot_payout_ttm"),
    ("disclosure", "dividend", "screen_quality", "分红质量优筛选", "bonus.screen_quality"),
    ("disclosure", "dividend", "screen_high_yield", "高股息筛选", "bonus.screen_high_yield"),
    ("disclosure", "dividend", "screen_undervalued_yield", "低估+高股息筛选",
     "bonus.screen_undervalued_yield"),
    ("reference", "info", "profile", "公司档案摘要", "档案指标（$NAME 等）"),
    # ---- equity：全部 query_*（fmt_* 规范化工具经属性直达）----
    ("reference", "equity", "query_holder10", "最新一期十大股东", "equity.query_holder10"),
    ("reference", "equity", "query_holdernum", "最新股东户数", "equity.query_holdernum"),
    ("reference", "equity", "query_pledge_detail", "主要股东质押明细",
     "equity.query_pledge_detail"),
    ("reference", "equity", "query_pledge_summary", "公司质押比例",
     "equity.query_pledge_summary"),
    ("reference", "equity", "query_pledge_market", "市场整体质押",
     "equity.query_pledge_market"),
    ("reference", "equity", "query_pledge_industry", "行业质押比例",
     "equity.query_pledge_industry"),
    ("reference", "equity", "query_pledge_org", "质押机构分布", "equity.query_pledge_org"),
    ("reference", "equity", "query_institution_detail", "机构持股明细",
     "equity.query_institution_detail"),
    ("reference", "equity", "query_institution_summary", "机构持仓占比",
     "equity.query_institution_summary"),
    ("reference", "equity", "query_hgt", "沪港通持股", "equity.query_hgt"),
    ("reference", "equity", "query_national_team", "国家队持股", "equity.query_national_team"),
    ("reference", "equity", "query_release", "限售解禁日程", "equity.query_release"),
    ("reference", "equity", "query_buyback_plan", "回购方案全览", "equity.query_buyback_plan"),
    ("reference", "equity", "query_buyback_detail", "回购执行明细",
     "equity.query_buyback_detail"),
    ("reference", "equity", "query_reorg", "并购重组", "equity.query_reorg"),
    ("reference", "equity", "query_related_trade", "关联交易", "equity.query_related_trade"),
    ("reference", "equity", "query_concert", "一致行动人", "equity.query_concert"),
    ("reference", "equity", "query_guarantee", "对外担保", "equity.query_guarantee"),
    ("reference", "equity", "query_litigation", "诉讼记录", "equity.query_litigation"),
    ("reference", "equity", "query_violation", "违规处罚", "equity.query_violation"),
    ("reference", "equity", "query_executives", "高管名册", "equity.query_executives"),
    ("reference", "equity", "query_exec_change", "高管增减持最新", "equity.query_exec_change"),
    ("reference", "equity", "query_exec_change_at", "指定报告期增减持",
     "equity.query_exec_change_at"),
    ("reference", "equity", "query_capital_change", "股本结构最新",
     "equity.query_capital_change"),
    ("reference", "equity", "query_capital_change_at", "指定报告期股本",
     "equity.query_capital_change_at"),
    # ---- intl：全部 query_* + issue_info ----
    ("reference", "intl", "query_ccass", "港股CCASS持仓", "intl.query_ccass"),
    ("reference", "intl", "query_shareholders", "港股主要股东", "intl.query_shareholders"),
    ("reference", "intl", "query_org_rating", "港股机构评级", "intl.query_org_rating"),
    ("reference", "intl", "query_profit_forecast", "港股盈利预测",
     "intl.query_profit_forecast"),
    ("reference", "intl", "query_sellshort", "港美沽空", "intl.query_sellshort"),
    ("reference", "intl", "issue_info", "美股发行信息", "intl.issue_info"),
    # ---- macro：宏观时序与行业情报（v1.11.0）----
    ("reference", "macro", "query", "宏观指标时序", "macro.query"),
    ("reference", "macro", "asof", "宏观最新单值", "macro.asof"),
    ("reference", "macro", "spots", "宏观原生期点", "macro.spots"),
    ("reference", "macro", "sampling_of", "宏观原生采样频率", "macro.sampling_of"),
    ("reference", "macro", "bond_curve", "中债收益率按期限", "macro.bond_curve"),
    ("reference", "macro", "nev_monthly", "新势力月交付", "macro.nev_monthly"),
    ("reference", "macro", "nev_weekly", "新势力周销量", "macro.nev_weekly"),
    ("reference", "macro", "avc_monthly", "奥维家电月度", "macro.avc_monthly"),
    ("reference", "macro", "chinaiol_monthly", "家电产销月度", "macro.chinaiol_monthly"),
    ("reference", "macro", "cpca_top", "乘联会厂商排行", "macro.cpca_top"),
    ("reference", "macro", "phone_share", "手机品牌周份额", "macro.phone_share"),
]

# 类型化门面（生成层）：目录命名空间的完整类型签名；运行时仍走 client.call()。
from wmshare.api._generated import NAMESPACES as GENERATED_NAMESPACES  # noqa: E402
