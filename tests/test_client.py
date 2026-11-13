"""客户端契约测试（mock 传输，不联网）。

FakeSession 复现 OpenAPI 合同：
  POST /v1/oauth/token      → {"data": {"access_token": ..., "expires_in": ...}}
  POST /v1/analysis/xs/eval → {"success": true, "data": {"result": ...}}
"""
import json
import threading

import pytest

from wmshare.catalog import load
from wmshare.client import Client, WmshareError, _xs_literal
from wmshare.client import LimitError
from wmshare.errors import ApiError, UsageError


class FakeSession:
    def __init__(self):
        self.calls = []          # (url, json_body_or_none, form_or_none, headers)
        self.token_count = 0
        self.eval_result = {"ok": True}

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data, "headers": headers})
        class R:
            status_code = 200
            text = "{}"
            def raise_for_status(self):
                pass
            def json(self):
                if url.endswith("/v1/oauth/token"):
                    self._cls.token_count += 1
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True, "data": {"result": self._cls.eval_result}}
        R._cls = self
        return R()


@pytest.fixture()
def client():
    s = FakeSession()
    return Client(base_url="https://test-api.winmale.com",
                  client_id="id", client_secret="sec",
                  catalog=load(), session=s, market="cn")


def last_eval(c: Client):
    return [x for x in c.session.calls if x["url"].endswith("/v1/analysis/xs/eval")][-1]


def test_xs_literal():
    assert _xs_literal("600519") == '"600519"'
    assert _xs_literal(30) == "30"
    assert _xs_literal(True) == "true"
    assert _xs_literal(["close"]) == '["close"]'
    assert _xs_literal({"scope": "合并"}) == '{"scope": "合并"}'
    # XS 空值是 nil，不是 JSON 的 null（否则服务端报 undefined variable "null"）
    assert _xs_literal(None) == "nil"
    assert _xs_literal({"a": None, "b": [1, None]}) == '{"a": nil, "b": [1, nil]}'


def test_call_builds_xs_and_body(client):
    out = client.call("kline.query_bars", sym="600519", limit=30)
    assert out == {"ok": True}
    ev = last_eval(client)
    assert ev["json"]["xs_lines"] == [
        '__r := kline.query_bars("600519", 30)',
        "return kline.fmt_maps(__r)",
    ]
    assert ev["json"]["mode"] == "call"
    assert ev["json"]["symbol"] == "600519"
    assert ev["json"]["market"] == "cn"
    assert ev["json"]["args"]["print.plain"] is True
    assert ev["json"]["script_files"] == {}
    assert ev["headers"]["Authorization"] == "Bearer tok-1"


def test_raw_bypasses_normalizer(client):
    client.call("kline.query_bars", sym="600519", _raw=True)
    assert last_eval(client)["json"]["xs_lines"] == ['return kline.query_bars("600519", 120)']


def test_default_fills_positional(client):
    client.call("kline.query_bars", sym="000807")
    assert last_eval(client)["json"]["xs_lines"] == [
        '__r := kline.query_bars("000807", 120)',
        "return kline.fmt_maps(__r)",
    ]


def test_missing_middle_param_fills_nil(client):
    """中段可选参数未传时必须补 nil 保位：调用字面量按位置绑定，跳洞会把后值错绑到前槽
    （实证：screen_quality(sym, payout_max=1.5) 曾生成 (sym, 1.5)，1.5 错进 payout_min）。"""
    client.call("bonus.screen_quality", sym="600519", min_yield=0.02, payout_max=1.5)
    lines = last_eval(client)["json"]["xs_lines"]
    assert 'return bonus.screen_quality("600519", 0.02, nil, 1.5)' in lines
    # 尾部未传仍按省略处理，不补尾 nil
    client.call("bonus.screen_quality", sym="600519", min_yield=0.02)
    lines = last_eval(client)["json"]["xs_lines"]
    assert 'return bonus.screen_quality("600519", 0.02)' in lines


