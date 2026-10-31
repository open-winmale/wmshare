"""API 设计新增能力：标的归一、批量调用、错误分类、目录检索、会话生命周期。"""
from __future__ import annotations

import pytest

import wmshare
from wmshare.catalog import load
from wmshare.client import BatchResult, Client, normalize_symbol
from wmshare.errors import (
    ApiError, AuthError, CatalogError, WmshareError, LimitError, TransportError,
    UsageError,
)


class FakeSession:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else [{"ok": True}]
        self.closed = False

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        outer = self

        class R:
            status_code = 200
            text = "{}"
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                return {"success": True, "data": {"result": outer.result}}
        return R()

    def close(self):
        self.closed = True


@pytest.fixture()
def cli():
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=load(), session=FakeSession())


def last_ev(cli) -> dict:
    return [x for x in cli.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]


# ---------------------------------------------------------------- 标的归一
@pytest.mark.parametrize("raw,expected", [
    ("600519", "600519"),
    ("sh.600519", "600519"),
    ("cn.600519", "600519"),
    ("sz.000001", "000001"),
    ("bj.430047", "430047"),
    ("600519.SH", "600519"),
    ("000001.SZ", "000001"),
    ("830799.BJ", "830799"),
    ("sh.600519.SH", "600519"),
    (" 600519 ", "600519"),
    ("aapl", "AAPL"),
])
def test_normalize_symbol(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    # 美股裸代码（上游注册表形态）：原样
    ("AAPL", "AAPL"),
    ("aapl", "AAPL"),
    ("BRK_B", "BRK_B"),
    # 交易所后缀 → 裸代码（否则上游按宏观序列处理，symbol 未绑定）
    ("AAPL.O", "AAPL"),
    ("aapl.n", "AAPL"),
    ("AAPL.N", "AAPL"),
    # 类别股分隔符 → 注册表下划线写法
    ("BRK.B", "BRK_B"),
    ("BRK-B", "BRK_B"),
    ("BRK.A", "BRK_A"),
    # 代码表未命中：不改写（不猜）
    ("ZZZZ.O", "ZZZZ.O"),
    # 裸代码 "O"（Realty Income）不受后缀规则影响
    ("O", "O"),
])
def test_normalize_symbol_us(raw, expected):
    assert normalize_symbol(raw, market="us", catalog=load()) == expected


def test_normalize_symbol_non_us_keeps_suffix():
    """非 us 市场不套用美股规则（港股/ A 股后缀由各自链路处理）。"""
    assert normalize_symbol("AAPL.O", market="hk", catalog=load()) == "AAPL.O"


def test_call_normalizes_symbol_everywhere(cli):
    cli.call("kline.query_bars", sym="sh.600519.SH", limit=1)
    ev = last_ev(cli)
    assert ev["symbol"] == "600519"
    assert 'kline.query_bars("600519", 1)' in ev["xs_lines"][0]


def test_friendly_layer_normalizes_symbol(cli):
    cli.kline.bars("cn.600519", n=1)
    ev = last_ev(cli)
    assert ev["symbol"] == "600519"
    assert 'kline.query_bars("600519", 1)' in ev["xs_lines"][0]


# ---------------------------------------------------------------- 批量调用
def test_call_batch_single_http_map(cli):
    cli.session.result = {"600519": [{"close": 1}], "000001": [{"close": 2}]}
    out = cli.call_batch("kline.query_bars", ["sh.600519", "000001", "600519"], limit=5)
    assert isinstance(out, BatchResult) and not out.errors
    assert set(out.results) == {"600519", "000001"}
    evals = [x for x in cli.session.calls if x["url"].endswith("/xs/eval")]
    assert len(evals) == 1, "批量应合并为单次 HTTP"
    xs = evals[0]["json"]["xs_lines"][-1]
    assert '"600519": kline.fmt_maps(kline.query_bars("600519", 5))' in xs
    assert '"000001": kline.fmt_maps(kline.query_bars("000001", 5))' in xs
    assert xs.count("kline.query_bars") == 2  # 去重


def test_call_batch_applies_normalizer(cli):
    cli.session.result = {"600519": [{"close": 1}]}
    cli.call_batch("kline.query_bars", ["600519"])
    xs = last_ev(cli)["xs_lines"][-1]
    assert "kline.fmt_maps(kline.query_bars" in xs


