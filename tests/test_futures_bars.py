"""futures 门面测试：store 直读归一化 / 周期起点 / 参数守卫（mock 传输，不联网）。"""
import pytest

from wmshare.api import FuturesApi, _iso_to_sas, _sas_to_iso
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import UsageError

_D_COLS = ["sas", "date", "open", "high", "low", "close", "settle",
           "pre_settle", "volume", "amount", "open_interest", "oi_chg",
           "has_kline"]
_WM_COLS = ["sas", "date", "open", "high", "low", "close", "settle",
            "volume", "open_interest", "has_kline"]


class FakeSession:
    def __init__(self):
        self.calls = []
        self.result = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})

        class R:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True,
                        "data": {"result": self._cls.result}}

        R._cls = self
        return R()


def _client(market="cn"):
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  market=market, catalog=load(), session=FakeSession())


def _row(day, close, **kw):
    row = {"date": day, "symbol": "cn.AL.SHF",
           "open": close - 10, "high": close + 10, "low": close - 20,
           "close": close, "settle": close - 5, "pre_settle": close - 15,
           "volume": 100000, "amount": 100000 * 5 * close,  # 元
           "oi": 200000, "oi_chg": 123, "percent": 0.001}
    row.update(kw)
    return row


def _xs(cli: Client) -> str:
    return [c for c in cli.session.calls
            if c["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"][0]


def test_bars_daily_normalization():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 21330), _row("2026-11-17", 22080),
                          _row("2026-11-18", 21550)]
    df = cli.futures.bars("AL.SHF", n=3)
    assert list(df.columns) == _D_COLS
    assert list(df["date"]) == ["2026-11-17", "2026-11-18", "2026-11-19"]  # 升序
    assert list(df["sas"]) == ["2026:D321", "2026:D322", "2026:D323"]
    assert df["open_interest"].tolist() == [200000, 200000, 200000]  # oi → 短名
    assert df["amount"].iloc[-1] == pytest.approx(100000 * 5 * 21330 / 1e4)  # 元→万元
    assert bool(df["has_kline"].all())
    assert "symbol" not in df.columns and "percent" not in df.columns


def test_bars_store_call_payload():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 21330)]
    cli.futures.bars("cn.AL.SHF", n=3)
    assert _xs(cli) == 'return futures.query_bars("AL.SHF", nil, nil, 3, "D")'
    cli.futures.bars("AL.SHF", n=2, freq="m")
    assert _xs(cli) == 'return futures.query_bars("AL.SHF", nil, nil, 2, "M")'
    cli.futures.bars("global.CL", n=2, freq="w")
    assert _xs(cli) == 'return futures.query_bars("GLOBAL.CL", nil, nil, 2, "W")'


def test_bars_weekly_monthly_period_start():
    cli = _client()
    cli.session.result = [_row("2026-11-20", 21330, amount=None)]
    df = cli.futures.bars("AL.SHF", n=1, freq="w")
    assert list(df.columns) == _WM_COLS
    assert list(df["date"]) == ["2026-11-16"]  # 周五 → ISO 周一
    assert list(df["sas"]) == ["2026:W47"]

    cli.session.result = [_row("2026-08-31", 24075), _row("2026-09-30", 23830),
                          _row("2026-10-30", 23395)]
    df = cli.futures.bars("AL.SHF", n=3, freq="m")
    assert list(df["date"]) == ["2026-08-01", "2026-09-01", "2026-10-01"]
    assert list(df["sas"]) == ["2026:M8", "2026:M9", "2026:M10"]
    assert list(df["volume"]) == [100000, 100000, 100000]  # 周期合计原样透传


def test_bars_begin_end_window_filter():
    cli = _client()
    cli.session.result = [_row("2026-08-31", 24075), _row("2026-09-30", 23830),
                          _row("2026-10-30", 23395)]
    df = cli.futures.bars("AL.SHF", begin="2026-09-01", end="2026-09-30", freq="m")
    assert list(df["date"]) == ["2026-09-01"]
    # store 的 end 是开区间 → 门面补一天再按周期起点过滤
    assert _xs(cli) == ('return futures.query_bars("AL.SHF", "2026-09-01", '
                        '"2026-10-01", nil, "M")')


def test_bars_raw_escape():
    cli = _client()
    cli.session.result = [_row("2026-11-17", 22080), _row("2026-11-19", 21330)]
    out = cli.futures.bars("AL.SHF", n=2, _raw=True)
    assert set(out) == {"sas", "vals"}
    assert out["sas"] == ["2026:D323", "2026:D321"]  # 新→旧（旧 cursor 顺序）
    assert len(out["vals"]) == 2 and len(out["vals"][0]) == 11
    close_idx = list(FuturesApi._FREQ_CODES["d"]).index("$FUT_CLOSE")
    assert out["vals"][0][close_idx] == 21330
    # 周/月原始形态 8 列
    cli.session.result = [_row("2026-10-30", 23395)]
    out_m = cli.futures.bars("AL.SHF", n=1, freq="m", _raw=True)
    assert out_m["sas"] == ["2026:M10"] and len(out_m["vals"][0]) == 8


