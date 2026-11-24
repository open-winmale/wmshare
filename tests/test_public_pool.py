"""免注册访问（公开池）测试：无凭证时的构造、传输与错误映射。

核心保护对象：
  1. 免注册客户端绝不申领、落盘凭据，也绝不带 Authorization、绝不调 OAuth——
     身份完全由服务端按来源网络记账；
  2. 公开池的终态拒绝（单 IP 限流、池分片停用、共享额度耗尽）不重试、码稳定；
  3. 凭证模式的行为不因免注册访问的引入而漂移（401 刷新重试一次仍在）。
"""
from __future__ import annotations

import json
import warnings

import pytest

import wmshare
from wmshare import Client
from wmshare.catalog import load
from wmshare.client import PUBLIC_LIMIT_CODES, QUOTA_CODES, TERMINAL_429_CODES
from wmshare.errors import ApiError, AuthError, LimitError, QuotaError, ServerError, UsageError

BASE = "https://test-api.winmale.com"


class Resp:
    """脚本化响应：与网关信封同形（{success, data, error, meta}）。"""

    def __init__(self, status: int, body: dict | None, text: str | None = None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body, ensure_ascii=False)
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _ok(result: dict | None = None) -> Resp:
    return Resp(200, {
        "success": True,
        "data": {"mode": "call", "result": {"ok": True} if result is None else result},
        "meta": {"app_id": "wm_pub_06", "mode": "call",
                 "metering": {"analysis.ec_cost": 95, "latency_ms": 9}},
    })


def _err(status: int, code: str, message: str = "rejected by gateway") -> Resp:
    return Resp(status, {"success": False, "data": None,
                         "error": {"code": code, "message": message}, "meta": {}})


class ScriptedSession:
    """按顺序回放脚本化响应，并记录每次请求（断言 Authorization 用）。"""

    def __init__(self, responses: list[Resp]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data,
                           "headers": dict(headers or {})})
        if not self.responses:
            raise AssertionError(f"未预期的请求：{url}")
        return self.responses.pop(0)


class OAuthSession:
    """凭证模式：OAuth 恒 200，eval 依次返回给定响应。"""

    def __init__(self, eval_responses: list[Resp]):
        self.eval_responses = list(eval_responses)
        self.calls: list[dict] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        if url.endswith("/v1/oauth/token"):
            return Resp(200, {"data": {"access_token": "tok-1", "expires_in": 3600}})
        return self.eval_responses.pop(0)


def _public(session, **kw) -> Client:
    """无凭证的 from_env：env 用显式字典，绝不读本机凭证，也绝不打到生产地址。"""
    return Client.from_env(env={"WMSHARE_CREDENTIALS": "/nonexistent/wmshare-test/credentials.env",
                                "WMSHARE_BASE_URL": BASE},
                           catalog=load(), session=session, **kw)


def _call(c: Client):
    return c.call("kline.query_bars", sym="600519", limit=30)


def _evals(session) -> list[dict]:
    return [x for x in session.calls if x["url"].endswith("/v1/analysis/xs/eval")]


# ---- 构造：零网络、零落盘、零凭据 ----

def test_from_env_without_credentials_is_public_pool(tmp_path):
    s = ScriptedSession([])
    c = Client.from_env(env={"WMSHARE_CREDENTIALS": str(tmp_path / "absent.env")},
                        catalog=load(), session=s)
    try:
        assert c.auth_mode == "public_pool"
        assert (c.client_id, c.client_secret) == ("", "")
        assert s.calls == []                      # 构造零网络：不申领凭据
        assert list(tmp_path.iterdir()) == []     # 零落盘：不写任何凭据文件
    finally:
        c.close()


