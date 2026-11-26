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
    bars = cli.kline.bars(symbol, n=5)  # 2.0：门面默认 DataFrame
    assert len(bars) == 5
    for _, bar in bars.iterrows():
        assert {"date", "close", "open", "high", "low"} <= set(bars.columns)
        assert _is_num(bar["close"]) and bar["close"] > 0
        assert bar["low"] <= bar["high"]
    dates = [str(d) for d in bars["date"]]
    assert dates == sorted(dates), "日 K 应按日期升序（2.0：旧→新）"


def test_kline_bars_adj_variants(cli):
    nr = cli.kline.bars(MAIN, n=3)
    qfq = cli.kline.bars(MAIN, n=3, adj="qfq")
    assert list(nr["date"]) == list(qfq["date"])
    assert all(_is_num(v) and v > 0 for v in qfq["close"])


def test_kline_bars_date_range(cli):
    rows = cli.kline.bars(MAIN, begin="2026-09-01", end="2026-09-30")
    assert rows is not None and len(rows) > 0
    assert all("2026-09-01" <= str(d) <= "2026-09-30" for d in rows["date"])
    money = cli.moneyflow.bars(MAIN, begin="2026-09-01", end="2026-09-30")
    assert all("2026-09-01" <= str(d) <= "2026-09-30" for d in money["date"])


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


# ---- ETF 九视图组合门面（W3 护栏 5：每 view 一个 live 调用点）----
ETF = "510300"  # 沪深300ETF，真实宽基，九视图均有采集


@pytest.mark.parametrize("view", [
    "card", "nav", "share", "div", "portfolio", "profile", "premium", "asset", "rank",
])
def test_etf_views(cli, view):
    """九视图 live 冒烟：返回 MAP、view 字段与请求一致、数值锚点合理。

    组合门面不进 FRIENDLY_INDEX（不触发 CORE_COUNT 提醒），故在此显式全覆盖，
    由 tests/test_live_coverage.py 的静态扫描守护不被删。
    """
    got = _call_or_xfail(getattr(cli.etf, view), ETF)
    assert isinstance(got, dict), got
    assert got.get("ok") is True, got                    # 未就绪/非 ETF 由门面抛 DataError
    expected_view = view                                 # meta.view 记 SDK 方法名
    # 2.0 信封：业务字段在 data，view/mode 在 meta（顶层不再有 view）
    assert (got.get("meta") or {}).get("view") == expected_view, (view, got.get("meta"))
    data = got.get("data") or {}
    # 数值锚点：至少有一个该 view 的特征数值字段且量级合理（防 0.25→25 量级错）
    if view == "asset":
        vals = [data[k] for k in ("stock_ratio", "bond_ratio", "cash_ratio",
                                  "other_ratio", "fund_ratio") if data.get(k) is not None]
        assert vals and all(0 <= v <= 100 for v in vals), data
    elif view == "rank":
        for key in ("chg_w1", "chg_m1", "chg_m3"):
            if data.get(key) is not None:
                assert -100 <= data[key] <= 1000, (key, data[key])
    elif view == "premium":
        if data.get("premium_pct") is not None:
            assert -100 <= data["premium_pct"] <= 1000, data["premium_pct"]
    elif view == "nav":
        na = data.get("net_asset")
        if isinstance(na, dict):                          # nav 返回 {date, net_asset}
            na = na.get("net_asset")
        if na is not None:
            assert na >= 0, na                            # 亿元非负
    elif view == "card":
        q = data.get("quote") or {}                       # card 顶层无 net_asset
        if q.get("close") is not None:
            assert q["close"] > 0, q["close"]


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
    assert len(rows) == 5
    assert {"date", "net_mf"} <= set(rows.columns)
    assert all(_is_num(v) for v in rows["net_mf"])
    dates = [str(d) for d in rows["date"]]
    assert dates == sorted(dates), "资金流应按日期升序（2.0：旧→新）"


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


def test_statements_notes(cli):
    card = cli.statements.notes(MAIN, "MFNS")
    assert isinstance(card, dict)
    assert {"found", "code", "cn", "period", "source", "sections"} <= set(card)
    if card["found"]:
        sec = card["sections"][0]
        assert {"title", "rows"} <= set(sec)


def test_statements_notes_cn_name(cli):
    # 中文名走脚本内目录双匹配，与目录码同形
    card = cli.statements.notes(MAIN, "货币资金")
    assert isinstance(card, dict) and {"found", "sections"} <= set(card)


def test_statements_notes_index(cli):
    rows = cli.statements.notes_index(MAIN)
    if hasattr(rows, "columns"):  # DataFrame
        assert {"code", "cn", "period"} <= set(rows.columns)
        records = rows.to_dict("records")
    else:
        records = rows
    assert isinstance(records, list)
    if records:
        assert {"code", "cn", "period"} <= set(records[0])


def test_statements_policies(cli):
    doc = cli.statements.policies(MAIN)
    assert isinstance(doc, dict)
    assert {"periods", "period", "cards", "hist"} <= set(doc)
    if doc["period"]:
        assert doc["period"].endswith("12-31")  # 政策卡仅年报期
    if doc["cards"]:
        assert {"policy_id", "params"} <= set(doc["cards"][0])
    if doc["hist"]:
        assert "quote" not in doc["hist"][0]  # hist 不带 quote（体积控制）



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


def test_notice_categories_and_regex(cli):
    keys = cli.notice.categories()
    assert isinstance(keys, list) and "buyback" in keys
    assert "回购" in cli.notice.category_regex("buyback")
    # 未知键原样透传（自定义正则入口）
    assert cli.notice.category_regex("业绩说明") == "业绩说明"


def test_equity_buyback_snapshot(cli):
    snap = _call_or_xfail(lambda: cli.equity.buyback_snapshot("600519"))
    assert isinstance(snap, dict)
    assert {"exec_1y", "exec_total", "plan_1y", "plan_total",
            "plan_1y_cancel", "plan_total_cancel"} <= set(snap)
    exec_total = snap.get("exec_total")
    assert exec_total is None or exec_total >= 0


