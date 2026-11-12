"""分批执行器契约测试（mock 传输，不联网）。

核心目标守护：批量接口的**存在理由是绕开 429 限流**——服务端按请求次数限流
（免费档 500 次/小时、5000 次/日），因此「N 个标的 = ⌈N/batch_size⌉ 次请求」
必须是可执行的断言，而不是文档里的口号。
"""
import pytest

from wmshare.catalog import load
from wmshare.client import BatchResult, Client
from wmshare.errors import LimitError, UsageError


class CountingSession:
    """记录 eval 请求次数的假传输；可按批次注入错误。"""

    def __init__(self, fail_at: int | None = None, fail_code: str = "rate_limited",
                 fail_status: int = 429):
        self.eval_calls = 0
        self.fail_at = fail_at          # 第 N 次 eval 调用抛错（1-based）
        self.fail_code = fail_code
        self.fail_status = fail_status

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
                if cls.fail_at is not None and cls.eval_calls == cls.fail_at:
                    return {"success": False,
                            "error": {"code": cls.fail_code,
                                      "message": f"injected failure #{cls.eval_calls}"}}
                # 按请求体里的代码回填结果，验证聚合正确性
                body = json or {}
                syms = []
                for ln in body.get("xs_lines") or []:
                    if ln.startswith("return {"):
                        syms = [p.split(":")[0].strip().strip('"')
                                for p in ln[len("return {"):-1].split(", ")]
                return {"success": True,
                        "data": {"result": {s: {"close": 10.0} for s in syms}}}

        return R()


def make_client(session=None, **kw):
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=load(), session=session or CountingSession(), **kw)


def test_whole_market_needs_12_requests():
    """A 股全市场 5691 家 + 500/批 → 恰好 12 次请求（而非 5691 次）。"""
    s = CountingSession()
    c = make_client(s)
    codes = [f"{i:06d}" for i in range(5691)]
    res = c.batch_all("kline.snapshot", codes)
    assert s.eval_calls == 12, f"应 12 次请求，实际 {s.eval_calls}"
    assert res.requests == 12
    assert len(res.results) == 5691
    assert not res.errors


def test_batch_size_controls_request_count():
    s = CountingSession()
    c = make_client(s)
    codes = [f"{i:06d}" for i in range(1000)]
    c.batch_all("kline.snapshot", codes, batch_size=250)
    assert s.eval_calls == 4


def test_dedupe_before_chunking():
    """重复代码先去重再切片——避免把同一标的重复塞进多批、浪费额度。"""
    s = CountingSession()
    c = make_client(s)
    res = c.batch_all("kline.snapshot", ["600519"] * 600)
    assert res.requests == 1
    assert list(res.results) == ["600519"]


def test_symbol_normalization_before_chunking():
    c = make_client()          # market 缺省 = cn
    res = c.batch_all("kline.snapshot", ["sh.600519.SH", "cn.000001", "sz.300750"])
    assert list(res.results) == ["600519", "000001", "300750"]


# ---- 跨市场边界（2026-10-29 实测：混批会取到错误数据） --------------------

def test_cross_market_batch_is_rejected():
    """cn 客户端混入港股代码必须报错——实测网关不拒但数据是错的
    （同一港股标的：close 387.6 vs 377.6、percent +0.62% vs -2.58%）。"""
    from wmshare.errors import UsageError

    c = make_client()
    with pytest.raises(UsageError, match="不属于当前市场") as ei:
        c.batch_all("kline.snapshot", ["600519", "00700"])
    msg = str(ei.value)
    assert "港股" in msg                      # 指出代码归属
    assert "跨市场" in msg
    assert 'Client(market="cn"' in msg        # 给出可执行改法
    assert "29 次请求" in msg                 # 给出跨市场总量算式


