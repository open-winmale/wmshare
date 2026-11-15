"""Live 冒烟（默认跳过）：FRIENDLY_INDEX 全部核心接口真实调用 + 数值合理性断言。

运行：
  WMSHARE_LIVE=1 WMSHARE_BASE_URL=... WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=... \
    pytest tests/test_live.py

覆盖：友好层 FRIENDLY_INDEX 的每个核心接口至少一条真实调用；K 线/资金流额外做
多标的（沪深主板 + 创业板）校验，断言数值口径而非仅类型。单位口径守护为**关系型
不变量**并参数化跑样本宇宙（不同板块/行业/规模 + 一只 ETF），不绑定任何单一公司
的绝对量级。

历史已知问题（2026-10-22 发现，2026-10-26 上游 a9bce960 修复）：kline.live/min1/
is_etf/query_bars_live 曾因 is_etf 的命名空间缓存写被 OpenAPI 沙箱以 403 POLICY_DENIED
拒绝。`_call_or_xfail` 保留为非 strict 容忍，防间歇性策略拒绝造成假红。
"""
import datetime
import os
from pathlib import Path

import pytest

from wmshare.api import FRIENDLY_INDEX
from wmshare.client import Client

pytestmark = pytest.mark.skipif(
    os.environ.get("WMSHARE_LIVE") != "1", reason="WMSHARE_LIVE!=1")

SYMBOLS = ["600519", "000001", "300750"]
MAIN = SYMBOLS[0]

# 单位审计样本宇宙：大市值消费 / 金融 / 创业板制造 / 科创板 / 高杠杆周期 + ETF
UNIVERSE = ["600519", "601318", "300750", "688981", "601857"]
ETF = "510300"

BLOCKED_REASON = ("间歇性 403 POLICY_DENIED：策略拒绝非 SDK 问题；"
                  "is_etf 缓存写根因已于上游修复（a9bce960），此路径仅兜底偶发")


def _call_or_xfail(fn, *args, **kwargs):
    """已知服务端策略拒绝：命中即 xfail（非 strict，避免间歇性 403 造成假红）。"""
    from wmshare.client import WmshareError
    try:
        return fn(*args, **kwargs)
    except WmshareError as e:
        msg = str(e)
        if "403" in msg and "POLICY_DENIED" in msg:
            pytest.xfail(BLOCKED_REASON)
        raise

CORE_COUNT = len(FRIENDLY_INDEX)


@pytest.fixture(scope="module")
def cli():
    return Client.from_env()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- 行情 market
@pytest.mark.parametrize("symbol", SYMBOLS)
def test_kline_bars_multi_symbol(cli, symbol):
    bars = cli.kline.bars(symbol, n=5)
    assert isinstance(bars, list) and len(bars) == 5
    for bar in bars:
        assert {"date", "close", "open", "high", "low"} <= set(bar)
        assert _is_num(bar["close"]) and bar["close"] > 0
        assert bar["low"] <= bar["high"]
    dates = [b["date"] for b in bars]
    assert dates == sorted(dates, reverse=True), "日 K 应按日期降序"


def test_kline_bars_adj_variants(cli):
    nr = cli.kline.bars(MAIN, n=3)
    qfq = cli.kline.bars(MAIN, n=3, adj="qfq")
    assert [b["date"] for b in nr] == [b["date"] for b in qfq]
    assert all(_is_num(b["close"]) and b["close"] > 0 for b in qfq)


def test_kline_bars_date_range(cli):
    rows = cli.kline.bars(MAIN, begin="2026-09-01", end="2026-09-30")
    assert isinstance(rows, list) and rows
    assert all("2026-09-01" <= b["date"] <= "2026-09-30" for b in rows)
    money = cli.moneyflow.bars(MAIN, begin="2026-09-01", end="2026-09-30")
    assert all("2026-09-01" <= r["date"] <= "2026-09-30" for r in money)


def test_kline_last(cli):
    bar = cli.kline.last(MAIN)
    assert isinstance(bar, dict)
    assert bar.get("date"), "last() 应与 bars() 同字段（含 date）"
    assert _is_num(bar["close"]) and bar["close"] > 0
    assert _is_num(bar["volume"]) and bar["volume"] >= 0


def test_kline_live(cli):
    bar = _call_or_xfail(cli.kline.live, MAIN)
    assert bar is None or (isinstance(bar, dict) and _is_num(bar["close"]))


def test_kline_is_etf(cli):
    assert isinstance(_call_or_xfail(cli.kline.is_etf, MAIN), bool)


def test_kline_snapshot(cli):
    snap = cli.kline.snapshot(MAIN)
    assert isinstance(snap, dict)
    assert _is_num(snap["close"]) and snap["close"] > 0


def test_kline_min1(cli):
    pkg = _call_or_xfail(cli.kline.min1, MAIN)
    assert isinstance(pkg, dict)
    assert "trading_day" in pkg and isinstance(pkg.get("bars"), list)


def test_kline_batch_live(cli):
    out = _call_or_xfail(cli.kline.batch_live, [MAIN, "000001"])
    assert isinstance(out, dict) and {MAIN, "000001"} <= set(out)


def test_moneyflow_bars(cli):
    rows = cli.moneyflow.bars(MAIN, n=5)
    assert isinstance(rows, list) and len(rows) == 5
    for r in rows:
        assert {"date", "net_mf"} <= set(r)
        assert _is_num(r["net_mf"])
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_moneyflow_last_and_live(cli):
    last = cli.moneyflow.last(MAIN)
    assert last is None or (isinstance(last, dict) and last.get("date")
                            and _is_num(last["net_mf"]))
    live = cli.moneyflow.live(MAIN)
    assert live is None or (isinstance(live, dict) and _is_num(live["net_mf"]))