def test_pdf_doc_read_surfaces(cli):
    """pdf_doc 纯读面：检索/状态/正文/markdown/定位（正文就绪与否不作断言）。"""
    df = _call_or_xfail(lambda: cli.pdf_doc.search(stock_code=MAIN, limit=3))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert rows, "检索应有结果"
    file_key = rows[0].get("file_key") if rows and isinstance(rows[0], dict) else ""
    st = _call_or_xfail(lambda: cli.pdf_doc.status(file_key or "no-such-key"))
    assert isinstance(st, dict) and "status" in st
    body = _call_or_xfail(lambda: cli.pdf_doc.read_text(file_key or "no-such-key"))
    assert isinstance(body, dict) and "ok" in body
    md = _call_or_xfail(lambda: cli.pdf_doc.read_markdown(stock_code=MAIN, period="2024"))
    assert isinstance(md, dict)
    assert not cli.pdf_doc.find_by_key("no-such-key")
    assert not cli.pdf_doc.find_by_url("https://")


def test_toplist_by_date_and_symbol(cli):
    """龙虎榜：单日榜单 + 单票事件（行合同与守护声明）"""
    rows = _call_or_xfail(lambda: cli.toplist.by_date("2026-11-18", 10))
    assert isinstance(rows, list) and rows
    r0 = rows[0]
    assert {"date", "symbol", "name", "close", "pct_chg", "net_amount",
            "reason"} <= set(r0), "toplist 行合同 15 字段"
    assert -1 <= r0["pct_chg"] <= 1, "涨跌幅应为小数"
    hits = _call_or_xfail(lambda: cli.toplist.by_symbol("000530", 10))
    assert isinstance(hits, list) and hits
    assert all(h["symbol"] == "000530" for h in hits)


def test_futures_mapping(cli):
    """期货换月映射：RB.SHF 全历史行合同（date/symbol/mapping_symbol 升序）"""
    df = _call_or_xfail(lambda: cli.futures.mapping("RB.SHF"))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert rows
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates), "mapping 应为 date 升序"
    assert all(r["symbol"] == "RB.SHF" and r["mapping_symbol"] for r in rows)
    win = _call_or_xfail(
        lambda: cli.futures.mapping("RB.SHF", "2026-11-01", "2026-11-18"))
    assert len(win) <= len(rows), "窗口行数不超过全历史"


def test_futures_bars(cli):
    """期货主力连续历史K线（store 直读）：月频聚合/日频交易日行/快照一致。"""
    df = _call_or_xfail(lambda: cli.futures.bars("AL.SHF", n=6, freq="m"))
    assert len(df) == 6
    assert list(df["date"]) == sorted(df["date"]), "bars 应为 date 升序"
    assert {"date", "sas", "open", "high", "low", "close", "settle",
            "volume", "open_interest", "has_kline"} <= set(df.columns)
    assert all(str(d).endswith("-01") for d in df["date"]), "月频 date=当月 1 日"
    assert bool((df["high"] >= df["low"]).all()) and bool((df["volume"] > 0).all())
    win = _call_or_xfail(
        lambda: cli.futures.bars("AL.SHF", begin="2026-11-01", end="2026-11-20"))
    assert len(win) >= 1 and list(win["date"]) == sorted(win["date"])
    # 日频只含交易日（无周末占位行）
    daily = _call_or_xfail(lambda: cli.futures.bars("AL.SHF", n=10, freq="d"))
    assert len(daily) == 10
    for value in daily["date"]:
        dt = datetime.date.fromisoformat(str(value))
        assert dt.weekday() < 5, f"日线出现非交易日行 {value}"
    # 快照与日线末根同源（date/close 一致）
    snap = _call_or_xfail(lambda: cli.futures.snapshot("AL.SHF"))
    assert snap["date"] == str(daily["date"].iloc[-1])
    assert snap["close"] == daily["close"].iloc[-1]
    # 外盘同路径可寻址（曾因 GLOBAL 前缀切错而全不可用）
    assert isinstance(
        _call_or_xfail(lambda: cli.futures.get("global.CL", "close")),
        (int, float))


def test_fx_rate_and_history(cli):
    """外汇：美元中间价量级归一（每 1 单位≈7.1，非每 100 外币≈700）+ 日线升序"""
    snap = _call_or_xfail(lambda: cli.fx.rate("USD"))
    assert snap and snap.get("middle") is not None
    # 硬断言：USD/CNY 必在 5~10 区间；若退化成每 100 外币原值（≈700）立即暴露
    assert 5.0 <= float(snap["middle"]) <= 10.0, f"USD 中间价量级异常：{snap['middle']}"
    assert len(str(snap.get("date", ""))) == 10, "date 应为 ISO YYYY-MM-DD"

    df = _call_or_xfail(lambda: cli.fx.history("USD", n=10))
    assert len(df) >= 1
    assert list(df["date"]) == sorted(df["date"]), "history 应为 date 升序"
    assert {"date", "ccy", "middle", "buy"} <= set(df.columns)
    vals = [v for v in df["middle"].tolist() if v is not None]
    assert vals and all(5.0 <= float(v) <= 10.0 for v in vals), "USD 日线全量级异常"

    win = _call_or_xfail(
        lambda: cli.fx.bars("USD", begin="2026-11-01", end="2026-11-21"))
    assert list(win["date"]) == sorted(win["date"])

    lst = _call_or_xfail(lambda: cli.fx.list())
    assert len(lst) >= 3 and "USD" in set(lst["ccy"])


