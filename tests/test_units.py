"""单位契约层：目录声明 → 单点换算 + 量级/不变量守护。

全部离线（可编排 FakeSession 回放罐头数据，数值取自真实 probe 样本）。
"""
import pytest

from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import CatalogError, DataError, ServerError
from wmshare.units import apply_units, convert_field, validate_meta

# 与 tests/test_transport.py 同款最小回放会话：eval 恒返回罐头结果。
BAR = {"date": "2026-10-20", "open": 1321.01, "high": 1335, "low": 1316.14,
       "close": 1331.88, "volume": 34135, "amount": 4525398959.0, "percent": 0.005215}
COMPARE_ROW = {"cn": "营业成本", "k": "operating_cost", "t": 1,
               "c": {"2025": 14892277570.91}, "p": {"2025": 16048785720.71},
               "diff": {"2025": -1156508149.8}, "diffp": {"2025": -7.765824564397575}}
YJYG_ROW = {"ann_date": "2026-10-21", "predict_type": "预增",
            "np_amp_lower": 153.6, "np_amp_upper": 174.7,
            "rev_amp_lower": 46.0, "rev_amp_upper": 46.0,
            "np_lower": 1200000000, "np_upper": 1300000000}
YJKB_ROW = {"ann_date": "2026-10-21", "basic_eps": 1.5778, "bvps": 14.8,
            "np_yoy": 0.200365203859, "rev_yoy": -0.478779830389, "roe": 11.28,
            "netprofit": 631114132.36}


