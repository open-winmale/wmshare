"""OpenAPI 客户端：OAuth(client_credentials) + /v1/analysis/xs/eval（mode=call）。

  POST {base}/v1/oauth/token        form: grant_type/client_id/client_secret[+scope]
  POST {base}/v1/analysis/xs/eval   JSON: {symbol, xs_lines, args, script_files, market?, mode}
                                    Bearer token；mode=call → 顶层 return 值在 data.result
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import threading
import time
import warnings
from importlib.metadata import PackageNotFoundError, version
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, NoReturn

import requests

if TYPE_CHECKING:  # 前向引用：运行时惰性导入，避免潜在环
    from wmshare.notice_stream import NoticePoller

from wmshare._credentials import DEFAULT_CREDENTIAL_PATH, read_credentials_file
from wmshare._endpoints import validate_base_url
from wmshare.catalog import Catalog, load
from wmshare.errors import (
    APPID_GUIDANCE, ApiError, AuthError, CatalogError, WmshareError, LimitError,
    QUOTA_CODES, QUOTA_GUIDANCE, QuotaError, ServerError, TransportError, UsageError,
)
from wmshare.units import apply_units

DEFAULT_BASE_URL = "https://api.winmale.com"
SDK_VERSION = version("wmshare")

# 网关若回显请求体，异常消息会把 client_secret 带进 traceback / MCP 信封。
# 所有错误出口统一走 _redact，且必须「先脱敏后截断」——否则落在 [:300]
# 边界之外的 secret 仍会泄漏。
_REDACT_PAIRS = re.compile(
    r"(?i)\b(client_secret|client_id|access_token|refresh_token)\b"
    r"(\s*[=:]\s*)(['\"]?)([^\s,}\]'\"&]+)"
)
_REDACT_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/\-=]+")


def _redact(text: str, *secrets: str) -> str:
    """把已知凭证值与常见凭证字段从任意上游文本中抹掉。"""
    out = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    out = _REDACT_BEARER.sub(lambda m: m.group(1) + "***", out)
    out = _REDACT_PAIRS.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***", out)
    return out

# 无标的参数函数的求值锚点：网关按注册表校验 symbol 与 market 匹配，
# 固定 A 股锚点在 hk/us 客户端会 MARKET_MISMATCH（400）。
DEFAULT_SYMBOLS = {"cn": "600519", "hk": "00700", "us": "AAPL"}


_SYM_PREFIX = re.compile(r"^(?:cn|sh|sz|bj)\.", re.IGNORECASE)
_SYM_SUFFIX = re.compile(r"\.(?:SH|SZ|BJ)$", re.IGNORECASE)
# 美股：交易所后缀（AAPL.O=纳斯达克、BRK.N=纽交所 …）与类别股分隔符。
# 上游 symbol 注册表只有裸代码（AAPL、BRK_B）：带后缀的代码会被网关当作宏观序列
# （SYMBOL_TYPE_MACRO），跳过 SETCURSOR，指标脚本里的 symbol 变量因此未绑定——
# _LAST 族 500、分位族静默返 0（2026-10-30 实测 AAPL.O；AAPL 正常）。
_US_EXCH_SUFFIX = re.compile(r"^(?P<base>[A-Z][A-Z0-9]*)[.\-](?:O|N|A|K|P|OQ|NQ|US)$")
_US_CLASS_SEP = re.compile(r"^(?P<base>[A-Z][A-Z0-9]*)[.\-](?P<cls>[A-Z])$")


def _normalize_us(s: str, catalog: "Catalog | None") -> str:
    """美股代码归一：仅在离线代码表能确认时改写，避免误伤真实代码（如 ``O``）。"""
    if not s or catalog is None:
        return s
    try:
        universe = catalog.symbols_set("us")
    except Exception:  # 代码表缺失/损坏时不改写，交由上游报错
        return s
    if not universe or s in universe:
        return s
    # 类别股优先：BRK.B / BRK-B → BRK_B（注册表用下划线分类别）
    m = _US_CLASS_SEP.match(s)
    if m:
        candidate = f"{m.group('base')}_{m.group('cls')}"
        if candidate in universe:
            return candidate
    # 交易所后缀：AAPL.O / AAPL.N → AAPL
    m = _US_EXCH_SUFFIX.match(s)
    if m and m.group("base") in universe:
        return m.group("base")
    return s


def normalize_symbol(symbol: str, *, market: str | None = None,
                     catalog: "Catalog | None" = None) -> str:
    """标的代码归一：去 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀，字母转大写。

    传 ``market="us"`` + ``catalog`` 时，再按随包美股代码表消解交易所后缀与类别股
    写法：``AAPL.O`` → ``AAPL``、``BRK.B``／``BRK-B`` → ``BRK_B``。改名仅在代码表
    命中时发生（未命中保持原样，不猜）。

    例：``sh.600519.SH`` → ``600519``；``cn.000001`` → ``000001``；``aapl`` → ``AAPL``。
    """
    s = str(symbol).strip()
    s = _SYM_PREFIX.sub("", s)
    s = _SYM_SUFFIX.sub("", s)
    s = s.upper()
    if str(market or "").lower() == "us":
        s = _normalize_us(s, catalog)
    return s


@dataclass
class BatchResult:
    """批量调用结果：成功项与错误（票级或批级，视调用入口而定）。

    requests 记录本次共发出多少次 HTTP 请求——批量解决 429 的关键指标
    （429 按请求次数限流，免费档 500 次/小时、5000 次/日）。
    ec_cost 是各批 EC 消耗合计（网关按计算量计费，批量省请求次数不省 EC；
    网关未回传时为 0）。
    """

    results: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    requests: int = 0
    requested: int = 0
    error_details: dict[str, "BatchError"] = field(default_factory=dict)
    ec_cost: int = 0
    truncated: bool = False
    """结果是否未覆盖全部请求标的（True 时 ``results`` 是请求集的子集）。

    触发场景：批量原生接口的准全市场空参捷径（``NATIVE_FULL_MARKET_MIN``）
    下服务端只返回「非停牌全市场」，停牌/ETF/索引外标的静默缺席；拼接路径
    缺票会直接抛 ``batch_missing``，不会静默截断。调用方据此判断是否需要
    用单票接口补齐名单。
    """

    def to_df(self) -> Any:
        """转长表 DataFrame：每标的一行（值为 MAP 时字段展平，symbol 列在最前）。

        errors 中的失败标的不进表；results 为空时返回空表。
        """
        rows = []
        for sym, v in self.results.items():
            rows.append({"symbol": sym, **v} if isinstance(v, dict)
                        else {"symbol": sym, "value": v})
        return _to_dataframe(rows)


@dataclass(frozen=True)
class BatchError:
    """Structured metadata for a failed symbol or batch key in BatchResult."""

    key: str
    message: str
    code: str = ""
    status: int | None = None
    retryable: bool = False


def _chunked(seq: list[Any], size: int) -> Iterator[list[Any]]:
    """把序列切成 size 大小的连续片（保序）。"""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _xs_literal(v: Any) -> str:
    """Python 值 → XS 字面量。

    XS 的空值是 ``nil``（不接受 JSON 的 ``null``），因此 None 必须单独映射；
    其余 string/number/bool/array/map 与 JSON 字面量一致。
    """
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_xs_literal(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_xs_literal(str(k))}: {_xs_literal(x)}"
                               for k, x in v.items()) + "}"
    return json.dumps(v, ensure_ascii=False)


# kline.snapshot 23 字段（目录顺序）与 snapshot_batch 索引 $指标 的映射。
# (None, 字段) = 索引未物化（$KLINE_* 为 cursor 侧指标），适配时置 None。
_SNAPSHOT_BATCH_FIELDS: tuple[tuple[str | None, str], ...] = (
    ("$SYMBOL", "symbol"), ("$NAME", "name"), ("$CLOSE_LAST", "close"),
    ("$PERCENT_LAST", "percent"), ("$VOLUME_LAST", "volume"),
    ("$AMOUNT_LAST", "amount"), ("$MV_LAST", "mv"), ("$MV_FREE_LAST", "mv_free"),
    (None, "kline_date"), (None, "kline_sas"),
    ("$MA_CLOSE_20_LAST", "ma20"), ("$MA_CLOSE_60_LAST", "ma60"),
    ("$MA120_LAST", "ma120"), ("$CHG_5D_LAST", "chg_5d"),
    ("$CHG_10D_LAST", "chg_10d"), ("$CHG_20D_LAST", "chg_20d"),
    ("$CHG_90D_LAST", "chg_90d"), ("$ROI_NERAST_1", "roi_1y"),
    ("$VOL_RATIO_5_LAST", "vol_ratio_5"), ("$MA60_UP_LAST", "ma60_up"),
    ("$INDUSTRY_CUR_1", "industry"), ("$IS_SUSPEND", "is_suspend"),
    ("$IS_ST", "is_st"),
)


def _adapt_snapshot_batch(rows: Any, syms: list[str], name: str,
                          *, allow_missing: bool = False) -> dict[str, dict]:
    """kline.snapshot_batch 原始行 [{row, values}] → {标的: snapshot 23 字段 MAP}。

    values 的 $指标键平化为 snapshot 的扁平字段名（均线/涨跌类逐值一致，2026-11-16
    实测）；kline_date/kline_sas 索引未物化，置 None。请求了但索引无行的标的按
    call_batch 同口径抛 batch_missing。
    """
    out: dict[str, dict] = {}
    for row in rows or []:
        v = (row or {}).get("values") or {}
        sym = str(v.get("$SYMBOL") or "")
        if not sym:
            continue
        out[sym] = {flat: (None if k is None else v.get(k))
                    for k, flat in _SNAPSHOT_BATCH_FIELDS}
    if allow_missing:
        # 捷径模式下服务端返回全市场，只保留请求集合内的标的
        out = {s: out[s] for s in syms if s in out}
    missing = [s for s in syms if s not in out]
    if missing and not allow_missing:
        raise ApiError(
            f"{name}: 批量返回缺少 {len(missing)} 个标的：{missing[:10]}"
            + (f" 等 {len(missing)} 个" if len(missing) > 10 else ""),
            code="batch_missing",
        )
    return out


# 逐票拼接 → 批量原生接口自动路由表：值 = (批量实现名, 适配器)。
# 命中时列表入参不再拼 N 次单票调用，而是一次 eval 调批量实现再整形回逐票合同——
# EC 从 N×单票首算（snapshot 均线 10,250/票）降为按量（snapshot_batch ≈58 EC/票）。
BATCH_NATIVE_ROUTES: dict[str, tuple[str, Any]] = {
    "kline.snapshot": ("kline.snapshot_batch", _adapt_snapshot_batch),
}
# 达到此票数的清单视为「准全市场」：批量原生调用改传空数组（服务端全市场
# 一次投影 + 客户端过滤），避免数组字面量按 AST 逐元素计费。
# 阈值与服务端对齐（2026-11-18）：上游 snapshot_batch 对去重 ≥2000 的清单
# 本来就走全市场无过滤扫描（5,693 行 ≈14.8 万 EC，与空参捷径冷启动同价），
# 而空参捷径按自然日 memo（复跑 ≈28 EC）——SDK 阈值高于服务端只会白白错过复跑折扣。
# 代价：捷径语义=非停牌全市场，大清单里的停牌标的会进 truncated——
# 用小清单（<阈值）补拉即可（逐票按量路径含停牌行，≈58 EC/票）。
NATIVE_FULL_MARKET_MIN = 2000
# 逐票拼接告警阈值：非原生路由接口 ≥ 该票数时提示 EC 线性放大（仅告警不阻断）。
SPLICE_WARN_MIN = 200


# ---- EC 成本模型（2.0：计费透明度前置）----
# 系数来自仓库内记录的 live 实测（GUIDE §配额实测 / CHANGELOG / examples/17），
# 是「区间估算」不是承诺——实际消耗以 meta.metering 回传为准。
EC_PER_ROW = (60, 75)                 # 行数驱动类接口（K 线/资金流/分红列表）每行 EC
EC_SCREENER_BASE = (70, 1_000)        # 轻列条件选股
EC_SCREENER_HEAVY = (40_000, 60_000)  # 重列（TTM 同比/年化族）
EC_SCREENER_COLD_NOTE = ("fields 引用未物化重列时有一次全市场物化成本，"
                         "实测可达 60 万 EC——先用轻列跑通，重列二次查询")
EC_HEAVY_SCREENER_TOKENS = ("NPTS_TTM_YOY", "NPTS_AR_", "TR_AR_", "DPPR_TTM_YOY")


def _days_between(begin: Any, end: Any) -> int:
    try:
        b = _dt.date.fromisoformat(str(begin)[:10])
        e = _dt.date.fromisoformat(str(end)[:10])
        return (e - b).days
    except ValueError:
        return 365


def estimate_cost(name: str, params: dict[str, Any] | None = None, *,
                  native_batch_min: int = 3) -> dict:
    """EC 消耗区间估算（纯离线，发不发请求都在此返回）。

    ``Client.cost_estimate`` 的模型本体；没有成本模型的接口如实
    返回 ``ec_lo=ec_hi=None``（绝不编造数字）。
    """
    out: dict[str, Any] = {"name": name, "requests": 1,
                           "ec_lo": None, "ec_hi": None, "model": "", "note": ""}
    p = params or {}
    limit = p.get("limit") or p.get("n") or p.get("lim")
    rows = None
    try:
        rows = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        rows = None
    if name.startswith(("kline.query_bars", "moneyflow.query_bars",
                        "bonus.query_list", "cbond.query")):
        if p.get("begin") and p.get("end") and not name.startswith(("bonus.", "cbond.")):
            # 日 K/资金流区间查询走锚点分页：服务端窗口右端锚在 anchor，只物化
            # ≤end 的行、覆盖 begin 即停——计费 ≈ 区间实际根数（不客户端砍量、
            # 不静默截断）。估算用自然日跨度的交易日密度区间，不是承诺。
            days = max(1, abs(_days_between(p["begin"], p["end"])) + 1)
            lo = int(days * 0.6) + 5
            out.update(ec_lo=lo * EC_PER_ROW[0], ec_hi=days * EC_PER_ROW[1],
                       model="range_rows",
                       note=f"区间 {p['begin']}~{p['end']} ≈区间内交易日根数"
                            f"（上界 {days} 自然日）× {EC_PER_ROW} EC/行；"
                            "锚点分页切片，每片 ≤ max_limit 行")
            return out
        if p.get("begin") and p.get("end"):
            # 分红/转债条款等区间单次请求 limit（Client 默认 max_limit=500）；
            # 区间超出单次上限时门面显式报错（不静默截断）
            n = rows if (rows and rows > 0) else 500
            out.update(ec_lo=n * EC_PER_ROW[0], ec_hi=n * EC_PER_ROW[1],
                       model="rows",
                       note=f"区间查询单次请求 {n} 行（Client 默认 max_limit=500，"
                            f"超出会显式报错）× {EC_PER_ROW} EC/行")
            return out
        n = rows if (rows and rows > 0) else (120 if "query_bars" in name else 20)
        out.update(ec_lo=n * EC_PER_ROW[0], ec_hi=n * EC_PER_ROW[1],
                   model="rows", note=f"按 {n} 行 × {EC_PER_ROW} EC/行估算")
    elif name == "kline.snapshot" or name == "kline.snapshot_batch":
        # 门面参数名是 symbol，底层目录参数名是 sym；两者都认，避免按门面习惯
        # 传 symbol=[...] 时被当成单票低估（2026-11-18 修）。
        codes: Any = None
        for _key in ("sym", "codes", "symbol"):
            if _key in p:
                codes = p[_key]
                break
        if isinstance(codes, (list, tuple)) and len(codes) == 0:
            # 显式空数组 = 全市场捷径（服务端全市场投影），不是「单票」
            out.update(ec_lo=110_000, ec_hi=150_000, model="full_market_shortcut",
                       note="空参 = 服务端全市场投影一次（实测 ≈14.2 万 EC）；"
                            "停牌/ETF/索引外标的静默缺席（truncated=True）")
            return out
        n = len(codes) if isinstance(codes, (list, tuple)) else 1
        if n >= int(native_batch_min or 3):
            if n >= NATIVE_FULL_MARKET_MIN:
                out.update(ec_lo=110_000, ec_hi=150_000,
                           model="full_market_shortcut",
                           note=f"{n} 票达准全市场阈值 {NATIVE_FULL_MARKET_MIN}，"
                                "走空参捷径（服务端全市场投影）；停牌/ETF 索引外标的"
                                "静默缺席，需完整名单请分批到阈值以下")
            else:
                out.update(ec_lo=n * 55, ec_hi=n * 65, model="batch_per_symbol",
                           note=f"批量原生路由 ≈58 EC/票 × {n} 票；"
                                "单票首触另计均线回看 ≈10,250 EC")
        else:
            out.update(ec_lo=n * 10_000, ec_hi=n * 11_000, model="first_touch",
                       note=f"{n} 票低于批量阈值：逐票首算 ≈10,250 EC/票；"
                            "≥3 票自动走批量原生（≈58 EC/票）")
    elif name == "screener.query" or (name.startswith("kline.") and "where" in p):
        codes = " ".join([str(p.get("where") or ""), str(p.get("order") or ""),
                          *map(str, p.get("fields") or [])])
        if any(tok in codes for tok in EC_HEAVY_SCREENER_TOKENS):
            out.update(ec_lo=EC_SCREENER_HEAVY[0], ec_hi=EC_SCREENER_HEAVY[1],
                       model="screener_heavy", note=EC_SCREENER_COLD_NOTE)
        else:
            out.update(ec_lo=EC_SCREENER_BASE[0], ec_hi=EC_SCREENER_BASE[1],
                       model="screener_base",
                       note="轻列 70~1,000 EC；重列物化另计（count-only 更低）")
    elif name.startswith("backtest.run") or name == "backtest.run":
        begin, end = p.get("begin"), p.get("end")
        if begin and end:
            days = abs(_days_between(begin, end))
            n = min(10000, max(int(days * 0.8) + 40, 22))
            out.update(ec_lo=n * EC_PER_ROW[0], ec_hi=n * EC_PER_ROW[1],
                       model="rows", note=f"按区间 {n} 根日 K 估算；不给区间拉全历史 ≈40 万 EC")
        else:
            out.update(ec_lo=380_000, ec_hi=420_000, model="full_history",
                       note="全历史 1 万根 ≈40 万 EC；传 begin/end 可降 1~2 个数量级")
    elif name.startswith("valuation.hist_stats"):
        out.update(ec_lo=4, ec_hi=200, model="cache_hit",
                   note="走预热缓存（实测命中 ≈4 EC）；缓存冷的回填成本未物化，"
                        "勿按本估算做回填预算")
    elif name == "buyback.snapshot":
        # 实测（2026-11-19 live，5 票）：171~709 EC，与是否有回购数据无关
        # （无数据票 171，六口径齐全票 697~709）——成本在按票取数+组装，
        # 不是按行；**不缓存**（复跑同价），单票一次。
        out.update(ec_lo=170, ec_hi=750, model="measured",
                   note="按票一次取数 ≈170~710 EC（2026-11-19 实测 5 票）；"
                        "复跑同价（无结果缓存），无回购数据的票走地板 ≈170 EC")
    elif name == "notice.type_keys":
        out.update(ec_lo=5, ec_hi=15, model="measured",
                   note="静态类目表（14 键），实测 ≈9 EC")
    elif name == "notice.type_regex":
        out.update(ec_lo=8, ec_hi=20, model="measured",
                   note="单键正则解析，实测 ≈14 EC")
    elif name == "equity.query_holdernum_history":
        # 实测（2026-11-23 live）：8 期 冷 1,967 → 热 794 EC；95 期 冷 15,623 → 热 1,853 EC。
        # 成本在 CONOF 逐行规范化（取数只是单档 store.find），所以按 limit 线性。
        n = rows if (rows and rows > 0) else 40
        out.update(ec_lo=700 + int(n * 10), ec_hi=800 + int(n * 170),
                   model="measured",
                   note=f"按返回期数线性：8 期冷 ≈2,000 / 热 ≈800 EC，95 期冷 ≈1.6 万 / 热 ≈1,850 EC"
                        f"（实测 2026-11-23）；此 limit={n} 冷态 ≈{800 + n * 170} EC，"
                        "复跑走 fmt 指纹缓存；单票上限 300 期（上游档宽）")
    elif name in {"board.moneyflow", "board.moneyflow_last"}:
        # 实测（2026-11-23 live，limit=20）：ths_concept 冷 16,137 → 热 185；
        # dc 冷 53,663 → 热 185（整档行数与冷态成本成正比）。
        src = p.get("src") or "ths_concept"
        cold = {"ths_concept": 16_200, "ths_industry": 6_000, "dc": 54_000}.get(src, 16_200)
        out.update(ec_lo=185, ec_hi=cold, model="measured",
                   note=f"src={src}：冷态 ≈{cold} EC（整日一档读取+排序，limit 只影响返回行数）、"
                        "复跑走数据版本键/fmt 指纹缓存 ≈185 EC")
    elif name == "stocks.limit_prices":
        # 全市场索引一次投影（7 字段 × 非停牌 ≈5,683 行）。冷态档位对齐同规模
        # 投影实测（kline.snapshot_batch 2026-11-17：5,693 行 ≈142,260 EC），
        # 本接口 2026-11-23 live 复跑 75 EC（按自然日 memo）。
        out.update(ec_lo=75, ec_hi=150_000, model="measured",
                   note="全市场索引一次投影 ≈25 EC/行（冷 ≈14 万）、按自然日缓存，"
                        "复跑 ≈75 EC；停牌股不返回")
    elif name == "stocks.limit_price":
        out.update(ec_lo=30, ec_hi=60, model="measured",
                   note="单票索引点查 ≈30-50 EC（无全市场投影）")
    elif name.startswith("toplist."):
        # 实测（2026-11-19 live，修复后）：
        #   by_date 单日整榜 95 行 冷 12,858 → 热 175 EC（fmt_maps 指纹缓存）
        #   by_symbol 单票 10 条   冷 1,567  → 热 185 EC
        # 冷态成本在逐 doc 扫全市场行（不是取数：store.find 仅 37 EC）。
        if name == "toplist.by_date":
            out.update(ec_lo=170, ec_hi=13_000, model="measured",
                       note="单日整榜 ≈95 行：冷态 ≈1.3 万 EC（逐行 CONOF 规范化）、"
                            "复跑走指纹缓存 ≈175 EC；盘后当日榜单当日可查")
        else:
            out.update(ec_lo=185, ec_hi=1_600, model="measured",
                       note="单票上榜历史：冷态 ≈1,600 EC（逐 doc 扫全市场行）、"
                            "复跑走数据版本键缓存 ≈185 EC；limit 越小冷态越省")
    elif name == "blocktrade.by_date":
        # 实测（2026-11-23 live，全量回补后 4,100 日 / 68 万行）：
        # 单日档点查 1,272~1,703 EC（按当日行数浮动，档内行数即读取量）。
        out.update(ec_lo=1_200, ec_hi=1_800, model="measured",
                   note="单日一档点查 ≈1,300~1,700 EC（2026-11-23 全量回补后实测）；"
                        "成本随当日大宗笔数浮动，非固定开销")
    elif name == "blocktrade.by_symbol":
        # 实测（2026-11-23 live）：冷 4,814 → 热 243 EC（数据版本键缓存）。
        out.update(ec_lo=240, ec_hi=4_900, model="measured",
                   note="单票历史：冷态 ≈4,800 EC（raw 按日分档，单票过滤需扫全档）、"
                        "复跑走数据版本键缓存 ≈240 EC；limit 越小冷态越省")
    elif name == "futures.mapping":
        # 实测（2026-11-19 live）：窗口 13 行 冷 833 → 热 160 EC；
        # 全历史 4,287 行 冷 214,514 EC（CONOF 逐行计费），必须传窗口。
        out.update(ec_lo=160, ec_hi=5_000, model="measured",
                   note="按窗口行数：13 行冷 ≈833 / 热 ≈160 EC；"
                        "全历史 4,287 行冷 ≈21.4 万 EC——务必传 begin/end 收窄窗口")
    elif name == "futures.bars":
        # 实测（2026-11-23 live，store 直读 futures.query_bars）：
        # 1 行冷 317 / 6 行 947 / 21 行 2,844 / 250 行 31,691 EC
        # → 冷 ≈190 + 126×行；同日复跑命中数据版本键缓存 ≈135 EC（与行数基本无关）。
        # 门面已按 freq 硬顶行数（d 3000/w 600/m 300）。
        _freq = str(p.get("freq") or "d").strip().lower()
        _freq = {"day": "d", "daily": "d", "week": "w", "weekly": "w",
                 "month": "m", "monthly": "m"}.get(_freq, _freq) or "d"
        est = rows
        if est is None and p.get("begin") and p.get("end"):
            days = max(1, abs(_days_between(p["begin"], p["end"])) + 1)
            if _freq == "w":
                est = days // 7 + 1
            elif _freq == "m":
                est = days // 30 + 1
            else:
                est = days
        est = max(1, int(est or 120))  # 120 = bars 默认 n
        out.update(ec_lo=135, ec_hi=190 + 126 * est, model="measured",
                   note=f"store 直读按行计费：冷 ≈190+126×{est}≈{190 + 126 * est} EC、"
                        "同日复跑命中数据版本键缓存 ≈135 EC；"
                        "长区间建议 freq='m'（行数省 20 倍）")
    elif name in ("futures.snapshot", "futures.get"):
        # 实测（2026-11-23 live）：store 单行冷 317 EC、同日复跑 ≈135 EC。
        out.update(ec_lo=135, ec_hi=320, model="measured",
                   note="store 单行取数（最新一根）：冷 ≈317 EC、同日复跑 ≈135 EC"
                        "（数据版本键缓存）")
    elif name == "futures.query_bars":
        # 实测（2026-11-23 live，RB.SHF）：10 行冷 867、250 行冷 31,691 EC
        # → 线性 ≈128 EC/行（CONOF 逐行计费）；同日复跑命中数据版本键缓存 ≈135 EC。
        # 周期上限：日 5500 / 周 1200 / 月 360（缺省取满，超上限会被截到上限）。
        _period = str(p.get("period") or "D").strip().upper()[:1]
        _cap = {"W": 1200, "M": 360}.get(_period, 5500)
        n = rows if (rows and rows > 0) else _cap
        out.update(ec_lo=max(300, int(n * 128) - 450), ec_hi=int(n * 128) + 450,
                   model="measured",
                   note=f"按行数线性 ≈128 EC/行 × {n} 行（10 行冷 867、250 行冷 31,691 "
                        "实测）；同日复跑走数据版本键缓存 ≈135 EC——全历史长窗冷态"
                        "上万元 EC，按需传 limit 或 begin/end")
    elif name.startswith(("fx.", "reserve.")):
        # 实测（2026-11-23 部署后 probe，全部取 metering.ec_cost）：
        #   fx.history 冷/热均 85；fx.list 61（含整表缓存）；reserve.asof 102；
        #   reserve.list 67；reserve.query(12期) 冷 889 → 热 90；
        #   fx.query_bars(100行) 冷 1,901 → 热 111（数据版本键缓存）。
        # 共同点：**缓存命中后基本恒定**（1 行探针 + memo 命中），冷态才有
        # 下行数相关的取数成本——与 K 线类「按行线性」不同，勿套 EC_PER_ROW。
        if name in ("fx.list",):
            out.update(ec_lo=61, ec_hi=61, model="measured",
                       note="整表版本键缓存后恒定 ≈61 EC（命中零探测；冷首次含 16 币种探测）")
        elif name == "fx.rate":
            out.update(ec_lo=147, ec_hi=147, model="measured",
                       note="单次 store.query 取 1 行 ≈147 EC")
        elif name == "fx.history":
            out.update(ec_lo=85, ec_hi=85, model="measured",
                       note="数据版本键缓存后恒定 ≈85 EC（n 大小不改变成本；冷首次同价）")
        elif name == "fx.query_bars":
            out.update(ec_lo=111, ec_hi=1_901, model="measured",
                       note="区间读面：冷态按行数（100 行 ≈1,901 EC）→ 热态走数据版本键"
                            "缓存 ≈111 EC")
        elif name == "reserve.asof":
            out.update(ec_lo=102, ec_hi=102, model="measured",
                       note="单期储备最新值（单次 store.query）≈102 EC")
        elif name == "reserve.list":
            out.update(ec_lo=67, ec_hi=67, model="measured",
                       note="整表缓存后恒定 ≈67 EC（4 项探测仅首次）")
        else:  # reserve.query
            out.update(ec_lo=90, ec_hi=889, model="measured",
                       note="月频时序：冷态 ≈889 EC（12 期）→ 热态 ≈90 EC（数据版本键缓存）")
    elif name.startswith("fred."):
        # 实测（2026-11-23 部署后 metering.ec_cost，cn 客户端）：
        #   topics 408（静态包，但 xs.call 加载本身计费）/ search 1,324（同）/
        #   series_meta 746 / points(20行) 冷 986 → 热 92 / 窗口 2 年 7 行 394。
        # 2026-11-23 review 修正：行内组装从逐行 append 改为 CONOF/CONFT 向量化
        # （append 深拷贝是 O(n²)），实测重标 45 EC/行（500 行 22,619 / 2,000 行
        # 90,180 / 10,000 行 450,509，线性 ≈45 EC/行 + ~2,000 固定）。
        # 热态仍恒定 ≈92 EC（数据版本键缓存命中后不组装）。
        if name == "fred.topics":
            out.update(ec_lo=408, ec_hi=408, model="measured",
                       note="静态主题包直读，恒定 ≈408 EC（xs.call 加载计费，无 store 取数）")
        elif name == "fred.search":
            out.update(ec_lo=1_324, ec_hi=1_324, model="measured",
                       note="在 88 条精选内匹配，实测 ≈1,324 EC（含中文名/说明包加载）")
        elif name == "fred.series_meta":
            out.update(ec_lo=746, ec_hi=746, model="measured",
                       note="1 行探针判 has_data + 目录元信息单查，实测 ≈746 EC")
        else:  # fred.points_asc
            n = rows if (rows and rows > 0) else 500
            if n > 10_000:
                n = 10_000  # store 单次硬顶，更大的 limit 不会多拿行
            cold = 2_000 + int(n * 45)
            out.update(ec_lo=92, ec_hi=cold, model="measured",
                       note=f"冷态 ≈45 EC/行 + ~2,000 固定（实测 500 行 22,619、"
                            f"2,000 行 90,180、10,000 行 450,509），{n} 行 ≈{cold}；"
                            "**复跑恒定 92 EC**（数据版本键缓存）。上限 10000 行"
                            "（store 单次硬顶）；更长历史按 begin/end 分段各取一次"
                            "（2 年 7 行仅 394 EC）")
    elif name.startswith("pdf_doc."):
        # 实测（2026-11-19 live）：search 5 行 ≈836 EC（含 fmt_one 组装，
        # 无结果缓存，复跑同价）；find_by_key/status/read_* 单行点查数百 EC。
        if name == "pdf_doc.search":
            n = rows if (rows and rows > 0) else 20
            out.update(ec_lo=int(n * 150), ec_hi=int(n * 200) + 200, model="measured",
                       note=f"按命中行 ≈150~200 EC/行 × {n} 行（含元数据组装，"
                            "无结果缓存，复跑同价）；正文不在 search 返回里")
        else:
            out.update(ec_lo=200, ec_hi=1_200, model="measured",
                       note="单文档点查/正文预览 ≈200~1,200 EC（正文越长越高）")
    elif name.startswith("valuation.daily_basic"):
        # 实测（2026-11-19 生产 probe，全部取 metering.ec_cost）：
        # **单票 + begin/end**：读窗按 kernel window 锚下推，只扫窗口覆盖的日文档
        #   实测 1 日 578、13 日 962、1 年 8,626 → ≈550 + 22 EC/自然日
        # **单票无 begin/end**：读 DEFAULT_LIMIT(1,500) 日文档后客户端过滤
        #   全量 727 文档 = 23,414 EC
        # **多票（daily_basic_multi）**：一次 eval 内逐票扫 per-symbol 物化表，
        #   EC 按票计价。18 天窗口实测 1→674 / 5→2,858 / 10→5,588 / 30→16,521
        #   / 50→26,625；span 1/90 的 5 票为 1,401 / 10,218。
        #   统一拟合：total ≈ 150 + 票数 × (230 + 20 × 自然日跨度)，
        #   上表全部落点误差 <12%。
        #   批量只省请求调度，**不省算力**。此前本分支忽略 syms，多票预估
        #   算的是单票价（低估一个数量级以上）——预估失真比没有预估更危险。
        b, e = p.get("begin"), p.get("end")
        span = max(1, abs(_days_between(b, e)) + 1) if (b and e) else 0
        syms = p.get("syms") or p.get("symbols") or []
        n_syms = max(1, len(syms)) if isinstance(syms, (list, tuple)) else 1
        if b or e:
            base_lo = 150 + n_syms * (230 + 20 * span)
            out.update(ec_lo=int(base_lo * 0.75), ec_hi=int(base_lo * 1.7),
                       model="measured")
        else:
            out.update(ec_lo=20_000 * n_syms, ec_hi=26_000 * n_syms,
                       model="measured")
        if n_syms > 1:
            out["note"] = (
                f"多票 ×{n_syms}：EC 按票计价（18 天窗口边际 ≈550 EC/票），"
                f"合计 ≈{out['ec_lo']:,}~{out['ec_hi']:,} EC。"
                "批量只省请求调度，**不省算力**；大清单建议先小样本确认口径")
        elif b or e:
            out["note"] = (
                f"读窗已下推（kernel window 锚）：按窗口自然日跨度 ≈{span} 天文档，"
                "≈550 EC 地板 + ≈22 EC/日；实测单日 578、13 日 962、1 年 8,626 EC。"
                "**不给 begin/end 时仍是全表扫 ≈23,414 EC**（727 文档），区间查询务必传"
            )
        else:
            out["note"] = (
                "不给 begin/end = 全表扫（1,500 日文档上限）≈23,414 EC（2026-11-19 实测）；"
                "传 begin/end 会下推读窗、成本随窗口走（单日 ≈578、13 日 ≈962 EC）"
            )



    elif name.startswith("indices.trend"):
        out.update(ec_lo=1, ec_hi=50, model="cache_hit",
                   note="只读预热缓存；未命中返回 ok=False（不现算、不产生 EC）")
    elif name in ("margin.universe", "margin.market_summary"):
        # 实测（2026-11-17 live）：市场级两融按行物化 ≈100~115 EC/行
        is_univ = name.endswith("universe")
        per = 112 if is_univ else 101
        n = rows if (rows and rows > 0) else (4010 if is_univ else 60)
        out.update(ec_lo=int(n * per * 0.9), ec_hi=int(n * per * 1.1),
                   model="rows_per_symbol",
                   note=(f"≈{per} EC/行 × {n} 行（市场级逐行物化）；"
                         + ("全量名单 ≈4,010 行 ≈45 万 EC，按需传 limit 可线性降低"
                            if is_univ else
                            "默认 60 行 ≈6 千 EC；跨交易所同日并存，每行一个 (日期,交易所)")))
    elif name.startswith("dividend.rating") or name.startswith("income.rating_rows"):
        # 实测（2026-11-20 live，循环去 DEFAULT 化后）：memo 直读 + 全表过滤遍历为主成本
        #   top20 无行业过滤 54,277 / top100+grade 67,123 / 行业过滤早停 17,537
        out.update(ec_lo=15_000, ec_hi=70_000, model="measured",
                   note="memo 直读零冷算（全市场评分在 cron 物化侧分 5 片防 fuel 顶）"
                        "≈15k~70k EC（2026-11-20 实测：top20 全量 54k、top100 67k、"
                        "行业过滤早停 17k）。COLD_CACHE（cron 未就绪）显式失败。"
                        "老口径现场重算全市场评分曾 95 万 EC/次——已由服务端直读替代，"
                        "AI 勿自行重算榜单")
    elif name.startswith("dividend.diagnose") or name.startswith("income.diagnose"):
        # 实测（2026-11-20 live）：INDEX_ROW_VALUES_MANY_SPEC 原生批量 + 榜内 rank 映射
        #   批量档 2 票 21,688（≈11k/票）；deep 档单票（含分红史/方案逐票读）28,462
        n_syms = 1
        s = p.get("symbols") or p.get("symbol")
        if isinstance(s, (list, tuple)):
            n_syms = max(1, len(s))
        out.update(ec_lo=10_000 * n_syms, ec_hi=35_000 * n_syms, model="measured",
                   note=(f"原生批量 ≈10k EC/票 + 榜内 rank 映射（2 票实测 21.7k）；"
                         "deep 档 include_history=True 逐票加分红史/方案读 ≈28k/票。"
                         "批量一次调用，勿逐票循环"))
    elif name.startswith("dividend.calendar") or name.startswith("income.calendar_events"):
        # 实测（2026-11-20 live）：当月窗口 19,535（147 事件 + 全票指标 enrich）
        out.update(ec_lo=15_000, ec_hi=45_000, model="measured",
                   note="store 窗口查 + 逐票指标 enrich ≈15k~45k EC（当月实测 19.5k /"
                        " 147 事件）；窗口越宽事件越多，建议按月查询")
    elif name.startswith("dividend.decomp") or name.startswith("income.decomp"):
        # 实测（2026-11-20 live）：热态 ≈9.9k/票线性（月 K 双序列 + AT 锚点序列）。
        # **冷首查尖刺**：AT 锚点指标序列（$PE_TTM/$BONUS_RATE_TTM 月频）首查物化，
        #   单票可达 ~20 万 EC（600036 首查实测 217k，复查即热 9.9k），与票无关、间歇出现
        n_syms = 1
        s = p.get("symbols") or p.get("symbol")
        if isinstance(s, (list, tuple)):
            n_syms = max(1, len(s))
        out.update(ec_lo=int(8_000 * n_syms),
                   ec_hi=int(max(15_000, 200_000) * n_syms), model="measured",
                   note=(f"热态 ≈10k EC/票 线性（≤10 票一次调用）；**AT 锚点指标序列"
                         "首查有冷物化惩罚，单票尖刺可达 ~20 万 EC（复查即热 ≈10k）**，"
                         "上界按尖刺留量。次新股 K 线覆盖不足 ok=false 如实呈现"))
    else:
        out["note"] = ("暂无该接口的成本模型；多数读接口在数百 EC 量级。"
                       "可用 cli.last_ec_cost 观测实际消耗后反馈补模型。")
    return out


def _to_dataframe(result: Any) -> Any:
    try:
        import pandas as pd
    except ImportError as e:  # pragma: no cover
        raise UsageError(
            "DataFrame 返回需要 pandas：pip install pandas", code="pandas") from e
    if isinstance(result, list):
        return pd.DataFrame(result)
    if isinstance(result, dict):
        return pd.DataFrame([result])
    raise UsageError(f"结果类型 {type(result).__name__} 无法转 DataFrame", code="dataframe")


def to_output_frame(value: Any) -> Any:
    """2.0 门面返回形态收口：行数组（list[dict]）默认转 DataFrame，其余原样。

    这是「查询/序列类默认 DataFrame」规范的唯一收口点：
      - list[dict] → DataFrame（列序与行序由门面保证：标识列在前、时间升序）
      - dict（MAP/信封）、标量、None → 原样
      - BatchResult 容器 → 原样，仅把 results 里的行数组逐标的转 DF
    两层契约：门面（``cli.ns.method``）给 DataFrame/dict/信封；底层
    ``cli.call`` / ``cli.call_batch`` 保持规范化行数组（``BatchResult.to_df()``
    出长表）。
    """
    if isinstance(value, list):
        return _to_dataframe(value)
    if isinstance(value, BatchResult):
        value.results = {k: (_to_dataframe(v) if isinstance(v, list) else v)
                         for k, v in value.results.items()}
        return value
    return value


def _normalize_field_list(fields: Any) -> list[str] | None:
    """``_fields`` 入参归一：``None`` / ``"a,b"`` / ``["a", "b"]`` → 去重保序列表。"""
    if fields is None:
        return None
    if isinstance(fields, str):
        parts = [s.strip() for s in fields.split(",") if s.strip()]
    elif isinstance(fields, (list, tuple)):
        parts = [str(s).strip() for s in fields if str(s).strip()]
    else:
        raise UsageError(
            '_fields 只接受 list[str] 或逗号字符串（如 "date,close"）', code="params")
    if not parts:
        raise UsageError("_fields 不能为空", code="params")
    return list(dict.fromkeys(parts))


def project_fields(value: Any, fields: Any, *, fname: str = "") -> Any:
    """列投影：按请求顺序保留行/映射中的字段（客户端通用选项，``_fields=``）。

    - 行数组（``list[dict]``）→ 逐行投影；空数组原样返回（无字段可校验）
    - 映射（``dict``）→ 按键投影
    - 标量/``None`` → ``UsageError``（该结果没有字段可投影）

    未知字段抛 ``UsageError`` 并列出可用字段。投影发生在规范化与单位换算
    **之后**，因此不改变数值口径；也**不降低 EC**（EC 按服务端物化行计），
    只收窄返回体与 DataFrame 列宽。函数自带的 ``fields`` 参数（如
    ``valuation.daily_basic``/``screener.query``）是上游参数，与本选项无关。
    """
    req = _normalize_field_list(fields)
    if req is None:
        return value
    label = f"{fname}: " if fname else ""
    if isinstance(value, dict):
        missing = [f for f in req if f not in value]
        if missing:
            raise UsageError(
                f"{label}_fields 含未知字段 {missing}；可用字段：{sorted(value)}",
                code="params")
        return {f: value[f] for f in req}
    if isinstance(value, list):
        if not value:
            return value
        if any(not isinstance(r, dict) for r in value):
            raise UsageError(
                f"{label}_fields 只适用于行/映射结果（存在非映射行）", code="params")
        available: set[str] = set()
        for r in value:
            available.update(r)
        missing = [f for f in req if f not in available]
        if missing:
            raise UsageError(
                f"{label}_fields 含未知字段 {missing}；可用字段：{sorted(available)}",
                code="params")
        return [{f: r.get(f) for f in req} for r in value]
    raise UsageError(
        f"{label}_fields 只适用于行/映射结果（收到 {type(value).__name__}）", code="params")


def _project_batch(value: "BatchResult", fields: Any, *, fname: str = "") -> "BatchResult":
    """对批量结果逐标的做列投影（标量结果保持原样，不报错）。"""
    if fields is None or not value.results:
        return value
    for key, item in list(value.results.items()):
        if isinstance(item, (dict, list)):
            value.results[key] = project_fields(item, fields, fname=fname)
    return value


def normalize_date(value: Any) -> str:
    """日期入参归一（2.0 全库统一 ISO ``YYYY-MM-DD``）。

    接受 ``date``/``datetime``、``YYYY-MM-DD``、紧凑 ``YYYYMMDD``（含 3.11+
    ``fromisoformat`` 原生支持）；非法输入抛 ``UsageError``（不静默透传）。
    """
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    s = str(value or "").strip()
    try:
        return _dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        raise UsageError(
            f"日期 {value!r} 不合法；需 YYYY-MM-DD（或 YYYYMMDD 紧凑格式）",
            code="range") from None


def _legacy_finpipe_hints() -> str:
    """检测旧版 finpipe 的配置残留（本项目更名前的 env 前缀与凭证路径）。

    只用于在缺凭证报错时指路迁移，不读取、不映射旧配置（更名即全面切新名）。
    """
    found = [k for k in ("FINPIPE_CLIENT_ID", "FINPIPE_CLIENT_SECRET")
             if os.environ.get(k)]
    legacy_file = Path.home() / ".finpipe" / "credentials.env"
    if legacy_file.is_file():
        found.append(str(legacy_file))
    return "、".join(found)


class Client:
    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        market: str = "cn",
        catalog: Catalog | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        max_limit: int | None = 500,
        retries: int = 2,
        backoff: float = 0.5,
        backoff_jitter: float = 0.1,
        max_retry_after: float = 10.0,
        validate: bool = True,
        ec_warn_threshold: int | None = 100_000,
        allow_custom_host: bool = False,
        native_batch: bool = True,
        native_batch_min: int = 3,
    ):
        market = str(market or "cn").strip().lower()
        if market not in ("cn", "hk", "us"):
            raise UsageError(
                f"market 只支持 cn/hk/us，收到 {market!r}", code="market")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise UsageError("base_url 必须是非空 URL", code="config")
        if base_url is not None:
            # 端点策略见 _endpoints.py：默认只放行官方主机与本地回环，
            # 其余需显式 opt-in —— OAuth token 会向该 host 明文 POST client_secret。
            validate_base_url(base_url.strip(), allow_custom_host=allow_custom_host)
        self._allow_custom_host = bool(allow_custom_host)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
                or not float(timeout) > 0 or not math.isfinite(float(timeout)):
            raise UsageError("timeout 必须为正有限秒数", code="config")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise UsageError("retries 必须为非负整数", code="config")
        if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) \
                or not float(backoff) >= 0 or not math.isfinite(float(backoff)):
            raise UsageError("backoff 必须为非负有限秒数", code="config")
        if max_limit is not None and (isinstance(max_limit, bool)
                                      or not isinstance(max_limit, int) or max_limit <= 0):
            raise UsageError("max_limit 必须为正整数或 None", code="config")
        if not isinstance(native_batch, bool):
            raise UsageError("native_batch 必须是布尔值", code="config")
        if isinstance(native_batch_min, bool) or not isinstance(native_batch_min, int) \
                or native_batch_min < 1:
            raise UsageError("native_batch_min 必须是正整数", code="config")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        if bool(self.client_id) != bool(self.client_secret):
            raise AuthError(
                "client_id 与 client_secret 需成对提供。"
                f"不配置则无法取数——{APPID_GUIDANCE}", code="config")
        if not self.client_id:
            legacy = _legacy_finpipe_hints()
            raise AuthError(
                "缺少凭证：请先配置自己的开放平台凭证"
                "（构造参数 / WMSHARE_* 环境变量 / ~/.wmshare/credentials.env 任一）。"
                + (f"\n检测到旧版 finpipe 配置（{legacy}）：本项目已更名 wmshare，"
                   "凭证配置同步改为 WMSHARE_* 环境变量 / ~/.wmshare/credentials.env，"
                   "旧配置不再被读取，请迁移。\n" if legacy else "\n")
                # 报错即引导：未配置凭证时首选 Client.from_env()——凭据双缺
                # 会自动回落匿名试用（免注册、真实数据、免费额度）。回落不可用
                # （服务端未开放 / WMSHARE_DISABLE_ANON=1）时 from_env 也会落到
                # 本错误，故文案必须自解释，不能把「去用 from_env()」当唯一出口。
                + "未配置凭证可用 wmshare.Client.from_env() 自动领取匿名试用"
                  "（免注册、真实数据、免费额度）。若已在 from_env() 中仍见本"
                  "错误，说明该服务端未开放匿名试用、或 WMSHARE_DISABLE_ANON=1"
                  " 已关闭回落，请直接配置上述凭证。\n"
                + f"{APPID_GUIDANCE}",
                code="config")
        self.market = market
        self.catalog = catalog or load()
        self._owns_session = session is None
        self.session = session or requests.Session()
        session_headers = getattr(self.session, "headers", None)
        if session_headers is not None:
            session_headers.setdefault("User-Agent", f"wmshare/{SDK_VERSION}")
            # 来源标记：网关按此头落库 call_log（client 字段），审计可区分
            # SDK/MCP/裸 HTTP。MCP 层会覆写为 wmshare-mcp/<版本>（mcp/core.py）。
            session_headers.setdefault("X-WM-Client", f"wmshare-py/{SDK_VERSION}")
        self.timeout = timeout
        self.max_limit = max_limit
        # 批量原生路由开关：命中 BATCH_NATIVE_ROUTES 的接口收列表时自动改走
        # 批量实现（如 kline.snapshot → kline.snapshot_batch，EC 按量而非 N×单票）。
        # native_batch_min 以下的列表仍走拼接——极小列表首触更便宜，且保留逐票语义。
        self.native_batch = native_batch
        self.native_batch_min = native_batch_min
        self.retries = max(0, int(retries))
        self.backoff = backoff
        if isinstance(backoff_jitter, bool) or not isinstance(backoff_jitter, (int, float)) \
                or not 0 <= float(backoff_jitter) < 1 \
                or not math.isfinite(float(backoff_jitter)):
            raise UsageError("backoff_jitter 需在 [0, 1)", code="config")
        if isinstance(max_retry_after, bool) or not isinstance(max_retry_after, (int, float)) \
                or not float(max_retry_after) >= 0 or not math.isfinite(float(max_retry_after)):
            raise UsageError("max_retry_after 必须为非负有限秒数", code="config")
        if ec_warn_threshold is not None and (
                isinstance(ec_warn_threshold, bool)
                or not isinstance(ec_warn_threshold, int) or ec_warn_threshold <= 0):
            raise UsageError(
                "ec_warn_threshold 必须为正整数（单次 eval EC 提示阈值）或 None（关闭提示）",
                code="config")
        self.backoff_jitter = float(backoff_jitter)
        self.max_retry_after = float(max_retry_after)
        # 开放平台按计算量（EC）计费：批量/多标的脚本按标的数逐票计价，
        # 单次 eval 超过阈值的消耗在响应里直接提示（网关经 meta.metering 回传）。
        self.ec_warn_threshold = ec_warn_threshold
        self.last_ec_cost: int | None = None  # 最近一次成功 eval 的 EC 消耗
        self._validate = validate  # False=关闭单位量级/不变量校验（换算仍执行）
        if not validate:
            # 构造期只提示一次：这是全局开关，调用期反复告警会淹没日志。
            warnings.warn(
                "Client(validate=False) 已关闭单位量级与不变量校验；结果仅供口径诊断，"
                "禁止直接用于数值结论。保留守护请去掉该参数；MCP 侧可查 meta.guards_off。",
                RuntimeWarning, stacklevel=2)
        self._sleep = time.sleep  # 测试注入点：不真实等待
        self._uniform = __import__("random").uniform
        self._token_lock = threading.Lock()
        self._token: str = ""
        self._token_exp: float = 0.0

    # ---- 凭证 ----
    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **kw: Any) -> "Client":
        """从环境解析凭据构造客户端；凭据双缺时自动回落匿名试用（免注册可用）。

        解析顺序：显式参数 > 环境变量（``WMSHARE_*``）> 凭据文件（``WMSHARE_CREDENTIALS``）。
        双缺时自动申领匿名额度并落盘独立文件（不覆盖付费凭据）；服务端未开放时
        保持「缺少凭证」报错。``WMSHARE_DISABLE_ANON=1`` 关闭回落。
        """
        e = dict(os.environ if env is None else env)
        cred_file = Path(e.get("WMSHARE_CREDENTIALS", DEFAULT_CREDENTIAL_PATH))
        # 解析与权限检查统一走 _credentials.py（MCP 侧 credential_values 同用）。
        for k, v in read_credentials_file(cred_file, env=e).items():
            e.setdefault(k, v)
        base = e.get("WMSHARE_BASE_URL") or e.get("OPEN_PLATFORM_BASE_URL")
        cid = e.get("WMSHARE_CLIENT_ID") or e.get("OPEN_PLATFORM_CLIENT_ID")
        sec = e.get("WMSHARE_CLIENT_SECRET") or e.get("OPEN_PLATFORM_CLIENT_SECRET")
        # 环境变量只在显式参数缺省时注入；凭证成对性由 __init__ 校验（部分配置报错）
        if base:
            kw.setdefault("base_url", base)
        if cid:
            kw.setdefault("client_id", cid)
        if sec:
            kw.setdefault("client_secret", sec)
        # 登录墙拆除（2.7.0）：全部缺省时尝试匿名试用回落——「缺少凭证」报错只在
        # 回落不可用时触达（服务端未开放该功能，或用户显式 WMSHARE_DISABLE_ANON）。
        if not str(kw.get("client_id") or "").strip() and not str(kw.get("client_secret") or "").strip():
            client = cls._anonymous_fallback(e, kw)
            if client is not None:
                return client
        return cls(**kw)

    @classmethod
    def _anonymous_fallback(cls, env: dict[str, str], kw: dict[str, Any]) -> "Client | None":
        """凭据双缺时尝试匿名试用回落；返回 ``None`` 表示不回落（走原报错路径）。

        - 本地已存匿名凭据 → 直接复用（零网络）；
        - 否则向服务端申领并落盘（独立文件，永不覆盖付费凭据）；
        - 服务端未开放匿名试用（404 ``anon_unavailable``）→ 返回 ``None``，
          from_env 落回原「缺少凭证」报错——错误口径与未拆墙时一致；
        - 名额满 / 网络失败等其他错误 → 抛 ``AuthError`` 合并注册指引。
        """
        from wmshare._anon import (  # 局部导入：回落是可选路径，主构造路径不承担其成本
            anon_credentials_path,
            load_anon_credentials,
            request_anon_credentials,
            save_anon_credentials,
        )

        if str(env.get("WMSHARE_DISABLE_ANON", "")).strip().lower() not in ("", "0", "false", "no", "off"):
            return None
        # 匿名凭据路径跟随 env 字典（与 WMSHARE_CREDENTIALS 同语义，便于测试隔离）。
        path_override = env.get("WMSHARE_ANON_CREDENTIALS", "").strip() or None

        saved = load_anon_credentials(Path(path_override) if path_override else None)
        if saved is not None:
            kw.setdefault("client_id", saved["client_id"])
            kw.setdefault("client_secret", saved["client_secret"])
            client = cls(**kw)
            client.anon_credentials_path = saved.get("path") or str(  # type: ignore[attr-defined]
                Path(path_override) if path_override else anon_credentials_path())
            return client

        base = str(kw.get("base_url") or DEFAULT_BASE_URL)
        try:
            creds = request_anon_credentials(base)
        except AuthError as exc:
            if getattr(exc, "code", "") == "anon_unavailable":
                return None  # 服务端未开放该功能：保持既有「缺少凭证」报错口径
            raise AuthError(
                f"自动领取匿名试用凭据失败：{exc}\n"
                "可稍后重试；或到 https://open.winmale.com 注册免费账号并配置凭据。",
                code=getattr(exc, "code", None) or "anon_failed",
            ) from None
        except TransportError as exc:
            raise AuthError(
                f"自动领取匿名试用凭据失败（网络错误：{exc}）；"
                "请检查网络后重试，或到 https://open.winmale.com 注册免费账号并配置凭据。",
                code="anon_failed",
            ) from None
        path = save_anon_credentials(
            creds, Path(path_override) if path_override else anon_credentials_path())
        kw.setdefault("client_id", creds["client_id"])
        kw.setdefault("client_secret", creds["client_secret"])
        client = cls(**kw)
        # 便于调用方提示用户额度与凭据位置（不参与鉴权）。
        client.anon_credentials_path = str(path)  # type: ignore[attr-defined]
        return client

    @classmethod
    def anonymous(cls, *, refresh: bool = False, **kw: Any) -> "Client":
        """用匿名试用凭据构造客户端（免注册；一次性额度，对齐正常注册用户免费档）。

        首次调用向服务端申领一份匿名凭据并写入 ``~/.wmshare/anon_credentials.env``
        （**与付费凭据文件分离**，不会覆盖 ``credentials.env``）。之后直接复用本地
        凭据，不再消耗申领名额。``Client.from_env()`` 在凭据双缺时会自动走同一条
        回落链——通常无需显式调用本方法。

        匿名额度是「一次性给足、用完即止」（额度与限频、单次上限对齐正常注册用户的
        免费档，具体数值以服务端返回的 ``ec_balance`` 为准）——服务端不会为匿名应用
        周补满。凭据对应的匿名应用由服务端在创建 7 天后自动清理（TTL）；届时本地凭据
        会失效（401/配额类错误），用 ``Client.anonymous(refresh=True)`` 重新申领一份
        即可（受当日发放名额限制）。需要长期额度请到 https://open.winmale.com 注册免费账号。

        :param refresh: 忽略本地已存凭据，重新申领一份。
        :raises AuthError: 服务端未开放匿名试用、今日名额已满，或本网络领取次数超限。
        """
        from wmshare._anon import (
            anon_credentials_path,
            load_anon_credentials,
            request_anon_credentials,
            save_anon_credentials,
        )

        if not refresh:
            saved = load_anon_credentials()
            if saved is not None:
                kw.setdefault("client_id", saved["client_id"])
                kw.setdefault("client_secret", saved["client_secret"])
                return cls(**kw)

        base = kw.get("base_url") or os.environ.get("WMSHARE_BASE_URL") or DEFAULT_BASE_URL
        creds = request_anon_credentials(base)
        path = save_anon_credentials(creds, anon_credentials_path())
        kw.setdefault("client_id", creds["client_id"])
        kw.setdefault("client_secret", creds["client_secret"])
        client = cls(**kw)
        # 便于调用方提示用户额度与凭据位置（不参与鉴权）。
        client.anon_credentials_path = str(path)  # type: ignore[attr-defined]
        return client

    # ---- 传输 ----
    RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

    def _quota_code(self, resp: requests.Response) -> str:
        """429 响应体里的服务端 error.code 若属配额终态则原样返回，否则空串。"""
        if resp.status_code != 429:
            return ""
        code, _ = self._error_detail(resp)
        return code if code in QUOTA_CODES else ""

    def _retry_after(self, resp: requests.Response | None) -> float | None:
        if resp is None or not hasattr(resp, "headers"):
            return None
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return None

    def _delay(self, attempt: int, resp: requests.Response | None) -> float:
        """退避秒数：优先 Retry-After，其次指数退避；可配置对称 jitter。"""
        retry_after = self._retry_after(resp)
        if retry_after is not None:
            base = min(self.max_retry_after, retry_after)
        else:
            base = min(self.max_retry_after, self.backoff * (2 ** attempt))
        if self.backoff_jitter:
            base *= 1.0 + self._uniform(-self.backoff_jitter, self.backoff_jitter)
        return base

    def _sleep_for_retry(self, attempt: int, resp: requests.Response | None) -> None:
        retry_after = self._retry_after(resp)
        if retry_after is not None and retry_after > self.max_retry_after:
            assert resp is not None  # Retry-After 只会来自响应
            self._raise_http_error(resp, stage="request")
        self._sleep(self._delay(attempt, resp))

    def _post(self, url: str, **kw: Any) -> requests.Response:
        """统一 POST 出口：对真实 requests.Session 关闭自动重定向。

        requests 对 307/308 会携带原 POST body 重放到 Location 指向的新 host；
        OAuth 请求体含 client_secret，构造期 host 白名单拦不住这一步，必须在
        传输层关掉。测试替身（FakeSession）没有 allow_redirects 参数，按能力
        探测，避免为了一个安全修复去改全部测试夹具。
        """
        if isinstance(self.session, requests.Session):
            return self.session.post(url, allow_redirects=False, **kw)
        return self.session.post(url, **kw)

    def _request(self, url: str, **kw: Any) -> requests.Response:
        """POST + 429/5xx 指数退避重试；网络异常同样重试并在耗尽后转 WmshareError。"""
        attempts = self.retries + 1
        last: requests.Response | None = None
        for i in range(attempts):
            try:
                resp = self._post(url, **kw)
            except requests.RequestException as e:
                if i == attempts - 1:
                    raise TransportError(
                        f"网络请求失败（已重试 {self.retries} 次）：{e}。"
                        "请检查网络连接与代理设置（国内直连不稳定时可配置 HTTPS_PROXY）。",
                        code="network") from e
                self._sleep_for_retry(i, None)
                continue
            last = resp
            if resp.status_code in self.RETRY_STATUS and i < attempts - 1:
                if self._quota_code(resp):
                    # 配额终态（周钱包空/当日到顶）：重试无意义，立即终止本次调用。
                    break
                self._sleep_for_retry(i, resp)
                continue
            return resp
        assert last is not None  # 循环必然 return 或 raise
        return last

    def _safe_detail(self, text: str, limit: int = 300) -> str:
        """上游原文先整体脱敏再截断（顺序不可换）。"""
        return _redact(
            text, self.client_id, self.client_secret,
            getattr(self, "_token", ""),
        )[:limit]

    def _error_detail(self, resp: requests.Response) -> tuple[str, str]:
        """从错误响应中尽力提取服务端 code/message（OAuth 与网关两种格式）。

        上游若回显请求体，code/message 里可能含 client_secret；所有分支统一
        脱敏，避免凭证随异常进入 traceback 与 MCP 的 error 信封。
        """
        raw = resp.text or ""
        try:
            doc = resp.json()
        except ValueError:
            return "", self._safe_detail(raw)
        if not isinstance(doc, dict):
            return "", self._safe_detail(raw)
        err = doc.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or "")
            msg = str(err.get("message") or err.get("error_description") or "")
            if code or msg:
                return self._safe_detail(code, 120), self._safe_detail(msg)
        # OAuth 规范风格：{"error": "invalid_client", "error_description": "..."}
        if isinstance(err, str):
            return (
                self._safe_detail(err, 120),
                self._safe_detail(
                    str(doc.get("error_description") or doc.get("message") or "")),
            )
        return "", self._safe_detail(raw)

    def _raise_http_error(self, resp: requests.Response, *, stage: str) -> NoReturn:
        """把 OAuth/eval 的非 200 响应统一映射为 WmshareError，并附 AppID 引导。"""
        status = resp.status_code
        code, detail = self._error_detail(resp)
        label = f"HTTP {status}" + (f"，{code}" if code else "")
        suffix = f"：{detail}" if detail else ""
        if status == 429:
            retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
            wait = f"（建议 {retry_after} 秒后重试）" if retry_after else ""
            if code in QUOTA_CODES:
                # 配额终态透传服务端原串（如 EC_BALANCE_EXHAUSTED），便于程序化
                # except QuotaError 处理；重试已被 _request 抑制。
                raise QuotaError(
                    f"配额耗尽（{label}）{wait}{suffix}。{QUOTA_GUIDANCE}"
                    f"{APPID_GUIDANCE}",
                    code=code, status=status, retry_after=self._retry_after(resp))
            raise LimitError(
                f"请求被限流（{label}）{wait}{suffix}。请稍后重试，或申请自己的 AppID 提升额度。"
                f"{APPID_GUIDANCE}",
                code="rate_limited", status=status, retry_after=self._retry_after(resp))
        if stage == "oauth" and status in (400, 401, 403):
            raise AuthError(
                f"OAuth 认证失败（{label}）{suffix}。"
                f"当前 client_id/client_secret 无效。"
                f"{APPID_GUIDANCE}",
                code=code or "oauth_denied", status=status)
        if status in (401, 403):
            if status == 403 and (code == "POLICY_DENIED" or "策略拒绝" in (detail or "")):
                raise AuthError(
                    f"服务端策略拒绝该调用（{label}）{suffix}。"
                    f"这是 AppID 的接口权限范围限制，与额度/凭证无关，换 AppID 不解决，"
                    f"勿反复重试：请到 open.winmale.com 开放平台检查应用权限，"
                    f"或改用无此权限要求的其他接口。",
                    code=code or "policy_denied", status=status)
            raise AuthError(
                f"认证或权限被拒绝（{label}）{suffix}。"
                f"请检查凭证配置；如未申请，按上方指引注册开放平台领取。"
                f"{APPID_GUIDANCE}",
                code=code or "denied", status=status)
        if status >= 500:
            raise ServerError(
                f"服务端错误（HTTP {status}）{suffix}。已自动重试仍失败，请稍后重试；"
                "若持续出现请携带时间与请求名到项目 issues 反馈。",
                code=code or "server", status=status)
        raise ApiError(f"HTTP {status}{suffix}", code=code or "http", status=status)

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        with self._token_lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            resp = self._request(
                f"{self.base_url}/v1/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                self._raise_http_error(resp, stage="oauth")
            try:
                doc = resp.json()
            except ValueError as e:
                raise ApiError(
                    f"OAuth 响应不是合法 JSON（HTTP {resp.status_code}）："
                f"{self._safe_detail(resp.text, 200)}",
                    code="oauth_response", status=resp.status_code) from e
            if not isinstance(doc, dict):
                raise ApiError(
                    f"OAuth 响应格式异常："
                    f"{self._safe_detail(json.dumps(doc, ensure_ascii=False), 300)}",
                    code="oauth_response", status=resp.status_code)
            data = doc.get("data") or doc
            if not isinstance(data, dict):
                data = {}
            token = data.get("access_token")
            if not token:
                raise AuthError(
                    f"OAuth 未返回 access_token："
                    f"{self._safe_detail(json.dumps(doc, ensure_ascii=False), 300)}。"
                    f"{APPID_GUIDANCE}",
                    code="oauth", status=resp.status_code)
            self._token = token
            self._token_exp = time.time() + float(data.get("expires_in", 3600))
            return token

    def _post_authed(self, path: str, body: dict[str, Any]) -> requests.Response:
        """带 OAuth Bearer 的 POST；401 清令牌刷新后重试一次（仅一次，避免环路）。"""
        url = f"{self.base_url}{path}"

        def call_once() -> requests.Response:
            return self._request(url, json=body, timeout=self.timeout,
                                 headers={"Authorization": f"Bearer {self._get_token()}"})

        resp = call_once()
        if resp.status_code == 401:
            # 令牌可能已失效：清缓存强制刷新后重试一次（仅一次，避免环路）
            self._token = ""
            self._token_exp = 0.0
            resp = call_once()
        return resp

    # ---- eval ----
    def eval(self, xs: str | list[str], *, symbol: str | None = None,
             args: dict | None = None, market: str | None = None,
             mode: str = "call") -> dict:
        """执行 XS，返回完整响应 doc（成功时 data.result 为顶层 return 值）。

        symbol 为求值锚点代码；None 时按客户端市场取默认锚点
        （cn=600519 / hk=00700 / us=AAPL，防 MARKET_MISMATCH）。

        .. warning:: 低层逃生口，不做语法解析、不做白名单，``xs`` 会原样进入
           服务端脚本。**禁止把 LLM 生成或来自不可信输入的字符串传入**；
           Agent 场景请走 ``call()`` / friendly API / MCP 网关（见 SECURITY.md）。
        """
        lines = xs if isinstance(xs, list) else [ln for ln in xs.splitlines() if ln.strip()]
        mk = str(market or self.market or "cn").lower()
        anchor = normalize_symbol(symbol, market=mk, catalog=self.catalog) \
            if symbol is not None else DEFAULT_SYMBOLS.get(mk, "600519")
        body: dict[str, Any] = {
            "symbol": anchor,
            "xs_lines": lines,
            "args": {"print.plain": True, **(args or {})},
            "script_files": {},
            "mode": mode,
        }
        if market := (market or self.market):
            body["market"] = market
        self.last_ec_cost = None  # 每次求值重置：消耗只归因于本次调用
        resp = self._post_authed("/v1/analysis/xs/eval", body)
        if resp.status_code != 200:
            self._raise_http_error(resp, stage="eval")
        try:
            doc = resp.json()
        except ValueError as e:
            raise ApiError(
                f"eval 响应不是合法 JSON（HTTP {resp.status_code}）："
                f"{self._safe_detail(resp.text, 200)}",
                code="response", status=resp.status_code) from e
        if not isinstance(doc, dict):
            raise ApiError(
                f"eval 响应格式异常："
                f"{self._safe_detail(json.dumps(doc, ensure_ascii=False), 300)}",
                code="response", status=resp.status_code)
        if not doc.get("success", True):
            err = doc.get("error") or {}
            code = str(err.get("code") or "eval")
            message = str(err.get("message") or self._safe_detail(
                json.dumps(doc, ensure_ascii=False), 200))
            if code.upper() in QUOTA_CODES:
                # HTTP 200 信封里的配额终态：同样不重试、透传原串。
                raise QuotaError(
                    f"eval 失败：{code} {message}。{QUOTA_GUIDANCE}"
                    f"{APPID_GUIDANCE}", code=code, status=resp.status_code)
            if "RATE" in code.upper() or "QUOTA" in code.upper():
                raise LimitError(
                    f"eval 失败：{code} {message}。"
                    f"请稍后重试，或申请自己的 AppID 提升额度。"
                    f"{APPID_GUIDANCE}", code=code, status=resp.status_code)
            raise ApiError(f"eval 失败: {code} {message}", code=code,
                           status=resp.status_code)
        self._consume_metering(doc)
        return doc

    def _consume_metering(self, doc: dict) -> None:
        """读取网关回传的 EC 消耗（meta.metering["analysis.ec_cost"]），超阈值告警。

        EC 是开放平台的计算量计费单位：多标的脚本按标的数逐票计价，
        批量省的是请求次数不是 EC——大消耗必须当场可见，否则配额会被静默打穿。
        """
        metering = (doc.get("meta") or {}).get("metering") or {}
        ec = metering.get("analysis.ec_cost")
        if not isinstance(ec, (int, float)) or isinstance(ec, bool) or ec <= 0:
            return
        self.last_ec_cost = int(ec)
        if self.ec_warn_threshold is not None and self.last_ec_cost >= self.ec_warn_threshold:
            warnings.warn(
                f"本次 eval 消耗 {self.last_ec_cost} EC（提示阈值 {self.ec_warn_threshold}）。"
                "EC 按计算量计费：多标的脚本按标的数逐票计价，批量省请求次数不省 EC；"
                "全市场快照类数据优先用服务端一次取数接口（如 cli.moneyflow.board()），"
                "或缩小标的范围。Client(ec_warn_threshold=None) 可关闭本提示。",
                stacklevel=3)

    def eval_result(self, xs: str | list[str], **kw: Any) -> Any:
        doc = self.eval(xs, **kw)
        data = doc.get("data") or {}
        return data.get("result")

    # ---- 目录驱动的调用门面 ----
    def _canon_symbol(self, symbol: str) -> str:
        """标的代码归一：按客户端市场消解美股交易所后缀与类别股写法（见 normalize_symbol）。"""
        return normalize_symbol(symbol, market=self.market, catalog=self.catalog)

    def _resolve_function(self, name: str) -> dict:
        """目录函数查找；把「指标码当函数名」误用补成可执行的指引。"""
        try:
            return self.catalog.function(name)
        except CatalogError as e:
            if name.split(".", 1)[0] == "indicator":
                raise CatalogError(
                    f"{e}\n提示：调用入口只接受目录函数名（cat.functions_by_domain() 可查）；"
                    "指标码不是函数名——一票多码用 cli.indicator.metrics(sym, codes)，"
                    "全市场指标请逐票调用。", code="function") from e
            raise

    def _require_lines(self, name: str) -> list[str]:
        """函数命名空间不在 sys/init 预载链时，自动补 xs.require（幂等）。"""
        ns = name.split(".", 1)[0]
        inv = self.catalog.inventory
        if ns in (inv.get("preloaded_libs") or []):
            return []
        entry = (inv.get("domains") or {}).get(ns, {}).get("entry")
        return [f'xs.require("{entry}")'] if entry else []

    # 标的参数自动归一；stock_code 用于 notice.query_find 等底层函数。
    # 批量识别只用 BATCH_SYMBOL_PARAMS，避免把 stock_code 误当成可批量首个参数。
    # code 是 cbond/macro 域对标的参数的叫法（cbond.call_hits(code, trig)），
    # 与 sym/stk 同义，同样归一代码写法。
    SYMBOL_PARAMS = ("sym", "symbol", "stk", "stock_code", "code")
    BATCH_SYMBOL_PARAMS = ("sym", "symbol", "stk", "code")
    # 通用别名 → 函数实际参数名：用户按目录习惯写 symbol= / sym= 时自动落到该
    # 函数的真实标的名（cbond.of_stock 叫 stk、cbond.call_hits 叫 code）。
    SYMBOL_ALIASES = ("symbol", "sym")

    def _resolve_symbol_alias(self, name: str, params: list[dict],
                              kwargs: dict[str, Any]) -> dict[str, Any]:
        """把通用的 symbol= / sym= 落到该函数真实的标的名上。

        目录里标的参数叫法不统一（kline 用 sym、cbond.of_stock 用 stk、
        cbond.call_hits 用 code）。用户不该为此记三套名字，故：
        函数有唯一标的名、且该名未被传、且恰好传了一个别名时，改名。
        歧义（同时传 sym= 与 symbol=）或函数没有标的名时不动，交给常规校验报错。
        """
        sym_names = [p["name"] for p in params if p["name"] in self.SYMBOL_PARAMS]
        if len(sym_names) != 1:
            return kwargs
        real = sym_names[0]
        if real in kwargs:
            return kwargs
        given = [a for a in self.SYMBOL_ALIASES if a in kwargs]
        if len(given) != 1 or given[0] == real:
            return kwargs
        out = dict(kwargs)
        out[real] = out.pop(given[0])
        return out

    def _build_call_line(self, name: str, params: list[dict], kwargs: dict[str, Any],
                         *, sym_override: str | None = None,
                         sym_param: str | None = None) -> str:
        """校验参数并生成单次调用字面量（含标的一体化归一）。"""
        def _validate(p: dict, value: Any) -> None:
            kind = p.get("type", "any")
            valid = True
            if kind == "string":
                valid = isinstance(value, str)
            elif kind == "int":
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif kind == "float":
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(float(value)))
            elif kind == "bool":
                valid = isinstance(value, bool)
            elif kind == "array":
                valid = isinstance(value, (list, tuple))
            elif kind == "object":
                valid = isinstance(value, dict)
            if not valid:
                raise UsageError(
                    f"{name}: 参数 {p['name']} 需要 {kind}，收到 {type(value).__name__}",
                    code="params")
            allowed = p.get("enum")
            if allowed is not None and value not in allowed:
                raise UsageError(
                    f"{name}: 参数 {p['name']}={value!r} 不在允许值 {allowed} 内",
                    code="params")

        known = {p["name"] for p in params}
        unknown = set(kwargs) - known
        if unknown:
            raise UsageError(f"{name}: 未知参数 {sorted(unknown)}；合法参数 {sorted(known)}",
                             code="params")
        for p in params:
            provided = p["name"] in kwargs or (sym_override is not None and p["name"] == sym_param)
            if p["name"] in kwargs:
                _validate(p, kwargs[p["name"]])
            if not provided and "default" not in p and p.get("required"):
                raise UsageError(f"{name}: 缺少必填参数 {p['name']}", code="params")
        if self.max_limit is not None:
            for p in params:
                if p["name"] in ("limit", "lim") and p["type"] == "int":
                    v = kwargs.get(p["name"], p.get("default"))
                    if isinstance(v, int) and not isinstance(v, bool) and v > self.max_limit:
                        raise LimitError(
                            f"{name}: {p['name']}={v} 超过单次请求上限 {self.max_limit}"
                            "（防止单次拉取过大；可在 Client(max_limit=...) 调整，设 None 关闭）",
                            code="limit")
        def _provided(p: dict) -> bool:
            return p["name"] in kwargs or (sym_override is not None and p["name"] == sym_param)

        last_provided = max((i for i, p in enumerate(params) if _provided(p)), default=-1)
        args = []
        for i, p in enumerate(params):
            if sym_override is not None and p["name"] == sym_param:
                args.append(_xs_literal(self._canon_symbol(sym_override)))
            elif p["name"] in kwargs:
                v = kwargs[p["name"]]
                # 标的参数不论目录声明为 string 还是 any 都要归一：
                # cbond.* / macro.* 的标的名在 xs 侧是 any 类型，
                # 只按 type=="string" 判断会漏掉，导致 "601009.SH" 原样下发。
                if p["name"] in self.SYMBOL_PARAMS and isinstance(v, str):
                    v = self._canon_symbol(v)
                args.append(_xs_literal(v))
            elif "default" in p:
                args.append(_xs_literal(p["default"]))
            elif i < last_provided:
                # 中段未传且无目录 default：补 nil 保位。调用字面量按位置绑定，
                # 跳过中段参数会把后值错绑到前槽（曾把 payout_max 绑进 payout_min）。
                args.append("nil")
        return f"{name}({', '.join(args)})"

    def call(self, name: str, /, _raw: bool = False,
             _units: str = "base", _fields: Any = None, **kwargs: Any) -> Any:
        """按目录合同调用目录内函数：校验参数 → 生成 XS（自动 require + 规范化）→ eval(call)。

        底层入口保持**规范化行数组**（list[dict]/dict/标量）；DataFrame 默认
        转换在门面层（``cli.ns.method`` → ``to_output_frame``）完成，2.0 起
        本方法不再提供 ``_df``。选项以下划线开头，避免与 XS 参数名冲突：
          _raw=True        跳过 normalize_with 与单位换算，返回 store 原始 Unit
          _units="native"  保留脚本输出的原有单位（字段名仍规范化）；默认 "base" 把
                           目录声明的非基础单位换算为小数/元/股，并做量级与不变量校验
          _fields=...      列投影：只保留指定字段（list 或逗号串），按请求顺序输出；
                           未知字段报 UsageError。在换算之后执行，不改变口径、不降 EC
        参数合同：优先用域目录精修 params；L1 精简条目回退到 inventory 的签名参数。
        标的参数（sym/symbol/stk）自动归一：去 cn./sh./sz./bj. 前缀与 .SH/.SZ/.BJ 后缀。
        """
        if _units not in ("base", "native"):
            raise UsageError('_units 只支持 "base"（默认，换算基础单位）或 "native"（脚本原值）',
                             code="units")
        _normalize_field_list(_fields)  # 早失败：格式错误在发请求前就报
        fn = self._resolve_function(name)
        params = fn.get("params") or self.catalog.inventory_params(name)
        kwargs = self._resolve_symbol_alias(name, params, kwargs)
        # 传列表即批量：标的参数收到 list/tuple 自动转批量。
        # 命中 BATCH_NATIVE_ROUTES 且票数达 native_batch_min 时走批量原生实现
        # （单次 eval、EC 按量）；否则转 call_batch 拼接（≤500，超限 LimitError）。
        for p in params:
            v = kwargs.get(p["name"])
            if (p["name"] in self.BATCH_SYMBOL_PARAMS
                    and isinstance(v, (list, tuple))):
                rest = {k: w for k, w in kwargs.items() if k != p["name"]}
                syms = list(v)
                if self.native_batch and name in BATCH_NATIVE_ROUTES \
                        and len(syms) >= self.native_batch_min:
                    return self._call_native_batch(name, syms, _raw=_raw,
                                                   _units=_units,
                                                   _fields=_fields, **rest)
                return self.call_batch(name, syms, _raw=_raw,
                                       _units=_units, _fields=_fields, **rest)
        call_line = self._build_call_line(name, params, kwargs)
        normalizer = fn.get("normalize_with")
        if normalizer and not _raw:
            lines = [f"__r := {call_line}", f"return {normalizer}(__r)"]
        else:
            lines = [f"return {call_line}"]
        xs = self._require_lines(name) + lines
        symbol = DEFAULT_SYMBOLS.get(str(self.market or "cn").lower(), "600519")
        for p in params:
            if p["name"] in kwargs and p["name"] in self.SYMBOL_PARAMS:
                symbol = self._canon_symbol(str(kwargs[p["name"]]))
                break
        result = self.eval_result(xs, symbol=symbol)
        if not _raw and _units == "base":
            result = apply_units(result, fn, fname=name, validate=self._validate,
                                 market=self.market, symbol=symbol)
        return project_fields(result, _fields, fname=name)

    def _call_native_batch(self, name: str, syms: list[str], *, _raw: bool = False,
                           _units: str = "base", _fields: Any = None,
                           **kwargs: Any) -> BatchResult:
        """批量原生路由：单次 eval 调批量实现，适配回逐票合同。

        与拼接（call_batch raise 模式）同返回 BatchResult，但 EC 按量计费——
        如 kline.snapshot 拼接是 N×均线首算 10,250 EC/票，snapshot_batch ≈58 EC/票。
        on_error="skip" 不走此路径（原生批量无法逐票隔离错误）。
        _raw=True 跳过单位换算（返回未换算的原始值 MAP，仍为逐票 dict）。
        results 值保持逐票 MAP（2.0 门面层的 ``to_output_frame`` 才做 DF 转换）。
        """
        impl, adapter = BATCH_NATIVE_ROUTES[name]
        impl_fn = self._resolve_function(impl)
        arr_param = next((p["name"] for p in (impl_fn.get("params") or [])
                          if p.get("type") == "array"), None)
        if arr_param is None:
            raise UsageError(f"{impl}: 批量原生实现缺少数组参数", code="params")
        # 与 call_batch 同口径：归一 + 去重（保持首现顺序）；跨市场混批同拒。
        syms = list(dict.fromkeys(self._canon_symbol(s) for s in syms))
        if not syms:
            return BatchResult(requested=0)
        self._assert_same_market(name, syms)
        # 准全市场清单走空参捷径：服务端全市场扫描 + 客户端过滤，
        # 省掉数千元素数组字面量的求值计费（实测 5,693 票 ≈11 万 EC）。
        # 捷径语义 = 服务端「非停牌全市场」，停牌/ETF/无效票静默缺席。
        shortcut = len(syms) >= NATIVE_FULL_MARKET_MIN
        arr_kwargs: dict[str, Any] = {arr_param: [] if shortcut else list(syms)}
        raw = self.call(impl, _raw=True, **arr_kwargs, **kwargs)
        adapted = adapter(raw, syms, name, allow_missing=shortcut)
        if not _raw and _units == "base":
            adapted = apply_units(adapted, self._resolve_function(name), fname=name,
                                  validate=self._validate, market=self.market,
                                  symbol=syms[0])
        missing = [s for s in syms if s not in adapted]
        result = BatchResult(results=adapted, requests=1, requested=len(syms),
                             ec_cost=self.last_ec_cost or 0, truncated=bool(missing))
        return _project_batch(result, _fields, fname=name)

    def call_batch(self, name: str, symbols: list[str], /, on_error: str = "raise",
                   _raw: bool = False, _units: str = "base",
                   _fields: Any = None, **kwargs: Any) -> BatchResult:
        """同一目录函数在多个标的上的批量调用（results 值保持行数组；``to_df()`` 出长表）。

        on_error="raise"（默认）：把所有标的组装成**一次** eval（map 字面量），单次 HTTP；
        任一标的失败则整体抛出（服务端无 try/catch，无法在单次请求内隔离）。
        on_error="skip"：逐标的调用并捕获错误，成功项进 results、失败项进 errors（N 次 HTTP）。
        批量原生路由（BATCH_NATIVE_ROUTES，如 kline.snapshot → kline.snapshot_batch）：
        raise 模式不再拼接，改为单次 eval 调批量实现并适配回逐票合同——EC 按量
        （≈58 EC/票）而非 N×单票首算（10,250/票）；skip 模式恒为逐票拼接。
        _raw/_units 语义与 call() 一致（_units="native" 时跳过单位换算）。
        _fields 语义与 call() 一致：逐标的做列投影（标量结果保持原样）。
        """
        if on_error not in ("raise", "skip"):
            raise UsageError('on_error 只支持 "raise" 或 "skip"', code="params")
        if _units not in ("base", "native"):
            raise UsageError('_units 只支持 "base"（默认，换算基础单位）或 "native"（脚本原值）',
                             code="units")
        fn = self._resolve_function(name)
        params = fn.get("params") or self.catalog.inventory_params(name)
        sym_param = next((p["name"] for p in params
                          if p["name"] in self.BATCH_SYMBOL_PARAMS), None)
        if sym_param is None:
            raise UsageError(f"{name}: 没有标的参数（sym/symbol/stk/code），不支持批量调用",
                             code="params")
        if sym_param in kwargs:
            raise UsageError(f"{name}: 批量调用请用 symbols 指定标的，不要在 kwargs 传 {sym_param}",
                             code="params")
        syms = list(dict.fromkeys(self._canon_symbol(s) for s in symbols))
        if not syms:
            return BatchResult()
        requested = len(syms)
        self._assert_same_market(name, syms)
        # 批量原生路由（raise 模式）：单次 eval 调批量实现，EC 按量而非 N×单票放大。
        # 置于 max_limit 检查之前——原生路径单次 eval 可承载全市场清单，不受拼接 500 上限。
        route = BATCH_NATIVE_ROUTES.get(name)
        if (on_error == "raise" and self.native_batch and route is not None
                and len(syms) >= self.native_batch_min):
            return self._call_native_batch(name, syms, _raw=_raw, _units=_units,
                                           _fields=_fields)
        if self.max_limit is not None and len(syms) > self.max_limit:
            raise LimitError(
                f"{name}: 批量标的数 {len(syms)} 超过上限 {self.max_limit}"
                f"（请分批，如 codes[i:i+{self.max_limit}]；"
                "或直接用 batch_all() 自动分批、batch_iter() 逐批处理）",
                code="limit")
        if on_error == "skip":
            results: dict[str, Any] = {}
            errors: dict[str, str] = {}
            error_details: dict[str, BatchError] = {}
            for s in syms:
                try:
                    results[s] = self.call(name, _raw=_raw, _units=_units,
                                           _fields=_fields, **kwargs,
                                           **{sym_param: s})
                except WmshareError as e:
                    errors[s] = str(e)
                    error_details[s] = BatchError(
                        key=s, message=str(e), code=getattr(e, "code", ""),
                        status=getattr(e, "status", None),
                        retryable=(getattr(e, "status", None) in self.RETRY_STATUS
                                   or isinstance(e, (TransportError, ServerError))),
                    )
            # skip 模式逐票请求：N 个标的 = N 次请求（会快速耗尽限流额度）
            return BatchResult(results=results, errors=errors, requests=len(syms),
                               requested=requested, error_details=error_details)

        normalizer = fn.get("normalize_with")
        if name not in BATCH_NATIVE_ROUTES and len(syms) >= SPLICE_WARN_MIN:
            # 拼接护栏：EC 随票数线性放大（如均线首算类接口 10,250 EC/票 × N）。
            # 仅提示不阻断——数据量驱动型接口（如资金流全历史）本就该批量拉。
            warnings.warn(
                f"{name}: 逐票拼接 {len(syms)} 票进单次 eval，总 EC 按票数放大；"
                "若该接口单票成本高请优先使用批量原生接口（如 kline.snapshot_batch），"
                "否则建议分批 + 增量拉取。",
                stacklevel=3)
        pairs = []
        for s in syms:
            line = self._build_call_line(name, params, kwargs, sym_override=s, sym_param=sym_param)
            pairs.append(f'{_xs_literal(s)}: {normalizer}({line})' if normalizer and not _raw
                         else f"{_xs_literal(s)}: {line}")
        xs = self._require_lines(name) + [f"return {{{', '.join(pairs)}}}"]
        result = self.eval_result(xs, symbol=syms[0])
        if not isinstance(result, dict):
            raise ApiError(f"{name}: 批量返回不是 MAP（{type(result).__name__}）", code="batch")
        missing = [sym for sym in syms if sym not in result]
        if missing:
            raise ApiError(
                f"{name}: 批量返回缺少 {len(missing)} 个标的：{missing[:10]}"
                + (f" 等 {len(missing)} 个" if len(missing) > 10 else ""),
                code="batch_missing",
            )
        if not _raw and _units == "base":
            for s, v in result.items():
                result[s] = apply_units(v, fn, fname=name, validate=self._validate,
                                        market=self.market, symbol=s)
        # raise 模式把 N 个标的压进一次 eval：1 次请求
        out = BatchResult(results=result, requests=1, requested=requested,
                          ec_cost=self.last_ec_cost or 0)
        return _project_batch(out, _fields, fname=name)

    # ---- 分批执行器（批量绕开 429 的正式入口） ----
    def _assert_same_market(self, name: str, syms: list[str]) -> None:
        """批量代码必须同属客户端市场——跨市场混批会取到错误数据。

        实测（2026-10-29）：cn 客户端批量混入 00700 不报错，但该港股标的的 close/percent
        与 hk 客户端结果不符（387.6 vs 377.6、+0.62% vs -2.58%，连涨跌方向都相反）——
        网关只校验请求锚点（xs_eval_target.go 的 checkMarketMatch），xs_lines 内代码
        不校验，本市场引擎上下文解析他市场符号会走错数据管线。

        仅当代码出现在**其他市场代码表**时报错；代码表里都没有（新股/ETF）放行，
        不误伤。常规同市场批量只加载本市场代码表（毫秒级、带缓存）。
        """
        mk = str(self.market or "cn").lower()
        if mk not in ("cn", "hk", "us"):
            return
        try:
            own = self.catalog.symbols_set(mk)
        except CatalogError:
            return
        missing = [s for s in syms if s not in own]
        if not missing:
            return
        foreign: list[tuple[str, str]] = []
        for om in ("cn", "hk", "us"):
            if om == mk:
                continue
            try:
                other = self.catalog.symbols_set(om)
            except CatalogError:
                continue
            foreign.extend((x, om) for x in missing if x in other)
        if not foreign:
            return
        langs = {"cn": "A 股", "hk": "港股", "us": "美股"}
        sample = "、".join(f"{c}（{langs[m]}）" for c, m in foreign[:5])
        extra = f" 等 {len(foreign)} 个" if len(foreign) > 5 else ""
        raise UsageError(
            f"{name}: 代码 {sample}{extra} 不属于当前市场（Client market={mk}）。"
            "批量不支持跨市场混批——网关只校验请求锚点，他市场代码会在本市场引擎上下文"
            "里走错数据管线，返回的 close/涨跌幅等数值不可信。"
            f"请按市场分别调用 Client(market=\"cn\"/\"hk\"/\"us\")："
            "A 股全市场 12 批 + 港股 6 批 + 美股 11 批 = 29 次请求。",
            code="market")

    def _batch_size(self, batch_size: int | None, name: str) -> int:
        size = int(batch_size) if batch_size is not None else (self.max_limit or 500)
        if size <= 0:
            raise UsageError(f"{name}: batch_size 必须为正整数，收到 {size}", code="params")
        if self.max_limit is not None and size > self.max_limit:
            raise UsageError(
                f"{name}: batch_size={size} 超过单批上限 {self.max_limit}"
                f"（单批最大 {self.max_limit} 个标的；可调 Client(max_limit=...)）",
                code="params")
        return size

    def batch_iter(self, name: str, symbols: Any, /, batch_size: int | None = None,
                   on_batch_error: str = "raise", _raw: bool = False,
                   _units: str = "base", _fields: Any = None,
                   **kwargs: Any) -> Iterator[BatchResult]:
        """分批执行器（逐批产出）：N 个标的切成 ⌈N/batch_size⌉ 批，每批一次 HTTP。

        解决 429 的正解——服务端按**请求次数**限流（免费档 500 次/小时、
        5000 次/日），逐票取全市场（A 股 5691 家）必然撞墙；分批后只需 12 次请求。
        逐批 yield 便于边取边落盘、显示进度、随时中断（``break`` 即可）。

        :param name: 目录函数名（如 ``"kline.snapshot"``），**位置参数**
        :param symbols: 标的代码序列，**位置参数**（如 ``[r["symbol"] for r in cli.stocks.list()]``）。
            必须同属 ``Client(market=...)`` 的市场——跨市场混批会报 ``UsageError``
            （他市场代码在本市场引擎上下文里会取到错误数值）；跨市场请分别建 Client。
        :param batch_size: 每批标的数，默认 ``Client(max_limit=500)``；须 ≤ max_limit
        :param on_batch_error: **批级**容错（与 ``call_batch`` 的票级 ``on_error`` 不同）：
            ``"raise"``（默认）任一批失败即抛；``"skip"`` 跳过失败批继续
            （失败批记进 ``errors``，键形如 ``batch#3[1000:1500]``）。
        :param _raw: 跳过规范化与单位换算，返回上游原始行
        :param _units: ``"base"``（默认，换算基础单位并校验）/ ``"native"``（脚本原值）
        :returns: 逐批 ``BatchResult``（``requests`` 恒为 1）

        限流（HTTP 429）在任何模式下都**停止并给出续跑位置**（消息含已完成标的数与
        ``codes[done:]`` 切片）——配额是时间窗口，继续跑只会连续失败。
        参数错误在**调用时**立即抛出（不等待首次迭代）。
        """
        if on_batch_error not in ("raise", "skip"):
            raise UsageError('on_batch_error 只支持 "raise" 或 "skip"', code="params")
        if "_df" in kwargs:
            # 2.0 起 call() 已无 _df；批量入口的 results 恒为行数组，
            # 这里显式拦截以防 _df 被当成 XS 参数下发（报错更可读）。
            raise UsageError(
                f"{name}: 批量入口不支持 _df（2.0 已移除）——results 保持规范化行数组；"
                "长表用 BatchResult.to_df()（每标的一行），"
                "门面级 DataFrame 请逐批对 results 取值后自转。", code="params")
        size = self._batch_size(batch_size, name)
        syms = list(dict.fromkeys(self._canon_symbol(s) for s in symbols))
        self._assert_same_market(name, syms)
        return self._batch_iter(name, syms, size, on_batch_error,
                                _raw=_raw, _units=_units, _fields=_fields, **kwargs)

    def _batch_iter(self, name: str, syms: list[str], size: int,
                    on_batch_error: str, *, _raw: bool = False,
                    _units: str = "base", _fields: Any = None,
                    **kwargs: Any) -> Iterator[BatchResult]:
        """batch_iter 的生成器实体（参数已在外壳校验，错误早暴露）。"""
        if not syms:
            return
        total = (len(syms) + size - 1) // size
        for idx, chunk in enumerate(_chunked(syms, size), start=1):
            start = (idx - 1) * size
            try:
                # 批内必须是 raise 模式：整批压进一次请求
                part = self.call_batch(name, chunk, on_error="raise",
                                       _raw=_raw, _units=_units,
                                       _fields=_fields, **kwargs)
                part.ec_cost = self.last_ec_cost or part.ec_cost
                yield part
            except QuotaError as e:
                # 配额耗尽（周钱包空/当日到顶）：换默认应用凭证或等周补/充值后，
                # 从断点续跑；限流的「500 次/小时」文案对配额场景是误导。
                raise QuotaError(
                    f"{name}: 第 {idx}/{total} 批配额耗尽（已完成 {start} / {len(syms)} 个标的）。"
                    f"{QUOTA_GUIDANCE}"
                    f"恢复后请续跑：batch_all({name!r}, codes[{start}:])。"
                    f"原始错误：{e}", code=getattr(e, "code", ""), status=429,
                    retry_after=getattr(e, "retry_after", None)) from e
            except LimitError as e:
                if getattr(e, "code", "") == "rate_limited" or getattr(e, "status", None) == 429:
                    raise LimitError(
                        f"{name}: 第 {idx}/{total} 批触发限流（已完成 {start} / {len(syms)} 个标的）。"
                        "服务端按请求次数限流（免费档 500 次/小时、5000 次/日）；"
                        f"请稍后续跑：batch_all({name!r}, codes[{start}:])；"
                        "或调大 batch_size 减少请求次数、申请更高档位。"
                        f"原始错误：{e}", code="rate_limited", status=429,
                        retry_after=getattr(e, "retry_after", None)) from e
                raise
            except WmshareError as e:
                if on_batch_error == "skip":
                    key = f"batch#{idx}[{start}:{start + len(chunk)}]"
                    yield BatchResult(
                        errors={key: str(e)}, requests=1, requested=len(chunk),
                        error_details={key: BatchError(
                            key=key, message=str(e), code=getattr(e, "code", ""),
                            status=getattr(e, "status", None),
                            retryable=(getattr(e, "status", None) in self.RETRY_STATUS
                                       or isinstance(e, (TransportError, ServerError))),
                        )},
                    )
                    continue
                raise

    def batch_all(self, name: str, symbols: Any, /, batch_size: int | None = None,
                  on_batch_error: str = "raise", _raw: bool = False,
                  _units: str = "base", _fields: Any = None,
                  **kwargs: Any) -> BatchResult:
        """一站式分批取数：自动切片并聚合为单个 ``BatchResult``。

        ``cli.batch_all("kline.snapshot", [r["symbol"] for r in cli.stocks.list()])``
        → A 股 5691 家一次 eval（批量原生路由接口不分批；非路由接口按 500/批，
        如 12 次请求而非 5691 次），一次跑完不撞限流。

        :param name: 目录函数名，**位置参数**
        :param symbols: 标的代码序列，**位置参数**（须同属客户端市场，跨市场混批报错）
        :param batch_size: 每批标的数，默认 ``Client(max_limit=500)``
        :param on_batch_error: **批级**容错（``"skip"`` 跳过失败批），与 ``batch_iter`` 一致
        :param _raw: 跳过规范化与单位换算
        :param _units: ``"base"``（默认）/ ``"native"``
        :param _fields: 逐标的列投影（语义同 ``call(_fields=...)``）
        :returns: ``BatchResult``——``results`` 聚合全部批次、``errors`` 含失败批、
            ``requests`` 为实际请求次数（可直接对比标的数看省了多少次配额）

        长表用 ``.to_df()``（每标的一行）；多行历史类数据（``bars``/``history``）
        建议改用 ``batch_iter`` 边取边落盘，或读 ``results[代码]``。
        """
        # 批量原生路由接口不分批：单次 eval 可承载全市场清单，切片反而多次点查。
        if self.native_batch and name in BATCH_NATIVE_ROUTES \
                and on_batch_error != "skip":
            syms = list(dict.fromkeys(self._canon_symbol(s) for s in symbols))
            return self.call_batch(name, syms, _raw=_raw, _units=_units,
                                   _fields=_fields)
        out = BatchResult()
        for part in self.batch_iter(name, symbols, batch_size=batch_size,
                                    on_batch_error=on_batch_error, _raw=_raw,
                                    _units=_units, _fields=_fields, **kwargs):
            out.results.update(part.results)
            out.errors.update(part.errors)
            out.requests += part.requests
            out.requested += part.requested
            out.error_details.update(part.error_details)
            out.ec_cost += part.ec_cost
            out.truncated = out.truncated or part.truncated
        return out

    # ---- EC 成本预估（2.0：计费透明度前置；模型本体在模块级 estimate_cost）----
    # 保留类属性别名，避免既有第三方代码按 Client._EC_PER_ROW 取值时断掉。
    _EC_PER_ROW = EC_PER_ROW
    _EC_SCREENER_BASE = EC_SCREENER_BASE
    _EC_SCREENER_HEAVY = EC_SCREENER_HEAVY
    _EC_SCREENER_COLD_NOTE = EC_SCREENER_COLD_NOTE
    _EC_HEAVY_SCREENER_TOKENS = EC_HEAVY_SCREENER_TOKENS

    def cost_estimate(self, name: str, /, **params: Any) -> dict:
        """预估一次调用的 EC 消耗区间（按请求行数/列物化的经验模型）。

        返回 ``{"name", "requests", "ec_lo", "ec_hi", "model", "note"}``；
        没有成本模型的接口如实返回 ``ec_lo=ec_hi=None``（绝不编造数字）。
        估算不含预热缓存的复跑折扣（如 ``kline.snapshot`` 复跑 ≈26 EC）。
        模型本体是模块级 ``estimate_cost``。
        """
        try:
            self._resolve_function(name)  # 目录函数：合同存在性校验
        except CatalogError:
            pass  # 组合接口（backtest.run/screener.query/valuation.hist_stats 等）不在目录
        return estimate_cost(name, params,
                             native_batch_min=getattr(self, "native_batch_min", 3) or 3)

    def notice_poller(self, *, group: str, consumer: str, on_events: Any = None,
                      **kw: Any) -> "NoticePoller":
        """公告变更订阅轮询器：本地定时器轮询探针，有新公告才拉取、回调、确认。

        消费进度按 (group, consumer) 标识存在服务端，ack 前崩溃会重投
        （at-least-once）。详见 ``wmshare.notice_stream.NoticePoller``。
        """
        from wmshare.notice_stream import NoticePoller
        return NoticePoller(self, group=group, consumer=consumer,
                            on_events=on_events, **kw)

    # ---- 生命周期 ----
    def close(self) -> None:
        """关闭底层 HTTP 会话；调用方注入的 session 由调用方自行管理。"""
        if not self._owns_session:
            return
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __dir__(self) -> list[str]:
        """IDE 补全/交互式探索可见全部命名空间：友好门面 + 类型化门面 + 底层目录。"""
        from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
        return sorted({*super().__dir__(), *FRIENDLY_NAMESPACES,
                       *GENERATED_NAMESPACES, *self.catalog.namespaces()})

    def __getattr__(self, ns: str) -> Any:
        """client.bonus.query_list(...) —— 友好 API 优先，其次类型化门面，最后通用门面。"""
        if ns.startswith("_"):
            raise AttributeError(ns)
        from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
        cls = FRIENDLY_NAMESPACES.get(ns)
        if cls is not None:
            return cls(self)
        gcls = GENERATED_NAMESPACES.get(ns)
        if gcls is not None:
            return gcls(self)
        if ns not in self.catalog.namespaces():
            raise AttributeError(
                f"命名空间 {ns!r} 不在目录中；可用友好入口 "
                f"{sorted(FRIENDLY_NAMESPACES)} 或底层命名空间 {sorted(self.catalog.namespaces())}")
        return _Namespace(self, ns)


class _Namespace:
    def __init__(self, client: Client, ns: str):
        self._client = client
        self._ns = ns

    def __getattr__(self, fname: str) -> Any:
        if fname.startswith("_"):
            raise AttributeError(fname)
        return lambda **kw: self._client.call(f"{self._ns}.{fname}", **kw)
