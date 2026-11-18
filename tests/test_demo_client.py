"""演示客户端门禁：真实快照回放、单位、轮询语义和演示宇宙边界。"""
from __future__ import annotations

import pytest

import wmshare
from wmshare._demo import DemoPoller, load_demo_snapshot
from wmshare.errors import UsageError
from wmshare.notice_stream import NoticeStreamEvent


@pytest.fixture(scope="module")
def snapshot():
    return load_demo_snapshot()


@pytest.fixture(scope="module")
def cli():
    return wmshare.demo_client()


def test_repr_marks_demo_data():
    text = repr(wmshare.demo_client())
    assert "演示" in text and "非实时行情" in text
    from wmshare._demo import SNAPSHOT_AS_OF

    assert f"as_of={SNAPSHOT_AS_OF}" in text


def test_packaged_surface(snapshot, cli):
    yield_value = snapshot["data"]["dividend"]["yield_ttm"]["600519"]
    pct_value = snapshot["data"]["indicators"]["$PCT_PE_TTM_10Y_LAST"]
    assert cli.dividend.yield_ttm("600519") == yield_value
    assert cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST") == pct_value
    codes = list(cli.stocks.list()["symbol"])
    assert codes == snapshot["data"]["universe"]
    result = cli.batch_all("kline.snapshot", codes)
    assert len(result.results) == 10 and result.requests == 1


def test_units_are_base(snapshot, cli):
    assert 0 <= cli.dividend.yield_ttm("600519") < 1
    # dps=元/股：上游「最近一条」可能是零派息的期中记录（2026-06-30 中期 0），
    # 单位口径看历史里的最大 dps——若退化成「分」或「元/10股」，这个数会相差 10~100 倍。
    hist = cli.dividend.history("600519", limit=20)
    assert float(hist["dps"].max()) > 1
    mf = cli.moneyflow.last("600519")
    if mf is not None:
        assert mf["net_mf"] > 1
    bars = cli.kline.bars("600519", n=3)
    assert 100 < float(bars.iloc[-1]["close"]) < 10000 and bars.iloc[-1]["volume"] >= 0
    breadth = cli.screener.index_breadth_summary()
    assert breadth["up_pct"] >= 0
    assert -1 <= breadth["median_pct"] <= 1


def test_bars_are_date_ascending_and_slice_real_rows(snapshot, cli):
    """2.0 方向契约：demo 与 live 同为升序（旧→新），切片取快照最新 5 根。"""
    dates = list(cli.kline.bars("600519", n=5)["date"])
    assert dates == sorted(dates)
    expected = [row["date"] for row in snapshot["data"]["kline_bars"]["600519"][-5:]]
    assert expected == dates
    with pytest.raises(UsageError, match="120"):
        cli.kline.bars("600519", n=121)


def test_screener_query_needs_live_client(cli):
    """全市场条件选股依赖服务端索引列：快照只有 10 只票，显式 unsupported 而非假筛选。"""
    with pytest.raises(UsageError) as err:
        cli.screener.query("$ROE_TTM_LAST > 0.15")
    assert err.value.code == "demo_unsupported"


def test_backtest_runs_on_demo_bars(cli):
    """回测在演示数据上真跑（120 根不复权日 K），口径标注 demo 而非伪造。"""
    res = cli.backtest.run("600519", fast=5, slow=20)
    assert res["period"]["bars"] == 120
    assert res["caliber"]["demo"] is True and res["caliber"]["adj"] is None
    assert isinstance(res["trades"], list) and isinstance(res["equity"], list)
    assert any("演示快照" in w for w in res["warnings"])
    with pytest.raises(UsageError) as err:
        cli.backtest.run("600519", adj="hfq")
    assert err.value.code == "demo_unsupported"


def test_backtest_pe_runs_on_demo_snapshot(cli):
    """演示快照带 pe/3y 估值序列：PE 规则可跑，阈值必然命中时出买点。"""
    res = cli.backtest.run("600519", rule="pe", buy=1e6, sell=1e7)
    assert res["caliber"]["valuation"] == {"metric": "pe", "window": "3y"}
    assert res["rule"] == "pe(buy=1e+06, sell=1e+07)"
    assert res["trades"][0]["side"] == "buy" and res["trades"][0]["reason"] == "买点"
    quiet = cli.backtest.run("600519", rule="pe", buy=1.0, sell=2.0)
    assert quiet["trades"] == []
    with pytest.raises(UsageError) as err:
        cli.backtest.run("600519", rule="pb", buy=1.0, sell=2.0)
    assert err.value.code == "demo_unsupported"


