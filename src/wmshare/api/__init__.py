"""友好 API：按四大类组织的推荐入口（行情 / 财务 / 披露 / 参考）。

2.0 设计契约（标准化规范，破坏性变更集中在 2.0.0）：
  - 参数统一 ``symbol``（6 位裸码；自动归一 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀；
    港股 5 位、美股字母码）；日期一律 ``YYYY-MM-DD``；比率/涨跌幅/分位=小数、
    金额/价格/市值=元、量=股（units.yaml 台账登记码由 SDK 默认换算）；
  - 返回形态：行表/序列类默认 **pandas DataFrame**（``date`` 列 ISO、按日期
    **升序**=旧→新）；单行取数返回 dict（无数据 None）；面板/时序组合面返回
    统一信封 ``{ok, as_of, data, meta}``；单票快照 MAP 保持扁平。
    ``_raw=True`` 取上游原始行（list[dict]，跳过规范化与换算）——诊断逃生口；
  - 本层是目录合同的薄翻译：高频方法显式包装；目录内其余非内部函数经 ``__getattr__``
    属性直达（如 ``cli.kline.screen_above_ma20``）；目录标 ``internal: true`` 的
    规范化辅助（fmt_* 等）不再直达，请走 ``cli.call``——331 个底层函数零遮蔽；
  - 选股能力集中在 ``cli.screener``：单票筛选器（bool）、全市场宽度/涨跌榜与
    全市场条件选股 ``query()``（服务端索引直出）显式包装，kline 目录的其余筛选
    函数经属性直达。

使用：
    cli = wmshare.Client.from_env()
    cli.kline.bars("600519", n=30)          # -> DataFrame（date 升序）
    cli.statements.income("600519", years=5)
    cli.notice.list("600519", window="3m")  # -> DataFrame（date 升序）
"""
from __future__ import annotations

import json
import re
import warnings
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from wmshare.backtest import (
    VALUATION_RULES,
    ma_cross_signals,
    run_backtest,
    valuation_by_date,
    valuation_signals,
)
from wmshare.errors import (
    ApiError, CatalogError, DataError, LimitError, ServerError, UsageError, WmshareError)
from wmshare.units import (apply_facade_units, finish_metric, is_index_symbol,
                           ledger_convert)

# 期货门面的求值锚点（cn 默认锚）与日期归一（client.py 单一事实源）
from wmshare.client import DEFAULT_SYMBOLS as _DEFAULT_SYMBOLS  # noqa: E402
from wmshare.client import normalize_date as _normalize_date  # noqa: E402

# 服务端分桶 label 的排序前缀（如 i_涨停 / h_+5%~10%），单字母+下划线，对用户是噪音
_BIN_PREFIX = re.compile(r"^[a-z]_")

# 选股条件里的指标码（$ 开头）与 Python 式布尔词（XS 只认 && / || / !）
_METRIC_CODE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
_PY_BOOL_RE = re.compile(r"(?<![A-Za-z0-9_])(and|or|not)(?![A-Za-z0-9_])")


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


# 区间锚点切片的片数上限：100 片 × max_limit 行，覆盖任何现实区间；
# 超限仍未覆盖到 begin 属调用方配置问题（max_limit 过小），显式报错不静默截断。
_MAX_RANGE_SLICES = 100


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


def _out(result: Any, raw: bool = False, _fields: Any = None) -> Any:
    """2.0 门面返回收口：行数组默认转 DataFrame；``_raw=True`` 原样透传。

    dict（MAP/信封）、标量、None、BatchResult 容器由 ``to_output_frame``
    决定去留（容器仅把 results 里的行数组逐标的转 DF）。

    ``_fields`` 为客户端列投影（``list[str]`` 或逗号串）：在排序/过滤之后
    只保留指定字段、按请求顺序输出；未知字段抛 ``UsageError``。统一信封
    （``{ok, as_of, data, meta}``）不参与投影——那是协议字段，数据字段在
    ``data`` 内，需要字段级裁剪请用底层 ``cli.call``。
    """
    if _fields is not None:
        from wmshare.client import BatchResult, project_fields
        if isinstance(result, BatchResult):
            for key, item in list(result.results.items()):
                if isinstance(item, (dict, list)):
                    result.results[key] = project_fields(item, _fields)
        elif isinstance(result, list):
            result = project_fields(result, _fields)
        elif isinstance(result, dict) and not {"ok", "data"} <= set(result):
            result = project_fields(result, _fields)
    if raw:
        return result
    from wmshare.client import to_output_frame
    return to_output_frame(result)


def _rows(result: Any) -> Any:
    """SDK 内部取行数组的统一入口（供 backtest/cb 等内部消费方）。

    门面已默认 DataFrame，内部消费者经此还原为行数组：list 原样、
    DataFrame→records、其它形态原样透传。
    """
    if isinstance(result, list):
        return result
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        try:
            return result.to_dict("records")
        except TypeError:  # pragma: no cover - 非 records 兼容形态
            return result
    return result


def _sort_rows_by_date(rows: Any, key: str = "date") -> Any:
    """序列方向标准化（2.0）：按日期键**升序**（旧→新）稳定排序。

    上游 store 窗口/查询返回新→旧（cursor.ds 顺序），1.x 契约把它透传给用户
    是全局 footgun；2.0 起时间序列门面统一在此翻转为升序。非行数组原样。
    """
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return sorted(rows, key=lambda r: str(r.get(key) or ""))
    return rows


def _envelope(ok: bool, data: Any, as_of: str = "", **meta: Any) -> dict[str, Any]:
    """2.0 组合面统一信封：``{ok, as_of, data, meta}``。

    ok=False 时 data 恒为空 dict，失败原因进 meta（cache="miss" 等）——
    绝不静默把降级结果伪装成正常数据。
    """
    if not ok:
        return {"ok": False, "as_of": str(as_of or ""), "data": {}, "meta": meta}
    return {"ok": True, "as_of": str(as_of or ""), "data": data, "meta": meta}


