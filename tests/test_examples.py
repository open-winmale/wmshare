"""示例冒烟（11/11 全覆盖）：离线示例真实执行；凭证示例用共享 FakeClient 端到端跑。

签名正确性由 test_docs 的 AST 门禁全量把关；本文件保证每个示例在罐头数据上
真的跑得完、关键输出（含单位口径注释）不回退。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

import wmshare

from fake_client import fake_client
from wmshare._demo import load_demo_snapshot

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
EXAMPLES = REPO / "examples"


@pytest.fixture(scope="module")
def snapshot():
    return load_demo_snapshot()


def _run_example(name: str, demo: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    command = [sys.executable, str(EXAMPLES / name)]
    if demo:
        command.append("--demo")
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"wmshare_example_{name[:-3]}",
                                                  EXAMPLES / name)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 离线示例：子进程真实执行（不联网、零凭证） ----

@pytest.mark.parametrize("name,needles", [
    # 计数从目录派生（精选码数会随 curated 组增减），只锁结构不锁数字。
    ("02_catalog_tour.py", ["数据域：18", "指标代码：精选 ", "/ 目录全量 2752"]),
    ("03_error_handling.py", ["[auth]", "[limit]", "open.winmale.com",
                              "WMSHARE_CLIENT_ID"]),
    ("09_ai_skill_setup.py", ["skill 位置", "skill 自检", "cat.search"]),
    ("12_mcp_server.py", ["wmshare-mcp 位置", "wmshare-mcp doctor", "mcpServers"]),
])
def test_offline_example_runs(name, needles):
    result = _run_example(name)
    assert result.returncode == 0, result.stderr
    for needle in needles:
        assert needle in result.stdout, f"{name} 缺输出 {needle!r}"
    if name == "02_catalog_tour.py":
        # 精选码数必须与目录实际值一致（防示例打印写死数字）
        curated = sum(len(g.get("metrics") or [])
                      for d in wmshare.load().domains.values()
                      for g in d.get("metric_groups") or [])
        assert f"精选 {curated} /" in result.stdout


# ---- 凭证示例：注入共享 FakeClient，端到端跑 main() ----

def test_01_quickstart(snapshot, capsys):
    _load("01_quickstart.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    roe = snapshot["data"]["indicators"]["$ROE_TTM_LAST"]
    dps = snapshot["data"]["dividend"]["last"]["600519"]["dps"]
    notice = snapshot["data"]["notice_event"]
    assert f"ROE(TTM)={roe:.2%}" in out
    assert f"DPS {dps:.5f}" in out
    assert notice["title"] in out
    assert "DataFrame" not in out
    # 批量段落：必须展示「家数 → 请求数」对比（新手动线，防回退成逐票循环）
    assert "演示宇宙 10 家：1 次请求" in out
    assert "逐票需 10 次" in out


def test_04_screener(snapshot, capsys):
    _load("04_screener.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "站上MA20=True" in out
    summary = snapshot["data"]["screener"]["breadth_summary"]
    assert f"总数={summary['total']}" in out
    assert "涨幅榜 Top5 / 跌幅榜 Top3" in out
    mover = snapshot["data"]["screener"]["top_movers_up"][0]["percent"]
    assert f"{mover:+.2%}" in out


def test_05_dividend_screener(snapshot, capsys):
    _load("05_dividend_screener.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    expected = snapshot["data"]["dividend"]["yield_ttm"]["600519"]
    assert f"TTM股息率={expected:.4f}" in out
    assert "筛选表达式" in out


def test_14_cbond_double_low_needs_credentials(capsys):
    """演示快照不含 cbond 域：示例应给出明确的「需凭证」提示而非崩溃。"""
    _load("14_cbond_double_low.py").main(fake_client())
    out = capsys.readouterr().out
    assert "需真实凭证" in out


def test_15_backtest_ma(snapshot, capsys):
    """单股回测示例：演示数据 120 根跑出成交明细 + 汇总，不回退成空结果。"""
    _load("15_backtest_ma.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "ma_cross(fast=5, slow=20)" in out
    assert "成交明细" in out and "金叉" in out
    assert "最大回撤" in out
    assert "演示快照" in out                     # 口径提示必须出现


def test_12_futures_macro(capsys):
    _load("13_futures_macro.py").main(fake_client())
    out = capsys.readouterr().out
    assert "郑糖主力收盘 = 5354.0" in out
    assert "外盘 WTI = 5354.0" in out
    assert "$CPI 频率=month" in out               # 时序结构：frequency 字段
    assert "（价格指数点，上年同期=100）" in out    # 原生口径注释（非小数比率）
    assert "107.1 万亿元" in out                   # GDP 原值=元
    assert "0.016822（小数，即 1.68%）" in out     # 中债收益率小数口径


def test_06_indicator_tour(snapshot, capsys):
    _load("06_indicator_tour.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "指标组 11 个" in out                  # cat.metric_groups() 真目录
    expected = snapshot["data"]["dividend"]["yield_ttm"]["600519"]
    assert f"TTM 股息率 = {expected:.4f}（{expected:.2%}）" in out
    assert "（" in out


def test_07_stocks_industry_batch(capsys):
    pytest.importorskip("pandas")  # call_batch(...).to_df() 需要可选依赖
    _load("07_stocks_industry_batch.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "演示宇宙共 10 家" in out
    assert "批量 1 次请求" in out
    assert "省 10 倍配额" in out
    assert "第 1 批 10 家" in out
    assert "「银行」20 行快照" in out


def test_08_pandas_analysis(capsys):
    pytest.importorskip("pandas")
    _load("08_pandas_analysis.py").main(fake_client())
    out = capsys.readouterr().out
    assert "站上 MA20：True" in out
    assert "近 20 日主力净流入合计：" in out
    assert "近 10 次分红" in out


def test_10_notice_monitor(snapshot, capsys):
    _load("10_notice_monitor.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    event = snapshot["data"]["notice_event"]
    title = event["title"]
    date = event["date"]
    assert f"[cn] 600519 贵州茅台｜{title}（{date}）" in out
    assert "本轮交付 1 条" in out
    assert "本轮交付 0 条" in out                # ack 后不重投（at-least-once 语义）
    assert "seek_oldest('cn')" in out


def test_11_statements_tour(capsys):
    _load("11_statements_tour.py").main(fake_client())
    out = capsys.readouterr().out
    assert "利润表可用年报：[2025, 2024" in out   # 年份降序
    assert "资产负债表：" in out and "行科目；如「" in out
    assert "差额占比 " in out                     # diffp 小数 → 百分比展示
    assert "2024 年审计意见：标准无保留意见" in out


def test_16_metric_adapter(snapshot, capsys):
    """适配层示例：分类发现 + 长表 + 多标的小列表，不改变旧接口。"""
    _load("16_metric_adapter.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "指标 scope：" in out
    assert "valuation：可组合组" in out
    assert "适配长表（4 行）" in out
    assert "多标的小列表：2 标的" in out
    assert "screener.query(fields=codes" in out


def test_examples_index_covers_dir():
    """examples/README.md 课程表必须覆盖目录里每个脚本（防孤儿示例）。"""
    index = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    scripts = sorted(p.name for p in EXAMPLES.glob("*.py"))
    assert len(scripts) == 16, f"示例应恰为 16 个（编号课程），实际 {len(scripts)}：{scripts}"
    for name in scripts:
        assert f"`{name}`" in index, f"examples/README.md 缺 {name} 的索引行"


@pytest.mark.parametrize("name", [
    "01_quickstart.py", "04_screener.py", "05_dividend_screener.py",
    "06_indicator_tour.py", "07_stocks_industry_batch.py", "08_pandas_analysis.py",
    "10_notice_monitor.py", "11_statements_tour.py", "15_backtest_ma.py",
    "16_metric_adapter.py",
])
def test_credential_examples_run_with_demo_snapshot(name):
    if name in ("07_stocks_industry_batch.py", "08_pandas_analysis.py"):
        pytest.importorskip("pandas")
    result = _run_example(name, demo=True)
    assert result.returncode == 0, result.stderr
    assert "演示模式" in result.stdout