def test_macro_reserves(cli):
    """储备：值=美元数值（外汇≈3e12、黄金≈3e11 量级），SDR 无生产者返回 None"""
    items = _call_or_xfail(lambda: cli.macro.reserves())
    assert {"kind", "label", "available", "value"} <= set(items.columns)
    kinds = set(items["kind"])
    assert {"forex", "gold", "sdr"} <= kinds
    avail = {row["kind"]: row["available"] for row in items.to_dict("records")}
    assert avail["forex"] is True and avail["gold"] is True
    assert avail["sdr"] is False, "SDR 上游无生产者，应如实标 False"

    snap = _call_or_xfail(lambda: cli.macro.reserves_asof("forex"))
    # 硬断言：外汇储备约 3~4 万亿美元 = 3~4e12；若变成 亿美元(≈3e4) 或 元(≈2e13+) 立即暴露
    assert 2.5e12 <= float(snap["value"]) <= 5.0e12, f"外汇储备量级异常：{snap['value']}"
    assert len(str(snap.get("date", ""))) == 7, "储备期次应为 YYYY-MM"

    hist = _call_or_xfail(lambda: cli.macro.reserves_history("forex", n=6))
    assert len(hist) >= 1 and list(hist["date"]) == sorted(hist["date"])

    assert cli.macro.reserves_asof("sdr") is None, "SDR 无数据应返回 None（不返回 0）"


def test_us_macro_series(cli):
    """美宏观：升序合同 + 单位随序列而变 + 需授权序列如实无数据。

    量纲硬断言（本域最易错处）：GDP 是十亿美元口径（≈3e4），UNRATE 是百分数
    （0~30）。若有人把单位当元来归一，GDP 会掉到 3e4 以外的量级立即暴露。
    """
    topics = _call_or_xfail(lambda: cli.us_macro.topics())
    assert len(topics) == 11, f"精选主题应 11 个，实际 {len(topics)}"
    assert {"topic", "name", "series"} <= set(topics.columns)
    total_series = sum(len(list(s)) for s in topics["series"])
    assert total_series == 88, f"精选序列应 88 条，实际 {total_series}"

    hits = _call_or_xfail(lambda: cli.us_macro.search("GDP", 5))
    assert len(hits) >= 1 and "GDP" in set(hits["id"])
    assert all(hits["title_zh"]), "精选中文名应齐（88 条均有中文名）"

    meta = _call_or_xfail(lambda: cli.us_macro.series_meta("GDP"))
    assert meta["units"] == "Billions of Dollars", f"GDP 单位应为十亿美元：{meta['units']}"
    assert meta["has_data"] is True
    assert meta["citation"].startswith("FRED"), "引用字段原文应保留"

    pts = _call_or_xfail(lambda: cli.us_macro.points("GDP", limit=20))
    assert len(pts) >= 1
    assert list(pts["date"]) == sorted(pts["date"]), "点序列应 date 升序（旧→新）"
    assert {"id", "date", "value"} <= set(pts.columns)
    last = float(pts["value"].iloc[-1])
    # 十亿美元口径：名义 GDP 万亿美元级 → 2e4~4e4；若误当元/百万分立即暴露
    assert 1e3 <= last <= 1e5, f"GDP 末值量级异常（应为十亿美元）：{last}"

    # 百分数序列：不同单位必须共存于同一读面（证明无统一换算）
    unrate = _call_or_xfail(lambda: cli.us_macro.points("UNRATE", limit=10))
    if len(unrate) >= 1:
        v = float(unrate["value"].iloc[-1])
        assert 0.0 <= v <= 30.0, f"UNRATE 应为百分数（0~30），实际 {v}"

    # 需授权序列：如实标 has_data=False，不伪造数据
    locked = _call_or_xfail(lambda: cli.us_macro.series_meta("CSUSHPINSA"))
    if locked and locked.get("status") == "pre_approval_required":
        assert locked["has_data"] is False, "需授权序列不应有数据"

    # 参数健壮性：非法日期曾使 DATE() 抛宿主异常（HTTP 500）。现应视为未提供该端。
    bad = _call_or_xfail(lambda: cli.us_macro.points("GDP", begin="not-a-date",
                                                     end="also-bad", limit=5))
    assert len(bad) >= 1, "非法日期应退化为「不设窗口」而不是抛异常或空集"

    # 单次硬顶：limit 超过 store 上限（10000）时不得静默超领，也不得报错
    big = _call_or_xfail(lambda: cli.us_macro.points("DGS10", limit=12000))
    assert len(big) <= 10_000, f"store 单次硬顶 10000 行，实际返回 {len(big)}"


def test_notice_read_text(cli):
    """公告正文读取：取一条有 PDF 的公告，预览路径应返回纯读 MAP。

    覆盖四个锚点：① 预览 text_chars<=4000 且 text_truncated 与之一致；
    ② status/title/source_url 等 11 字段齐全；③ 纯读不触发入队（ok=false 时
    status 为 not_ready/no_pdf_url 等非 ready 态）；④ 港股 5 位码定位路径。
    """
    FIELDS = {"ok", "status", "text", "text_chars", "text_truncated", "file_key",
              "source_url", "announce_date", "title", "error", "note"}
    rows = cli.notice.list(MAIN, window="1y", limit=20)
    assert rows
    picked = None
    for r in rows:
        url = r.get("pdf_url") or r.get("url")
        if url:
            picked = r
            break
    assert picked, "近一年公告里应有带 PDF 链接的行"
    date = str(picked.get("date", ""))[:10]
    got = cli.notice.read_text(MAIN, date, picked.get("pdf_url") or picked.get("url", ""),
                               full=False)
    assert isinstance(got, dict) and FIELDS <= set(got), (FIELDS - set(got), got)
    assert isinstance(got["text_chars"], int) and got["text_chars"] >= 0
    if got["ok"]:
        assert got["text_chars"] <= 4000 and got["text_truncated"] in (True, False)
        assert len(got["text"]) == got["text_chars"]
    # 全量路径：正文应包含预览或更长（同一文档，不张冠李戴）
    full = cli.notice.read_text(MAIN, date, picked.get("pdf_url") or picked.get("url", ""),
                                full=True)
    assert isinstance(full, dict) and full["source_url"] == got["source_url"]