def _compact_date(value: str) -> str:
    """日期入参宽容归一（2.0 全库统一接受 ISO）；返回紧凑 YYYYMMDD（文件名用）。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{8}", s):
        return s
    try:
        return date.fromisoformat(s[:10]).strftime("%Y%m%d")
    except ValueError:
        return s


def _sas_to_iso(value: Any) -> str:
    """sas 周期戳 → ISO 日期（周期起点口径：M=当月 1 日、W=ISO 周一、D=当日）。

    服务端 cursor 周期戳形如 ``2026:M10`` / ``2026:W48`` / ``2026:D326``；
    非周期戳（已 ISO 等）原样返回。
    """
    s = str(value or "").strip()
    m = re.fullmatch(r"(\d{4}):([MWD])(\d{1,3})", s)
    if not m:
        return s
    y, kind, num = int(m.group(1)), m.group(2), int(m.group(3))
    try:
        if kind == "M":
            if not 1 <= num <= 12:
                return s
            return f"{y:04d}-{num:02d}-01"
        if kind == "W":
            return date.fromisocalendar(y, num, 1).isoformat()
        return (date(y, 1, 1) + timedelta(days=num - 1)).isoformat()
    except ValueError:
        return s


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


def _kline_last_row(row: Any) -> Any:
    """把 ``kline.query_last`` 的 store 单行收口成与 ``bars()`` 一致的 9 字段。

    上游 ``kline.fmt_maps`` 只接受数组（对单个 MAP 会报 CONOF NotSupportedType），
    故单行路径在 SDK 侧按 ``sys/kline/format.xs`` 的同一字段映射收口。
    单位换算已由 ``apply_units`` 依目录声明完成（percent 百分数→小数、
    volume 手→股），此处只做字段挑选与 date/sas 派生，不重算任何数值。
    """
    if not isinstance(row, dict) or not row:
        return None
    ts = row.get("samplingTs")
    bar_date = ""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
        # 采样时间戳按北京时间零点落库，固定 +08 避免宿主时区漂移；
        # 与上游 time.date(samplingTs) 同义。
        bar_date = (date(1970, 1, 1)
                    + timedelta(seconds=float(ts) + 8 * 3600)).isoformat()
    return {
        "sas": f"{row.get('annual', '')}:{row.get('sampling', '')}",
        "date": bar_date,
        "open": float(row.get("open") or 0),
        "high": float(row.get("high") or 0),
        "low": float(row.get("low") or 0),
        "close": float(row.get("close") or 0),
        "volume": float(row.get("volume") or 0),
        "amount": float(row.get("amount") or 0),
        "percent": float(row.get("percent") or 0),
    }


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
    "calendar": "calendar",
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
            meta = None
        if meta is None:
            # 跨 ns 域函数回退：域 id 与函数 ns 可能不同（corp.equity 域含
            # buyback.snapshot，批次1 起）——在本 friendly ns 对应域（id 尾段=
            # catalog ns）的函数集内找唯一 short 名匹配。
            hits: list[str] = []
            for did, fns in (client.catalog.functions_by_domain() or {}).items():
                if did.split(".", 1)[-1] == catalog_ns:
                    hits += [fn for fn in fns if fn.split(".", 1)[1] == name]
            if len(hits) == 1:
                qualified = hits[0]
                meta = client.catalog.function(qualified)
        if meta is None:
            raise AttributeError(
                f"{type(self).__name__!s}.{name} 不存在；请查目录："
                f"cat.search({name!r}) 或 docs/API.md")
        # 2.0 命名空间净化：internal: true（fmt_* 规范化辅助）不再属性直达——
        # 这些是 SDK/文档管线的内部函数，不是用户接口；确需原始口径请走
        # ``cli.call("{qualified}")``（_raw/_units 逃生口都在）。
        if meta.get("internal"):
            raise AttributeError(
                f"{qualified} 是目录标注的内部辅助（internal: true），2.0 起不经属性直达；"
                f"确需调用请 cli.call({qualified!r}, ...)，或查 docs/API.md 附录")
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
    """行情与 K 线。单位：价格=元、量=股、涨跌幅=小数；序列按 date 升序（旧→新）。"""

    def bars(self, symbol: str, n: int | None = None, adj: str | None = None,
             begin: str | None = None, end: str | None = None,
             freq: str | None = None,
             _raw: bool = False, _fields: Any = None) -> Any:
        """K 线序列（日/周/月）→ DataFrame：date/open/high/low/close/volume/amount/percent。

        日 K 覆盖自上市首日起的全部交易日（最早 1991 年）；周/月 K 为服务端预派生
        （由日线先复权再聚合，date 为周期末交易日）。
        2.0 契约：按 ``date`` **升序**（旧→新）返回；``_raw=True`` 返回上游原始行
        （诊断逃生口，不支持 begin/end）。指数只有日频：``freq`` 非 D 显式报错
        （1.x 静默返回空序列的坑已移除）。

        :param n: 根数（按所选周期计），默认 120。区间查询：显式传 n=只取区间内
            最近 n 根（不补页）；不传 n=自动锚点切片补齐（见下），每片 ≤ max_limit
        :param adj: None=不复权；"qfq"=前复权；"hfq"=后复权
        :param begin: 起始日期（含，YYYY-MM-DD），须与 end 同时提供；区间上限 5 年
        :param end: 结束日期（含）
        :param freq: None/"D"=日 K（默认）；"W"=周 K；"M"=月 K（指数仅 D）
        :param _raw: True=上游原始行（跳过规范化/单位换算）
        :param _fields: 列投影（list/逗号串），在排序过滤后执行；不降 EC

        区间完整性（日 K，不传 n）：按「锚点切片」自动分页——每片走
        ``kline.query_at_anchor(_adj)``（窗口右端锚在已取最早一根），只物化
        ≤ end 的行、覆盖 begin 即停；任意区间一次拿到全量、不静默截断，
        计费 ≈ 区间实际根数（服务端窗口读取，不在客户端砍量）。
        周/月 K 与显式 n 为单次请求，超出单次上限显式报错（不静默截断）。
        """
        period = _kline_period_tag(freq)
        if period != "D" and is_index_symbol(str(symbol)):
            raise UsageError(
                "指数只有日频（上游不派生指数周/月 K）；周/月聚合请取日 K 后自行重采样",
                code="freq")
        period_args: dict[str, Any] = {} if period == "D" else {"period": period}
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            if _raw:
                raise UsageError("_raw=True 时不支持 begin/end（原始行无扁平日期字段）",
                                 code="range")
            begin_iso = _normalize_date(begin)
            limit = min(int(n) if n is not None else (self._c.max_limit or 10000), 10000)
            if n is None and isinstance(symbol, str) and period == "D":
                # 锚点切片（能力对标：任意区间完整返回）。不估算根数——覆盖由
                # 结构保证：每片 ≤ limit 行且右端锚在 marker，最早一根 ≤ begin
                # 或取不满一片即停；切片超限仍未覆盖才显式报错。
                fn = ("kline.query_at_anchor_adj" if adj is not None
                      else "kline.query_at_anchor")
                merged: dict[str, dict] = {}
                anchor = _normalize_date(end)
                prev_anchor: str | None = None
                for _ in range(_MAX_RANGE_SLICES):
                    anchor_kw: dict[str, Any] = {"sym": symbol, "limit": limit,
                                                 "anchor_date": anchor}
                    if adj is not None:
                        anchor_kw["adj"] = adj
                    chunk = self._c.call(fn, **anchor_kw)
                    if not isinstance(chunk, list) or not chunk:
                        break
                    dates: list[str] = []
                    for r in chunk:
                        d = str(r.get("date") or "")[:10] if isinstance(r, dict) else ""
                        if d:
                            dates.append(d)
                            merged.setdefault(d, r)
                    if not dates or len(chunk) < limit or min(dates) <= begin_iso:
                        break
                    prev_anchor, anchor = anchor, min(dates)
                    if anchor == prev_anchor:
                        # 服务端未按锚点收窄（返回原样一片）：再切只会重复烧 EC，立刻停
                        raise LimitError(
                            f"kline.bars: 锚点未前移（anchor={anchor}）——服务端未按 "
                            f"anchor_date 收窄窗口；请改传 n= 或缩小区间", code="range")
                else:
                    raise LimitError(
                        f"kline.bars: 区间 {begin}~{end} 切了 {_MAX_RANGE_SLICES} 片"
                        f"（每片 ≤{limit} 行）仍未覆盖到 begin；请调大 "
                        "Client(max_limit=...) 或缩小区间", code="range")
                rows = [merged[d] for d in sorted(merged)]
                return _out(_filter_by_date(rows, begin, end, "date", 0),
                            raw=_raw, _fields=_fields)
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
            out = _per_symbol(rows, lambda r: _sort_rows_by_date(
                _filter_by_date(r, begin, end, "date", limit)))
            return _out(out, raw=_raw, _fields=_fields)
        limit = 120 if n is None else n
        if adj is None:
            fn = "kline.query_bars_period" if period_args else "kline.query_bars"
        else:
            fn = ("kline.query_bars_period_adj" if period_args
                  else "kline.query_bars_adj")
        kwargs = {"sym": symbol, "limit": limit, "_raw": _raw}
        if adj is not None:
            kwargs["adj"] = adj
        kwargs.update(period_args)
        out = _per_symbol(self._c.call(fn, **kwargs), _sort_rows_by_date)
        return _out(out, raw=_raw, _fields=_fields)

    def last(self, symbol: str, _raw: bool = False) -> Any:
        """最新一根日 K（dict：date/open/high/low/close/volume/amount/percent），无数据返回 None。

        取 store 最新一行（``kline.query_last`` / ``store.latest``），含当日已入库的日 K；
        不受回测锚点截断——需要「锚点内最新一根」请用 ``bars(n=1)``（DataFrame 末行）。
        字段与 ``bars()`` 列一致；``_raw=True`` 时跳过规范化，返回上游原始行
        （字段名不同，含 CreatedAt/sampling 等）。
        """
        value = self._c.call("kline.query_last", sym=symbol, _raw=_raw)
        if _raw:
            return _per_symbol(value, lambda r: r)
        return _per_symbol(value, _kline_last_row)

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

    def snapshot(self, symbol: str | list[str], _fields: Any = None) -> Any:
        """行情快照（23 字段：价量、涨跌、均线、市值、标识）。

        传单个代码返回该票快照 MAP；传代码列表（≥3 票）自动路由批量原生实现
        ``kline.snapshot_batch``（单次 eval，EC 按量 60~90 EC/票，而非逐票首算
        10,250 EC/票），返回 BatchResult——``results`` 为 ``{代码: 23 字段 MAP}``。
        批量路径下 ``kline_date/kline_sas`` 为 None（当日索引未物化这两个字段），
        价格为索引 EOD 快照值（非实时 tick），盘中实时价请用 ``live``/``batch_live``；
        ETF/新上市等索引外标的自动回退逐票快照（数值与单票一致）。列表 <3 票或
        ``Client(native_batch=False)`` 时退回逐票拼接（语义同单票）。

        价量与涨跌：close、percent、volume、amount、chg_5d、chg_10d、chg_20d、chg_90d、roi_1y。
        均线与市值：ma20、ma60、ma120、ma60_up、vol_ratio_5、mv、mv_free。
        标识与日期：symbol、name、industry、is_st、is_suspend、kline_date、kline_sas。
        percent 与 chg_* 为小数，volume=股，amount 与市值=元；布尔字段为 ma60_up、is_st、is_suspend。
        目录 returns_shape 由本仓精修条目给出完整字段表，不依赖上游注释。

        :param _fields: 列投影（list/逗号串）：只保留指定字段；批量时逐标的投影
        """
        return _out(self._c.call("kline.snapshot", sym=symbol), _fields=_fields)

    def is_etf(self, symbol: str) -> bool:
        """是否场内 ETF。"""
        return bool(self._c.call("kline.is_etf", sym=symbol))


class MoneyflowApi(_Api):
    """资金流向（日频：主力/超大单/大单/中单/小单净流入，单位=元；非逐笔 Level2）。"""

    def bars(self, symbol: str, n: int | None = None,
             begin: str | None = None, end: str | None = None,
             _raw: bool = False, _fields: Any = None) -> Any:
        """资金流历史（DataFrame：date/net_mf/elg_net/lg_net/md_net/sm_net，date 升序）。

        :param n: 条数，默认 20。区间查询：显式传 n=只取区间内最近 n 根（不补页）；
            不传 n=自动锚点切片补齐（每片 ≤ max_limit，覆盖 begin 即停）
        :param begin: 起始日期（含，YYYY-MM-DD），须与 end 同时提供；区间上限 5 年
        :param end: 结束日期（含）
        :param _raw: True=上游原始行（跳过规范化/换算）
        :param _fields: 列投影（list/逗号串），在排序过滤后执行；不降 EC

        区间完整性（不传 n）：与 ``kline.bars`` 同款锚点切片——每片走
        ``moneyflow.query_bars_anchor``（窗口右端锚在已取最早一根），只物化
        ≤ end 的行、覆盖 begin 即停；任意区间完整返回、计费 ≈ 区间实际行数。
        显式传 n 为单次请求，超出单次上限显式报错（不静默截断）。
        """
        _warn_large_moneyflow_list(symbol)
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            if _raw:
                raise UsageError("_raw=True 时不支持 begin/end（原始行无扁平日期字段）",
                                 code="range")
            begin_iso = _normalize_date(begin)
            limit = min(int(n) if n is not None else (self._c.max_limit or 10000), 10000)
            if n is None and isinstance(symbol, str):
                # 锚点切片（与 kline.bars 同口径）：覆盖由结构保证，不估算根数
                merged: dict[str, dict] = {}
                anchor = _normalize_date(end)
                prev_anchor: str | None = None
                for _ in range(_MAX_RANGE_SLICES):
                    chunk = self._c.call("moneyflow.query_bars_anchor", sym=symbol,
                                         limit=limit, anchor_date=anchor)
                    if not isinstance(chunk, list) or not chunk:
                        break
                    dates: list[str] = []
                    for r in chunk:
                        d = str(r.get("date") or "")[:10] if isinstance(r, dict) else ""
                        if d:
                            dates.append(d)
                            merged.setdefault(d, r)
                    if not dates or len(chunk) < limit or min(dates) <= begin_iso:
                        break
                    prev_anchor, anchor = anchor, min(dates)
                    if anchor == prev_anchor:
                        raise LimitError(
                            f"moneyflow.bars: 锚点未前移（anchor={anchor}）——服务端未按 "
                            f"anchor_date 收窄窗口；请改传 n= 或缩小区间", code="range")
                else:
                    raise LimitError(
                        f"moneyflow.bars: 区间 {begin}~{end} 切了 {_MAX_RANGE_SLICES} 片"
                        f"（每片 ≤{limit} 行）仍未覆盖到 begin；请调大 "
                        "Client(max_limit=...) 或缩小区间", code="range")
                rows = [merged[d] for d in sorted(merged)]
                return _out(_filter_by_date(rows, begin, end, "date", 0),
                            raw=_raw, _fields=_fields)
            rows = self._c.call("moneyflow.query_bars", sym=symbol, limit=limit, _raw=_raw)
            out = _per_symbol(rows, lambda r: _sort_rows_by_date(
                _filter_by_date(r, begin, end, "date", limit)))
            return _out(out, raw=_raw, _fields=_fields)
        limit = 20 if n is None else n
        out = _per_symbol(self._c.call("moneyflow.query_bars", sym=symbol,
                                       limit=limit, _raw=_raw), _sort_rows_by_date)
        return _out(out, raw=_raw, _fields=_fields)

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

    def board(self) -> Any:
        """全市场资金流快照：一次取数，按主力净流入降序（日频 EOD，仅 A 股非停牌）。

        字段 symbol/name/net_mf/net_mv_ratio/lg_net/elg_net/md_net/sm_net/industry，
        金额=元、占比=小数。服务端索引直出——替代「全市场逐票批量」的正解：
        EC 只花一次求值的计算量，不再是 标的数 × 单票成本。非交易日数据不变；
        当日读数用 ``live()``（外部公开源，非盘中行情）。
        """
        return _out(self._c.call("moneyflow.board"))

class MarginApi(_Api):
    """融资融券（个股日频 + 市场级汇总/标的名单，2.0 P1 新增面）。

    融资买入/偿还/余额与融券卖出/偿还/余量；金额=元、量=股（与全库基础单位
    一致）。``latest`` 为最新一日单行；``market_summary`` 为沪深交易所汇总日表
    （BSE 无公开口径缺席）；``universe`` 为标的名单快照+调整史（out_date 空=生效）。
    """

    def query(self, symbol: str, limit: int = 20, _fields: Any = None) -> Any:
        """个股两融历史（DataFrame：trade_date/fin_buy_amt/fin_repay_amt/fin_balance/…，升序）。

        :param limit: 条数，默认 20
        :param _fields: 列投影（list/逗号串），在排序后执行；不降 EC
        """
        return _out(_sort_rows_by_date(
            self._c.call("margin.query", sym=symbol, limit=limit), key="trade_date"),
            _fields=_fields)

    def latest(self, symbol: str) -> Any:
        """最新一日两融单行，字段同 ``query()``。"""
        return self._c.call("margin.latest", sym=symbol)

    def market_summary(self, limit: int = 60, _fields: Any = None) -> Any:
        """市场级两融汇总（DataFrame：trade_date/exchange/fin_buy_amt/…，升序）。

        沪深交易所汇总日表（金额=元、量=股）；BSE 无公开汇总口径，缺席属源边界。
        服务端按交易日披露（约 17:00 后），非交易日不刷新。源无「融资偿还额/
        融券偿还量」两列（上游未披露，不造假填充），其余 6 列齐全。

        :param limit: 条数，默认 60（每交易所日一行；跨交易所同日并存）；
            长历史（如 3 年 ≈1,500 行）需 ``Client(max_limit=None)`` 或分批
        :param _fields: 列投影（list/逗号串），在排序后执行；不降 EC
        """
        return _out(_sort_rows_by_date(
            self._c.call("margin.market_summary", limit=limit), key="trade_date"),
            _fields=_fields)

    def universe(self, limit: int | None = None, _fields: Any = None) -> Any:
        """两融标的名单（DataFrame：security_code/security_name/exchange/in_date/out_date/…）。

        当前可两融标的（沪深保证金比例表口径 ≈4,000 行）。``out_date`` 为空 =
        当前生效；源不提供调入调出日期，故 ``in_date/out_date`` 为空（字段保留）。

        :param limit: 条数；默认 ``None`` = 全量快照（服务端上限 5,000）
            成本：逐行物化 ≈112 EC/行——全量 ≈45 万 EC（超默认告警阈值会被提示），
            只看部分标的可传 ``limit=500``（≈5.6 万 EC）；先估用
            ``cli.cost_estimate("margin.universe", limit=…)``
        :param _fields: 列投影（list/逗号串），在排序后执行；不降 EC
        """
        kw: dict[str, Any] = {} if limit is None else {"limit": limit}
        return _out(_sort_rows_by_date(
            self._c.call("margin.universe", **kw), key="security_code"),
            _fields=_fields)


class CalendarApi(_Api):
    """A 股交易日历（年表；回测/窗口计算的前置面，2.0 P1 新增）。

    交易日行结构 ``{date, is_open: true}``（非交易日不出行）；数据由交易所年历
    每年 11 月定稿后灌库（当年+次年）。次日历未灌时 ``next`` 如实返回可得行数。
    """

    def days(self, begin: str, end: str, limit: int | None = None) -> Any:
        """区间内交易日（DataFrame：date 升序；跨年自动合并年档）。

        :param begin: 起始日期（含，YYYY-MM-DD）
        :param end: 结束日期（含）
        :param limit: 行数上限（默认 800/年档；5 年区间 ≈1215 行，按需调高）
        """
        if limit is None:
            return _out(_sort_rows_by_date(
                self._c.call("calendar.days", begin=begin, end=end)))
        return _out(_sort_rows_by_date(
            self._c.call("calendar.days", begin=begin, end=end, limit=limit)))

    def is_open(self, date: str) -> bool:
        """某日是否交易日（缺行=非交易日，含周末与节假日）。

        :param date: 日期（YYYY-MM-DD；也接受 YYYYMMDD 与 date/datetime）
        """
        return bool(self._c.call("calendar.is_open", date=_normalize_date(date)))

    def next(self, date: str, n: int = 1) -> Any:
        """某日之后 N 个交易日（DataFrame：date 升序；不足 N 个如实返回）。

        :param date: 起算日期（YYYY-MM-DD；也接受 YYYYMMDD 与 date/datetime）
        :param n: 取之后 N 个交易日（默认 1）
        """
        return _out(_sort_rows_by_date(
            self._c.call("calendar.next", date=_normalize_date(date), n=int(n))))


class CbondApi(_Api):
    """可转债——合约快照/条款事件/正股关联/强赎触发/独立日 K。

    价格为面值 100 口径（元）；转债无除权口径，日 K 不复权。``board`` 是
    全市场面板（快照 + 最新事件 + 盘中价 + callHits + resetFloor）；``call_hits``
    统计正股无复权收盘 ≥ 强赎触发价的近窗交易日数，勿以单日价判定已满足；
    ``kline_window`` 返回 store 列式窗口（open/close/high/low/volume/amount）。
    目录内其余函数（quote_list/event_list/min1_live 等）经属性直达。
    """

    def board(self, _raw: bool = False) -> Any:
        """转债全市场面板：快照行 + 每债最新条款事件 + 盘中债价 overlay
        + 强赎触发计数（callHits）+ 下修地板价（resetFloor）。

        行为 latest_quotes 规范化行的超集（event/bondPercent/callHits/resetFloor）。
        注意：全市场重计算，openapi 沙箱（xs eval）有燃料上限，经 API 端点调用不受限。
        """
        return _out(self._c.call("cbond.board", _raw=_raw), raw=_raw)

    def latest_quotes(self, _raw: bool = False) -> Any:
        """全市场转债最新快照（按日更新；行字段经 fmt_quote 规范化）。"""
        return _out(self._c.call("cbond.latest_quotes", _raw=_raw), raw=_raw)

    def of_stock(self, symbol: str, _raw: bool = False) -> Any:
        """正股关联的转债快照行。

        :param symbol: 正股代码（6 位裸码）
        """
        return _out(self._c.call("cbond.of_stock", stk=symbol, _raw=_raw), raw=_raw)

    def query(self, symbol: str) -> Any:
        """按转债标的查条款事件（下修/回售/赎回等，规范化事件行）。

        :param symbol: 转债代码
        """
        return _out(self._c.call("cbond.query", sym=symbol))

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

    def bars(self, symbol: str, n: int = 120, _fields: Any = None) -> Any:
        """转债日线表 → DataFrame：date/open/high/low/close/volume/amount（date 升序）。

        列式窗口转每根一行（``date`` 取上游采样名前 10 位）；某列缺失时补 ``None``。
        不复权；价格与金额单位为元（本币），成交量单位为**张**（转债面值口径，
        1 张 = 100 元面值；live 实测 ``amount / close ≈ volume``）。
        窗口无数据时返回空 DataFrame。

        :param symbol: 转债代码（6 位裸码）
        :param n: 窗口根数，默认 120
        :param _fields: 列投影（list/逗号串）：只保留指定字段
        """
        raw = self._c.call("cbond.kline_window", code=symbol, n=n)
        if not isinstance(raw, dict):
            # 异常形态原值透传（dict 行数组仍走 DF 收口）；空窗口给空 DataFrame
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                return _out(_sort_rows_by_date(raw), _fields=_fields)
            return raw if raw is not None else _out([], _fields=_fields)
        names = raw.get("samplingName") or []
        columns = ("open", "high", "low", "close", "volume", "amount")
        series = {c: raw.get(c) or [] for c in columns}
        rows: list[dict[str, Any]] = []
        for i, name in enumerate(names):
            row: dict[str, Any] = {"date": str(name)[:10]}
            for col_name in columns:
                col = series[col_name]
                row[col_name] = col[i] if i < len(col) else None
            rows.append(row)
        return _out(_sort_rows_by_date(rows), _fields=_fields)

    def universe_codes(self, _raw: bool = False) -> Any:
        """转债代码全集（与快照口径一致）。"""
        return _out(self._c.call("cbond.universe_codes", _raw=_raw), raw=_raw)

    # ---- 研究级组合接口：取数 → 规则 → 事实包 → 成稿/出图，一条链路。----
    # 这些方法**不是**目录函数的薄翻译，故不登记 FRIENDLY_INDEX（那张表是
    # 「核心接口 ↔ 底层目录函数」的一一映射，生成器靠它回溯 returns_shape）。
    def daily(self, as_of: str | None = None, top_n: int = 20,
              budget: int = 60) -> dict[str, Any]:
        """跑一期可转债日更，返回事实包（三层口径 + 三道闸 + 状态机 + 事件日历）。

        取数构成（默认 ``enrich``/``curves`` 全开）：全市场面板 1 次、条款事件
        1 次、榜单前三各 1 次通道日 K、全表日 K 按 ≤120 只/批的批量 eval
        （批次随在市债数浮动）、收益率曲线 10 次（AAA/国债 × 5 期限）——
        **不是固定三次**，实际请求见返回的 ``coverage.requests_made``；
        ``budget`` 是硬上限（默认与 ``DailyConfig.DEFAULT_BUDGET`` 对齐），
        超出直接报错而不静默降级。

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
        :param date: 文件名日期（``YYYY-MM-DD`` 或 ``YYYYMMDD``，2.0 起统一接受 ISO；
            缺省取事实包的快照日）
        :param campaign: UTM campaign（缺省 ``day{date}cb``）
        :param fig_dir: 正文图片链接前缀；正式发布用相对路径 ``figs``，
            演练写临时目录时传绝对路径，配图存在性校验才能定位到真实文件
        """
        from wmshare.cb import article as A

        d = _compact_date(date or str(payload.get("date") or ""))
        if not d:
            raise UsageError("缺少日期：请传 date=YYYY-MM-DD 或使用带 date 的事实包",
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
        :param date: 文件名日期（``YYYY-MM-DD`` 或 ``YYYYMMDD``，2.0 起统一接受 ISO；
            缺省取事实包快照日）
        :param klines: 通道图用的日 K（缺省取事实包里的 featured_klines）
        """
        from wmshare.cb import article as A
        from wmshare.cb import figures as G

        d = _compact_date(date or str(payload.get("date") or ""))
        if not d:
            raise UsageError("缺少日期：请传 date=YYYY-MM-DD 或使用带 date 的事实包",
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

    def keys(self) -> Any:
        """可用指数键列表（``members``/``weights``/``valuation`` 的 key 取值域）。"""
        return _out(self._c.call("indices.keys"))

    def members(self, key: str, sort_by: str | None = None,
                top_n: int | None = None) -> Any:
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
        return _out(self._c.call("indices.members", **kw))

    def weights(self, key: str, top_n: int | None = None) -> Any:
        """指数权重股（披露权重降序；weight 为小数，0.071 = 7.1%）。

        :param key: 指数键（见 ``keys()``）
        :param top_n: 只取前 N 条
        """
        kw: dict[str, Any] = {"key": key}
        if top_n is not None:
            kw["top_n"] = top_n
        return _out(self._c.call("indices.weights", **kw))

    def members_history(self, key: str, begin: str = "", end: str = "") -> Any:
        """指数成分**日快照**长表（前向 PIT；信封 {ok, as_of, data, meta}）。

        数据源是物化表 ``alt.index_members_daily``（airflow
        ``pipeline.cn.index_members_daily`` 每日快照）：``data`` 为长表行
        ``{date, symbol, name, mv, weight}``（weight 可能缺失=诚实 nil），
        meta.window 语义与 ``valuation.daily_basic`` 逐字段同形
        （scan_days/scan_limit/pushed_down/oldest_scanned/truncated）。

        **前向 PIT 合同**：只有表内真实快照日；更早的历史上游不存在
        （``members`` 无日期参数、引擎成分绑当前时点），``count==0`` 表示
        「尚无快照」而非「成分无变化」。典型用途：按日聚合成分 → 拼 Qlib
        instruments episode 文件（wmshare-qlib ``write-universe --index``）。

        :param key: 指数键（"index.hs300" / "hs300" 均可）
        :param begin: 起始 ISO 日期（"" = 全量表）
        :param end: 结束 ISO 日期（"" = 到最新）
        """
        k = (key or "").strip()
        if not k:
            raise UsageError("key 只支持非空指数键（见 keys()）", code="params")
        xs = (
            f'return indices.members_daily("{k}", "{begin or ""}", "{end or ""}")'
        )
        res = self._c.eval_result(xs)
        if not isinstance(res, dict):
            return {"ok": False, "as_of": "", "data": [], "meta": {"note": "upstream non-map"}}
        return res

    def valuation(self, key: str, points: int | None = None) -> Any:
        """宽基估值时序（信封：``data.series`` 为 DataFrame，d/pe/pb 按 d 升序）。

        :param key: 指数键（见 ``keys()``）
        :param points: 季采样点数；series 可自行算分位
        """
        kw: dict[str, Any] = {"key": key}
        if points is not None:
            kw["points"] = points
        res = self._c.call("indices.valuation", **kw)
        if not isinstance(res, dict):
            return res
        series = res.get("series")
        if isinstance(series, list) and series and isinstance(series[0], dict):
            res["series"] = _sort_rows_by_date(series, key="d")
        return _envelope(True, res, as_of=str(res.get("asof") or ""))

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

        2.0 统一信封 ``{ok, as_of, data, meta}``：

        - ``data.points`` 为 DataFrame（date/pe/pb），**升序（旧→新）**——最新点
          用 ``points.iloc[-1]``；预热缓存未命中时 ``ok=False``、
          ``meta.cache="miss"``、``data`` 为空（绝不静默给错值）
        - ``data.pe_pct``/``data.pb_pct`` 是最新点在 ``window`` 窗口内的历史分位
          （0=最低，1=最高）；口径 ``rank0/(n-1)``、并列取中点，与前端一致
        - ``data.pe_pct_window`` 是分位**实际生效**的窗口：正常等于入参
          ``window``；该窗口被截断或拿不到分位时为 None
        - ``data.pct`` 给出 3y/5y/10y 三档原始分位束（p3/p5/p10 与样本数）。
          注意服务端的 ``p`` 恒为 5 年分位（与入参 window 无关），本方法按窗口
          取 ``p3``/``p5``/``p10``，不读 ``p``
        - ``data.win_trunc=True`` 表示缓存序列盖不住所选窗口，此时相关分位为 None
          （**不拿短窗口冒充长窗口**，不降级到更短窗口）
        - ``data.pe_missing``/``data.pb_missing``：该口径**最新点本身**无值（整体法下
          行业近期整体亏损时 ``ΣNPTS_TTM ≤ 0``，价格侧指标为 nil；实测
          ``industry.S11`` 最新 PE=None 而 PB 正常）。与「窗口不够」造成的 None
          是两回事，看这两个标志区分
        - ``meta.pct_source``：``server``（服务端分位）/ ``client``（本地补算）；
          ``meta.dv_has_history``：股息率是否有历史序列

        :param key: 指数/行业/红利键（见 ``universe_keys()``）
        :param window: 分位窗口 ``3y``/``5y``/``10y``，默认 ``5y``

        .. note::
           指数/行业 PE 历史的本入口是 **周频整体法**（平台预热缓存，约 14 年跨度）。
           个股的 ``$PCT_PE_TTM_*`` 分位码按求值会话 ``$SYMBOL`` 绑定，**不随指数/行业
           键切换**——给指数或行业算分位只能用本方法（或 ``valuation().data.series`` 自算）。
        """
        w = str(window or "5y").lower()
        if w not in ("3y", "5y", "10y"):
            w = "5y"
        try:
            raw = self._c.call("indices.trend", key=key, window=w)
        except UsageError:
            # 旧服务端只接受 key 一参（新增的 window 不被识别）：退回单参调用并在
            # 客户端自算分位。只吞 UsageError——鉴权/网络/服务端错误必须原样抛出，
            # 否则一次失败会变成两次请求，且真实故障被掩盖成「服务端没部署 pct」。
            raw = self._c.call("indices.trend", key=key)
        if not isinstance(raw, dict):
            # 预热缓存未命中：显式降级（ok=False + meta.cache="miss"），不静默给错值
            return _envelope(False, {}, as_of="", cache="miss", pct_source="client")
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

        # 服务端的 ``pct.<col>.p`` **恒为 5 年分位**（pct_bundle 里 "p": w5["p"]），
        # 与入参 window 无关。直接读 p 会让 trend(k, "3y") 静默返回 5 年分位
        # （实测 hs300：p=0.7671 而 p3=0.6119，差 15.5 个百分点）。因此按窗口取档：
        # 3y→p3、5y→p5、10y→p10。
        _FIELD = {"3y": "p3", "5y": "p5", "10y": "p10"}
        _TRUNC = {"10y": "trunc10"}

        def _pick(col: str) -> float | None:
            """按 window 取该档分位；该档截断或缺失时返回 None。

            契约是「**不拿短窗口冒充长窗口**」（market.index.yaml / API.md）：序列盖不住
            所选窗口时给 None，绝不降级到更短的窗口。实测 hs300 序列跨 2016-11-16 →
            2026-11-09（9.98 年），服务端 trunc10=True、p10=None，故 trend(k,"10y")
            的分位为 None——调用方可通过 ``pe_pct_window``/``pct.<col>.trunc10`` 分辨。
            """
            node = server_pct.get(col)
            if not isinstance(node, dict):
                return None
            if node.get(_TRUNC.get(w, "")):
                return None
            val = node.get(_FIELD[w])
            return val if isinstance(val, (int, float)) else None

        pe_pct = _pick("pe")
        pb_pct = _pick("pb")
        # 实际生效窗口：拿到分位才等于入参 window（截断时为 None）
        eff_win = w if (pe_pct is not None or pb_pct is not None) else None
        # 分位为 None 的两种原因必须可区分，否则调用方无法判断「窗口不够」还是
        # 「该主体当前无 PE」：整体法下行业近期整体亏损时 ΣNPTS_TTM ≤ 0，价格侧指标
        # 返回 nil（实测 industry.S11 最新 PE=None 但 PB 有值），此时无 PE 分位是正常
        # 结果，不是数据缺失。注意判断的是**最新点** pts[0]，而 last_pe 取的是「最近的
        # 正值点」（供本地分位兜底用），二者不能混用。
        head = pts[0] if pts else {}
        pe_missing = not (isinstance(head.get("pe"), (int, float)) and head["pe"] > 0)
        pb_missing = not (isinstance(head.get("pb"), (int, float)) and head["pb"] > 0)
        source = "server"
        win_n = int(raw.get("win_n") or 0)
        win_trunc = bool(raw.get("win_trunc", False))
        if pe_pct is None and pb_pct is None:
            # 旧服务端没有 pct/窗口：本地按同一口径补算，并如实标记截断
            years = int(w[:-1]) if w[:-1].isdigit() else 5
            pe_pct, pe_n, pe_trunc = _win("pe", years)
            pb_pct, pb_n, pb_trunc = _win("pb", years)
            win_n, win_trunc, source = max(pe_n, pb_n), (pe_trunc or pb_trunc), "client"
            eff_win = None if win_trunc else w
        # 2.0 契约：points/med 统一升序（旧→新）输出——服务端 base 是新→旧
        # （cursor.ds 顺序），1.x 直接透传是全局方向 footgun。分位计算内部仍按
        # 降序进行（head=pts[0] 是最新点），只在出口翻转，两套语义不再混淆。
        pts_asc = list(reversed(pts))
        med = raw.get("med") or []
        if isinstance(med, list) and med and isinstance(med[0], (list, tuple)):
            med = list(reversed(med))
        med_df = _out([{"date": str(m[0])[:10], "pe_med": m[1]}
                       for m in med if isinstance(m, (list, tuple)) and len(m) >= 2]) \
            if med and isinstance(med[0], (list, tuple)) else med
        return _envelope(
            True,
            {"key": key, "density": str(raw.get("density") or "weekly"),
             "n": len(pts), "points": _out(pts_asc),
             "pe_pct": pe_pct, "pb_pct": pb_pct,
             "pe_pct_window": eff_win,
             "pe_missing": pe_missing, "pb_missing": pb_missing,
             "med": med_df,
             "pct": server_pct,
             "window": str(raw.get("window") or w),
             "win_start": str(raw.get("win_start") or ""),
             "win_n": win_n,
             "win_trunc": win_trunc},
            as_of=str(raw.get("asof") or ""),
            pct_source=source, dv_has_history=bool(raw.get("dv_has_history", False)))


# ---------------------------------------------------------------- 证券基础 market
class StocksApi(_Api):
    """全市场证券列表与行业映射（代码池 / 行业成分；stocks 目录域）。

    证券行字段：symbol/name/exchange/industry(三级行业键)/industry_name/is_st/listed。
    美股：列表与个股行业码可用；行业目录树上游未灌数，``industries()`` 恒空。
    """

    def list(self) -> Any:
        """全市场证券列表（当前市场；A≈5.7k / 港≈2.8k / 美≈5.3k 行，排序不保证）。

        全表单次返回，无分页；随上游每日刷新（美股 universe 为手动刷新，有滞后）。
        """
        return _out(self._c.call("stocks.query_list"))

    def industries(self, level: int | None = None) -> Any:
        """行业目录（standard: sw2021 申万 | hsi 恒生）。

        :param level: None=全部层级；1..3=指定级
        行字段：symbol/name/level/parent/standard。
        """
        kw: dict[str, Any] = {}
        if level is not None:
            kw["level"] = int(level)
        return _out(self._c.call("stocks.industry_list",**kw))

    def industry_members(self, industry: str, top_n: int | None = None) -> Any:
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
        return _out(rows)

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
    """选股与全景：单票筛选器（bool）+ 全市场条件选股 + 涨跌宽度（服务端索引直出）。

    筛选阈值与返回占比统一**小数**（0.10 = 10%；1.x 宽度返回的 ``*_pct`` 百分数
    反例已在 2.0 统一换算为小数，全库单位口径不再有例外）；事件筛选以「当日有
    成交」为前置（停牌恒 False）。全市场四件套（全景/分桶/行业分布/涨跌榜）由
    服务端索引聚合直出、免本地计算；``idx`` 不传时由服务端解析 A 股最新查询索引。
    ``query()`` 是条件选股主入口：一条 ``$码`` 表达式出全市场命中数与前 N 行，
    替代「先批量取数再本地过滤」的逐票路径；返回列与 indicator/macro 同一台账
    换算管线（登记码默认换算到基础单位）。kline 目录的其余筛选函数经属性直达
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
    # 1.x 的 up_pct/down_pct/flat_pct/pct_of_total 是百分数（全库唯一反例），
    # 2.0 起统一 ×0.01 换算为小数，与 median_pct 同口径。
    _PCT_FIELDS = ("up_pct", "down_pct", "flat_pct", "pct_of_total")

    @classmethod
    def _normalize_pct(cls, node: Any) -> Any:
        if isinstance(node, dict):
            for k in cls._PCT_FIELDS:
                v = node.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    node[k] = v * 0.01
        elif isinstance(node, list):
            for r in node:
                if isinstance(r, dict):
                    cls._normalize_pct(r)
        return node

    def _breadth(self, fn: str, idx: str | None,
                 label_key: str | None = None) -> Any:
        if idx is None:
            rows = self._c.eval_result(f"return {fn}(LatestIndexKey())")
        else:
            rows = self._c.call(fn, idx=idx)
        if label_key is not None:
            rows = _strip_bin_prefixes(rows, label_key)
        return _out(self._normalize_pct(rows))

    def index_breadth_summary(self, idx: str | None = None) -> dict:
        """全市场涨跌全景（上涨/下跌/平盘家数、占比与涨跌幅中位数；占比=小数）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_summary", idx)

    def index_breadth_bins(self, idx: str | None = None) -> Any:
        """涨跌幅 9 档分桶（DataFrame：label/count/pct_of_total 小数）。

        label 已剥服务端排序前缀（上游 `i_涨停` → `涨停`）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_bins", idx, label_key="label")

    def index_breadth_bin_industries(self, idx: str | None = None) -> Any:
        """涨跌幅分桶 × 一级行业分布（DataFrame：bin/industry/count；bin 同样剥前缀）。

        :param idx: 服务端索引键（高级；默认不传 = A 股最新查询索引）
        """
        return self._breadth("kline.index_breadth_bin_industries", idx,
                             label_key="bin")

    def index_top_movers(self, limit: int = 20, desc: bool = True,
                         idx: str | None = None) -> Any:
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
        return _out(rows)

    # ---- 全市场条件选股（服务端索引引擎直出，免逐票 eval）----
    def _metric_code(self, code: Any, *, what: str) -> str:
        """输出列/排序键必须是单个 ``$码`` 且在目录内（防编造）。"""
        text = str(code).strip()
        if not _METRIC_CODE.fullmatch(text):
            raise UsageError(
                f"{what} 必须是单个指标码（如 \"$ROE_TTM_LAST\"），收到 {code!r}；"
                "码先 cat.search(...) 查", code="params")
        return text

    def _check_codes(self, codes: list[str]) -> None:
        bad = [c for c in codes if self._c.catalog.metric(c) is None]
        if bad:
            raise CatalogError(
                f"未知指标 {bad}（防编造：code 必须在指标目录内）；"
                "先 cat.search(...) 查真码", code="metric")

    def query(self, where: str, order: str | None = None, desc: bool = True,
              limit: int = 50, offset: int = 0, fields: list[str] | None = None,
              idx: str | None = None) -> Any:
        """全市场条件选股：一条表达式扫最新索引，返回命中总数与前 N 行。

        ``where`` 是 XS 布尔表达式（与/或用 ``&&`` / ``||``、非用 ``!``；比率一律
        小数，0.03 = 3%），服务端索引引擎一次查完，**不是**逐票 eval、也不需要先
        拉全市场再本地过滤。返回统一信封，数据在 ``data`` 内——``data.count`` 是
        全市场真实命中数，与 ``limit`` 无关（防把 topN 当全市场）。

        :param where: 条件表达式，$码须在指标目录内，如 "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15"
        :param order: 排序指标码（单个 $码）；不传则按索引顺序
        :param desc: order 降序（默认 True，高分/高值在前）
        :param limit: 返回行数，默认 50；传 0 = 只取 count；受 Client(max_limit=...) 与单次 10000 行硬上限钳制
        :param offset: 跳过前 N 条（配合 order 分页）
        :param fields: 额外返回列（$码 列表）；传了就用它替代默认列集合
        :param idx: 服务端索引键（高级；默认不传 = 当前市场最新查询索引）

        返回统一信封：``data.count`` 是全市场真实命中数（与 limit 无关，防把 topN
        当全市场）、``data.rows`` 为 DataFrame（列=symbol/name+$码原文）。
        口径与成本：索引为**日频 EOD**（盘中不刷新）；返回列与 indicator/macro
        同一台账换算管线（登记码默认换算到基础单位）。``$IS_ST``/``$IS_SUSPEND``
        仅 A 股索引有列，港美请改用其它条件。成本 = 1 次请求，EC 随 where/order
        引用列的物化成本变化（实测 70~4.8 万，不计标的数），远低于全市场逐票
        eval（≈45.6 万且按标的数放大）。
        """
        text = str(where or "").strip()
        if not text:
            raise UsageError(
                "where 不能为空；示例：cli.screener.query(\"$ROE_TTM_LAST > 0.15\")",
                code="params")
        if _PY_BOOL_RE.search(text):
            raise UsageError(
                "where 是 XS 表达式：与/或用 && / ||、非用 !（不是 Python 的 "
                f"and/or/not）：{where!r}", code="params")
        try:
            limit, offset = int(limit), int(offset)
        except (TypeError, ValueError):
            raise UsageError(f"limit/offset 必须是整数（收到 {limit!r}/{offset!r}）",
                             code="params") from None
        if limit < 0 or offset < 0:
            raise UsageError(f"limit/offset 不能为负（收到 {limit}/{offset}）", code="params")
        cap = min(self._c.max_limit or 10000, 10000)
        if limit > cap:
            raise LimitError(
                f"query: limit={limit} 超过单次上限 {cap}"
                "（分页用 offset 续取；可在 Client(max_limit=...) 调整，设 None 关闭）",
                code="limit")
        codes = list(dict.fromkeys(_METRIC_CODE.findall(text)))
        if not codes:
            raise UsageError(
                f"where 里没有 $指标码：{where!r}；示例 "
                "\"$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15\"（码先 cat.search 查）",
                code="params")
        self._check_codes(codes)
        order_code = self._metric_code(order, what="order") if order else None
        if order_code is not None:
            self._check_codes([order_code])
        extra = [self._metric_code(c, what="fields") for c in (fields or [])]
        self._check_codes(extra)
        projected = extra if extra else ([order_code] if order_code else []) + codes
        labels = list(dict.fromkeys(["$SYMBOL", "$NAME", *projected]))
        key = "LatestIndexKey()"
        if idx is not None:
            if not re.fullmatch(r"[\w.\-]+", str(idx)):
                raise UsageError(f"idx 只接受索引键（如 index.hs300），收到 {idx!r}",
                                 code="params")
            key = f'"{idx}"'
        cond = json.dumps(text, ensure_ascii=False)
        lines = [
            f"idx := {key}",
            f'_ := INDEX_FIELD_LOAD(idx, {", ".join(labels)})',
            f'ids := INDEX_QUERY_SPEC(idx, {{"where": {cond}, "result": "row_ids"}})',
        ]
        if limit:
            spec = f'"where": {cond}'
            if order_code is not None:
                spec += f', "order": "{order_code}", "order_desc": {str(bool(desc)).lower()}'
            spec += f', "limit": {limit}, "offset": {offset}'
            lines.append(f"rows := INDEX_QUERY_SPEC(idx, {{{spec}}})")
            it = ", ".join(labels)
            lines.append(f'return {{"count": LEN(ids), "rows": CONOF(rows, ITER({it}))}}')
        else:
            lines.append('return {"count": LEN(ids), "rows": []}')
        res = self._c.eval_result(lines)
        if not isinstance(res, dict):
            return res  # 上游异常形态原样透传（同 indicator.metrics）
        rows = res.get("rows") or []
        keys = ["symbol", "name", *labels[2:]]
        metric_keys = labels[2:]
        out = [dict(zip(keys, r)) if isinstance(r, (list, tuple)) else r for r in rows]
        # 返回列与 indicator/macro 同一台账换算管线：登记码（成交量/亿元/百分数族）
        # 在选股结果里同样换算到基础单位，跨链路口径一致。
        for row in out:
            if isinstance(row, dict):
                for k in metric_keys:
                    if k in row:
                        row[k] = ledger_convert(k, row[k])
        return _envelope(True, {"count": int(res.get("count") or 0), "rows": _out(out)})


# ---------------------------------------------------------------- 回测 backtest
class BacktestApi(_Api):
    """单股回测：均线买卖点 → 成交明细 + 净值 + 汇总（本地撮合，口径固定）。

    一条调用串完「取全历史日 K → 金叉买/死叉卖 → 次日开盘成交（T+1）→ 100 股整手 →
    佣金/印花 → 逐笔成交与净值」。成交规则与费用固定在返回的 ``caliber`` 里，
    不建模的部分（历史 ST、分红税、涨跌停排队、日内）逐条写在文档中。
    """

    def run(self, symbol: str, rule: str = "ma_cross", fast: int = 5, slow: int = 20,
            buy: float | None = None, sell: float | None = None,
            begin: str | None = None, end: str | None = None,
            cash: float = 1_000_000.0, adj: str = "qfq") -> dict:
        """跑一次单股买卖点回测，返回成交明细与净值汇总。

        两种规则（成交/费用/净值口径完全相同）：
        ``rule="ma_cross"``（默认）用收盘价 SMA：``fast`` 上穿 ``slow`` 买、下穿卖；
        ``rule="pe"/"pb"/"ps"/"pr"`` 用估值：当根估值 ``<= buy`` 买、``>= sell`` 卖。
        **估值回测核默认取 3 年窗口**（``cli.valuation.hist_stats`` 支持
        6m~10y，公告日 TTM、PIT），所以估值回测区间自动限制在序列覆盖内，
        亏损期等无估值的日子不出信号。

        成交：信号当根收盘后确定、**次日开盘**成交（T+1）；100 股整手；现金不足一手
        则放弃该次买入（见 ``warnings``）。一字板（open==high==low==close）与零量
        （停牌占位）顺延到下一根，次数见 ``caliber.skipped``。期末未平仓按最后一根
        收盘平仓（``reason="期末平仓"``）。

        :param symbol: 标的代码（6 位裸码；港/美按客户端市场）
        :param rule: ``ma_cross``（默认）/ ``pe`` / ``pb`` / ``ps`` / ``pr``
        :param fast: 均线快线周期，默认 5（仅 ma_cross）
        :param slow: 均线慢线周期，默认 20，须大于 fast（仅 ma_cross）
        :param buy: 估值买点阈值（仅 pe/pb/ps/pr），如 PE <= 20
        :param sell: 估值卖点阈值，须大于 buy，如 PE >= 40
        :param begin: 回测起点（含，YYYY-MM-DD）；须与 end 同时提供
        :param end: 回测终点（含，YYYY-MM-DD）
        :param cash: 初始资金（元），默认 100 万——高价股一手可能十几万，不足一手买不进
        :param adj: 复权方式，默认 "qfq"；长历史建议 "hfq"，不复权会按分红日跳空计亏

        ``trades`` 每行一笔成交：买入带 date/side/price/shares/amount/fee/reason；
        卖出额外带本次闭环的 pnl/ret/hold_days。``summary`` 只有 8 个数字；
        ``equity`` 是逐日 ``[{date, nav}]``。成本口径：佣金 0.03%（最低 5 元）、
        卖出印花 0.05%，见 ``caliber``；估值规则的 ``caliber.valuation`` 记录
        ``{metric, window: "3y"}``。

        取数成本：不给 begin/end 时取全历史（1 万根，约 40 万 EC，EC 按请求行数计费）；
        给了区间就只取该区间需要的根数，EC 同步下降——看近两年请显式传 begin/end。
        """
        rule = str(rule or "ma_cross").lower()
        if rule == "ma":
            rule = "ma_cross"
        if rule not in ("ma_cross", *VALUATION_RULES):
            raise UsageError(
                f"rule 只支持 ma_cross / {' / '.join(VALUATION_RULES)}，收到 {rule!r}",
                code="params")
        valuation = rule in VALUATION_RULES
        try:
            fast, slow = int(fast), int(slow)
        except (TypeError, ValueError):
            raise UsageError(f"fast/slow 必须是整数（收到 {fast!r}/{slow!r}）",
                             code="params") from None
        if not (1 <= fast < slow):
            raise UsageError(f"周期不合法：需要 1 ≤ fast < slow，收到 fast={fast}, slow={slow}",
                             code="params")
        buy_threshold: float | None = None
        sell_threshold: float | None = None
        if valuation:
            if buy is None or sell is None:
                raise UsageError(
                    f"rule={rule} 需要 buy/sell 阈值（如 cli.backtest.run(\"600519\", "
                    f"rule=\"{rule}\", buy=20, sell=40)）", code="params")
            try:
                buy_threshold, sell_threshold = float(buy), float(sell)
            except (TypeError, ValueError):
                raise UsageError(f"buy/sell 必须是数字（收到 {buy!r}/{sell!r})",
                                 code="params") from None
            if not (0 < buy_threshold < sell_threshold):
                raise UsageError(
                    f"估值阈值需 0 < buy < sell，收到 buy={buy_threshold}, "
                    f"sell={sell_threshold}", code="params")
        if float(cash) <= 0:
            raise UsageError(f"cash 必须为正数，收到 {cash!r}", code="params")
        if begin is not None or end is not None:
            if not (begin and end):
                raise UsageError("begin 与 end 需同时提供", code="range")
            for label, value in (("begin", begin), ("end", end)):
                try:
                    date.fromisoformat(str(value)[:10])
                except ValueError:
                    raise UsageError(f"{label} 需为 YYYY-MM-DD，收到 {value!r}",
                                     code="range") from None
        # 取数根数按区间估算（EC 按请求行数计费：全历史 1 万根约 40 万 EC，只取区间能省下来）
        limit = 10000
        if begin:
            days = (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(begin)[:10])).days
            limit = min(10000, max(int(days * 0.8) + slow + 20, slow + 2))
        try:
            rows = _rows(self._c.kline.bars(symbol, n=limit, adj=adj))
        except LimitError as e:
            raise UsageError(
                f"回测要取的日 K 根数（{limit}）超过当前客户端单次上限 max_limit="
                f"{self._c.max_limit}；用 wmshare.Client.from_env(max_limit=None) 重建客户端，"
                "或缩小 begin/end 区间（EC 也随行数走）", code="limit") from e
        rows = sorted((r for r in (rows or []) if isinstance(r, dict)),
                      key=lambda r: str(r.get("date") or ""))
        if begin:
            rows = [r for r in rows if str(r.get("date") or "")[:10] >= str(begin)[:10]]
        if end:
            rows = [r for r in rows if str(r.get("date") or "")[:10] <= str(end)[:10]]
        if not rows:
            raise DataError(f"{symbol} 在回测区间内没有日 K：核对代码/区间，"
                            "或先用 cli.kline.bars 看数据是否存在")

        warnings: list[str] = []
        if valuation:
            stats = self._c.valuation.hist_stats(symbol, metric=rule, window="3y")
            # 2.0：hist_stats 返回统一信封（data.series 为 DataFrame，date=ISO），
            # 还原为引擎契约的 [[unix 秒, 值], ...]（北京零点 epoch，与 +08 归日一致）
            stats_data = stats.get("data") if isinstance(stats, dict) \
                and isinstance(stats.get("data"), dict) else stats
            sv = stats_data.get("series") if isinstance(stats_data, dict) else None
            series_rows = _rows(sv if sv is not None else [])  # DF/行数组两态都收
            series: list[list[Any]] = []
            for point in series_rows:
                if isinstance(point, (list, tuple)):      # 引擎原值形态（直连时）
                    series.append([point[0], point[1]])
                    continue
                d = str(point.get("date") or "")[:10]
                v = point.get("value")
                if not d or v is None:
                    continue
                epoch = (date.fromisoformat(d) - date(1970, 1, 1)).days * 86400 - 8 * 3600
                series.append([epoch, v])
            values = valuation_by_date(series)
            if not values:
                raise DataError(f"{symbol} 没有 {rule.upper()} 历史序列（亏损期无 PE、"
                                "或该标的未被估值序列覆盖）")
            first = min(values)
            earlier = [r for r in rows if str(r.get("date") or "")[:10] < first]
            if earlier:
                rows = rows[len(earlier):]
                warnings.append(f"估值序列只从 {first} 起（对齐行情窗口），更早的 "
                                f"{len(earlier)} 根已剔除")
            if not rows:
                raise DataError(f"{symbol} 的行情与 {rule.upper()} 估值序列（{first} 起）"
                                "没有重叠区间")
            assert buy_threshold is not None and sell_threshold is not None
            signals, missing = valuation_signals(rows, values, buy_threshold, sell_threshold)
            if missing:
                warnings.append(f"{missing} 根没有 {rule.upper()} 估值（亏损期/未覆盖），"
                                "当日不出信号")
            label = f"{rule}(buy={buy_threshold:g}, sell={sell_threshold:g})"
        else:
            if len(rows) < slow + 2:
                raise UsageError(
                    f"回测区间只有 {len(rows)} 根日 K，{fast}/{slow} 均线至少需要 {slow + 2} 根"
                    "（加大区间或调小周期）", code="range")
            signals = ma_cross_signals(rows, fast, slow)
            label = f"ma_cross(fast={fast}, slow={slow})"
            missing = 0

        out = run_backtest(rows, signals, cash=float(cash), rule=label)
        out["symbol"] = symbol
        out["warnings"] = warnings + out["warnings"]
        if valuation:
            out["caliber"]["valuation"] = {"metric": rule, "window": "3y"}
        if adj is None or str(adj).lower() in ("nr", "none", ""):
            out["warnings"].append("未复权：分红/除权日会被当成亏损，长区间建议 adj=\"qfq\" 或 \"hfq\"")
        return out