def test_cross_market_rejected_in_all_batch_entries():
    from wmshare.errors import UsageError

    c = make_client()
    for call in (lambda: c.batch_all("kline.snapshot", ["600519", "00700"]),
                 lambda: c.batch_iter("kline.snapshot", ["600519", "00700"]),
                 lambda: c.call_batch("kline.snapshot", ["600519", "00700"]),
                 lambda: c.kline.batch_live(["600519", "00700"])):
        with pytest.raises(UsageError, match="不属于当前市场"):
            call()


def test_unknown_codes_are_not_rejected():
    """代码表里都没有的代码（新股/ETF/指数）放行，不误伤。"""
    c = make_client()
    res = c.batch_all("kline.snapshot", ["600519", "999999"])
    assert "[600519]" in str([list(res.results)]) or set(res.results) == {"600519", "999999"}


def test_same_market_batch_still_works():
    c = make_client()
    res = c.batch_all("kline.snapshot", ["600519", "000001", "300750"])
    assert len(res.results) == 3 and res.requests == 1


def test_hk_client_rejects_cn_codes():
    from wmshare.errors import UsageError

    c = make_client(market="hk")
    with pytest.raises(UsageError, match="A 股"):
        c.batch_all("kline.snapshot", ["00700", "600519"])


def test_empty_symbols_yields_nothing():
    s = CountingSession()
    c = make_client(s)
    assert list(c.batch_iter("kline.snapshot", [])) == []
    res = c.batch_all("kline.snapshot", [])
    assert res.results == {} and res.requests == 0
    assert s.eval_calls == 0


def test_batch_iter_yields_per_batch():
    c = make_client()
    parts = list(c.batch_iter("kline.snapshot", [f"{i:06d}" for i in range(1200)],
                              batch_size=500))
    assert [len(p.results) for p in parts] == [500, 500, 200]
    assert all(p.requests == 1 for p in parts)


def test_batch_size_validation():
    c = make_client(max_limit=500)
    with pytest.raises(UsageError, match="batch_size=600 超过单批上限 500"):
        c.batch_all("kline.snapshot", ["600519"], batch_size=600)
    with pytest.raises(UsageError, match="batch_size 必须为正整数"):
        c.batch_all("kline.snapshot", ["600519"], batch_size=0)


def test_rate_limit_stops_with_resume_hint():
    """429 是按时间窗口的配额：必须停止并给出续跑位置，而不是继续连败。"""
    s = CountingSession(fail_at=3)
    c = make_client(s)
    codes = [f"{i:06d}" for i in range(3000)]      # 6 批，第 3 批失败
    with pytest.raises(LimitError) as ei:
        c.batch_all("kline.snapshot", codes)
    msg = str(ei.value)
    assert "第 3/6 批" in msg
    assert "已完成 1000 / 3000 个标的" in msg
    assert "codes[1000:]" in msg
    assert "500 次/小时" in msg
    assert s.eval_calls == 3                        # 第 3 批失败后不再发请求


def test_rate_limit_stops_even_in_skip_mode():
    """skip 是批级容错，但 429 例外——配额耗尽时跳过无用，必须停。"""
    s = CountingSession(fail_at=2)
    c = make_client(s)
    with pytest.raises(LimitError, match="触发限流"):
        c.batch_all("kline.snapshot", [f"{i:06d}" for i in range(2000)],
                    on_batch_error="skip")
    assert s.eval_calls == 2


def test_skip_mode_drops_failed_batch_only():
    """非 429 的批失败可跳过，其余批照常返回，失败批记进 errors。"""
    s = CountingSession(fail_at=2, fail_code="XS_EVAL", fail_status=500)
    c = make_client(s)
    codes = [f"{i:06d}" for i in range(1500)]       # 3 批，第 2 批失败
    res = c.batch_all("kline.snapshot", codes, on_batch_error="skip")
    assert len(res.results) == 1000                 # 第 1、3 批
    assert len(res.errors) == 1
    assert "batch#2[500:1000]" in res.errors
    assert res.requests == 3