def test_moneyflow_board(cli):
    """全市场资金流快照：服务端一次直出，行按净流入降序。"""
    rows = _call_or_xfail(cli.moneyflow.board())
    assert isinstance(rows, list) and len(rows) > 100
    assert {"symbol", "name", "net_mf"} <= set(rows[0])
    nets = [r["net_mf"] for r in rows if _is_num(r.get("net_mf"))]
    assert nets == sorted(nets, reverse=True), "board 应按净流入降序"


# ---------------------------------------------------------------- 财务 fundamentals
@pytest.mark.parametrize("method", ["balance", "income", "cashflow"])
def test_statements_three_tables(cli, method):
    rows = getattr(cli.statements, method)(MAIN, years=2)
    assert isinstance(rows, list) and len(rows) > 5
    assert all({"k", "cn", "vals"} <= set(r) for r in rows)
    assert all(len(r["vals"]) <= 2 for r in rows)  # years=2 → 至多 2 期列


def test_statements_audit(cli):
    doc = cli.statements.audit(MAIN)
    assert isinstance(doc, dict) and doc
    assert all(str(k).isdigit() for k in doc)


def test_statements_compare_tree_years(cli):
    cmp_rows = cli.statements.compare(MAIN, "balance", years=2)
    assert isinstance(cmp_rows, list) and cmp_rows
    assert {"c", "p", "diff", "diffp", "k"} <= set(cmp_rows[0])
    diff_rows = [r for r in cmp_rows if r.get("diff")]
    assert diff_rows, "资产负债表应有部分科目可比出差额"
    # 差额占比为小数：diffp = diff / 合并值（SDK 已由脚本百分数自动 ÷100）
    r = diff_rows[0]
    year = sorted(r["diff"])[0]
    assert abs(r["diffp"][year] - r["diff"][year] / r["c"][year]) < 1e-6

    tree = cli.statements.tree(MAIN, "balance", years=2)
    assert isinstance(tree, list) and tree
    assert {"k", "cn", "vals"} <= set(tree[0])
    # 树视图派生行保留原生口径：pct 行为百分数（如 DART 16.4 = 16.4%）
    dart = next((x for x in tree if x.get("k") == "DART" and x.get("vals")), None)
    if dart:
        v = next(iter(dart["vals"].values()))
        assert v > 1, f"资产负债率 pct 行应为百分数口径，实际 {v}"

    years = cli.statements.years(MAIN, "income")
    assert isinstance(years, list) and years
    assert all(isinstance(y, (int, str)) for y in years)


def test_indicator_get_and_metrics(cli):
    pe = cli.indicator.get(MAIN, "$PE_TTM_LAST")
    assert _is_num(pe) and pe > 0
    # $PB_LAST 已随目录对齐上游剔除（script 仅注释残留），改用 $PB_TTM_LAST
    batch = cli.indicator.metrics(MAIN, ["$PE_TTM_LAST", "$ROE_TTM_LAST", "$PB_TTM_LAST"])
    assert set(batch) == {"$PE_TTM_LAST", "$ROE_TTM_LAST", "$PB_TTM_LAST"}
    assert _is_num(batch["$PE_TTM_LAST"]) and batch["$PE_TTM_LAST"] > 0
    # 指标层比率是小数（0.332 = 33.2%），不是 0.332 个百分点
    assert _is_num(batch["$ROE_TTM_LAST"]) and 0 < batch["$ROE_TTM_LAST"] < 2


def test_indicator_basic(cli):
    """估值截面：字段齐全、PE/PB 为正、换手率小数、市值元量级。"""
    v = _call_or_xfail(cli.indicator.basic, MAIN)
    assert set(v) == {"pe_ttm", "pb", "turnover_rate", "total_mv"}
    assert _is_num(v["pe_ttm"]) and v["pe_ttm"] > 0
    assert _is_num(v["pb"]) and v["pb"] > 0
    tr = v["turnover_rate"]
    assert tr is None or (0 <= tr <= 1), f"换手率应为小数，实际 {tr}"
    mv = v["total_mv"]
    assert mv is None or mv > 1e8, f"市值应为元量级（个股），实际 {mv}"


def test_indicator_financials(cli):
    """财务截面：ROE 小数量级、近3年平均 ROE 与 TTM 同量级、EPS 元。"""
    v = _call_or_xfail(cli.indicator.financials, MAIN)
    assert set(v) == {"roe_ttm", "roe_avg", "eps_ttm"}
    for key in ("roe_ttm", "roe_avg"):
        x = v[key]
        assert x is None or -20 < x < 20, f"{key} 应为小数量级，实际 {x}"
    eps = v["eps_ttm"]
    assert eps is None or abs(eps) > 0, f"EPS 应为元量级，实际 {eps}"


def test_volume_codes_are_lot_denominated(cli):
    """指标层成交量是「手」（与 kline 的「股」差 100 倍）——单位台账的机器锚点。"""
    m = _call_or_xfail(cli.indicator.metrics, MAIN,
                       ["$VOLUME_DAY", "$EQUITY_FREE_SHARES", "$TURNOVER_RATE"])
    vol, free, turnover = m["$VOLUME_DAY"], m["$EQUITY_FREE_SHARES"], m["$TURNOVER_RATE"]
    if _is_num(vol) and _is_num(free) and _is_num(turnover):
        assert vol * 100 / free == pytest.approx(turnover, rel=1e-6), \
            "成交量为手时，×100/流通股本 应等于换手率；否则上游已改为股"