class CannedSession:
    """eval 每次返回 result 的深拷贝（模拟真实 HTTP：每次全新 JSON，允许就地换算）。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append(url)
        if url.endswith("/v1/oauth/token"):
            return Resp({"data": {"access_token": "tok", "expires_in": 3600}})
        import copy
        return Resp({"success": True, "data": {"result": copy.deepcopy(self.result)}})


class Resp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}
        self.text = "{}"

    def json(self):
        return self._body


def make(result, **kw):
    s = CannedSession(result)
    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=s, **kw)
    return c, s


# ---- call() 换算 ----

def test_kline_volume_lot_converted_to_shares():
    c, _ = make([dict(BAR)])
    out = c.call("kline.query_bars", sym="600519", limit=1)
    assert out[0]["volume"] == 3413500.0  # 手 → 股
    assert out[0]["close"] == BAR["close"]  # 基础单位字段不动


def test_kline_volume_lot_kept_for_non_cn_markets():
    # 港美上游即披露股：market != cn 不做手×100，原值直出且不变量守恒
    c, _ = make([dict(BAR, volume=3413500)], market="hk")
    out = c.call("kline.query_bars", sym="00700", limit=1)
    assert out[0]["volume"] == 3413500  # 原样，未 ×100


def test_kline_non_cn_with_lot_shaped_volume_trips_guard():
    # 港美行若给的是手形量值（×close/amount≈0.01），守护拦下——
    # 正是 2026-10-27 修复前港美被错误 ×100 的形态
    c, _ = make([dict(BAR)], market="hk")
    with pytest.raises(DataError, match="volume_amount"):
        c.call("kline.query_bars", sym="00700", limit=1)


def test_volume_amount_invariant_passes_and_violates():
    c, _ = make([dict(BAR)])
    c.call("kline.query_bars", sym="600519", limit=1)  # 不抛 = 不变量通过

    bad = dict(BAR, volume=3413500.0)  # 已是股的值再被换算一次 → ×100 偏离
    c2, _ = make([bad])
    with pytest.raises(DataError, match="volume_amount"):
        c2.call("kline.query_bars", sym="600519", limit=1)


def test_volume_amount_skips_zero_volume_rows():
    """volume=0 无从验算，跳过而不是误判（日线入口直接验守卫行为）。

    A 股 2001-08~2016-08 月线只有 amount 没有 volume（实测 180/302 行），
    守卫按 [0.4, 2.5] 判会算出 ratio=0 → 整条调用被误杀。
    """
    c, _ = make([dict(BAR, volume=0)])
    out = c.call("kline.query_bars", sym="600519", limit=1)
    assert out[0]["volume"] == 0  # 未换算、未拦下


def test_period_bars_carry_no_volume_amount_check():
    """聚合周期不套 volume_amount：ratio 恒等于「期末价/期内均价」，天然偏离。

    月线实测 2,269 样本落在 [0.07, 2.59]（拆股月与早年 amount 口径差异放大），
    套个股日线带 [0.4, 2.5] 会把正常序列判成单位漂移。
    """
    cat = load()
    assert "volume_amount" not in (cat.function("kline.query_bars_period").get("checks") or [])
    # 极端偏离的行不该被拦（这里 close/amount 比例远离 1）
    c, _ = make([dict(BAR, volume=0), dict(BAR, volume=3413500.0)])
    out = c.call("kline.query_bars_period", sym="600519", limit=2, period="M")
    assert len(out) == 2


def test_volume_amount_zero_skip_does_not_relax_daily_bars():
    """日线同源守卫不受影响：坏行照旧抛。"""
    c, _ = make([dict(BAR, volume=3413500.0)])
    with pytest.raises(DataError, match="volume_amount"):
        c.call("kline.query_bars", sym="600519", limit=1)


def test_invariant_message_carries_escape_hatch():
    c, _ = make([dict(BAR, volume=3413500.0)])
    with pytest.raises(DataError) as ei:
        c.call("kline.query_bars", sym="600519", limit=1)
    msg = str(ei.value)
    assert "_raw=True" in msg and 'native' in msg and "validate=False" in msg
    assert ei.value.code == "invariant"


def test_range_guard_raises_data_error():
    c, _ = make([dict(BAR, percent=123.0)])  # 换算后超出 [-1, 30]
    with pytest.raises(DataError, match="超出声明范围") as ei:
        c.call("kline.query_bars", sym="600519", limit=1)
    assert ei.value.code == "range"




def test_yjyg_amp_percent_converted():
    c, _ = make([dict(YJYG_ROW)])
    out = c.call("forecast.yjyg_rows", sym="688008", limit=1)
    assert out[0]["np_amp_lower"] == pytest.approx(1.536)
    assert out[0]["rev_amp_upper"] == pytest.approx(0.46)
    assert out[0]["np_lower"] == 1200000000  # 金额已是元


def test_yjkb_yoy_and_roe_converted():
    c, _ = make([dict(YJKB_ROW)])
    out = c.call("forecast.yjkb_rows", sym="603092", limit=1)
    assert out[0]["np_yoy"] == pytest.approx(0.00200365203859)
    assert out[0]["roe"] == pytest.approx(0.1128)
    assert out[0]["netprofit"] == YJKB_ROW["netprofit"]


def test_snapshot_nested_container_converted():
    snap = {"symbol": "688008", "next_disclosure": {"report_date": "2026-09-30"},
            "yjyg": dict(YJYG_ROW), "yjkb": dict(YJKB_ROW)}
    c, _ = make(dict(snap))
    out = c.call("forecast.snapshot", sym="688008")
    assert out["yjyg"]["np_amp_upper"] == pytest.approx(1.747)
    assert out["yjkb"]["roe"] == pytest.approx(0.1128)
    assert out["next_disclosure"]["report_date"] == "2026-09-30"


# ---- 参数语义：native / raw / validate=False ----

def test_units_native_keeps_script_values():
    c, _ = make([dict(YJYG_ROW)])
    out = c.call("forecast.yjyg_rows", sym="688008", limit=1, _units="native")
    assert out[0]["np_amp_lower"] == 153.6  # 脚本原值（百分数），字段名仍规范化


def test_units_native_skips_validation_too():
    c, _ = make([dict(BAR, volume=3413500.0)])
    out = c.call("kline.query_bars", sym="600519", limit=1, _units="native")
    assert out[0]["volume"] == 3413500.0  # 不换算也不守护


def test_raw_skips_everything():
    c, _ = make([dict(YJYG_ROW)])
    out = c.call("forecast.yjyg_rows", sym="688008", limit=1, _raw=True)
    assert out[0]["np_amp_lower"] == 153.6


def test_validate_false_keeps_conversion_skips_checks():
    c, _ = make([dict(BAR, volume=3413500.0)], validate=False)
    out = c.call("kline.query_bars", sym="600519", limit=1)
    assert out[0]["volume"] == 341350000.0  # 换算仍执行
    # 不抛：volume_amount 不变量被关闭


def test_invalid_units_token_rejected():
    c, _ = make([dict(BAR)])
    with pytest.raises(Exception, match='_units'):
        c.call("kline.query_bars", sym="600519", limit=1, _units="foo")


# ---- call_batch 两条路径 ----

def _two_symbol_result():
    return {"600519": dict(BAR), "000001": dict(BAR)}


def test_call_batch_map_path_converts():
    c, _ = make(_two_symbol_result())
    out = c.call_batch("kline.query_bars", ["600519", "000001"], limit=1)
    assert out.results["600519"]["volume"] == 3413500.0
    assert out.results["000001"]["volume"] == 3413500.0


def test_call_batch_skip_path_converts_and_isolates():
    c, _ = make(dict(BAR))  # skip 路径逐标的单 HTTP，罐头为单行
    out = c.call_batch("kline.query_bars", ["600519", "000001"], limit=1, on_error="skip")
    assert not out.errors
    assert all(r["volume"] == 3413500.0 for r in out.results.values())


def test_call_batch_native_keeps_raw():
    c, _ = make(_two_symbol_result())
    out = c.call_batch("kline.query_bars", ["600519"], limit=1, _units="native")
    assert out.results["600519"]["volume"] == 34135


# ---- IndicatorApi：精选指标 range 守护 ----

def test_indicator_get_range_guard():
    c, _ = make(0.42)
    assert c.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST") == 0.42
    c2, _ = make(42.0)  # ×100 量级 → 超出 [0, 1]
    with pytest.raises(DataError, match="PCT_PE_TTM_10Y"):
        c2.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")


def test_indicator_metrics_none_and_unmeta_codes():
    c, _ = make({"$GM": None, "$PE_TTM_LAST": 25.5})
    out = c.indicator.metrics("601318", ["$GM", "$PE_TTM_LAST"])
    assert out["$GM"] is None          # None 原样透传
    assert out["$PE_TTM_LAST"] == 25.5  # 未声明 range 的代码不守护


def test_indicator_range_violation_in_batch():
    c, _ = make({"$ROE_TTM_LAST": 3324.0})  # ×100 量级
    with pytest.raises(DataError, match="ROE_TTM"):
        c.indicator.metrics("600519", ["$ROE_TTM_LAST"])


# ---- IndicatorApi：市场可用性（美股代码归一 + symbol 未绑定翻译） ----

def test_indicator_us_last_family_works_with_bare_symbol():
    """美股 _LAST 族本身可用：裸代码走公司路径（symbol 已绑定），值正常返回。

    实测 2026-10-30：AAPL $PE_TTM_LAST=39.49、$PCT_PE_TTM_10Y_LAST=0.7858；
    带交易所后缀（AAPL.O）才会被上游当宏观序列——归一在 normalize_symbol 层完成。
    """
    c, _ = make(0.7858, market="us")
    assert c.indicator.get("AAPL", "$PCT_PE_TTM_10Y_LAST") == 0.7858
    c2, _ = make({"$PE_TTM_LAST": 39.49}, market="us")
    assert c2.indicator.metrics("AAPL", ["$PE_TTM_LAST"])["$PE_TTM_LAST"] == 39.49


def test_indicator_engine_error_translated():
    """上游没有绑定 symbol 时，翻译成带「裸代码」指引的 DataError（保留原始错误）。"""
    c, _ = make(1, market="us")
    def boom(xs, **kw):
        raise ServerError('openapi:1: sel.recv: LAST: store.latest: '
                          'undefined variable "symbol"', status=500)
    c.eval_result = boom
    with pytest.raises(DataError, match="裸代码") as ei:
        c.indicator.get("AAPL", "$PE_TTM_LAST")
    assert 'undefined variable "symbol"' in str(ei.value)


# ---- segments（经营分部）：值已是基础单位，只守护不换算 ----

SEG_ROW = {"name": "茅台酒", "tr": 77724437925.48, "tr_text": "",
           "cost": 6000884228.7, "margin": 0.922792825668891, "ratio": 0}


def test_segments_rows_pass_through_with_guards():
    c, _ = make([dict(SEG_ROW)])
    out = c.segments.business("600519")           # 2.0：门面默认 DataFrame
    assert float(out.loc[0, "tr"]) == 77724437925.48                        # 元，原样
    assert float(out.loc[0, "margin"]) == pytest.approx(0.922792825668891)  # 小数，原样

    c2, _ = make([dict(SEG_ROW, margin=92.28)])  # 百分数口径混入 → 超界
    with pytest.raises(DataError, match="margin"):
        c2.segments.business("600519")


def test_segments_snapshot_nested_guard():
    snap = {"coverage": {"has_business": True},
            "business": [dict(SEG_ROW)],
            "region": {"source": "clean", "report_sas": "2026:Q2",
                       "domestic": {"tr": 8.9e10, "pct": 0.9886, "margin": 0.895, "yoy": 0.036},
                       "overseas": {"tr": 1.0e9, "pct": 0.0114, "margin": 0.918, "yoy": -0.64}}}
    c, _ = make(dict(snap))
    out = c.segments.snapshot("600519")
    assert out["region"]["domestic"]["pct"] == pytest.approx(0.9886)

    bad = dict(snap)
    bad["region"] = dict(snap["region"], domestic=dict(snap["region"]["domestic"], pct=98.86))
    c2, _ = make(bad)
    with pytest.raises(DataError, match="pct"):
        c2.segments.snapshot("600519")


def test_forecast_snapshot_nested_shape_covers_guards():
    """批 B 回归：snapshot 的守护字段须能在 returns_shape 嵌套层找到。

    drift 曾把这些嵌套守护误报为「上游 shape 声明滞后」；声明补全后，
    嵌套换算（百分数→小数）与量级守护必须照常生效。
    """
    snap = {"symbol": "688008",
            "yjyg": dict(YJYG_ROW),
            "yjkb": dict(YJKB_ROW),
            "next_disclosure": {"report_date": "2026-09-30"}}
    c, _ = make(dict(snap))
    out = c.forecast.snapshot("688008")
    assert out["yjyg"]["rev_amp_upper"] == pytest.approx(0.46)
    assert out["yjkb"]["roe"] == pytest.approx(0.1128)

    bad = dict(snap)
    # percent 换算先于 ranges：roe=1128（原生百分数）换算后 11.28，超 [-2, 5] 上界
    bad["yjkb"] = dict(YJKB_ROW, roe=1128)
    c2, _ = make(bad)
    with pytest.raises(DataError, match="roe"):
        c2.forecast.snapshot("688008")


# ---- 目录透传与声明自检 ----

def test_catalog_passthrough_and_metric_meta():
    cat = load()
    kb = cat.function("kline.query_bars")
    assert kb["units"] == {"volume": "lot"} and kb["checks"] == ["volume_amount"]
    sc = cat.function("rptdom.statement_compare")
    assert sc["units"] == {"diffp": "percent"} and sc["checks"] == ["diffp_ratio"]
    assert cat.metric_meta("$ROE_TTM_LAST")["range"] == [-20, 20]
    m = cat.metric("$ROE_TTM_LAST")
    assert m["code"] == "$ROE_TTM_LAST" and m["range"] == [-20, 20]
    assert cat.metric_meta("$ACC") is None  # 非精选代码无声明


def test_validate_meta_rejects_bad_declarations():
    with pytest.raises(CatalogError, match="单位声明"):
        validate_meta({"units": {"x": "liang"}}, "demo")
    with pytest.raises(CatalogError, match="不在注册表"):
        validate_meta({"checks": ["nope"]}, "demo")
    with pytest.raises(CatalogError, match="range"):
        validate_meta({"ranges": {"x": [3, 1]}}, "demo")
    validate_meta({"units": {"v": "lot"}, "checks": ["volume_amount"],
                   "ranges": {"percent": [-1, 30]}}, "demo")


def test_apply_units_scalar_and_odd_shapes():
    assert convert_field("percent", None) is None
    assert convert_field("percent", "文本") == "文本"
    assert convert_field("lot", {"a": 34135, "b": None}) == {"a": 3413500.0, "b": None}
    assert convert_field("percent", [14.67, None]) == [0.1467, None]
    # 无声明的函数：结果原样返回
    cat = load()
    fn = cat.function("kline.snapshot")  # 未声明 units/ranges/checks
    out = apply_units({"close": 1.0}, fn, fname="kline.snapshot")
    assert out == {"close": 1.0}


# ---- valuation.hist_stats（估值历史统计，组合接口）----

HIST = {"avg": 3.027, "current": 3.334, "median": 3.032, "min": 2.473,
        "max": 3.661, "pct": 0.889, "count": 2,
        "series": [[1698076800, 2.55], [1792684800, 3.33]]}


def test_valuation_hist_stats_passthrough_and_validation():
    """2.0：hist_stats 返回统一信封；series 为 DataFrame（date ISO 升序）。"""
    c, _ = make(dict(HIST))
    out = c.valuation.hist_stats("600900", metric="pb", window="3y")
    assert out["ok"] is True
    assert out["data"]["avg"] == 3.027 and out["data"]["pct"] == 0.889
    ser = out["data"]["series"]
    assert list(ser["date"]) == ["2023-10-24", "2026-10-23"]  # unix+8h → ISO 升序
    assert list(ser["value"]) == [2.55, 3.33]
    assert out["meta"] == {"metric": "pb", "window": "3y"}

    with pytest.raises(Exception, match="metric"):
        c.valuation.hist_stats("600900", metric="roe")
    with pytest.raises(Exception, match="window"):
        c.valuation.hist_stats("600900", window="5y")  # 上限 3 年
    out6 = c.valuation.hist_stats("600900", metric="pb", window="6m")  # 半年窗口
    assert out6["data"]["current"] == 3.334


def test_normalized_query_shapes_cover_guards():
    """批 C 回归：normalize_with 继承链上的守护字段必须落在 returns_shape 里。

    catalog returns_shape 优先级是 YAML shape → normalize_with 目标 shape →
    inventory shape；fmt 行规范化的 shape 曾滞后于守护声明，导致 openapi
    文档少列字段（query_hgt 只列 3 个，实际返回 7 个）。
    """
    import wmshare as m

    cat = m.load()
    cases = {
        "equity.query_hgt": {"add_shares_pct", "free_shares_ratio", "total_shares_ratio"},
        "equity.query_holdernum": {"total_num_ratio", "avg_free_shares",
                                   "hold_ratio_total", "freehold_ratio_total"},
        "equity.query_institution_detail": {"total_shares_ratio", "free_shares_ratio"},
        "equity.query_institution_summary": {"all_shares_ratio", "total_shares_ratio"},
        "equity.query_national_team": {"shares_ratio", "shares_ratio_change"},
        "equity.query_pledge_detail": {"accum_pledge_tsr", "pf_hold_ratio"},
        "equity.query_pledge_market": {"csi300_chg", "pledge_market_value",
                                       "total_pledged_shares"},
        "equity.query_release": {"unlimited_ratio"},
        "equity.query_reorg": {"transfer_ratio"},
        "estimates.query_forecast": {"eps2", "eps3", "eps4", "pe2", "pe3", "pe4"},
        "estimates.query_forecast_detail": {"eps2", "eps3", "eps4", "pe2", "pe3", "pe4"},
        "intl.query_ccass": {"pct_of_issued"},
        "intl.query_shareholders": {"total_shares_ratio"},
    }
    for name, guarded in cases.items():
        shape = cat.function(name).get("returns_shape") or {}
        items = shape.get("items") if isinstance(shape.get("items"), dict) else shape
        fields = {f.get("name") for f in (items or {}).get("fields") or []
                  if isinstance(f, dict)}
        missing = guarded - fields
        assert not missing, f"{name}: 守护字段 {sorted(missing)} 不在 returns_shape"


# ---- 零守护域合同化 · 第一批（ranges 量级守护生效锚） ----

# 基线行 = live 实测 600519 / 000001 的合规值（ranges 内）
BONUS_SNAPSHOT = {
    "symbol": "600519", "name": "贵州茅台", "industry": "industry.S34",
    "quote_date": "2026-11-16", "is_suspend": False,
    "yield_ttm": 0.0362, "yield_lyr": 0.0362, "yield_3y_avg": 0.0437,
    "yield_3y_min": 0.0384, "yield_3y_trend": "valley",
    "pct_yield_3y": 0.554, "payout_ttm": 0.79, "dps_ttm": 51.98,
    "pe_ttm": 21.86, "mv": 1.796e12, "bonus_ttm": 6.503e10,
    "bonus_total": 4.011e11, "bonus_3y_trend": "valley",
    "bonus_npts_rate": 0.591,
}
MF_BOARD_ROW = {
    "symbol": "000001", "name": "平安银行", "industry": "industry.S48",
    "net_mf": 8.125e8, "elg_net": 3.941e7, "lg_net": 1.742e8,
    "md_net": 2.362e7, "sm_net": -2.372e8, "net_mv_ratio": 0.00347,
}


def test_zero_guard_domain_ranges_take_effect():
    """A 档第一批：bonus 聚合快照的 ranges 量级守护。

    这些接口此前零守护（guard_coverage 0%），本批登记 ranges 后，
    ×100 类量级错必须在 SDK 层拦截（percent 先换算后守护——
    本接口比率已是小数，负例直接取超界值）。
    """
    c, _ = make([dict(BONUS_SNAPSHOT, yield_ttm=3.62)])  # 百分数口径混入 → 超界
    with pytest.raises(DataError, match="yield_ttm"):
        c.bonus.snapshot("600519")

    c2, _ = make([{**BONUS_SNAPSHOT, "payout_ttm": 98.76}])
    with pytest.raises(DataError, match="payout_ttm"):
        c2.bonus.snapshot("600519")


def test_moneyflow_board_row_wise_guard():
    """board 全市场逐行守护：任一行超界即拦。"""
    rows = [dict(MF_BOARD_ROW), dict(MF_BOARD_ROW, net_mv_ratio=1.5)]
    c, _ = make(rows)
    with pytest.raises(DataError, match="net_mv_ratio"):
        c.moneyflow.board()


def test_moneyflow_snapshot_guard_ok():
    """合规基线正常通过（守护不误伤实测值）。"""
    c, _ = make([{**MF_BOARD_ROW, "quote_date": "2026-11-16",
                  "mf_date": "2026-11-13", "source": "store",
                  "net_5d": 9.96e7, "net_10d": 5.687e9,
                  "net_20d": 1.121e10, "trend_5d": "rising_volatile",
                  "trend_20d": "falling_volatile"}])
    out = c.moneyflow.snapshot("600519")
    assert out[0]["net_mv_ratio"] == 0.00347
