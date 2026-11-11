"""index.trend 分位口径回归（防「拿最旧点当今天」类静默错误）。

背景：服务端 ``indices.trend`` 返回的 base 序列是 **新→旧**（cursor.ds 原始顺序）。
早期 SDK 实现用 ``reversed(pts)`` 取当前值，实际取到最旧点，于是把 2020 年的
分位当今天展示；demo 罐头当时又按升序生成、用 ``pts[-1]``，方向相反，单测全绿
也抓不到。以下四条断言锁死方向、基准点与公式。
"""
from __future__ import annotations

import pytest

from wmshare._demo import demo_client

WEEKS = 120


def _trend():
    return demo_client().index.trend("index.hs300")


def test_points_are_newest_first():
    """points[0] 必须是最新点（服务端 cursor.ds 顺序），不能是升序。"""
    t = _trend()
    dates = [p["date"] for p in t["points"]]
    assert dates, "demo trend 不应为空"
    assert dates == sorted(dates, reverse=True), f"points 必须新→旧，实际首尾 {dates[0]} / {dates[-1]}"
    # as_of 是快照日，可能晚于最后一个周频点（demo 罐头即如此），但不得早于它
    assert t["as_of"] >= dates[0], f"as_of {t['as_of']} 早于最新点 {dates[0]}"


def test_percentile_anchors_on_latest_point():
    """分位基准点是 points[0]，不是序列末尾。"""
    t = _trend()
    pts = t["points"]
    latest = next(p for p in pts if isinstance(p.get("pe"), (int, float)) and p["pe"] > 0)
    assert t["pe_pct"] is not None
    # 用最新点独立复算，必须与 SDK 输出逐位一致
    vals = sorted(p["pe"] for p in pts if isinstance(p.get("pe"), (int, float)) and p["pe"] > 0)
    cur = latest["pe"]
    if len(vals) >= 2:
        rank0 = (sum(1 for v in vals if v < cur) + sum(1 for v in vals if v <= cur) - 1) / 2
        assert t["pe_pct"] == pytest.approx(rank0 / (len(vals) - 1)), "分位应与最新点独立复算一致"
    # 用最旧点复算，除非两端分位恰好相同，否则不应等于 SDK 输出
    oldest = next(p for p in reversed(pts) if isinstance(p.get("pe"), (int, float)) and p["pe"] > 0)
    if oldest["pe"] != cur and len(vals) >= 2:
        old_rank0 = (sum(1 for v in vals if v < oldest["pe"]) + sum(1 for v in vals if v <= oldest["pe"]) - 1) / 2
        assert t["pe_pct"] != pytest.approx(old_rank0 / (len(vals) - 1)), \
            "分位疑似仍锚定最旧点（reversed 回归）"


def test_percentile_formula_matches_frontend():
    """公式逐位复刻前端 percentileRank：rank0=(lt+le-1)/2，除以 n-1，并列取中点。"""
    from wmshare.api import IndexApi

    pct = IndexApi.__dict__["trend"]  # 存在性守卫
    assert pct is not None
    t = _trend()
    pts = t["points"]
    pbs = sorted(p["pb"] for p in pts if isinstance(p.get("pb"), (int, float)) and p["pb"] > 0)
    cur = next(p["pb"] for p in pts if isinstance(p.get("pb"), (int, float)) and p["pb"] > 0)
    expected = ((sum(1 for v in pbs if v < cur) + sum(1 for v in pbs if v <= cur) - 1) / 2) / (len(pbs) - 1)
    assert t["pb_pct"] == pytest.approx(expected)