def test_notice_read_text_empty_date_returns_business_failure(cli):
    """review P1-1 回归：date 为空串（契约允许）不得抛 ServerError。

    script 侧修复前，空串切片在远程沙箱返回 null，使 `_date != ""` 守卫失效，
    query_find → DATE(null) 触发 HTTP 500；修复后应直接返回可预期的
    no_pdf_url 业务失败包，且 announce_date 为 str 空串。

    该用例依赖 script 修复已发布；未发布时会如实失败，不用 xfail 吞掉 500。
    """
    got = cli.notice.read_text(MAIN, "", "", full=False)
    assert isinstance(got, dict)
    assert got.get("ok") is False, got
    assert got.get("status") == "no_pdf_url", got
    assert got.get("error") == "no_pdf_url", got
    assert isinstance(got.get("announce_date"), str), got
    assert got.get("announce_date") == "", got


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


# ---- 2.5 收息场景闭环（sys/income：榜单 memo 直读 / 原生批量诊断 / 日历 / 拆解）----

def test_income_rating_smoke(cli):
    env = cli.dividend.rating(top_n=3)
    if not env.get("ok"):
        assert env.get("meta", {}).get("error") == "COLD_CACHE"
        pytest.skip("收息榜 memo 未就绪（cron 未跑），稍后重试")
    rows = env["data"]["rows"]
    assert rows and rows[0]["rank"] == 1
    top = rows[0]
    assert isinstance(top["score"]["total"], int) and top["score"]["grade"] in (
        "strong", "good", "watch", "avoid")
    assert isinstance(top["gate_pass"], bool)
    # 批量档对账：同一 memo 下 batch 诊断的评分口径与榜单行一致（found 票必有档位）
    assert isinstance(env["meta"].get("universe"), int) and env["meta"]["universe"] > 0


def test_income_diagnose_batch_smoke(cli):
    env = cli.dividend.diagnose([MAIN, "600900"])
    assert env.get("ok") is True
    items = env["data"]["items"]
    assert len(items) == 2
    for it in items:
        assert it.get("found") is True
        sc = it.get("score") or {}
        assert isinstance(sc.get("total"), int)
        assert set(sc.get("flags") or []) <= {
            "payout_danger", "decaying_high_yield", "verify_data", "floor_blind"}


def test_income_calendar_smoke(cli):
    today = date.today()
    env = cli.dividend.calendar(today.strftime("%Y-%m-01"), today.strftime("%Y-%m-%d"))
    assert env.get("ok") is True
    assert isinstance(env["data"].get("count"), int)


def test_income_decomp_smoke(cli):
    env = cli.dividend.decomp(MAIN, years=3)
    assert env.get("ok") is True
    item = env["data"]["items"][0]
    assert item.get("ok") is True
    for key in ("total_return", "price_return", "dividend_return"):
        v = item.get(key)
        assert v is None or -1 <= v <= 50


def test_index_members_history_smoke(cli):
    # 2.5 并发会话新面（indices.members_daily 前向 PIT）：上游刚部署，宽松冒烟
    env = _call_or_xfail(cli.index.members_history, "index.hs300", begin="2026-11-01")
    if isinstance(env, dict) and "ok" in env:
        assert env.get("ok") is True


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


# ---------------------------------------------------------------- 每日估值宽表
def test_valuation_daily_basic_live(cli):
    """600519 近 60 日：信封形 + 长表字段合法 + as_of 新鲜（服务端物化表就绪后转真）。"""
    r = _call_or_xfail(
        lambda: cli.valuation.daily_basic("600519", begin="2026-09-01", end="2026-11-16",
                                          fields=["pe_ttm", "total_mv"]))
    assert r.get("ok") is True and isinstance(r.get("data"), list)
    assert r.get("as_of"), "缺 as_of（表内最新行日期）"
    for row in r["data"]:
        assert row["symbol"] == "600519" and row["field"] in ("pe_ttm", "total_mv")
        assert isinstance(row["value"], (int, float))
    # 2026-11-19 新增：meta.window 段暴露读窗口截断（BACKLOG 缺口闭环）
    win = (r.get("meta") or {}).get("window") or {}
    assert win.get("scan_limit"), "缺 meta.window.scan_limit"
    assert isinstance(win.get("truncated"), bool), "缺 meta.window.truncated"
    # 2026-11-24：服务端按日期降序返回，门面必须归一为 (date, field) 升序
    pairs = [(row["date"], row["field"]) for row in r["data"]]
    assert pairs == sorted(pairs), "长表应按 (date, field) 升序"


def test_valuation_daily_basic_multi_live(cli):
    """多票估值序列：一次 eval 两票，行合同与单票一致 + per_symbol 明细。"""
    r = _call_or_xfail(
        lambda: cli.valuation.daily_basic_multi(
            ["600519", "000001"], begin="2026-10-01", end="2026-11-16",
            fields=["pe_ttm"]))
    assert r.get("ok") is True and isinstance(r.get("data"), list)
    syms = {row["symbol"] for row in r["data"]}
    assert syms == {"600519", "000001"}, syms
    for row in r["data"]:
        assert row["field"] == "pe_ttm"
        assert isinstance(row["value"], (int, float))
    per = (r.get("meta") or {}).get("per_symbol") or []
    assert {p["symbol"] for p in per} == {"600519", "000001"}, per
    for item in per:
        assert isinstance(item.get("count"), int)
        assert isinstance(item.get("truncated"), bool)
    # 2026-11-24：多票长表按 (symbol, date, field) 升序，每票内 date 升序
    keys = [(row["symbol"], row["date"], row["field"]) for row in r["data"]]
    assert keys == sorted(keys), "多票长表应按 (symbol, date, field) 升序"


def test_valuation_daily_basic_coverage_live(cli):
    """可用范围发现：不拉序列，只回 window 元数据。"""
    r = _call_or_xfail(lambda: cli.valuation.daily_basic_coverage(
        "600519", begin="2023-01-01", end="2026-11-16"))
    assert r.get("ok") is True
    data = r.get("data") or {}
    assert data.get("as_of"), "缺 as_of"
    assert isinstance(data.get("truncated"), bool)
    assert int(data.get("scan_limit") or 0) > 0



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