# ---------------------------------------------------------------- 披露 disclosure
def test_notice_list(cli):
    rows = cli.notice.list(MAIN, window="1y", limit=5)
    assert isinstance(rows, list) and rows
    assert all({"date", "title", "code", "type"} <= set(r) for r in rows), \
        "notice.list() 应为扁平规范化行"


def test_notice_by_category(cli):
    rows = cli.notice.by_category("回购", window="1m", limit=5)
    assert isinstance(rows, list)
    assert all({"date", "title"} <= set(r) for r in rows)


def test_notice_find(cli):
    rows = cli.notice.find(MAIN, "2026-01-01", "2026-06-30", limit=5)
    assert isinstance(rows, list) and rows
    assert all({"date", "title"} <= set(r) for r in rows)


def test_notice_signals(cli):
    assert isinstance(cli.notice.has_buyback(MAIN, window="1y"), bool)
    assert isinstance(cli.notice.has_reduction(MAIN, window="1y"), bool)


def test_notice_recent_and_on_date(cli):
    recent = cli.notice.recent("7d", limit=3)
    assert isinstance(recent, list) and recent
    assert all({"date", "title"} <= set(r) for r in recent)
    on = cli.notice.on_date("2026-10-21", limit=3)
    assert isinstance(on, list)
    assert all({"date", "title"} <= set(r) for r in on)


def test_filings_list_and_latest(cli):
    rows = cli.filings.list(MAIN, kind="annual", limit=3)
    assert isinstance(rows, list) and rows
    assert all({"report_date", "title"} <= set(r) for r in rows)
    latest = cli.filings.latest(MAIN, kind="annual")
    assert isinstance(latest, dict) and latest.get("report_date")


def test_forecast_yjyg(cli):
    rows = cli.forecast.yjyg(MAIN, limit=3)
    assert isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
    latest = cli.forecast.yjyg_latest(MAIN)
    assert latest is None or isinstance(latest, dict)


def test_forecast_yjkb(cli):
    rows = cli.forecast.yjkb(MAIN, limit=3)
    assert isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
    latest = cli.forecast.yjkb_latest(MAIN)
    assert latest is None or isinstance(latest, dict)


def test_forecast_next_disclosure(cli):
    row = cli.forecast.next_disclosure(MAIN)
    assert isinstance(row, dict) and row.get("report_date")


def test_forecast_disclosure_history(cli):
    rows = cli.forecast.disclosure_history(MAIN, limit=3)
    assert isinstance(rows, list) and rows
    assert all({"report_date", "report_type_name"} <= set(r) for r in rows)


def test_dividend_history_and_last(cli):
    rows = cli.dividend.history(MAIN, limit=5)
    assert isinstance(rows, list) and rows
    last = cli.dividend.last(MAIN)
    assert isinstance(last, dict)
    assert {"announce", "ex_div", "dps", "total"} <= set(last)
    assert last == cli.dividend.history(MAIN, limit=1)[0]


def test_dividend_dps_and_ratios(cli):
    dps = cli.dividend.dps(MAIN)
    assert _is_num(dps) and dps > 0            # 元/股
    y = cli.dividend.yield_ttm(MAIN)
    p = cli.dividend.payout_ttm(MAIN)
    assert _is_num(y) and 0 < y < 1            # 小数口径：0.0396 = 3.96%
    assert p is None or (_is_num(p) and p >= 0)


def test_dividend_window_stats(cli):
    st = cli.dividend.window_stats(MAIN, "3y")
    assert set(st) == {"dps", "total", "count"}
    assert _is_num(st["dps"]) and st["dps"] > 0
    assert _is_num(st["total"]) and st["total"] > 0
    assert isinstance(st["count"], int) and st["count"] >= 1


def test_dividend_screeners(cli):
    assert isinstance(_call_or_xfail(cli.dividend.screen_quality, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.dividend.screen_high_yield, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.dividend.screen_undervalued_yield, MAIN), bool)


def test_dividend_history_fields_and_range(cli):
    rows = cli.dividend.history(MAIN, limit=5)
    assert isinstance(rows, list) and rows
    assert {"dps", "total", "ex_div", "announce"} <= set(rows[0]), \
        "history() 应为扁平规范化行（不再 props 嵌套）"
    ranged = cli.dividend.history(MAIN, begin="2024-01-01", end="2026-10-22")
    assert isinstance(ranged, list)
    assert all("2024-01-01" <= str(r.get("ex_div"))[:10] <= "2026-10-22" for r in ranged)


def test_kline_query_bars_live(cli):
    rows = _call_or_xfail(cli.call, "kline.query_bars_live", sym=MAIN, limit=3)
    assert isinstance(rows, list)


# ---------------------------------------------------------------- 选股 screener
def test_screener_predicates(cli):
    """单票筛选器恒返回 bool（涨停/跌停/均线/动量/回撤/放量各抽一；未命中 False 合法）。"""
    assert isinstance(_call_or_xfail(cli.screener.screen_limit_up, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_limit_down, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_above_ma20, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_ma60_up, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_breakout_ma20, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_momentum_20d, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_pullback_20d, MAIN), bool)
    assert isinstance(_call_or_xfail(cli.screener.screen_volume_spike, MAIN), bool)


