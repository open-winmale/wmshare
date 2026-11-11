"""cli.backtest.run：取数、切片、参数校验与注册（mock 传输，不联网）。"""
from __future__ import annotations

import datetime as dt
import re

import pytest

from wmshare import DataError, UsageError
from wmshare.api import COMPOSITE_METHODS, FRIENDLY_INDEX, FRIENDLY_NAMESPACES
from wmshare.catalog import load
from wmshare.client import Client

CLOSES = [10.0] * 6 + [12.0, 12.0] + [8.0] * 4


def _rows(closes=None):
    closes = CLOSES if closes is None else closes
    day = dt.date(2024, 1, 1)
    return [{"date": (day + dt.timedelta(days=i)).isoformat(), "open": c, "high": c + 1,
             "low": c - 1, "close": c, "volume": 100_000.0}
            for i, c in enumerate(closes)]


class FakeSession:
    """按顺序返回预置结果：第一次取 K 线，第二次取估值统计。"""

    def __init__(self, results):
        self.calls = []
        self.results = list(results)

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})

        class R:
            status_code = 200
            text = "{}"
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                results = self._results
                result = results.pop(0) if len(results) > 1 else results[0]
                return {"success": True, "data": {"result": result}}

        R._results = self.results
        return R()


def _client(*results, **kw):
    session = FakeSession(results or (_rows(),))
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  catalog=load(), session=session, **kw)


def _eval_calls(cli):
    return [c["json"] for c in cli.session.calls if c["url"].endswith("/xs/eval")]


def _last_json(cli):
    return _eval_calls(cli)[-1]


