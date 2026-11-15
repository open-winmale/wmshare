"""友好 API 层测试：注册表同步、命名统一、调用翻译（mock 传输，不联网）。"""
import inspect

import pytest

from wmshare.api import FRIENDLY_INDEX, FRIENDLY_NAMESPACES
from wmshare.catalog import load
from wmshare.client import Client, WmshareError


class FakeSession:
    def __init__(self):
        self.calls = []
        self.token_count = 0
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
                    self._cls.token_count += 1
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True, "data": {"result": self._cls.eval_result}}
        R._cls = self
        return R()


@pytest.fixture()
def cli():
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  catalog=load(), session=FakeSession())


def last_xs(c: Client) -> list[str]:
    return [x for x in c.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


def test_registry_in_sync_with_classes():
    # 注册表每条都能解析到真实方法
    for _, ns, method, cn, _u in FRIENDLY_INDEX:
        assert ns in FRIENDLY_NAMESPACES, ns
        assert hasattr(FRIENDLY_NAMESPACES[ns], method), f"{ns}.{method}"
        assert cn
    # 每个公开方法都在注册表中（防漏文档）；组合接口单列 COMPOSITE_METHODS
    from wmshare.api import COMPOSITE_METHODS

    indexed = {(ns, m) for _, ns, m, _, _ in FRIENDLY_INDEX}
    composite = {(ns, m) for ns, names in COMPOSITE_METHODS.items() for m in names}
    for ns, cls in FRIENDLY_NAMESPACES.items():
        for name, member in inspect.getmembers(cls):
            if name.startswith("_") or not inspect.isfunction(member):
                continue
            assert (ns, name) in indexed or (ns, name) in composite, \
                f"方法 {ns}.{name} 未登记 FRIENDLY_INDEX 或 COMPOSITE_METHODS"
    # 反向：登记的组合接口必须真实存在，防止改名后残留
    for ns, name in composite:
        assert hasattr(FRIENDLY_NAMESPACES[ns], name), f"{ns}.{name} 不存在"


def test_symbol_param_uniform():
    """命名统一性：凡按标的查询的方法，首参必须是 symbol（全市场类方法可无 symbol）。"""
    for ns, cls in FRIENDLY_NAMESPACES.items():
        for name, member in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            params = list(inspect.signature(member).parameters)
            if "symbol" in params:
                assert params[1] == "symbol", \
                    f"{ns}.{name} 含 symbol 但非首参：{params}"


def test_kline_bars_dispatch(cli):
    cli.kline.bars("600519", n=5)
    assert last_xs(cli) == ['__r := kline.query_bars("600519", 5)',
                            'return kline.fmt_maps(__r)']
    cli.kline.bars("600519", n=5, adj="qfq", _raw=True)
    assert last_xs(cli) == ['return kline.query_bars_adj("600519", 5, "qfq")']
    # 复权序列也走规范化（输出字段与不复权一致）
    cli.kline.bars("600519", n=5, adj="qfq")
    assert last_xs(cli) == ['__r := kline.query_bars_adj("600519", 5, "qfq")',
                            'return kline.fmt_maps(__r)']


def test_kline_bars_period_dispatch(cli):
    """freq 分发：D 走日 K 原函数；W/M 走周期函数；非法值抛 UsageError。"""
    cli.kline.bars("AAPL", n=5, freq="W")
    assert last_xs(cli) == ['__r := kline.query_bars_period("AAPL", 5, "W")',
                            'return kline.fmt_maps(__r)']
    cli.kline.bars("AAPL", n=5, freq="monthly", adj="qfq")
    assert last_xs(cli) == [
        '__r := kline.query_bars_period_adj("AAPL", 5, "M", "qfq")',
        'return kline.fmt_maps(__r)']
    # D/None 保持原路径（回归：不因新参数改变既有生成行）
    for freq in (None, "D", "daily", ""):
        cli.kline.bars("600519", n=5, freq=freq)
        assert last_xs(cli) == ['__r := kline.query_bars("600519", 5)',
                                'return kline.fmt_maps(__r)']
    with pytest.raises(WmshareError):
        cli.kline.bars("600519", n=5, freq="Q")
    # 区间 + 周频：limit 取 max_limit（夹具默认 10000）
    cli.session.eval_result = [{"date": "2026-11-06", "close": 342.37}]
    bars = cli.kline.bars("AAPL", freq="W", begin="2026-01-01", end="2026-11-30")
    assert last_xs(cli) == ['__r := kline.query_bars_period("AAPL", 500, "W")',
                            'return kline.fmt_maps(__r)']
    assert [b["date"] for b in bars] == ["2026-11-06"]


def test_last_returns_normalized_latest_row(cli):
    # last() 取 store.latest 的单行原始记录（非数组），由 SDK 收口成 bars() 同款 9 字段
    raw = {"annual": 2026, "sampling": "D294", "samplingTs": 1792512000,
           "open": 1300.0, "high": 1320.0, "low": 1290.0, "close": 1309.69,
           "volume": 30000, "amount": 3929070000.0, "percent": 1.234}
    cli.session.eval_result = dict(raw)
    bar = cli.kline.last("600519")
    assert bar["date"] == "2026-10-21" and bar["close"] == 1309.69
    assert bar["sas"] == "2026:D294"
    assert bar["percent"] == pytest.approx(0.01234)
    assert bar["volume"] == 3000000.0
    assert last_xs(cli) == ['return kline.query_last("600519")']
    cli.session.eval_result = [{"date": "2026-10-21", "net_mf": -161756700}]
    assert cli.moneyflow.last("600519") == {"date": "2026-10-21", "net_mf": -161756700}
    cli.session.eval_result = []
    assert cli.kline.last("600519") is None


def test_statements_translation(cli):
    cli.statements.income("600519", years=3)
    xs = last_xs(cli)
    assert xs[0] == 'xs.require("sys/rptdom/init.xs")'
    assert xs[-1] == ('return rptdom.statement("600519", "fin.income_statement", '
                      '{"scope": "合并", "n": 3})')


def test_notice_and_dividend(cli):
    cli.notice.list("600519", window="3m", keyword="回购", limit=5)
    assert last_xs(cli) == ['__r := notice.query_by_symbol("600519", "90", "回购", 5)',
                            'return notice.fmt_maps(__r)']
    cli.notice.list("600519", window="3m", keyword="回购", limit=5, _raw=True)
    assert last_xs(cli) == ['return notice.query_by_symbol("600519", "90", "回购", 5)']
    cli.notice.find("600519", "2026-01-01", "2026-03-31", keyword="回购", limit=10)
    assert last_xs(cli) == ['__r := notice.query_find("2026-01-01", "2026-03-31", "回购", "600519", 10)',
                            'return notice.fmt_maps(__r)']
    cli.dividend.yield_ttm("600519")
    assert last_xs(cli) == ['return bonus.snapshot_yield_ttm("600519")']


def test_notice_window_rejects_unknown_token(cli):
    from wmshare import UsageError
    with pytest.raises(UsageError, match="未知窗口"):
        cli.notice.list("600519", window="2w")
    with pytest.raises(UsageError, match="未知窗口"):
        cli.notice.recent(window="2w")
    with pytest.raises(UsageError, match="未知窗口"):
        cli.notice.by_category("回购", window="2w")


def test_dividend_last_returns_normalized_latest_row(cli):
    cli.session.eval_result = [{"announce": "2026-06-22", "ex_div": "2026-06-26",
                                "dps": 28.02}]
    assert cli.dividend.last("600519") == cli.session.eval_result[0]
    assert last_xs(cli) == ['__r := bonus.query_list("600519", 1)',
                            'return bonus.fmt_maps(__r)']
    cli.session.eval_result = []
    assert cli.dividend.last("600519") is None


def test_dynamic_facade_accepts_positional_args(cli):
    cli.kline.screen_above_ma20("600519")
    assert last_xs(cli) == ['return kline.screen_above_ma20("600519")']
    cli.dividend.query_dps_window("600519", "3y")
    assert last_xs(cli) == ['return bonus.query_dps_window("600519", "3y")']
    with pytest.raises(WmshareError, match="同时以位置和关键字"):
        cli.kline.screen_above_ma20("600519", sym="600519")
    with pytest.raises(WmshareError, match="最多接受"):
        cli.kline.screen_above_ma20("600519", "extra")


def test_notice_find_normalizes_stock_code(cli):
    cli.notice.find("sh.600519.SH", "2026-01-01", "2026-01-31")
    assert last_xs(cli)[0] == ('__r := notice.query_find("2026-01-01", "2026-01-31", '
                               '"", "600519", 50)')


def test_raw_plus_date_range_is_rejected(cli):
    from wmshare import UsageError
    with pytest.raises(UsageError, match="_raw=True"):
        cli.kline.bars("600519", begin="2026-01-01", end="2026-01-31", _raw=True)
    with pytest.raises(UsageError, match="_raw=True"):
        cli.moneyflow.bars("600519", begin="2026-01-01", end="2026-01-31", _raw=True)


def test_close_respects_injected_session():
    class S:
        closed = False
        def close(self):
            self.closed = True
    s = S()
    c = Client(base_url="https://t.example", client_id="i", client_secret="s",
               catalog=load(), session=s)
    c.close()
    assert s.closed is False
    owned = Client(base_url="https://t.example", client_id="i", client_secret="s",
                   catalog=load())
    owned.session.close = lambda: None
    owned.close()  # 自建 session 应可关闭且不抛错


def test_indicator_anti_fabrication(cli):
    with pytest.raises(KeyError, match="未知指标"):
        cli.indicator.get("600519", "$NOT_EXIST")
    cli.indicator.get("600519", "$PE_TTM_LAST")
    assert last_xs(cli) == ["return $PE_TTM_LAST"]
    cli.indicator.metrics("600519", ["$PE_TTM_LAST", "$ROE_TTM_LAST"])
    assert last_xs(cli) == ["return {\"$PE_TTM_LAST\": $PE_TTM_LAST, \"$ROE_TTM_LAST\": $ROE_TTM_LAST}"]


def test_info_profile(cli):
    cli.info.profile("600519")
    assert last_xs(cli) == ['return {"name": $NAME, "industry": $INDUSTRY_CUR, '
                            '"style_industry": $STYLE_INDUSTRY, "org_type": $ORG_ORGTYPE, '
                            '"listing_date": $ORG_LISTINGDATE}']


def test_unknown_param_still_guards(cli):
    # 友好层为强类型签名：越权参数在 Python 层即被拒
    with pytest.raises(TypeError):
        cli.kline.bars("600519", bogus=1)
    # 通用 call() 层同守
    from wmshare.client import WmshareError
    with pytest.raises(WmshareError, match="未知参数"):
        cli.call("kline.query_bars", sym="600519", bogus=1)


def test_getattr_delegates_catalog_functions(cli):
    """__getattr__ 兜底：友好类未显式包装的目录函数经属性直达，零遮蔽。"""
    # kline 命名空间的筛选器（未显式包装）可直达
    cli.kline.screen_above_ma20(sym="600519")
    assert last_xs(cli) == ['return kline.screen_above_ma20("600519")']
    # dividend 命名空间映射到目录 bonus 命名空间，窗口函数同理
    cli.dividend.query_dps_window(sym="600519", window="3y")
    assert last_xs(cli) == ['return bonus.query_dps_window("600519", "3y")']
    # 委托函数带可读名（便于调试与 repr）
    fn = cli.kline.screen_above_ma20
    assert fn.__name__ == "screen_above_ma20"
    assert fn.__qualname__ == "KlineApi.screen_above_ma20"


def test_getattr_rejects_non_catalog_names(cli):
    """目录之外的名字显式 AttributeError，且提示可发现性入口。"""
    with pytest.raises(AttributeError, match="cat.search"):
        cli.kline.no_such_fn
    # 双下划线永不委托（不干扰 pickle/copy 等协议探测）
    with pytest.raises(AttributeError):
        cli.kline.__deepcopy__


def test_dividend_screeners_promoted(cli):
    """杀手锏筛选器提为显式方法，可经 cli.dividend.screen_* 调用。"""
    cli.dividend.screen_quality("600519", min_yield=0.03, payout_max=1.0)
    # payout_min 未传 → 补 nil 保位（调用字面量按位置绑定，跳洞会把 1.0 错绑进 payout_min）
    assert last_xs(cli) == ['return bonus.screen_quality("600519", 0.03, nil, 1.0)']
    cli.dividend.screen_high_yield("600519")
    assert last_xs(cli) == ['return bonus.screen_high_yield("600519")']
    cli.dividend.screen_undervalued_yield("600519", min_yield=0.04)
    assert last_xs(cli) == ['return bonus.screen_undervalued_yield("600519", 0.04)']


def test_screener_translation(cli):
    """选股门面：单票筛选器直译目录合同；宽度接口默认由服务端解析最新查询索引。"""
    cli.screener.screen_limit_up("600519")
    assert last_xs(cli) == ['return kline.screen_limit_up("600519")']
    cli.screener.screen_momentum_20d("600519", min_chg=0.15)
    assert last_xs(cli) == ['return kline.screen_momentum_20d("600519", 0.15)']
    cli.screener.screen_volume_spike("600519")
    assert last_xs(cli) == ['return kline.screen_volume_spike("600519", 1.5)']
    cli.screener.index_breadth_summary()
    assert last_xs(cli) == ['return kline.index_breadth_summary(LatestIndexKey())']
    cli.screener.index_top_movers(limit=10, desc=False)
    assert last_xs(cli) == ['return kline.index_top_movers(LatestIndexKey(), 10, false)']
    # 其余 kline 目录筛选器经属性直达（委托），零遮蔽
    cli.screener.screen_above_ma120("600519")
    assert last_xs(cli) == ['return kline.screen_above_ma120("600519")']
    with pytest.raises(AttributeError, match="cat.search"):
        cli.screener.no_such_fn


def test_screener_top_movers_limit_clamped(cli):
    """eval 拼脚本路径同样受 max_limit/10000 防脱库钳制（不发请求直接拒绝）。"""
    from wmshare import LimitError
    with pytest.raises(LimitError, match="超过单次上限"):
        cli.screener.index_top_movers(limit=20000)
    cli.screener.index_top_movers(limit=10)
    assert last_xs(cli) == ['return kline.index_top_movers(LatestIndexKey(), 10, true)']


def test_screener_query_builds_index_spec(cli):
    """全市场条件选股：一条 XS 出 count + 前 N 行（服务端索引，不是逐票 eval）。"""
    cli.session.eval_result = {"count": 108,
                               "rows": [["900948", "伊泰B股", 0.2104, 0.1631, False]]}
    res = cli.screener.query(
        "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15 && !$IS_ST",
        order="$BONUS_RATE_3Y_AVG_LAST", limit=10)
    xs = last_xs(cli)
    assert xs[0] == "idx := LatestIndexKey()"
    assert xs[1].startswith("_ := INDEX_FIELD_LOAD(idx, ") and "$IS_ST" in xs[1]
    assert ('"where": "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15 && !$IS_ST"'
            in xs[2])
    assert xs[2].endswith('"result": "row_ids"})')
    assert ('"order": "$BONUS_RATE_3Y_AVG_LAST", "order_desc": true, "limit": 10, '
            '"offset": 0') in xs[3]
    assert xs[4].startswith("return") and "LEN(ids)" in xs[4]
    # count 是全市场命中数（不受 limit 截断）；行键 = symbol/name + 指标码原文
    assert res["count"] == 108
    assert res["rows"] == [{"symbol": "900948", "name": "伊泰B股",
                            "$BONUS_RATE_3Y_AVG_LAST": 0.2104,
                            "$ROE_TTM_LAST": 0.1631, "$IS_ST": False}]


def test_screener_query_fields_and_count_only(cli):
    """fields 覆盖默认列集合；limit=0 只查 count（不再写第二条索引查询）。"""
    cli.session.eval_result = {"count": 0, "rows": []}
    cli.screener.query("$ROE_TTM_LAST > 0.3", fields=["$PE_TTM_LAST"])
    xs = last_xs(cli)
    assert xs[1] == "_ := INDEX_FIELD_LOAD(idx, $SYMBOL, $NAME, $PE_TTM_LAST)"
    assert '"order"' not in xs[3]          # 未传 order 不生成 order 键
    cli.session.eval_result = {"count": 164, "rows": []}
    assert cli.screener.query("$ROE_TTM_LAST > 0.3", limit=0) == {"count": 164,
                                                                  "rows": []}
    xs = last_xs(cli)
    assert len([ln for ln in xs if "INDEX_QUERY_SPEC" in ln]) == 1
    assert xs[-1] == 'return {"count": LEN(ids), "rows": []}'


def test_screener_query_validates(cli):
    """where/order/fields 的指标码走目录白名单；Python 式布尔词直接报 XS 语法。"""
    from wmshare import CatalogError, UsageError
    with pytest.raises(CatalogError, match="防编造"):
        cli.screener.query("$NOT_A_CODE > 1")
    with pytest.raises(UsageError, match="XS 表达式"):
        cli.screener.query("$ROE_TTM_LAST > 0.15 and 1")
    with pytest.raises(UsageError, match=r"没有 \$指标码"):
        cli.screener.query("ROE_TTM_LAST > 0.15")
    with pytest.raises(UsageError, match="order 必须是单个指标码"):
        cli.screener.query("$ROE_TTM_LAST > 0.15", order="roe")
    with pytest.raises(CatalogError, match="防编造"):
        cli.screener.query("$ROE_TTM_LAST > 0.15", fields=["$PE_NO_SUCH_LAST"])
    with pytest.raises(UsageError, match="idx 只接受索引键"):
        cli.screener.query("$ROE_TTM_LAST > 0.15", idx='index.cnall" }')


def test_screener_query_limit_df_and_passthrough(cli):
    """limit 受 max_limit 钳制；_df 只转 rows；上游异常形态原样透传。"""
    from wmshare import LimitError
    with pytest.raises(LimitError, match="超过单次上限"):
        cli.screener.query("$ROE_TTM_LAST > 0.15", limit=20000)
    pd = pytest.importorskip("pandas")
    cli.session.eval_result = {"count": 1, "rows": [["600519", "贵州茅台", 0.33]]}
    df = cli.screener.query("$ROE_TTM_LAST > 0.3", _df=True)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["symbol", "name", "$ROE_TTM_LAST"]
    cli.session.eval_result = [{"ok": True}]
    assert cli.screener.query("$ROE_TTM_LAST > 0.3") == [{"ok": True}]


def test_screener_breadth_supports_df(cli):
    """列表返回的宽度接口支持 _df=True（模块 docstring 的承诺，列表方法逐一对齐）。"""
    pd = pytest.importorskip("pandas")   # CI 离线环境不装可选依赖
    cli.session.eval_result = [{"label": "i_涨停", "count": 109, "pct_of_total": 1.9}]
    df = cli.screener.index_breadth_bins(_df=True)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["label", "count", "pct_of_total"]
    assert df.iloc[0]["label"] == "涨停"   # 服务端排序前缀在展示层剥除


def test_screener_bins_label_prefix_stripped(cli):
    """分桶 label/bin 的服务端排序前缀（i_/h_/g_）对用户是噪音，友好层剥除（2026-10-30 实测）。"""
    cli.session.eval_result = [
        {"label": "i_涨停", "count": 32, "pct_of_total": 0.6},
        {"label": "h_+5%~10%", "count": 113, "pct_of_total": 2.0},
    ]
    rows = cli.screener.index_breadth_bins()
    assert [r["label"] for r in rows] == ["涨停", "+5%~10%"]
    cli.session.eval_result = [{"bin": "g_+3%~5%", "industry": "银行", "count": 4}]
    rows = cli.screener.index_breadth_bin_industries()
    assert rows[0]["bin"] == "+3%~5%"
    # 非 dict/非字符串行原样透传，不误伤
    cli.session.eval_result = [{"label": "涨停"}, {"x": 1}, "raw"]
    assert cli.screener.index_breadth_bins() == [{"label": "涨停"}, {"x": 1}, "raw"]