def test_raise_mode_propagates_batch_failure():
    s = CountingSession(fail_at=2, fail_code="XS_EVAL", fail_status=500)
    c = make_client(s)
    with pytest.raises(Exception, match="injected failure"):
        c.batch_all("kline.snapshot", [f"{i:06d}" for i in range(1500)])


def test_ticket_level_skip_is_much_costlier():
    """防回潮：票级 skip（call_batch）请求数 = N，批级（batch_all）= 批数。

    这条断言就是「不要用 call_batch(on_error='skip') 做容错」的可执行证据。
    票级同样受 max_limit 约束（400 < 500），所以对比用 400 个代码。
    """
    codes = [f"{i:06d}" for i in range(400)]

    s1 = CountingSession()
    c1 = make_client(s1)
    c1.call_batch("kline.snapshot", codes, on_error="skip")
    ticket_level = s1.eval_calls

    s2 = CountingSession()
    c2 = make_client(s2)
    c2.batch_all("kline.snapshot", codes, on_batch_error="skip")
    batch_level = s2.eval_calls

    assert ticket_level == 400, "票级 skip 应逐票发请求"
    assert batch_level == 1, "批级应 1 次请求"
    assert ticket_level >= 100 * batch_level


def test_batch_result_requests_default_zero():
    assert BatchResult().requests == 0


def test_call_batch_over_limit_mentions_batch_all():
    c = make_client(max_limit=500)
    with pytest.raises(LimitError, match="batch_all"):
        c.call_batch("kline.snapshot", [f"{i:06d}" for i in range(501)])


# ---- 参数与边界空白（2026-10-29 审计补齐） -------------------------------

def test_batch_entries_have_no_df_param():
    """批量入口不提供 _df：它会让每标的值变成 DataFrame，聚合后 to_df 失真。

    长表请用 BatchResult.to_df()；单标的多行读 .results[代码]。
    """
    import inspect

    for fn in (Client.batch_all, Client.batch_iter):
        params = inspect.signature(fn).parameters
        assert "_df" not in params, f"{fn.__name__} 不应有 _df 参数"
        assert "on_batch_error" in params, f"{fn.__name__} 应使用 on_batch_error（批级语义）"
        assert "on_error" not in params, f"{fn.__name__} 不应有 on_error（那是票级，属 call_batch）"
    # 签名之外还要挡住经 **kwargs 透传（否则形同虚设，已实测踩过）
    c = make_client()
    with pytest.raises(UsageError, match="批量入口不支持 _df"):
        c.batch_all("kline.snapshot", ["600519"], _df=True)
    with pytest.raises(UsageError, match="批量入口不支持 _df"):
        c.batch_iter("kline.snapshot", ["600519"], _df=True)


def test_batch_entries_are_positional_only():
    """name/symbols 是 positional-only——写 batch_all(name=...) 必须报 TypeError。"""
    import inspect

    for fn in (Client.batch_all, Client.batch_iter):
        kinds = {n: p.kind for n, p in inspect.signature(fn).parameters.items()}
        assert kinds["name"] is inspect.Parameter.POSITIONAL_ONLY
        assert kinds["symbols"] is inspect.Parameter.POSITIONAL_ONLY
    c = make_client()
    with pytest.raises(TypeError):
        c.batch_all(name="kline.snapshot", symbols=["600519"])


def test_units_native_and_raw_passthrough():
    """_units='native' 与 _raw=True 在批量入口透传到每批（不报错、结果完整）。"""
    c = make_client()
    r = c.batch_all("kline.snapshot", ["600519", "000001"], _units="native")
    assert len(r.results) == 2
    r = c.batch_all("kline.snapshot", ["600519", "000001"], _raw=True)
    assert len(r.results) == 2
    with pytest.raises(UsageError, match='_units 只支持'):
        c.batch_all("kline.snapshot", ["600519"], _units="bogus")