def test_window_and_truncation_flags():
    """窗口与截断标记齐备；sample 不足 10 年时 p10 必须为 None（不拿短窗口冒充）。"""
    t = demo_client().index.trend("index.hs300", "10y")
    assert t["window"] == "10y"
    assert "win_n" in t and "win_trunc" in t and "pct" in t
    assert t["pct_source"] in ("server", "client")
    assert t["dv_has_history"] is False, "股息率无历史序列，不得声称有"
    node = (t["pct"] or {}).get("pe") or {}
    if t["win_trunc"]:
        # 只看所选档位（p10），不能用「p 为 None」放行——服务端的 p 恒为 5y 分位，
        # 它非 None 恰恰是 bug 的表征。
        assert t["pe_pct"] is None and node.get("p10") is None, \
            "10y 窗口被截断时不得给出分位，也不得降级到更短窗口"


def test_pe_pct_follows_window():
    """``pe_pct`` 必须按入参 window 取档（p3/p5/p10），不能恒取 5 年分位。

    回归背景：服务端 ``pct.<col>.p`` **恒为 5 年分位**（pct_bundle 里 "p": w5["p"]），
    旧实现直接读 p，于是 ``trend(k,"3y")["pe_pct"]`` 返回的是 5 年分位。live 实测
    hs300 时 p=0.7671、p3=0.6119，差 15.5 个百分点且完全静默。
    """
    cli = demo_client()
    t3 = cli.index.trend("index.hs300", "3y")
    t5 = cli.index.trend("index.hs300", "5y")
    assert t3["pe_pct"] == pytest.approx(t3["pct"]["pe"]["p3"]), "3y 必须取 p3"
    assert t5["pe_pct"] == pytest.approx(t5["pct"]["pe"]["p5"]), "5y 必须取 p5"
    assert t3["pe_pct_window"] == "3y" and t5["pe_pct_window"] == "5y"
    # demo 三档必须算出不同值，否则这条断言形同虚设（旧 demo 三档全相等）
    assert t3["pct"]["pe"]["p3"] != t3["pct"]["pe"]["p5"], \
        "demo 三档分位不得相同，否则无法暴露「恒取 5y」的回归"
    assert t3["pct"]["pe"]["n3"] < t3["pct"]["pe"]["n5"], "3y 样本数应少于 5y"


def test_pb_pct_follows_window():
    """``pb_pct`` 与 pe 侧同选择逻辑（旧 demo 让 pb 恒取 p5，掩盖了同类回归）。"""
    cli = demo_client()
    t3 = cli.index.trend("index.hs300", "3y")
    t5 = cli.index.trend("index.hs300", "5y")
    assert t3["pb_pct"] == pytest.approx(t3["pct"]["pb"]["p3"]), "3y 必须取 pb.p3"
    assert t5["pb_pct"] == pytest.approx(t5["pct"]["pb"]["p5"]), "5y 必须取 pb.p5"


def test_industry_keys_have_trend_history():
    """申万一级行业键必须能取到估值历史（行业 PE 历史的唯一入口）。

    live 覆盖 31 个 ``industry.SXX``；demo 取代表键。这条测试锁死「行业可用」这一
    契约——此前 demo 的 ``universe_keys("industry")`` 返回空，行业路径无法离线验证，
    用户也无法从文档判断该能力是否存在。
    """
    cli = demo_client()
    keys = cli.index.universe_keys("industry")
    assert keys, "industry 组不得为空"
    for k in keys:
        assert k.startswith("industry."), f"行业键格式应为 industry.SXX：{k}"
        t = cli.index.trend(k, "5y")
        assert t["ok"] is True, f"{k} 应能取到估值趋势"
        assert t["points"], f"{k} 应返回非空序列"
        assert t["pe_pct"] is not None, f"{k} 应给出 5y 分位"


def test_universe_keys_groups():
    """四组 universe_keys 与 live 同构：broad/industry/dividend/all。"""
    cli = demo_client()
    broad = cli.index.universe_keys("broad")
    ind = cli.index.universe_keys("industry")
    div = cli.index.universe_keys("dividend")
    assert broad and ind and div
    assert set(cli.index.universe_keys("all")) == set(broad) | set(ind) | set(div)
    assert cli.index.universe_keys("unknown-group") == []


