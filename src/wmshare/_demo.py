"""离线演示客户端：真实 API 固定快照回放，零凭证、不联网。

快照日为 2026-10-30，由维护者用 ``tools/generate_demo_snapshot.py`` 生成。
数据覆盖 examples 的 demo 路径：10 只 A 股演示宇宙 + 当日真实全市场 screener。
它不是实时行情，也不承诺覆盖全部 252 个目录函数；接真实数据用
``wmshare.Client.from_env()``。
"""
from __future__ import annotations

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
_AS_OF = "2026-10-30"
_CATALOG_REV = "d9bbd944"
_SDK_VERSION = "1.11.0"
_UNIVERSE = (
    "600519", "000858", "601088", "600900", "601318",
    "000001", "600036", "000333", "300750", "688981",
)
_MAX_BARS = 120
_MAX_MONEYFLOW_BARS = 30
_MAX_DIVIDEND_HISTORY = 20
_MAX_BANK_MEMBERS = 20
# 期货与宏观罐头（v1.11 后新数据面）：PROD 活体探针实证值（2026-11-07），不在
# 2026-10-30 快照采集范围内，故不进 _demo_data.json（避免破坏快照哈希合同）
_FUT_CANS: dict[str, float] = {"$FUT_CLOSE": 5354.0, "$FUT_VOLUME": 302888.0}

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
        if dates != sorted(dates, reverse=True):
            raise ValueError(f"kline_bars[{sym}] 不是日期降序")
        snapshot = _require_mapping(snapshots[sym], f"kline_snapshot[{sym}]")
        _check_finite(snapshot.get("close"), f"kline_snapshot[{sym}].close")
        _check_date_not_after(snapshot.get("kline_date"), f"kline_snapshot[{sym}].kline_date")
        if str(snapshot.get("kline_date", ""))[:10] != dates[0]:
            raise ValueError(f"{sym} snapshot.kline_date 与最新 bar.date 不一致")
        _check_finite(rows[0].get("close"), f"kline_bars[{sym}][0].close")
        if not math.isclose(float(snapshot["close"]), float(rows[0]["close"]),
                            rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"{sym} snapshot.close 与最新 bar.close 不一致")

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
    years = statements.get("years")
    if not isinstance(years, list) or years != sorted(years, reverse=True):
        raise ValueError("statements.years 必须非空且降序")
    for kind in ("income", "balance", "cashflow"):
        rows = _require_rows(statements.get(kind), f"statements.{kind}")
        if not any(row.get("vals") for row in rows):
            raise ValueError(f"statements.{kind} 缺少非空 vals")
    for i, row in enumerate(_require_rows(statements.get("compare"), "statements.compare")):
        diff, pct, combined = row.get("diff"), row.get("diffp"), row.get("c")
        if not isinstance(diff, dict) or not isinstance(pct, dict) \
                or not isinstance(combined, dict):
            continue
        for key, diff_value in diff.items():
            if key not in pct or key not in combined:
                continue
            p, d, c = pct[key], diff_value, combined[key]
            if not all(_is_finite_number(x) for x in (p, d, c)) or float(c) == 0:
                continue
            expected = float(d) / float(c)
            if abs(float(p) - expected) > max(1e-9, abs(expected) * 1e-6):
                raise ValueError(f"statements.compare[{i}][{key}] 的 diffp 不一致")

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

    return doc


