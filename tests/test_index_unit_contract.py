"""指数键单位契约回归（默认离线、零凭证可跑）。

运行（项目根目录）：
    PYTHONPATH=src python -m pytest -q tests/test_index_unit_contract.py

联网冒烟（需凭证，收盘后运行）：
    WMSHARE_LIVE_SMOKE=1 PYTHONPATH=src python -m pytest -q tests/test_index_unit_contract.py

背景：指数点位行由上游 index_quote 桥接生成，volume 是成分股聚合量、amount 是
聚合成交额，二者比值不在 1 量级；上游也不以「手」披露指数成交量。此前目录把
个股专属的 ``units.volume=lot`` 与 ``checks=[volume_amount]`` 挂在同一个函数上，
于是指数走个股入口时：

  * 默认调用抛 ``DataError: volume×close/amount=1.4e5``；
  * 用 ``Client(validate=False)`` 绕过校验，volume 却被静默放大 100 倍
    （比显式报错更危险）。

修法是**按标的收窄守护**，不是删声明：指数键下只跳过 lot 换算与
volume_amount 不变量，percent / ranges / diffp_ratio 等守护一律保留。
本文件把每条边界钉死，尤其防止「只跳过不变量、留下静默错值」的半截修法。
"""
from __future__ import annotations

import os

import pytest

import wmshare
from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import DataError
from wmshare.units import apply_units, is_index_symbol

LIVE_SMOKE = pytest.mark.skipif(os.getenv("WMSHARE_LIVE_SMOKE") != "1",
                                reason="设置 WMSHARE_LIVE_SMOKE=1 才联网")

IDX = "399300.INDEX"
STK = "600519"

# 指数 bar（上游原值）：volume 与 amount 不同量纲，volume×close/amount≈1486
INDEX_BAR = {
    "date": "2026-11-13", "open": 4090.0, "high": 4100.0, "low": 4050.0,
    "close": 4075.7093, "volume": 161199262, "amount": 442127614.3404,
    "percent": 0.004089,
}
# store.latest 原始行的 percent 仍是百分数；其余 bar 入口上游已格式化为小数
INDEX_BAR_PCT = dict(INDEX_BAR, percent=-0.7798)
# 个股 bar（上游 volume 为「手」）：×100 后 volume×close/amount≈0.99
STOCK_BAR = {
    "date": "2026-11-13", "open": 1400.0, "high": 1410.0, "low": 1395.0,
    "close": 1402.3, "volume": 39847, "amount": 5633865699.0,
    "percent": 0.005215,
}
STOCK_BAR_PCT = dict(STOCK_BAR, percent=0.5215)

# 目录里全部声明了 units.volume=lot 的函数；新增声明必须同步补进本表
LOT_FUNCS = {
    "kline.query_bars", "kline.query_bars_period", "kline.query_bars_adj",
    "kline.query_bars_period_adj", "kline.query_last", "kline.query_last_live",
    "kline.query_last_live_many", "kline.query_min1_live", "kline.snapshot",
    "kline.query_last_adj",
}
# 这两个入口上游 percent 是百分数（store.latest 原始行），其余已是小数
PERCENT_FUNCS = {"kline.query_last", "kline.query_last_adj"}


class FakeSession:
    """复现 OpenAPI 合同：/v1/oauth/token + /v1/analysis/xs/eval，不联网。"""

    def __init__(self):
        self.calls: list[dict] = []
        self.eval_result: object = {"ok": True}

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
                return {"success": True, "data": {"result": self._cls.eval_result}}

        R._cls = self
        return R()


@pytest.fixture()
def client():
    return Client(base_url="https://test-api.winmale.com", client_id="id",
                  client_secret="sec", catalog=load(), session=FakeSession(),
                  market="cn")


def _meta(name: str) -> dict:
    return load().function(name)


