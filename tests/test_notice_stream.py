"""公告订阅轮询器：探针/拉取/ack 语义、回调异常重投、超期重置、线程生命周期、错误映射。

全部走 FakeStreamServer + 假 Session（不联网、不真实等待；线程用例用极小 interval 真实起停）。
"""
from __future__ import annotations

import threading
import time

import pytest

from wmshare.catalog import load
from wmshare.client import Client
from wmshare.errors import ApiError, AuthError, LimitError, StreamResetError, UsageError
from wmshare.notice_stream import (
    MAX_LIMIT, MarketProgress, NoticePoller, NoticeStreamEvent,
)


class Resp:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}
        self.headers = {}
        self.text = "{}"

    def json(self):
        return self._json


def ev(seq, market="cn", code="600519", **kw):
    base = dict(seq=seq, eid=f"e{seq}:{code}", market=market, code=code,
                name=f"名称{code}", type="分红", title=f"公告{seq}",
                date="2026-10-27", announce_date="2026-10-27",
                available_at="2026-10-27 16:03:11", url="http://x", pdf_url="http://p")
    base.update(kw)
    return base


class FakeStreamServer:
    """最小服务端语义：事件池 + 各消费者 acked + 超期 reset 检测 + 请求审计。"""

    def __init__(self, events=()):
        self.events = sorted(events, key=lambda e: e["seq"])
        self.acked = {}  # (consumer, market) -> seq
        self.requests: list[tuple[str, dict]] = []

    def handle(self, op, body):
        self.requests.append((op, dict(body)))
        c = body.get("consumer", "c")
        if op == "poll":
            markets = {}
            for m in ("cn", "hk"):
                mine = [e for e in self.events if e["market"] == m]
                head = mine[-1]["seq"] if mine else 0
                a = self.acked.get((c, m), 0)
                new = (head - a + 1) if head > 0 and a <= head else 0
                markets[m] = {"acked": a, "head": head, "new_count": max(0, new)}
            head = self.events[-1]["seq"] if self.events else 0
            return {"success": True, "data": {"head": head, "markets": markets}}
        if op == "read":
            m = body["market"]
            after = body.get("after_seq", self.acked.get((c, m), 0))
            limit = body.get("limit", 100)
            mine = [e for e in self.events if e["market"] == m]
            oldest = mine[0]["seq"] if mine else 0
            if 0 < after < oldest:
                return {"success": True, "data": {"market": m, "events": [],
                                                  "oldest": oldest,
                                                  "reset_needed": True}}
            out = [e for e in mine if e["seq"] >= after][:limit]
            return {"success": True, "data": {"market": m, "events": out,
                                              "oldest": oldest,
                                              "reset_needed": False}}
        if op == "ack":
            m = body["market"]
            self.acked[(c, m)] = body["seq"]
            return {"success": True, "data": {"market": m, "acked": body["seq"]}}
        raise AssertionError(op)


class StreamSession:
    """requests.Session 假体：token + notice-stream 三端点路由。

    failures 按次插队（注意 5xx 会被 Client 重试吃掉，需按 retries+1 配额注入）；
    always_fail=持续失败模式（线程韧性测试用）。
    """

    def __init__(self, server, failures=(), always_fail=None):
        self.server = server
        self.failures = list(failures)
        self.always_fail = always_fail
        self.token_count = 0

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        if url.endswith("/v1/oauth/token"):
            self.token_count += 1
            return Resp(json_body={"data": {"access_token": f"tok-{self.token_count}",
                                            "expires_in": 3600}})
        if self.failures:
            return Resp(status_code=self.failures.pop(0))
        if self.always_fail is not None:
            return Resp(status_code=self.always_fail)
        op = url.rsplit("/", 1)[-1]
        return Resp(json_body=self.server.handle(op, json or {}))


def make(events=(), failures=(), always_fail=None, **kw):
    server = FakeStreamServer(events)
    s = StreamSession(server, failures, always_fail)
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=load(), session=s, backoff=0.001)
    poller = cli.notice_poller(group="g", consumer="c", **kw)
    return poller, server


