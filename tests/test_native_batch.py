"""批量原生路由契约测试（mock 传输，不联网）。

守护 BATCH_NATIVE_ROUTES 路由：命中接口（kline.snapshot）收列表时自动改走
批量原生实现（kline.snapshot_batch）并适配回逐票合同——EC 按量而非 N×单票放大。
分批执行器语义（native_batch=False 下）见 test_batch.py。
"""
import warnings

import pytest

from wmshare.catalog import load
from wmshare.client import NATIVE_FULL_MARKET_MIN, Client
from wmshare.errors import ApiError


class RouteSession:
    """按 XS 脚本形态回填结果的假传输：

    - 含 ``snapshot_batch`` → 原始索引行 [{row, values}]（$指标键）
    - ``return {`` 开头（拼接）→ {标的: MAP}，并按标的数计 eval 次数
    """

    def __init__(self):
        self.eval_calls = 0
        self.eval_lines: list[str] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        cls = self

        class R:
            status_code = 200
            text = "{}"
            headers: dict = {}

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                cls.eval_calls += 1
                lines = (json or {}).get("xs_lines") or []
                cls.eval_lines.extend(lines)
                joined = "\n".join(lines)
                if "snapshot_batch(" in joined:
                    codes = _codes_from_lines(lines)
                    if not codes:   # 空参 = 服务端全市场（捷径路径）
                        codes = [f"{i:06d}" for i in range(5693)]
                    rows = []
                    for i, c in enumerate(codes):
                        if c in _MISSING:
                            continue
                        rows.append({"row": i, "values": dict(_RAW_ROW, **{"$SYMBOL": c})})
                    return {"success": True, "data": {"result": rows}}
                for ln in lines:
                    if ln.startswith("return {"):
                        syms = [p.split(":")[0].strip().strip('"')
                                for p in ln[len("return {"):-1].split(", ")]
                        return {"success": True,
                                "data": {"result": {s: {"close": 10.0} for s in syms}}}
                return {"success": True, "data": {"result": {"ok": True}}}

        R._cls = cls
        return R()


_RAW_ROW = {
    "$NAME": "浦发银行", "$CLOSE_LAST": 10.0, "$PERCENT_LAST": 0.01,
    "$VOLUME_LAST": 10.0, "$AMOUNT_LAST": 1.0e8, "$MV_LAST": 2.0e11,
    "$MV_FREE_LAST": 1.5e11, "$MA_CLOSE_20_LAST": 9.9, "$MA_CLOSE_60_LAST": 9.8,
    "$MA120_LAST": 9.7, "$CHG_5D_LAST": 0.02, "$CHG_10D_LAST": 0.03,
    "$CHG_20D_LAST": 0.04, "$CHG_90D_LAST": 0.05, "$ROI_NERAST_1": 0.06,
    "$VOL_RATIO_5_LAST": 1.1, "$MA60_UP_LAST": True, "$INDUSTRY_CUR_1": "银行",
    "$IS_SUSPEND": False, "$IS_ST": False,
}
_MISSING = {"000003"}


def _codes_from_lines(lines: list[str]) -> list[str]:
    import json as _json
    out: list[str] = []
    for ln in lines:
        if "snapshot_batch(" in ln:
            body = ln[ln.index("(", ln.index("snapshot_batch")) + 1:ln.rindex(")")]
            out = [str(s) for s in _json.loads(body)]
    return out


def make_client(**kw):
    return Client(base_url="https://test-api.winmale.com", client_id="id",
                  client_secret="sec", catalog=load(),
                  session=RouteSession(), market="cn", **kw)


def last_lines(c: Client) -> list[str]:
    return c.session.eval_lines


def test_list_routes_to_snapshot_batch_native():
    """≥3 票列表 → 单次 eval 调 snapshot_batch，适配回 {代码: 23 字段}。"""
    c = make_client()
    res = c.kline.snapshot(["600519", "000001", "000002"])
    assert c.session.eval_calls == 1
    assert any("snapshot_batch(" in ln for ln in last_lines(c))
    assert not any(ln.startswith("return {") for ln in last_lines(c))
    assert isinstance(res.results, dict) and set(res.results) == {"600519", "000001", "000002"}
    row = res.results["600519"]
    assert row["symbol"] == "600519" and row["close"] == 10.0
    assert row["ma60"] == 9.8 and row["ma60_up"] is True and row["is_st"] is False
    # 索引未物化的两个 cursor 字段置 None（23 字段合同保持）
    assert row["kline_date"] is None and row["kline_sas"] is None
    assert len(row) == 23
    assert res.requests == 1 and res.requested == 3


def test_small_list_still_splices():
    """< native_batch_min(3) 的列表保持拼接语义。"""
    c = make_client()
    res = c.kline.snapshot(["600519", "000001"])
    assert any(ln.startswith("return {") for ln in last_lines(c))
    assert not any("snapshot_batch(" in ln for ln in last_lines(c))
    assert set(res.results) == {"600519", "000001"}


def test_native_batch_disabled_falls_back_to_splice():
    c = make_client(native_batch=False)
    res = c.kline.snapshot(["600519", "000001", "000002"])
    assert any(ln.startswith("return {") for ln in last_lines(c))
    assert set(res.results) == {"600519", "000001", "000002"}