def test_from_env_ignores_legacy_anon_credentials_file(tmp_path, monkeypatch):
    """3.2.x 及更早版本落盘的匿名凭据不再被读取（服务端已停发，读它只会拿到死凭据）。"""
    home = tmp_path / "home"
    (home / ".wmshare").mkdir(parents=True)
    (home / ".wmshare" / "anon_credentials.env").write_text(
        "WMSHARE_CLIENT_ID=anon_open_stale\nWMSHARE_CLIENT_SECRET=s\nWMSHARE_ANON=1\n",
        encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    c = Client.from_env(env={"WMSHARE_CREDENTIALS": str(tmp_path / "absent.env")},
                        catalog=load(), session=ScriptedSession([]))
    try:
        assert c.auth_mode == "public_pool" and c.client_id == ""
    finally:
        c.close()


def test_from_env_with_credentials_stays_credentials():
    s = OAuthSession([_ok()])
    c = Client.from_env(env={"WMSHARE_CREDENTIALS": "/nonexistent/wmshare-test/credentials.env",
                             "WMSHARE_CLIENT_ID": "wm_open_x", "WMSHARE_CLIENT_SECRET": "sec"},
                       base_url=BASE, catalog=load(), session=s)
    try:
        assert c.auth_mode == "credentials"
        _call(c)
        assert _evals(s)[0]["headers"]["Authorization"] == "Bearer tok-1"
    finally:
        c.close()


def test_bare_client_without_credentials_still_raises():
    """裸 Client() 不回落（2.8.0 起的约定不变）：报错指向 from_env 的免注册路径。"""
    with pytest.raises(AuthError) as ei:
        Client(catalog=load())
    assert ei.value.code == "config"
    assert "缺少凭证" in str(ei.value) and "from_env" in str(ei.value)
    assert "免注册" in str(ei.value) and "WMSHARE_DISABLE_ANON=1" in str(ei.value)


def test_disable_anon_restores_missing_credentials_error():
    """WMSHARE_DISABLE_ANON=1 → 恢复「缺少凭证」报错（迁移逃生口），且零网络。"""
    s = ScriptedSession([])
    with pytest.raises(AuthError, match="缺少凭证") as ei:
        Client.from_env(env={"WMSHARE_CREDENTIALS": "/nonexistent/wmshare-test/credentials.env",
                             "WMSHARE_DISABLE_ANON": "true"},
                        catalog=load(), session=s)
    assert ei.value.code == "config" and s.calls == []


def test_public_pool_rejects_credentials():
    for cid, sec in (("wm_open_x", "sec"), ("wm_open_x", ""), ("", "sec")):
        with pytest.raises(UsageError, match="不能同时提供") as ei:
            Client(client_id=cid, client_secret=sec, _public_pool=True, catalog=load())
        assert ei.value.code == "config"


def test_public_pool_must_be_bool():
    with pytest.raises(UsageError, match="_public_pool 必须是布尔值"):
        Client(client_id="wm_open_x", client_secret="sec", _public_pool="yes", catalog=load())


def test_anonymous_forces_public_pool_even_with_credentials(monkeypatch):
    """Client.anonymous()：忽略环境里已配置的凭证，强制免注册。"""
    monkeypatch.setenv("WMSHARE_CLIENT_ID", "wm_open_x")
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "sec")
    c = Client.anonymous(catalog=load(), session=ScriptedSession([]))
    try:
        assert c.auth_mode == "public_pool" and (c.client_id, c.client_secret) == ("", "")
    finally:
        c.close()


def test_anonymous_with_explicit_credentials_keeps_credentials():
    """显式传成对凭证 → 仍按凭证构造（旧语义不变）。"""
    c = Client.anonymous(client_id="wm_open_x", client_secret="sec",
                         catalog=load(), session=OAuthSession([]))
    try:
        assert c.auth_mode == "credentials"
    finally:
        c.close()


def test_anonymous_with_half_credentials_reports_pair_error():
    with pytest.raises(AuthError, match="成对"):
        Client.anonymous(client_id="wm_open_x", catalog=load(), session=OAuthSession([]))