def test_auto_require_for_unpreloaded_ns(client):
    client.call("rptdom.statement_years", sym="600519", domain="fin.income_statement")
    lines = last_eval(client)["json"]["xs_lines"]
    assert lines[0] == 'xs.require("sys/rptdom/init.xs")'
    assert lines[-1] == ('return rptdom.statement_years("600519", "fin.income_statement")')
    # 预载域不补 require
    client.call("kline.query_last", sym="600519")
    lines = last_eval(client)["json"]["xs_lines"]
    assert not any(l.startswith("xs.require") for l in lines)


def test_param_validation(client):
    with pytest.raises(WmshareError, match="未知参数"):
        client.call("kline.query_bars", sym="600519", n=10)
    with pytest.raises(WmshareError, match="必填参数 sym"):
        client.call("moneyflow.query_bars", limit=5)
    with pytest.raises(KeyError, match="未知函数"):
        client.call("kline.no_such_fn", sym="600519")
    with pytest.raises(WmshareError, match="需要 int"):
        client.call("kline.query_bars", sym="600519", limit="30")
    with pytest.raises(WmshareError, match="不在允许值"):
        client.call("rptdom.statement", sym="600519", domain="not.a.statement")


def test_batch_name_must_be_catalog_function(client):
    """指标码不是批量入口的 name：报错里给出一票多码的正确路径。"""
    with pytest.raises(WmshareError, match="指标码不是函数名") as ei:
        client.call_batch("indicator.get", ["600519"])
    assert "cli.indicator.metrics" in str(ei.value)
    with pytest.raises(WmshareError, match="指标码不是函数名"):
        client.call("indicator.get", sym="600519")


def test_max_limit_caps_limit_params(client):
    with pytest.raises(WmshareError, match="超过单次请求上限 500"):
        client.call("kline.query_bars", sym="600519", limit=501)
    client.call("kline.query_bars", sym="600519", limit=500)  # 上限值本身放行
    c2 = Client(base_url="https://t", client_id="i", client_secret="s",
                catalog=load(), session=FakeSession(), max_limit=None)
    c2.call("kline.query_bars", sym="600519", limit=5000)  # None 关闭上限


# ---- 凭证解析：SDK 不再内置体验 AppID，缺凭证必须在构造期报错并给指引 ----

def test_client_without_credentials_rejected():
    with pytest.raises(WmshareError, match="缺少凭证") as ei:
        Client(base_url="https://t", catalog=load(), session=FakeSession())
    assert ei.value.code == "config"
    assert "open.winmale.com" in str(ei.value)
    # 报错即引导：零凭证离线演示入口必须随错误给出（同 README 首屏口径）
    assert "wmshare.demo_client()" in str(ei.value)


def test_missing_credentials_mention_legacy_finpipe(monkeypatch, tmp_path):
    """更名迁移指引：检测到旧 finpipe 配置残留时，缺凭证报错附迁移提示（只指路不映射）。"""
    monkeypatch.setenv("FINPIPE_CLIENT_ID", "old-id")
    monkeypatch.delenv("FINPIPE_CLIENT_SECRET", raising=False)
    with pytest.raises(WmshareError, match="缺少凭证") as ei:
        Client(base_url="https://t", catalog=load(), session=FakeSession())
    assert "FINPIPE_CLIENT_ID" in str(ei.value) and "迁移" in str(ei.value)

    monkeypatch.delenv("FINPIPE_CLIENT_ID", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))      # 无 ~/.finpipe/ 残留
    with pytest.raises(WmshareError, match="缺少凭证") as ei2:
        Client(base_url="https://t", catalog=load(), session=FakeSession())
    assert "迁移" not in str(ei2.value)


def test_dir_exposes_all_namespaces():
    """dir(cli) 必须可见友好门面与底层目录命名空间（IDE 补全可达）。"""
    cli = Client(base_url="https://t", client_id="cid", client_secret="sec",
                 catalog=load(), session=FakeSession())
    names = set(dir(cli))
    assert {"dividend", "kline", "screener", "call", "call_batch"} <= names
    assert {"bonus", "rptdom"} <= names            # 底层目录命名空间


