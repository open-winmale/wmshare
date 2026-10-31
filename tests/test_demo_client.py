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
    assert "as_of=2026-10-30" in text


def test_packaged_surface(snapshot, cli):
    yield_value = snapshot["data"]["dividend"]["yield_ttm"]["600519"]
    pct_value = snapshot["data"]["indicators"]["$PCT_PE_TTM_10Y_LAST"]
    assert cli.dividend.yield_ttm("600519") == yield_value
    assert cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST") == pct_value
    codes = [row["symbol"] for row in cli.stocks.list()]
    assert codes == snapshot["data"]["universe"]
    result = cli.batch_all("kline.snapshot", codes)
    assert len(result.results) == 10 and result.requests == 1


def test_units_are_base(snapshot, cli):
    assert 0 <= cli.dividend.yield_ttm("600519") < 1
    assert cli.dividend.last("600519")["dps"] > 1
    mf = cli.moneyflow.last("600519")
    if mf is not None:
        assert mf["net_mf"] > 1
    bar = cli.kline.bars("600519", n=3)[0]
    assert 100 < bar["close"] < 10000 and bar["volume"] >= 0
    breadth = cli.screener.index_breadth_summary()
    assert breadth["up_pct"] >= 0
    assert -1 <= breadth["median_pct"] <= 1


def test_bars_are_date_descending_and_slice_real_rows(snapshot, cli):
    dates = [row["date"] for row in cli.kline.bars("600519", n=5)]
    assert dates == sorted(dates, reverse=True)
    expected = [row["date"] for row in snapshot["data"]["kline_bars"]["600519"][:5]]
    assert dates == expected
    with pytest.raises(UsageError, match="120"):
        cli.kline.bars("600519", n=121)


def test_snapshot_matches_latest_bar(snapshot, cli):
    for symbol in snapshot["data"]["universe"]:
        bars = cli.kline.bars(symbol, n=1)
        assert cli.kline.snapshot(symbol)["close"] == bars[0]["close"]


def test_unknown_symbol_is_rejected(cli):
    with pytest.raises(UsageError) as exc:
        cli.kline.snapshot("999999")
    assert exc.value.code == "demo_symbol"


def test_statements_shapes_match_real(snapshot, cli):
    for kind in ("income", "balance", "cashflow"):
        rows = getattr(cli.statements, kind)("600519", years=2)
        assert rows and all({"k", "cn", "vals"} <= set(row) for row in rows)
        for row in rows:
            assert set(row["vals"]).issubset(set(snapshot["data"]["statements"][kind][0]["vals"]))
    years = cli.statements.years("600519", "income")
    assert years == sorted(years, reverse=True)
    rows = cli.statements.compare("600519", "income", years=2)
    assert {"c", "p", "diff", "diffp", "k"} <= set(rows[0])
    diff_rows = [row for row in rows if row.get("diff")]
    assert diff_rows
    for row in diff_rows:
        for year, diff_value in row["diff"].items():
            if row["c"].get(year):
                expected = diff_value / row["c"][year]
                assert abs(row["diffp"][year] - expected) <= max(1e-9, abs(expected) * 1e-6)


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
    assert cli.call("not.covered") == []


def test_example_quality_thresholds_are_captured(snapshot, cli):
    for symbol in snapshot["data"]["universe"][:5]:
        value = cli.dividend.screen_quality(symbol, min_yield=0.02, payout_max=1.2)
        assert isinstance(value, bool)