def test_blocktrade_read_face(cli):
    """大宗交易：单票历史 date 升序、成交额≈价×量；单日榜成交额降序。"""
    out = _call_or_xfail(lambda: cli.blocktrade.by_symbol("000001", 5))
    rows = out.to_dict("records") if hasattr(out, "to_dict") else list(out)
    assert rows, "000001 应有大宗交易历史（2010 至今全量已回补，4,100 个交易日）"
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates), f"单票历史必须 date 升序：{dates}"
    for r in rows:
        assert float(r["volume"]) > 0 and float(r["amount"]) > 0
        implied = float(r["price"]) * float(r["volume"])
        assert abs(float(r["amount"]) - implied) / max(implied, 1) < 0.01, (
            f"amount 与 price×volume 偏离过大：{r}")
    day = _call_or_xfail(lambda: cli.blocktrade.by_date(dates[-1], 5))
    day_rows = day.to_dict("records") if hasattr(day, "to_dict") else list(day)
    assert day_rows, "最新一笔所在交易日应有全市场榜"
    amounts = [float(r["amount"]) for r in day_rows]
    assert amounts == sorted(amounts, reverse=True), "单日榜必须成交额降序"


def test_st_lifecycle_read_face(cli):
    """ST/停复牌史：简称段按生效日升序、is_st 与简称一致；时间轴严格升序。"""
    out = _call_or_xfail(lambda: cli.stocks.name_history("000001"))
    rows = out.to_dict("records") if hasattr(out, "to_dict") else list(out)
    if not rows:
        pytest.skip("namechange 尚未回补（采集部署后解除此跳过）")
    starts = [str(r["start_date"]) for r in rows]
    assert starts == sorted(starts), f"简称段必须 start_date 升序：{starts}"
    for r in rows:
        assert bool(r["is_st"]) == ("ST" in str(r["name"]).upper()), r

    susp = _call_or_xfail(
        lambda: cli.stocks.suspend_history("600519", "2026-01-01", "2026-11-23"))
    susp_rows = susp.to_dict("records") if hasattr(susp, "to_dict") else list(susp)
    if susp_rows:
        sdates = [str(r["date"]) for r in susp_rows]
        assert sdates == sorted(sdates), f"停复牌必须 date 升序：{sdates[:3]}…"
        assert {str(r["type"]) for r in susp_rows} <= {"S", "R"}
        for r in susp_rows:
            assert len(str(r["date"])) == 10, r  # ISO YYYY-MM-DD

    lc = _call_or_xfail(lambda: cli.stocks.lifecycle("000001"))
    events = lc.to_dict("records") if hasattr(lc, "to_dict") else list(lc)
    assert events, "时间轴不应为空"
    dates = [str(e["date"]) for e in events]
    assert dates == sorted(dates), f"时间轴必须 date 升序：{dates[:3]}…"
    kinds = {str(e["kind"]) for e in events}
    assert kinds <= {"rename", "st_enter", "st_exit", "suspend", "resume"}, kinds
    assert "rename" in kinds, "000001 应有简称变更事件"


def test_board_concept_tags(cli):
    """概念标签：单票 tags 非空且去 s: 前缀；成份按代码升序。"""
    info = _call_or_xfail(lambda: cli.board.concepts_of("600519"))
    if info is None:
        pytest.skip("概念索引未物化（$CONCEPT_TAGS 为空）")
    tags = info.get("tags") or []
    assert tags, "600519 应有概念标签"
    assert not any(str(t).startswith("s:") for t in tags), f"tags 应去前缀：{tags[:3]}"

    members = _call_or_xfail(lambda: cli.board.concept_members("白酒", 50))
    rows = members.to_dict("records") if hasattr(members, "to_dict") else list(members)
    assert rows, "白酒概念应有成份股"
    syms = [str(r["symbol"]) for r in rows]
    assert syms == sorted(syms), f"成份应代码升序：{syms[:5]}"


def test_futures_receipts(cli):
    """交易所仓单快照：行形齐、unit 非空、title 基本唯一（按月口径，非逐日历史）。"""
    df = _call_or_xfail(lambda: cli.futures.receipts())
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        pytest.skip("该月无仓单档（上游按月 REPLACE，月初可能未抓取）")
    assert all(r["unit"] for r in rows), "每行应有 unit（吨/张）"
    titles = [r["title"] for r in rows]
    # 郑商所仓单表对红枣CJ/花生PK 会把同一行输出两遍（qty=0，2026-11-23 档实测），
    # 属上游原样数据；除这两项外重复即说明读面拼档出错。
    dup = {t for t in titles if titles.count(t) > 1}
    assert dup <= {"CZCE.红枣CJ", "CZCE.花生PK"}, f"非预期重复 title：{sorted(dup)}"
    assert {str(r["exchange"]) for r in rows} <= {"SHFE", "CZCE", "GFEX", "DCE"}


def test_futures_holding(cli):
    """每日持仓排名：按合约返回会员排名，vol 降序、合约一致。"""
    dates = _call_or_xfail(lambda: cli.call("futures.holding_dates"))
    if not dates:
        pytest.skip("无持仓排名档（采集器未跑）")
    probe = _call_or_xfail(lambda: cli.futures.holding(limit=1))
    rows0 = probe.to_dict("records") if hasattr(probe, "to_dict") else list(probe)
    if not rows0:
        pytest.skip("最新交易日无持仓行")
    contract = str(rows0[0]["contract"])
    df = _call_or_xfail(lambda: cli.futures.holding(contract=contract, limit=10))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert rows, f"{contract} 应有会员排名行"
    assert all(str(r["contract"]) == contract for r in rows)
    vols = [float(r["vol"]) for r in rows]
    assert vols == sorted(vols, reverse=True), "应按成交量降序"
    assert {"broker", "long_hld", "short_hld"} <= set(rows[0])


def test_futures_settle(cli):
    """每日结算参数：品种前缀过滤生效、合约升序、结算价为正。"""
    dates = _call_or_xfail(lambda: cli.call("futures.settle_dates"))
    if not dates:
        pytest.skip("无结算参数档（采集器未跑）")
    df = _call_or_xfail(lambda: cli.futures.settle(contract="CU"))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        pytest.skip("最新交易日无 CU 结算参数")
    contracts = [str(r["contract"]) for r in rows]
    assert all(c.startswith("CU") for c in contracts), "品种前缀过滤应生效"
    assert contracts == sorted(contracts), "应按合约升序"
    assert all(float(r["settle"]) > 0 for r in rows)