# ---------------------------------------------------------------- 财务 fundamentals
class StatementsApi(_Api):
    """三大报表 + 主要指标透视（三加一，cn/hk/us 全市场；披露原值、报表原币）。

    数据源与平台专业版同构：fin_income / fin_balance / fin_cashflow /
    fin_indicator 宽表（季度粒度、披露原币），一次 ``store.query`` 窗口批量
    取回全部期次后按「披露科目原文 × 期次」透视成行式。列名为各市场披露
    科目原文，不做 CN 口径翻译——列映射由消费侧负责。本方法族为组合门面
    （底层是读取脚本而非单一目录函数），不经过目录合同的单位换算与量级
    守护层。

    ``period`` 两档：``"annual"``（年报档，缺省，vals 键=纯年份）/
    ``"quarter"``（季报全档 Q1..Q4 混合，键=``2026-Q1``，2.0 起由 ``2026:Q1``
    统一为 ISO 风格连字符）。``years`` 期数 1..12（与专业版前端窗口对齐）。
    ``audit`` 读审计意见（按报告期对齐的年轴口径，仅 cn）。

    ``kind`` 取值：``balance``（资产负债）/``income``（利润）/``cashflow``
    （现金流）/``indicators``（主要指标）。
    """

    _CATALOGS = {"balance": "fin.balance",
                 "income": "fin.income",
                 "cashflow": "fin.cashflow",
                 "indicators": "fin.indicator"}

    @classmethod
    def _kind_catalog(cls, kind: str) -> str:
        try:
            return cls._CATALOGS[kind]
        except KeyError:
            raise UsageError(f"未知报表 kind={kind!r}；可选 {sorted(cls._CATALOGS)}",
                             code="params") from None

    @staticmethod
    def _validate_years(years: int) -> int:
        if not isinstance(years, int) or not 1 <= years <= 12:
            raise UsageError(f"years 只支持 1~12（专业版同窗口），收到 {years!r}",
                             code="params") from None
        return int(years)

    def _statement(self, kind: str, symbol: str, years: int, period: str) -> Any:
        from wmshare._stmt_xs import build_statement_xs, infer_market

        catalog = self._kind_catalog(kind)
        years = self._validate_years(years)
        if period not in ("annual", "quarter"):
            raise UsageError(f"未知 period={period!r}；可选 'annual'（年报档）| 'quarter'（季报全档）",
                             code="params") from None
        xs = build_statement_xs(catalog, symbol, years, period)
        rows = self._c.eval_result(xs, symbol=symbol, market=infer_market(symbol))
        # 2.0 期次键归一：quarter 档上游键 "2026:Q1" → "2026-Q1"（全库连字符口径）
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and isinstance(r.get("vals"), dict):
                    r["vals"] = {re.sub(r"^(\d{4}):Q(\d)$", r"\1-Q\2", k): v
                                 for k, v in r["vals"].items()}
        return _out(rows)

    def balance(self, symbol: str, years: int = 5,
                period: str = "annual") -> Any:
        """资产负债表（fin_balance 宽表；cn/hk/us）→ DataFrame（k=科目原文，vals=各期值）。

        :param symbol: 6 位 A 股代码 / 港股 5 位代码 / 美股 ticker（自动路由市场）
        :param years: 期数 1..12（缺省 5；季报档=总期数）
        :param period: "annual"（年报档，缺省）或 "quarter"（季报全档 Q1..Q4）
        """
        return self._statement("balance", symbol, years, period)

    def income(self, symbol: str, years: int = 5,
               period: str = "annual") -> Any:
        """利润表（fin_income 宽表；cn/hk/us）→ DataFrame（k=科目原文，vals=各期值）。

        :param symbol: 6 位 A 股代码 / 港股 5 位代码 / 美股 ticker（自动路由市场）
        :param years: 期数 1..12（缺省 5；季报档=总期数）
        :param period: "annual"（年报档，缺省）或 "quarter"（季报全档 Q1..Q4）
        """
        return self._statement("income", symbol, years, period)

    def cashflow(self, symbol: str, years: int = 5,
                 period: str = "annual") -> Any:
        """现金流量表（fin_cashflow 宽表；cn/hk/us）→ DataFrame（k=科目原文，vals=各期值）。

        :param symbol: 6 位 A 股代码 / 港股 5 位代码 / 美股 ticker（自动路由市场）
        :param years: 期数 1..12（缺省 5；季报档=总期数）
        :param period: "annual"（年报档，缺省）或 "quarter"（季报全档 Q1..Q4）
        """
        return self._statement("cashflow", symbol, years, period)

    def indicators(self, symbol: str, years: int = 5,
                   period: str = "annual") -> Any:
        """主要指标（fin_indicator 宽表；cn/hk/us）→ DataFrame（k=指标原文，vals=各期值）。

        :param symbol: 6 位 A 股代码 / 港股 5 位代码 / 美股 ticker（自动路由市场）
        :param years: 期数 1..12（缺省 5；季报档=总期数）
        :param period: "annual"（年报档，缺省）或 "quarter"（季报全档 Q1..Q4）
        """
        return self._statement("indicators", symbol, years, period)

    def audit(self, symbol: str) -> Any:
        """审计意见（按年报，返回 {年份: 意见}；cn）。"""
        return self._c.call("rptdom.statement_audit", sym=symbol)