def test_partial_credentials_rejected():
    with pytest.raises(WmshareError, match="成对"):
        Client(base_url="https://t", client_id="only-id",
               catalog=load(), session=FakeSession())
    with pytest.raises(WmshareError, match="成对"):
        Client(base_url="https://t", client_secret="only-sec",
               catalog=load(), session=FakeSession())


@pytest.mark.parametrize("kwargs,match", [
    ({"market": "jp"}, "market 只支持"),
    ({"base_url": "http://api.example.com"}, "HTTPS"),
    ({"base_url": "not-a-url"}, "HTTPS"),
    ({"timeout": 0}, "timeout"),
    ({"timeout": -1}, "timeout"),
    ({"retries": -1}, "retries"),
    ({"backoff": -1}, "backoff"),
    ({"max_limit": 0}, "max_limit"),
])
def test_client_options_fail_fast(kwargs, match):
    options = {"client_id": "id", "client_secret": "sec", "base_url": "https://t"}
    options.update(kwargs)
    with pytest.raises(UsageError, match=match):
        Client(**options)


def test_client_accepts_default_market_and_local_http_base_url():
    local = Client(base_url="http://localhost:8080", client_id="id",
                   client_secret="sec", catalog=load())
    assert local.base_url == "http://localhost:8080"
    assert local.market == "cn"


def test_from_env_prefers_explicit_env():
    c = Client.from_env(env={"WMSHARE_CLIENT_ID": "id-1", "WMSHARE_CLIENT_SECRET": "sec-1"},
                        base_url="https://t", catalog=load(), session=FakeSession())
    assert (c.client_id, c.client_secret) == ("id-1", "sec-1")


def test_from_env_partial_raises(tmp_path):
    # WMSHARE_CREDENTIALS 指向不存在文件：隔离本机 ~/.wmshare/credentials.env
    with pytest.raises(WmshareError, match="成对"):
        Client.from_env(env={"WMSHARE_CLIENT_ID": "id-1",
                             "WMSHARE_CREDENTIALS": str(tmp_path / "absent.env")},
                        base_url="https://t", catalog=load(), session=FakeSession())


def test_from_env_open_platform_fallback(tmp_path):
    c = Client.from_env(env={"OPEN_PLATFORM_CLIENT_ID": "pid",
                             "OPEN_PLATFORM_CLIENT_SECRET": "psec",
                             "WMSHARE_CREDENTIALS": str(tmp_path / "absent.env")},
                        base_url="https://t", catalog=load(), session=FakeSession())
    assert c.client_id == "pid"


def test_from_env_empty_raises_with_guidance(tmp_path):
    # 隔离本机凭证文件（维护者/用户可能已配置 ~/.wmshare/credentials.env），
    # 确保测的是「无任何配置 → 构造期报错并附申请指引」这条路径
    with pytest.raises(WmshareError, match="缺少凭证"):
        Client.from_env(env={"WMSHARE_CREDENTIALS": str(tmp_path / "absent.env")},
                        base_url="https://t", catalog=load(), session=FakeSession())


def test_object_param_serialized(client):
    client.call("rptdom.statement", sym="600519", domain="fin.income_statement",
                opts={"scope": "合并", "n": 5})
    xs = last_eval(client)["json"]["xs_lines"][-1]
    assert xs == ('return rptdom.statement("600519", "fin.income_statement", '
                  '{"scope": "合并", "n": 5})')


