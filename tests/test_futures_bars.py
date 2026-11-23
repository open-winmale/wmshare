"""futures.bars 组合门面测试：eval 构造 / 收口升序 / 参数守卫（mock 传输，不联网）。"""
import pytest

import wmshare
from wmshare.api import _sas_to_iso
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import DataError, UsageError

# 月频 8 字段（$FUT_*_MONTH 族顺序，与 FuturesApi._FREQ_CODES["m"] 一致）
_M8 = {"$FUT_OPEN_MONTH": "open", "$FUT_HIGH_MONTH": "high",
       "$FUT_LOW_MONTH": "low", "$FUT_CLOSE_MONTH": "close",
       "$FUT_SETTLE_MONTH": "settle", "$FUT_VOLUME_MONTH": "volume",
       "$FUT_OI_MONTH": "open_interest", "$FUT_HAS_MONTH": "has_kline"}


class FakeSession:
    def __init__(self):
        self.calls = []
        self.eval_result = {"ok": True}

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
                        "data": {"result": self._cls.eval_result}}

        R._cls = self
        return R()


def _client(market="cn"):
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  market=market, catalog=load(), session=FakeSession())


def _payload(year=2026, n=3, width=8):
    months = [f"{year}:M{10 - i}" for i in range(n)]
    return {"sas": months,
            "vals": [[float(i + 1)] * width for i in range(n)]}


def _last_xs(cli: Client) -> list[str]:
    return [c for c in cli.session.calls
            if c["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


def test_bars_monthly_shape_ascending():
    cli = _client()
    cli.session.eval_result = _payload()
    df = cli.futures.bars("AL.SHF", n=3, freq="m")
    assert list(df["date"]) == ["2026-08-01", "2026-09-01", "2026-10-01"]  # 升序
    for col in ("open", "high", "low", "close", "settle", "volume",
                "open_interest", "has_kline", "sas", "date"):
        assert col in df.columns, col
    assert df["close"].tolist() == [3.0, 2.0, 1.0]  # cursor 新→旧 → 翻转后旧→新


def test_bars_default_daily_120_and_fields():
    cli = _client()
    cli.session.eval_result = _payload(width=11)
    cli.futures.bars("AL.SHF")
    xs = _last_xs(cli)
    assert xs[0] == 'pts := cursor.ds(120, "now")'
    assert "$FUT_CLOSE" in xs[1] and "$FUT_HAS" in xs[1]
    assert xs[2] == 'return {"sas": pts, "vals": vals}'
    body = [c for c in cli.session.calls if c["url"].endswith("/xs/eval")][-1]["json"]
    assert body["args"]["fut.symbol"] == "cn.AL.SHF"
    assert body["symbol"] == "600519"  # cn 默认锚点


def test_bars_month_cursor_fn():
    cli = _client()
    cli.session.eval_result = _payload()
    cli.futures.bars("RB.SHF", n=2, freq="m")
    assert 'cursor.ms(2, "now")' in _last_xs(cli)[0]
    cli.session.eval_result = _payload(width=8)
    cli.futures.bars("RB.SHF", n=2, freq="w")
    assert 'cursor.ws(2, "now")' in _last_xs(cli)[0]


def test_bars_begin_end_window_filter():
    cli = _client()
    cli.session.eval_result = _payload(n=3)
    cli.futures.bars("AL.SHF", begin="2026-09-01", end="2026-09-30", freq="m")
    xs = _last_xs(cli)
    assert "cursor.ms(" in xs[0]  # 按日期跨度反推点数取回后客户端过滤
    df = cli.futures.bars("AL.SHF", begin="2026-09-01", end="2026-09-30", freq="m")
    assert list(df["date"]) == ["2026-09-01"]


def test_bars_raw_escape():
    cli = _client()
    payload = _payload()
    cli.session.eval_result = payload
    out = cli.futures.bars("AL.SHF", n=3, freq="m", _raw=True)
    assert out == payload


def test_bars_field_projection():
    cli = _client()
    cli.session.eval_result = _payload()
    df = cli.futures.bars("AL.SHF", n=3, freq="m", fields=["date", "close"])
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
    with pytest.raises(UsageError, match="缺少交易所"):
        cli.futures.bars("600519")
    with pytest.raises(UsageError, match="cn 客户端"):
        cli_hk = _client(market="hk")
        cli_hk.futures.bars("AL.SHF")


def test_bars_malformed_upstream():
    cli = _client()
    cli.session.eval_result = {"foo": 1}
    with pytest.raises(DataError, match="形态异常"):
        cli.futures.bars("AL.SHF", n=3, freq="m")
    cli.session.eval_result = {"sas": ["2026:M10"], "vals": []}
    with pytest.raises(DataError, match="行数不一致"):
        cli.futures.bars("AL.SHF", n=3, freq="m")


def test_bars_begin_desc_rejected():
    cli = _client()
    with pytest.raises(UsageError, match="晚于"):
        cli.futures.bars("AL.SHF", begin="2026-02-01", end="2026-01-01")


def test_sas_to_iso():
    assert _sas_to_iso("2026:M10") == "2026-10-01"
    assert _sas_to_iso("2026:D326") == "2026-11-22"
    assert _sas_to_iso("2026:W48") == "2026-11-23"  # ISO 周 48 周一
    assert _sas_to_iso("2026-11-23") == "2026-11-23"  # 非 sas 原样
    assert _sas_to_iso("") == ""
    assert _sas_to_iso("2026:M13") == "2026:M13"  # 越界原样


def test_replay_bars_unsupported():
    from replay_client import replay_client
    with pytest.raises(UsageError, match="replay_unsupported|期货历史序列") as ei:
        replay_client().futures.bars("AL.SHF", n=6)
    assert ei.value.code == "replay_unsupported"
