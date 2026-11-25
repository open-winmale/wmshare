"""W2：公告正文读取接口的目录声明、SDK dispatch 与纯读护栏。

`notice.read_text` 是 S2 在 script 侧新增的纯读函数（未就绪不入队）。
本测试锁定三件事：
1. 目录合同可见（4 参 + 11 返回字段 + min_args=2 + 纯读语义）；
2. SDK 核心接口注册（FRIENDLY_INDEX）且 dispatch 把 symbol→sym、full 透传；
3. 生成的 XS 不含 ensure/submit（纯读，绝不触发入队/生成）——这是 S2 的核心护栏。

数值对账（4000 字预览 vs 全量、pending 行数不变、港股 5 位码）受 scope/EC 限制
不在离线测试覆盖，属 live 验证边界（见 closure 手册 §7），以契约测试兜底。
"""
from __future__ import annotations

import inspect

import wmshare

REPORT_FIELDS = [
    "ok", "status", "text", "text_chars", "text_truncated", "file_key",
    "source_url", "announce_date", "title", "error", "note",
]

# 与 script 侧 xs:catalog 注释的 11 返回字段一致（往返对账锚点）。
SCRIPT_FIELDS = REPORT_FIELDS


def _fn():
    return wmshare.load().function("notice.read_text")


def test_catalog_visible_with_full_contract():
    """目录可见：4 参 + 11 返回字段（顺序/名称与 script 契约一致）。"""
    fn = _fn()
    params = [p["name"] for p in (fn.get("params") or [])]
    assert params == ["sym", "date", "url", "full"], params
    required = [p["name"] for p in fn["params"] if p.get("required")]
    assert required == ["sym", "date"], required
    fields = [f["name"] for f in fn["returns_shape"]["fields"]]
    assert fields == SCRIPT_FIELDS, fields
    assert fn.get("min_args") == 2, fn.get("min_args")


def test_pure_read_guard_in_example_and_desc():
    """纯读护栏：示例/说明体现「纯读、未就绪不入队」，无 ensure/submit 字样。"""
    fn = _fn()
    blob = " ".join([
        str(fn.get("example", "")),
        str(fn.get("returns", {}).get("desc", "")),
        str(fn.get("cn", "")),
    ])
    assert "read_text" in blob
    assert "入队" in blob or "纯读" in blob, blob
    assert "ensure" not in blob.lower() and "submit" not in blob.lower(), blob


def test_friendly_index_registers_read_text():
    """核心接口注册：FRIENDLY_INDEX 含 notice.read_text。"""
    from wmshare.api import FRIENDLY_INDEX
    rows = [r for r in FRIENDLY_INDEX if r[1] == "notice" and r[2] == "read_text"]
    assert len(rows) == 1, rows
    assert rows[0][4] == "notice.read_text", rows[0]


class _FakeSession:
    """最小会话：记录 /xs/eval 的 xs_lines，返回合法 eval 包。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})

        class R:
            status_code = 200
            text = "{}"
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                return {"success": True, "data": {"result": {"ok": True}}}

        return R()


def test_sdk_dispatch_maps_symbol_and_full():
    """SDK dispatch：symbol→sym、date/full 透传，生成合法 return 行。"""
    from wmshare.client import Client

    sess = _FakeSession()
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=wmshare.load(), session=sess)
    cli.notice.read_text("00700", "2026-03-15", "https://x/y.pdf", True)
    xs = [c["json"]["xs_lines"] for c in sess.calls
          if c["url"].endswith("/xs/eval")][-1]
    assert xs and xs[-1].startswith("return"), xs
    call = xs[-1]
    # 位置参数顺序：sym / date / url / full（symbol→sym 作第一参，港股 5 位码直传）
    assert call == ('return notice.read_text("00700", "2026-03-15", '
                    '"https://x/y.pdf", true)'), call
    assert "ensure" not in call and "submit" not in call, call  # 纯读护栏


def test_method_signature_optional_url_and_full():
    """方法签名：url/full 为可选，常用路径必填仅 symbol/date（≤3）。"""
    from wmshare.api import NoticeApi
    sig = inspect.signature(NoticeApi.read_text)
    assert list(sig.parameters) == ["self", "symbol", "date", "url", "full"]
    assert sig.parameters["url"].default == ""
    assert sig.parameters["full"].default is False


def test_empty_date_is_valid_positional_arg():
    """契约回归：date 位置必传但值可空串，dispatch 原样透传、不抛异常。

    review P1-1：空串切片在远程沙箱返回 null，曾使 `_date != \"\"` 守卫失效
    并触发服务端 500。本用例锁定 SDK 侧契约与 dispatch；服务端行为由
    tests/test_live.py 的空 date 用例覆盖（需 script 发布后才有意义）。
    """
    fn = _fn()
    params = fn["params"]
    assert params[1]["name"] == "date" and params[1]["required"] is True
    desc = str(params[1].get("desc", ""))
    if desc:
        assert "空串" in desc, desc

    from wmshare.client import Client

    sess = _FakeSession()
    cli = Client(base_url="https://t", client_id="i", client_secret="s",
                 catalog=wmshare.load(), session=sess)
    cli.notice.read_text("600519", "", "", False)
    xs = [c["json"]["xs_lines"] for c in sess.calls
          if c["url"].endswith("/xs/eval")][-1]
    assert xs[-1] == 'return notice.read_text("600519", "", "", false)', xs[-1]