def test_namespace_facade(client):
    # 通用门面（非友好命名空间）：rptdom 仍走底层函数直调
    out = client.rptdom.statement_years(sym="600519", domain="fin.income_statement")
    assert out == {"ok": True}
    xs = last_eval(client)["json"]["xs_lines"]
    assert xs[0] == 'xs.require("sys/rptdom/init.xs")'
    assert xs[-1] == 'return rptdom.statement_years("600519", "fin.income_statement")'
    with pytest.raises(AttributeError, match="不在目录中"):
        client.no_such_ns.query(sym="1")
    # L1 精简条目：回退 inventory 签名参数，可直接调用
    client.call("kline.fmt_snapshot_line", sym="600519")
    assert last_eval(client)["json"]["xs_lines"] == ['return kline.fmt_snapshot_line("600519")']
    with pytest.raises(WmshareError, match="未知参数"):
        client.call("kline.fmt_snapshot_line", code="600519")


def test_inventory_min_args_optional(client):
    # kline.query_bars_adj(sym, limit, adj) xs:catalog min_args=2 → adj 可选
    client.call("kline.query_bars_adj", sym="600519", limit=10)
    assert last_eval(client)["json"]["xs_lines"] == [
        '__r := kline.query_bars_adj("600519", 10)',
        "return kline.fmt_maps(__r)"]  # 复权序列走规范化，字段与不复权一致
    with pytest.raises(WmshareError, match="必填参数 limit"):
        client.call("kline.query_bars_adj", sym="600519")


def test_dataframe_option(client):
    pytest.importorskip("pandas")
    client.session.eval_result = [{"date": "2026-10-21", "close": 1309.69}]
    df = client.call("kline.query_bars", sym="600519", limit=1, _df=True)
    assert list(df.columns) == ["date", "close"] and len(df) == 1


def test_token_cached(client):
    client.call("kline.query_last", sym="600519")
    client.call("kline.query_last", sym="000807")
    assert client.session.token_count == 1


def test_concurrent_clients_share_one_token_refresh():
    started = threading.Event()
    release = threading.Event()

    class SlowTokenSession(FakeSession):
        def post(self, url, json=None, data=None, headers=None, timeout=None):
            response = super().post(url, json=json, data=data, headers=headers,
                                    timeout=timeout)
            if url.endswith("/v1/oauth/token"):
                started.set()
                assert release.wait(1)
            return response

    session = SlowTokenSession()
    client = Client(base_url="https://t", client_id="id", client_secret="sec",
                    catalog=load(), session=session)
    threads = [threading.Thread(target=client.eval_result,
                                args=("return $PE_TTM_LAST",))
               for _ in range(2)]
    threads[0].start()
    assert started.wait(1)
    threads[1].start()
    release.set()
    for thread in threads:
        thread.join(1)
    assert session.token_count == 1
    assert len([call for call in session.calls
                if call["url"].endswith("/xs/eval")]) == 2


def test_eval_error_surfaced(client):
    class FailSession(FakeSession):
        def post(self, url, **kw):
            if url.endswith("/xs/eval"):
                class R:
                    status_code = 200
                    text = "{}"
                    def json(self):
                        return {"success": False,
                                "error": {"code": "XS_EVAL", "message": "undefined: foo"}}
                return R()
            return super().post(url, **kw)
    c2 = Client(base_url="https://t", client_id="i", client_secret="s",
                catalog=load(), session=FailSession())
    with pytest.raises(WmshareError, match="undefined: foo"):
        c2.call("kline.query_bars", sym="600519")


# ---- v1.9.0 批量与 stocks -----------------------------------------------

def test_batch_live_caps_symbols(client):
    from wmshare.errors import LimitError
    client.max_limit = 500
    with pytest.raises(LimitError, match="超过上限 500"):
        client.kline.batch_live([f"{600000 + i:06d}" for i in range(501)])
    client.session.eval_result = {}
    client.kline.batch_live(["600000", "000001"])
    assert last_eval(client)["json"]["xs_lines"][-1].startswith(
        "return kline.query_last_live_many")


def test_call_routes_list_symbol_to_batch(client):
    client.session.eval_result = {"600519": [{"close": 1.0}], "000001": [{"close": 2.0}]}
    out = client.kline.last(["600519", "000001"])
    line = last_eval(client)["json"]["xs_lines"][-1]
    assert line.startswith(
        'return {"600519": kline.fmt_maps(kline.query_bars("600519", 1))')
    assert out.results == {"600519": {"close": 1.0}, "000001": {"close": 2.0}}
    assert out.errors == {}


