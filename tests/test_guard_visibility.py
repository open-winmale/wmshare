"""R1 / S6：守护关闭必须在 MCP 信封与客户端构造期可见。"""
from __future__ import annotations

import asyncio
import warnings

import pytest

from wmshare.client import Client
from wmshare.mcp import tools
from wmshare.mcp.core import MCPRuntime
from wmshare.mcp.server import build_server


class _Bars:
    @staticmethod
    def bars(**kw):
        return [{"close": 1.0}]


class _FakeCli:
    kline = _Bars()
    last_ec_cost = 10

    @staticmethod
    def call(name, **kw):
        return [{"close": 1.0}]


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(MCPRuntime, "client", lambda self, market=None: _FakeCli())
    return MCPRuntime(demo=False)


def test_guards_off_is_visible_for_raw(runtime):
    result = tools.call(runtime, "kline.bars", mode="api", raw=True)
    assert result["ok"] is True
    assert result["meta"]["guards_off"] is True
    assert "禁止直接用于数值结论" in result["meta"]["guard_note"]


def test_guards_off_is_visible_for_native_units(runtime):
    # friendly 路由并非都支持 _units（apis 会拒），catalog 模式走 client.call 的
    # 通用 _units 通道，正好覆盖这条守护关闭路径。
    result = tools.call(runtime, "kline.query_bars", arguments={"sym": "600519"},
                        mode="catalog", units="native")
    assert result["ok"] is True
    assert result["meta"]["guards_off"] is True
    assert result["meta"]["units"] == "native"


def test_default_envelope_stays_byte_compatible(runtime):
    meta = tools.call(runtime, "kline.bars", mode="api")["meta"]
    assert "guards_off" not in meta and "guard_note" not in meta
    # 旧信封键一个都不能少
    assert {"market", "source", "units", "row_count", "rows_total", "truncated",
            "next_action", "demo", "as_of", "retrieved_at", "data_freshness",
            "target", "mode", "raw", "ec_cost"} <= set(meta)


def test_validate_false_warns_exactly_once():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Client(client_id="x", client_secret="y", validate=False)
    hits = [w for w in caught if "validate=False" in str(w.message)]
    assert len(hits) == 1
    assert issubclass(hits[0].category, RuntimeWarning)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Client(client_id="x", client_secret="y")
    assert not [w for w in caught if "validate=False" in str(w.message)]


def test_units_resource_documents_raw_and_guards_off():
    server = build_server(MCPRuntime(market="cn", demo=True))
    resource = server._resource_manager._resources["wmshare://units"]
    text = asyncio.run(resource.read())
    assert "_raw" in text and "guards_off" in text and "禁止" in text