def test_bars_field_projection():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 21330)]
    df = cli.futures.bars("AL.SHF", n=1, fields=["date", "close"])
    assert list(df.columns) == ["date", "close"]


def test_bars_param_guards():
    cli = _client()
    with pytest.raises(UsageError, match="二选一"):
        cli.futures.bars("AL.SHF", n=3, begin="2026-01-01", end="2026-02-01")
    with pytest.raises(UsageError, match="同时提供"):
        cli.futures.bars("AL.SHF", begin="2026-01-01")
    with pytest.raises(UsageError, match="不支持的 freq"):
        cli.futures.bars("AL.SHF", freq="h")
    with pytest.raises(UsageError, match="超上限"):
        cli.futures.bars("AL.SHF", n=3001)
    with pytest.raises(UsageError, match="超上限"):
        cli.futures.bars("AL.SHF", n=301, freq="m")
    with pytest.raises(UsageError, match="超上限"):
        cli.futures.bars("AL.SHF", begin="2010-01-01", end="2026-01-01")
    with pytest.raises(UsageError, match="缺少交易所"):
        cli.futures.bars("600519")
    with pytest.raises(UsageError, match="cn 客户端"):
        cli_hk = _client(market="hk")
        cli_hk.futures.bars("AL.SHF")


def test_bars_begin_desc_rejected():
    cli = _client()
    with pytest.raises(UsageError, match="晚于"):
        cli.futures.bars("AL.SHF", begin="2026-02-01", end="2026-01-01")


def test_snapshot_daily_fields_and_date():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 21330)]
    snap = cli.futures.snapshot("AL.SHF")
    assert snap["date"] == "2026-11-19"
    assert snap["close"] == 21330 and snap["open_interest"] == 200000
    assert snap["amount"] == pytest.approx(100000 * 5 * 21330 / 1e4)
    assert "sas" not in snap  # 快照只追加 date，不加 sas
    assert len(snap) == 12  # 11 字段 + date
    assert _xs(cli) == 'return futures.query_bars("AL.SHF", nil, nil, 1, "D")'


def test_snapshot_weekly_and_empty():
    cli = _client()
    cli.session.result = [_row("2026-11-20", 21330)]
    snap = cli.futures.snapshot("AL.SHF", freq="w")
    assert snap["date"] == "2026-11-16" and snap["close"] == 21330
    assert len(snap) == 9  # 8 字段 + date

    cli.session.result = []
    empty = cli.futures.snapshot("AL.SHF")
    assert empty["date"] is None and all(v is None for k, v in empty.items())


def test_snapshot_invalid_freq():
    cli = _client()
    with pytest.raises(UsageError, match="不支持的 freq"):
        cli.futures.snapshot("AL.SHF", freq="h")
    with pytest.raises(UsageError, match="不支持的 freq"):
        cli.futures.get("AL.SHF", "close", freq="h")


def test_get_field_and_dollar_code():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 21330)]
    assert cli.futures.get("AL.SHF", "close") == 21330
    assert cli.futures.get("AL.SHF", "$FUT_CLOSE") == 21330
    assert cli.futures.get("AL.SHF", "$FUT_CLOSE_WEEK") == 21330  # 按码后缀切周期
    assert cli.futures.get("global.CL", "close") == 21330
    with pytest.raises(UsageError, match="未知字段"):
        cli.futures.get("AL.SHF", "nope")
    with pytest.raises(UsageError, match="未知期货指标"):
        cli.futures.get("AL.SHF", "$NOPE")


def test_normalize_global_prefix():
    cli = _client()
    cli.session.result = [_row("2026-11-19", 83.16)]
    for form in ("global.CL", "GLOBAL.CL", "global.cl"):
        assert cli.futures.get(form, "close") == 83.16
        assert '"GLOBAL.CL"' in _xs(cli)
    with pytest.raises(UsageError, match="不合法"):
        cli.futures.get("global.crude.oil", "close")


def test_iso_to_sas_roundtrip():
    assert _iso_to_sas("d", __import__("datetime").date(2026, 11, 22)) == "2026:D326"
    assert _iso_to_sas("w", __import__("datetime").date(2026, 11, 23)) == "2026:W48"
    assert _iso_to_sas("m", __import__("datetime").date(2026, 9, 1)) == "2026:M9"
    for sas in ("2026:D326", "2026:W48", "2026:M10"):
        assert _iso_to_sas(
            {"D": "d", "W": "w", "M": "m"}[sas.split(":")[1][0]],
            __import__("datetime").date.fromisoformat(_sas_to_iso(sas))) == sas


def test_replay_bars_unsupported():
    from replay_client import replay_client
    with pytest.raises(UsageError, match="replay_unsupported|期货历史序列") as ei:
        replay_client().futures.bars("AL.SHF", n=6)
    assert ei.value.code == "replay_unsupported"