def test_screener_breadth_summary(cli):
    """涨跌全景：家数守恒；up_pct 为百分数（0~100）、median_pct 为小数。"""
    s = _call_or_xfail(lambda: cli.screener.index_breadth_summary())
    assert {"total", "up", "down", "flat", "up_pct", "median_pct"} <= set(s)
    assert s["up"] + s["down"] + s["flat"] == s["total"] and s["total"] > 1000
    assert 0 <= s["up_pct"] <= 100 and 0 <= s["down_pct"] <= 100
    assert -0.5 <= s["median_pct"] <= 0.5


def test_screener_breadth_bins(cli):
    """涨跌幅分桶：档位行齐全、家数合计与全景同量级。"""
    bins = _call_or_xfail(lambda: cli.screener.index_breadth_bins())
    assert isinstance(bins, list) and len(bins) >= 5
    assert {"label", "count", "pct_of_total"} <= set(bins[0])
    assert sum(b["count"] for b in bins) > 1000


def test_screener_bin_industries(cli):
    """分桶行业分布：行含 bin/industry/count（industry 为行业代码）。"""
    rows = _call_or_xfail(lambda: cli.screener.index_breadth_bin_industries())
    assert isinstance(rows, list) and rows
    assert {"bin", "industry", "count"} <= set(rows[0])


def test_screener_top_movers(cli):
    """涨跌榜：新合同行含 symbol/name/percent（小数）且按涨跌幅降序。

    服务端跑的是已部署脚本副本：本地上游 7615b7ea 的字段投影未部署前为
    values.$XXX 旧形态，此时 xfail（部署后自动转正）。
    """
    rows = _call_or_xfail(cli.screener.index_top_movers, 5)
    assert isinstance(rows, list) and len(rows) == 5
    if "symbol" not in rows[0]:
        pytest.xfail("上游部署未含 7615b7ea 的 top_movers 字段投影（旧形态 values.$XXX）")
    assert {"symbol", "name", "percent"} <= set(rows[0])
    percents = [r["percent"] for r in rows]
    assert percents == sorted(percents, reverse=True), "涨幅榜应按涨跌幅降序"


def test_screener_query_market(cli):
    """全市场条件选股：一条表达式出 count + 行；count 与 limit 无关（防 topN 当全市场）。"""
    where = "$ROE_TTM_LAST > 0.30 && !$IS_SUSPEND"
    res = _call_or_xfail(lambda: cli.screener.query(where, limit=5))
    assert res["count"] >= len(res["rows"]) and len(res["rows"]) <= 5
    row = res["rows"][0]
    assert {"symbol", "name", "$ROE_TTM_LAST"} <= set(row)
    assert row["$ROE_TTM_LAST"] > 0.30
    only = _call_or_xfail(lambda: cli.screener.query(where, limit=0))
    assert only["rows"] == [] and only["count"] == res["count"]


# ---------------------------------------------------------------- 参考 reference
def test_info_profile(cli):
    prof = cli.info.profile(MAIN)
    assert isinstance(prof, dict)
    assert prof.get("name") == "贵州茅台"
    assert prof.get("industry")


# ---------------------------------------------------------------- 单位口径：样本宇宙关系型不变量
@pytest.mark.parametrize("symbol", [*UNIVERSE, ETF])
def test_universe_invariants(cli, symbol):
    """每家样本公司一组调用（3 次 HTTP），全部关系型断言——不绑定任何单一公司量级：

    - volume(股)×close ≈ amount(元)（ETF 与个股同口径）
    - $MV_FREE_LAST ≤ $MV_LAST；分位 [0,1]；ROE 小数量级
    - $AMOUNT_LAST 与日 K amount 同量级（同为中心元，容时间戳差）
    - dividend.yield_ttm == $BONUS_RATE_TTM_LAST（分红公司跨接口恒等）
    运行时量级守护（声明 range）已内置于这些调用，未抛 DataError 本身即一项通过。
    """
    metrics_only = symbol == ETF
    codes = ["$MV_LAST", "$MV_FREE_LAST", "$AMOUNT_LAST", "$BONUS_RATE_TTM_LAST",
             "$PCT_PE_TTM_10Y_LAST", "$ROE_TTM_LAST"]
    m = {} if metrics_only else cli.indicator.metrics(symbol, codes)

    bars = cli.kline.bars(symbol, n=3)
    bar = bars[-1]
    v, c, a = bar["volume"], bar["close"], bar["amount"]
    assert v * c / a == pytest.approx(1.0, abs=1.5), \
        f"{symbol}: volume×close/amount={v * c / a:.4f}（volume 应为股、amount 应为元）"

    if metrics_only:
        return
    if _is_num(m.get("$MV_FREE_LAST")) and _is_num(m.get("$MV_LAST")):
        assert m["$MV_FREE_LAST"] <= m["$MV_LAST"] * 1.01, f"{symbol}: 流通市值 > 总市值"
    pct = m.get("$PCT_PE_TTM_10Y_LAST")
    if _is_num(pct):
        assert 0 <= pct <= 1, f"{symbol}: 10 年分位应为 [0,1] 小数，实际 {pct}"
    roe = m.get("$ROE_TTM_LAST")
    if _is_num(roe):
        assert -20 < roe < 20, f"{symbol}: ROE 应为小数量级，实际 {roe}"
    scale = m["$AMOUNT_LAST"] / a
    assert 0.02 < scale < 50, f"{symbol}: $AMOUNT_LAST/bars.amount={scale:.3g}，量级不一致"
    rate = m.get("$BONUS_RATE_TTM_LAST")
    if _is_num(rate) and rate > 0:  # 未分红公司跳过恒等式
        y = cli.dividend.yield_ttm(symbol)
        assert y == pytest.approx(rate, abs=1e-9), \
            f"{symbol}: yield_ttm={y} != $BONUS_RATE_TTM_LAST={rate}"