def load_demo_snapshot() -> dict[str, Any]:
    """加载、校验并返回打包的 demo 快照（内部函数，测试和生成器校验可用）。"""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        try:
            raw = _DATA_PATH.read_bytes()
        except OSError as e:
            raise RuntimeError(f"demo 快照缺失或不可读：{_DATA_PATH.name}") from e
        if len(raw) > 512 * 1024:
            raise RuntimeError("demo 快照超过 512 KiB")
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
            last=self._kline_snapshot,
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
            years=self._statement_years,
            compare=self._statement_compare,
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
        self.notice = SimpleNamespace(list=self._notice_list)
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
            screen_limit_up=lambda sym: self._screen(sym, "limit_up"),
            screen_above_ma20=lambda sym: self._screen(sym, "above_ma20"),
            screen_volume_spike=lambda sym: self._screen(sym, "volume_spike"),
            screen_up_today=lambda sym: self._screen(sym, "up_today"),
            index_breadth_summary=lambda: dict(self._data["screener"]["breadth_summary"]),
            index_breadth_bins=lambda: [dict(row) for row in self._data["screener"]["breadth_bins"]],
            index_top_movers=self._top_movers,
            query=self._screen_query,
        )
        self.valuation = SimpleNamespace(hist_stats=self._valuation_hist_stats)
        self.index = self._index_ns()
        self.batch_all = self._batch_all
        self.batch_iter = self._batch_iter
        self.call_batch = self._call_batch
        self.notice_poller = self._notice_poller
        self.call = self._call

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

    def _maybe_df(self, rows: list[dict[str, Any]], df_flag: bool) -> Any:
        if not df_flag:
            return rows
        try:
            import pandas as pd
        except ImportError as e:
            raise UsageError('_df=True 需要 pandas：pip install "wmshare[dataframe]"') from e
        return pd.DataFrame(rows)

    # ---- market data ----
    def _kline_bars(self, symbol: str, n: int | None = None, adj: str | None = None,
                    begin: str | None = None, end: str | None = None,
                    _raw: bool = False, _df: bool = False) -> Any:
        if adj is not None or begin is not None or end is not None or _raw:
            raise UsageError(
                "demo 快照只覆盖不复权、不带日期区间的 kline.bars(n<=120)",
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
        rows = [dict(row) for row in self._data["kline_bars"][sym][:count]]
        return self._maybe_df(rows, _df)

    def _kline_snapshot(self, symbol: str) -> dict[str, Any]:
        sym = self._require_snapshot_symbol(symbol)
        return dict(self._data["kline_snapshot"][sym])

    def _kline_batch_live(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {self._require_snapshot_symbol(s): self._kline_snapshot(s)
                for s in symbols}

    def _moneyflow_last(self, symbol: str, _raw: bool = False) -> Any:
        if _raw:
            raise UsageError("demo 快照不提供 _raw 原始口径", code="demo_unsupported")
        sym = self._require_symbol(symbol)
        value = self._data["moneyflow_last"][sym]
        return dict(value) if isinstance(value, dict) else value

    def _moneyflow_bars(self, symbol: str, n: int = 20, _raw: bool = False,
                        _df: bool = False) -> Any:
        if _raw:
            raise UsageError("demo 快照不提供 _raw 原始口径", code="demo_unsupported")
        count = int(n)
        if count <= 0 or count > _MAX_MONEYFLOW_BARS:
            raise UsageError(
                f"demo 快照最多保存 {_MAX_MONEYFLOW_BARS} 根资金流，收到 {count}",
                code="demo_limit",
            )
        sym = self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["moneyflow_bars"][sym][:count]]
        return self._maybe_df(rows, _df)

    def _moneyflow_board(self, _df: bool = False) -> Any:
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
        return self._maybe_df(rows, _df)

    # ---- fundamentals ----
    def _statement(self, kind: str):
        def method(symbol: str, years: int = 5, scope: str = "合并",
                   _df: bool = False) -> Any:
            if scope != "合并":
                raise UsageError("demo 快照只保存合并报表", code="demo_unsupported")
            if int(years) <= 0:
                raise UsageError("years 必须为正整数", code="params")
            sym = self._require_symbol(symbol)
            if sym != "600519":
                raise UsageError("demo 报表快照只覆盖 600519", code="demo_symbol")
            rows = _slice_statement_rows(self._data["statements"][kind], int(years))
            return self._maybe_df(rows, _df)
        return method

    def _statement_years(self, symbol: str, kind: str = "income", _df: bool = False) -> list[str]:
        self._require_symbol(symbol)
        if kind not in ("income", "balance", "cashflow"):
            raise UsageError(f"未知报表 kind={kind!r}", code="params")
        return list(self._data["statements"]["years"])

    def _statement_compare(self, symbol: str, kind: str = "income", years: int = 2,
                           _df: bool = False) -> Any:
        if kind != "income":
            raise UsageError("demo compare 快照只保存 income", code="demo_unsupported")
        if int(years) <= 0 or int(years) > 2:
            raise UsageError("demo compare 快照最多 2 期", code="demo_limit")
        self._require_symbol(symbol)
        rows = _slice_statement_rows(self._data["statements"]["compare"], int(years))
        return self._maybe_df(rows, _df)

    def _statement_audit(self, symbol: str) -> dict[str, str]:
        self._require_symbol(symbol)
        return dict(self._data["statements"]["audit"])

    def _indicator_get(self, symbol: str, code: str, **kw: Any) -> Any:
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

    def _indicator_metrics(self, symbol: str, codes: list[str], **kw: Any) -> dict[str, Any]:
        return {code: self._indicator_get(symbol, code, **kw) for code in codes}

    # ---- disclosure ----
    def _notice_list(self, symbol: str, window: str = "3m", keyword: str = "",
                     limit: int = 20, _raw: bool = False, _df: bool = False) -> Any:
        self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["notices"][:max(0, int(limit))]]
        return self._maybe_df(rows, _df)

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
                          _raw: bool = False, _df: bool = False) -> Any:
        if begin is not None or end is not None or _raw:
            raise UsageError("demo 分红快照只支持 limit 查询", code="demo_unsupported")
        count = 20 if limit is None else int(limit)
        if count <= 0 or count > _MAX_DIVIDEND_HISTORY:
            raise UsageError(
                f"demo 分红快照最多 {_MAX_DIVIDEND_HISTORY} 行，收到 {count}", code="demo_limit",
            )
        sym = self._require_symbol(symbol)
        rows = [dict(row) for row in self._data["dividend"]["history"][sym][:count]]
        return self._maybe_df(rows, _df)

    def _dividend_screen_quality(self, symbol: str, min_yield: float | None = None,
                                 payout_min: float | None = None,
                                 payout_max: float | None = None,
                                 _raw: bool = False, _df: bool = False) -> bool:
        if _raw or _df:
            raise UsageError("demo screen_quality 只返回布尔值", code="demo_unsupported")
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

    def _stocks_list(self, _df: bool = False) -> Any:
        rows = [dict(row) for row in self._data["stocks_list"]]
        return self._maybe_df(rows, _df)

    def _industries(self, level: int | None = None, _df: bool = False) -> Any:
        if level is not None and int(level) != 1:
            raise UsageError("demo 快照只保存一级行业", code="demo_limit")
        rows = [dict(row) for row in self._data["industries"]]
        return self._maybe_df(rows, _df)

    def _industry_members(self, industry: str, top_n: int | None = None,
                          _df: bool = False) -> Any:
        if str(industry) not in ("银行", "S48"):
            raise UsageError(
                "demo 快照只保存「银行」行业成分；可传 银行 或 S48", code="demo_symbol",
            )
        rows = [dict(row) for row in self._data["industry_members_bank"]]
        if top_n is not None:
            rows = rows[:max(0, int(top_n))]
        return self._maybe_df(rows, _df)

    # ---- screener ----
    def _screen(self, symbol: str, key: str) -> bool:
        sym = self._require_symbol(symbol)
        return bool(self._data["screener"]["screens"][sym][key])

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
        rows = [dict(r) for r in self._kline_bars(symbol, n=120, adj=None)]
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
            values = valuation_by_date(self._data["valuation"]["series"])
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
            "演示快照：120 根不复权日 K（2026-10-30，非实时），仅用于验证调用形态"]
        return out

    def _screen_query(self, where: str, order: str | None = None, desc: bool = True,
                      limit: int = 50, offset: int = 0,
                      fields: list[str] | None = None, idx: str | None = None,
                      _df: bool = False) -> Any:
        """演示快照只有 10 只票的截面，没有全市场索引列——不做假筛选。"""
        raise UsageError(
            "demo 快照不含全市场索引，screener.query 需真实凭证（Client.from_env()）；"
            "离线可用 index_breadth_summary / index_top_movers / screen_* 演示接口",
            code="demo_unsupported",
        )

    def _top_movers(self, limit: int = 20, desc: bool = True,
                    idx: str | None = None, _df: bool = False) -> Any:
        if idx is not None:
            raise UsageError("demo 快照只保存默认全市场索引", code="demo_unsupported")
        if int(limit) <= 0 or int(limit) > 10:
            raise UsageError("demo 涨跌榜最多保存 10 行", code="demo_limit")
        key = "top_movers_up" if desc else "top_movers_down"
        rows = [dict(row) for row in self._data["screener"][key][:int(limit)]]
        return self._maybe_df(rows, _df)

    def _valuation_hist_stats(self, symbol: str, metric: str = "pe",
                              window: str = "3y") -> dict[str, Any]:
        if metric != "pe" or window != "3y":
            raise UsageError("demo valuation 快照只保存 pe/3y", code="demo_unsupported")
        self._require_symbol(symbol)
        return dict(self._data["valuation"])

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
            raise UsageError(f"demo 快照不支持批量函数 {name!r}", code="demo_unsupported")
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
                    _raw: bool = False, _df: bool = False, _units: str = "base",
                    **kwargs: Any) -> BatchResult:
        if on_error not in ("raise", "skip"):
            raise UsageError("on_error 只支持 raise 或 skip", code="params")
        return self._batch(name, list(symbols))

    def _call(self, name: str, /, _raw: bool = False, _df: bool = False,
              _units: str = "base", **kwargs: Any) -> Any:
        symbol = kwargs.get("symbol") or kwargs.get("sym") or ""
        if name == "kline.query_bars":
            return self._kline_bars(symbol, n=kwargs.get("n") or kwargs.get("limit") or 120,
                                    _raw=_raw, _df=_df)
        if name == "kline.snapshot":
            return self._kline_snapshot(symbol)
        if name == "bonus.snapshot_yield_ttm":
            return self._dividend_yield(symbol)
        return []

    def close(self) -> None:
        return None

    def __enter__(self) -> "DemoClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"wmshare.demo_client()  # 真实 API 固定快照（as_of={self._doc['as_of']}, "
            f"10 只演示宇宙，非实时行情）；接真实数据请 wmshare.Client.from_env()"
        )


    def _index_ns(self) -> SimpleNamespace:
        """指数域罐头：universe_keys/keys/valuation/trend（冻结快照 2026-10-30 口径）。"""
        uni = ["index.hs300", "index.csi500", "index.sz50", "index.cybz", "index.star50",
               "index.shzs", "index.szcz", "index.zx100", "index.szzzs", "index.gz2000",
               "index.kc200"]
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
        }

        def _trend(key: str, window: str = "5y") -> dict:
            # 确定性合成周频序列：每键目标分位按 seed 铺开 5%~95%（分位演示各不相同；
            # 序列形状仍为正弦波，真实数据以 live 为准）。
            # 方向必须与 live 一致：**新→旧**，points[0] 是最新点。
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
            for i in range(n):  # 行=[date, pe, pb]，生成升序；落库前反转为新→旧
                pts.append([_demo_date(i, n), round(pe_s[i], 4), round(pb_s[i], 4)])
            pts.reverse()  # 落库前反转为新→旧（与 cursor.ds 顺序一致）
            w = str(window or "5y").lower()
            if w not in ("3y", "5y", "10y"):
                w = "5y"

            def _pct(col: int, cur_v: float | None) -> dict:
                """单列分位：rank0/(n-1)，并列取中点（与 live/前端同口径）。"""
                vals: list[float] = []
                for p in pts:
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

            def _bundle(col: int, cur_v: float | None) -> dict:
                b = _pct(col, cur_v)
                p = b["p"]
                # demo 序列只有 120 周，三档窗口用同一批样本；不作窗口截断声明
                return {"p": p, "p3": p, "p5": p, "p10": p,
                        "n3": b["n"], "n5": b["n"], "n10": b["n"], "trunc10": False}

            last_pe, last_pb = float(pts[0][1]), float(pts[0][2])  # 行=[date, pe, pb]
            pe_b = _bundle(1, last_pe)
            pb_b = _bundle(2, last_pb)
            sel = {"3y": pe_b["p3"], "5y": pe_b["p5"], "10y": pe_b["p10"]}[w]
            return {"ok": True, "key": key, "as_of": "2026-10-30", "density": "weekly",
                    "n": n,
                    "points": [{"date": p[0], "pe": p[1], "pb": p[2]} for p in pts],
                    "pe_pct": sel,
                    "pb_pct": pb_b["p5"], "med": [],
                    "window": w, "win_start": pts[-1][0], "win_n": n, "win_trunc": False,
                    "pct": {"pe": pe_b, "pb": pb_b, "pe_med": {}},
                    "pct_source": "server", "dv_has_history": False}

        def _demo_date(i: int, n: int) -> str:
            """第 i 周（0=最旧）的日期，升序生成；落库时整体反转为新→旧。"""
            from datetime import date, timedelta
            return (date(2024, 6, 7) + timedelta(weeks=i)).isoformat()

        def _valuation(key: str, points: int | None = None):
            c = cur.get(key)
            if not c:
                return {"current": {"pe": None, "pb": None, "dv": None}, "series": []}
            series = [{"d": _demo_date(i, 8),
                       "pe": round(c["pe"] * (1 - 0.02 * (7 - i) / 7), 4),
                       "pb": round(c["pb"] * (1 - 0.02 * (7 - i) / 7), 4)}
                      for i in range(8)]
            return {"current": dict(c), "series": series}

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
            keys=lambda: list(uni),
            universe_keys=lambda group="broad": (
                list(uni) if str(group or "broad").lower() in ("broad", "all") else []),
            members=_members,
            weights=_weights,
            valuation=_valuation,
            trend=_trend,
        )


def demo_client() -> DemoClient:
    """创建零凭证、离线、固定快照的演示客户端。

    快照来自真实 API 的 2026-10-30 固定日，包含 10 只演示宇宙与当日全市场 screener。
    与真实 Client 不同处：数据不更新、只覆盖公开示例调用面、未知演示标的报错。
    """
    return DemoClient()
