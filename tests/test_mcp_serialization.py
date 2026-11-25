"""MCP 序列化边界：DataFrame → JSON 安全行数组 + 时间序列尾部截断。

门面（cli.ns.method）默认返回 DataFrame；MCP 若直接 str(df) 会把 pandas
截断文本预览塞进 data，且 row_count/max_rows 全部失效。这里用假客户端
（不联网）锁定结构、空值处理和截断方向。
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from wmshare.mcp import tools  # noqa: E402
from wmshare.mcp.core import MCPRuntime, success  # noqa: E402


class _FrameClient:
    last_ec_cost = 1

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.kline = SimpleNamespace(bars=self._bars)
        self.futures = SimpleNamespace(bars=self._bars, mapping=self._bars)

    def _bars(self, *args: Any, **kwargs: Any) -> Any:
        return self._payload


def _runtime(payload: Any) -> MCPRuntime:
    rt = MCPRuntime(market="cn")
    rt._clients = {"cn": _FrameClient(payload)}
    return rt


def _dates(start: str, periods: int) -> list[str]:
    return [item.strftime("%Y-%m-%d")
            for item in pd.date_range(start, periods=periods, freq="D")]


def test_history_dataframe_becomes_rows() -> None:
    frame = pd.DataFrame([
        {"date": "2026-11-19", "close": 100.0, "volume": 1000},
        {"date": "2026-11-20", "close": 101.0, "volume": 1100},
    ])
    env = tools.history(_runtime(frame), "600519", n=2)
    assert env["ok"] is True
    assert isinstance(env["data"], list)
    assert env["data"][0] == {"date": "2026-11-19", "close": 100.0, "volume": 1000}
    assert env["meta"]["row_count"] == 2
    assert env["meta"]["rows_total"] == 2
    assert env["meta"]["truncated"] is False

    counted = tools.history(_runtime(frame), "600519", n=2, output="count")
    assert counted["data"] is None
    assert counted["meta"]["row_count"] == 2


def test_futures_bars_dataframe_is_json_safe() -> None:
    frame = pd.DataFrame([{
        "sas": "M11", "date": "2026-11-01", "open": 21000.0, "high": None,
        "low": float("nan"), "close": 21535.0, "settle": 21500.0,
        "pre_settle": pd.NaT, "volume": 100, "amount": 2.5,
        "open_interest": 300, "oi_chg": 1, "has_kline": True,
    }])
    env = tools.futures(_runtime(frame), "bars", code="AL.SHF", n=1)
    assert env["ok"] is True
    assert isinstance(env["data"], list)
    row = env["data"][0]
    assert row["date"] == "2026-11-01" and row["close"] == 21535.0
    assert row["low"] is None and row["pre_settle"] is None
    # MCP 结果必须能被严格 JSON（禁止 NaN/Inf 字面量）编码
    json.dumps(env, ensure_ascii=False, allow_nan=False)


def test_time_series_truncation_keeps_latest_rows() -> None:
    dates = _dates("2025-01-01", 250)
    frame = pd.DataFrame({"date": dates, "close": range(250)})
    env = tools.history(_runtime(frame), "600519", n=250, max_rows=3)
    assert [row["date"] for row in env["data"]] == dates[-3:]
    assert env["meta"]["rows_total"] == 250
    assert env["meta"]["row_count"] == 3
    assert env["meta"]["truncated"] is True
    assert "最近 3 行" in env["meta"]["next_action"]


def test_plain_list_truncation_stays_head() -> None:
    rows = [{"date": f"2026-11-{day:02d}", "close": float(day)}
            for day in range(1, 11)]
    env = tools.history(_runtime(rows), "600519", n=10, max_rows=3)
    assert [row["date"] for row in env["data"]] == [
        "2026-11-01", "2026-11-02", "2026-11-03"]
    assert env["meta"]["rows_total"] == 10
    assert env["meta"]["truncated"] is True
    assert "最近" not in env["meta"]["next_action"]


def test_nested_dataframe_in_dict_and_blocks() -> None:
    dates = _dates("2026-10-01", 5)
    frame = pd.DataFrame({"date": dates, "value": range(5)})
    runtime = MCPRuntime()
    env = success(runtime, {"series": frame}, max_rows=2)
    assert [row["date"] for row in env["data"]["series"]] == dates[-2:]
    assert env["meta"]["truncated"] is True

    blocked = success(runtime, {"symbol": "600519", "blocks": {"bars": frame}},
                      max_rows=2)
    assert [row["date"] for row in blocked["data"]["blocks"]["bars"]] == dates[-2:]


def test_call_api_dataframe_route_becomes_rows() -> None:
    frame = pd.DataFrame([
        {"date": "2026-11-19", "close": 100.0},
        {"date": "2026-11-20", "close": 101.0},
    ])
    env = tools.call(_runtime(frame), "kline.bars", {"symbol": "600519"},
                     mode="api")
    assert env["ok"] is True
    assert isinstance(env["data"], list)
    assert env["data"][-1] == {"date": "2026-11-20", "close": 101.0}
    assert env["meta"]["row_count"] == 2


def test_blocks_keep_symbol_at_top_level() -> None:
    """company 形态：symbol 必须留在顶层，blocks 里只有块。

    曾经的缺陷：_limit_tree 用 ``{"symbol": data.get("symbol")}`` 起手装块，
    于是 symbol 被搬进 blocks——_row_count 把它当一行（每次多报 1），
    _summary 的 block_row_counts 里出现伪块 ``symbol``。
    """
    dates = _dates("2026-11-01", 5)
    frame = pd.DataFrame({"date": dates, "value": range(5)})
    env = success(MCPRuntime(), {"symbol": "600519", "blocks": {"bars": frame}},
                  max_rows=2)

    assert env["data"]["symbol"] == "600519"
    assert "symbol" not in env["data"]["blocks"]
    assert [row["date"] for row in env["data"]["blocks"]["bars"]] == dates[-2:]
    # row_count 是「展示行数」：2 行，不是 2 行 + 伪 symbol 行
    assert env["meta"]["row_count"] == 2
    assert env["meta"]["rows_total"] == 5

    summary = success(MCPRuntime(), {"symbol": "600519", "blocks": {"bars": frame}},
                      max_rows=2, output="summary")
    assert "symbol" not in summary["data"]["block_row_counts"]
    assert summary["data"]["block_row_counts"]["bars"] == 5


def test_time_series_tail_survives_nat_tokens() -> None:
    """date 列中间夹 NaT 时仍判为时间序列（尾部截断不退化）。

    NaT 在 str() 下变成字面量 "NaT"，若不过滤会让排序判定失败 →
    静默退回头部截断，即时间序列拿到最旧的一段。
    """
    dates = _dates("2026-11-01", 5)
    dates[2] = None
    frame = pd.DataFrame({"date": dates, "close": range(5)})
    env = tools.history(_runtime(frame), "600519", n=5, max_rows=2)
    shown = [row["date"] for row in env["data"]]
    # 保留最新一段（倒数两行），而不是最旧两行
    assert shown == [dates[-2], dates[-1]]
    assert env["meta"]["truncated"] is True