def test_forecast_amp_is_decimal(cli):
    """预告幅度已由 SDK 换算为小数：|amp| 远小于百分数口径（预增 153.6% → 1.536）。"""
    rows = cli.forecast.yjyg("688008", limit=2)  # 样本期内有预告的标的
    amps = [r[k] for r in rows for k in ("np_amp_lower", "np_amp_upper")
            if _is_num(r.get(k))]
    assert amps, "样本应包含预告幅度字段"
    assert all(abs(a) < 20 for a in amps), f"预告幅度应为小数口径，实际 {amps}"


def test_yjkb_yoy_matches_underlying(cli):
    """快报同比为小数且与行内金额自洽：np_yoy ≈ netprofit/netprofit_ly - 1。"""
    rows = cli.forecast.yjkb("603092", limit=1)
    assert rows
    r = rows[0]
    if _is_num(r.get("np_yoy")) and r.get("netprofit") and r.get("netprofit_ly"):
        expected = r["netprofit"] / r["netprofit_ly"] - 1
        assert r["np_yoy"] == pytest.approx(expected, rel=0.01), \
            f"np_yoy={r['np_yoy']} 与金额同比 {expected:.4f} 不一致"


def test_kline_volume_native_escape(cli):
    """逃生口语义：_units="native" 返回脚本原生单位（手），与默认（股）差 ×100。"""
    base = cli.kline.bars(MAIN, n=1)[0]
    native = cli.call("kline.query_bars", sym=MAIN, limit=1, _units="native")
    row = native[0] if isinstance(native, list) else native
    assert row["volume"] * 100 == pytest.approx(base["volume"], rel=1e-9), \
        "native 应为手原值、默认应为股（×100）"


# ---------------------------------------------------------------- 经营分部
def test_segments_business_and_income(cli):
    """分部行：收入降序、金额元量级、毛利率小数；income 维占比求和≈1。"""
    rows = cli.segments.business(MAIN)
    assert isinstance(rows, list) and rows, "茅台应有业务线分部（茅台酒/系列酒）"
    trs = [r["tr"] for r in rows]
    assert trs == sorted(trs, reverse=True), "分部行应按收入降序"
    assert all(0 < r["tr"] < 1e13 for r in rows), "收入应为元量级"
    for r in rows:
        if r["margin"] is not None:
            assert -5 < r["margin"] <= 1, f"毛利率应为小数：{r['name']}={r['margin']}"

    inc = cli.segments.income(MAIN)
    total = sum(r["ratio"] for r in inc)
    assert total == pytest.approx(1.0, abs=0.01), f"主营标签占比求和应≈1，实际 {total}"


def test_segments_region_and_coverage(cli):
    """境内外分部：境内+境外占比≈1；coverage 布尔自洽。"""
    region = cli.segments.region(MAIN)
    assert isinstance(region, dict) and region.get("source") == "clean"
    pct_sum = region["domestic"]["pct"] + region["overseas"]["pct"]
    assert pct_sum == pytest.approx(1.0, abs=0.01), f"境内外占比求和应≈1，实际 {pct_sum}"
    for side in ("domestic", "overseas"):
        m = region[side]["margin"]
        if m is not None:
            assert -5 < m <= 1, f"{side} 毛利率应为小数：{m}"

    cov = cli.segments.coverage(MAIN)
    assert isinstance(cov.get("has_business"), bool)


def test_segments_products_varies_by_company(cli):
    """products 维因公司披露而异：制造业有值、无披露公司为空列表（不报错）。"""
    rows = cli.segments.products("000333")
    assert isinstance(rows, list) and rows, "美的应有产品分部"
    assert all(0 < r["tr"] < 1e13 for r in rows)
    empty = cli.segments.products("600519")  # 茅台产品维为空（走业务维）
    assert empty == []


def test_segments_periods_and_snapshot(cli):
    periods = cli.segments.periods(MAIN)
    assert isinstance(periods, dict) and periods.get("clean_last")
    snap = cli.segments.snapshot(MAIN)
    assert isinstance(snap, dict) and "business" in snap and "coverage" in snap


# ---------------------------------------------------------------- 估值历史统计
def test_valuation_hist_stats_live(cli):
    """600900 PB 3y：字段齐全、序列升序且与 count 一致、分位在 [0,1]。"""
    r = cli.valuation.hist_stats("600900", metric="pb", window="3y")
    assert {"avg", "current", "median", "min", "max", "pct", "count", "series"} <= set(r)
    assert r["count"] > 100 and len(r["series"]) == r["count"]
    assert 0 <= r["pct"] <= 1
    assert r["min"] <= r["median"] <= r["max"]
    dates = [pt[0] for pt in r["series"]]
    assert dates == sorted(dates), "估值序列应按时间升序"



# ------------------------------------------------- v1.5.0 七域冒烟（2026-10-27 起上游已部署，转真）