def test_anonymous_refresh_is_deprecated_noop():
    """refresh 参数已无意义：保留签名、发 DeprecationWarning（兼容政策的弃用流程）。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        c = Client.anonymous(refresh=True, catalog=load(), session=ScriptedSession([]))
    try:
        assert c.auth_mode == "public_pool"
    finally:
        c.close()
    assert [w.category for w in caught] == [DeprecationWarning]
    assert "refresh" in str(caught[0].message)


# ---- 传输：不带令牌、不调 OAuth ----

def test_public_client_sends_no_authorization_and_never_calls_oauth():
    s = ScriptedSession([_ok()])
    c = _public(s)
    try:
        assert _call(c) == {"ok": True}
    finally:
        c.close()
    assert len(s.calls) == 1
    ev = s.calls[0]
    assert ev["url"] == f"{BASE}/v1/analysis/xs/eval"
    assert "Authorization" not in ev["headers"]
    # 请求体与凭证模式同形：免注册只差「带不带令牌」，接口与数据完全一致
    assert ev["json"]["mode"] == "call" and ev["json"]["market"] == "cn"
    assert c.last_ec_cost == 95  # 计量头照常解析


def test_public_client_401_is_not_retried():
    """没有令牌可刷新：401 只发一次请求，文案不再叫人「检查凭证配置」。"""
    s = ScriptedSession([_err(401, "INVALID_TOKEN")])
    c = _public(s)
    try:
        with pytest.raises(AuthError) as ei:
            _call(c)
    finally:
        c.close()
    assert len(s.calls) == 1
    assert (ei.value.code, ei.value.status) == ("INVALID_TOKEN", 401)
    assert "免注册访问被拒绝" in str(ei.value) and "检查凭证配置" not in str(ei.value)


def test_notice_poller_on_public_client_sends_no_token():
    """公告轮询端点不在免注册范围内：照常拿到「端点未开放」，且不带令牌。"""
    s = ScriptedSession([Resp(404, None, text="404 page not found\n")])
    c = _public(s)
    try:
        with pytest.raises(ApiError) as ei:
            c.notice_poller(group="g", consumer="w").probe()
    finally:
        c.close()
    assert ei.value.code == "endpoint_unavailable"
    assert s.calls[0]["url"].endswith("/v1/notice-stream/poll")
    assert "Authorization" not in s.calls[0]["headers"]


# ---- 错误映射：公开池的终态拒绝不重试、码稳定 ----

@pytest.mark.parametrize("code,exc,sdk_code", [
    ("IP_RATE_LIMITED", LimitError, "ip_rate_limited"),
    ("APP_SUSPENDED", LimitError, "pool_unavailable"),
    ("EC_BALANCE_EXHAUSTED", QuotaError, "EC_BALANCE_EXHAUSTED"),
    ("DAILY_EC_CAP_EXCEEDED", QuotaError, "DAILY_EC_CAP_EXCEEDED"),
])
def test_public_terminal_429_is_not_retried(code, exc, sdk_code):
    """终态 429 只发一次请求（旧行为：空转重试到耗尽再报 rate_limited）。"""
    s = ScriptedSession([_err(429, code)])
    c = _public(s)
    c._sleep = lambda _seconds: None  # 测试注入点：不真实等待
    try:
        with pytest.raises(exc) as ei:
            _call(c)
    finally:
        c.close()
    assert len(s.calls) == 1
    assert (ei.value.code, ei.value.status) == (sdk_code, 429)
    assert "注册免费账号" in str(ei.value)  # 所有免注册拒绝都给注册路径


def test_public_quota_guidance_has_no_own_app_advice():
    """免注册没有「默认应用/周补」可换：不能套用自有应用的配额指引。"""
    s = ScriptedSession([_err(429, "EC_BALANCE_EXHAUSTED")])
    c = _public(s)
    try:
        with pytest.raises(QuotaError) as ei:
            _call(c)
    finally:
        c.close()
    msg = str(ei.value)
    assert "免注册试用额度已用完" in msg and "每周" not in msg and "我的应用" not in msg


def test_public_quota_code_in_200_envelope_uses_public_guidance():
    s = ScriptedSession([Resp(200, {"success": False, "data": None,
                                    "error": {"code": "EC_BALANCE_EXHAUSTED", "message": "x"}})])
    c = _public(s)
    try:
        with pytest.raises(QuotaError) as ei:
            c.eval(["return 1"])
    finally:
        c.close()
    assert ei.value.code == "EC_BALANCE_EXHAUSTED" and "每周" not in str(ei.value)


def test_public_ip_banned_is_auth_error():
    s = ScriptedSession([_err(403, "IP_BANNED")])
    c = _public(s)
    try:
        with pytest.raises(AuthError) as ei:
            _call(c)
    finally:
        c.close()
    assert (ei.value.code, ei.value.status) == ("ip_banned", 403)
    assert "配置自有应用凭证后不受此限制" in str(ei.value)


def test_public_shard_rate_limit_is_retried_then_rate_limited():
    """池分片的普通限流（非终态）：照常退避重试，耗尽后报 rate_limited。"""
    s = ScriptedSession([_err(429, "RATE_LIMITED")] * 3)
    c = _public(s, retries=2)
    c._sleep = lambda _seconds: None
    try:
        with pytest.raises(LimitError) as ei:
            _call(c)
    finally:
        c.close()
    assert len(s.calls) == 3
    assert ei.value.code == "rate_limited" and "免注册" in str(ei.value)
    assert "申请自己的 AppID" not in str(ei.value)


def test_public_403_policy_denied_keeps_server_code():
    s = ScriptedSession([_err(403, "INSUFFICIENT_SCOPE", "public pool app is missing analysis:xs:eval")])
    c = _public(s)
    try:
        with pytest.raises(AuthError) as ei:
            _call(c)
    finally:
        c.close()
    assert ei.value.code == "INSUFFICIENT_SCOPE" and ei.value.status == 403
    assert "配置凭证后重试" in str(ei.value)


def test_public_503_is_retried_then_server_error():
    s = ScriptedSession([_err(503, "APP_UNAVAILABLE")] * 3)
    c = _public(s, retries=2)
    c._sleep = lambda _seconds: None
    try:
        with pytest.raises(ServerError) as ei:
            _call(c)
    finally:
        c.close()
    assert len(s.calls) == 3 and ei.value.code == "APP_UNAVAILABLE"


def test_terminal_429_codes_cover_quota_and_public_limits():
    """终态集合 = 配额码 ∪ 公开池限流码；缺一个都会让 SDK 对终态拒绝空转重试。"""
    assert TERMINAL_429_CODES == QUOTA_CODES | PUBLIC_LIMIT_CODES
    assert {"IP_RATE_LIMITED", "APP_SUSPENDED"} <= PUBLIC_LIMIT_CODES


# ---- 凭证模式回归：不因免注册访问的引入而漂移 ----

def test_credentials_mode_still_refreshes_token_on_401():
    s = OAuthSession([_err(401, "INVALID_TOKEN"), _ok()])
    c = Client(base_url=BASE, client_id="id", client_secret="sec", catalog=load(), session=s)
    try:
        assert _call(c) == {"ok": True}
    finally:
        c.close()
    evals = _evals(s)
    assert len(evals) == 2
    assert all(x["headers"]["Authorization"] == "Bearer tok-1" for x in evals)
    assert sum(1 for x in s.calls if x["url"].endswith("/v1/oauth/token")) == 2  # 失效后重取一次


def test_credentials_mode_quota_guidance_unchanged():
    s = OAuthSession([_err(429, "EC_BALANCE_EXHAUSTED")])
    c = Client(base_url=BASE, client_id="id", client_secret="sec", catalog=load(), session=s)
    try:
        with pytest.raises(QuotaError) as ei:
            _call(c)
    finally:
        c.close()
    assert len(_evals(s)) == 1
    assert "配额耗尽" in str(ei.value) and "每周" in str(ei.value)


def test_auth_mode_values_are_stable_strings():
    assert sorted({Client.anonymous(catalog=load(), session=ScriptedSession([])).auth_mode,
                   "credentials"}) == ["credentials", "public_pool"]
    assert isinstance(wmshare.Client.auth_mode, property)