def test_call_batch_skip_mode_isolates_errors(cli):
    calls = {"n": 0}

    class Flaky(FakeSession):
        def post(self, url, json=None, data=None, headers=None, timeout=None):
            if url.endswith("/xs/eval"):
                calls["n"] += 1
                if any('"000001"' in ln for ln in json["xs_lines"]):
                    class R:
                        status_code = 500
                        text = "boom"
                        headers = {}
                        def json(self):
                            return {}
                    return R()
            return super().post(url, json=json, data=data, headers=headers, timeout=timeout)

    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=Flaky(), retries=0)
    out = c.call_batch("kline.query_bars", ["600519", "000001"], on_error="skip", limit=1)
    assert "600519" in out.results and "000001" in out.errors
    assert calls["n"] == 2


def test_call_batch_guards(cli):
    with pytest.raises(UsageError, match="没有标的参数"):
        cli.call_batch("notice.query_recent", ["600519"])
    with pytest.raises(UsageError, match="不要在 kwargs 传"):
        cli.call_batch("kline.query_bars", ["600519"], sym="600519")
    with pytest.raises(UsageError, match="on_error"):
        cli.call_batch("kline.query_bars", ["600519"], on_error="bogus")
    with pytest.raises(LimitError, match="超过上限"):
        c = Client(base_url="https://t", client_id="i", client_secret="s",
                   catalog=load(), session=FakeSession(), max_limit=1)
        c.call_batch("kline.query_bars", ["600519", "000001"])
    assert cli.call_batch("kline.query_bars", []) == BatchResult()


# ---------------------------------------------------------------- 错误体系
def test_catalog_error_message_has_no_keyerror_quotes():
    err = CatalogError("未知函数 'x'", code="function")
    assert str(err) == "未知函数 'x'"


def test_statement_compare_supports_native_units(cli):
    cli.statements.compare("600519", "income", years=2, _units="native")
    body = last_ev(cli)
    assert body["args"]["print.plain"] is True
    assert "_units" not in body["xs_lines"][-1]


def test_error_hierarchy_and_exports():
    for cls in (AuthError, UsageError, LimitError, TransportError, ApiError, CatalogError):
        assert issubclass(cls, WmshareError)
        assert getattr(wmshare, cls.__name__) is cls
    assert issubclass(CatalogError, KeyError)   # 兼容既有 except KeyError
    assert issubclass(LimitError, WmshareError)


def test_error_codes(cli):
    with pytest.raises(LimitError) as ei:
        cli.call("kline.query_bars", sym="600519", limit=10_000)
    assert ei.value.code == "limit"
    with pytest.raises(UsageError) as ei:
        cli.call("kline.query_bars", sym="600519", bogus=1)
    assert ei.value.code == "params"
    with pytest.raises(CatalogError) as ei:
        cli.call("no.such_fn")
    assert ei.value.code == "function"
    with pytest.raises(CatalogError):
        cli.indicator.get("600519", "$NOT_REAL")


def test_auth_error_for_partial_credentials():
    with pytest.raises(AuthError) as ei:
        Client(client_id="only")
    assert ei.value.code == "config"


def test_catalog_error_on_unknown_domain():
    cat = load()
    with pytest.raises(CatalogError):
        cat.domain("no.such.domain")


# ---------------------------------------------------------------- 目录检索
def test_catalog_search_and_groups():
    cat = load()
    fns = cat.search("query_bars", kind="function")
    assert any(x["name"] == "kline.query_bars" for x in fns)
    metrics = cat.search("市盈率", kind="metric", limit=5)
    assert metrics and all("code" in m for m in metrics)
    assert cat.search("   ") == []
    val = cat.metrics_in_group("valuation")
    assert val and cat.metric(val[0]["code"]) == val[0]
    groups = cat.metric_groups()
    assert {g["id"] for g in groups} >= {"valuation", "dividend", "revenue_mix"}
    assert all(g["count"] > 0 for g in groups)
    with pytest.raises(CatalogError):
        cat.metrics_in_group("no_such_group")


def test_metric_lookup_is_indexed():
    cat = load()
    assert cat._metric_by_code["$PE_TTM_LAST"]["cn"] == "PE(TTM)"
    assert cat.metric("$PE_TTM_LAST") is cat._metric_by_code["$PE_TTM_LAST"]