def test_gold_symbols(cli):
    """金交所现货品种清单：键带 .SGE 后缀、日期为 ISO、有成交的品种收盘为正。"""
    df = _call_or_xfail(lambda: cli.gold.symbols())
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        pytest.skip("金交所现货无数据（采集器未跑）")
    assert all(str(r["symbol"]).endswith(".SGE") for r in rows)
    assert all(len(str(r["date"])) == 10 for r in rows)
    # 部分品种当期无成交（如 Au99.95/Au100g 停做），上游 close=0 → 不作正数断言，
    # 但至少要有一半品种有真实报价（否则说明读面整体取错）
    closes = [float(r["close"]) for r in rows if r.get("close") is not None]
    positive = [c for c in closes if c > 0]
    assert len(positive) >= max(len(closes) // 2, 1), closes
    # 主力品种必须有价：Au99.99 是探针基准（gold.symbols 的版本键就是它）
    assert any(str(r["code"]) == "Au99.99" and float(r["close"] or 0) > 0
               for r in rows), rows


def test_gold_bars(cli):
    """金交所现货日线：三品种口径自洽（vol×1000×close ≈ amount）、date 升序。"""
    df = _call_or_xfail(lambda: cli.gold.bars("Au99.99", n=10))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        pytest.skip("Au99.99 无日线（采集器未跑）")
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates), "date 应升序（旧→新）"
    assert all(str(r["symbol"]).endswith(".SGE") for r in rows)
    # 口径实证：价=元/克、量=千克、额=元 → vol×1000×close ≈ amount（容差 5%）
    checked = 0
    for r in rows:
        vol, close, amt = r.get("volume"), r.get("close"), r.get("amount")
        if not (vol and close and amt):
            continue
        checked += 1
        ratio = float(vol) * 1000.0 * float(close) / float(amt)
        assert 0.5 < ratio < 2.0, f"{r['date']} vol×1000×close/amount={ratio:.3f}"
    assert checked, "至少应有一行齐备 volume/close/amount"
    # percent 由 change1 派生：非空时应在合理带内，且不得全为 None
    pcts = [r["percent"] for r in rows if r.get("percent") is not None]
    if pcts:
        assert all(abs(float(p)) < 0.3 for p in pcts), pcts


def test_gold_query_bars(cli):
    """金交所现货区间日线：begin/end 下推生效、区间内日期单调。"""
    latest = _call_or_xfail(lambda: cli.gold.bars("Au99.99", n=1))
    rows0 = latest.to_dict("records") if hasattr(latest, "to_dict") else list(latest)
    if not rows0:
        pytest.skip("Au99.99 无日线（采集器未跑）")
    end = str(rows0[-1]["date"])
    df = _call_or_xfail(lambda: cli.gold.query_bars("Au99.99", "2026-11-01", end, 50))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    if not rows:
        pytest.skip("区间内无数据")
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates)
    assert dates[0] >= "2026-11-01" and dates[-1] <= end


def test_kline_adj_factor(cli):
    """累计复权因子：hfq/nr 比值，除权间隔内恒定，非复权日应等于 hfq/nr 直比。"""
    df = _call_or_xfail(lambda: cli.kline.adj_factor("600519", n=5))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert len(rows) == 5, rows
    factors = [float(r["factor"]) for r in rows]
    assert all(f > 0 for f in factors), factors
    # 600519 近 5 个交易日无除权（2026-11-24 实测 8.6469 恒定）
    assert len(set(round(f, 4) for f in factors)) == 1, factors
    # 与两次直取互证
    nr = cli.kline.bars("600519", n=1)
    hfq = cli.kline.bars("600519", n=1, adj="hfq")
    last_nr = float(nr["close"].iloc[-1])
    last_hfq = float(hfq["close"].iloc[-1])
    assert abs(factors[-1] - last_hfq / last_nr) < 1e-6


def test_index_bars_weekly(cli):
    """指数周线（SDK 聚合）：date 为周期末交易日、OHLC 关系成立、末值对齐日线。"""
    df = _call_or_xfail(lambda: cli.index.bars("index.hs300", freq="W", n=5))
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert len(rows) == 5, rows
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates)
    for r in rows:
        hi, lo = float(r["high"]), float(r["low"])
        assert hi >= max(float(r["open"]), float(r["close"])) - 1e-6
        assert lo <= min(float(r["open"]), float(r["close"])) + 1e-6
    # 末个周线 close == 最新交易日日线 close（周线含未走完的当前周）
    daily = cli.kline.bars("index.hs300", n=1)
    assert abs(float(rows[-1]["close"]) - float(daily["close"].iloc[-1])) < 1e-6


def test_board_concept_list(cli):
    """概念板块目录（日更物化档）：行形 name/count/members；count 降序、
    members 升序；与 concept_members 同源互证。"""
    df = _call_or_xfail(lambda: cli.board.concept_list())
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    assert rows, "概念目录应为非空（未物化会受控报错而非空表）"
    counts = [int(r["count"]) for r in rows]
    assert counts == sorted(counts, reverse=True), "应按成员数降序"
    top = rows[0]
    assert top["members"] == sorted(top["members"]), "members 应代码升序"
    assert int(top["count"]) == len(top["members"]), "count 应等于成员数"
    # 同源互证：任取一个真实概念名，concept_members 的代码应落在目录并集内
    probe = next((r for r in rows if r["name"].strip() == "白酒"), None)
    if probe is not None:
        ms = _call_or_xfail(lambda: cli.board.concept_members("白酒", 300))
        mrows = ms.to_dict("records") if hasattr(ms, "to_dict") else list(ms)
        in_list = {str(r["symbol"]) for r in mrows} & set(probe["members"])
        assert in_list, "concept_members 成员应与目录同源"