def test_max_limit_none_defaults_to_500():
    """max_limit=None（关闭单次上限）时，batch_size 仍默认 500。"""
    s = CountingSession()
    c = make_client(s, max_limit=None)
    r = c.batch_all("kline.snapshot", [f"{i:06d}" for i in range(1200)])
    assert r.requests == 3, "1200 / 500 → 3 批"


def test_batch_iter_validates_eagerly():
    """参数错误在调用时报错，不等首次迭代（生成器惰性校验是坑）。"""
    c = make_client(max_limit=500)
    with pytest.raises(UsageError, match="超过单批上限"):
        c.batch_iter("kline.snapshot", ["600519"], batch_size=999)
    with pytest.raises(UsageError, match='on_batch_error 只支持'):
        c.batch_iter("kline.snapshot", ["600519"], on_batch_error="ignore")


def test_calc_limit_exceeded_is_batch_error_not_rate_limit():
    """CALC_LIMIT_EXCEEDED（算力超限，400）与 429 限流不同：可跳过、不必停下。

    与 429 的处理区别是刻意的——配额是时间窗口（停），算力是单批过大（调小 batch_size）。
    """
    # raise 模式：直接抛（带服务端消息）
    c1 = make_client(CountingSession(fail_at=2, fail_code="CALC_LIMIT_EXCEEDED",
                                     fail_status=400))
    with pytest.raises(Exception, match="CALC_LIMIT_EXCEEDED"):
        c1.batch_all("kline.snapshot", [f"{i:06d}" for i in range(1500)])

    # skip 模式：跳过该批、继续其余批
    s2 = CountingSession(fail_at=2, fail_code="CALC_LIMIT_EXCEEDED", fail_status=400)
    c2 = make_client(s2)
    res = c2.batch_all("kline.snapshot", [f"{i:06d}" for i in range(1500)],
                       on_batch_error="skip")
    assert len(res.results) == 1000
    assert "batch#2[500:1000]" in res.errors
    assert s2.eval_calls == 3


def test_batch_iter_close_midway():
    """逐批消费可随时 break/close，无副作用（长任务中断的常见用法）。"""
    c = make_client()
    g = c.batch_iter("kline.snapshot", [f"{i:06d}" for i in range(2000)])
    first = next(g)
    assert len(first.results) == 500
    g.close()
    assert len(list(c.batch_iter("kline.snapshot", ["600519"]))) == 1


@pytest.mark.parametrize("n,size,expected", [
    (1, 500, 1), (500, 500, 1), (501, 500, 2),
    (1200, 250, 5), (1200, 500, 3), (1200, 1000, 2),
    (5691, 500, 12),
])
def test_request_count_is_conserved(n, size, expected):
    """请求数守恒：⌈N / batch_size⌉——这是绕开 429 的量化保证。"""
    s = CountingSession()
    c = make_client(s, max_limit=1000)
    r = c.batch_all("kline.snapshot", [f"{i:06d}" for i in range(n)], batch_size=size)
    assert s.eval_calls == expected
    assert r.requests == expected


def test_quota_exhaustion_stops_with_quota_hint():
    """配额耗尽（EC_BALANCE_EXHAUSTED）不是限流：必须停并给配额指引，而非「500 次/小时」文案。"""
    from wmshare.errors import QuotaError

    s = CountingSession(fail_at=3, fail_code="EC_BALANCE_EXHAUSTED")
    c = make_client(s)
    codes = [f"{i:06d}" for i in range(3000)]      # 6 批，第 3 批失败
    with pytest.raises(QuotaError) as ei:
        c.batch_all("kline.snapshot", codes)
    msg = str(ei.value)
    assert "配额耗尽" in msg
    assert "第 3/6 批" in msg
    assert "codes[1000:]" in msg
    assert "默认应用" in msg                        # 指引：换默认应用/等周补/充值
    assert "500 次/小时" not in msg                 # 限流文案对配额场景是误导
    assert ei.value.code == "EC_BALANCE_EXHAUSTED"
    assert s.eval_calls == 3