def test_call_list_over_limit_raises(client):
    from wmshare.errors import LimitError
    client.max_limit = 500
    with pytest.raises(LimitError):
        client.kline.last([f"{600000 + i:06d}" for i in range(501)])


def test_batch_result_to_df_long_table(client):
    pd = pytest.importorskip("pandas")
    client.session.eval_result = {
        "600519": {"close": 10.5, "percent": 0.01},
        "000001": {"close": 9.9, "percent": -0.01},
    }
    out = client.call_batch("kline.snapshot", ["600519", "000001"])
    df = out.to_df()
    assert isinstance(df, pd.DataFrame)
    assert list(df["symbol"]) == ["600519", "000001"]
    assert {"symbol", "close", "percent"} <= set(df.columns)


def test_batch_result_tracks_requested_and_detects_missing_keys(client):
    client.session.eval_result = {
        "600519": {"close": 1}, "000001": {"close": 2},
    }
    out = client.call_batch("kline.snapshot", ["600519", "000001"])
    assert out.requested == 2
    client.session.eval_result = {"600519": {"close": 1}}
    with pytest.raises(WmshareError, match="批量返回缺少"):
        client.call_batch("kline.snapshot", ["600519", "000001"])


def test_batch_iter_skip_records_structured_error(client, monkeypatch):
    calls: list[list[str]] = []

    def fail_batch(name, symbols, /, **_kwargs):
        calls.append(list(symbols))
        raise ApiError("isolated failure", code="isolated", status=400)

    monkeypatch.setattr(client, "call_batch", fail_batch)
    parts = list(client.batch_iter("kline.snapshot", ["600519", "000001"],
                                   batch_size=1, on_batch_error="skip"))
    assert len(parts) == 2 and calls == [["600519"], ["000001"]]
    assert all(part.requested == 1 and part.requests == 1 for part in parts)
    keys = ["batch#1[0:1]", "batch#2[1:2]"]
    assert all(part.error_details[key].code == "isolated"
               and not part.error_details[key].retryable
               for part, key in zip(parts, keys))


def test_us_symbol_suffix_canonicalized_everywhere():
    """美股交易所后缀/类别股写法在 eval 锚点、目录调用、批量三处都归一。"""
    s = FakeSession()
    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=s, market="us")
    c.eval_result("return $PE_TTM_LAST", symbol="AAPL.O")
    assert last_eval(c)["json"]["symbol"] == "AAPL"
    c.call("kline.query_bars", sym="BRK.B", limit=1)
    ev = last_eval(c)
    assert ev["json"]["symbol"] == "BRK_B"
    assert any('kline.query_bars("BRK_B", 1)' in ln for ln in ev["json"]["xs_lines"])
    c.session.eval_result = {"AAPL": {"close": 1}, "BRK_B": {"close": 2}}
    c.call_batch("kline.snapshot", ["AAPL.O", "BRK-B"])
    xs = "\n".join(last_eval(c)["json"]["xs_lines"])
    assert '"AAPL"' in xs and '"BRK_B"' in xs and "AAPL.O" not in xs and "BRK-B" not in xs


def test_eval_default_anchor_follows_market():
    s = FakeSession()
    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=s, market="hk")
    c.eval_result("return 1")
    assert last_eval(c)["json"]["symbol"] == "00700"
    s2 = FakeSession()
    c2 = Client(base_url="https://t", client_id="i", client_secret="s",
                catalog=load(), session=s2, market="us")
    c2.eval_result("return 1")
    assert last_eval(c2)["json"]["symbol"] == "AAPL"


def test_stocks_list_routes_with_require(client):
    client.session.eval_result = [{"symbol": "600519", "name": "贵州茅台"}]
    rows = client.stocks.list()
    assert rows and rows[0]["symbol"] == "600519"
    lines = last_eval(client)["json"]["xs_lines"]
    assert any("stocks.query_list()" in ln for ln in lines)
    assert any('xs.require("sys/stocks/init.xs")' in ln for ln in lines)