# ---- 参数校验 ----
def test_params_validation():
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=load(), session=StreamSession(FakeStreamServer()))
    with pytest.raises(UsageError):
        cli.notice_poller(group="", consumer="c")
    with pytest.raises(UsageError):
        cli.notice_poller(group="g", consumer=" ")
    with pytest.raises(UsageError):
        cli.notice_poller(group="g", consumer="c", interval=0)
    with pytest.raises(UsageError):
        cli.notice_poller(group="g", consumer="c", markets=["cn", "us"])
    with pytest.raises(UsageError):
        cli.notice_poller(group="g", consumer="c", jitter=1.0)
    p = cli.notice_poller(group="g", consumer="c")
    with pytest.raises(UsageError):
        p.read()  # 多市场必须显式指定 market
    with pytest.raises(UsageError):
        p.ack(5)  # 裸 seq 必须带 market
    with pytest.raises(UsageError):
        p.ack(-1, market="cn")


# ---- 探针：无新事件时零 read ----
def test_probe_only_when_no_new():
    p, server = make(events=[ev(1, market="hk")], markets=["cn"])
    delivered = p.poll_now()
    assert delivered == []
    assert [op for op, _ in server.requests] == ["poll"]


# ---- 主流程：探针 → read → 回调 → ack ----
def test_read_callback_ack_flow():
    p, server = make(events=[ev(1), ev(2), ev(3, code="000001")])
    got: list[list[NoticeStreamEvent]] = []
    p._on_events = got.append
    delivered = p.poll_now()
    assert [e.seq for e in delivered] == [1, 2, 3]
    assert got and [e.seq for e in got[0]] == [1, 2, 3]
    assert all(isinstance(e, NoticeStreamEvent) for e in delivered)
    assert delivered[0].market == "cn" and delivered[0].name == "名称600519"
    assert server.acked[("c", "cn")] == 4      # 游标语义：下一条要交付的 seq
    # 追平后再轮询：只探针、零 read
    p.poll_now()
    assert [op for op, _ in server.requests].count("read") == 1


def test_multi_market_and_batching():
    events = [ev(i) for i in range(1, 6)] + [ev(10 + i, market="hk", code="00700")
                                             for i in range(2)]
    p, server = make(events=events, markets=["cn", "hk"], limit=2)
    delivered = p.poll_now()
    assert len(delivered) == 7
    assert {e.market for e in delivered} == {"cn", "hk"}
    assert server.acked[("c", "cn")] == 6
    assert server.acked[("c", "hk")] == 12
    # limit=2 → cn 需要 3 次 read（2+2+1）
    cn_reads = [b for op, b in server.requests if op == "read" and b["market"] == "cn"]
    assert len(cn_reads) == 3


# ---- at-least-once：回调异常不 ack，下轮重投 ----
def test_callback_exception_redelivers():
    p, server = make(events=[ev(1), ev(2)])
    state = {"n": 0}

    def flaky(events):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("下游崩了")

    p._on_events = flaky
    first = p.poll_now()
    assert [e.seq for e in first] == [1, 2]      # 已交付给回调
    assert "ack" not in [op for op, _ in server.requests]
    st = p.status()
    assert st.ack_failures == 1 and st.consecutive_errors == 1
    assert st.last_error and "RuntimeError" in st.last_error
    second = p.poll_now()                        # 重投同批
    assert [e.seq for e in second] == [1, 2]
    assert server.acked[("c", "cn")] == 3
    assert p.status().consecutive_errors == 0


def test_status_is_not_blocked_by_user_callback():
    callback_started = threading.Event()
    release_callback = threading.Event()

    def slow_callback(_events):
        callback_started.set()
        assert release_callback.wait(1)

    p, _ = make(events=[ev(1)], on_events=slow_callback)
    worker = threading.Thread(target=p.poll_now)
    worker.start()
    assert callback_started.wait(1)
    status = p.status()  # 旧实现持有状态锁执行回调，这里会阻塞。
    release_callback.set()
    worker.join(1)
    assert not worker.is_alive()
    assert status.polls == 1 and status.progress["cn"].head == 1


# ---- read 不动游标；ack 写入的是「下一条要交付的 seq」 ----
def test_read_is_idempotent_until_ack():
    p, server = make(events=[ev(1), ev(2), ev(3)])
    assert [e.seq for e in p.read("cn")] == [1, 2, 3]
    assert [e.seq for e in p.read("cn")] == [1, 2, 3]
    assert p.ack(3, market="cn") == 3            # 游标=3：下一条交付 3
    assert [e.seq for e in p.read("cn")] == [3]
    assert p.ack(4, market="cn") == 4
    assert p.read("cn") == []


