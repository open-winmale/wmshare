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
        assert t["pe_pct"] is None or node.get("p") is None, "截断窗口不应给出分位"


def test_bad_window_falls_back_to_5y():
    t = demo_client().index.trend("index.hs300", "7y")
    assert t["window"] == "5y"


def test_demo_direction_matches_live_contract():
    """demo 与 live 必须同向：两边都由 points[0] 表示最新点。"""
    t = _trend()
    assert t["points"][0]["date"] >= t["points"][-1]["date"]