# ---------------------------------------------------------------- 生命周期与 DataFrame
def test_context_manager_owns_only_internal_session():
    injected = FakeSession()
    with Client(base_url="https://t", client_id="i", client_secret="s",
                catalog=load(), session=injected) as c:
        assert c is not None
    assert injected.closed is False  # 注入 session 由调用方管理

    owned = FakeSession()
    c = Client(base_url="https://t", client_id="i", client_secret="s", catalog=load())
    c.session = owned
    with c:
        pass
    assert owned.closed is True


def test_df_on_list_interfaces(cli):
    pd = pytest.importorskip("pandas")
    cli.session.result = [{"date": "2026-10-21", "close": 1.0}]
    df = cli.notice.list("600519", _df=True)
    assert isinstance(df, pd.DataFrame) and list(df.columns) == ["date", "close"]
    df2 = cli.statements.income("600519", _df=True)
    assert isinstance(df2, pd.DataFrame)


# ---------------------------------------------------------------- 日期区间
def test_kline_range_filters_within_bounds(cli):
    cli.session.result = [
        {"date": "2026-09-30", "close": 1.0},
        {"date": "2026-09-01", "close": 2.0},
        {"date": "2026-08-31", "close": 3.0},
    ]
    out = cli.kline.bars("600519", begin="2026-09-01", end="2026-09-30")
    assert [r["date"] for r in out] == ["2026-09-30", "2026-09-01"]
    # 区间查询默认按 max_limit 取数（默认 500）
    assert 'kline.query_bars("600519", 500)' in last_ev(cli)["xs_lines"][0]


def test_moneyflow_range_filters(cli):
    cli.session.result = [{"date": "2026-09-30", "net_mf": 1},
                          {"date": "2026-08-01", "net_mf": 2}]
    out = cli.moneyflow.bars("600519", begin="2026-09-01", end="2026-09-30")
    assert [r["date"] for r in out] == ["2026-09-30"]
    assert 'moneyflow.query_bars("600519", 500)' in last_ev(cli)["xs_lines"][0]


def test_range_guards(cli):
    with pytest.raises(UsageError, match="同时提供"):
        cli.kline.bars("600519", begin="2026-01-01")
    with pytest.raises(UsageError, match="不能晚于"):
        cli.kline.bars("600519", begin="2026-09-30", end="2026-09-01")
    with pytest.raises(UsageError, match="YYYY-MM-DD"):
        cli.kline.bars("600519", begin="bad", end="2026-01-01")
    with pytest.raises(LimitError, match="超过上限"):
        cli.kline.bars("600519", begin="2010-01-01", end="2026-01-01")


def test_range_coverage_error_when_truncated(cli):
    cli.session.result = [{"date": "2026-09-30"}, {"date": "2026-09-29"}]
    with pytest.raises(LimitError, match="区间未被覆盖"):
        cli.kline.bars("600519", n=2, begin="2026-01-01", end="2026-09-30")


def test_dividend_history_normalized_and_ranged(cli):
    cli.session.result = [
        {"ex_div": "2026-06-26", "dps": 28.0, "total": 1, "announce": "2026-06-22"},
        {"ex_div": "2023-06-26", "dps": 20.0, "total": 1, "announce": "2023-06-22"},
    ]
    out = cli.dividend.history("600519", begin="2025-01-01", end="2026-12-31")
    assert len(out) == 1 and out[0]["ex_div"] == "2026-06-26"
    with pytest.raises(UsageError, match="_raw=True"):
        cli.dividend.history("600519", begin="2025-01-01", end="2026-01-01", _raw=True)


# ---------------------------------------------------------------- 窗口统计
def test_window_stats_counts_rows_by_ex_div(cli):
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=10)).isoformat()
    old = (date.today() - timedelta(days=2000)).isoformat()
    cli.session.result = {
        "rows": [{"ex_div": recent}, {"ex_div": old}, {"ex_div": recent}],
        "dps": 10.0, "total": 100.0,
    }
    st = cli.dividend.window_stats("600519", "3y")
    assert st == {"dps": 10.0, "total": 100.0, "count": 2}


def test_window_token_validation(cli):
    with pytest.raises(UsageError, match="未知窗口"):
        cli.dividend.window_stats("600519", "10y")   # 上游会静默退化为 30 天
    with pytest.raises(UsageError, match="未知窗口"):
        cli.dividend.window_stats("600519", "2y")
    with pytest.raises(LimitError, match="超出支持范围"):
        cli.dividend.window_stats("600519", 2000)
    cli.session.result = {"rows": [], "dps": 0.0, "total": 0.0}
    assert cli.dividend.window_stats("600519", 30)["count"] == 0
