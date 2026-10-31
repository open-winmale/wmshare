"""公告变更订阅：消息队列消费组语义（流、消费进度与 ack 全在服务端），SDK 侧本地定时器轮询。

服务端（与取数同一 base_url、同一 OAuth Bearer 认证）维护公告变更事件流，合同见
平台网关文档 `docs/notice-stream-api.md`（winmale 仓）：

  poll  探针——各市场 {head, acked, new_count}，O(1)，是定时器每轮的常态开销；
  read  拉取——自消费游标（含）起的事件（游标=下一条要交付的 seq，limit 服务端钳制）；
  ack   确认——推进游标；ack 前崩溃 = 下轮重投同批事件（at-least-once）。

典型用法::

    def on_events(events):
        for e in events:
            print(e.market, e.code, e.title)

    p = cli.notice_poller(group="my_service", consumer="host-1",
                          on_events=on_events, interval=300)
    p.start()                       # daemon 定时线程，不阻塞进程退出；p.stop() 停止
    # 也可完全自驱：p.poll_now() 一轮，或 p.read(market) + p.ack(events[-1])

事件语义：内容修订 = 新事件再次入流；服务端保留 7 天，消费进度落后超期时 read 抛
StreamResetError——用 ``seek_oldest(market)`` 重置进度，只能取回保留期内剩余数据。
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from wmshare.errors import ApiError, LimitError, StreamResetError, UsageError, WmshareError

MARKETS = ("cn", "hk")
DEFAULT_INTERVAL = 300.0
DEFAULT_LIMIT = 100
MAX_LIMIT = 200  # 服务端同款钳制；客户端先行拦截，省一次往返


@dataclass(frozen=True)
class NoticeStreamEvent:
    """公告变更事件（字段与取数侧 notice.fmt_maps 对齐）。"""

    seq: int
    eid: str
    market: str
    code: str
    name: str
    type: str
    title: str
    date: str
    announce_date: str
    available_at: str
    url: str
    pdf_url: str

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, market: str = "") -> "NoticeStreamEvent":
        try:
            seq = int(d["seq"])
        except (KeyError, TypeError, ValueError) as e:
            raise ApiError(f"事件缺少合法 seq：{str(d)[:200]}", code="stream_event") from e
        return cls(
            seq=seq,
            eid=str(d.get("eid") or ""),
            market=str(d.get("market") or market),
            code=str(d.get("code") or ""),
            name=str(d.get("name") or ""),
            type=str(d.get("type") or ""),
            title=str(d.get("title") or ""),
            date=str(d.get("date") or ""),
            announce_date=str(d.get("announce_date") or ""),
            available_at=str(d.get("available_at") or ""),
            url=str(d.get("url") or ""),
            pdf_url=str(d.get("pdf_url") or ""),
        )


@dataclass(frozen=True)
class MarketProgress:
    """单市场消费进度：acked=消费游标（下一条要读的 seq），head=服务端该市场最新 seq。"""

    market: str
    acked: int
    head: int

    @property
    def new_count(self) -> int:
        if self.head <= 0:
            return 0
        return max(0, self.head - self.acked + 1)


@dataclass
class PollerStatus:
    """轮询器运行状态（status() 快照，可接心跳/监控）。"""

    polls: int = 0
    reads: int = 0
    events_delivered: int = 0
    ack_failures: int = 0
    consecutive_errors: int = 0
    last_error: str | None = None
    last_success_ts: float | None = None
    progress: dict[str, MarketProgress] = field(default_factory=dict)


class NoticePoller:
    """公告变更轮询器：``cli.notice_poller(group=..., consumer=..., on_events=...)`` 构造。

    一轮（poll_now）= 探针 → 有新市场逐个 read（按 limit 分批直到追平 head）→
    回调 → ack。回调抛异常时该批不 ack、记入 status、线程保活，下轮自动重投。
    """

    def __init__(self, client: Any, *, group: str, consumer: str,
                 on_events: Callable[[list[NoticeStreamEvent]], Any] | None = None,
                 interval: float = DEFAULT_INTERVAL,
                 markets: tuple[str, ...] | list[str] = MARKETS,
                 limit: int = DEFAULT_LIMIT, jitter: float = 0.1,
                 backoff_cap: float = 8.0):
        if not str(group).strip() or not str(consumer).strip():
            raise UsageError("group 与 consumer 必填（消费进度的定位标识）", code="params")
        if interval <= 0:
            raise UsageError("interval 必须为正秒数", code="params")
        bad = [m for m in markets if m not in MARKETS]
        if bad:
            raise UsageError(f"markets 只支持 {MARKETS}，收到 {bad}", code="params")
        if not 0 <= jitter < 1:
            raise UsageError("jitter 需在 [0, 1)", code="params")
        self._client = client
        self._group = str(group)
        self._consumer = str(consumer)
        self._on_events = on_events
        self._interval = float(interval)
        self._markets = tuple(dict.fromkeys(markets))
        self._limit = max(1, min(int(limit), MAX_LIMIT))
        self._jitter = float(jitter)
        self._backoff_cap = max(1.0, float(backoff_cap))
        # 注入点：测试零等待 / 确定性
        self._uniform = random.uniform
        self._now = time.time
        self._stop_event = threading.Event()
        self._poll_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._acked: dict[str, int] = {}  # 服务端进度的本地镜像（probe/ack 后刷新）
        self._status = PollerStatus()

    # ---- 服务端三调用 ----
    def _post(self, op: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client._post_authed(f"/v1/notice-stream/{op}", body)
        if resp.status_code == 404:
            raise ApiError(
                f"公告订阅端点未开放（HTTP 404）：/v1/notice-stream/{op} 在当前网关不存在，"
                "该能力尚未对外开放，请勿反复重试；可关注版本公告或到 open.winmale.com "
                "确认平台的开通状态。",
                code="endpoint_unavailable", status=404)
        if resp.status_code != 200:
            self._client._raise_http_error(resp, stage="notice_stream")
        try:
            doc = resp.json()
        except ValueError as e:
            raise ApiError(f"公告订阅 {op} 响应不是合法 JSON：{resp.text[:200]}",
                           code="response") from e
        if not isinstance(doc, dict) or not doc.get("success", True):
            err = doc.get("error") if isinstance(doc, dict) else None
            err = err if isinstance(err, dict) else {}
            code = str(err.get("code") or "notice_stream")
            msg = str(err.get("message") or "")
            if "RATE" in code.upper() or "QUOTA" in code.upper():
                raise LimitError(f"公告订阅 {op} 被限流：{code} {msg}")
            raise ApiError(f"公告订阅 {op} 失败：{code} {msg}", code=code)
        data = doc.get("data")
        return data if isinstance(data, dict) else {}

    def probe(self) -> dict[str, MarketProgress]:
        """消费进度探针（服务端 O(1)）：各市场 acked/head/new_count。"""
        data = self._post("poll", {"group": self._group, "consumer": self._consumer})
        global_head = int(data.get("head") or 0)
        raw_slots = data.get("markets")
        slots: dict[str, Any] = raw_slots if isinstance(raw_slots, dict) else {}
        out: dict[str, MarketProgress] = {}
        with self._lock:
            for m in self._markets:
                raw_slot = slots.get(m)
                slot: dict[str, Any] = raw_slot if isinstance(raw_slot, dict) else {}
                acked = int(slot.get("acked") or 0)
                # head=0 是合法值（该市场尚无事件），不能回落到全局 head
                raw_head = slot.get("head")
                head = int(raw_head) if raw_head is not None else global_head
                self._acked[m] = acked
                out[m] = MarketProgress(market=m, acked=acked, head=head)
            self._status.progress = out
        return out

    def read(self, market: str | None = None, *, after: int | None = None,
             limit: int | None = None) -> list[NoticeStreamEvent]:
        """拉取 market 在消费进度之后的事件（不动进度；ack 才推进）。

        进度落后超保留期时抛 StreamResetError（事件已过期，见模块 docstring）。
        """
        if market is None:
            if len(self._markets) != 1:
                raise UsageError("多市场订阅需显式指定 market（read 的第一参数）",
                                 code="params")
            market = self._markets[0]
        if market not in self._markets:
            raise UsageError(f"market 只支持本订阅的 {self._markets}", code="params")
        if after is None:
            with self._lock:
                after = self._acked.get(market, 0)
        body = {
            "group": self._group,
            "consumer": self._consumer,
            "market": market,
            "after_seq": int(after),
            "limit": max(1, min(int(limit or self._limit), MAX_LIMIT)),
        }
        data = self._read_body(body)
        if data.get("reset_needed"):
            raise StreamResetError(
                f"市场 {market} 的消费进度已超出保留期（服务端最早可用 seq={data.get('oldest')}）。"
                f"调用 seek_oldest({market!r}) 重置进度，只能取回保留期内剩余数据；"
                "此后建议缩短轮询间隔。",
                code="stream_reset")
        events = [NoticeStreamEvent.from_dict(d, market=market)
                  for d in (data.get("events") or [])]
        return events

    def ack(self, what: "NoticeStreamEvent | int", *, market: str | None = None) -> int:
        """确认消费进度：传事件（游标推进到该事件之后）或裸 seq（游标设为该 seq）。

        游标语义：acked = 下一条要交付的 seq，read 自游标起**含**游标返回；
        裸 seq 可回退（回放）；``seek_oldest`` 等价于游标设为保留期内最早 seq。
        """
        if isinstance(what, NoticeStreamEvent):
            seq = what.seq + 1
            m: str | None = what.market
        else:
            seq = int(what)
            m = market
        if m is None:
            raise UsageError("裸 seq 的 ack 必须指定 market", code="params")
        if m not in self._markets:
            raise UsageError(f"market 只支持本订阅的 {self._markets}", code="params")
        if seq < 0:
            raise UsageError("seq 不能为负", code="params")
        data = self._post("ack", {"group": self._group, "consumer": self._consumer,
                                  "market": m, "seq": seq})
        raw_acked = data.get("acked")
        acked = int(raw_acked) if raw_acked is not None else seq
        with self._lock:
            self._acked[m] = acked
            prog = self._status.progress.get(m)
            if prog is not None:
                self._status.progress[m] = replace(prog, acked=acked)
        return acked

    def _read_body(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("read", body)

    def seek_oldest(self, market: str) -> int:
        """把消费游标重置到保留期内最早可用事件（seek 后 read 从头回放）。

        进度超期（StreamResetError）后用它恢复；平时调用等价于「从最早可用事件起
        完整回放」。目标 seq 取自服务端 read 响应的 ``oldest``——保留期外的 seq
        永远读不到，游标落在那里只会反复触发超期判定。
        """
        if market not in self._markets:
            raise UsageError(f"market 只支持本订阅的 {self._markets}", code="params")
        with self._lock:
            cursor = self._acked.get(market, 0)
        data = self._read_body({"group": self._group, "consumer": self._consumer,
                                "market": market,
                                "after_seq": cursor, "limit": 1})
        oldest = int(data.get("oldest") or 0)
        return self.ack(oldest, market=market)

    # ---- 一轮轮询 ----
    def poll_now(self) -> list[NoticeStreamEvent]:
        """执行一轮：探针 → 逐市场 read 分批拉平 → 回调 → ack。返回本轮交付的事件。"""
        delivered: list[NoticeStreamEvent] = []
        had_error = False
        with self._poll_lock:
            progress = self.probe()
            with self._lock:
                self._status.polls += 1
            for m in self._markets:
                head = progress[m].head
                while head > 0:
                    with self._lock:
                        cursor = self._acked.get(m, 0)
                    if cursor > head:
                        break
                    events = self.read(m)
                    with self._lock:
                        self._status.reads += 1
                    if not events:
                        break  # head 与事件短暂不一致：下轮追平
                    delivered.extend(events)
                    if self._on_events is not None:
                        try:
                            self._on_events(events)
                        except Exception as e:  # 回调失败不杀线程；该批不 ack，下轮重投
                            self._record_error(e, ack_failed=True)
                            had_error = True
                            break
                    self.ack(events[-1], market=m)
            with self._lock:
                if not had_error:
                    self._status.consecutive_errors = 0
                    self._status.last_success_ts = self._now()
                self._status.events_delivered += len(delivered)
        return delivered

    # ---- 本地定时器 ----
    def start(self) -> None:
        """启动 daemon 定时线程；重复 start 报 UsageError。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise UsageError("NoticePoller 已在运行，不要重复 start()", code="params")
            self._stop_event.clear()
            t = threading.Thread(target=self._loop, name="wmshare-notice-poller",
                                 daemon=True)
            self._thread = t
        t.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止定时线程并等待退出（在轮询线程内调用则只置停止位）。"""
        self._stop_event.set()
        with self._lock:
            t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        with self._lock:
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_now()
            except WmshareError as e:  # 探针/拉取失败：记录并退避，不杀线程
                self._record_error(e)
            except Exception as e:  # 意外异常同样保活
                self._record_error(e)
            factor = min(self._backoff_cap,
                         2.0 ** max(0, self._status.consecutive_errors))
            wait = self._interval * factor * (1.0 + self._uniform(0.0, self._jitter))
            if self._stop_event.wait(wait):
                break

    # ---- 状态 ----
    @property
    def running(self) -> bool:
        """定时线程是否在运行。"""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def status(self) -> PollerStatus:
        """运行状态快照（探针次数/交付数/积压/最近错误），供心跳与监控。"""
        with self._lock:
            return replace(self._status, progress=dict(self._status.progress))

    def __enter__(self) -> "NoticePoller":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def _record_error(self, e: Exception, *, ack_failed: bool = False) -> None:
        with self._lock:
            self._status.last_error = f"{type(e).__name__}: {e}"
            self._status.consecutive_errors += 1
            if ack_failed:
                self._status.ack_failures += 1