# ---- 超期 reset 与 seek_oldest ----
def test_reset_needed_and_seek_oldest():
    p, server = make(events=[ev(50), ev(51)])
    server.acked[("c", "cn")] = 10               # 进度落在保留期之前
    p._acked["cn"] = 10
    with pytest.raises(StreamResetError):
        p.read("cn")
    assert p.seek_oldest("cn") == 50             # ack 到服务端 oldest，而非 0
    assert [e.seq for e in p.read("cn")] == [50, 51]


# ---- limit 客户端先行钳制 ----
def test_limit_clamped_client_side():
    p, server = make(events=[ev(1)])
    p.read("cn", limit=999)
    body = [b for op, b in server.requests if op == "read"][-1]
    assert body["limit"] == MAX_LIMIT


# ---- HTTP 错误映射 ----
def test_http_error_mapping():
    p, _ = make(failures=[403])
    with pytest.raises(AuthError):
        p.poll_now()
    p2, _ = make(failures=[429, 429, 429])       # 429 在重试集内，需吃满 retries+1
    with pytest.raises(LimitError):
        p2.poll_now()
    p3, _ = make(failures=[400])                 # 400 不在重试集，直接映射 ApiError
    with pytest.raises(ApiError):
        p3.poll_now()


def test_endpoint_404_guidance():
    """网关未开放（404）：给「未开放，请勿反复重试」专门提示，而非裸 HTTP 404。"""
    p, _ = make(failures=[404])
    with pytest.raises(ApiError, match="未开放") as ei:
        p.poll_now()
    assert ei.value.code == "endpoint_unavailable"


# ---- 业务错误 success=false ----
def test_business_error_envelope():
    server = FakeStreamServer()
    server.handle = lambda op, body: {"success": False,
                                      "error": {"code": "RATE_LIMITED", "message": "慢"}}
    s = StreamSession(server)
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=load(), session=s)
    p = cli.notice_poller(group="g", consumer="c")
    with pytest.raises(LimitError):
        p.poll_now()


# ---- 线程生命周期与退避恢复 ----
def test_thread_lifecycle_and_recovery():
    got = threading.Event()
    seen: list[int] = []

    def on_events(events):
        seen.extend(e.seq for e in events)
        got.set()

    p, server = make(events=[ev(1)], interval=0.02, jitter=0.0,
                     on_events=on_events)
    p.stop()  # 未启动时 stop 是无害操作
    p.start()
    with pytest.raises(UsageError):
        p.start()  # 运行中重复 start
    assert got.wait(5.0)
    assert seen == [1]
    # 注入一轮失败（3 个 500 吃满 retries+1 次尝试），线程必须存活并恢复
    p._client.session.failures.extend([500, 500, 500])
    deadline = time.time() + 5
    while time.time() < deadline and p.status().consecutive_errors == 0:
        time.sleep(0.02)
    deadline = time.time() + 5
    while time.time() < deadline and p.status().consecutive_errors != 0:
        time.sleep(0.02)
    assert p.status().consecutive_errors == 0    # 下一轮成功后归零
    p.stop(timeout=5.0)
    assert server.acked[("c", "cn")] == 2


def test_thread_survives_persistent_failure():
    p, _ = make(always_fail=403, interval=0.02, jitter=0.0)
    p.start()
    time.sleep(0.15)
    p.stop(timeout=5.0)
    st = p.status()
    assert st.consecutive_errors > 0
    assert st.last_error and "AuthError" in st.last_error


# ---- status 快照 ----
def test_status_snapshot_fields():
    p, _ = make(events=[ev(1), ev(2)])
    p._on_events = lambda events: None
    p.poll_now()
    st = p.status()
    assert st.polls == 1 and st.reads == 1
    assert st.events_delivered == 2
    assert st.last_success_ts is not None
    assert st.progress["cn"] == MarketProgress(market="cn", acked=3, head=2)


# ---- 事件解析 ----
def test_event_from_dict_validation():
    assert NoticeStreamEvent.from_dict({"seq": "7", "market": "hk"}).seq == 7
    assert NoticeStreamEvent.from_dict({"seq": 1}).market == ""
    assert NoticeStreamEvent.from_dict({"seq": 1}, market="cn").market == "cn"
    with pytest.raises(ApiError):
        NoticeStreamEvent.from_dict({"eid": "x"})


# ---- Client 入口 ----
def test_client_entrypoint_binding():
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=load(), session=StreamSession(FakeStreamServer()))
    p = cli.notice_poller(group="g", consumer="c", on_events=None,
                          markets=["hk"], interval=1.0)
    assert isinstance(p, NoticePoller)
    assert p._markets == ("hk",)