def test_snapshot_matches_latest_bar(snapshot, cli):
    """快照为拍摄日盘中价，日 K 结算到上一交易日——同量级（±20%）即同标的同单位。

    精确相等只在收盘后拍摄成立；盘中拍摄必然偏离（2026-11-17 快照：快照 1439.55
    vs 11-16 收盘 1453.9）。这条测试守的是「单位/标的没串」，不是「价格相同」。
    """
    for symbol in snapshot["data"]["universe"]:
        bars = cli.kline.bars(symbol, n=1)
        snap_close = float(cli.kline.snapshot(symbol)["close"])
        bar_close = float(bars.iloc[-1]["close"])
        assert abs(snap_close / bar_close - 1) < 0.20, symbol


def test_unknown_symbol_is_rejected(cli):
    with pytest.raises(UsageError) as exc:
        cli.kline.snapshot("999999")
    assert exc.value.code == "demo_symbol"


def test_statements_shapes_match_real(snapshot, cli):
    for kind in ("income", "balance", "cashflow"):
        rows = getattr(cli.statements, kind)("600519", years=2).to_dict("records")
        assert rows and all({"k", "cn", "vals"} <= set(row) for row in rows)
        for row in rows:
            assert set(row["vals"]).issubset(set(snapshot["data"]["statements"][kind][0]["vals"]))


def test_notice_poller_ack_semantics(snapshot, cli):
    seen: list[list[NoticeStreamEvent]] = []
    poller = cli.notice_poller(group="demo", consumer="w1", on_events=seen.append)
    first = poller.poll_now()
    event = snapshot["data"]["notice_event"]
    assert len(first) == 1 and isinstance(first[0], NoticeStreamEvent)
    assert first[0].seq == event["seq"]
    assert first[0].title == event["title"]
    assert seen and seen[0] == first
    assert poller.poll_now() == []


def test_demo_poller_running_is_property_and_context_works(snapshot):
    poller = DemoPoller(snapshot["data"]["notice_event"])
    assert isinstance(type(poller).running, property)
    assert poller.running is False
    with poller:
        pass


def test_demo_client_context_works():
    with wmshare.demo_client() as cli:
        assert cli.kline.snapshot("600519")["close"] > 0


def test_batch_entries_and_call(snapshot, cli):
    expected_yield = snapshot["data"]["dividend"]["yield_ttm"]["600519"]
    batch = cli.call_batch("bonus.snapshot_yield_ttm", ["600519"])
    assert batch.results["600519"] == expected_yield and batch.requests == 1
    assert cli.batch_iter("kline.snapshot", ["600519", "000001"]).__next__().requests == 1
    assert len(cli.call("kline.query_bars", sym="600519", limit=5)) == 5
    assert cli.call("kline.snapshot", sym="600519")["close"] > 0
    # S3：未回放函数不再返回 []（会被 Agent 误读成「调用成功、结果为空」）。
    with pytest.raises(UsageError) as err:
        cli.call("not.covered")
    assert err.value.code == "demo_unsupported"


def test_example_quality_thresholds_are_captured(snapshot, cli):
    for symbol in snapshot["data"]["universe"][:5]:
        value = cli.dividend.screen_quality(symbol, min_yield=0.02, payout_max=1.2)
        assert isinstance(value, bool)


def test_moneyflow_board_is_sorted_desc_and_covers_universe(snapshot, cli):
    rows = cli.moneyflow.board()  # 2.0：DataFrame（按主力净流入降序）
    assert len(rows) == len(snapshot["data"]["moneyflow_last"])
    net = list(rows["net_mf"])
    assert net == sorted(net, reverse=True)
    row = rows.iloc[0].to_dict()  # Series 直接 set 会迭代值；转 dict 取键
    assert {"symbol", "name", "net_mf", "net_mv_ratio", "lg_net", "elg_net",
            "md_net", "sm_net", "industry"} <= set(row)


def test_kline_last_is_bar_not_snapshot(cli):
    """live `kline.last` 返回单根 bar（9 字段），不是 23 字段快照。

    demo 曾把 `last` 直接指向 `_kline_snapshot`，示例里 `last()["date"]` 能过、
    但字段集与 live 不同（多出 ma/mv/is_st 等），教出错误的用法。
    """
    bar = cli.kline.last("600519")
    assert sorted(bar) == ["amount", "close", "date", "high", "low", "open",
                           "percent", "sas", "volume"]
    assert bar["close"] == float(cli.kline.bars("600519", n=1).iloc[-1]["close"])
    assert len(cli.kline.snapshot("600519")) > len(bar)