class SegmentsApi(_Api):
    """经营分部：主营构成的多维分解（分产品 / 分业务 / 分区域 / 主营标签占比）。

    行结构统一 ``{name, tr, tr_text, cost, margin, ratio}``：收入/成本为**元**，
    毛利率与占比为**小数**（margin = (tr-cost)/tr，0.332 = 33.2%）；ratio 仅主营
    标签维填充、其余维为 0 占位。数据来自定期报告分部披露的平台清洗归一（clean
    口径，默认）；各维披露覆盖度先用 coverage() 探明。

    :param source: "clean"（默认，清洗归一）或 "raw"（披露明细）
    """

    def products(self, symbol: str, source: str = "clean", limit: int = 20) -> Any:
        """分产品/商品收入构成（行按收入降序）。"""
        return _out(self._c.call("segments.query_products", sym=symbol, opts={"source": source, "limit": limit}, ))

    def business(self, symbol: str, source: str = "clean", limit: int = 20) -> Any:
        """分业务线收入构成（行按收入降序）。"""
        return _out(self._c.call("segments.query_business", sym=symbol, opts={"source": source, "limit": limit}, ))

    def region(self, symbol: str, source: str = "clean", limit: int = 20) -> Any:
        """境内外分部。clean 口径返回 MAP（domestic/overseas 各含 tr/pct/margin/yoy），
        source="raw" 返回披露明细 ARR；无分部披露时为 None。"""
        return _out(self._c.call("segments.query_region", sym=symbol, opts={"source": source, "limit": limit}, ))

    def income(self, symbol: str, limit: int = 20) -> Any:
        """主营标签占比（name + ratio 小数；tr/cost 恒 0，margin 为 None）。"""
        return _out(self._c.call("segments.query_income", sym=symbol, opts={"limit": limit}, ))

    def snapshot(self, symbol: str, source: str = "clean") -> Any:
        """四维合并快照：{overview, income, region, product, business, coverage}。"""
        return _out(self._c.call("segments.snapshot", sym=symbol, opts={"source": source}, ))

    def coverage(self, symbol: str) -> Any:
        """各维是否有数据（has_income/has_region/has_products/has_business 布尔）。"""
        return self._c.call("segments.coverage", sym=symbol)

    def periods(self, symbol: str) -> Any:
        """清洗口径可用报告期（{clean_last, clean_last_q4}）。"""
        return self._c.call("segments.list_sas", sym=symbol)


class ValuationApi(_Api):
    """估值历史统计（与平台 web「估值通道」取数同源，宿主函数 HIST_STATS）。

    2.0 统一信封 ``{ok, as_of, data, meta}``：``data`` 含 ``avg/current/median/
    min/max/pct/count/series``——pct 为当前值的历史分位（小数，0.42 = 42% 分位）；
    ``data.series`` 为 DataFrame（date ISO / value），按日期升序。引擎不返回
    stddev，需要通道带宽时由调用方按总体口径（÷N）自算。
    口径注记：亏损期 PE 无数据、净资产为负期间不参与统计（与平台免责一致）。
    """

    _METRICS = {"pe": "pe", "pb": "pb", "ps": "ps", "pr": "pr_base"}
    # 引擎支持 <数字><单位> 通用窗口（vfunc parseWindow 无年限封顶，2.5 放开
    # 5y/10y 白名单；此前误记「上限 3 年」——那是旧白名单，不是引擎限制）
    _WINDOWS = ("6m", "1y", "2y", "3y", "5y", "10y")
    # 每日估值宽表字段（服务端物化 alt.valuation_daily；2.0 基础单位，
    # 与 _catalog/domains/valuation.yaml units 一致）
    _DAILY_FIELDS = ("pe_ttm", "pb", "ps", "pr", "total_mv", "circ_mv",
                     "turnover_rate", "dv_ttm")

    def hist_stats(self, symbol: str, metric: str = "pe", window: str = "3y") -> dict:
        """估值指标的历史统计与每日序列（PE=TTM 口径；pr=市赚率 pr_base）。

        :param metric: "pe" / "pb" / "ps" / "pr"
        :param window: "6m" / "1y" / "2y" / "3y" / "5y" / "10y"
            （引擎按日历月回溯，深度受标的上市时长限制；实际可得序列长度
            以返回 count/series 为准）
        """
        if metric not in self._METRICS:
            raise UsageError(
                f"metric 只支持 {sorted(self._METRICS)}（pe=市盈率TTM、pb=市净率、"
                "ps=市销率、pr=市赚率；金融/亏损股建议用 pb）", code="params")
        if window not in self._WINDOWS:
            raise UsageError(
                f"window 只支持 {list(self._WINDOWS)}", code="params")
        raw = self._c.eval_result(
            f'return HIST_STATS("{window}", "{self._METRICS[metric]}")', symbol=symbol)
        if not isinstance(raw, dict):
            return _envelope(False, {}, note="上游返回非 MAP")
        series = raw.get("series") or []
        rows = []
        for item in series:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                ts = item[0]
                d = ""
                if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
                    # 引擎按交易所本地零点（+08:00）落 unix 秒，与 _kline_last_row 同口径
                    d = (date(1970, 1, 1)
                         + timedelta(seconds=float(ts) + 8 * 3600)).isoformat()
                rows.append({"date": d, "value": item[1]})
        data = {k: v for k, v in raw.items() if k != "series"}
        data["series"] = _out(rows)
        return _envelope(True, data, metric=metric, window=window)


    def _daily_fields(self, fields: Any) -> list[str]:
        """解析/校验每日估值字段（列表或逗号串；未知字段报 UsageError）。"""
        if isinstance(fields, str):
            req = [f.strip().lower() for f in fields.split(",") if f.strip()]
        elif fields is None:
            req = list(self._DAILY_FIELDS)
        elif isinstance(fields, (list, tuple)):
            req = [str(f).strip().lower() for f in fields]
        else:
            raise UsageError(
                "fields 只接受 list[str] / 逗号字符串 / None", code="params")
        unknown = [f for f in req if f not in self._DAILY_FIELDS]
        if unknown:
            raise UsageError(
                f"fields 含未知字段 {unknown}；只支持 {list(self._DAILY_FIELDS)}",
                code="params")
        return list(dict.fromkeys(req))  # 去重保序

    def daily_basic(
        self, symbol: str, begin: str | None = None, end: str | None = None,
        fields: Any = None,
    ) -> dict:
        """个股每日估值序列（服务端物化宽表 ``valuation_daily``，仅 CN）。

        每股每交易日一行（airflow pipeline.cn.valuation_daily 当日 16:25 物化、
        SLA 17:00），8 字段全部服务端现成口径直出、2.0 基础单位（率=小数、
        额=元）：``pe_ttm/pb/ps/pr``（HIST_STATS 同核，公告日 PIT）、
        ``total_mv/circ_mv/turnover_rate/dv_ttm``（metric 层同式）。数据自
        物化日起可用；历史回填深度见域目录 notes（诚实缺行，不伪造）。

        :param begin: ISO 起日（含），``None``/``""`` = 开区间
        :param end: ISO 止日（含），``None``/``""`` = 开区间
        :param fields: list[str] / 逗号字符串 / ``None``（全部 8 个）
        :returns: 统一信封 ``{ok, as_of, data, meta}``；``data`` 为长表
            ``[{date, symbol, field, value}...]`` 升序；``as_of`` 为表内最新
            行日期（与过滤区间无关，供调用方判新鲜度）。
        """
        req = self._daily_fields(fields)
        b = _normalize_date(begin) if begin else ""
        e = _normalize_date(end) if end else ""
        raw = self._c.call(
            "valuation.daily_basic", sym=symbol, begin=b, end=e, fields=req)
        if not isinstance(raw, dict):
            return _envelope(False, {}, note="上游返回非 MAP")
        # 读窗口截断 → 按 oldest_scanned 向更早翻页补齐（每片一个服务端窗口）。
        # 服务端一次最多扫 scan_limit(1,500) 个日文档，请求 begin 早于实际扫到的
        # 最早日期时 meta.window.truncated=True（2026-11-19 新增）。这里按
        # 「下一页 end = oldest_scanned 前一天」继续拉，直到不截断或没有更早数据。
        # 上限 10 片（≈15,000 交易日，远超 A 股历史）防死循环。
        pages = 1
        meta = dict(raw.get("meta") or {})
        win = meta.get("window") or {}
        collected = list(raw.get("data") or [])
        while win.get("truncated") and pages < 10:
            oldest = str(win.get("oldest_scanned") or "")[:10]
            if len(oldest) != 10:
                break
            import datetime as _d
            try:
                page_end = (_d.date.fromisoformat(oldest)
                            - _d.timedelta(days=1)).isoformat()
            except ValueError:
                break
            page = self._c.call(
                "valuation.daily_basic", sym=symbol, begin=b, end=page_end,
                fields=req)
            pages += 1
            if not isinstance(page, dict):
                break
            page_rows = list(page.get("data") or [])
            if not page_rows:
                break
            collected = page_rows + collected      # 更早的在前 → 保持升序
            page_win = (page.get("meta") or {}).get("window") or {}
            win = page_win
        if pages > 1:
            meta["window"] = win
            meta["pages"] = pages
            meta["count"] = len(collected)
            raw = dict(raw)
            raw["data"] = collected
            raw["meta"] = meta
            raw["ok"] = bool(collected)
        return raw

    def daily_basic_multi(
        self, symbols: Any, begin: str | None = None, end: str | None = None,
        fields: Any = None,
    ) -> dict:
        """多票每日估值序列（一次 eval，行合同与 ``daily_basic`` 完全一致）。

        物化表按 per-symbol key 落库、没有全市场入口，逐票调用要把固定开销乘 N；
        本方法走服务端 ``valuation.daily_basic_multi``，一次求值内处理多票。
        **EC 仍按票计价**（批量省请求次数不省算力），但省掉 N 次调度开销。

        :param symbols: 标的清单（list/tuple；``>=200`` 票时提示成本量级）
        :param begin: ISO 起日（含），``None``/``""`` = 开区间
        :param end: ISO 止日（含），``None``/``""`` = 开区间
        :param fields: list[str] / 逗号字符串 / ``None``（全部 8 个）
        :returns: 统一信封；``data`` 为多票长表 ``[{date, symbol, field, value}]``，
            ``meta.per_symbol`` 给出每票的 ``count/oldest_scanned/truncated``
        """
        if isinstance(symbols, (str, bytes)) or not isinstance(symbols, (list, tuple)):
            raise UsageError("symbols 只接受 list/tuple", code="params")
        syms = [str(s) for s in symbols if str(s).strip()]
        if not syms:
            raise UsageError("symbols 不能为空", code="params")
        syms = list(dict.fromkeys(syms))
        if len(syms) > 200 and self._c.ec_warn_threshold is not None:
            import warnings
            warnings.warn(
                f"daily_basic_multi: {len(syms)} 票按票计价，总 EC ≈ 票数 × 单票地板"
                f" ≈{len(syms) * 1700:,} EC 量级；大清单建议先抽样确认口径",
                stacklevel=2)
        req = self._daily_fields(fields)
        raw = self._c.call(
            "valuation.daily_basic_multi", syms=syms,
            begin=_normalize_date(begin) if begin else "",
            end=_normalize_date(end) if end else "",
            fields=req)
        if not isinstance(raw, dict):
            return _envelope(False, {}, note="上游返回非 MAP")
        return raw

    def daily_basic_coverage(
        self, symbol: str, begin: str | None = None, end: str | None = None,
    ) -> dict:
        """可用日期范围发现（不拉序列，只取一个日窗口的元数据）。

        只请求 ``fields=["pe_ttm"]`` 并读取 ``meta.window``，因此成本与
        ``daily_basic`` 同阶（按扫描行计费）但数据量最小——用于先探「这段区间
        有没有数据 / 表能回溯到多早」，再决定要不要拉整段。

        :param begin: 关心区间的起日；早于表内可读范围时 ``truncated`` 为真
        :param end: 关心区间的止日；``None``/``""`` = 开区间
        :returns: 统一信封；``data`` 为
            ``{as_of, oldest_scanned, scan_days, scan_limit, truncated, pages}``
        """
        raw = self.daily_basic(symbol, begin, end, fields=["pe_ttm"])
        if not isinstance(raw, dict):
            return _envelope(False, {}, note="上游返回非 MAP")
        meta = raw.get("meta") or {}
        win = meta.get("window") or {}
        data = {
            "as_of": str(raw.get("as_of") or "")[:10],
            "oldest_scanned": str(win.get("oldest_scanned") or "")[:10],
            "scan_days": int(win.get("scan_days") or 0),
            "scan_limit": int(win.get("scan_limit") or 0),
            "truncated": bool(win.get("truncated")),
            "pages": int(meta.get("pages") or 1),
        }
        return _envelope(True, data, symbol=str(symbol))