# ---------------------------------------------------------------- 真实逻辑（注入 stub）
# demo 的 cli.index 是 SimpleNamespace，**完全绕过** IndexApi.trend 的分位选择代码，
# 因此上面那些 demo 断言抓不到「恒取 p」的回归（已用回滚实验验证）。以下用例直接
# 构造 IndexApi + 可编程 stub client，锁死 SDK 侧真正的取档逻辑。
class _StubClient:
    """只提供 IndexApi 用到的 .call；返回预置的 indices.trend 原始 MAP。"""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[dict] = []

    def call(self, name: str, /, **kw):
        self.calls.append({"name": name, **kw})
        return self._payload


def _raw(p3=None, p5=None, p10=None, trunc10=False, density="weekly"):
    """构造服务端 indices.trend 原始返回（新→旧 base，p 恒等于 p5 正是线上行为）。"""
    return {
        "ok": True, "key": "index.hs300", "asof": "2026-11-09", "density": density,
        "n": 3, "base": [["2026-11-09", 13.4, 1.25], ["2026-11-02", 13.1, 1.22],
                         ["2026-10-26", 12.8, 1.19]],
        "med": [], "window": "5y", "win_start": "2021-11-09", "win_n": 3,
        "win_trunc": False,
        # 服务端 pct_bundle 的 "p" 恒为 5 年分位——即 p5
        "pct": {"pe": {"p": p5, "p3": p3, "p5": p5, "p10": p10,
                       "n3": 156, "n5": 260, "n10": 520, "trunc10": trunc10},
                "pb": {"p": p5, "p3": p3, "p5": p5, "p10": p10,
                       "n3": 156, "n5": 260, "n10": 520, "trunc10": trunc10},
                "pe_med": {}},
        "pct_p": p5, "dv_has_history": False,
    }


def test_real_logic_pe_pct_uses_window_field():
    """真实 IndexApi：3y 取 p3、5y 取 p5，绝不读恒为 5y 的 ``p``。

    这是本次修复的核心回归点。旧实现读 ``pct.pe.p``，于是 3y 请求拿到 5y 分位
    （live hs300 实测 0.7671 vs 真值 0.6119）。
    """
    from wmshare.api import IndexApi

    p3, p5 = 0.6119, 0.7671
    api = IndexApi(_StubClient(_raw(p3=p3, p5=p5)))
    t3 = api.trend("index.hs300", "3y")
    t5 = api.trend("index.hs300", "5y")
    assert t3["pe_pct"] == pytest.approx(p3), "3y 必须取 p3，不能取 p（=p5）"
    assert t5["pe_pct"] == pytest.approx(p5)
    assert t3["pb_pct"] == pytest.approx(p3), "pb 侧同口径"
    assert t3["pe_pct_window"] == "3y" and t5["pe_pct_window"] == "5y"


def test_real_logic_10y_truncated_gives_none():
    """10y 档被服务端置 None（trunc10）时，分位必须为 None，不降级到 5y。"""
    from wmshare.api import IndexApi

    api = IndexApi(_StubClient(_raw(p3=0.61, p5=0.77, p10=None, trunc10=True)))
    t = api.trend("index.hs300", "10y")
    assert t["pe_pct"] is None and t["pb_pct"] is None
    assert t["pe_pct_window"] is None, "截断时不应声称任何窗口生效"


def test_real_logic_10y_when_covered():
    """序列真能盖住 10 年（trunc10=False）时，10y 正常给 p10。"""
    from wmshare.api import IndexApi

    api = IndexApi(_StubClient(_raw(p3=0.61, p5=0.77, p10=0.55, trunc10=False)))
    t = api.trend("index.hs300", "10y")
    assert t["pe_pct"] == pytest.approx(0.55)
    assert t["pe_pct_window"] == "10y"


