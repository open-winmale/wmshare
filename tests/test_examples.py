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

from fake_client import fake_client

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
EXAMPLES = REPO / "examples"


def _run_example(name: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run([sys.executable, str(EXAMPLES / name)],
                          capture_output=True, text=True, env=env, timeout=60)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"wmshare_example_{name[:-3]}",
                                                  EXAMPLES / name)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 离线示例：子进程真实执行（不联网、零凭证） ----

@pytest.mark.parametrize("name,needles", [
    ("02_catalog_tour.py", ["数据域：17", "指标代码：精选 74 / 目录全量 2752"]),
    ("03_error_handling.py", ["[auth]", "[limit]", "open.winmale.com",
                              "WMSHARE_CLIENT_ID"]),
    ("09_ai_skill_setup.py", ["skill 位置", "skill 自检", "cat.search"]),
])
def test_offline_example_runs(name, needles):
    result = _run_example(name)
    assert result.returncode == 0, result.stderr
    for needle in needles:
        assert needle in result.stdout, f"{name} 缺输出 {needle!r}"


# ---- 凭证示例：注入共享 FakeClient，端到端跑 main() ----

def test_01_quickstart(capsys):
    _load("01_quickstart.py").main(fake_client())
    out = capsys.readouterr().out
    assert "ROE(TTM)=33.24%" in out          # 0.3324 小数 → 33.24%
    assert "DPS 28.02" in out
    assert "回购股份的公告" in out
    assert "DataFrame" not in out
    # 批量段落：必须展示「家数 → 请求数」对比（新手动线，防回退成逐票循环）
    assert "全市场 3 家：1 次请求" in out
    assert "逐票需 3 次" in out


def test_04_screener(capsys):
    _load("04_screener.py").main(fake_client())
    out = capsys.readouterr().out
    assert "站上MA20=True" in out
    assert "总数=5685  涨=4567(80.3%)" in out   # *_pct 百分数数值
    assert "涨幅榜 Top5 / 跌幅榜 Top3" in out
    assert "+5.21%" in out                       # percent 小数格式化


def test_05_dividend_screener(capsys):
    _load("05_dividend_screener.py").main(fake_client())
    out = capsys.readouterr().out
    assert "TTM股息率=0.0396" in out
    assert "3.96%" in out                        # call_batch 批量结果同为小数口径
    assert "筛选表达式" in out


def test_06_indicator_tour(capsys):
    _load("06_indicator_tour.py").main(fake_client())
    out = capsys.readouterr().out
    assert "指标组 11 个" in out                  # cat.metric_groups() 真目录
    assert "TTM 股息率 = 0.0396（3.96%）" in out
    assert "（42%）" in out                       # 分位小数 → 百分比展示
    assert "位置=54%" in out


def test_07_stocks_industry_batch(capsys):
    pytest.importorskip("pandas")  # call_batch(...).to_df() 需要可选依赖
    _load("07_stocks_industry_batch.py").main(fake_client())
    out = capsys.readouterr().out
    assert "全市场共 3 家" in out
    assert "批量 1 次请求" in out
    assert "省 3 倍配额" in out
    assert "第 1 批 3 家" in out
    assert "「银行」5 行快照" in out


def test_08_pandas_analysis(capsys):
    pytest.importorskip("pandas")
    _load("08_pandas_analysis.py").main(fake_client())
    out = capsys.readouterr().out
    assert "站上 MA20：True" in out
    assert "近 20 日主力净流入合计：2,000 元" in out
    assert "近 10 次分红" in out


def test_10_notice_monitor(capsys):
    _load("10_notice_monitor.py").main(fake_client())
    out = capsys.readouterr().out
    assert "[cn] 600519 贵州茅台｜关于回购股份的公告（2026-10-28）" in out
    assert "本轮交付 1 条" in out
    assert "本轮交付 0 条" in out                # ack 后不重投（at-least-once 语义）
    assert "seek_oldest('cn')" in out


def test_11_statements_tour(capsys):
    _load("11_statements_tour.py").main(fake_client())
    out = capsys.readouterr().out
    assert "利润表可用年报：['2025', '2024']" in out   # 年份降序
    assert "资产总计" in out                            # 资产负债表科目行（中文名）
    assert "差额占比 2.00%" in out                     # diffp 小数 → 百分比展示
    assert "2024 年审计意见：标准无保留意见" in out


def test_examples_index_covers_dir():
    """examples/README.md 课程表必须覆盖目录里每个脚本（防孤儿示例）。"""
    index = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    scripts = sorted(p.name for p in EXAMPLES.glob("*.py"))
    assert len(scripts) == 11, f"示例应恰为 11 个（编号课程），实际 {len(scripts)}：{scripts}"
    for name in scripts:
        assert f"`{name}`" in index, f"examples/README.md 缺 {name} 的索引行"