def test_board_moneyflow_three_sources(cli):
    """板块资金流：三源同口径（额=元、率=小数），指定日与最新日逐行一致。"""
    for src, min_rows in (("ths_concept", 300), ("ths_industry", 80), ("dc", 900)):
        out = _call_or_xfail(lambda: cli.board.moneyflow_last(src, 5))
        rows = out.to_dict("records") if hasattr(out, "to_dict") else list(out)
        assert len(rows) == 5, f"{src} 应返回 5 行，实际 {len(rows)}"
        first = rows[0]
        assert first["source"] == src
        assert abs(float(first["net_amount"])) > 1e6, f"{src} 净额应为元量级"
        assert -1 < float(first["pct_change"]) < 1, f"{src} 涨跌幅应为小数"
    # 指定交易日回查与最新榜一致（同排序、同截断）
    last = _call_or_xfail(lambda: cli.board.moneyflow_last("ths_concept", 5))
    rows = last.to_dict("records") if hasattr(last, "to_dict") else list(last)
    day = rows[0]["date"]
    back = _call_or_xfail(lambda: cli.board.moneyflow("ths_concept", day, 5))
    back_rows = back.to_dict("records") if hasattr(back, "to_dict") else list(back)
    assert [r["code"] for r in rows] == [r["code"] for r in back_rows]


def test_limit_prices_snapshot(cli):
    """每日涨跌停价：全市场快照的规则价必须与当日封板收盘精确相等。"""
    out = _call_or_xfail(lambda: cli.stocks.limit_prices())
    rows = out.to_dict("records") if hasattr(out, "to_dict") else list(out)
    assert len(rows) > 4000, f"非停牌全市场应 >4000 行，实际 {len(rows)}"

    def band(sym: str) -> float:
        p2 = str(sym)[:2]
        if p2 in ("30", "68"):
            return 0.20
        if p2 in ("43", "83", "87", "88", "92"):
            return 0.30
        return 0.10

    near = mism = 0
    for r in rows:
        if r["rule"] not in ("main10", "gem20", "star20", "bse30"):
            continue
        pct = float(r["percent"] or 0)
        if abs(pct) >= band(r["symbol"]) - 0.001:
            near += 1
            want = r["limit_up"] if pct >= 0 else r["limit_down"]
            if want != r["close"]:
                mism += 1
    assert near > 0, "当日应存在贴近涨跌停的样本"
    assert mism == 0, f"规则价与封板收盘不等：{mism}/{near}"

    one = _call_or_xfail(lambda: cli.stocks.limit_price("600519"))
    assert one is not None
    if one["limit_up"] is not None:
        assert float(one["limit_up"]) > float(one["limit_down"]) > 0


def test_limit_price_history_series(cli):
    """历史涨跌停价：逐日规则价、ST 5%、创业板改革、IPO 与除权参考价。"""
    out = _call_or_xfail(lambda: cli.stocks.limit_price_history("600519", n=60))
    rows = out.to_dict("records") if hasattr(out, "to_dict") else list(out)
    assert len(rows) >= 20, f"600519 近 60 日应返回足量行，实际 {len(rows)}"
    dates = [str(r["date"]) for r in rows]
    assert dates == sorted(dates), f"date 必须升序：{dates[:3]}…"
    for r in rows:
        if r["rule"] in {"main10", "main5", "gem10", "gem5",
                         "gem20", "star20", "bse30"}:
            assert float(r["limit_up"]) > float(r["limit_down"]) > 0

    # 主板 ST 5%：*ST天龙 2003-05-12/13 连续跌停（不是 10%）
    st = _call_or_xfail(lambda: cli.stocks.limit_price_history(
        "600234", begin="2003-05-12", end="2003-05-13"))
    st_rows = st.to_dict("records") if hasattr(st, "to_dict") else list(st)
    assert [r["rule"] for r in st_rows] == ["main5", "main5"]
    assert float(st_rows[0]["close"]) == float(st_rows[0]["limit_down"])
    assert float(st_rows[0]["low"]) == float(st_rows[0]["close"])

    # 主板 ST 制度切换：2026-05-06 起 5% → 10%（603021 ST华鹏/*ST华鹏）
    cut = _call_or_xfail(lambda: cli.stocks.limit_price_history(
        "603021", begin="2026-04-29", end="2026-05-08"))
    cut_rows = cut.to_dict("records") if hasattr(cut, "to_dict") else list(cut)
    pre = [r for r in cut_rows if str(r["date"]) < "2026-05-06"]
    post = [r for r in cut_rows if str(r["date"]) >= "2026-05-06"]
    assert pre and post, f"603021 应同时有 5/6 前后行：{cut_rows}"
    assert all(r["band"] == 0.05 and r["rule"] == "main5" for r in pre)
    assert all(r["band"] == 0.10 and r["rule"] == "main10" for r in post)

    # 创业板改革：2020-08-24 起 10% → 20%
    gem = _call_or_xfail(lambda: cli.stocks.limit_price_history(
        "300750", begin="2020-08-21", end="2020-08-24"))
    gem_rows = gem.to_dict("records") if hasattr(gem, "to_dict") else list(gem)
    assert [r["band"] for r in gem_rows] == [0.10, 0.20]
    assert float(gem_rows[-1]["basis"]) == 192.23

    # 科创板 IPO 前 5 个交易日无涨跌幅（rule=ipo，价格为空）
    ipo = _call_or_xfail(lambda: cli.stocks.limit_price_history(
        "688981", begin="2020-07-16", end="2020-07-24"))
    ipo_rows = ipo.to_dict("records") if hasattr(ipo, "to_dict") else list(ipo)
    assert [r["rule"] for r in ipo_rows[:5]] == ["ipo"] * 5
    assert all(r["limit_up"] is None or r["limit_up"] != r["limit_up"]
               for r in ipo_rows[:5])

    # 除权参考价：600519 2024-06-19 除息 30.876 元，前收 1490.62（非 1521.5）
    ex = _call_or_xfail(lambda: cli.stocks.limit_price_history(
        "600519", begin="2024-06-19", end="2024-06-19"))
    ex_rows = ex.to_dict("records") if hasattr(ex, "to_dict") else list(ex)
    assert len(ex_rows) == 1 and str(ex_rows[0]["date"]) == "2024-06-19"
    assert abs(float(ex_rows[0]["basis"]) - 1490.62) < 0.01
    assert float(ex_rows[0]["limit_up"]) == 1639.68