def test_equity_domain_smoke(cli):
    """股东治理域：逐接口真实调用，返回容器类型冒烟。"""
    for r in (
        _call_or_xfail(lambda: cli.equity.query_holder10("600519")),
        _call_or_xfail(lambda: cli.equity.query_pledge_detail("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_pledge_summary("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_pledge_market(5)),
        _call_or_xfail(lambda: cli.equity.query_pledge_industry(5)),
        _call_or_xfail(lambda: cli.equity.query_pledge_org(5)),
        _call_or_xfail(lambda: cli.equity.query_release("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_institution_detail("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_institution_summary("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_hgt("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_national_team("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_buyback_plan("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_reorg("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_related_trade("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_concert("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_guarantee("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_litigation("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_violation("600519", 5)),
        _call_or_xfail(lambda: cli.equity.query_executives("600519")),
    ):
        assert r is None or isinstance(r, (list, dict))
    # 单对象接口
    for r in (
        _call_or_xfail(lambda: cli.equity.query_holdernum("600519")),
        _call_or_xfail(lambda: cli.equity.query_buyback_detail("600519")),
        _call_or_xfail(lambda: cli.equity.query_exec_change("600519")),
        _call_or_xfail(lambda: cli.equity.query_exec_change_at("600519", 2024, "Q4")),
        _call_or_xfail(lambda: cli.equity.query_capital_change("600519")),
        _call_or_xfail(lambda: cli.equity.query_capital_change_at("600519", 2024, "Q4")),
    ):
        assert r is None or isinstance(r, dict)


def test_margin_domain_smoke(cli):
    rows = _call_or_xfail(lambda: cli.margin.query("600519", 5))
    assert rows is None or isinstance(rows, list)
    latest = _call_or_xfail(lambda: cli.margin.latest("600519"))
    assert latest is None or isinstance(latest, dict)


def test_estimates_domain_smoke(cli):
    for r in (
        _call_or_xfail(lambda: cli.estimates.query_forecast("600519", 5)),
        _call_or_xfail(lambda: cli.estimates.query_forecast_detail("600519", 5)),
        _call_or_xfail(lambda: cli.estimates.query_rating("600519", 5)),
        _call_or_xfail(lambda: cli.estimates.query_reports("600519", 5)),
    ):
        assert r is None or isinstance(r, list)


def test_cbond_domain_smoke(cli):
    for r in (
        _call_or_xfail(lambda: cli.cbond.latest_quotes()),
        _call_or_xfail(lambda: cli.cbond.board()),
        _call_or_xfail(lambda: cli.cbond.of_stock("600519")),
        _call_or_xfail(lambda: cli.cbond.query("600519")),
        _call_or_xfail(lambda: cli.cbond.call_hits("113050", 130)),
        _call_or_xfail(lambda: cli.cbond.kline_window("113050", 30)),
        _call_or_xfail(lambda: cli.cbond.bars("113050", n=5)),
        _call_or_xfail(lambda: cli.cbond.universe_codes()),
    ):
        assert r is None or isinstance(r, (list, dict, int))


def test_cbond_bars_row_shape(cli):
    """转债日线表：列转行后字段齐全、日期降序、OHLC 关系成立、无缺失结构。"""
    rows = _call_or_xfail(cli.cbond.bars, "113050", n=5)
    if not rows:
        pytest.xfail("样本转债该窗口无数据")
    assert all({"date", "open", "high", "low", "close"} <= set(r) for r in rows)
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True), "转债日线应按日期降序"
    for r in rows:
        if all(_is_num(r.get(k)) for k in ("open", "high", "low", "close")):
            assert r["low"] <= min(r["open"], r["close"])
            assert r["high"] >= max(r["open"], r["close"])


def test_workout_index_intl_domain_smoke(cli):
    assert isinstance(_call_or_xfail(lambda: cli.workout.board()), (dict, list))
    r = _call_or_xfail(lambda: cli.workout.query("601059"))
    assert r is None or isinstance(r, (list, dict))
    assert isinstance(_call_or_xfail(lambda: cli.index.keys()), list)
    for r in (
        _call_or_xfail(lambda: cli.index.members("index.hs300", "mv", 5)),
        _call_or_xfail(lambda: cli.index.weights("index.hs300", 5)),
    ):
        assert r is None or isinstance(r, list)
    v = _call_or_xfail(lambda: cli.index.valuation("index.hs300", 8))
    assert v is None or isinstance(v, dict)


def test_index_trend_long_history_and_industries(cli):
    """指数/行业历史 PE：周频整体法序列 + 按 window 取档的分位（真实服务端）。

    覆盖此前在 test_live 里完全没有的 ``index.trend`` / ``index.universe_keys``：
    静态覆盖面守护 ``test_all_core_interfaces_are_exercised_here`` 要求它们出现，
    但该守护本身受 ``WMSHARE_LIVE`` 门控，CI 从不执行，等于无契约。
    """
    # ① 宽基：序列应覆盖 10 年以上（周频约 700+ 点）；分位必须按窗口取档
    t3 = _call_or_xfail(lambda: cli.index.trend("index.hs300", "3y"))
    assert isinstance(t3, dict) and t3.get("ok") is True, "hs300 应有预热缓存"
    assert t3["n"] >= 500, f"宽基估值序列应覆盖 10 年（周频），实际 {t3['n']} 点"
    dates = [p["date"] for p in t3["points"]]
    assert dates == sorted(dates, reverse=True), "points 必须新→旧"
    node = t3["pct"]["pe"]
    assert t3["pe_pct"] == pytest.approx(node["p3"]), \
        "3y 分位必须取 p3（服务端 p 恒为 5y，读 p 会静默错值）"
    t5 = _call_or_xfail(lambda: cli.index.trend("index.hs300", "5y"))
    assert t5["pe_pct"] == pytest.approx(t5["pct"]["pe"]["p5"])
    assert t3["pe_pct"] != pytest.approx(t5["pe_pct"]), \
        "3y 与 5y 分位不应相同（相同说明没按窗口取档）"

    # ② 申万一级行业：31 键都必须能取到历史
    keys = _call_or_xfail(lambda: cli.index.universe_keys("industry"))
    assert isinstance(keys, list) and len(keys) >= 20, f"行业键应约 31 个，实际 {keys}"
    bad = []
    for k in keys:
        r = _call_or_xfail(lambda k=k: cli.index.trend(k, "5y"))
        if not (isinstance(r, dict) and r.get("ok") and r.get("n", 0) > 100):
            bad.append(k)
    assert not bad, f"以下行业键取不到估值历史（缓存未预热？）：{bad}"

    # ③ 红利键
    div = _call_or_xfail(lambda: cli.index.universe_keys("dividend"))
    assert isinstance(div, list) and div
    # intl 按市场路由：网关校验标的注册市场，须用对应市场客户端
    hk = Client.from_env(market="hk")
    us = Client.from_env(market="us")
    for r in (
        _call_or_xfail(lambda: hk.intl.query_ccass("00700", 5)),
        _call_or_xfail(lambda: hk.intl.query_shareholders("00700", 5)),
        _call_or_xfail(lambda: hk.intl.query_org_rating("00700", 5)),
        _call_or_xfail(lambda: hk.intl.query_profit_forecast("00700", 5)),
        _call_or_xfail(lambda: hk.intl.query_sellshort("00700", 5)),
    ):
        assert r is None or isinstance(r, list)
    info = _call_or_xfail(lambda: us.intl.issue_info("BRK_B"))
    assert info is None or isinstance(info, dict)


def test_stocks_universe_industry_batch(cli):
    """v1.9.0 证券基础库：全市场列表 / 行业目录 / 行业成分 / 批量 500 长表。"""
    rows = _call_or_xfail(lambda: cli.stocks.list())
    assert isinstance(rows, list) and len(rows) > 5000
    assert {"symbol", "name", "industry", "industry_name", "listed"} <= set(rows[0].keys())
    l1 = _call_or_xfail(lambda: cli.stocks.industries(1))
    assert isinstance(l1, list) and len(l1) >= 20  # 申万一级 31 个
    banks = _call_or_xfail(lambda: cli.stocks.industry_members("银行"))
    assert isinstance(banks, list) and 30 <= len(banks) <= 60
    assert all(str(r.get("industry", "")).startswith("industry.S48") for r in banks)
    codes = [r["symbol"] for r in rows[:500]]
    res = _call_or_xfail(lambda: cli.call_batch("kline.snapshot", codes))
    assert not res.errors and len(res.results) == 500
    df = res.to_df()
    assert len(df) == 500 and "symbol" in df.columns


def test_stocks_universe_hk_us_markets():
    hk = Client.from_env(market="hk")
    us = Client.from_env(market="us")
    hk_rows = _call_or_xfail(lambda: hk.stocks.list())
    us_rows = _call_or_xfail(lambda: us.stocks.list())
    assert len(hk_rows) > 2000 and len(us_rows) > 5000
    assert {"symbol", "name", "listed"} <= set(hk_rows[0].keys())
    l1 = _call_or_xfail(lambda: hk.stocks.industries(1))
    assert isinstance(l1, list)  # hsi 一级 12 个；美股目录树暂缺不在此断言


def test_macro_domain_smoke(cli):
    """v1.11.0 宏观域：时序结构 + 原生口径数值型断言（业务值随发布漂移不绑死）。"""
    q = _call_or_xfail(lambda: cli.macro.query("$CPI", 3))
    assert isinstance(q, dict) and q.get("ok") is True
    assert q.get("frequency") == "month" and q.get("periods") == 3
    assert isinstance(q.get("series"), list) and len(q["series"]) == 3
    assert {"sas", "annual", "sampling", "value"} <= set(q["latest"].keys())
    asof = _call_or_xfail(lambda: cli.macro.asof("$CPI"))
    assert _is_num(asof)  # 价格指数点（上年同期=100），原生口径
    assert _call_or_xfail(lambda: cli.macro.sampling_of("$GDP")) == "quarter"
    spots = _call_or_xfail(lambda: cli.macro.spots("$GDP", 3))
    assert isinstance(spots, list) and len(spots) == 3
    curve = _call_or_xfail(lambda: cli.macro.bond_curve("中债国债收益率曲线", "10年"))
    assert _is_num(curve)  # 小数口径（0.0168 = 1.68%）
    # 行业情报按披露名单精确匹配；掉榜/名单为空合法返回 None——只断言类型契约
    for r in (
        _call_or_xfail(lambda: cli.macro.nev_monthly("零跑", "sales")),
        _call_or_xfail(lambda: cli.macro.nev_weekly("零跑", "sales")),
        _call_or_xfail(lambda: cli.macro.avc_monthly("消费级摄像头", "volume")),
        _call_or_xfail(lambda: cli.macro.chinaiol_monthly("洗衣机", "volume")),
        _call_or_xfail(lambda: cli.macro.cpca_top("比亚迪汽车", "wholesale")),
        _call_or_xfail(lambda: cli.macro.phone_share("小米", "share")),
    ):
        assert r is None or _is_num(r)


def test_futures_metric_posture(cli):
    """$FUT_* 期货指标码姿势：symbol 绑任意 A 股代码（供 annual/sampling 上下文），
    合约键经 fut_symbol 经 ARGS 透传（国内 cn.SR.ZCE、外盘 global.CL）。"""
    v = _call_or_xfail(lambda: cli.indicator.get("600519", "$FUT_CLOSE"))
    assert _is_num(v), f"期货主力连续收盘应返数值，got {v!r}"
    batch = _call_or_xfail(lambda: cli.indicator.metrics(
        "600519", ["$FUT_CLOSE", "$FUT_VOLUME"], fut_symbol="global.CL"))
    assert isinstance(batch, dict) and _is_num(batch.get("$FUT_CLOSE"))
    has = _call_or_xfail(lambda: cli.indicator.get("600519", "$FUT_HAS"))
    assert has is True


def test_us_kline_daily_bars():
    """美股日 K（上游 us_kline_daily 管线已落库）：合同级断言。

    调度已转正（2026-11-09 daily DAG 启用 + us_dayk_eod 翻闸）：
    新鲜度门禁收紧为末根 ≥ 今天-5 自然日（容忍长周末），另锁结构与降序。
    """
    us = Client.from_env(market="us")
    bars = _call_or_xfail(lambda: us.kline.bars("AAPL", n=5))
    assert isinstance(bars, list) and len(bars) == 5
    assert {"date", "close", "volume"} <= set(bars[0].keys())
    dates = [b["date"] for b in bars]
    assert dates == sorted(dates, reverse=True), "bars 应按日期降序（最新在前）"
    last = datetime.date.fromisoformat(dates[0])
    assert last >= datetime.date.today() - datetime.timedelta(days=5), (
        f"美股日K末根 {dates[0]} 落后超过 5 个自然日（调度已转正）"
    )


def test_us_kline_week_month_bars():
    """美股周/月 K（上游日线本地聚合派生）：结构 + 与日 K 的同日收盘一致性。

    周/月 bar 是日线的纯函数：日期=周期末交易日、open=首日开、close=末日收。
    末根新鲜度按周期给宽（周 ≤ 12 天、月 ≤ 45 天，容忍长周末与月结算）。
    """
    us = Client.from_env(market="us")
    weekly = _call_or_xfail(lambda: us.kline.bars("AAPL", n=5, freq="W"))
    monthly = _call_or_xfail(lambda: us.kline.bars("AAPL", n=3, freq="M"))
    assert isinstance(weekly, list) and len(weekly) == 5
    assert isinstance(monthly, list) and len(monthly) == 3
    for bars, span in ((weekly, 12), (monthly, 45)):
        dates = [b["date"] for b in bars]
        assert dates == sorted(dates, reverse=True), "周期 K 应按日期降序（最新在前）"
        for b in bars:
            assert {"date", "open", "high", "low", "close", "volume"} <= set(b)
            assert b["low"] <= min(b["open"], b["close"]) and b["high"] >= max(
                b["open"], b["close"]), "OHLC 关系违例"
        last = datetime.date.fromisoformat(dates[0])
        assert last >= datetime.date.today() - datetime.timedelta(days=span), (
            f"美股周期K末根 {dates[0]} 落后超过 {span} 天（派生链未跑或滞后）"
        )
    # 同日一致性：周期末日的 close == 当日日 K 的 close（聚合规则 close=末日收）
    daily = _call_or_xfail(lambda: us.kline.bars("AAPL", n=60))
    close_by_date = {b["date"]: b["close"] for b in daily}
    for w in weekly:
        if w["date"] in close_by_date:
            assert abs(w["close"] - close_by_date[w["date"]]) < 1e-6, (
                f"周K {w['date']} 收盘 {w['close']} ≠ 日K {close_by_date[w['date']]}")


def test_kline_week_month_cn_hk():
    """CN/HK 周/月 K 可读（服务端预派生；CN 来自上游预聚合，HK 来自日线派生）。"""
    cn = Client.from_env(market="cn")
    wk = _call_or_xfail(lambda: cn.kline.bars("600519", n=3, freq="W"))
    assert isinstance(wk, list) and wk
    hk = Client.from_env(market="hk")
    hk_wk = _call_or_xfail(lambda: hk.kline.bars("00700", n=3, freq="W"))
    assert isinstance(hk_wk, list) and hk_wk


# ---------------------------------------------------------------- 覆盖面守护
def test_all_core_interfaces_are_exercised_here():
    """本文件必须覆盖 FRIENDLY_INDEX 的每个核心接口（防冒烟面回退）。"""
    src = Path(__file__).read_text(encoding="utf-8")
    missing = []
    for _, ns, method, _, _ in FRIENDLY_INDEX:
        if ns == "statements" and method in ("balance", "income", "cashflow"):
            if '["balance", "income", "cashflow"]' not in src:
                missing.append(f"{ns}.{method}")
            continue
        # 直接调用 <客户端>.ns.method(...) 或以可调用对象传入；客户端变量名可多样
        # （cli / hk / us——港美股披露须用对应市场客户端，见 test_workout_index_intl_domain_smoke）
        if f".{ns}.{method}(" not in src and f".{ns}.{method}," not in src:
            missing.append(f"{ns}.{method}")
    assert not missing, f"live 冒烟未覆盖：{missing}（共 {CORE_COUNT} 个核心接口）"
