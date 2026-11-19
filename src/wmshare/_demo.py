"""离线演示客户端：真实 API 固定快照回放，零凭证、不联网。

快照日为 2026-11-16，由维护者用 ``tools/generate_demo_snapshot.py`` 生成。
数据覆盖 examples 的 demo 路径：10 只 A 股演示宇宙 + 当日真实全市场 screener。
它不是实时行情，也不承诺覆盖全部 288 个目录函数；接真实数据用
``wmshare.Client.from_env()``。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from wmshare.backtest import (
    VALUATION_RULES,
    ma_cross_signals,
    run_backtest,
    valuation_by_date,
    valuation_signals,
)
from wmshare.client import BatchResult
from wmshare.errors import UsageError
from wmshare.notice_stream import NoticeStreamEvent

_DATA_PATH = Path(__file__).with_name("_demo_data.json")
_SNAPSHOT_SCHEMA_VERSION = 1
_AS_OF = "2026-11-19"
_CATALOG_REV = "26692375"
_SDK_VERSION = "2.3.1"

# 对外溯源常量：显式 SNAPSHOT_ 前缀，避免把「拍快照时的 SDK 版本」误当成当前版本。
# 保留上面的短名供模块内部快照校验使用（不重拍 _demo_data.json、不改哈希合同）。
SNAPSHOT_AS_OF = _AS_OF
SNAPSHOT_CATALOG_REV = _CATALOG_REV
SNAPSHOT_SDK_VERSION = _SDK_VERSION
SNAPSHOT_SCHEMA_VERSION = _SNAPSHOT_SCHEMA_VERSION
DEMO_SNAPSHOT_PROVENANCE = {
    "as_of": SNAPSHOT_AS_OF,
    "schema_version": SNAPSHOT_SCHEMA_VERSION,
    "snapshot_sdk_version": SNAPSHOT_SDK_VERSION,
    "snapshot_catalog_rev": SNAPSHOT_CATALOG_REV,
}

_UNIVERSE = (
    "600519", "000858", "601088", "600900", "601318",
    "000001", "600036", "000333", "300750", "688981",
)
_MAX_BARS = 120
_MAX_MONEYFLOW_BARS = 30
_MAX_DIVIDEND_HISTORY = 20
_MAX_BANK_MEMBERS = 20
# 期货/宏观罐头（v1.11 后新数据面）：期货已由 2026-11-17 快照覆盖
# （data.futures）；宏观仍为 PROD 活体探针实证值，不在快照采集范围内。
_FUT_CANS: dict[str, float] = {"$FUT_CLOSE": 5354.0, "$FUT_VOLUME": 302888.0}


def _unsupported(name: str, kind: str = "底层函数") -> UsageError:
    """未回放的函数一律显式报错，绝不返回空结果冒充成功（与真实 Client.call 同向）。"""
    return UsageError(
        f"demo 快照不提供{kind} {name!r} 的回放数据；"
        "用 wmshare.load().functions_by_domain() 查可用目录函数，"
        "或改用 Client.from_env() 接真实数据（demo 只回放固定快照，不伪造空结果）",
        code="demo_unsupported",
    )

_SNAPSHOT: dict[str, Any] | None = None


def _is_finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _canonical_data_hash(data: Mapping[str, Any]) -> str:
    payload = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} 必须是 MAP，收到 {type(value).__name__}")
    return value


def _require_rows(value: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{where} 必须是 MAP 行数组")
    return value


def _check_finite(value: Any, where: str) -> None:
    if not _is_finite_number(value):
        raise ValueError(f"{where} 必须是有限数字：{value!r}")


def _check_date_not_after(value: Any, where: str) -> None:
    text = str(value or "")[:10]
    if len(text) != 10 or text > _AS_OF:
        raise ValueError(f"{where} 日期非法或晚于 {text}（as_of={_AS_OF}）")


def _check_date_if_present(value: Any, where: str) -> None:
    if value not in (None, ""):
        _check_date_not_after(value, where)


def _check_url(value: Any, where: str) -> None:
    text = str(value or "")
    if text and not text.startswith("https://"):
        raise ValueError(f"{where} 只允许 HTTPS 或空 URL：{text}")


def _validate_snapshot(document: Any) -> dict[str, Any]:
    doc = _require_mapping(document, "_demo_data.json")
    if doc.get("schema_version") != _SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"demo snapshot schema_version 不兼容：{doc.get('schema_version')!r}")
    if doc.get("as_of") != _AS_OF:
        raise ValueError(f"demo snapshot as_of 应为 {_AS_OF}：{doc.get('as_of')!r}")
    if doc.get("market") != "cn":
        raise ValueError(f"demo snapshot market 应为 cn：{doc.get('market')!r}")
    if doc.get("sdk_version") != _SDK_VERSION:
        raise ValueError(f"demo snapshot sdk_version 不匹配：{doc.get('sdk_version')!r}")
    if doc.get("catalog_rev") != _CATALOG_REV:
        raise ValueError(f"demo snapshot catalog_rev 不匹配：{doc.get('catalog_rev')!r}")
    data = _require_mapping(doc.get("data"), "data")
    if doc.get("content_hash") != _canonical_data_hash(data):
        raise ValueError("demo snapshot content_hash 校验失败")

    universe = data.get("universe")
    if universe != list(_UNIVERSE):
        raise ValueError(f"demo universe 与固定清单不一致：{universe!r}")
    if not isinstance(doc.get("capture_requests"), int) or doc["capture_requests"] < 0:
        raise ValueError("capture_requests 必须是非负整数")
    if not isinstance(doc.get("generated_at"), str) or not doc["generated_at"]:
        raise ValueError("generated_at 必须是非空字符串")

    stocks_rows = _require_rows(data.get("stocks_list"), "stocks_list")
    if [row.get("symbol") for row in stocks_rows] != list(_UNIVERSE):
        raise ValueError("stocks_list 必须按演示宇宙顺序包含 10 只标的")
    industries = _require_rows(data.get("industries"), "industries")
    if not industries:
        raise ValueError("industries 不能为空")
    bank_rows = _require_rows(data.get("industry_members_bank"), "industry_members_bank")
    if not bank_rows or len(bank_rows) > _MAX_BANK_MEMBERS:
        raise ValueError("industry_members_bank 必须包含 1~20 行")

    kline = _require_mapping(data.get("kline_bars"), "kline_bars")
    snapshots = _require_mapping(data.get("kline_snapshot"), "kline_snapshot")
    if set(kline) != set(_UNIVERSE) or not set(_UNIVERSE).issubset(snapshots):
        raise ValueError("K 线必须覆盖演示宇宙；快照必须至少覆盖演示宇宙")
    for sym in _UNIVERSE:
        rows = _require_rows(kline[sym], f"kline_bars[{sym}]")
        if not rows or len(rows) > _MAX_BARS:
            raise ValueError(f"kline_bars[{sym}] 必须有 1~120 行")
        for i, row in enumerate(rows):
            where = f"kline_bars[{sym}][{i}]"
            _check_date_not_after(row.get("date"), f"{where}.date")
            for field in ("close", "volume", "amount", "percent"):
                _check_finite(row.get(field), f"{where}.{field}")
            if float(row["volume"]) < 0 or float(row["amount"]) < 0:
                raise ValueError(f"{where} volume/amount 不能为负")
            if abs(float(row["percent"])) > 1:
                raise ValueError(f"{where}.percent 不是小数口径")
        dates = [str(row.get("date", ""))[:10] for row in rows]
        if dates != sorted(dates):
            raise ValueError(f"kline_bars[{sym}] 不是日期升序（2.0 全库旧→新）")
        snapshot = _require_mapping(snapshots[sym], f"kline_snapshot[{sym}]")
        _check_finite(snapshot.get("close"), f"kline_snapshot[{sym}].close")
        _check_date_not_after(snapshot.get("kline_date"), f"kline_snapshot[{sym}].kline_date")
        # 2.0：快照是拍摄日盘中价（kline_date=拍摄日），日 K 结算面到上一交易日；
        # 升序下最新 bar 在尾行。价格只做同量级校验（盘中必然偏离上一收盘）。
        snap_date = str(snapshot.get("kline_date", ""))[:10]
        last_date = dates[-1]
        if snap_date and snap_date < last_date:
            raise ValueError(f"{sym} snapshot.kline_date 早于最新 bar.date")
        _check_finite(rows[-1].get("close"), f"kline_bars[{sym}][-1].close")
        if not math.isclose(float(snapshot["close"]), float(rows[-1]["close"]),
                            rel_tol=0.20):
            raise ValueError(f"{sym} snapshot.close 与最新 bar.close 相差超 20%")

    for group, max_len in (("moneyflow_bars", _MAX_MONEYFLOW_BARS),
                           ("dividend_history", _MAX_DIVIDEND_HISTORY)):
        source = data["dividend"]["history"] if group == "dividend_history" else data.get(group)
        rows_by_symbol = _require_mapping(source, group)
        if set(rows_by_symbol) != set(_UNIVERSE):
            raise ValueError(f"{group} 必须完整覆盖演示宇宙")
        for sym, rows in rows_by_symbol.items():
            if len(rows) > max_len:
                raise ValueError(f"{group}[{sym}] 超过 {max_len} 行")
            for i, row in enumerate(_require_rows(rows, f"{group}[{sym}]")):
                if "date" in row:
                    _check_date_not_after(row.get("date"), f"{group}[{sym}][{i}].date")
                for field in ("ex_div", "pay"):
                    if field in row:
                        _check_date_if_present(row.get(field), f"{group}[{sym}][{i}].{field}")
                if "net_mf" in row:
                    _check_finite(row.get("net_mf"), f"{group}[{sym}][{i}].net_mf")

    moneyflow_last = _require_mapping(data.get("moneyflow_last"), "moneyflow_last")
    for sym, row in moneyflow_last.items():
        if isinstance(row, dict):
            _check_date_not_after(row.get("date"), f"moneyflow_last[{sym}].date")

    dividend_last = _require_mapping(data["dividend"].get("last"), "dividend.last")
    for sym, row in dividend_last.items():
        if isinstance(row, dict):
            for field in ("ex_div", "pay"):
                _check_date_if_present(row.get(field), f"dividend.last[{sym}].{field}")

    dividend = _require_mapping(data.get("dividend"), "dividend")
    variants = _require_rows(
        dividend.get("screen_quality_by_args"), "dividend.screen_quality_by_args",
    )
    for variant in variants:
        if not isinstance(variant.get("args"), dict) or not isinstance(variant.get("results"), dict):
            raise ValueError("screen_quality_by_args 格式不合法")

    statements = _require_mapping(data.get("statements"), "statements")
    for kind in ("income", "balance", "cashflow"):
        rows = _require_rows(statements.get(kind), f"statements.{kind}")
        if not any(row.get("vals") for row in rows):
            raise ValueError(f"statements.{kind} 缺少非空 vals")

    indicators = _require_mapping(data.get("indicators"), "indicators")
    for code, value in indicators.items():
        _check_finite(value, f"indicators[{code}]")
        if code != "$PE_TTM_LAST" and not 0 <= float(value) <= 1:
            raise ValueError(f"indicators[{code}] 不是小数分位/比率")
    valuation = _require_mapping(data.get("valuation"), "valuation")
    for key in ("current", "median", "min", "max", "pct"):
        _check_finite(valuation.get(key), f"valuation.{key}")
    if not 0 <= float(valuation["pct"]) <= 1:
        raise ValueError("valuation.pct 不是小数口径")

    screener = _require_mapping(data.get("screener"), "screener")
    summary = _require_mapping(screener.get("breadth_summary"), "breadth_summary")
    for key in ("up_pct", "down_pct", "flat_pct"):
        if key in summary:
            _check_finite(summary[key], f"breadth_summary.{key}")
            if float(summary[key]) < 0:
                raise ValueError(f"breadth_summary.{key} 不能为负")
    _check_finite(summary.get("median_pct"), "breadth_summary.median_pct")
    for i, row in enumerate(_require_rows(screener.get("breadth_bins"), "breadth_bins")):
        _check_finite(row.get("pct_of_total"), f"breadth_bins[{i}].pct_of_total")
        if float(row["pct_of_total"]) < 0:
            raise ValueError(f"breadth_bins[{i}].pct_of_total 不能为负")
    for group in ("top_movers_up", "top_movers_down"):
        for i, row in enumerate(_require_rows(screener.get(group), group)):
            _check_finite(row.get("percent"), f"{group}[{i}].percent")
            if abs(float(row["percent"])) > 1:
                raise ValueError(f"{group}[{i}].percent 不是小数口径")

    notices = _require_rows(data.get("notices"), "notices")
    for i, row in enumerate(notices):
        _check_date_not_after(row.get("date"), f"notices[{i}].date")
        _check_date_not_after(row.get("announce_date"), f"notices[{i}].announce_date")
        _check_date_if_present(
            str(row.get("available_at", ""))[:10] or None,
            f"notices[{i}].available_at",
        )
    if not notices:
        raise ValueError("notices 不能为空")
    event = _require_mapping(data.get("notice_event"), "notice_event")
    _check_url(event.get("url"), "notice_event.url")
    _check_url(event.get("pdf_url"), "notice_event.pdf_url")
    if not event.get("url") and not event.get("pdf_url"):
        raise ValueError("notice_event 必须有 URL")
    NoticeStreamEvent.from_dict(event)

    # ---- 2.0 新三面：calendar / margin / futures（2026-11-18 前完全不校验） ----
    calendar = _require_mapping(data.get("calendar"), "calendar")
    seen_cal: list[str] = []
    for i, row in enumerate(_require_rows(calendar.get("days"), "calendar.days")):
        d = str(row.get("date") or "")
        _check_date_not_after(d, f"calendar.days[{i}].date")
        if d in seen_cal:
            raise ValueError(f"calendar.days[{i}] 日期重复：{d}")
        seen_cal.append(d)
    if seen_cal != sorted(seen_cal):
        raise ValueError("calendar.days 必须按日期升序")
    for d, flag in _require_mapping(calendar.get("is_open"), "calendar.is_open").items():
        if not isinstance(flag, bool):
            raise ValueError(f"calendar.is_open[{d}] 必须是 bool")
    for i, row in enumerate(_require_rows(calendar.get("next"), "calendar.next")):
        # next 的日期可以晚于 as_of（未来交易日），只查格式不做 as_of 门控
        d = str(row.get("date") or "")
        if len(d) != 10:
            raise ValueError(f"calendar.next[{i}].date 非法：{d!r}")

    margin = _require_mapping(data.get("margin"), "margin")
    pairs: dict[str, set[str]] = {}
    for i, row in enumerate(_require_rows(margin.get("market_summary"),
                                          "margin.market_summary")):
        d = str(row.get("trade_date") or "")
        ex = str(row.get("exchange") or "")
        _check_date_not_after(d, f"margin.market_summary[{i}].trade_date")
        if ex not in ("SSE", "SZSE"):
            raise ValueError(f"margin.market_summary[{i}].exchange 非法：{ex}")
        if row.get("fin_balance") is not None:
            _check_finite(row.get("fin_balance"),
                          f"margin.market_summary[{i}].fin_balance")
            if float(row["fin_balance"]) <= 0:
                raise ValueError(f"margin.market_summary[{i}].fin_balance 必须为正")
        pairs.setdefault(d, set()).add(ex)
    for d, exs in pairs.items():
        if len(exs) != 2:
            raise ValueError(f"margin.market_summary {d} 沪深不成对：{sorted(exs)}")
    universe_rows = _require_rows(margin.get("universe"), "margin.universe")
    uni_codes = [str(r.get("security_code") or "") for r in universe_rows]
    if len(uni_codes) != len(set(uni_codes)):
        raise ValueError("margin.universe 标的代码重复")
    if not universe_rows or len(universe_rows) > 500:
        raise ValueError("margin.universe 行数不在 [1, 500]")

    futures_book = _require_mapping(data.get("futures"), "futures")
    if not futures_book:
        raise ValueError("futures 快照缺失")
    for fut, snap in futures_book.items():
        row = _require_mapping(snap, f"futures[{fut}]")
        for field in ("close", "settle", "pre_settle"):
            _check_finite(row.get(field), f"futures[{fut}].{field}")
            if float(row[field]) <= 0:
                raise ValueError(f"futures[{fut}].{field} 必须为正")

    # ---- 2.3 新面：回购 / 龙虎榜 / 公告类目 / PDF / 期货映射 ----
    buyback = _require_mapping(data.get("buyback"), "buyback")
    if set(buyback) != set(_UNIVERSE):
        raise ValueError("buyback 必须完整覆盖演示宇宙")
    for sym, snap in buyback.items():
        for field, value in _require_mapping(snap, f"buyback[{sym}]").items():
            if value is None:
                continue  # 无数据源字段如实为 None（不伪造 0）
            _check_finite(value, f"buyback[{sym}].{field}")
            if float(value) < 0:
                raise ValueError(f"buyback[{sym}].{field} 不能为负")

    toplist = _require_mapping(data.get("toplist"), "toplist")
    toplist_date = str(toplist.get("date") or "")
    if len(toplist_date) != 10:
        raise ValueError("toplist.date 必须是 ISO 日期")
    if toplist_date > _AS_OF:
        raise ValueError(f"toplist.date 晚于快照日：{toplist_date}")
    toplist_rows = _require_rows(toplist.get("by_date"), "toplist.by_date")
    for i, row in enumerate(toplist_rows):
        where = f"toplist.by_date[{i}]"
        if str(row.get("date") or "")[:10] != toplist_date:
            raise ValueError(f"{where}.date 与 toplist.date 不一致")
        if len(str(row.get("symbol") or "")) != 6:
            raise ValueError(f"{where}.symbol 必须是 6 位裸码")
        for field in ("close", "pct_chg", "turnover_rate", "amount", "float_mv"):
            _check_finite(row.get(field), f"{where}.{field}")
        # 率高斯上界：amount_ratio 可 >1（小盘高换手）
        for field in ("pct_chg", "turnover_rate", "net_ratio"):
            if abs(float(row.get(field) or 0)) > 1:
                raise ValueError(f"{where}.{field} 不是小数口径")
    toplist_sym = str(toplist.get("symbol") or "")
    if len(toplist_sym) != 6:
        raise ValueError("toplist.symbol 必须是 6 位裸码")
    hist_rows = _require_rows(toplist.get("by_symbol"), "toplist.by_symbol")
    for i, row in enumerate(hist_rows):
        where = f"toplist.by_symbol[{i}]"
        if str(row.get("symbol") or "") != toplist_sym:
            raise ValueError(f"{where}.symbol 不是 {toplist_sym}")
        _check_date_not_after(row.get("date"), f"{where}.date")

    cats = _require_mapping(data.get("notice_categories"), "notice_categories")
    cat_keys = cats.get("keys")
    cat_regex = _require_mapping(cats.get("regex"), "notice_categories.regex")
    if not isinstance(cat_keys, list) or len(cat_keys) < 10:
        raise ValueError("notice_categories.keys 至少 10 类目")
    if set(cat_keys) != set(cat_regex):
        raise ValueError("notice_categories.keys 与 regex 键不一致")
    for key in cat_keys:
        if not str(cat_regex.get(key) or "").strip():
            raise ValueError(f"notice_categories.regex[{key}] 为空")

    pdf = _require_mapping(data.get("pdf_doc"), "pdf_doc")
    pdf_search = _require_rows(pdf.get("search"), "pdf_doc.search")
    pdf_key = str(pdf.get("sample", {}).get("file_key") or "")
    if not pdf_key:
        raise ValueError("pdf_doc.sample.file_key 为空")
    if not any(str(r.get("file_key")) == pdf_key for r in pdf_search):
        raise ValueError("pdf_doc.sample 必须出现在 pdf_doc.search 里")
    for section in ("find_by_key", "status", "read_text", "read_markdown"):
        sec = pdf.get(section)
        if section == "find_by_url" and sec is None:
            continue
        if not isinstance(sec, dict):
            raise ValueError(f"pdf_doc.{section} 必须是 MAP")
    if str(pdf["read_text"].get("file_key")) != pdf_key:
        raise ValueError("pdf_doc.read_text 的 file_key 与 sample 不一致")
    _check_url(pdf["read_text"].get("source_url"), "pdf_doc.read_text.source_url")
    for i, row in enumerate(pdf_search):
        _check_url(row.get("source_url"), f"pdf_doc.search[{i}].source_url")
        _check_url(row.get("oss_url"), f"pdf_doc.search[{i}].oss_url")

    fut_map = _require_mapping(data.get("futures_mapping"), "futures_mapping")
    if not fut_map:
        raise ValueError("futures_mapping 快照缺失")
    for fut, rows in fut_map.items():
        mr_rows = _require_rows(rows, f"futures_mapping[{fut}]")
        dates = []
        for i, row in enumerate(mr_rows):
            where = f"futures_mapping[{fut}][{i}]"
            if str(row.get("symbol") or "") != fut:
                raise ValueError(f"{where}.symbol 不是 {fut}")
            d = str(row.get("date") or "")[:10]
            _check_date_not_after(d, f"{where}.date")
            if not str(row.get("mapping_symbol") or ""):
                raise ValueError(f"{where}.mapping_symbol 为空")
            dates.append(d)
        if dates != sorted(dates):
            raise ValueError(f"futures_mapping[{fut}] 不是日期升序")

    return doc


def load_demo_snapshot() -> dict[str, Any]:
    """加载、校验并返回打包的 demo 快照（内部函数，测试和生成器校验可用）。"""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        try:
            raw = _DATA_PATH.read_bytes()
        except OSError as e:
            raise RuntimeError(f"demo 快照缺失或不可读：{_DATA_PATH.name}") from e
        if len(raw) > 768 * 1024:
            raise RuntimeError("demo 快照超过 768 KiB")
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise RuntimeError("demo 快照不是合法 JSON") from e
        _SNAPSHOT = _validate_snapshot(document)
    return _SNAPSHOT


def _quality_args_key(min_yield: float | None, payout_min: float | None,
                      payout_max: float | None) -> str:
    return json.dumps(
        {"min_yield": min_yield, "payout_min": payout_min, "payout_max": payout_max},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _slice_years(values: dict[str, Any], years: int) -> dict[str, Any]:
    """Select the latest N reported periods while preserving upstream key order."""
    if years <= 0:
        return {}
    latest = set(sorted(values, key=str, reverse=True)[:years])
    return {key: value for key, value in values.items() if key in latest}


def _slice_statement_rows(rows: list[dict[str, Any]], years: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("vals"), dict):
            item["vals"] = _slice_years(item["vals"], years)
        for key in ("c", "p", "diff", "diffp"):
            if isinstance(item.get(key), dict):
                item[key] = _slice_years(item[key], years)
        out.append(item)
    return out


class DemoPoller:
    """零网络公告轮询桩：复刻首轮交付、ack 后不重投与 seek 语义。"""

    def __init__(self, event: dict[str, Any],
                 on_events: Callable[[list[NoticeStreamEvent]], Any] | None = None):
        self._event = NoticeStreamEvent.from_dict(event)
        self._on_events = on_events
        self._acked = False

    def poll_now(self) -> list[NoticeStreamEvent]:
        if self._acked:
            return []
        self._acked = True
        events = [self._event]
        if self._on_events is not None:
            self._on_events(events)
        return events

    def seek_oldest(self, market: str = "cn") -> int:
        if market != "cn":
            raise UsageError("demo 快照只支持 cn 市场", code="demo_market")
        self._acked = False
        return self._event.seq

    def start(self) -> None:
        return None

    def stop(self, timeout: float = 5.0) -> None:
        return None

    @property
    def running(self) -> bool:
        return False

    def __enter__(self) -> "DemoPoller":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class DemoClient:
    """``wmshare.Client`` 的固定快照替身：覆盖 examples 和公开文档调用面。"""

    def __init__(self) -> None:
        document = load_demo_snapshot()
        self._doc = document
        self._data: dict[str, Any] = document["data"]
        self._universe = tuple(self._data["universe"])
        self.kline = SimpleNamespace(
            bars=self._kline_bars,
            snapshot=self._kline_snapshot,
            live=self._kline_snapshot,
            last=self._kline_last,
            batch_live=self._kline_batch_live,
        )
        self.moneyflow = SimpleNamespace(
            last=self._moneyflow_last, bars=self._moneyflow_bars,
            board=self._moneyflow_board,
        )
        self.statements = SimpleNamespace(
            income=self._statement("income"),
            balance=self._statement("balance"),
            cashflow=self._statement("cashflow"),
            audit=self._statement_audit,
        )
        self.indicator = SimpleNamespace(
            get=self._indicator_get,
            metrics=self._indicator_metrics,
        )
        # 宏观域罐头：形状与真实返回同构（series 最新在前、CPI=价格指数点、GDP=元）
        self.macro = SimpleNamespace(
            query=lambda code, n=6: {
                "ok": True, "metric": "$CPI", "store": "cpi", "frequency": "month",
                "periods": 3,
                "latest": {"sas": "600519:2026:M09", "annual": 2026,
                           "sampling": "M09", "value": 100.9},
                "series": [
                    {"sas": "600519:2026:M09", "annual": 2026, "sampling": "M09",
                     "value": 100.9},
                    {"sas": "600519:2026:M08", "annual": 2026, "sampling": "M08",
                     "value": 100.8},
                    {"sas": "600519:2026:M07", "annual": 2026, "sampling": "M07",
                     "value": 100.5},
                ][:n],
            },
            asof=lambda code: 107107120000000,
            spots=lambda code, n=4: ["2026:Q3", "2026:Q2", "2026:Q1", "2025:Q4"][:n],
            sampling_of=lambda code: "quarter",
            bond_curve=lambda curve_name, tenor: 0.016822,
            nev_monthly=lambda brand, field: 40000,
            nev_weekly=lambda brand, field: None,
            avc_monthly=lambda category, field: None,
            chinaiol_monthly=lambda category, field: None,
            cpca_top=lambda manufacturer, field: 45.5113,
            phone_share=lambda brand, field="share": 11,
        )
        self.notice = SimpleNamespace(
            list=self._notice_list,
            categories=self._notice_categories,
            category_regex=self._notice_category_regex,
        )
        # 批次1/3 暴露层：equity/pdf_doc/toplist 快照未拍摄 → 显式 demo_unsupported（签名同形）
        self.equity = SimpleNamespace(buyback_snapshot=self._equity_buyback_snapshot)
        self.toplist = SimpleNamespace(
            by_date=self._toplist_by_date,
            by_symbol=self._toplist_by_symbol,
        )
        self.pdf_doc = SimpleNamespace(
            search=self._pdf_search,
            read_text=self._pdf_read_text,
            read_markdown=self._pdf_read_markdown,
            status=self._pdf_status,
            find_by_url=self._pdf_find_by_url,
            find_by_key=self._pdf_find_by_key,
        )
        self.dividend = SimpleNamespace(
            last=self._dividend_last,
            yield_ttm=self._dividend_yield,
            history=self._dividend_history,
            screen_quality=self._dividend_screen_quality,
            index_where_high_yield_5=self._dividend_expression,
        )
        self.info = SimpleNamespace(profile=self._profile)
        self.backtest = SimpleNamespace(run=self._backtest_run)
        self.stocks = SimpleNamespace(
            list=self._stocks_list,
            industries=self._industries,
            industry_members=self._industry_members,
        )
        self.screener = SimpleNamespace(
            screen_limit_up=lambda symbol: self._screen(symbol, "limit_up"),
            screen_above_ma20=lambda symbol: self._screen(symbol, "above_ma20"),
            screen_volume_spike=(
                lambda symbol, min_ratio=None: self._screen(symbol, "volume_spike",
                                                           min_ratio=min_ratio)),
            screen_up_today=lambda symbol: self._screen(symbol, "up_today"),
            index_breadth_summary=(
                lambda idx=None: dict(self._data["screener"]["breadth_summary"])),
            index_breadth_bins=lambda idx=None: (lambda rows: (
                __import__("wmshare.client", fromlist=["to_output_frame"]).to_output_frame(rows)))(
                [dict(row) for row in self._data["screener"]["breadth_bins"]]),
            index_top_movers=self._top_movers,
            query=self._screen_query,
        )
        self.valuation = SimpleNamespace(
            hist_stats=self._valuation_hist_stats,
            daily_basic=self._valuation_daily_basic,
            daily_basic_multi=self._valuation_daily_basic_multi,
            daily_basic_coverage=self._valuation_daily_basic_coverage)
        self.index = self._index_ns()
        # 2.0 新面：快照已覆盖（calendar/margin 市场面/futures），逐面回放。
        # 快照是真实 API 固定日拍摄，方向/形态与 live 同构。
        self.futures = SimpleNamespace(
            snapshot=self._futures_snapshot,
            get=self._futures_get,
            mapping=self._futures_mapping,
        )
        self.calendar = SimpleNamespace(
            days=self._calendar_days,
            is_open=self._calendar_is_open,
            next=self._calendar_next,
        )
        self.margin = SimpleNamespace(
            # 形参与 live 逐字对齐（symbol/limit/_fields）：未回放要报 demo_unsupported，
            # 不能靠 *a/**kw 让 TypeError/静默吞参数。
            query=lambda symbol, limit=20, _fields=None: (_ for _ in ()).throw(
                _unsupported("margin.query", "底层函数")),
            market_summary=self._margin_market_summary,
            universe=self._margin_universe,
        )
        self.batch_all = self._batch_all
        self.batch_iter = self._batch_iter
        self.call_batch = self._call_batch
        self.notice_poller = self._notice_poller
        self.call = self._call
        self.cost_estimate = self._cost_estimate


    def _cost_estimate(self, name: str, /, **params: Any) -> dict:
        """EC 预估与真实客户端同源（模块级 estimate_cost，纯离线零请求）。"""
        from wmshare.client import estimate_cost

        return estimate_cost(name, params)

    # ---- 公告类目表：优先回放快照（与 live 同源），快照缺段时退回内置表 ----
    # 内置表是 2.3.0 手抄的兜底（旧快照不含 notice_categories 段时仍可用），
    # 快照重拍后以快照为准——类目/正则一旦上游变化，回放会自动跟随。

    _NOTICE_CATEGORY_REGEX = {
        "reduction": "减持|減持",
        "insider_buy": "增持|增持",
        "buyback": "回购|購回",
        "equity_incentive": "股权激励|股權激勵",
        "forecast": "业绩预告|业绩快报|業績|中期業績|末期業績|季度業績",
        "dividend": "分配|派息|股息",
        "risk": "处罚|诉讼|风险|ST|退市|异常波动|问询|處罰|訴訟|風險",
        "mna": "重组|并购|收购|要约|重組|併購|收購|要約",
        "contract": "重大合同|重大合約",
        "pledge": "质押|冻结|質押|凍結",
        "issue": "增发|配售|供股",
        "report": "报告全文|報告全文|年報|年报|季报|季報",
        "suspend": "停牌|复牌|停牌|復牌",
        "correct": "更正|延期披露|更正|延期披露",
    }

    def _notice_category_table(self) -> dict[str, str]:
        stored = self._data.get("notice_categories") or {}
        keys = stored.get("keys") or []
        regex = stored.get("regex") or {}
        if keys and regex and len(regex) >= len(keys):
            return {str(k): str(regex.get(k, k)) for k in keys}
        return dict(self._NOTICE_CATEGORY_REGEX)

    def _notice_categories(self) -> list:
        return list(self._notice_category_table())

    def _notice_category_regex(self, key: str) -> str:
        table = self._notice_category_table()
        return str(table.get(key, key))

    def _equity_buyback_snapshot(self, symbol: str) -> Any:
        """2.3：回购六口径快照（演示宇宙 10 票已拍；其余报 demo_symbol）。"""
        sym = self._require_symbol(symbol)
        return dict(self._data["buyback"][sym])

    # ---- 2.3 pdf_doc：全库检索 / 点查 / 正文预览（快照含检索结果 + 一条正文）----

    def _pdf_search(self, stock_code: str = "", title: str = "",
                    announce_date_from: str = "", announce_date_to: str = "",
                    status: str = "", kind: str = "", limit: int = 20,
                    skip: int = 0, _raw: bool = False) -> Any:
        """按快照里的检索结果做本地过滤（live 是服务端查询）。"""
        rows = [dict(r) for r in self._data["pdf_doc"]["search"]]
        if stock_code:
            rows = [r for r in rows if str(r.get("stock_code")) == str(stock_code)]
        if status:
            rows = [r for r in rows if str(r.get("status")) == str(status)]
        if kind:
            rows = [r for r in rows if str(r.get("kind")) == str(kind)]
        if title:
            rows = [r for r in rows if str(title) in str(r.get("title") or "")]
        if announce_date_from:
            rows = [r for r in rows
                    if str(r.get("announce_date") or "") >= announce_date_from]
        if announce_date_to:
            rows = [r for r in rows
                    if str(r.get("announce_date") or "") <= announce_date_to]
        rows = rows[int(skip):int(skip) + int(limit)]
        if _raw:
            return rows
        return self._df_asc(rows, "updated_at")

    def _pdf_row(self, file_key: str, source_url: str) -> dict[str, Any] | None:
        """在快照的检索结果里找一行（live 是 store 点查）。"""
        for row in self._data["pdf_doc"]["search"]:
            if file_key and str(row.get("file_key")) == str(file_key):
                return dict(row)
            if source_url and str(row.get("source_url")) == str(source_url):
                return dict(row)
        return None

    def _pdf_require_sampled(self, stored: dict[str, Any], file_key: str,
                             source_url: str, what: str) -> None:
        """快照只存一条正文样本；请求的不是它时明确报错（不返错数据）。"""
        row = self._pdf_row(file_key, source_url)
        if row is None or str(row.get("file_key")) != str(stored.get("file_key")):
            raise UsageError(
                f"demo 快照只回放一条 PDF {what}（pdf_doc.search() 的首条）；"
                f"收到 file_key={file_key!r} source_url={source_url!r}",
                code="demo_symbol",
            )

    def _pdf_read_text(self, file_key: str = "", source_url: str = "") -> Any:
        stored = self._data["pdf_doc"]["read_text"]
        self._pdf_require_sampled(stored, file_key, source_url, "正文")
        return dict(stored)

    def _pdf_read_markdown(self, file_key: str = "", source_url: str = "",
                           stock_code: str = "", period: str = "") -> Any:
        stored = self._data["pdf_doc"]["read_markdown"]
        if file_key or source_url:
            self._pdf_require_sampled(stored, file_key, source_url, "markdown")
        return dict(stored)

    def _pdf_status(self, file_key: str = "", source_url: str = "") -> Any:
        stored = self._data["pdf_doc"]["status"]
        self._pdf_require_sampled(stored, file_key, source_url, "状态")
        return dict(stored)

    def _pdf_find_by_url(self, url: str) -> Any:
        found = self._data["pdf_doc"].get("find_by_url")
        row = self._pdf_row("", url)
        if row is None:
            return None
        return dict(found) if found else row

    def _pdf_find_by_key(self, file_key: str) -> Any:
        found = self._data["pdf_doc"].get("find_by_key")
        row = self._pdf_row(file_key, "")
        if row is None:
            return None
        return dict(found) if found else row

    # ---- 2.3 toplist：指定日榜单 / 单票上榜历史 ----

    def _toplist_by_date(self, trade_date: str, limit: int = 100,
                         _raw: bool = False) -> Any:
        from wmshare.client import normalize_date

        stored_date = str(self._data["toplist"]["date"])
        if normalize_date(trade_date) != stored_date:
            raise UsageError(
                f"demo 快照只含 {stored_date} 的龙虎榜（榜单盘后 T+1 落库）；"
                f"收到 {trade_date!r}", code="demo_symbol",
            )
        rows = [dict(r) for r in self._data["toplist"]["by_date"]]
        rows = rows[:int(limit or len(rows))]
        if _raw:
            return rows
        return self._df_asc(rows, "date")

    def _toplist_by_symbol(self, symbol: str, limit: int = 100,
                           _raw: bool = False) -> Any:
        stored_sym = str(self._data["toplist"]["symbol"])
        code = str(symbol)
        for prefix in ("cn.", "sh.", "sz.", "bj."):
            if code.lower().startswith(prefix):
                code = code[len(prefix):]
        for suffix in (".SH", ".SZ", ".BJ"):
            if code.upper().endswith(suffix):
                code = code[:-len(suffix)]
        if code != stored_sym:
            raise UsageError(
                f"demo 快照只含 {stored_sym} 的上榜历史；收到 {symbol!r}",
                code="demo_symbol",
            )
        rows = [dict(r) for r in self._data["toplist"]["by_symbol"]]
        # 快照按最新在前（与 live by_symbol 同序）
        rows = rows[:int(limit or len(rows))]
        if _raw:
            return rows
        return self._df_asc(rows, "date")

    # ---- 2.3 futures.mapping：换月映射（窗口过滤）----

    def _futures_mapping(self, symbol: str, begin: str = "", end: str = "",
                         _raw: bool = False) -> Any:
        from wmshare.client import normalize_date

        code = str(symbol).upper().strip()
        stored = self._data["futures_mapping"].get(code)
        if stored is None:
            raise UsageError(
                f"demo 快照只含 {sorted(self._data['futures_mapping'])} 的换月映射；"
                f"收到 {symbol!r}", code="demo_symbol",
            )
        rows = [dict(r) for r in stored]
        if begin:
            b = normalize_date(begin)
            rows = [r for r in rows if str(r.get("date")) >= b]
        if end:
            e = normalize_date(end)
            rows = [r for r in rows if str(r.get("date")) <= e]
        if _raw:
            return rows
        # live 的 mapping 是 date 升序（store 层已 sort）
        return self._df_asc(rows, "date")

    def _df_asc(self, rows: Any, key: str = "date") -> Any:
        """2.0 同形：demo 行列表也按升序 + DataFrame 输出（与 live 门面同形同向）。"""
        from wmshare.client import to_output_frame
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            rows = sorted(rows, key=lambda r: str(r.get(key) or ""))
        return to_output_frame(rows)

    def _require_symbol(self, symbol: str) -> str:
        sym = str(symbol)
        if sym not in self._universe:
            raise UsageError(
                f"demo 快照只支持演示宇宙标的：{', '.join(self._universe)}；收到 {sym!r}",
                code="demo_symbol",
            )
        return sym

    def _require_snapshot_symbol(self, symbol: str) -> str:
        sym = str(symbol)
        if sym not in self._data["kline_snapshot"]:
            raise UsageError(
                f"demo snapshot 只支持演示宇宙与银行成分；收到 {sym!r}", code="demo_symbol",
            )
        return sym

    def _kline_bars(self, symbol: str, n: int | None = None, adj: str | None = None,
                    begin: str | None = None, end: str | None = None,
                    freq: str | None = None, _raw: bool = False,
                    _fields: Any = None) -> Any:
        # 签名与 live 门面逐字对齐：未回放的能力报 demo_unsupported（不是 TypeError）。
        if adj is not None or begin is not None or end is not None or _raw or freq:
            raise UsageError(
                "demo 快照只覆盖复权/周月频/日期区间之外的 kline.bars(n<=120)",
                code="demo_unsupported",
            )
        count = 120 if n is None else int(n)
        if count <= 0:
            raise UsageError("n 必须为正整数", code="params")
        if count > _MAX_BARS:
            raise UsageError(
                f"demo 快照最多保存 {_MAX_BARS} 根日 K，收到 {count}", code="demo_limit",
            )
        sym = self._require_symbol(symbol)
        # 快照升序存储（2.0 口径）；n = 最近 n 根 → 取尾部，与 live 语义一致
        rows = [dict(row) for row in self._data["kline_bars"][sym][-count:]]
        if _fields is not None:
            from wmshare.client import project_fields
            rows = project_fields(rows, _fields, fname="kline.bars")
        return self._df_asc(rows)

    def _kline_snapshot(self, symbol: Any, _raw: bool = False,
                        _fields: Any = None) -> Any:
        """单票 MAP；传列表（≥3 票）与 live 同形——一次请求的 BatchResult。

        1.22.1 起 live 的列表入参自动路由批量原生实现（单次 eval、EC 按量），
        demo 必须同形同次数，否则示例会教出「批量=12 次请求」的旧口径。
        """
        if isinstance(symbol, (list, tuple)):
            syms = list(dict.fromkeys(str(s) for s in symbol))
            if len(syms) >= 3:
                return BatchResult(results={self._require_snapshot_symbol(s):
                                            self._kline_snapshot(s) for s in syms},
                                   requests=1, requested=len(syms))
            return BatchResult(
                results={self._require_snapshot_symbol(s): self._kline_snapshot(s)
                         for s in syms},
                requests=len(syms), requested=len(syms))
        sym = self._require_snapshot_symbol(symbol)
        row = dict(self._data["kline_snapshot"][sym])
        if _raw:
            raise UsageError("demo 快照不提供 kline.snapshot 的 _raw 原始口径",
                             code="demo_unsupported")
        if _fields is not None:
            from wmshare.client import project_fields
            row = project_fields(row, _fields, fname="kline.snapshot")
        return row

    def _kline_last(self, symbol: str, _raw: bool = False) -> Any:
        """最新一根日 K（与 live `kline.last` 同形：date/open/high/low/close/...）。"""
        if _raw:
            raise UsageError("demo 快照不提供 kline.last 的 _raw 原始口径",
                             code="demo_unsupported")
        sym = self._require_symbol(symbol)
        rows = self._data["kline_bars"][sym]
        return dict(rows[-1]) if rows else None

    def _kline_batch_live(self, symbols: list[str], _raw: bool = False) -> dict[str, dict[str, Any]]:
        return {self._require_snapshot_symbol(s): dict(self._data["kline_snapshot"][s])
                for s in symbols}

    # ---- 2.0 新面回放（calendar / margin 市场面 / futures）----
    def _calendar_rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._data["calendar"]["days"]]

    def _calendar_days(self, begin: str, end: str, limit: int | None = None) -> Any:
        from wmshare.client import normalize_date

        b, e = normalize_date(begin), normalize_date(end)
        rows = [r for r in self._calendar_rows() if b <= str(r.get("date")) <= e]
        if limit:
            rows = rows[: int(limit)]
        return self._df_asc(rows, "date")

    def _calendar_is_open(self, date: str) -> bool:
        from wmshare.client import normalize_date

        d = normalize_date(date)
        stored = self._data["calendar"].get("is_open") or {}
        if d in stored:
            return bool(stored[d])
        return any(str(r.get("date")) == d for r in self._calendar_rows())

    def _calendar_next(self, date: str, n: int | None = None) -> Any:
        from wmshare.client import normalize_date

        d = normalize_date(date)
        rows = [dict(r) for r in self._data["calendar"]["next"]
                if str(r.get("date")) > d]
        cap = int(n or 1)
        return self._df_asc(rows[:cap], "date")

    def _margin_market_summary(self, limit: int | None = None, _fields: Any = None) -> Any:
        rows = [dict(r) for r in self._data["margin"]["market_summary"]]
        rows.sort(key=lambda r: str(r.get("trade_date")))      # 2.0 升序
        if limit:
            rows = rows[-int(limit):]                          # 取最近 N 行
        if _fields is not None:
            from wmshare.client import project_fields
            rows = project_fields(rows, _fields, fname="margin.market_summary")
        return self._df_asc(rows, "trade_date")

    def _margin_universe(self, limit: int | None = None, _fields: Any = None) -> Any:
        rows = [dict(r) for r in self._data["margin"]["universe"]]
        rows.sort(key=lambda r: str(r.get("security_code")))
        if limit:
            rows = rows[: int(limit)]
        if _fields is not None:
            from wmshare.client import project_fields
            rows = project_fields(rows, _fields, fname="margin.universe")
        return self._df_asc(rows, "security_code")

    def _futures_snapshot(self, fut_code: str, freq: str = "d") -> dict[str, Any]:
        code = str(fut_code or "").strip().upper()
        bare = code[3:] if code.startswith("CN.") else code      # RB.SHF / IF.CFX
        if str(freq or "d").lower() not in ("d", "day", "daily"):
            raise _unsupported(f"futures.snapshot(freq={freq!r})", "演示快照只回放日频")
        book = self._data.get("futures") or {}
        snap = book.get(bare) or book.get(f"cn.{bare}")
        if snap is None:
            raise UsageError(
                f"演示快照未回放 {fut_code}（快照覆盖 {sorted(book)}）",
                code="demo_unsupported")
        return dict(snap)

    def _futures_get(self, fut_code: str, field: str = "close",
                     freq: str | None = None, native: bool = False) -> Any:
        snap = self._futures_snapshot(fut_code, freq or "d")
        text = str(field or "").strip()
        if text.startswith("$"):
            # $码 → 短名（与 live 同口径：日频域内 code→短名 反查）
            from wmshare.api import FuturesApi

            text = FuturesApi._FREQ_CODES["d"].get(text, "")
            if not text:
                raise UsageError(f"未知指标 {field!r}", code="params")
        if text not in snap:
            raise UsageError(f"演示快照 {fut_code} 无字段 {text!r}", code="demo_unsupported")
        return snap[text]

    def _moneyflow_last(self, symbol: str, _raw: bool = False) -> Any:
        if _raw:
            raise UsageError("demo 快照不提供 _raw 原始口径", code="demo_unsupported")
        sym = self._require_symbol(symbol)
        value = self._data["moneyflow_last"][sym]
        return dict(value) if isinstance(value, dict) else value

    def _moneyflow_bars(self, symbol: str, n: int | None = None,
                        begin: str | None = None, end: str | None = None,
                        _raw: bool = False, _fields: Any = None) -> Any:
        # 签名与 live 门面逐字对齐（含区间参数）：未回放的能力报 demo_unsupported，
        # 不能靠「参数不存在」抛 TypeError 让调用方以为是自己写错了。
        if begin is not None or end is not None or _raw:
            raise UsageError(
                "demo 快照只覆盖不带日期区间的 moneyflow.bars(n<=60)",
                code="demo_unsupported",
            )
        count = 20 if n is None else int(n)
        if count <= 0 or count > _MAX_MONEYFLOW_BARS:
            raise UsageError(
                f"demo 快照最多保存 {_MAX_MONEYFLOW_BARS} 根资金流，收到 {count}",
                code="demo_limit",
            )
        sym = self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["moneyflow_bars"][sym][-count:]]
        if _fields is not None:
            from wmshare.client import project_fields
            rows = project_fields(rows, _fields, fname="moneyflow.bars")
        return self._df_asc(rows)

    def _moneyflow_board(self) -> Any:
        """演示宇宙（10 只）的全市场快照罐头：由 moneyflow_last 派生、按净流入降序。"""
        rows = []
        for sym, v in self._data["moneyflow_last"].items():
            snap = self._data["kline_snapshot"].get(sym, {})
            rows.append({
                "symbol": sym,
                "name": snap.get("name", ""),
                "net_mf": v.get("net_mf", 0),
                "net_mv_ratio": 0.0,
                "lg_net": v.get("lg_net", 0),
                "elg_net": v.get("elg_net", 0),
                "md_net": v.get("md_net", 0),
                "sm_net": v.get("sm_net", 0),
                "industry": snap.get("industry", ""),
            })
        rows.sort(key=lambda r: r["net_mf"], reverse=True)
        from wmshare.client import to_output_frame
        return to_output_frame(rows)

    # ---- fundamentals ----
    def _statement(self, kind: str):
        def method(symbol: str, years: int = 5, period: str = "annual",
                   **_kw) -> Any:
            if period not in ("annual", "quarter"):
                raise UsageError(f"未知 period={period!r}", code="params")
            if int(years) <= 0:
                raise UsageError("years 必须为正整数", code="params")
            sym = self._require_symbol(symbol)
            if sym != "600519":
                raise UsageError("demo 报表快照只覆盖 600519", code="demo_symbol")
            rows = _slice_statement_rows(self._data["statements"][kind], int(years))
            from wmshare.client import to_output_frame
            return to_output_frame(rows)
        return method



    def _statement_audit(self, symbol: str) -> dict[str, str]:
        self._require_symbol(symbol)
        return dict(self._data["statements"]["audit"])

    def _indicator_get(self, symbol: str, code: str, fut_symbol: str | None = None,
                       native: bool = False, **kw: Any) -> Any:
        if code in _FUT_CANS:  # 期货主力连续（合约键仅透传，罐头不随合约变化）
            return _FUT_CANS[code]
        self._require_symbol(symbol)
        try:
            return self._data["indicators"][code]
        except KeyError:
            raise UsageError(
                f"demo 快照只保存 indicators：{', '.join(self._data['indicators'])}",
                code="demo_unsupported",
            ) from None

    def _indicator_metrics(self, symbol: str, codes: list[str],
                           fut_symbol: str | None = None, native: bool = False,
                           **kw: Any) -> dict[str, Any]:
        return {code: self._indicator_get(symbol, code, fut_symbol=fut_symbol,
                                          native=native, **kw) for code in codes}

    # ---- disclosure ----
    def _notice_list(self, symbol: str, window: str = "3m", keyword: str = "",
                     limit: int = 20, _raw: bool = False) -> Any:
        self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["notices"][:max(0, int(limit))]]
        return self._df_asc(rows)

    def _dividend_last(self, symbol: str, _raw: bool = False) -> Any:
        if _raw:
            raise UsageError("demo 快照不提供 _raw 原始口径", code="demo_unsupported")
        sym = self._require_symbol(symbol)
        value = self._data["dividend"]["last"][sym]
        return dict(value) if isinstance(value, dict) else value

    def _dividend_yield(self, symbol: str) -> Any:
        return self._data["dividend"]["yield_ttm"][self._require_symbol(symbol)]

    def _dividend_history(self, symbol: str, limit: int | None = None,
                          begin: str | None = None, end: str | None = None,
                          _raw: bool = False) -> Any:
        if begin is not None or end is not None or _raw:
            raise UsageError("demo 分红快照只支持 limit 查询", code="demo_unsupported")
        count = 20 if limit is None else int(limit)
        if count <= 0 or count > _MAX_DIVIDEND_HISTORY:
            raise UsageError(
                f"demo 分红快照最多 {_MAX_DIVIDEND_HISTORY} 行，收到 {count}", code="demo_limit",
            )
        sym = self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["dividend"]["history"][sym][:count]]
        return self._df_asc(rows, key="ex_div")

    def _dividend_screen_quality(self, symbol: str, min_yield: float | None = None,
                                 payout_min: float | None = None,
                                 payout_max: float | None = None,
                                 _raw: bool = False) -> bool:
        if _raw:
            raise UsageError("demo screen_quality 不提供 _raw 原始口径", code="demo_unsupported")
        sym = self._require_symbol(symbol)
        wanted = _quality_args_key(min_yield, payout_min, payout_max)
        for variant in self._data["dividend"]["screen_quality_by_args"]:
            actual = _quality_args_key(
                variant["args"].get("min_yield"), variant["args"].get("payout_min"),
                variant["args"].get("payout_max"),
            )
            if actual == wanted and sym in variant["results"]:
                return bool(variant["results"][sym])
        raise UsageError(
            "demo 快照未捕获该 screen_quality 阈值组合；可先切换真实 Client",
            code="demo_unsupported",
        )

    def _dividend_expression(self) -> str:
        return str(self._data["dividend"]["index_where_high_yield_5"])

    # ---- reference ----
    def _profile(self, symbol: str) -> dict[str, Any]:
        self._require_symbol(symbol)
        if symbol != "600519":
            raise UsageError("demo profile 只覆盖 600519", code="demo_symbol")
        return dict(self._data["profile"])

    def _stocks_list(self) -> Any:
        from wmshare.client import to_output_frame
        return to_output_frame([dict(row) for row in self._data["stocks_list"]])

    def _industries(self, level: int | None = None) -> Any:
        if level is not None and int(level) != 1:
            raise UsageError("demo 快照只保存一级行业", code="demo_limit")
        from wmshare.client import to_output_frame
        return to_output_frame([dict(row) for row in self._data["industries"]])

    def _industry_members(self, industry: str, top_n: int | None = None) -> Any:
        if str(industry) not in ("银行", "S48"):
            raise UsageError(
                "demo 快照只保存「银行」行业成分；可传 银行 或 S48", code="demo_symbol",
            )
        rows = [dict(row) for row in self._data["industry_members_bank"]]
        if top_n is not None:
            rows = rows[:max(0, int(top_n))]
        from wmshare.client import to_output_frame
        return to_output_frame(rows)

    # ---- screener ----
    def _screen(self, symbol: str, key: str, *, min_ratio: float | None = None) -> bool:
        sym = self._require_symbol(symbol)
        ok = bool(self._data["screener"]["screens"][sym][key])
        if min_ratio is not None and key == "volume_spike":
            # 快照只存布尔判定（拍摄时的默认阈值），自定义阈值无法回溯——
            # 报 demo_unsupported 而不是忽略参数返回一个不同的「真值」。
            raise UsageError(
                f"demo 快照只回放默认阈值的 volume_spike 判定，不支持 min_ratio={min_ratio}",
                code="demo_unsupported",
            )
        return ok

    def _backtest_run(self, symbol: str, rule: str = "ma_cross", fast: int = 5,
                      slow: int = 20, buy: float | None = None, sell: float | None = None,
                      begin: str | None = None, end: str | None = None,
                      cash: float = 1_000_000.0, adj: str = "qfq") -> Any:
        """演示快照 120 根不复权日 K，真跑一遍回测（不伪造结果）。"""
        if adj not in ("qfq", None) or begin is not None or end is not None:
            raise UsageError(
                "demo 快照只有近 120 根不复权日 K，不支持自定义区间/复权；"
                "真实回测请用 Client.from_env()（建议 max_limit=None 取全历史）",
                code="demo_unsupported",
            )
        rule = str(rule or "ma_cross").lower()
        if rule == "ma":
            rule = "ma_cross"
        bars = self._kline_bars(symbol, n=120, adj=None)
        rows = bars.to_dict("records") if hasattr(bars, "to_dict") else bars
        rows.sort(key=lambda r: str(r.get("date") or ""))
        warnings: list[str] = []
        if rule in VALUATION_RULES:
            if rule != "pe":
                raise UsageError("demo 快照只保存 pe/3y 估值序列", code="demo_unsupported")
            if buy is None or sell is None:
                raise UsageError(f"rule={rule} 需要 buy/sell 阈值（如 buy=20, sell=40）",
                                 code="params")
            buy, sell = float(buy), float(sell)
            if not (0 < buy < sell):
                raise UsageError(f"估值阈值需 0 < buy < sell，收到 buy={buy}, sell={sell}",
                                 code="params")
            # 快照 series 为 [{date, value}]（2.0 口径）；valuation_by_date 收
            # [[unix 秒, 值]]——按交易所本地零点（+08:00）换回 epoch，与 live 同源
            ep = _dt.date(1970, 1, 1)
            pairs = []
            for row in self._data["valuation"]["series"]:
                try:
                    d = _dt.date.fromisoformat(str(row.get("date"))[:10])
                except ValueError:
                    continue
                pairs.append([(d - ep).days * 86400 - 8 * 3600, row.get("value")])
            values = valuation_by_date(pairs)
            first = min(values)
            rows = [r for r in rows if str(r.get("date") or "")[:10] >= first]
            if not rows:
                raise UsageError("演示行情与估值序列没有重叠区间", code="demo_unsupported")
            signals, missing = valuation_signals(rows, values, buy, sell)
            if missing:
                warnings.append(f"{missing} 根没有 PE 估值（亏损期/未覆盖），当日不出信号")
            label = f"{rule}(buy={buy:g}, sell={sell:g})"
        else:
            signals = ma_cross_signals(rows, fast=int(fast), slow=int(slow))
            label = f"ma_cross(fast={int(fast)}, slow={int(slow)})"
        out = run_backtest(rows, signals, cash=float(cash), rule=label)
        out["symbol"] = symbol
        out["caliber"].update({"demo": True, "adj": None})
        if rule in VALUATION_RULES:
            out["caliber"]["valuation"] = {"metric": rule, "window": "3y"}
        out["warnings"] = warnings + out["warnings"] + [
            f"演示快照：120 根不复权日 K（{_AS_OF}，非实时），仅用于验证调用形态"]
        return out

    def _screen_query(self, where: str, order: str | None = None, desc: bool = True,
                      limit: int = 50, offset: int = 0,
                      fields: list[str] | None = None, idx: str | None = None) -> Any:
        """演示快照只有 10 只票的截面，没有全市场索引列——不做假筛选。"""
        raise UsageError(
            "demo 快照不含全市场索引，screener.query 需真实凭证（Client.from_env()）；"
            "离线可用 index_breadth_summary / index_top_movers / screen_* 演示接口",
            code="demo_unsupported",
        )

    def _top_movers(self, limit: int = 20, desc: bool = True,
                    idx: str | None = None) -> Any:
        if idx is not None:
            raise UsageError("demo 快照只保存默认全市场索引", code="demo_unsupported")
        if int(limit) <= 0 or int(limit) > 10:
            raise UsageError("demo 涨跌榜最多保存 10 行", code="demo_limit")
        key = "top_movers_up" if desc else "top_movers_down"
        rows = [dict(row) for row in self._data["screener"][key][:int(limit)]]
        from wmshare.client import to_output_frame
        return to_output_frame(rows)

    def _valuation_hist_stats(self, symbol: str, metric: str = "pe",
                              window: str = "3y") -> dict[str, Any]:
        """与 live 同形：统一信封 + ``data.series`` 为 DataFrame（date/value 升序）。"""
        if metric != "pe" or window != "3y":
            raise UsageError("demo valuation 快照只保存 pe/3y", code="demo_unsupported")
        self._require_symbol(symbol)
        snap = self._data["valuation"]
        data = {k: v for k, v in snap.items() if k != "series"}
        data["series"] = self._df_asc([dict(r) for r in snap.get("series") or []], "date")
        return {"ok": True, "as_of": _AS_OF, "data": data,
                "meta": {"metric": metric, "window": window}}

    def _valuation_daily_basic(self, symbol: str, begin: str = "",
                               end: str = "", fields: str = "") -> dict[str, Any]:
        """demo 未收录该物化表——显式不支持（2.0 demo 纪律：不伪造）。

        罐头样本待服务端 pipeline.cn.valuation_daily 样本组首跑后重拍快照；
        live 模式（valuation.daily_basic 物化表就绪后）不受影响。
        """
        self._require_symbol(symbol)
        raise UsageError(
            "demo 快照未收录 valuation.daily_basic（服务端物化表尚未投产，"
            "无真实罐头值可回放）；live 模式可用。", code="demo_unsupported")

    def _valuation_daily_basic_multi(self, symbols: Any, begin: str = "",
                                     end: str = "", fields: Any = None) -> dict[str, Any]:
        """与 live 同签名；物化表未入快照，显式 demo_unsupported。"""
        if not isinstance(symbols, (list, tuple)) or not symbols:
            raise UsageError("symbols 只接受非空 list/tuple", code="params")
        raise UsageError(
            "demo 快照未收录 valuation.daily_basic_multi；live 模式可用。",
            code="demo_unsupported")

    def _valuation_daily_basic_coverage(self, symbol: str, begin: str = "",
                                        end: str = "") -> dict[str, Any]:
        """与 live 同签名；物化表未入快照，显式 demo_unsupported（不伪造范围）。"""
        self._require_symbol(symbol)
        raise UsageError(
            "demo 快照未收录 valuation.daily_basic 的 window 元数据；live 模式可用。",
            code="demo_unsupported")

    # ---- generic and batch surfaces ----
    def _notice_poller(self, *, group: str, consumer: str,
                       on_events: Callable[[list[NoticeStreamEvent]], Any] | None = None,
                       **kw: Any) -> DemoPoller:
        if not str(group).strip() or not str(consumer).strip():
            raise UsageError("group 与 consumer 必填", code="params")
        return DemoPoller(self._data["notice_event"], on_events)

    def _batch(self, name: str, symbols: list[str], **kwargs: Any) -> BatchResult:
        if name == "kline.snapshot":
            results = {self._require_snapshot_symbol(s): self._kline_snapshot(s)
                       for s in symbols}
        elif name == "bonus.snapshot_yield_ttm":
            results = {self._require_symbol(s): self._dividend_yield(s) for s in symbols}
        else:
            raise _unsupported(name, "批量函数")
        return BatchResult(results=results, requests=max(1, -(-len(results) // 500)))

    def _batch_all(self, name: str, symbols: list[str], /, batch_size: int | None = None,
                   on_batch_error: str = "raise", _raw: bool = False,
                   _units: str = "base", **kwargs: Any) -> BatchResult:
        if on_batch_error != "raise":
            raise UsageError("demo 批量只支持 on_batch_error='raise'", code="demo_unsupported")
        return self._batch(name, list(symbols))

    def _batch_iter(self, name: str, symbols: list[str], /, batch_size: int | None = None,
                    on_batch_error: str = "raise", _raw: bool = False,
                    _units: str = "base", **kwargs: Any):
        yield self._batch(name, list(symbols))

    def _call_batch(self, name: str, symbols: list[str], /, on_error: str = "raise",
                    _raw: bool = False, _units: str = "base",
                    **kwargs: Any) -> BatchResult:
        if on_error not in ("raise", "skip"):
            raise UsageError("on_error 只支持 raise 或 skip", code="params")
        return self._batch(name, list(symbols))

    def _call(self, name: str, /, _raw: bool = False,
              _units: str = "base", **kwargs: Any) -> Any:
        symbol = kwargs.get("symbol") or kwargs.get("sym") or ""
        if name == "kline.query_bars":
            return self._kline_bars(symbol, n=kwargs.get("n") or kwargs.get("limit") or 120,
                                    _raw=_raw)
        if name == "kline.snapshot":
            return self._kline_snapshot(symbol)
        if name == "bonus.snapshot_yield_ttm":
            return self._dividend_yield(symbol)
        raise _unsupported(name)

    def close(self) -> None:
        return None

    def __enter__(self) -> "DemoClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        # 函数内惰性导入：模块加载期 wmshare 尚未完成初始化，不能顶层 import。
        import wmshare
        p = DEMO_SNAPSHOT_PROVENANCE
        return (
            f"wmshare.demo_client()  # 真实 API 固定快照（as_of={self._doc['as_of']}, "
            f"10 只演示宇宙，非实时行情）；接真实数据请 wmshare.Client.from_env()\n"
            f"  # 快照 SDK {p['snapshot_sdk_version']} / catalog_rev "
            f"{p['snapshot_catalog_rev']}\n"
            f"  # 当前 SDK {wmshare.__version__}（快照不随发版更新；"
            "用 wmshare_status 的 demo_snapshot 对照）"
        )


    def _index_ns(self) -> SimpleNamespace:
        """指数域罐头：universe_keys/keys/valuation/trend（冻结快照 2026-11-16 口径）。

        trend 覆盖与 live 同构的三组键：11 宽基 + 申万一级行业（此处取 6 个代表键，
        live 为全部 31 个）+ 2 个红利键——行业路径必须可离线验证，否则
        ``universe_keys("industry")`` 返空会让「行业无估值历史」被误判为平台缺陷。
        """
        uni = ["index.hs300", "index.csi500", "index.sz50", "index.cybz", "index.star50",
               "index.shzs", "index.szcz", "index.zx100", "index.szzzs", "index.gz2000",
               "index.kc200"]
        ind = ["industry.S11", "industry.S22", "industry.S23", "industry.S24",
               "industry.S27", "industry.S28"]
        div = ["index.csidividend", "index.ssedividend"]
        cur = {
            "index.hs300": {"pe": 13.42, "pb": 1.25, "dv": 0.0231},
            "index.csi500": {"pe": 27.62, "pb": 2.01, "dv": 0.0154},
            "index.sz50": {"pe": 11.42, "pb": 1.11, "dv": 0.0267},
            "index.cybz": {"pe": 27.45, "pb": 4.02, "dv": 0.0127},
            "index.star50": {"pe": 91.5, "pb": 6.05, "dv": 0.0026},
            "index.shzs": {"pe": 15.71, "pb": 1.3, "dv": 0.0198},
            "index.szcz": {"pe": 24.1, "pb": 2.26, "dv": 0.0181},
            "index.zx100": {"pe": 21.3, "pb": 2.43, "dv": 0.0151},
            "index.szzzs": {"pe": 33.9, "pb": 2.27, "dv": 0.0149},
            "index.gz2000": {"pe": 46.8, "pb": 2.14, "dv": 0.0118},
            "index.kc200": {"pe": 128.0, "pb": 3.52, "dv": 0.0056},
            # 申万一级行业（整体法 PE/PB，量级与指数同阶）
            "industry.S11": {"pe": 21.6, "pb": 2.35, "dv": 0.0189},
            "industry.S22": {"pe": 14.8, "pb": 1.42, "dv": 0.0246},
            "industry.S23": {"pe": 18.2, "pb": 1.88, "dv": 0.0205},
            "industry.S24": {"pe": 26.4, "pb": 2.91, "dv": 0.0132},
            "industry.S27": {"pe": 29.8, "pb": 3.14, "dv": 0.0117},
            "industry.S28": {"pe": 16.9, "pb": 1.63, "dv": 0.0221},
            # 红利指数
            "index.csidividend": {"pe": 8.42, "pb": 0.86, "dv": 0.0481},
            "index.ssedividend": {"pe": 8.73, "pb": 0.91, "dv": 0.0462},
        }

        def _trend(key: str, window: str = "5y") -> dict:
            # 确定性合成周频序列：每键目标分位按 seed 铺开 5%~95%（分位演示各不相同；
            # 序列形状仍为正弦波，真实数据以 live 为准）。
            # 2.0 方向契约：与 live 一致按**升序**（旧→新）输出，最新点在末行。
            import math
            base = cur.get(key) or {"pe": 20.0, "pb": 2.0}
            seed = sum(ord(c) for c in key) % 11
            n = 120
            amp = 0.12 + 0.012 * seed
            ph = seed * 0.57

            def _series(scale: str, target_pct: float) -> list[float]:
                waves = [base[scale] *
                         (1.0 - amp * math.sin((i / (n - 1)) * 6.28318 + ph))
                         for i in range(n)]
                sv = sorted(waves)
                target = sv[min(n - 1, int((n - 1) * target_pct))]
                c = target - waves[-1]           # 线性倾斜使终点落在目标分位
                return [w + c * (i / (n - 1)) for i, w in enumerate(waves)]

            tgt_pe = 0.05 + (seed / 10) * 0.90
            tgt_pb = 0.05 + (((seed + 5) % 11) / 10) * 0.90
            pe_s = _series("pe", tgt_pe)
            pb_s = _series("pb", tgt_pb)
            pts: list[list[float | str]] = []
            for i in range(n):  # 行=[date, pe, pb]，升序（旧→新，2.0 标准）
                pts.append([_demo_date(i, n), round(pe_s[i], 4), round(pb_s[i], 4)])
            w = str(window or "5y").lower()
            if w not in ("3y", "5y", "10y"):
                w = "5y"

            def _pct(col: int, cur_v: float | None, window_n: int = 0) -> dict:
                """单列分位：rank0/(n-1)，并列取中点（与 live/前端同口径）。

                ``window_n`` 为窗口内的点数（取最近 window_n 个点；0=全序列）。
                pts 是旧→新，故 ``pts[-window_n:]`` 恰是最近的一段。
                """
                rows = pts[len(pts) - window_n:] if window_n else pts
                vals: list[float] = []
                for p in rows:
                    v = p[col]
                    if isinstance(v, (int, float)) and v > 0:
                        vals.append(float(v))
                n_v = len(vals)
                if n_v < 2 or cur_v is None:
                    return {"p": None, "n": n_v}
                ordered = sorted(vals)
                lo = sum(1 for v in ordered if v < cur_v)
                eq = sum(1 for v in ordered if v == cur_v)
                if eq <= 0:
                    return {"p": None, "n": n_v}
                return {"p": (lo + lo + eq - 1) / 2 / (n_v - 1), "n": n_v}

            # 三档按各自窗口取样本（live 亦如此：n3 < n5 < n10）。此前把三档算成
            # 同一个数，导致「pe_pct 恒取 5y」的 bug 在离线测试里完全不可见。
            # demo 只有 120 周（≈2.3 年），3y 窗口取后 60%，5y/10y 均覆盖全序列；
            # 与 live 一致地声明 trunc10=True（不拿短序列冒充 10 年）。
            _WIN_ROWS = {"3y": int(n * 0.6), "5y": n, "10y": n}

            def _bundle(col: int, cur_v: float | None) -> dict:
                b3 = _pct(col, cur_v, _WIN_ROWS["3y"])
                b5 = _pct(col, cur_v, _WIN_ROWS["5y"])
                b10 = _pct(col, cur_v, _WIN_ROWS["10y"])
                # live 序列约 9.98 年，服务端 trunc10=True 时把 p10 置 None（不拿
                # 短窗口冒充长窗口）。demo 只有 2.3 年，必须同构地置 None。
                return {"p": b5["p"], "p3": b3["p"], "p5": b5["p"], "p10": None,
                        "n3": b3["n"], "n5": b5["n"], "n10": b10["n"], "trunc10": True}

            last_pe, last_pb = float(pts[-1][1]), float(pts[-1][2])  # 最新点=末行
            pe_b = _bundle(1, last_pe)
            pb_b = _bundle(2, last_pb)
            # 与 live 同选择逻辑：按 window 取档；10y 因 trunc10 给 None（不降级）
            _FIELD = {"3y": "p3", "5y": "p5", "10y": "p10"}
            _trunc = w == "10y" and bool(pe_b.get("trunc10"))
            pe_sel = None if _trunc else pe_b.get(_FIELD[w])
            pb_sel = None if _trunc else pb_b.get(_FIELD[w])
            eff_win = None if _trunc else w
            from wmshare.client import to_output_frame
            data = {"key": key, "density": "weekly", "n": n,
                    "points": to_output_frame(
                        [{"date": p[0], "pe": p[1], "pb": p[2]} for p in pts]),
                    "pe_pct": pe_sel,
                    "pb_pct": pb_sel, "pe_pct_window": eff_win,
                    "pe_missing": False, "pb_missing": False, "med": [],
                    "window": w, "win_start": pts[0][0], "win_n": n, "win_trunc": True,
                    "pct": {"pe": pe_b, "pb": pb_b, "pe_med": {}}}
            return {"ok": True, "as_of": _AS_OF, "data": data,
                    "meta": {"pct_source": "server", "dv_has_history": False}}

        def _demo_date(i: int, n: int) -> str:
            """第 i 周（0=最旧）的日期，升序生成；落库时整体反转为新→旧。"""
            from datetime import date, timedelta
            return (date(2024, 6, 7) + timedelta(weeks=i)).isoformat()

        def _valuation(key: str, points: int | None = None):
            c = cur.get(key)
            if not c:
                data = {"current": {"pe": None, "pb": None, "dv": None}, "series": []}
                return {"ok": True, "as_of": _AS_OF, "data": data, "meta": {}}
            series = [{"d": _demo_date(i, 8),
                       "pe": round(c["pe"] * (1 - 0.02 * i / 7), 4),
                       "pb": round(c["pb"] * (1 - 0.02 * i / 7), 4)}
                      for i in range(8)]  # 升序（旧→新，2.0 标准）
            from wmshare.client import to_output_frame
            data = {"current": dict(c), "series": to_output_frame(series)}
            return {"ok": True, "as_of": _AS_OF, "data": data, "meta": {}}

        def _members(key: str, sort_by: str = "mv", top_n: int | None = None):
            rows = [
                {"symbol": "600519", "name": "贵州茅台", "mv": 1.82e12, "pe_ttm": 21.5,
                 "pb": 7.8, "ps_ttm": 15.0, "roe_ttm": 0.31, "close": 1450.0, "percent": 0.038},
                {"symbol": "601939", "name": "建设银行", "mv": 3.12e12, "pe_ttm": 8.8,
                 "pb": 0.85, "ps_ttm": 3.8, "roe_ttm": 0.1, "close": 11.9, "percent": 0.021},
            ]
            return rows[: top_n or len(rows)]

        def _weights(key: str, top_n: int | None = None):
            rows = [
                {"symbol": "600519", "name": "贵州茅台", "weight": 0.038, "mv": 1.82e12,
                 "pe_ttm": 21.5, "roe_ttm": 0.31},
                {"symbol": "601939", "name": "建设银行", "weight": 0.021, "mv": 3.12e12,
                 "pe_ttm": 8.8, "roe_ttm": 0.1},
            ]
            return rows[: top_n or len(rows)]

        return SimpleNamespace(
            keys=lambda: list(uni) + list(ind) + list(div),
            universe_keys=lambda group="broad": list({
                "broad": uni, "industry": ind, "dividend": div,
                "all": list(uni) + list(ind) + list(div),
            }.get(str(group or "broad").lower(), [])),
            members=_members,
            weights=_weights,
            valuation=_valuation,
            trend=_trend,
        )


def demo_client() -> DemoClient:
    """创建零凭证、离线、固定快照的演示客户端。

    快照来自真实 API 的 2026-11-16 固定日，包含 10 只演示宇宙与当日全市场 screener。
    与真实 Client 不同处：数据不更新、只覆盖公开示例调用面、未知演示标的报错。
    """
    return DemoClient()