def test_stocks_industry_members_and_fuzzy(client):
    client.session.eval_result = [{"symbol": "600519", "name": "贵州茅台"}]
    rows = client.stocks.industry_members("S48", top_n=1)
    assert rows == [{"symbol": "600519", "name": "贵州茅台"}]
    assert last_eval(client)["json"]["xs_lines"][-1] == \
        'return stocks.industry_members("S48")'


def test_stocks_industry_fuzzy_candidates(client):
    # 中文名解析走目录模糊匹配：唯一命中直用；多候选/未命中报错列候选
    client.session.eval_result = [
        {"symbol": "S48", "name": "银行", "level": 1},
        {"symbol": "S4801", "name": "银行二级", "level": 2},
    ]
    with pytest.raises(Exception, match="命中 2 个行业"):
        client.stocks._resolve_industry("银行")
    client.session.eval_result = [{"symbol": "S48", "name": "银行", "level": 1}]
    assert client.stocks._resolve_industry("银行") == "industry.S48"
    client.session.eval_result = []
    with pytest.raises(Exception, match="未找到行业"):
        client.stocks._resolve_industry("不存在的行业")


def test_symbol_alias_lands_on_real_param_name(client):
    """目录里标的参数叫法不统一（sym/stk/code），symbol= 应自动落到真实名。"""
    client.session.eval_result = []
    client.call("cbond.of_stock", symbol="601009")
    assert last_eval(client)["json"]["xs_lines"][-1] == 'return cbond.of_stock("601009")'

    client.call("cbond.call_hits", symbol="603129", trig=314.21)
    assert (last_eval(client)["json"]["xs_lines"][-1]
            == 'return cbond.call_hits("603129", 314.21)')

    client.call("cbond.query", symbol="113615")
    assert last_eval(client)["json"]["xs_lines"][-1] == 'return cbond.query("113615")'


def test_symbol_alias_does_not_override_explicit_real_name(client):
    """真实名已传时别名不动它；同时传两个别名视为歧义，交给常规校验报错。"""
    client.session.eval_result = []
    client.call("cbond.of_stock", stk="601009")
    assert last_eval(client)["json"]["xs_lines"][-1] == 'return cbond.of_stock("601009")'

    with pytest.raises(WmshareError, match="未知参数"):
        client.call("cbond.of_stock", sym="601009", symbol="601009")


def test_symbol_alias_absent_for_functions_without_symbol(client):
    """没有标的参数的函数不受别名影响，symbol= 照旧报未知参数。"""
    with pytest.raises(WmshareError, match="未知参数"):
        client.call("cbond.board", symbol="601009")


def test_suffixed_code_canonicalized_for_any_typed_symbol(client):
    """cbond.* 的标的名在 xs 侧是 any 类型，带后缀的代码也必须归一。"""
    client.session.eval_result = []
    client.call("cbond.of_stock", stk="601009.SH")
    assert last_eval(client)["json"]["xs_lines"][-1] == 'return cbond.of_stock("601009")'

    client.call("cbond.kline_window", code="sz.128044", n=5)
    assert (last_eval(client)["json"]["xs_lines"][-1]
            == 'return cbond.kline_window("128044", 5)')


def test_batch_accepts_any_typed_symbol_param(client):
    """批量识别不再要求参数声明为 string：cbond.kline_window 的 code 是 any。"""
    client.session.eval_result = {"128044": {"close": [1.0]}, "113615": {"close": [2.0]}}
    r = client.call_batch("cbond.kline_window", ["128044", "113615"], n=5)
    assert r.results == {"128044": {"close": [1.0]}, "113615": {"close": [2.0]}}
    xs = " ".join(last_eval(client)["json"]["xs_lines"])
    assert 'cbond.kline_window("128044", 5)' in xs
    assert 'cbond.kline_window("113615", 5)' in xs


