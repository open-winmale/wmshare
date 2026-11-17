"""2.0 标准化契约锚点：DF 默认/升序/信封/台账换算/内部函数下架/期货门面/EC 预估。

这些用例锁死 2.0 破坏性变更的目标形态——任何回退（如序列方向翻回降序、
fmt_* 回到属性直达、单位退回原生默认）都应在这里立刻红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from wmshare.catalog import load
from wmshare.client import Client, normalize_date
from wmshare.errors import CatalogError, UsageError

REPO = Path(__file__).resolve().parents[1]


class FakeSession:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {}
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
        self.closed = False


@pytest.fixture()
def cli():
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=load(), session=FakeSession())


# ---------------------------------------------------------------- DF 默认与方向
def test_bars_default_dataframe_ascending(cli):
    cli.session.result = [
        {"date": "2026-09-30", "close": 1.0},
        {"date": "2026-09-01", "close": 2.0},
    ]
    df = cli.kline.bars("600519", n=2)
    assert isinstance(df, pd.DataFrame)
    assert list(df["date"]) == ["2026-09-01", "2026-09-30"]  # 旧→新
    raw = cli.kline.bars("600519", n=2, _raw=True)
    assert isinstance(raw, list)


def test_notice_list_sorted_ascending(cli):
    cli.session.result = [
        {"date": "2026-09-30", "title": "b"},
        {"date": "2026-09-01", "title": "a"},
    ]
    df = cli.notice.list("600519")
    assert list(df["date"]) == ["2026-09-01", "2026-09-30"]


def test_normalize_date_accepts_compact_and_iso():
    assert normalize_date("20260131") == "2026-01-31"
    assert normalize_date("2026-01-31") == "2026-01-31"
    with pytest.raises(UsageError, match="不合法"):
        normalize_date("not-a-date")


# ---------------------------------------------------------------- 统一信封
def test_screener_query_envelope(cli):
    cli.session.result = {"count": 2,
                          "rows": [["600519", "贵州茅台", 21.8], ["000001", "平安银行", 6.1]]}
    out = cli.screener.query("$PE_TTM_LAST > 10", limit=10)
    assert out["ok"] is True and out["as_of"] == "" and out["meta"] == {}
    assert out["data"]["count"] == 2
    rows = out["data"]["rows"]
    assert isinstance(rows, pd.DataFrame)
    assert list(rows.columns) == ["symbol", "name", "$PE_TTM_LAST"]


def test_index_trend_envelope_miss(cli):
    cli.session.result = "not-a-dict"  # 预热缓存未命中的异常形态
    out = cli.index.trend("index.hs300", window="5y")
    assert out["ok"] is False and out["data"] == {}
    assert out["meta"]["cache"] == "miss" and out["meta"]["pct_source"] == "client"


def test_workout_board_envelope(cli):
    cli.session.result = {"as_of": "2026-11-17", "deals": [{"deal": "a"}],
                          "quotes": [{"code": "600001"}]}
    out = cli.workout.board()
    assert out["ok"] is True and out["as_of"] == "2026-11-17"
    assert isinstance(out["data"]["deals"], pd.DataFrame)
    assert isinstance(out["data"]["quotes"], pd.DataFrame)


def test_statements_quarter_keys_iso(cli):
    cli.session.result = [{"k": "营业收入", "vals": {"2026:Q1": 1, "2025:Q4": 2}}]
    df = cli.statements.income("600519", period="quarter")
    assert isinstance(df, pd.DataFrame)
    vals = df.loc[0, "vals"]
    assert set(vals) == {"2026-Q1", "2025-Q4"}


# ---------------------------------------------------------------- 台账换算
def test_indicator_volume_converted_to_shares(cli):
    # 上游手 → SDK 默认股（38330 手 = 3,833,000 股）
    cli.session.result = {"$VOLUME_LAST": 38330, "$PE_TTM_LAST": 21.84}
    out = cli.indicator.metrics("600519", ["$VOLUME_LAST", "$PE_TTM_LAST"])
    assert out["$VOLUME_LAST"] == 3833000.0
    assert out["$PE_TTM_LAST"] == 21.84
    native = cli.indicator.metrics("600519", ["$VOLUME_LAST"], native=True)
    assert native["$VOLUME_LAST"] == 38330


def test_ledger_re_codes_converted_in_macro(cli):
    cli.session.result = 1234.5  # 亿元
    assert cli.macro.asof("$RE_INVEST") == pytest.approx(1.2345e11)


# ---------------------------------------------------------------- screener 单位反例修复
def test_breadth_pct_normalized_to_ratio(cli):
    cli.session.result = {"up": 100, "down": 50, "flat": 10,
                          "up_pct": 52.3, "down_pct": 26.1, "flat_pct": 5.2,
                          "median_pct": 0.01}
    out = cli.screener.index_breadth_summary()
    assert out["up_pct"] == pytest.approx(0.523)
    assert out["down_pct"] == pytest.approx(0.261)
    assert out["flat_pct"] == pytest.approx(0.052)
    assert out["median_pct"] == pytest.approx(0.01)  # 本就是小数


# ---------------------------------------------------------------- 命名空间净化
def test_l1_helpers_blocked_from_attribute_direct(cli):
    with pytest.raises(AttributeError, match="内部辅助"):
        cli.dividend.fmt_maps("x")
    # 底层入口仍可用（合同校验不发起网络即可触达参数校验前的路径）
    assert callable(cli.call)


def test_generated_layer_has_no_l1_methods():
    from wmshare.api._generated import BonusNS
    assert not hasattr(BonusNS, "fmt_maps")
    assert hasattr(BonusNS, "query_list")


# ---------------------------------------------------------------- 期货门面
def test_futures_code_validation(cli):
    with pytest.raises(UsageError, match="缺少交易所"):
        cli.futures.get("RB")
    with pytest.raises(UsageError, match="不合法"):
        cli.futures.get("cn.RB.XX")


def test_futures_snapshot_maps_fields(cli):
    codes = ["$FUT_OPEN", "$FUT_HIGH", "$FUT_LOW", "$FUT_CLOSE", "$FUT_SETTLE",
             "$FUT_PRE_SETTLE", "$FUT_VOLUME", "$FUT_AMOUNT", "$FUT_OI",
             "$FUT_OI_CHG", "$FUT_HAS"]
    cli.session.result = {c: 1 for c in codes}
    snap = cli.futures.snapshot("RB.SHF")
    assert set(snap) == {"open", "high", "low", "close", "settle", "pre_settle",
                         "volume", "amount", "open_interest", "oi_chg", "has_kline"}
    # 求值锚点使用 cn 默认锚，fut_symbol 传归一化合约键
    ev = [c for c in cli.session.calls if c["url"].endswith("/xs/eval")][-1]["json"]
    assert ev["symbol"] == "600519"
    assert '"cn.RB.SHF"' in json_of(ev)
    assert any("fut.symbol" in str(a) for a in [ev.get("args") or {}])


def json_of(ev: dict) -> str:
    import json as _json
    return _json.dumps(ev, ensure_ascii=False)


# ---------------------------------------------------------------- EC 预估器
def test_cost_estimate_row_model(cli):
    est = cli.cost_estimate("kline.query_bars", limit=500)
    assert est["ec_lo"] == 500 * 60 and est["ec_hi"] == 500 * 75
    est2 = cli.cost_estimate("kline.snapshot")
    assert est2["ec_lo"] >= 10_000  # 单票首触
    est3 = cli.cost_estimate("screener.query", where="$NPTS_TTM_YOY_LAST > 0")
    assert est3["ec_lo"] >= 40_000  # 重列
    est4 = cli.cost_estimate("notice.query_recent")
    assert est4["ec_lo"] is None and "成本模型" in est4["note"]


# ---------------------------------------------------------------- P3a 停牌五码锚点
def test_suspend_metric_codes_registered_and_documented():
    cat = load()
    for code in ("$IS_SUSPEND", "$SUSPEND_TYPE", "$SUSPEND_REASON",
                 "$SUSPEND_START_DATE", "$SUSPEND_MARKET"):
        assert cat.metric(code) is not None, code
    doc = (REPO / "docs" / "INDICATORS.md").read_text(encoding="utf-8")
    for code in ("$IS_SUSPEND", "$SUSPEND_TYPE", "$SUSPEND_REASON",
                 "$SUSPEND_START_DATE", "$SUSPEND_MARKET"):
        assert code in doc, f"{code} 应出现在 INDICATORS.md 场景速查"


# ---------------------------------------------------------------- profile 扩列
def test_profile_keys_extended(cli):
    cli.session.result = {"name": "贵州茅台", "full_name": "贵州茅台酒股份有限公司"}
    out = cli.info.profile("600519")
    assert set(out) == {"name", "full_name", "name_en", "industry_l1", "industry",
                        "style_industry", "org_type", "listing_date",
                        "listing_board", "business_scope"}
    assert out["full_name"] == "贵州茅台酒股份有限公司"
    assert out["name_en"] is None  # 未返回的键显式 None


# ---------------------------------------------------------------- 目录与门禁协同
def test_fund_domain_registered():
    cat = load()
    dom = cat.domain("market.fund")
    assert dom["kind"] == "computed"
    stats = cat.stats()
    assert stats["domains"] >= 19


# ---------------------------------------------------------------- P4：交易日历 + 两融市场面
def test_calendar_days_sorted(cli):
    cli.session.result = [
        {"date": "2026-03-02", "is_open": True},
        {"date": "2026-01-05", "is_open": True},
    ]
    df = cli.calendar.days("2026-01-01", "2026-03-31")
    assert isinstance(df, pd.DataFrame)
    assert list(df["date"]) == ["2026-01-05", "2026-03-02"]  # 升序
    assert list(df["is_open"]) == [True, True]


def test_calendar_is_open_bool(cli):
    cli.session.result = [{"date": "2026-01-05", "is_open": True}]
    assert cli.calendar.is_open("2026-01-05") is True


def test_calendar_next_accepts_compact_date(cli):
    cli.session.result = [{"date": "2026-11-18", "is_open": True}]
    df = cli.calendar.next("20261117", 1)  # 紧凑日期被 normalize_date 归一
    assert list(df["date"]) == ["2026-11-18"]


def test_margin_market_summary_sorted(cli):
    cli.session.result = [
        {"trade_date": "2026-11-14", "exchange": "SZSE", "fin_balance": 1.0},
        {"trade_date": "2026-11-13", "exchange": "SSE", "fin_balance": 2.0},
    ]
    df = cli.margin.market_summary(limit=10)
    assert list(df["trade_date"]) == ["2026-11-13", "2026-11-14"]  # 升序


def test_margin_universe_rows(cli):
    cli.session.result = [
        {"security_code": "600519", "security_name": "贵州茅台", "exchange": "SSE",
         "in_date": "2010-01-01", "out_date": "", "effective_date": "2026-11-01"},
    ]
    df = cli.margin.universe(limit=10)
    assert list(df["security_code"]) == ["600519"]
    assert df.iloc[0]["out_date"] == ""  # 空=当前生效


# ---------------------------------------------------------------- MCP cost 模式
def test_mcp_cost_mode_offline():
    """wmshare_call(mode="cost")：不发起取数，返回区间估算信封。"""
    from wmshare.mcp import tools as mcp_tools
    calls = {"n": 0}

    class _RT:
        market = "cn"
        demo = None

        def client(self, market=None):
            c = Client(base_url="https://t", client_id="i", client_secret="s",
                       catalog=load())
            c.session = FakeSession()
            orig = c.eval_result

            def guarded(*a, **kw):
                calls["n"] += 1
                return orig(*a, **kw)
            c.eval_result = guarded
            return c

    out = mcp_tools.call(_RT(), "kline.query_bars",
                         arguments={"limit": 500}, mode="cost")
    assert calls["n"] == 0, "cost 模式不得发起取数"
    assert out["meta"]["mode"] == "cost"
    assert out["data"]["ec_lo"] == 500 * 60 and out["data"]["ec_hi"] == 500 * 75


# ---------------------------------------------------------------- 原生批量路由 × 2.0 形态
def test_list_snapshot_routes_native_and_keeps_batch_result():
    """列表入参走批量原生（单次 eval）；门面收口不把 BatchResult 改成 DataFrame。"""
    rows = [{"row": i, "values": {"$SYMBOL": s, "$CLOSE_LAST": 10.0,
                                  "$VOLUME_LAST": 10.0, "$NAME": s, "$PERCENT_LAST": 0.01,
                                  "$AMOUNT_LAST": 1.0e8, "$MV_LAST": 2.0e11,
                                  "$MV_FREE_LAST": 1.5e11, "$MA_CLOSE_20_LAST": 9.9,
                                  "$MA_CLOSE_60_LAST": 9.8, "$MA120_LAST": 9.7,
                                  "$CHG_5D_LAST": 0.02, "$CHG_10D_LAST": 0.03,
                                  "$CHG_20D_LAST": 0.04, "$CHG_90D_LAST": 0.05,
                                  "$ROI_NERAST_1": 0.06, "$VOL_RATIO_5_LAST": 1.1,
                                  "$MA60_UP_LAST": True, "$INDUSTRY_CUR_1": "银行",
                                  "$IS_SUSPEND": False, "$IS_ST": False}}
            for i, s in enumerate(("600519", "000001", "000002"))]
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=load(), session=FakeSession(rows))
    out = cli.kline.snapshot(["600519", "000001", "000002"])
    assert type(out).__name__ == "BatchResult"
    assert out.requests == 1 and out.requested == 3
    assert out.results["600519"]["volume"] == 1000.0   # 手→股（2.0 默认换算）
    assert out.results["600519"]["kline_date"] is None  # 索引未物化
    assert len(out.results["600519"]) == 23
    # 单次 eval 证据：只发了一次取数请求（外加一次 OAuth）
    assert len([c for c in cli.session.calls if "oauth" not in c["url"]]) == 1


def test_cost_estimate_full_market_shortcut_model(cli):
    """准全市场清单的成本模型 = 空参捷径（不是 N×58 EC/票 的线性放大）。"""
    est = cli.cost_estimate("kline.snapshot", sym=[f"{i:06d}" for i in range(4000)])
    assert est["model"] == "full_market_shortcut"
    assert est["ec_lo"] == 110_000 and est["ec_hi"] == 150_000
    est2 = cli.cost_estimate("kline.snapshot", sym=["600519", "000001", "000002"])
    assert est2["model"] == "batch_per_symbol"
    assert est2["ec_lo"] == 3 * 55


def test_demo_list_snapshot_same_shape_as_live():
    """demo 与 live 同形同次数：≥3 票列表 = 一次请求的 BatchResult。"""
    import wmshare
    demo = wmshare.demo_client()
    out = demo.kline.snapshot(["600519", "000858", "601088"])
    assert type(out).__name__ == "BatchResult"
    assert out.requests == 1 and set(out.results) == {"600519", "000858", "601088"}
    assert isinstance(out.results["600519"], dict)