def _call_kwargs(name: str, sym: str) -> dict:
    """按目录签名补齐必填参数（query_bars_adj 的 limit 是必填）。"""
    fn = _meta(name)
    params = fn.get("params") or load().inventory_params(name)
    kw: dict = {}
    for p in params:
        n = p["name"]
        if n in ("sym", "symbol", "stk", "code"):
            kw[n] = sym
        elif n == "syms":
            kw[n] = [sym]
        elif p.get("required"):
            kw[n] = 5 if n == "limit" else "D"
    return kw


def _canned(name: str, sym: str) -> object:
    """按各入口的真实返回形态造罐头：ARR / 单行 MAP / 容器 MAP / 分时嵌套。"""
    row = INDEX_BAR_PCT if name in PERCENT_FUNCS else INDEX_BAR
    if name.startswith("kline.query_bars"):
        return [dict(row)]
    if name == "kline.query_last_live_many":
        return {sym: dict(row)}
    if name == "kline.query_min1_live":
        return {"trading_day": "2026-11-13", "bar_n": 1, "bars": [dict(row)]}
    return dict(row)


def _all_volumes(node: object) -> list:
    """递归收集结果里所有 volume 值，用于判定「确实一根 bar 都没有」。"""
    found: list = []
    if isinstance(node, list):
        for item in node:
            found.extend(_all_volumes(item))
    elif isinstance(node, dict):
        if "volume" in node:
            found.append(node["volume"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                found.extend(_all_volumes(v))
    return found


def _first_bar(result: object) -> dict:
    """从各种返回形态里取出第一根 bar，便于统一断言 volume/percent。"""
    if isinstance(result, list):
        return result[0] if result else {}
    if isinstance(result, dict):
        if "volume" in result:
            return result
        for v in result.values():
            if isinstance(v, dict) and "volume" in v:
                return v
            if isinstance(v, list) and v and isinstance(v[0], dict) and "volume" in v[0]:
                return v[0]
            if isinstance(v, dict) and "bars" in v:
                bars = v["bars"]
                if bars:
                    return bars[0]
    return {}


# ---- 1. 指数键判定（与上游桥接规则对齐）----

@pytest.mark.parametrize("sym", [
    "399300.INDEX", "399300", "399001.SZ", "cn.399300", "sh.399300",
    "index.hs300", "INDEX.HS300", "index.sz50", "000300.INDEX", " 399300 ",
])
def test_is_index_symbol_true(sym):
    assert is_index_symbol(sym) is True


@pytest.mark.parametrize("sym", [
    None, "", "   ", "600519", "600519.SH", "000001", "300058", "510300",
    "AAPL", "00700", "39930", "3993001", "399ABC", "my.index", "399300.SHX",
])
def test_is_index_symbol_false(sym):
    """000001 等歧义裸码、ETF、港美股、非数字不得误判成指数（会跳过守护）。"""
    assert is_index_symbol(sym) is False


def test_normalized_symbol_still_recognized(client):
    for raw in ("399300.INDEX", "399300.SZ", "cn.399300", "index.hs300"):
        assert is_index_symbol(client._canon_symbol(raw)), raw


# ---- 2. apply_units 纯函数：只做减法，不放宽守护面 ----

def test_index_skips_lot_and_volume_amount():
    row = dict(INDEX_BAR)
    apply_units(row, _meta("kline.query_bars"), fname="kline.query_bars", symbol=IDX)
    assert row["volume"] == INDEX_BAR["volume"]          # 未被 ×100
    assert row["percent"] == INDEX_BAR["percent"]        # 无 percent 声明，保持小数


def test_stock_still_converts_lot_and_guards():
    row = dict(STOCK_BAR)
    apply_units(row, _meta("kline.query_bars"), fname="kline.query_bars", symbol=STK)
    assert row["volume"] == STOCK_BAR["volume"] * 100
    with pytest.raises(DataError, match="volume_amount"):
        apply_units(dict(STOCK_BAR, volume=3984700.0), _meta("kline.query_bars"),
                    fname="kline.query_bars", symbol=STK)


def test_index_still_converts_percent():
    """指数 query_last 的原生 percent 是百分数，声明不能一并跳过。"""
    row = dict(INDEX_BAR_PCT)
    apply_units(row, _meta("kline.query_last"), fname="kline.query_last", symbol=IDX)
    assert row["percent"] == pytest.approx(-0.007798)
    assert row["volume"] == INDEX_BAR["volume"]


def test_index_still_enforces_ranges():
    """ranges.percent 仍生效：指数键不是「关闭全部校验」的通行证。"""
    row = dict(INDEX_BAR, percent=123.0)
    with pytest.raises(DataError, match="超出声明范围"):
        apply_units(row, _meta("kline.query_bars"), fname="kline.query_bars", symbol=IDX)


def test_index_still_enforces_other_invariants():
    """diffp_ratio 与指数无关，必须照常拦截（防一刀切关掉所有 checks）。"""
    meta = {"checks": ["diffp_ratio"]}
    row = {"c": {"2025": 100.0}, "diff": {"2025": -10.0},
           "diffp": {"2025": -0.5}}       # 应为 -0.1
    with pytest.raises(DataError, match="diffp_ratio"):
        apply_units(row, meta, fname="fund.statement_compare", symbol=IDX)


def test_meta_is_not_mutated():
    """目录缓存是共享 dict，按标的收窄不能就地改写声明。"""
    meta = _meta("kline.query_bars")
    before = (dict(meta["units"]), list(meta["checks"]))
    apply_units(dict(INDEX_BAR), meta, fname="kline.query_bars", symbol=IDX)
    assert dict(meta["units"]) == before[0] and list(meta["checks"]) == before[1]


def test_index_in_non_cn_market():
    row = dict(INDEX_BAR)
    apply_units(row, _meta("kline.query_bars"), fname="kline.query_bars",
                market="us", symbol=IDX)
    assert row["volume"] == INDEX_BAR["volume"]


def test_nested_bars_and_mixed_container():
    """{symbol: bar} 容器里指数与个股各走自己的口径，互不串味。"""
    result = {IDX: dict(INDEX_BAR), STK: dict(STOCK_BAR)}
    apply_units(result, _meta("kline.query_bars"), fname="kline.query_bars")
    assert result[IDX]["volume"] == INDEX_BAR["volume"]
    assert result[STK]["volume"] == STOCK_BAR["volume"] * 100

    bars = [dict(INDEX_BAR), dict(INDEX_BAR)]
    apply_units(bars, _meta("kline.query_bars"), fname="kline.query_bars", symbol=IDX)
    assert all(b["volume"] == INDEX_BAR["volume"] for b in bars)


# ---- 3. 目录声明未被改写（防止靠删声明「修」掉问题）----

def test_catalog_declarations_intact():
    cat = load()
    lot = {n for n in LOT_FUNCS
           if (cat.function(n).get("units") or {}).get("volume") == "lot"}
    assert lot == LOT_FUNCS, f"声明被删或新增未同步：{LOT_FUNCS ^ lot}"
    for n in ("kline.query_bars", "kline.query_bars_period", "kline.query_last"):
        assert "volume_amount" in (cat.function(n).get("checks") or []), n


# ---- 4. Client.call 端到端（离线罐头）----

@pytest.mark.parametrize("name", sorted(LOT_FUNCS))
def test_all_lot_functions_index_default_call_no_error(client, name):
    """10 个入口在指数键下默认调用零 DataError，且 volume 不被静默放大。"""
    client.session.eval_result = _canned(name, IDX)
    out = client.call(name, **_call_kwargs(name, IDX))
    bar = _first_bar(out)
    assert bar, f"{name}: 罐头未解析出 bar"
    assert bar["volume"] == INDEX_BAR["volume"], name
    if name in PERCENT_FUNCS:
        assert bar["percent"] == pytest.approx(-0.007798), name


def test_index_volume_not_inflated_when_validation_off():
    """validate=False 只关校验、保留换算；指数仍不得被 ×100（关键回归）。"""
    with pytest.warns(RuntimeWarning, match="guards_off"):
        c = Client(base_url="https://test-api.winmale.com", client_id="id",
                   client_secret="sec", catalog=load(), session=FakeSession(),
                   market="cn", validate=False)
    c.session.eval_result = [dict(INDEX_BAR)]
    out = c.call("kline.query_bars", sym=IDX, limit=1)
    assert out[0]["volume"] == INDEX_BAR["volume"]


def test_stock_conversion_unchanged(client):
    client.session.eval_result = [dict(STOCK_BAR)]
    out = client.call("kline.query_bars", sym=STK, limit=1)
    assert out[0]["volume"] == STOCK_BAR["volume"] * 100


def test_native_and_raw_bypass_unchanged(client):
    client.session.eval_result = [dict(INDEX_BAR)]
    assert client.call("kline.query_bars", sym=IDX, limit=1,
                       _units="native")[0]["volume"] == INDEX_BAR["volume"]
    assert client.call("kline.query_bars", sym=IDX, limit=1,
                       _raw=True)[0]["volume"] == INDEX_BAR["volume"]


def test_kline_last_and_bars_high_level_api(client):
    client.session.eval_result = dict(INDEX_BAR_PCT, annual=2026,
                                      sampling="D317", samplingTs=1794499200)
    last = client.kline.last(IDX)
    assert last["volume"] == INDEX_BAR["volume"]
    assert last["percent"] == pytest.approx(-0.007798)

    client.session.eval_result = [dict(INDEX_BAR)]
    assert client.kline.bars(IDX, n=1)[0]["volume"] == INDEX_BAR["volume"]


def test_batch_live_mixed_container(client):
    """syms 单请求路径：顶层 symbol 是默认锚点，靠容器 key 逐子树判定。"""
    client.session.eval_result = {IDX: dict(INDEX_BAR), STK: dict(STOCK_BAR)}
    out = client.kline.batch_live([IDX, STK])
    assert out[IDX]["volume"] == INDEX_BAR["volume"]
    assert out[STK]["volume"] == STOCK_BAR["volume"] * 100


def test_call_batch_mixed_container(client):
    client.session.eval_result = {IDX: [dict(INDEX_BAR)], STK: [dict(STOCK_BAR)]}
    out = client.call_batch("kline.query_bars", [IDX, STK], limit=1)
    assert out.results[IDX][0]["volume"] == INDEX_BAR["volume"]
    assert out.results[STK][0]["volume"] == STOCK_BAR["volume"] * 100


# ---- 5. 联网冒烟（需凭证 + 显式开关）----

@LIVE_SMOKE
@pytest.mark.parametrize("name", sorted(LOT_FUNCS))
def test_live_smoke_index_default_call_no_error(name):
    """默认调用零 DataError；有数据则 volume 必须与 native 一致，无数据则
    必须是明确的空形态（None / 空容器），避免出现「有数据却被静默放大」。
    """
    cli = wmshare.Client.from_env()
    out = cli.call(name, **_call_kwargs(name, IDX))
    bar = _first_bar(out)
    if not bar:
        assert not _all_volumes(out), \
            f"{name}: _first_bar 未解析出 bar，但结果里存在 volume 字段"
        return
    native = cli.call(name, _units="native", **_call_kwargs(name, IDX))
    native_bar = _first_bar(native)
    assert bar["volume"] == pytest.approx(native_bar["volume"]), name


@LIVE_SMOKE
def test_live_smoke_stock_still_multiplied_by_100():
    cli = wmshare.Client.from_env()
    base = cli.call("kline.query_bars", sym=STK, limit=1)[0]
    native = cli.call("kline.query_bars", sym=STK, limit=1, _units="native")[0]
    assert base["volume"] == pytest.approx(native["volume"] * 100)


@LIVE_SMOKE
def test_live_smoke_high_level_api():
    cli = wmshare.Client.from_env()
    assert cli.kline.last(IDX)["volume"] > 0
    assert cli.kline.bars(IDX, n=2)[0]["volume"] > 0