class EstimatesApi(_Api):
    """盈利预测与研报（卖方研究数据）。

    机构盈利预测逐年 EPS/PE（year_mark A=实际 E=预测，YEAR1..YEAR4 为预测年份
    序列）、预测明细（机构/研究员/归母净利/评级）、评级统计（综合评级与买卖
    家数按窗口）、个股研报列表（标题/机构/作者/行业/链接；研报正文不在接口
    范围）。EPS=元/股、金额=元、PE=倍。
    """

    def query_forecast(self, symbol: str, limit: int = 8) -> Any:
        """机构盈利预测（逐年 EPS/PE，A=实际 E=预测）。

        :param limit: 条数，默认 8
        """
        return _out(self._c.call("estimates.query_forecast", sym=symbol, limit=limit))

    def query_forecast_detail(self, symbol: str, limit: int = 8) -> Any:
        """盈利预测明细（机构/研究员/归母净利/评级）。

        :param limit: 条数，默认 8
        """
        return _out(self._c.call("estimates.query_forecast_detail", sym=symbol,
                                 limit=limit))

    def query_rating(self, symbol: str, limit: int = 8) -> Any:
        """评级统计（综合评级与买卖家数按窗口）。

        :param limit: 条数，默认 8
        """
        return _out(self._c.call("estimates.query_rating", sym=symbol, limit=limit))

    def query_reports(self, symbol: str, limit: int = 8) -> Any:
        """个股研报列表（标题/机构/作者/行业/报告链接）。

        :param limit: 条数，默认 8
        """
        return _out(self._c.call("estimates.query_reports", sym=symbol, limit=limit))


# 截面字段 → 指标码：一一对应且全部经指标目录校验，防止凭空造码。
# 这些码只有当前值，没有按交易日的历史序列；不据此合成历史宽表。
#
# 选码口径（2026-11-13 live 实测，600519）：
# - pb 用 $PB_TTM_LAST 而非 $PB：$PB 是 $PB_TTM 的纯别名（点值 5.80），
#   $PB_TTM_LAST 才是最新截面（6.62），与 pe_ttm 同为「最新」口径。
# - total_mv 用 $MV_LAST 而非 $ID_MV_LAST：后者是 SUMS($MV_LAST) 的行业/指数
#   聚合族（单标的求值返回 nil），不是个股总市值。
# - roe_avg 用 $ROE_AVG3：$ROE_AVG 是「全部 Q4 历史平均」，无固定窗口、无守护。
# - eps_ttm 用 $EPS_NPTS_TTM_LAST（归母）：$EPS_DPPR_TTM_LAST 是扣非，字段名会误导。
BASIC_FIELDS: dict[str, str] = {
    "pe_ttm": "$PE_TTM_LAST",
    "pb": "$PB_TTM_LAST",
    "turnover_rate": "$TURNOVER_RATE_LAST",
    "total_mv": "$MV_LAST",
}
FINANCIAL_FIELDS: dict[str, str] = {
    "roe_ttm": "$ROE_TTM_LAST",
    "roe_avg": "$ROE_AVG3",
    "eps_ttm": "$EPS_NPTS_TTM_LAST",
}