# ---- EC 可见性：metering 解析、阈值告警、BatchResult.ec_cost ----

class MeteringSession(FakeSession):
    """eval 响应带 meta.metering（复刻网关信封）。"""

    def __init__(self, ec_cost):
        super().__init__()
        self.ec_cost = ec_cost

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data, "headers": headers})
        outer = self

        class R:
            status_code = 200
            text = "{}"
            def raise_for_status(self):
                pass
            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                doc = {"success": True, "data": {"result": outer.eval_result}}
                if outer.ec_cost is not None:
                    doc["meta"] = {"metering": {"analysis.ec_cost": outer.ec_cost,
                                                "latency_ms": 12}}
                return doc
        return R()


def _metering_client(ec_cost, **kw):
    s = MeteringSession(ec_cost)
    c = Client(base_url="https://t", client_id="id", client_secret="sec",
               catalog=load(), session=s, **kw)
    return c, s


def test_last_ec_cost_parsed_from_metering():
    c, _ = _metering_client(318)
    c.call("kline.query_last", sym="600519")
    assert c.last_ec_cost == 318


def test_last_ec_cost_none_without_metering():
    c, _ = _metering_client(None)
    c.call("kline.query_last", sym="600519")
    assert c.last_ec_cost is None


def test_ec_warning_above_threshold():
    import warnings as _w
    c, _ = _metering_client(146_525)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        c.call("moneyflow.query_bars", sym="600519", limit=1)
    assert any("EC" in str(w.message) for w in caught)


def test_ec_no_warning_below_threshold():
    import warnings as _w
    c, _ = _metering_client(318)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        c.call("kline.query_last", sym="600519")
    assert not [w for w in caught if "EC" in str(w.message)]


def test_ec_warning_disabled_by_none_threshold():
    import warnings as _w
    c, _ = _metering_client(146_525, ec_warn_threshold=None)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        c.call("kline.query_last", sym="600519")
    assert not [w for w in caught if "EC" in str(w.message)]


def test_ec_threshold_invalid_rejected():
    with pytest.raises(UsageError, match="ec_warn_threshold"):
        Client(base_url="https://t", client_id="id", client_secret="sec",
               catalog=load(), ec_warn_threshold=0)


def test_batch_result_carries_ec_cost():
    c, _ = _metering_client(146_525)
    c.session.eval_result = {"600519": {"net_mf": 1.0}, "000001": {"net_mf": 2.0}}
    r = c.call_batch("moneyflow.query_bars", ["600519", "000001"], limit=1)
    assert r.ec_cost == 146_525


def test_batch_all_sums_ec_cost_across_batches():
    c, _ = _metering_client(146_525)
    codes = ["600519", "000001", "000002"]
    c.session.eval_result = {s: {"net_mf": 1.0} for s in codes}
    r = c.batch_all("moneyflow.query_bars", codes, batch_size=1)
    assert r.requests == 3
    assert r.ec_cost == 146_525 * 3


def test_moneyflow_large_list_warns_ec_semantics():
    import warnings as _w
    client = Client(base_url="https://t", client_id="id", client_secret="sec",
                    catalog=load(), session=FakeSession())
    codes = ["600519", "000001", "000002"]  # 小列表不提示
    client.session.eval_result = {s: [] for s in codes}
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        client.moneyflow.last(codes)
    assert not [w for w in caught if "EC" in str(w.message)]
    big = [f"{i:06d}" for i in range(300)]
    client.session.eval_result = {s: [] for s in big}
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        client.moneyflow.last(big)
    assert any("EC" in str(w.message) for w in caught)


def test_moneyflow_board_builds_bare_call():
    client = Client(base_url="https://t", client_id="id", client_secret="sec",
                    catalog=load(), session=FakeSession())
    client.moneyflow.board()
    ev = last_eval(client)
    assert ev["json"]["xs_lines"] == ["return moneyflow.board()"]
    assert ev["json"]["mode"] == "call"