def _ts(day: str) -> int:
    """日期 → 交易所本地零点（+08:00）的 unix 秒，与 hist_stats 的 series 同口径。"""
    return int(dt.datetime.fromisoformat(day).replace(
        tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp())


def test_run_fetches_full_history_and_returns_trades():
    cli = _client(max_limit=None)
    res = cli.backtest.run("600519", fast=2, slow=3)
    lines = _last_json(cli)["xs_lines"]
    assert any("kline.query_bars_adj" in ln for ln in lines)
    assert any("10000" in ln and "qfq" in ln for ln in lines)
    assert _last_json(cli)["symbol"] == "600519"
    assert res["symbol"] == "600519"
    assert res["trades"] and res["trades"][0]["side"] == "buy"
    assert res["summary"]["n_trades"] >= 1
    assert set(res) == {"symbol", "rule", "period", "trades", "summary", "equity",
                        "caliber", "warnings"}


def test_begin_end_sliced_locally():
    rows = _rows()
    cli = _client(rows, max_limit=None)
    res = cli.backtest.run("600519", fast=2, slow=3,
                           begin=rows[2]["date"], end=rows[9]["date"])
    assert res["period"]["start"] == rows[2]["date"]
    assert res["period"]["end"] == rows[9]["date"]
    assert res["period"]["bars"] == 8
    # 仍然只发一次取数请求（区间在本地切，不用 begin/end 参数）
    assert len([c for c in cli.session.calls if c["url"].endswith("/xs/eval")]) == 1


def test_window_reduces_fetch_size():
    """给区间只取区间需要的根数（EC 按请求行数计费，别为两年窗口拉一万根）。"""
    rows = _rows()
    cli = _client(rows, max_limit=None)
    cli.backtest.run("600519", fast=2, slow=3, begin=rows[0]["date"], end=rows[-1]["date"])
    line = next(ln for ln in _last_json(cli)["xs_lines"] if "kline.query_bars_adj" in ln)
    match = re.search(r"kline\.query_bars_adj\([^,]+, (\d+)", line)
    assert match and int(match.group(1)) < 100


def test_max_limit_translated_to_fix():
    cli = _client()                                   # 默认 max_limit=500
    with pytest.raises(UsageError, match="max_limit=None"):
        cli.backtest.run("600519")


def test_empty_rows_raise_data_error():
    cli = _client([], max_limit=None)
    with pytest.raises(DataError, match="没有日 K"):
        cli.backtest.run("600519")


def test_short_window_error():
    rows = _rows()
    cli = _client(rows, max_limit=None)
    with pytest.raises(UsageError, match="至少需要"):
        cli.backtest.run("600519", fast=2, slow=3,
                         begin=rows[0]["date"], end=rows[3]["date"])


def test_invalid_params():
    cli = _client(max_limit=None)
    with pytest.raises(UsageError, match="周期不合法"):
        cli.backtest.run("600519", fast=20, slow=5)
    with pytest.raises(UsageError, match="begin 与 end"):
        cli.backtest.run("600519", begin="2024-01-01")
    with pytest.raises(UsageError, match="YYYY-MM-DD"):
        cli.backtest.run("600519", begin="2024/01/01", end="2024-02-01")


def test_unadjusted_warns():
    cli = _client(max_limit=None)
    res = cli.backtest.run("600519", fast=2, slow=3, adj=None)
    assert any("未复权" in w for w in res["warnings"])


def test_registered_as_composite():
    assert COMPOSITE_METHODS["backtest"] == {"run"}
    assert "backtest" in FRIENDLY_NAMESPACES
    assert not [row for row in FRIENDLY_INDEX if row[1] == "backtest"]


def test_pe_rule_fetches_hist_stats_and_trades():
    rows = _rows()
    series = [[_ts(r["date"]), 18.0 if i < 3 else 45.0] for i, r in enumerate(rows)]
    cli = _client(rows, {"series": series}, max_limit=None)
    res = cli.backtest.run("600519", rule="pe", buy=20, sell=40)
    calls = _eval_calls(cli)
    assert len(calls) == 2
    assert any('HIST_STATS("3y", "pe")' in ln for ln in calls[1]["xs_lines"])
    assert res["rule"] == "pe(buy=20, sell=40)"
    assert res["caliber"]["valuation"] == {"metric": "pe", "window": "3y"}
    assert [t["side"] for t in res["trades"]] == ["buy", "sell"]
    assert res["trades"][0]["reason"] == "买点" and res["trades"][1]["reason"] == "卖点"


def test_pe_rule_trims_bars_before_valuation():
    rows = _rows()
    series = [[_ts(r["date"]), 18.0] for r in rows[4:]]
    cli = _client(rows, {"series": series}, max_limit=None)
    res = cli.backtest.run("600519", rule="pe", buy=20, sell=40)
    assert res["period"]["start"] == rows[4]["date"]
    assert any("更早的 4 根已剔除" in w for w in res["warnings"])


def test_pe_rule_requires_thresholds():
    cli = _client(max_limit=None)
    with pytest.raises(UsageError, match="需要 buy/sell"):
        cli.backtest.run("600519", rule="pe", buy=20)
    with pytest.raises(UsageError, match="0 < buy < sell"):
        cli.backtest.run("600519", rule="pe", buy=40, sell=20)


def test_pe_rule_without_overlap():
    series = [[_ts("2030-01-02"), 18.0]]
    cli = _client(_rows(), {"series": series}, max_limit=None)
    with pytest.raises(DataError, match="没有重叠"):
        cli.backtest.run("600519", rule="pe", buy=20, sell=40)


def test_pe_rule_empty_series():
    cli = _client(_rows(), {"series": []}, max_limit=None)
    with pytest.raises(DataError, match="没有 PE 历史序列"):
        cli.backtest.run("600519", rule="pe", buy=20, sell=40)


def test_bad_rule_and_ma_alias():
    cli = _client(max_limit=None)
    with pytest.raises(UsageError, match="rule 只支持"):
        cli.backtest.run("600519", rule="roe")
    res = cli.backtest.run("600519", rule="ma", fast=2, slow=3)
    assert res["rule"] == "ma_cross(fast=2, slow=3)"
