#!/usr/bin/env python3
"""Generate the packaged wmshare demo snapshot from the real CN API.

Maintainer tool. Credentials are read only from the standard wmshare environment
or credentials file via ``Client.from_env``; this script never accepts secrets on
the command line and never prints credential values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections.abc import Mapping
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

from wmshare import __version__, load
from wmshare.client import Client

AS_OF = date(2026, 10, 30)
UNIVERSE = (
    "600519", "000858", "601088", "600900", "601318",
    "000001", "600036", "000333", "300750", "688981",
)
WATCHLIST = UNIVERSE[:5]
INDICATORS = (
    "$PE_TTM_LAST", "$ROE_TTM_LAST",
    "$PCT_PE_TTM_10Y_LAST", "$CUR_IND_ROE_PCT_LAST",
)
QUALITY_VARIANTS = (
    {},
    {"min_yield": 0.02, "payout_max": 1.2},
    {"min_yield": 0.02, "payout_max": 1.5},
)
MAX_BYTES = 512 * 1024


class CountingSession(requests.Session):
    """Session that records how many HTTP requests the capture consumed."""

    def __init__(self) -> None:
        super().__init__()
        self.request_count = 0

    def post(self, *args: Any, **kwargs: Any) -> requests.Response:
        self.request_count += 1
        return super().post(*args, **kwargs)


def _require_num(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数字，收到 {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} 必须是有限数字，收到 {value!r}")
    return result


def _require_date(value: Any, label: str) -> str:
    text = str(value or "")[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"{label} 不是合法日期：{value!r}") from e
    if parsed > AS_OF:
        raise ValueError(f"{label} 晚于快照日 {AS_OF}: {text}")
    return text


def _public_url(value: Any, label: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if text.startswith("http://"):
        text = "https://" + text[len("http://"):]
    if not text.startswith("https://"):
        raise ValueError(f"{label} 只允许 HTTPS 或空字符串：{text}")
    return text


def _parse_date(value: Any) -> str:
    text = str(value or "")[:10]
    try:
        date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"公告日期非法：{value!r}") from e
    return text


def _require_rows(value: Any, label: str, *, min_len: int = 1) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < min_len:
        raise ValueError(f"{label} 必须至少有 {min_len} 行，收到 {type(value).__name__}")
    if not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{label} 必须全是 MAP 行")
    return value


def _slice_years(values: dict[str, Any], years: int) -> dict[str, Any]:
    return dict(list(values.items())[:years])


def _slice_statement_rows(rows: list[dict[str, Any]], years: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if "vals" in item and isinstance(item["vals"], dict):
            item["vals"] = _slice_years(item["vals"], years)
        for key in ("c", "p", "diff", "diffp"):
            if key in item and isinstance(item[key], dict):
                item[key] = _slice_years(item[key], years)
        out.append(item)
    return out


def _screen_quality_args_key(args: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "min_yield": args.get("min_yield"),
            "payout_min": args.get("payout_min"),
            "payout_max": args.get("payout_max"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def capture() -> tuple[dict[str, Any], int]:
    session = CountingSession()
    cli = Client.from_env(market="cn", session=session)
    try:
        # ---- stock universe and reference rows ----
        all_stocks = _require_rows(cli.stocks.list(), "stocks.list")
        by_symbol = {str(row.get("symbol")): row for row in all_stocks}
        missing = [sym for sym in UNIVERSE if sym not in by_symbol]
        if missing:
            raise ValueError(f"stocks.list 缺少演示宇宙标的：{missing}")
        stocks_list = [by_symbol[sym] for sym in UNIVERSE]
        industries = _require_rows(cli.stocks.industries(1), "stocks.industries(1)")
        bank_members = _require_rows(
            cli.stocks.industry_members("银行"), "stocks.industry_members('银行')", min_len=5,
        )[:20]
        bank_symbols = [str(row.get("symbol")) for row in bank_members]

        # ---- per-symbol time series and snapshots ----
        kline_bars: dict[str, list[dict[str, Any]]] = {}
        snapshots: dict[str, dict[str, Any]] = {}
        moneyflow_last: dict[str, Any] = {}
        moneyflow_bars: dict[str, list[dict[str, Any]]] = {}
        dividend_yield: dict[str, Any] = {}
        dividend_last: dict[str, Any] = {}
        dividend_history: dict[str, list[dict[str, Any]]] = {}
        quality_by_args: list[dict[str, Any]] = []

        for sym in UNIVERSE:
            bars = _require_rows(
                cli.kline.bars(sym, n=120), f"kline.bars({sym})", min_len=20,
            )
            latest = bars[0]
            if _require_date(latest.get("date"), f"kline.bars({sym}).date") != AS_OF.isoformat():
                raise ValueError(
                    f"{sym} 最新 K 线日期不是 {AS_OF}，而是 {latest.get('date')!r}"
                )
            for i, row in enumerate(bars):
                where = f"kline.bars({sym})[{i}]"
                _require_date(row.get("date"), f"{where}.date")
                _require_num(row.get("close"), f"{where}.close")
                _require_num(row.get("volume"), f"{where}.volume")
                _require_num(row.get("amount"), f"{where}.amount")
                percent = _require_num(row.get("percent"), f"{where}.percent")
                if abs(percent) > 1:
                    raise ValueError(f"{where}.percent 不是小数口径：{percent}")
                if _require_num(row.get("volume"), f"{where}.volume") < 0:
                    raise ValueError(f"{where}.volume 不能为负")
                if _require_num(row.get("amount"), f"{where}.amount") < 0:
                    raise ValueError(f"{where}.amount 不能为负")

            snapshot = cli.kline.snapshot(sym)
            if not isinstance(snapshot, dict):
                raise ValueError(f"kline.snapshot({sym}) 返回 {type(snapshot).__name__}")
            close = _require_num(snapshot.get("close"), f"kline.snapshot({sym}).close")
            bar_close = _require_num(latest.get("close"), f"kline.bars({sym}).close")
            if not math.isclose(close, bar_close, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(
                    f"{sym} snapshot.close={close} 与最新 bar.close={bar_close} 不一致"
                )
            kline_bars[sym] = bars
            snapshots[sym] = snapshot

            mf_last = cli.moneyflow.last(sym)
            if mf_last is not None and not isinstance(mf_last, dict):
                raise ValueError(f"moneyflow.last({sym}) 返回非 MAP")
            mf_bars = cli.moneyflow.bars(sym, n=30)
            if mf_bars is not None:
                mf_bars = _require_rows(mf_bars, f"moneyflow.bars({sym})", min_len=0)
                for i, row in enumerate(mf_bars):
                    where = f"moneyflow.bars({sym})[{i}]"
                    _require_date(row.get("date"), f"{where}.date")
                    _require_num(row.get("net_mf"), f"{where}.net_mf")
            moneyflow_last[sym] = mf_last
            moneyflow_bars[sym] = mf_bars or []

            dividend_yield[sym] = cli.dividend.yield_ttm(sym)
            if dividend_yield[sym] is not None:
                y = _require_num(dividend_yield[sym], f"dividend.yield_ttm({sym})")
                if not 0 <= y < 1:
                    raise ValueError(f"dividend.yield_ttm({sym}) 不是小数口径：{y}")
            dividend_last[sym] = cli.dividend.last(sym)
            history = cli.dividend.history(sym, limit=20)
            dividend_history[sym] = history if isinstance(history, list) else []
            for i, row in enumerate(dividend_history[sym]):
                for field in ("ex_div", "pay"):
                    value = row.get(field)
                    if value:
                        _require_date(value, f"dividend.history({sym})[{i}].{field}")

        for args in QUALITY_VARIANTS:
            results: dict[str, Any] = {}
            for sym in WATCHLIST:
                results[sym] = bool(cli.dividend.screen_quality(sym, **args))
            quality_by_args.append({"args": dict(args), "results": results})

        # examples/07 batches bank members directly, so keep snapshots for them too.
        for sym in bank_symbols:
            snapshot = cli.kline.snapshot(sym)
            if not isinstance(snapshot, dict):
                raise ValueError(f"kline.snapshot({sym}) 返回 {type(snapshot).__name__}")
            if _require_date(
                snapshot.get("kline_date"), f"kline.snapshot({sym}).kline_date",
            ) != AS_OF.isoformat():
                raise ValueError(f"{sym} snapshot.kline_date 不是 {AS_OF}")
            snapshots[sym] = snapshot

        dividend_expression = cli.dividend.index_where_high_yield_5()
        if dividend_expression is None:
            raise ValueError("dividend.index_where_high_yield_5() 返回空")

        # ---- primary symbol financials / disclosures / reference ----
        primary = "600519"
        income = _require_rows(
            cli.statements.income(primary, years=3), "statements.income", min_len=3,
        )
        balance = _require_rows(
            cli.statements.balance(primary, years=3), "statements.balance", min_len=3,
        )
        cashflow = _require_rows(
            cli.statements.cashflow(primary, years=3), "statements.cashflow", min_len=3,
        )
        statement_years = cli.statements.years(primary, "income")
        if not isinstance(statement_years, list) or not statement_years:
            raise ValueError("statements.years 返回空")
        if statement_years != sorted(statement_years, reverse=True):
            raise ValueError(f"statements.years 不是降序：{statement_years}")
        compare = _require_rows(
            cli.statements.compare(primary, "income", years=2),
            "statements.compare", min_len=1,
        )
        for i, row in enumerate(compare):
            diff, pct, combined = row.get("diff"), row.get("diffp"), row.get("c")
            if not (isinstance(diff, dict) and isinstance(pct, dict) and isinstance(combined, dict)):
                continue
            for key, diff_value in diff.items():
                if key not in pct or key not in combined:
                    continue
                p, d, c = pct[key], diff_value, combined[key]
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                           for x in (p, d, c)):
                    continue
                if c == 0:
                    continue
                expected = d / c
                if abs(p - expected) > max(1e-9, abs(expected) * 1e-6):
                    raise ValueError(
                        f"statements.compare[{i}][{key}] diffp={p} 与 diff/c={expected} 不一致"
                    )
        audit = cli.statements.audit(primary)
        if not isinstance(audit, dict) or not audit:
            raise ValueError("statements.audit 返回空")

        all_notices = _require_rows(
            cli.notice.list(primary, window="3m", limit=10), "notice.list", min_len=1,
        )
        notices = [
            row for row in all_notices
            if _parse_date(row.get("date")) <= AS_OF.isoformat()
        ]
        if not notices:
            raise ValueError(f"notice.list 没有 {AS_OF} 当日或之前的公告")
        notice = dict(notices[0])
        notice["seq"] = int(f"{AS_OF.strftime('%y%m%d')}01")
        notice["eid"] = "demo-" + hashlib.sha256(
            f"{notice.get('date')}|{notice.get('title')}".encode("utf-8")
        ).hexdigest()[:16]
        notice["market"] = "cn"
        notice["code"] = primary
        notice["url"] = _public_url(notice.get("url"), "notice.url")
        notice["pdf_url"] = _public_url(notice.get("pdf_url"), "notice.pdf_url")
        if not notice["url"] and not notice["pdf_url"]:
            raise ValueError("最新公告没有可用 URL")

        profile = cli.info.profile(primary)
        if not isinstance(profile, dict) or not profile.get("name"):
            raise ValueError("info.profile 返回空或缺少 name")

        indicators: dict[str, Any] = {}
        for code in INDICATORS:
            value = cli.indicator.get(primary, code)
            if value is None:
                raise ValueError(f"指标 {code} 返回空")
            value = _require_num(value, f"indicator.get({primary}, {code})")
            if code != "$PE_TTM_LAST" and not 0 <= value <= 1:
                raise ValueError(f"指标 {code} 不是小数口径：{value}")
            indicators[code] = value

        valuation = cli.valuation.hist_stats(primary, metric="pe", window="3y")
        if not isinstance(valuation, dict):
            raise ValueError("valuation.hist_stats 返回非 MAP")
        for key in ("current", "median", "min", "max", "pct"):
            _require_num(valuation.get(key), f"valuation.{key}")
        if not 0 <= float(valuation["pct"]) <= 1:
            raise ValueError(f"valuation.pct 不是小数口径：{valuation['pct']}")

        # ---- market-wide screener snapshot ----
        breadth_summary = cli.screener.index_breadth_summary()
        if not isinstance(breadth_summary, dict):
            raise ValueError("screener.index_breadth_summary 返回非 MAP")
        for key in ("up_pct", "down_pct", "flat_pct"):
            if key in breadth_summary:
                value = _require_num(breadth_summary[key], f"breadth_summary.{key}")
                if value < 0:
                    raise ValueError(f"breadth_summary.{key} 不能为负：{value}")
        _require_num(breadth_summary.get("median_pct"), "breadth_summary.median_pct")
        breadth_bins = _require_rows(
            cli.screener.index_breadth_bins(), "screener.index_breadth_bins", min_len=1,
        )
        for i, row in enumerate(breadth_bins):
            value = _require_num(row.get("pct_of_total"), f"breadth_bins[{i}].pct_of_total")
            if value < 0:
                raise ValueError(f"breadth_bins[{i}].pct_of_total 不能为负：{value}")
        movers_up = _require_rows(
            cli.screener.index_top_movers(limit=10), "screener.index_top_movers(up)",
        )
        movers_down = _require_rows(
            cli.screener.index_top_movers(limit=10, desc=False),
            "screener.index_top_movers(down)",
        )
        for i, row in enumerate(movers_up + movers_down):
            percent = _require_num(row.get("percent"), f"movers[{i}].percent")
            if abs(percent) > 1:
                raise ValueError(f"movers[{i}].percent 不是小数口径：{percent}")

        screens: dict[str, dict[str, bool]] = {}
        for sym in WATCHLIST:
            screens[sym] = {
                "limit_up": bool(cli.screener.screen_limit_up(sym)),
                "above_ma20": bool(cli.screener.screen_above_ma20(sym)),
                "volume_spike": bool(cli.screener.screen_volume_spike(sym)),
                "up_today": bool(cli.screener.screen_up_today(sym)),
            }

        data: dict[str, Any] = {
            "universe": list(UNIVERSE),
            "stocks_list": stocks_list,
            "industries": industries,
            "industry_members_bank": bank_members,
            "kline_bars": kline_bars,
            "kline_snapshot": snapshots,
            "moneyflow_last": moneyflow_last,
            "moneyflow_bars": moneyflow_bars,
            "dividend": {
                "yield_ttm": dividend_yield,
                "last": dividend_last,
                "history": dividend_history,
                "screen_quality_by_args": quality_by_args,
                "index_where_high_yield_5": dividend_expression,
            },
            "notices": notices,
            "notice_event": notice,
            "profile": profile,
            "statements": {
                "income": income,
                "balance": balance,
                "cashflow": cashflow,
                "years": statement_years,
                "compare": compare,
                "audit": audit,
            },
            "indicators": indicators,
            "valuation": valuation,
            "screener": {
                "breadth_summary": breadth_summary,
                "breadth_bins": breadth_bins,
                "top_movers_up": movers_up,
                "top_movers_down": movers_down,
                "screens": screens,
            },
        }
        return data, session.request_count
    finally:
        cli.close()


def canonical_hash(data: Mapping[str, Any]) -> str:
    payload = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_document(data: Mapping[str, Any], capture_requests: int) -> dict[str, Any]:
    generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "as_of": AS_OF.isoformat(),
        "market": "cn",
        "sdk_version": __version__,
        "catalog_rev": load().stats()["upstream_rev"],
        "generated_at": generated_at,
        "capture_requests": capture_requests,
        "content_hash": canonical_hash(data),
        "data": dict(data),
    }


def render(document: Mapping[str, Any]) -> bytes:
    body = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return (body + "\n").encode("utf-8")


def build_document(data: Mapping[str, Any], capture_requests: int) -> dict[str, Any]:
    generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "as_of": AS_OF.isoformat(),
        "market": "cn",
        "sdk_version": __version__,
        "catalog_rev": load().stats()["upstream_rev"],
        "generated_at": generated_at,
        "capture_requests": capture_requests,
        "content_hash": canonical_hash(data),
        "data": dict(data),
    }


def render(document: Mapping[str, Any]) -> bytes:
    body = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return (body + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="固定快照日，必须是 2026-10-30")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    args = parser.parse_args()
    if args.as_of != AS_OF.isoformat():
        raise SystemExit(f"--as-of 当前只支持 {AS_OF.isoformat()}")

    data, request_count = capture()
    document = build_document(data, request_count)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    body = render(document)
    if len(body) > MAX_BYTES:
        raise SystemExit(f"生成文件超过 {MAX_BYTES} 字节：{len(body)}")
    output.write_bytes(body)
    print(
        f"wrote {output} ({len(body)} bytes, {request_count} requests, "
        f"content_hash={document['content_hash']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