def test_explicit_call_batch_raise_routes_native_skip_splices():
    c = make_client()
    res = c.call_batch("kline.snapshot", ["600519", "000001", "000002", "000005"])
    assert any("snapshot_batch(" in ln for ln in last_lines(c))
    assert len(res.results) == 4
    # skip 模式恒为逐票请求（原生批量无法逐票隔离错误）
    c2 = make_client()
    res2 = c2.call_batch("kline.snapshot", ["600519", "000001", "000002", "000005"],
                         on_error="skip")
    assert c2.session.eval_calls == 4
    assert len(res2.results) == 4


def test_missing_symbol_raises_batch_missing():
    c = make_client()
    with pytest.raises(ApiError) as ei:
        c.kline.snapshot(["600519", "000001", "000003"])
    assert ei.value.code == "batch_missing"
    assert "000003" in str(ei.value)


def test_native_path_ignores_max_limit():
    """全市场清单走原生单次 eval，不受拼接 500 上限约束。"""
    c = make_client()
    codes = [f"{i:06d}" for i in range(5691) if f"{i:06d}" not in _MISSING]
    res = c.kline.snapshot(codes)
    assert c.session.eval_calls == 1
    assert res.requests == 1 and res.requested == 5690
    assert len(res.results) == 5690


def test_units_applied_once_on_adapted_container():
    """适配后的 {代码: MAP} 一次 apply_units：lot→股，指数键跳过。"""
    c = make_client()
    res = c.kline.snapshot(["600519", "399001", "000002"])
    assert res.results["600519"]["volume"] == 1000.0     # 10 手 → 1000 股
    assert res.results["399001"]["volume"] == 10.0       # 指数不换算


def test_raw_skips_unit_conversion():
    c = make_client()
    res = c.call("kline.snapshot", sym=["600519", "000001", "000002"], _raw=True)
    assert res.results["600519"]["volume"] == 10.0       # 原始「手」


def test_splice_guardrail_warns_for_unrouted_interface():
    """非路由接口 ≥200 票拼接触发 EC 放大提示（不阻断）。"""
    c = make_client()
    codes = [f"{i:06d}" for i in range(200)]
    with pytest.warns(UserWarning, match="逐票拼接"):
        c.call_batch("kline.query_bars", codes)
    assert c.session.eval_calls == 1


def test_routed_interface_does_not_trigger_guardrail():
    c = make_client()
    codes = [f"{i:06d}" for i in range(300) if f"{i:06d}" not in _MISSING]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        res = c.kline.snapshot(codes)
    assert len(res.results) == 299


def test_batch_all_skips_chunking_for_native_route():
    """batch_all 对路由接口不分批：全市场 1 次 eval（不再 12 批逐段点查）。"""
    c = make_client()
    codes = [f"{i:06d}" for i in range(5691) if f"{i:06d}" not in _MISSING]
    res = c.batch_all("kline.snapshot", codes)
    assert c.session.eval_calls == 1
    assert res.requests == 1 and res.requested == 5690
    assert len(res.results) == 5690


def test_batch_all_non_native_still_chunks():
    c = make_client()
    codes = [f"{i:06d}" for i in range(5691)]
    res = c.batch_all("kline.query_bars", codes)
    assert c.session.eval_calls == 12


def test_full_market_shortcut_marks_truncated():
    """准全市场捷径下停牌/索引外标的静默缺席 → truncated=True 显式披露。"""
    c = make_client()
    # 阈值与服务端对齐为 2000：上游 snapshot_batch 对去重 ≥2000 的清单本来就
    # 走全市场扫描（与空参捷径冷启动同价），捷径另享按日 memo（复跑 ≈28 EC）
    codes = [f"{i:06d}" for i in range(NATIVE_FULL_MARKET_MIN)]
    assert NATIVE_FULL_MARKET_MIN == 2000
    assert "000003" in codes  # _MISSING：索引无行
    res = c.kline.snapshot(codes)
    assert res.truncated is True
    assert "000003" not in res.results
    assert res.requested == NATIVE_FULL_MARKET_MIN
    # 阈值下 1 票仍走数组路径：缺票按 batch_missing 显式报错（捷径才给 truncated）
    with pytest.raises(ApiError, match="000003"):
        c.kline.snapshot([f"{i:06d}" for i in range(NATIVE_FULL_MARKET_MIN - 1)])
    # 正常规模（<阈值）缺票走 batch_missing（见下条测试），不是 truncated
    small = c.kline.snapshot(["600519", "000001", "000002"])
    assert small.truncated is False


def test_native_batch_fields_projection():
    """_fields 在批量原生路径逐标的投影（顺序=请求顺序）。"""
    c = make_client()
    res = c.kline.snapshot(["600519", "000001", "000002"],
                           _fields=["symbol", "close"])
    assert set(res.results) == {"600519", "000001", "000002"}
    assert res.results["600519"] == {"symbol": "600519", "close": 10.0}
    assert list(res.results["000001"]) == ["symbol", "close"]
    assert res.truncated is False