def test_real_logic_passes_window_through():
    """window 必须作为参数发给服务端（否则服务端只按默认 5y 算 win_n）。"""
    from wmshare.api import IndexApi

    stub = _StubClient(_raw(p3=0.6, p5=0.7))
    IndexApi(stub).trend("index.hs300", "3y")
    assert stub.calls[-1] == {"name": "indices.trend",
                              "key": "index.hs300", "window": "3y"}


def test_real_logic_loss_making_subject_distinguished_from_truncation():
    """「无 PE」与「窗口不够」两种 None 必须可区分（实测 industry.S11 整体亏损）。

    整体法下行业近期整体亏损时 ``ΣNPTS_TTM ≤ 0``，价格侧 PE 为 nil，服务端各档分位
    自然为 None——这是**正常结果**，不是数据缺失，也不该被误读成「窗口不足」。
    """
    from wmshare.api import IndexApi

    payload = _raw(p3=None, p5=None, p10=None, trunc10=False)
    # 最新点 PE 为 None（亏损），PB 正常
    payload["base"][0][1] = None
    t = IndexApi(_StubClient(payload)).trend("index.hs300", "5y")
    assert t["pe_pct"] is None, "亏损主体无 PE 分位"
    assert t["pe_missing"] is True, "必须标记最新点无 PE，区别于窗口截断"
    assert t["pb_missing"] is False
    # 窗口截断场景：最新点有值但 10y 档盖不住
    t2 = IndexApi(_StubClient(_raw(p3=0.6, p5=0.7, p10=None, trunc10=True))).trend(
        "index.hs300", "10y")
    assert t2["pe_pct"] is None and t2["pe_missing"] is False, \
        "截断造成的 None 不得被误标为「无 PE」"


def test_real_logic_only_usage_error_falls_back():
    """只有 UsageError（旧服务端不认 window）才重试单参调用。

    鉴权/网络/服务端错误必须原样抛出——旧实现用 ``except Exception`` 把真实故障
    也变成第二次请求，故障被掩盖成「服务端没部署 pct」。
    """
    from wmshare.api import IndexApi
    from wmshare.errors import AuthError, UsageError

    class _AuthStub(_StubClient):
        def call(self, name, /, **kw):
            self.calls.append({"name": name, **kw})
            raise AuthError("401")

    stub = _AuthStub(_raw())
    with pytest.raises(AuthError):
        IndexApi(stub).trend("index.hs300", "3y")
    assert len(stub.calls) == 1, "鉴权错误不得触发第二次请求"

    class _LegacyStub(_StubClient):
        def call(self, name, /, **kw):
            self.calls.append({"name": name, **kw})
            if "window" in kw:
                raise UsageError("unexpected kwarg window")
            # 真正的旧服务端：单参可调，且返回体里**没有** pct（该字段是后加的）
            payload = _raw(p3=0.6, p5=0.7, p10=None, trunc10=True)
            payload.pop("pct")
            return payload

    legacy = _LegacyStub(_raw())
    t = IndexApi(legacy).trend("index.hs300", "3y")
    assert len(legacy.calls) == 2 and "window" not in legacy.calls[-1]
    # 旧服务端无 pct：降级为按窗口本地自算（pct_source=client）。
    # 本例 base 仅 3 个点，低于本地兜底的 60 样本门槛，故分位为 None 是**正确行为**
    # （小样本不出分位，与 _pct 的 len(vals) < 60 守护一致）。
    assert t["pct_source"] == "client"
    assert t["pe_pct"] is None and t["win_trunc"] is True


def test_bad_window_falls_back_to_5y():
    t = demo_client().index.trend("index.hs300", "7y")
    assert t["window"] == "5y"


def test_demo_direction_matches_live_contract():
    """demo 与 live 必须同向：两边都由 points[0] 表示最新点。"""
    t = _trend()
    assert t["points"][0]["date"] >= t["points"][-1]["date"]