class IndicatorApi(_Api):
    """平台指标（按指标代码寻址）。

    2.0 单位标准化：比率类为小数（ROE 0.332 = 33.2%）、金额/市值为元、分位为
    小数、量为股；精选组声明过 range 的指标在返回前做量级守护（违例抛
    DataError）。units.yaml 台账登记码（成交量族=手、宏观房地产=亿元、
    $ROC_TTM 族=百分数）由 SDK **默认换算**到基础单位；``native=True`` 取
    上游原值（诊断逃生口）。

    美股标的按随包代码表归一，``AAPL.O``/``BRK.B`` 与裸码 ``AAPL``/``BRK_B`` 等价
    （见 ``normalize_symbol``）；上游仍报 ``symbol`` 未绑定时翻译成带代码写法指引的
    DataError，而不是把引擎返回的 0 静默放行。

    期货指标码（``$FUT_*``）用 ``fut_symbol`` 指定合约键：国内带市场前缀
    （``cn.SR.ZCE`` 郑商所、``cn.RB.SHF`` 上期所；后缀不是 .CZCE），外盘用
    ``global.CL`` 等 V2 键；``symbol`` 传任意 A 股代码（绑定期期间上下文），
    缺省合约 ``cn.SR.ZCE``。eval 引擎须为 cn 客户端；2.0 推荐走
    ``cli.futures`` 门面（锚定已内部封装）。
    """

    def get(self, symbol: str, code: str, fut_symbol: str | None = None,
            *, native: bool = False) -> Any:
        """取单个指标当前值，如 cli.indicator.get("600519", "$PE_TTM_LAST")。

        期货码传 fut_symbol（如 "global.CL"），symbol 传任意 A 股代码。
        台账登记码默认换算到基础单位；``native=True`` 返回上游原值。

        :param code: 指标码（``$`` 开头，如 ``"$PE_TTM_LAST"``；用 ``cat.search`` 查）
        :param fut_symbol: 期货连续合约键（``$FUT_*`` 需要，如 ``"cn.RB.SHF"``）
        :param native: True=保留上游原生单位（默认换算基础单位）
        """
        meta = self._c.catalog.metric_meta(code)
        if meta is None and self._c.catalog.metric(code) is None:
            raise CatalogError(f"未知指标 {code!r}（防编造：code 必须在指标目录内）",
                               code="metric")
        value = self._eval_metric(f"return {code}", symbol=symbol, label=code,
                                  fut_symbol=fut_symbol)
        return finish_metric(value, meta, code=code, validate=self._c._validate,
                             native=native)

    def metrics(self, symbol: str, codes: list[str],
                fut_symbol: str | None = None, *, native: bool = False) -> dict:
        """批量取多个指标当前值，返回 {code: value}（精选/台账码带换算与量级守护）。

        期货码传 fut_symbol（如 "cn.SR.ZCE"），symbol 传任意 A 股代码。
        ``native=True`` 返回上游原值。

        :param codes: 指标码列表（``$`` 开头；用 ``cat.search`` 查）
        :param fut_symbol: 期货连续合约键（``$FUT_*`` 需要）
        :param native: True=保留上游原生单位（默认换算基础单位）
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
                                 validate=self._c._validate, native=native)
                for c, v in values.items()}

    def basic(self, symbol: str) -> Any:
        """每日估值当前截面：``pe_ttm`` / ``pb`` / ``turnover_rate`` / ``total_mv``。

        **只有当前值，不提供按交易日的历史序列**；也不接受日期参数——上游没有
        按日回溯的估值序列，传入日期只会得到同一截面。

        口径：``pe_ttm`` 与 ``pb`` 都是最新 TTM 口径（``$PE_TTM_LAST`` /
        ``$PB_TTM_LAST``）；``turnover_rate`` 按流通股本计，小数（0.0026 = 0.26%）；
        ``total_mv`` 为个股总市值、单位元（``$MV_LAST``，不是行业聚合值）。
        字段名固定，缺失值以 ``None`` 表示。

        :param symbol: 标的裸码
        """
        values = self.metrics(symbol, list(BASIC_FIELDS.values()))
        if not isinstance(values, dict):
            return values
        return {field: values.get(code) for field, code in BASIC_FIELDS.items()}

    def financials(self, symbol: str) -> Any:
        """财务指标当前截面：``roe_ttm`` / ``roe_avg`` / ``eps_ttm``。

        **只有当前值，不是按报告期的百列宽表**。口径：``roe_ttm`` 是最新滚动
        十二个月口径；``roe_avg`` 是**近 3 年**平均（``$ROE_AVG3``，不是上市以来
        的历史均值）；``eps_ttm`` 是**归母**每股收益 TTM（不是扣非）。
        比率类为小数，每股收益为元。

        :param symbol: 标的裸码
        """
        values = self.metrics(symbol, list(FINANCIAL_FIELDS.values()))
        if not isinstance(values, dict):
            return values
        return {field: values.get(code) for field, code in FINANCIAL_FIELDS.items()}

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
    """公告检索与信号。window 枚举 "7d"/"1m"/"3m"/"6m"/"1y"/"3y"/"5y" 或天数整数；keyword 为标题/类型正则（可空）。

    市场：数据含 cn + 港股。``list``/``find``/``has_buyback`` 按标的代码自动
    路由（港股 5 位码直传）；全市场类方法（recent/by_category/on_date）缺省
    cn，用 ``market="hk"`` 取港股公告。列表类返回 DataFrame，按 ``date``
    **升序**（旧→新，2.0 标准；1.x 为倒序透传）。
    """

    def list(self, symbol: str, window: str = "3m", keyword: str = "",
             limit: int = 20, _raw: bool = False) -> Any:
        """单票公告列表（DataFrame：date/title/type/url/pdf_url，date 升序）。

        :param symbol: 6 位 A 股代码 / 港股 5 位代码（按代码自动路由市场）
        :param _raw: True=上游原始行（跳过规范化）
        """
        days = _window_days(window)
        rows = self._c.call("notice.query_by_symbol", sym=symbol, window=str(days),
                            type_regex=keyword, limit=limit, _raw=_raw)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def recent(self, window: str = "7d", keyword: str = "", limit: int = 50,
               market: str = "", _raw: bool = False) -> Any:
        """全市场近期公告（DataFrame：date/title/type/symbol/url，date 升序；cn/hk）。

        :param window: 时间窗口，如 "7d"/"1m" 或天数
        :param keyword: 标题/类型正则（可空）
        :param market: 公告市场，缺省自动（=cn）；港股显式传 "hk"
        :param _raw: True=上游原始行
        """
        days = _window_days(window)
        kwargs: dict = {"window": str(days), "type_regex": keyword, "limit": limit}
        if market:
            kwargs["market"] = market
        rows = self._c.call("notice.query_recent", _raw=_raw, **kwargs)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def by_category(self, category: str, window: str = "1m", limit: int = 20,
                    market: str = "", _raw: bool = False) -> Any:
        """按类别查公告（DataFrame，date 升序；如 "回购"；cn/hk）。

        :param category: 公告类别（如 ``"回购"``/``"减持"``；上游类别词表）
        :param market: 公告市场，缺省自动（=cn）；港股显式传 "hk"
        :param _raw: True=上游原始行
        """
        days = _window_days(window)
        kwargs: dict = {"category": category, "window": str(days), "limit": limit}
        if market:
            kwargs["market"] = market
        rows = self._c.call("notice.query_by_category", _raw=_raw, **kwargs)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def find(self, symbol: str, begin: str, end: str, keyword: str = "",
             limit: int = 50, market: str = "", _raw: bool = False) -> Any:
        """按日期区间查单票公告（DataFrame，date 升序；begin/end 均含当日，YYYY-MM-DD）。

        :param begin: 起始日期（含）
        :param end: 结束日期（含）
        :param keyword: 标题/类型正则（可空）
        :param market: 公告市场，缺省自动（按标的代码路由）；全市场语义可显式传 "cn"/"hk"
        :param _raw: True=上游原始行
        """
        kwargs: dict = {"from_date": begin, "to_date": end, "type_regex": keyword,
                        "stock_code": symbol, "limit": limit}
        if market:
            kwargs["market"] = market
        rows = self._c.call("notice.query_find", _raw=_raw, **kwargs)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def on_date(self, date: str, keyword: str = "", limit: int = 50,
                market: str = "", _raw: bool = False) -> Any:
        """指定日期的全市场公告（DataFrame；date 格式 YYYY-MM-DD；cn/hk）。

        :param date: 日期（YYYY-MM-DD）
        :param market: 公告市场，缺省自动（=cn）；港股显式传 "hk"
        :param _raw: True=上游原始行
        """
        kwargs: dict = {"date": date, "type_regex": keyword, "limit": limit}
        if market:
            kwargs["market"] = market
        rows = self._c.call("notice.query_on_date", _raw=_raw, **kwargs)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def read_text(self, symbol: str, date: str, url: str = "",
                  full: bool = False) -> Any:
        """公告正文读取（纯读；未就绪不入队，不触发入队/生成）。

        :param symbol: 6 位 A 股码 / 港股 5 位码（date+空 url 时用于定位 PDF）
        :param date: 披露日 YYYY-MM-DD；传 url 时可传空串
        :param url: PDF 链接，非空时直读（跳过 sym+date 定位）
        :param full: false=前 4000 字预览，true=全量正文
        :returns: MAP · ok/status/text/text_chars/text_truncated/file_key/
            source_url/announce_date/title/error/note（11 字段）
        """
        return self._c.call("notice.read_text", sym=symbol, date=date,
                            url=url, full=full)

    def has_buyback(self, symbol: str, window: str = "6m") -> bool:
        """窗口内是否有回购公告。"""
        return bool(self._c.call("notice.signal_has_buyback", sym=symbol,
                                 window=str(_window_days(window))))

    def has_reduction(self, symbol: str, window: str = "6m") -> bool:
        """窗口内是否有减持公告。"""
        return bool(self._c.call("notice.signal_has_reduction", sym=symbol,
                                 window=str(_window_days(window))))

    def categories(self) -> Any:
        """公告类目键列表（14 类目，含简繁对照；配合 category_regex / type_regex 参数）。

        返回注解用 Any：裸 ``list`` 在类体内会被同名方法 ``list`` 遮蔽。
        """
        return list(self._c.call("notice.type_keys"))

    def category_regex(self, key: str) -> str:
        """公告类目键 → 匹配正则（未知键原样透传，可直接传自定义正则）。

        :param key: 类目键（见 ``categories()`` 返回），或任意自定义正则
        """
        return str(self._c.call("notice.type_regex", key=key))


class FilingsApi(_Api):
    """定期报告清单。kind = all | annual | semi | quarter。"""

    def list(self, symbol: str, kind: str = "all", limit: int = 10) -> Any:
        """定期报告列表（报告期/标题/PDF 链接）。

        :param kind: 报告类型：``all | annual | semi | quarter``
        """
        return _out(self._c.call("filings.query", sym=symbol, type_key=kind, limit=limit))

    def latest(self, symbol: str, kind: str = "all") -> Any:
        """最新一条定期报告。

        :param kind: 报告类型：``all | annual | semi | quarter``
        """
        return self._c.call("filings.latest", sym=symbol, type_key=kind)


class PdfDocApi(_Api):
    """公告 PDF 全文库（检索 / 正文 / 财报 markdown / 状态）。

    写面（submit/ensure 触发抓取任务）未暴露——纯读面；公告口径的薄封装见
    ``cli.notice.read_text``。短文走 pdftotext 预览，财报走 markdown/经营评述。
    """

    def search(self, stock_code: str = "", title: str = "",
               announce_date_from: str = "", announce_date_to: str = "",
               status: str = "", kind: str = "", limit: int = 20,
               skip: int = 0, _raw: bool = False) -> Any:
        """检索 PDF 文档元数据（不含正文；按更新时间降序）。

        :param stock_code: 6 位裸码（可空=全库）
        :param title: 标题子串
        :param announce_date_from: 披露日起（YYYY-MM-DD）
        :param announce_date_to: 披露日止（YYYY-MM-DD）
        :param status: ``ready | pending | fetched | failed | converting``
        :param kind: 文档类型
        """
        opts: dict = {"limit": limit, "skip": skip}
        if stock_code:
            opts["stock_code"] = stock_code
        if title:
            opts["title"] = title
        if announce_date_from:
            opts["announce_date_from"] = announce_date_from
        if announce_date_to:
            opts["announce_date_to"] = announce_date_to
        if status:
            opts["status"] = status
        if kind:
            opts["kind"] = kind
        return _out(self._c.call("pdf_doc.search", opts=opts, _raw=_raw), raw=_raw)

    def read_text(self, file_key: str = "", source_url: str = "") -> Any:
        """读 PDF 提取正文（前 4000 字预览；纯读，未就绪不入队）。

        :param file_key: 文档键；与 source_url 至少给一个
        :returns: MAP · ok/status/text/text_truncated/file_key/source_url
            （未就绪含 error/note，note 引导改走 read_markdown）
        """
        return self._c.call("pdf_doc.read_text", file_key=file_key,
                            source_url=source_url)

    def read_markdown(self, file_key: str = "", source_url: str = "",
                      stock_code: str = "", period: str = "") -> Any:
        """读财报 markdown 挂接 / 经营评述。

        :param file_key: 文档键；与 source_url/stock_code 至少给一个
        :param source_url: 原文链接
        :param stock_code: 6 位裸码（定期报告传 stock_code+period 优先命中经营评述）
        :param period: 报告期（如 ``2024``）
        """
        return self._c.call("pdf_doc.read_markdown", file_key=file_key,
                            source_url=source_url, stock_code=stock_code,
                            period=period)

    def status(self, file_key: str = "", source_url: str = "") -> Any:
        """文档转换状态（status/convert_policy/kind/has_markdown/task）。

        :param file_key: 文档键；与 source_url 至少给一个
        """
        return self._c.call("pdf_doc.status", file_key=file_key,
                            source_url=source_url)

    def find_by_url(self, url: str) -> Any:
        """按原文链接定位文档行（无则 None）。

        :param url: 公告 PDF 原文链接
        """
        return self._c.call("pdf_doc.find_by_url", url=url)

    def find_by_key(self, file_key: str) -> Any:
        """按文档键定位文档行（无则 None）。

        :param file_key: 文档键（``search`` 返回行的 file_key 字段）
        """
        return self._c.call("pdf_doc.find_by_key", file_key=file_key)


class ForecastApi(_Api):
    """业绩预告 / 快报 / 披露日历（正式报表发布前的披露文件结构化）。"""

    def yjyg(self, symbol: str, limit: int = 8) -> Any:
        """业绩预告历史（净利/扣非/营收区间 + 同比 + 修正轨迹）。"""
        return _out(self._c.call("forecast.yjyg_rows", sym=symbol, limit=limit))

    def yjyg_latest(self, symbol: str) -> Any:
        """最新业绩预告。"""
        return self._c.call("forecast.yjyg_latest", sym=symbol)

    def yjkb(self, symbol: str, limit: int = 8) -> Any:
        """业绩快报历史。"""
        return _out(self._c.call("forecast.yjkb_rows", sym=symbol, limit=limit))

    def yjkb_latest(self, symbol: str) -> Any:
        """最新业绩快报。"""
        return self._c.call("forecast.yjkb_latest", sym=symbol)

    def disclosure_history(self, symbol: str, limit: int = 8) -> Any:
        """历史财报预约披露（报告期/计划披露日/实际日）。"""
        return _out(self._c.call("forecast.disclosure_rows", sym=symbol, limit=limit))

    def next_disclosure(self, symbol: str) -> Any:
        """下次财报预约披露。"""
        return self._c.call("forecast.disclosure_next", sym=symbol)


class WorkoutApi(_Api):
    """契约套利条款事件（要约收购/换股吸收合并/现金选择权等，披露原文提取）。

    ``board()`` 返回统一信封（``data`` = {deals DataFrame, quotes DataFrame}、
    ``as_of`` 为快照日）；``query()`` 返回单票规范化条款 DataFrame。
    价格为披露口径（公告对价/现价，元）；现价 < 公告对价的折价窗口由调用方
    自行判定，SDK 不内置收益测算（算法放工具仓）。同业数据商暂无对应接口，
    属平台独有面。
    """

    def board(self) -> Any:
        """进行中契约套利看板（信封：data.deals / data.quotes）。"""
        res = self._c.call("workout.board")
        if not isinstance(res, dict):
            return res
        data = dict(res)
        as_of = str(data.pop("as_of", "") or "")
        for k in ("deals", "quotes"):
            if isinstance(data.get(k), list):
                data[k] = _out(data[k])
        return _envelope(True, data, as_of=as_of)

    def query(self, symbol: str) -> Any:
        """单票契约套利条款（规范化条款行）。"""
        return _out(self._c.call("workout.query", sym=symbol))


class DividendApi(_Api):
    """分红。DPS 单位=元/股；股息率/派息率为小数（0.0396 = 3.96%）。

    除下方动宾化方法外，目录内全部 ``bonus.*`` 函数（含质量筛选器
    ``screen_quality`` / ``screen_high_yield`` / ``screen_undervalued_yield``…）
    经属性直达，如 ``cli.dividend.screen_quality("600519")``。
    """

    # 常用筛选器提为显式方法（docstring 在 IDE 可见；底层合同与目录一致）
    def screen_quality(self, symbol: str, min_yield: float | None = None,
                       payout_min: float | None = None,
                       payout_max: float | None = None, _raw: bool = False) -> Any:
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
        return _out(self._c.call("bonus.screen_quality", **kw, _raw=_raw), raw=_raw)

    def screen_high_yield(self, symbol: str, min_yield: float | None = None,
                          _raw: bool = False) -> Any:
        """高股息（min_yield 为小数，如 0.04 = 4%）。

        :param min_yield: 股息率门槛（小数；缺省=目录默认阈值）
        """
        kw: dict[str, Any] = {"sym": symbol}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        return _out(self._c.call("bonus.screen_high_yield", **kw, _raw=_raw), raw=_raw)

    def screen_undervalued_yield(self, symbol: str, min_yield: float | None = None,
                                 min_pct: float | None = None, _raw: bool = False) -> Any:
        """低估 + 高股息（min_yield 为小数；min_pct 为低估值百分位门槛）。

        :param min_yield: 股息率门槛（小数；缺省=目录默认阈值）
        :param min_pct: 估值分位门槛（0~1 小数，如 0.3=只看分位后 30%）
        """
        kw: dict[str, Any] = {"sym": symbol}
        if min_yield is not None:
            kw["min_yield"] = min_yield
        if min_pct is not None:
            kw["min_pct"] = min_pct
        return _out(self._c.call("bonus.screen_undervalued_yield", **kw, _raw=_raw), raw=_raw)

    def history(self, symbol: str, limit: int | None = None,
                begin: str | None = None, end: str | None = None,
                _raw: bool = False) -> Any:
        """分红历史明细 → DataFrame（ex_date 升序；dps=元/股、payout_ratio=小数）。

        字段：announce/ex_date/pay/dps/total/content/sas/payout_ratio/bonus_share/
        record_date（与目录 returns 契约一致）。

        :param limit: 条数，默认 20；区间查询时默认取 max_limit（上限 10000）
        :param begin: 起始日期（含，YYYY-MM-DD，按除权日），须与 end 同时提供；上限 5 年
        :param end: 结束日期（含）
        :param _raw: True=上游原始行（跳过规范化/换算）
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
            out = _per_symbol(rows, lambda r: _sort_rows_by_date(
                _filter_by_date(r, begin, end, "ex_div", fetch), key="ex_div"))
            return _out(out, raw=_raw)
        limit = 20 if limit is None else limit
        out = _per_symbol(self._c.call("bonus.query_list", sym=symbol, limit=limit,
                                       _raw=_raw),
                          lambda r: _sort_rows_by_date(r, key="ex_div"))
        return _out(out, raw=_raw)

    def last(self, symbol: str, _raw: bool = False) -> Any:
        """最近一次分红（dict，无数据返回 None），字段与 ``history`` 列一致。

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

    # ---- 收息场景闭环（sys/income，与 web 收息佬 / wm-income 技能共享评分 SoT）----

    def rating(self, top_n: int = 20, grade: str | None = None,
               industry: str | None = None, min_yield: float | None = None,
               gates: bool = True, *, _raw: bool = False) -> Any:
        """全市场收息排行 → 信封 ``{ok, as_of, data.rows, meta}``。

        排序 = 股息分（0.6×TTM + 0.4×近3年最低，**复合排序分，不是股息率**）降序，
        过资格门块在前、未过块沉底。每行含四维 ``score``（total/grade/dimensions/
        flags）与 ``dividend_score``/``gate_pass``；``meta.facets_industries`` 是
        全行业计数全集（改选行业过滤用）。

        :param top_n: 返回条数（默认 20，上限 100）
        :param grade: 档位过滤 ``strong``(≥75)/``good``(≥60)/``watch``(≥45)/``avoid``
        :param industry: 行业过滤——``industry.S48`` / ``S48`` / 申万一级中文名（如 "银行"）
        :param min_yield: TTM 股息率下限（小数，0.04 = 4%）
        :param gates: 资格门开关（默认 True；False 连未过门行一起看）
        """
        kw: dict[str, Any] = {"top_n": int(top_n), "gates": bool(gates)}
        if grade:
            kw["grade"] = str(grade)
        if industry:
            kw["industry"] = str(industry)
        if min_yield is not None:
            kw["min_yield"] = float(min_yield)
        res = self._c.call("income.rating_rows", **kw, _raw=True)
        if not isinstance(res, dict):
            return res if _raw else _out(res, raw=_raw)
        if res.get("error") == "COLD_CACHE":
            # 榜单 cron 未就绪：显式 miss，不静默给空榜（勿现场重算全市场评分）
            return _envelope(False, {}, as_of=str(res.get("asof") or ""),
                             cache="miss", error="COLD_CACHE",
                             message=res.get("message"), note=res.get("note"))
        return res if _raw else _envelope(
            bool(res.get("ok")), res,
            as_of=str(res.get("asof") or ""),
            universe=res.get("universe"), after_filter=res.get("after_filter"),
            missing_slices=res.get("missing_slices"),
            floor_degraded=res.get("floor_degraded"),
            filters=res.get("filters"), note=res.get("note"))

    def diagnose(self, symbols: str | list[str] | tuple[str, ...],
                 include_history: bool = False, *, _raw: bool = False) -> Any:
        """收息诊断（原生批量）→ 信封 ``{ok, data.items, meta}``。

        每票回四维评分逐项解释（``score.parts``）、静态下限双腿复原
        （``floor_explain``，残差 ``gate_uncertain`` 如实标注）、榜内位置
        （``rank``）与十年国债参照。``flags`` 硬修正必须透传不静默：
        payout_danger / decaying_high_yield / verify_data / floor_blind。

        :param symbols: 单码或代码数组——原生批量一次调用，勿逐票循环
        :param include_history: True 才逐票带分红史+方案（deep 档；批量不要开，
            逐票读贵）
        """
        syms = [symbols] if isinstance(symbols, str) else list(symbols)
        canon = [self._c._canon_symbol(str(s)) for s in syms]
        res = self._c.call("income.diagnose", symbols=canon,
                           include_history=bool(include_history), _raw=True)
        if not isinstance(res, dict):
            return res if _raw else _out(res, raw=_raw)
        return res if _raw else _envelope(
            bool(res.get("ok")), res,
            count=res.get("count"), include_history=res.get("include_history"),
            note=res.get("note"))

    def calendar(self, cal_from: str | None = None, cal_to: str | None = None,
                 codes: list[str] | None = None, *, _raw: bool = False) -> Any:
        """分红日历 → 信封 ``{ok, data.events, data.stocks, meta}``。

        一个事件文档含公告/登记/除息/到账四个日期，窗口内任一命中即返回；
        ``stocks`` 为名称/股息率/市值 enrich（股息率小数）。预告行（无确定
        除息日）不入库。

        :param cal_from: 起始日 YYYY-MM-DD（缺省当月 1 日）
        :param cal_to: 截止日 YYYY-MM-DD（缺省当月末）
        :param codes: 可选代码过滤
        """
        kw: dict[str, Any] = {}
        if cal_from:
            kw["cal_from"] = str(cal_from)
        if cal_to:
            kw["cal_to"] = str(cal_to)
        if codes:
            kw["cal_codes"] = [self._c._canon_symbol(str(s)) for s in codes]
        res = self._c.call("income.calendar_events", **kw, _raw=True)
        if not isinstance(res, dict):
            return res if _raw else _out(res, raw=_raw)
        return res if _raw else _envelope(
            bool(res.get("ok")), res,
            count=res.get("count"), schema=res.get("schema"), note=res.get("note"))

    def decomp(self, symbols: str | list[str] | tuple[str, ...],
               years: int = 10, *, _raw: bool = False) -> Any:
        """N 年持有收益拆解（≤10 票批量）→ 信封 ``{ok, data.items, meta}``。

        口径：总收益（hfq 后复权，含分红再投）− 价格收益（nr 不复权）= 股息
        贡献（差值口径，含再投效应，非精确现金分红率）；全部小数。每票带
        ``monthly`` 月末累计序列（close_nr/close_hfq/yield_ttm）与 ``yearly``
        逐年表、EPS×PE 归因；``ok=false`` 为 K 线覆盖不足（次新股）如实呈现。

        :param symbols: 单码或代码数组（≤10，超出截断并标 ``truncated``）
        :param years: 持有年限 3/5/10（默认 10）
        """
        syms = [symbols] if isinstance(symbols, str) else list(symbols)
        canon = [self._c._canon_symbol(str(s)) for s in syms]
        res = self._c.call("income.decomp", symbols=canon, years=int(years),
                           _raw=True)
        if not isinstance(res, dict):
            return res if _raw else _out(res, raw=_raw)
        return res if _raw else _envelope(
            bool(res.get("ok")), res,
            years=res.get("years"), count=res.get("count"),
            mode=res.get("mode"), truncated=res.get("truncated"),
            note=res.get("note"))


# ---------------------------------------------------------------- 参考 reference
class InfoApi(_Api):
    """公司档案与参考信息。

    ``profile`` 返回 10 字段档案摘要（2.0 扩列：全称/英文名/一级行业/上市板块/
    经营范围）。单个 undefined variable 会让整包 eval 直接 HTTP 400，故：
    ①按市场静态排除已知不可用码；②对未预知的缺码，捕获上游错误后**自动剔除
    该码重试一次**（实例级记忆，同 Client 生命周期只降一次）——保证返回键集合
    在各市场一致（缺的字段显式 None）。
    """

    _PROFILE_CODES = ["$NAME", "$ORG_FULLNAME", "$NAMEEN", "$INDUSTRY_CUR_1",
                      "$INDUSTRY_CUR", "$STYLE_INDUSTRY", "$ORG_ORGTYPE",
                      "$ORG_LISTINGDATE", "$LISTING_BOARD", "$ORG_BUSINESSSCOPE"]
    _PROFILE_KEYS = ["name", "full_name", "name_en", "industry_l1", "industry",
                     "style_industry", "org_type", "listing_date", "listing_board",
                     "business_scope"]
    # 实测 2026-11-14：cn/hk 全码可用（hk 的 $STYLE_INDUSTRY 返回 None）；
    # us 仅 $STYLE_INDUSTRY 为 undefined variable，静态排除。
    _PROFILE_SKIP_BY_MARKET = {"us": {"$STYLE_INDUSTRY"}}

    def __init__(self, client: "Client"):
        super().__init__(client)
        # 实例级缺码记忆：{market: {code}}——一次探测，后续调用零重试
        self._dynamic_skip: dict[str, set[str]] = {}

    def profile(self, symbol: str) -> dict:
        """公司档案摘要（10 字段，缺码字段显式 None）。

        键集合：``name/full_name/name_en/industry_l1/industry/style_industry/
        org_type/listing_date/listing_board/business_scope``，各市场一致。
        美股无 ``$STYLE_INDUSTRY``（静态排除）；其它市场若存在未预知缺码，
        自动剔除重试一次并记忆（同 Client 生命周期只降一次）。
        """
        market = getattr(self._c, "market", "cn")
        skip = set(self._PROFILE_SKIP_BY_MARKET.get(market, set())) \
            | self._dynamic_skip.setdefault(market, set())
        for attempt in range(2):  # 最多一次缺码降级重试
            pairs = [(k, c) for k, c in zip(self._PROFILE_KEYS, self._PROFILE_CODES)
                     if c not in skip]
            body = ", ".join(f'"{k}": {c}' for k, c in pairs)
            try:
                out = self._c.eval_result(f"return {{{body}}}", symbol=symbol) or {}
                break
            except ServerError as e:
                m = re.search(r'undefined variable "(\$?[A-Za-z_]\w*)"', str(e))
                if m is None or attempt == 1:
                    raise
                bad = m.group(1).upper()
                if not bad.startswith("$"):
                    bad = f"${bad}"
                self._dynamic_skip.setdefault(market, set()).add(bad)
                skip.add(bad)
        # 上游正常返回 MAP；非 MAP 时按无数据处理，仍保持 dict 返回契约
        values = out if isinstance(out, dict) else {}
        selected = {k for k, _ in pairs}
        # 被市场排除的字段显式置 None：不依赖「eval 里恰好没写」这一隐式保证
        return {k: (values.get(k) if k in selected else None)
                for k in self._PROFILE_KEYS}


class EquityApi(_Api):
    """股东治理与股本——十大股东/质押/解禁/机构/高管/回购/重组/担保/诉讼。

    披露原值直采；比例字段（*_ratio/*_tsr/hold_ratio 等）由百分数口径换算为
    **小数**（0.0522 = 5.22%，换算字段清单见目录 units 声明）；持股数=股、
    金额=元。市场级质押三件套（pledge_market/industry/org）不传标的；
    ``*_at`` 变体按报告期取数（annual 如 2024、sampling 如 "Q4"）。
    目录内全部 ``equity.*`` 函数（含 fmt_* 规范化工具）经属性直达。
    """

    # ---- 股东 ----
    def query_holder10(self, symbol: str) -> Any:
        """最新一期十大股东（holder_name/hold_num/hold_num_ratio）。"""
        return _out(self._c.call("equity.query_holder10", sym=symbol))

    def query_holdernum(self, symbol: str) -> Any:
        """最新股东户数（end_date/hold_focus/avg_hold_amt 单行）。"""
        return self._c.call("equity.query_holdernum", sym=symbol)

    # ---- 质押 ----
    def query_pledge_detail(self, symbol: str, limit: int = 20) -> Any:
        """主要股东质押明细（质押家数/数量/比例/状态）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_pledge_detail", sym=symbol,limit=limit, ))

    def query_pledge_summary(self, symbol: str, limit: int = 20) -> Any:
        """公司质押比例时序（trade_date/pledge_ratio/质押股数/质押市值）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_pledge_summary", sym=symbol,limit=limit, ))

    def query_pledge_market(self, limit: int = 20) -> Any:
        """市场整体质押（全市场两融式时序，不传标的）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_pledge_market", limit=limit))

    def query_pledge_industry(self, limit: int = 20) -> Any:
        """行业质押比例（全市场按行业，不传标的）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_pledge_industry", limit=limit))

    def query_pledge_org(self, limit: int = 20) -> Any:
        """质押机构分布（质权人类型维度，不传标的）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_pledge_org", limit=limit))

    # ---- 机构 ----
    def query_institution_detail(self, symbol: str, limit: int = 20) -> Any:
        """机构持股明细（机构 × 报告期持股数/市值/占比）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_institution_detail", sym=symbol,limit=limit, ))

    def query_institution_summary(self, symbol: str, limit: int = 20) -> Any:
        """机构持仓占比时序（机构家数/合计占比/环比变动）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_institution_summary", sym=symbol,limit=limit, ))

    def query_hgt(self, symbol: str, limit: int = 20) -> Any:
        """沪港通持股（机构/持股数/市值/占比变动）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_hgt", sym=symbol, limit=limit))

    def query_national_team(self, symbol: str, limit: int = 20) -> Any:
        """国家队持股（证券主体 × 报告期持股占比）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_national_team", sym=symbol,limit=limit, ))

    # ---- 治理事件 ----
    def query_release(self, symbol: str, limit: int = 20) -> Any:
        """限售解禁日程（解禁日期/数量/占比/类型）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_release", sym=symbol, limit=limit))

    def query_buyback_plan(self, symbol: str, limit: int = 20) -> Any:
        """回购方案全览（进度/价格上限/金额上限/起始日）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_buyback_plan", sym=symbol,limit=limit, ))

    def query_buyback_detail(self, symbol: str) -> Any:
        """回购执行明细单行（已回购股数/金额/公告日）。"""
        return self._c.call("equity.query_buyback_detail", sym=symbol)

    def buyback_snapshot(self, symbol: str) -> Any:
        """回购六口径快照（exec/plan × 近1年/累计 × 含/不含注销式）。

        :param symbol: 6 位 A 股码 / 港股 5 位码
        :returns: MAP · 元/原币；无数据源字段为 None（不伪造 0）；
            A股 plan_*/cancel_* 齐全，港股仅 exec_*（明细逐日精确加总，原币直加不换汇率）
        """
        return self._c.call("buyback.snapshot", sym=symbol)

    def query_reorg(self, symbol: str, limit: int = 20) -> Any:
        """并购重组（进度/交易金额/公告日）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_reorg", sym=symbol, limit=limit))

    def query_related_trade(self, symbol: str, limit: int = 20) -> Any:
        """关联交易（关联方/交易金额/公告日）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_related_trade", sym=symbol,limit=limit, ))

    def query_concert(self, symbol: str, limit: int = 20) -> Any:
        """一致行动人（组合名称/合计持股比例）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_concert", sym=symbol, limit=limit))

    def query_guarantee(self, symbol: str, limit: int = 20) -> Any:
        """对外担保（担保方/金额/是否履行完毕）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_guarantee", sym=symbol, limit=limit))

    def query_litigation(self, symbol: str, limit: int = 20) -> Any:
        """诉讼记录（案名/涉案金额/原告/被告）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_litigation", sym=symbol, limit=limit))

    def query_violation(self, symbol: str, limit: int = 20) -> Any:
        """违规处罚（类型/处分/罚款金额）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("equity.query_violation", sym=symbol, limit=limit))

    # ---- 高管与股本 ----
    def query_executives(self, symbol: str) -> Any:
        """高管名册（姓名/职务/薪酬/持股）。"""
        return _out(self._c.call("equity.query_executives", sym=symbol))

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

    def query_ccass(self, symbol: str, limit: int = 20) -> Any:
        """港股 CCASS 经纪持仓（经纪商/持股数/占发行股比）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("intl.query_ccass", sym=symbol, limit=limit))

    def query_shareholders(self, symbol: str, limit: int = 20) -> Any:
        """港股主要股东/董事权益（股东/持股数/占总股比）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("intl.query_shareholders", sym=symbol, limit=limit))

    def query_org_rating(self, symbol: str, limit: int = 20) -> Any:
        """港股机构评级（机构/评级/目标价，披露币种）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("intl.query_org_rating", sym=symbol, limit=limit))

    def query_profit_forecast(self, symbol: str, limit: int = 20) -> Any:
        """港股盈利预测（披露原文中文键：财政年度/纯利/每股盈利等）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("intl.query_profit_forecast", sym=symbol,limit=limit, ))

    def query_sellshort(self, symbol: str, limit: int = 20) -> Any:
        """港美沽空（沽空量/占比，shares=股）。

        :param limit: 条数，默认 20
        """
        return _out(self._c.call("intl.query_sellshort", sym=symbol, limit=limit))

    def issue_info(self, symbol: str) -> Any:
        """美股发行信息快照（发行价/数量/日期，以披露源为准）。"""
        return self._c.call("intl.issue_info", sym=symbol)


class MacroApi(_Api):
    """宏观与行业时序。

    覆盖宏观指标时序/as-of/采样频率、中债收益率、行业情报单值。2.0 单位标准化：
    units.yaml 台账登记码默认换算到基础单位（``$RE_*`` 亿元→元、``$ROC_TTM`` 族
    百分数→小数）；``$CPI`` 等价格指数=点（index_point，不换算）、``$GDP``/``$M2``
    等流量存量=元；bond_curve 收益率为小数（0.0168 = 1.68%）。
    指标码层等价物：``cli.indicator.get(sym, "$CPI")`` 与 ``asof`` 同源
    （同一台账换算管线）。时序 series 按 sas 升序（旧→新，2.0 标准）。
    """

    def query(self, code: str, n: int = 6) -> Any:
        """宏观指标时序（信封：data.series 为 DataFrame，sas 升序）。

        :param code: 指标码或名称（``$CPI`` / ``cpi`` 均可，服务端归一）
        :param n: 期数（1–48）
        """
        res = self._c.call("macro.query", code=code, n=n)
        if not isinstance(res, dict):
            return res
        series = res.get("series") or []
        latest = ledger_convert(code, res.get("latest"))
        if isinstance(series, list) and series and isinstance(series[0], dict):
            for row in series:
                row["value"] = ledger_convert(code, row.get("value"))
            series = _out(_sort_rows_by_date(series, key="sas"))
        return _envelope(True, {"frequency": res.get("frequency"),
                                "periods": res.get("periods"),
                                "latest": latest, "series": series})

    def asof(self, code: str) -> Any:
        """宏观指标最新一期值（无数据返回 None；人口类序列勿用）。

        台账登记码已换算到基础单位（如 ``$RE_INVEST`` 亿元→元）。
        """
        return ledger_convert(code, self._c.call("macro.asof", code=code))

    def spots(self, code: str, n: int = 4) -> Any:
        """宏观指标原生采样期点（升序，如 ["2026:M08", "2026:M09"]）。"""
        spots = self._c.call("macro.spots", code=code, n=n)
        if isinstance(spots, list):
            spots = sorted(str(s) for s in spots)
        return spots

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


class EtfApi(_Api):
    """ETF 九视图读取（组合门面；读已发布的 skillhub 脚本，非目录函数）。

    与目录函数不同，本类经 ``eval_result`` 读脚本：走同一取数端点、同价计费，
    不省 EC，也不额外费 EC。单位与量级守护经 units.yaml ``facades."etf.views"``
    声明接入全库单一口径（2.0：占比/涨幅/折溢价换算为小数、规模亿元→元、
    份额亿份→份），本地三道护栏（转义 / 数值守护 / 错误分类）见 ``_etf``；
    返回统一信封 ``{ok, as_of, data, meta}``。

    ``asset``/``rank`` 是 SDK 方法名，内部映射到 script view ``fund_asset``/
    ``etf_rank``；禁止把方法名当 view 直传（脚本只认后两者）。
    ``mode`` 仅 nav 视图消费：``series`` 展开近 N 期净值序列，``latest`` 取最新；
    其余视图忽略 mode（script 分发器只对 nav_build 传 mode）。
    """

    _ETF_VIEWS = frozenset({
        "card", "nav", "share", "div", "portfolio", "profile", "premium", "asset", "rank",
    })
    _VIEW_FOR_METHOD = {"asset": "fund_asset", "rank": "etf_rank"}
    _ETF_MODES = frozenset({"latest", "series"})
    _LIMIT_MIN, _LIMIT_MAX = 1, 500

    @staticmethod
    def _num(value: Any, field: str) -> float | None:
        """取数值字段；非数值返回 None（守护跳过，不误判 0）。"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @classmethod
    def _guard_etf(cls, result: Any, view: str) -> Any:
        """护栏 2：量级/不变量守护（声明见 units.yaml facades."etf.views"）。

        2.0 单位标准化：载荷先经 ``apply_facade_units`` 换算到基础单位
        （占比/涨幅/折溢价 %→小数、规模亿元→元、份额亿份→份），守护在**换算后**
        数值上进行。阈值取宽区间，只挡量级错，不误伤真实极端行情。
        """
        if not isinstance(result, dict):
            raise DataError(f"etf.{view} 返回非 MAP：{type(result).__name__}", code="response")
        if not result.get("ok", False):
            err = str(result.get("error") or "")
            raise DataError(
                f"etf.{view} 无数据或被拒：{err} {result.get('message', '')}；"
                f"{result.get('hint', '')}", code="range")
        result = apply_facade_units("etf.views", result)
        # 区间涨幅/折溢价（小数）：合理 [-1, 10]（极端杠杆/拆分另案）。
        for key in ("chg_w1", "chg_m1", "chg_m3", "premium_pct", "premium_mean"):
            v = cls._num(result.get(key), key)
            if v is not None and not -1.0 <= v <= 10.0:
                raise DataError(f"etf.{view} {key}={v} 超出合理区间 [-1,10]（小数）",
                                code="range")
        # 规模 net_asset（元）与份额 fd_share（份）：非负、上限 1e14。
        for key in ("net_asset", "fd_share"):
            raw = result.get(key)
            # nav 视图 net_asset 是 {date, 值} MAP，下探一层再校验。
            if key == "net_asset" and isinstance(raw, dict):
                raw = raw.get("net_asset")
            v = cls._num(raw, key)
            if v is not None and (v < 0 or v > 1e14):
                raise DataError(f"etf.{view} {key}={v} 非非负或超出量级上限 1e14",
                                code="range")
        # 五类资产占净值比（小数）：各自 0~1，合计不超 1（允许浮点误差 0.005）。
        if view in ("asset", "fund_asset"):
            ratios = [cls._num(result.get(k), k) for k in
                      ("stock_ratio", "bond_ratio", "cash_ratio", "other_ratio", "fund_ratio")]
            vals = [r for r in ratios if r is not None]
            for k, r in zip(("stock_ratio", "bond_ratio", "cash_ratio",
                             "other_ratio", "fund_ratio"), ratios):
                if r is not None and not 0.0 <= r <= 1.0:
                    raise DataError(f"etf.{view} {k}={r} 占净值比越界 [0,1]（小数）", code="range")
            if vals and sum(vals) > 1.005:
                raise DataError(f"etf.{view} 五类占净值比合计 {sum(vals):.4f} > 1",
                                code="invariant")
        return result

    @staticmethod
    def _classify_etf_error(exc: ApiError) -> WmshareError:
        """护栏 3：eval 的 ApiError 按语义翻译，不让调用方拿裸网关错误。"""
        code = str(getattr(exc, "code", "") or "")
        msg = str(exc)
        if any(k in code.upper() for k in ("PARAM", "ARG", "SYNTAX", "UNKNOWN_VIEW")):
            return UsageError(f"etf 调用参数错误：{msg}", code="params")
        if any(k in code.upper() for k in ("NOT_ETF", "NO_DATA", "VALIDATION")):
            return DataError(f"etf 数据/口径错误：{msg}", code="range")
        return DataError(f"etf 取数或口径异常：{msg}", code="eval")

    def _etf(self, view: str, symbol: str, mode: str = "latest",
             limit: int | None = None) -> Any:
        """护栏 1：白名单 + limit 严格校验 + json.dumps 字面量（禁裸 f-string 注入）。"""
        if view not in self._ETF_VIEWS:
            raise UsageError(f"未知 view={view!r}；可选 {sorted(self._ETF_VIEWS)}",
                             code="params")
        if mode not in self._ETF_MODES:
            raise UsageError(f"未知 mode={mode!r}；可选 {sorted(self._ETF_MODES)}",
                             code="params")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise UsageError(f"limit 必须是整数，收到 {limit!r}", code="params")
            if not self._LIMIT_MIN <= limit <= self._LIMIT_MAX:
                raise UsageError(f"limit 超出 [{self._LIMIT_MIN}, {self._LIMIT_MAX}]: {limit}",
                                 code="params")
        from wmshare.client import normalize_symbol
        sym = normalize_symbol(symbol)
        lit = json.dumps(sym, ensure_ascii=False)
        limit_lit = json.dumps(limit) if limit is not None else "nil"
        script_view = self._VIEW_FOR_METHOD.get(view, view)
        xs = [
            'xs.require("xs/skillhub/lib/init.xs")',
            f"return skhub.etf_build({lit}, {json.dumps(script_view)}, "
            f"{json.dumps(mode)}, {limit_lit})",
        ]
        try:
            result = self._c.eval_result(xs, symbol=sym, market="cn")
        except ApiError as exc:
            raise self._classify_etf_error(exc) from exc
        payload = self._guard_etf(result, view)
        # 2.0 统一信封：脚本业务字段进 data，脚本传输字段（ok/error/message/hint）剥离
        data = {k: v for k, v in payload.items()
                if k not in ("ok", "error", "message", "hint")}
        as_of = str(payload.get("date") or payload.get("asof") or "")
        return _envelope(True, data, as_of=as_of, view=view, mode=mode)

    def card(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 档案卡（信封：合并档案/净值/份额/分红；mode=latest|series）。"""
        return self._etf("card", symbol, mode)

    def nav(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 净值（信封：基金净值 + 规模 net_asset 元；mode=latest|series）。"""
        return self._etf("nav", symbol, mode)

    def share(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 份额（信封：fd_share 份；mode=latest|series）。"""
        return self._etf("share", symbol, mode)

    def div(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 分红（信封：历史分红行；mode=latest|series）。"""
        return self._etf("div", symbol, mode)

    def portfolio(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 持仓（信封：最新披露季 top10；mode=latest|series）。"""
        return self._etf("portfolio", symbol, mode)

    def profile(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 产品档案（信封：基金公司/跟踪标的/费率等；mode=latest|series）。"""
        return self._etf("profile", symbol, mode)

    def premium(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 折溢价率（信封：premium_pct 小数；mode=latest|series）。"""
        return self._etf("premium", symbol, mode)

    def asset(self, symbol: str, mode: str = "latest") -> Any:
        """ETF 资产配置（信封：五类占净值比小数 + net_asset 元；→script view fund_asset）。"""
        return self._etf("asset", symbol, mode)

    def rank(self, symbol: str, mode: str = "latest", limit: int | None = None) -> Any:
        """ETF 榜单指标（chg_w1/m1/m3、flow_20、premium_mean、net_asset；→script view etf_rank）。"""
        return self._etf("rank", symbol, mode, limit)


class ToplistApi(_Api):
    """A 股龙虎榜（交易所披露口径，日频）。

    同票多上榜原因各一行（榜单原值行合同）；率为小数、金额=元、日期=ISO。
    席位/营业部明细（top_inst）上游无落库，不提供按席位查询。
    """

    def by_date(self, trade_date: str, limit: int = 100,
                _raw: bool = False) -> Any:
        """指定交易日的全市场龙虎榜。

        :param trade_date: 交易日 YYYY-MM-DD
        :param limit: 条数上限（默认 100）
        :returns: DataFrame/行表 · date/symbol/name/close/pct_chg/
            turnover_rate/amount/amount_ratio/float_mv/seat_buy/seat_sell/
            seat_amount/net_amount/net_ratio/reason（date 升序）
        """
        rows = self._c.call("toplist.by_date", trade_date=trade_date,
                            limit=limit, _raw=_raw)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    def by_symbol(self, symbol: str, limit: int = 100,
                  _raw: bool = False) -> Any:
        """单票上榜历史（最近事件行，按日期升序）。

        :param symbol: 6 位裸码（自动拼交易所后缀）
        :param limit: 最近事件条数（默认 100）
        :returns: DataFrame/行表 · 字段与 ``by_date`` 一致
        """
        rows = self._c.call("toplist.by_symbol", sym=symbol, limit=limit,
                            _raw=_raw)
        return _out(_sort_rows_by_date(rows), raw=_raw)


class FuturesApi(_Api):
    def mapping(self, symbol: str, begin: str = "", end: str = "",
                _raw: bool = False) -> Any:
        """主力换月映射（主力连续码 → 当日实际合约；date 升序）。

        :param symbol: 主力连续码（品种.交易所，如 ``RB.SHF``）
        :param begin: 开始日期 YYYY-MM-DD（可空=全历史）
        :param end: 结束日期 YYYY-MM-DD
        :returns: DataFrame/行表 · date/symbol/mapping_symbol
            （换月事件≈每年 4-6 次；映射历史不可变，复跑走指纹缓存）
        """
        rows = self._c.call("futures.mapping", sym=symbol, begin=begin,
                            end=end, _raw=_raw)
        return _out(_sort_rows_by_date(rows), raw=_raw)

    """期货连续合约快照（27 个 ``$FUT_*`` 指标码 × 82 品种，eval 求值）。

    1.x 要「传任意 A 股代码做求值锚定 + fut_symbol 传参」的 hack 已封装：
    本门面内部固定用 cn 默认锚点求值，用户只传 ``fut_code``。**须 cn 客户端**
    （求值引擎按 A 股上下文锚定）。``fut_code`` 语法：``RB.SHF``/``cn.RB.SHF``
    （cn 商品，交易所 SHF/CZCE/DCE/GFEX/INE）或 ``global.CL``（外盘 V2 键）；
    品种白名单（74 商品 + 8 金融）由上游校验，未命中品种的报错按原样透传。

    单位为**期货原生口径**（显式豁免全库基础单位）：价格=元、量=手（期货一手
    = 合约乘数，换算成「股」无意义）、金额=万元——与交易所披露一致。

    ``freq``：``d``（默认，日频 11 字段）/ ``w``（周频 8 字段）/ ``m``（月频 8 字段）。
    """

    # CFX=中金所（IF/IH/IC/IM/T/TF/TS/TL 八个金融品种）——漏了它 8 个金融品种
    # 全不可寻址（2026-11-17 live 实测：cn.IF.CFX 在指标层可取值，但门面白名单拒）
    _CN_FUT_RE = re.compile(r"^cn\.[A-Z]{1,3}\.(SHF|CZCE|DCE|GFEX|INE|CFX)$")
    _GLOBAL_FUT_RE = re.compile(r"^global\.[A-Z]{1,4}$")
    _FREQ_CODES: dict[str, dict[str, str]] = {
        "d": {"$FUT_OPEN": "open", "$FUT_HIGH": "high", "$FUT_LOW": "low",
              "$FUT_CLOSE": "close", "$FUT_SETTLE": "settle",
              "$FUT_PRE_SETTLE": "pre_settle", "$FUT_VOLUME": "volume",
              "$FUT_AMOUNT": "amount", "$FUT_OI": "open_interest",
              "$FUT_OI_CHG": "oi_chg", "$FUT_HAS": "has_kline"},
        "w": {"$FUT_OPEN_WEEK": "open", "$FUT_HIGH_WEEK": "high",
              "$FUT_LOW_WEEK": "low", "$FUT_CLOSE_WEEK": "close",
              "$FUT_SETTLE_WEEK": "settle", "$FUT_VOLUME_WEEK": "volume",
              "$FUT_OI_WEEK": "open_interest", "$FUT_HAS_WEEK": "has_kline"},
        "m": {"$FUT_OPEN_MONTH": "open", "$FUT_HIGH_MONTH": "high",
              "$FUT_LOW_MONTH": "low", "$FUT_CLOSE_MONTH": "close",
              "$FUT_SETTLE_MONTH": "settle", "$FUT_VOLUME_MONTH": "volume",
              "$FUT_OI_MONTH": "open_interest", "$FUT_HAS_MONTH": "has_kline"},
    }
    _FREQ_ALIAS = {None: "d", "": "d", "d": "d", "day": "d", "daily": "d",
                   "w": "w", "week": "w", "weekly": "w",
                   "m": "m", "month": "m", "monthly": "m"}
    _FIELD_TO_CODE = {v: k for codes in _FREQ_CODES.values()
                      for k, v in codes.items()}

    def _normalize_fut(self, fut_code: str) -> str:
        s = str(fut_code or "").strip().upper()
        if s and "." not in s:
            raise UsageError(
                f"fut_code={fut_code!r} 缺少交易所/市场段；国内形如 \"RB.SHF\"/"
                f"\"cn.RB.SHF\"，外盘形如 \"global.CL\"", code="params")
        # 裸「品种.交易所」补 cn. 前缀（RB.SHF → cn.RB.SHF）
        if re.fullmatch(r"[A-Z]{1,3}\.(SHF|CZCE|DCE|GFEX|INE|CFX)", s):
            s = f"cn.{s}"
        if s.startswith(("CN.", "GLOBAL.")):
            s = s[:3].lower() + s[3:]  # 前缀小写约定（cn./global.），品种段大写
        if not (self._CN_FUT_RE.match(s) or self._GLOBAL_FUT_RE.match(s)):
            raise UsageError(
                f"fut_code={fut_code!r} 不合法；国内 \"cn.RB.SHF\"（SHF/CZCE/DCE/"
                "GFEX/INE）或外盘 \"global.CL\"", code="params")
        return s

    def _require_cn_client(self) -> None:
        if str(getattr(self._c, "market", "cn")).lower() != "cn":
            raise UsageError(
                "期货取数须 cn 客户端（求值引擎按 A 股上下文锚定）；"
                "Client(market=\"cn\") 重建", code="market")

    def get(self, fut_code: str, field: str = "close",
            freq: str | None = None, native: bool = False) -> Any:
        """期货连续合约单字段值（价格=元、量=手、金额=万元）。

        :param fut_code: 合约键（如 ``"RB.SHF"`` / ``"cn.RB.SHF"`` / ``"global.CL"``）
        :param field: 字段名（``close``/``volume``/``open_interest``…）或 ``$码``
            （如 ``"$FUT_SETTLE"``；传 $ 码时 freq 被忽略）
        :param freq: ``d``（默认）/ ``w`` / ``m``（field 用短名时生效）
        :param native: 期货量价已为原生口径，本参数仅为接口一致性保留
        """
        self._require_cn_client()
        code = self._normalize_fut(fut_code)
        text = str(field or "").strip()
        xs_code: str | None = None
        if text.startswith("$"):
            if self._c.catalog.metric(text) is None:
                raise CatalogError(f"未知指标 {text!r}（防编造：code 必须在指标目录内）",
                                   code="metric")
            xs_code = text
        else:
            f = self._FREQ_ALIAS.get(str(freq or "d").lower(), None)
            key = "d" if f is None else f
            mapping = self._FREQ_CODES[key]
            rev = {v: k for k, v in mapping.items()}  # 字段名 → $码（freq 域内反查）
            xs_code = rev.get(text)
            if xs_code is None:
                raise UsageError(
                    f"未知字段 {field!r}（freq={key}）；可选 {sorted(rev)} 或直接传 $码",
                    code="params")
        anchor = _DEFAULT_SYMBOLS.get("cn", "600519")
        return self._c.indicator.get(anchor, xs_code, fut_symbol=code)

    def snapshot(self, fut_code: str, freq: str = "d") -> dict:
        """期货连续合约一族字段快照（一次指标批量求值，返回 {字段: 值}）。

        :param fut_code: 合约键（同 ``get()``
        :param freq: ``d``（默认，11 字段）/ ``w`` / ``m``（各 8 字段）
        """
        self._require_cn_client()
        code = self._normalize_fut(fut_code)
        key = self._FREQ_ALIAS.get(str(freq or "d").strip().lower(), "d")
        mapping = self._FREQ_CODES[key]
        anchor = _DEFAULT_SYMBOLS.get("cn", "600519")
        values = self._c.indicator.metrics(anchor, list(mapping), fut_symbol=code)
        if not isinstance(values, dict):
            return values
        return {field: values.get(code_) for code_, field in mapping.items()}

    # bars 点数上限：eval 点读按「点 × 码」计费（2026-11-23 实测暖态 ≈8-11 EC/点·码），
    # 日频全史 ≈25 年 × 250 日 ≈ 6000 点会烧出五位数 EC——硬顶逼调用方选低频或缩窗。
    _BAR_POINT_CAPS: dict[str, int] = {"d": 3000, "w": 600, "m": 300}
    _BAR_CURSOR_FN = {"d": "ds", "w": "ws", "m": "ms"}

    def bars(self, fut_code: str, n: int | None = None, begin: str | None = None,
             end: str | None = None, freq: str | None = None,
             fields: Any = None, _raw: bool = False) -> Any:
        """期货主力连续历史K线（周期序列 × ``$FUT_*`` 点读；date 升序）。

        eval 组合面（``RANGE(cursor.*, ITER($FUT_*…))`` + ``fut.symbol`` 传参），
        与 ``kline.bars`` 同形：date 升序、DataFrame 默认、``_raw=True`` 逃生口。
        ``date`` 为周期起点口径（月=当月 1 日、周=ISO 周一、日=当日）；
        非交易日周期沿用上游口径原样返回（``has_kline`` 列可辨）。

        :param fut_code: 合约键（同 ``get()``；主力连续，非单合约）
        :param n: 取最近 n 个周期（默认 120；与 begin/end 二选一）
        :param begin: 开始日期 YYYY-MM-DD（含当日；须与 end 成对）
        :param end: 结束日期 YYYY-MM-DD（含当日）
        :param freq: ``d``（默认，11 字段）/ ``w``（8 字段）/ ``m``（8 字段）；
            长区间建议 ``m``（点数省 20 倍以上）
        :param fields: 列投影（字段名/``sas`` 列表，如 ``["date", "close"]``）
        :param _raw: True 跳过收口，返回 {sas: [...], vals: [[...]]} 原始形态
        :raises UsageError: freq 非法 / begin-end 不成对 / 点数超上限
            （d 3000 / w 600 / m 300——上游主力连续数据起点约束与成本双重要求）
        """
        self._require_cn_client()
        code = self._normalize_fut(fut_code)
        key = self._FREQ_ALIAS.get(str(freq or "d").strip().lower())
        if key is None:
            raise UsageError(
                f"futures.bars: 不支持的 freq={freq!r}；可用 None/\"d\"（日）、"
                "\"w\"（周）、\"m\"（月）", code="freq") from None
        mapping = self._FREQ_CODES[key]
        if (begin is not None) != (end is not None):
            raise UsageError("begin 与 end 需同时提供", code="range")
        if n is not None and begin is not None:
            raise UsageError("n 与 begin/end 二选一", code="range")

        today = date.today()
        if begin is not None:
            try:
                b = date.fromisoformat(str(begin)[:10])
                e = date.fromisoformat(str(end)[:10])
            except ValueError as exc:
                raise UsageError(f"begin/end 需为 YYYY-MM-DD：{exc}", code="range") from None
            if b > e:
                raise UsageError(f"begin={begin} 晚于 end={end}", code="range")
            n_points = self._periods_back(key, b, today)
        else:
            try:
                n_points = 120 if n is None else int(n)
            except (TypeError, ValueError) as exc:
                raise UsageError(f"n 需为正整数：{n!r}", code="params") from None
        cap = self._BAR_POINT_CAPS[key]
        if n_points < 1:
            raise UsageError(f"点数需 ≥1（freq={key}）", code="range")
        if n_points > cap:
            raise UsageError(
                f"futures.bars: freq={key} 点数 {n_points} 超上限 {cap}（成本按点×码计，"
                f"2026-11-23 实测 ≈8-11 EC/点·码）；请缩小区间或改用低频 freq",
                code="range")

        codes = ", ".join(mapping)
        cur = self._BAR_CURSOR_FN[key]
        xs = (f'pts := cursor.{cur}({n_points}, "now")\n'
              f'vals := RANGE(pts, ITER({codes}))\n'
              'return {"sas": pts, "vals": vals}')
        anchor = _DEFAULT_SYMBOLS.get("cn", "600519")
        result = self._c.eval_result(xs, symbol=anchor, args={"fut.symbol": code})
        if _raw:
            return result
        if not (isinstance(result, dict) and isinstance(result.get("sas"), list)
                and isinstance(result.get("vals"), list)):
            raise DataError(
                f"futures.bars: 上游返回形态异常（期望 sas/vals 两列，得到 "
                f"{type(result).__name__}）", code="response")
        sas_list: list = result["sas"]
        vals: list = result["vals"]
        if len(sas_list) != len(vals):
            raise DataError(
                f"futures.bars: sas/vals 行数不一致（{len(sas_list)} vs {len(vals)}）",
                code="response")
        rows: list[dict[str, Any]] = []
        code_names = list(mapping)
        for sas, point in zip(sas_list, vals):
            row: dict[str, Any] = {"sas": sas, "date": _sas_to_iso(sas)}
            for i, name in enumerate(code_names):
                row[mapping[code_names[i]]] = point[i] if i < len(point) else None
            rows.append(row)
        rows.reverse()  # cursor 新→旧 → 2.0 契约 date 升序
        if begin is not None:
            b_iso, e_iso = b.isoformat(), e.isoformat()
            rows = [r for r in rows if b_iso <= str(r["date"])[:10] <= e_iso]
        return _out(rows, raw=_raw, _fields=fields)

    @staticmethod
    def _periods_back(key: str, begin: "date", today: "date") -> int:
        """begin → 今天的周期数（含缓冲 2 期；begin/end 过滤在客户端收口）。"""
        days = max(0, (today - begin).days)
        if key == "d":
            return days + 2
        if key == "w":
            return days // 7 + 2
        return (today.year - begin.year) * 12 + (today.month - begin.month) + 2


# 组合接口：跨多个目录函数的研究级封装（取数 → 规则 → 事实包 → 成稿/出图）。
# 不登记 FRIENDLY_INDEX（那张表是「核心接口 ↔ 底层目录函数」的一一映射）；
# 文档在 docs/API.md 的「组合接口」小节单独成文。
COMPOSITE_METHODS: dict[str, set[str]] = {
    "cbond": {"daily", "article", "figures"},
    "backtest": {"run"},
    "statements": {"balance", "income", "cashflow", "indicators"},
    "etf": {"card", "nav", "share", "div", "portfolio", "profile", "premium", "asset", "rank"},
    # 2.5：收息诊断（索引读+四维评分+静态下限复原+榜内 rank 多源编排，真组合；
    # rating/calendar/decomp 是 income.* 直通面，在 FRIENDLY_INDEX 登记）
    "dividend": {"diagnose"},
}

FRIENDLY_NAMESPACES: dict[str, type[_Api]] = {
    "kline": KlineApi,
    "screener": ScreenerApi,
    "moneyflow": MoneyflowApi,
    "margin": MarginApi,
    "toplist": ToplistApi,
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
    "pdf_doc": PdfDocApi,
    "forecast": ForecastApi,
    "workout": WorkoutApi,
    "dividend": DividendApi,
    "info": InfoApi,
    "equity": EquityApi,
    "intl": IntlApi,
    "macro": MacroApi,
    "backtest": BacktestApi,
    "etf": EtfApi,
    "futures": FuturesApi,
    "calendar": CalendarApi,
}

# 文档索引用注册表：(category, namespace, method, cn, 底层函数)
FRIENDLY_INDEX: list[tuple[str, str, str, str, str]] = [
    ("market", "kline", "bars", "日 K 序列", "kline.query_bars[_adj]"),
    ("market", "kline", "last", "最新一根日 K", "kline.query_last"),
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
    ("market", "screener", "query", "全市场条件选股", "组合接口（宿主 INDEX_QUERY_SPEC）"),
    ("market", "margin", "query", "个股融资融券历史", "margin.query"),
    ("market", "margin", "latest", "最新两融单行", "margin.latest"),
    ("market", "margin", "market_summary", "市场级两融汇总", "margin.market_summary"),
    ("market", "margin", "universe", "两融标的名单", "margin.universe"),
    ("market", "calendar", "days", "交易日历区间", "calendar.days"),
    ("market", "calendar", "is_open", "是否交易日", "calendar.is_open"),
    ("market", "calendar", "next", "之后 N 个交易日", "calendar.next"),
    ("market", "cbond", "board", "转债全市场面板", "cbond.board"),
    ("market", "cbond", "latest_quotes", "转债最新快照", "cbond.latest_quotes"),
    ("market", "cbond", "of_stock", "正股关联转债", "cbond.of_stock"),
    ("market", "cbond", "query", "按标的查条款事件", "cbond.query"),
    ("market", "cbond", "call_hits", "强赎触发计数", "cbond.call_hits"),
    ("market", "cbond", "kline_window", "转债日K窗口", "cbond.kline_window"),
    ("market", "cbond", "bars", "转债日线表（行式）", "cbond.kline_window"),
    ("market", "cbond", "universe_codes", "转债代码全集", "cbond.universe_codes"),
    ("market", "index", "keys", "指数键列表", "indices.keys"),
    ("market", "index", "members", "指数成分", "indices.members"),
    ("market", "index", "members_history", "指数成分日快照（前向PIT）",
     "组合接口（indices.members_daily，物化表 alt.index_members_daily）"),
    ("market", "index", "weights", "指数权重股", "indices.weights"),
    ("market", "index", "valuation", "指数估值时序", "indices.valuation"),
    ("market", "index", "trend", "指数估值趋势(周频)", "indices.trend"),
    ("market", "index", "universe_keys", "指数域可用键", "indices.universe_keys"),
    ("market", "stocks", "list", "全市场证券列表", "stocks.query_list"),
    ("market", "stocks", "industries", "行业目录", "stocks.industry_list"),
    ("market", "stocks", "industry_members", "行业成分股", "stocks.industry_members"),
    ("market", "futures", "get", "期货连续合约单字段", "指标码 $FUT_*（fut_symbol 求值）"),
    ("market", "futures", "snapshot", "期货连续合约快照", "指标码 $FUT_*（fut_symbol 求值）"),
    ("market", "futures", "bars", "期货主力连续历史K线", "指标码 $FUT_*（fut_symbol 求值）"),
    ("market", "futures", "mapping", "主力换月映射", "futures.mapping"),
    ("fundamentals", "statements", "audit", "审计意见", "rptdom.statement_audit"),
    ("fundamentals", "indicator", "get", "取单个指标", "指标代码直查"),
    ("fundamentals", "indicator", "metrics", "批量取指标", "指标代码批量直查"),
    ("fundamentals", "indicator", "basic", "每日估值当前截面", "指标代码批量直查"),
    ("fundamentals", "indicator", "financials", "财务指标当前截面", "指标代码批量直查"),
    ("fundamentals", "segments", "products", "分产品收入构成", "segments.query_products"),
    ("fundamentals", "segments", "business", "分业务收入构成", "segments.query_business"),
    ("fundamentals", "segments", "region", "境内外分部", "segments.query_region"),
    ("fundamentals", "segments", "income", "主营标签占比", "segments.query_income"),
    ("fundamentals", "segments", "snapshot", "分部截面快照", "segments.snapshot"),
    ("fundamentals", "segments", "coverage", "分部披露覆盖度", "segments.coverage"),
    ("fundamentals", "segments", "periods", "分部可用报告期", "segments.list_sas"),
    ("fundamentals", "valuation", "hist_stats", "估值历史统计", "组合接口（宿主 HIST_STATS）"),
    ("fundamentals", "valuation", "daily_basic", "个股每日估值序列",
     "valuation.daily_basic（服务端物化 alt.valuation_daily）"),
    ("fundamentals", "valuation", "daily_basic_multi", "多票每日估值序列",
     "valuation.daily_basic_multi（一次 eval，EC 仍按票计价）"),
    ("fundamentals", "valuation", "daily_basic_coverage", "估值序列可用范围",
     "valuation.daily_basic（meta.window 段，只取单日窗口）"),
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
    ("disclosure", "notice", "read_text", "公告正文读取", "notice.read_text"),
    ("disclosure", "notice", "has_buyback", "窗口内有回购", "notice.signal_has_buyback"),
    ("disclosure", "notice", "has_reduction", "窗口内有减持", "notice.signal_has_reduction"),
    ("disclosure", "notice", "categories", "公告类目键列表", "notice.type_keys"),
    ("disclosure", "notice", "category_regex", "公告类目匹配正则", "notice.type_regex"),
    ("disclosure", "filings", "list", "定期报告列表", "filings.query"),
    ("disclosure", "filings", "latest", "最新定期报告", "filings.latest"),
    ("disclosure", "pdf_doc", "search", "PDF 文档检索", "pdf_doc.search"),
    ("disclosure", "pdf_doc", "read_text", "读 PDF 提取正文", "pdf_doc.read_text"),
    ("disclosure", "pdf_doc", "read_markdown", "读财报 markdown/经营评述", "pdf_doc.read_markdown"),
    ("disclosure", "pdf_doc", "status", "PDF 文档状态", "pdf_doc.status"),
    ("disclosure", "pdf_doc", "find_by_url", "按原文链接定位文档", "pdf_doc.find_by_url"),
    ("disclosure", "pdf_doc", "find_by_key", "按文档键定位文档", "pdf_doc.find_by_key"),
    ("market", "toplist", "by_date", "指定交易日龙虎榜", "toplist.by_date"),
    ("market", "toplist", "by_symbol", "单票上榜历史", "toplist.by_symbol"),
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
    # ---- 收息场景闭环（sys/income，评分 SoT 与 web 收息佬 / wm-income 技能共享）----
    ("disclosure", "dividend", "rating", "全市场收息排行", "income.rating_rows"),
    ("disclosure", "dividend", "calendar", "分红日历", "income.calendar_events"),
    ("disclosure", "dividend", "decomp", "持有收益拆解", "income.decomp"),
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
    ("reference", "equity", "buyback_snapshot", "回购六口径快照", "buyback.snapshot"),
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

# 文档暴露面元数据（开放平台接口文档站消费；SDK 面 / openapi / llms 全量不变）。
# 不在表内 = 默认完整成页。三类：
#   docs_visible=False —— 内部辅助接口：SDK 可调、cat.search 可查，但不成文档页
#     （参照 TickDB「只成页必要接口」的口径：纯谓词/运维探针不值得一张页）；
#   page=<宿主key> —— 同族变体：渲染在宿主页的「同族变体」表里一行，
#     variant=变体名；宿主必须是同命名空间内保留成页的接口；
#   variant_note —— 变体行说明（阈值/形态），缺省用该方法 docstring 首句。
DOC_META: dict[tuple[str, str], dict] = {
    # ---- 内部辅助：不成页 ----
    ("kline", "is_etf"): {"docs_visible": False},
    ("valuation", "daily_basic_coverage"): {"docs_visible": False},
    # ---- screener：13 → 1 页三小节（query 主页 + 两组变体表） ----
    ("screener", "screen_limit_up"): {"page": "screener.query", "variant": "涨停"},
    ("screener", "screen_limit_down"): {"page": "screener.query", "variant": "跌停"},
    ("screener", "screen_above_ma20"): {"page": "screener.query", "variant": "站上 MA20"},
    ("screener", "screen_ma60_up"): {"page": "screener.query", "variant": "MA60 上行"},
    ("screener", "screen_breakout_ma20"): {"page": "screener.query", "variant": "突破 MA20"},
    ("screener", "screen_momentum_20d"): {"page": "screener.query", "variant": "20 日动量"},
    ("screener", "screen_pullback_20d"): {"page": "screener.query", "variant": "20 日回撤"},
    ("screener", "screen_volume_spike"): {"page": "screener.query", "variant": "放量"},
    ("screener", "index_breadth_summary"): {"page": "screener.query", "variant": "全市场涨跌全景"},
    ("screener", "index_breadth_bins"): {"page": "screener.query", "variant": "涨跌幅分桶"},
    ("screener", "index_breadth_bin_industries"): {"page": "screener.query", "variant": "分桶行业分布"},
    ("screener", "index_top_movers"): {"page": "screener.query", "variant": "涨跌榜"},
    # ---- calendar：3 → 1 页（days 主页 + 两个便捷变体） ----
    ("calendar", "is_open"): {"page": "calendar.days", "variant": "是否交易日"},
    ("calendar", "next"): {"page": "calendar.days", "variant": "之后 N 个交易日"},
    # ---- macro：数据集预设并入 query 主页 ----
    ("macro", "nev_monthly"): {"page": "macro.query", "variant": "新势力月交付"},
    ("macro", "nev_weekly"): {"page": "macro.query", "variant": "新势力周销量"},
    ("macro", "avc_monthly"): {"page": "macro.query", "variant": "奥维家电月度"},
    ("macro", "chinaiol_monthly"): {"page": "macro.query", "variant": "家电产销月度"},
    ("macro", "cpca_top"): {"page": "macro.query", "variant": "乘联会厂商排行"},
    ("macro", "phone_share"): {"page": "macro.query", "variant": "手机品牌周份额"},
    # ---- cbond：bars 与 kline_window 同底层，行式并入列式主页 ----
    ("cbond", "bars"): {"page": "cbond.kline_window", "variant": "转债日线（行式）"},
}

# 类型化门面（生成层）：目录命名空间的完整类型签名；运行时仍走 client.call()。
from wmshare.api._generated import NAMESPACES as GENERATED_NAMESPACES  # noqa: E402