def test_holdernum_history_series(cli):
    """股东户数历史（raw 多期档）：日期升序、末期与快照同值、比例=小数。"""
    out = _call_or_xfail(lambda: cli.equity.query_holdernum_history("600519", 8))
    rows = out.to_dict("records") if hasattr(out, "to_dict") else out
    assert rows, "600519 应有股东户数历史"
    dates = [str(r["end_date"]) for r in rows]
    assert dates == sorted(dates), f"end_date 必须升序：{dates[:3]}…"
    assert len(set(dates)) == len(dates), "end_date 不得重复"
    last = rows[-1]
    assert int(last["holder_total_num"]) > 0
    assert 0 <= float(last["hold_ratio_total"]) <= 1, "比例必须已归一为小数"
    snap = _call_or_xfail(lambda: cli.equity.query_holdernum("600519"))
    assert snap is not None
    assert str(snap["end_date"])[:10] == str(last["end_date"])
    assert int(snap["holder_total_num"]) == int(last["holder_total_num"])


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
    """转债日线表：列转行后字段齐全、日期升序（2.0）、OHLC 关系成立、无缺失结构。"""
    rows = _call_or_xfail(cli.cbond.bars, "113050", n=5)
    if rows is None or len(rows) == 0:
        pytest.xfail("样本转债该窗口无数据")
    assert {"date", "open", "high", "low", "close"} <= set(rows.columns)
    dates = [str(d) for d in rows["date"]]
    assert dates == sorted(dates), "转债日线应按日期升序（2.0：旧→新）"
    for _, r in rows.iterrows():
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
    points = t3["data"]["points"]
    assert len(points) >= 500, f"宽基估值序列应覆盖 10 年（周频），实际 {len(points)} 点"
    dates = [str(d) for d in points["date"]]
    assert dates == sorted(dates), "points 必须升序（2.0：旧→新）"
    node = t3["data"]["pct"]["pe"]
    assert t3["data"]["pe_pct"] == pytest.approx(node["p3"]), \
        "3y 分位必须取 p3（服务端 p 恒为 5y，读 p 会静默错值）"
    t5 = _call_or_xfail(lambda: cli.index.trend("index.hs300", "5y"))
    assert t5["data"]["pe_pct"] == pytest.approx(t5["data"]["pct"]["pe"]["p5"])
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
    新鲜度门禁收紧为末根 ≥ 今天-5 自然日（容忍长周末），另锁结构与升序（2.0）。
    """
    us = Client.from_env(market="us")
    bars = _call_or_xfail(lambda: us.kline.bars("AAPL", n=5))
    assert len(bars) == 5
    assert {"date", "close", "volume"} <= set(bars.columns)
    dates = [str(d) for d in bars["date"]]
    assert dates == sorted(dates), "bars 应按日期升序（2.0：旧→新）"
    last = datetime.date.fromisoformat(dates[-1])
    assert last >= datetime.date.today() - datetime.timedelta(days=5), (
        f"美股日K末根 {dates[-1]} 落后超过 5 个自然日（调度已转正）"
    )


def test_us_kline_week_month_bars():
    """美股周/月 K（上游日线本地聚合派生）：结构 + 与日 K 的同日收盘一致性。

    周/月 bar 是日线的纯函数：日期=周期末交易日、open=首日开、close=末日收。
    末根新鲜度按周期给宽（周 ≤ 12 天、月 ≤ 45 天，容忍长周末与月结算）。
    """
    us = Client.from_env(market="us")
    weekly = _call_or_xfail(lambda: us.kline.bars("AAPL", n=5, freq="W"))
    monthly = _call_or_xfail(lambda: us.kline.bars("AAPL", n=3, freq="M"))
    assert len(weekly) == 5
    assert len(monthly) == 3
    for bars, span in ((weekly, 12), (monthly, 45)):
        dates = [str(d) for d in bars["date"]]
        assert dates == sorted(dates), "周期 K 应按日期升序（2.0：旧→新）"
        assert {"date", "open", "high", "low", "close", "volume"} <= set(bars.columns)
        assert all(bars["low"] <= bars[["open", "close"]].min(axis=1))
        assert all(bars["high"] >= bars[["open", "close"]].max(axis=1))
        last = datetime.date.fromisoformat(dates[-1])
        assert last >= datetime.date.today() - datetime.timedelta(days=span), (
            f"美股周期K末根 {dates[-1]} 落后超过 {span} 天（派生链未跑或滞后）"
        )
    # 同日一致性：周期末日的 close == 当日日 K 的 close（聚合规则 close=末日收）
    daily = _call_or_xfail(lambda: us.kline.bars("AAPL", n=60))
    close_by_date = dict(zip(daily["date"], daily["close"]))
    for _, w in weekly.iterrows():
        wdate = str(w["date"])
        if wdate in close_by_date:
            assert abs(float(w["close"]) - float(close_by_date[wdate])) < 1e-6, (
                f"周K {wdate} 收盘 {w['close']} ≠ 日K {close_by_date[wdate]}")


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


def test_v2_new_faces_smoke(cli):
    """2.0 P1/P2 新面 live 冒烟：calendar / margin 市场面 / futures。"""
    days = _call_or_xfail(lambda: cli.calendar.days("2026-01-01", "2026-03-31"))
    assert days is not None and len(days) > 0
    _call_or_xfail(lambda: cli.calendar.is_open("2026-01-05"))
    _call_or_xfail(lambda: cli.calendar.next("2026-01-30", 3))
    _call_or_xfail(lambda: cli.margin.market_summary(5))
    _call_or_xfail(lambda: cli.margin.universe(20))
    _call_or_xfail(lambda: cli.futures.get("RB.SHF", "close"))
    snap = _call_or_xfail(lambda: cli.futures.snapshot("RB.SHF"))
    assert snap is None or isinstance(snap, dict)
