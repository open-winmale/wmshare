"""示例冒烟（11/11 全覆盖）：离线示例真实执行；凭证示例用共享 FakeClient 端到端跑。

签名正确性由 test_docs 的 AST 门禁全量把关；本文件保证每个示例在罐头数据上
真的跑得完、关键输出（含单位口径注释）不回退。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
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

def _catalog_counts_needles() -> list[str]:
    """02 示例计数从目录动态派生（2.0 起新域随上游增减，不再手写死数）。"""
    from wmshare.catalog import load
    s = load().stats()
    return [f"数据域：{s['domains']}", "指标代码：精选 ",
            f"/ 目录全量 {s['metric_catalog_total']}"]


@pytest.mark.parametrize("name,needles", [
    # 计数从目录派生（精选码数会随 curated 组增减），只锁结构不锁数字。
    ("02_catalog_tour.py", _catalog_counts_needles()),
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


def _cb_stub_row(code="110001", **kw):
    """最小可用转债面板行（与 tests/test_cb_daily.py 的 _row 同构）。"""
    row = {
        "bondCode": code, "bondName": f"债{code}", "stockCode": "600000",
        "stockName": "浦发银行", "bondPrice": 100.0, "premiumRatio": 0.05,
        "remainSize": 5.0e9, "issueScale": 6.0e9, "expireDate": "2029-11-06",
        "redeemTrig": 13.0, "stockPrice": 10.0, "convertPrice": 10.0,
        "redeemValue": 110.0, "couponIr": 0.015, "asOf": "2026-11-06",
    }
    row.update(kw)
    return row


def test_14_cbond_double_low_with_facade_shaped_stub(capsys):
    """示例 14 管线段端到端：桩按 2.0 门面形态（DataFrame 面板）出数。

    曾用 ``rows.get("rows", [])`` 兜底——对 DataFrame 恒得 []，示例静默 0 行
    而测试不红。此用例把「cbond 成品链在门面收口下仍可用」锁进 CI。
    """
    pytest.importorskip("pandas")
    import pandas as pd

    from wmshare.api import CbondApi
    from wmshare.cb import DailyConfig, run_daily

    rows = [_cb_stub_row("110001"), _cb_stub_row("110002")]

    class _StubCli:
        """最小客户端桩：board 返回 DataFrame（复刻真实门面收口形态）。"""

        def __init__(self):
            self.macro = types.SimpleNamespace(bond_curve=lambda name, tenor: 0.02)
            self._api = CbondApi(self)        # article/figures 是纯计算，不用 self._c

        def call_batch(self, name, symbols, **kw):
            class _R:
                results: dict[str, dict] = {}
            return _R()

        @property
        def cbond(self):
            outer = self

            class _Ns:
                board = staticmethod(lambda: pd.DataFrame(rows))
                event_list = staticmethod(lambda: [])
                kline_window = staticmethod(
                    lambda code, n: {"samplingName": ["2026-11-06"], "close": [100.0]})
                daily = staticmethod(
                    lambda top_n=20: run_daily(
                        outer, config=DailyConfig(top_n=top_n, enrich=False, curves=False)))
                article = outer._api.article
                figures = outer._api.figures

            return _Ns()

    _load("14_cbond_double_low.py").main(_StubCli())
    out = capsys.readouterr().out
    assert "board 全表 2 行 · 在市 2 只" in out
    assert "债110001" in out and "双低=" in out
    assert "快照日 2026-11-06" in out                    # 管线段跑通（非「返回空」降级）
    assert "cli.cbond.article()" in out                 # 成稿段也跑通


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
    assert "利润表：" in out and "审计意见" in out   # 三表 + 审计意见
    assert "资产负债表：" in out and "行科目；如「" in out
    assert "季报档" in out                       # period=quarter 季报全档
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


def test_17_prr_dividend_screen(capsys):
    """红利排雷：演示客户端无全市场索引 → 罐头行走通本地三步，方向与 live 一致。"""
    _load("17_prr_dividend_screen.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "全市场命中 7 只" in out
    assert "-2 只 → 5" in out and "-1 只 → 4" in out and "-1 只 → 3" in out
    # 方向锁死（AGENTS.md 防坑 4）：PRR 最低、覆盖最高的罐头票必须排第一且 CHI=1.00
    top = [line for line in out.splitlines() if "600519" in line]
    assert top and "1.00" in top[0]
    assert "取数失败跳过 0 只" in out          # 失败显式计数，不静默


def test_18_calendar_margin(capsys):
    """2.0 新面：FakeClient 注入端到端（demo 下显式降级不伪造）。"""
    _load("18_calendar_margin.py").main(fake_client(), demo=True)
    out = capsys.readouterr().out
    assert "交易日历" in out


@pytest.mark.parametrize("name", [
    "01_quickstart.py", "04_screener.py", "05_dividend_screener.py",
    "06_indicator_tour.py", "07_stocks_industry_batch.py", "08_pandas_analysis.py",
    "10_notice_monitor.py", "11_statements_tour.py", "15_backtest_ma.py",
    "16_metric_adapter.py", "17_prr_dividend_screen.py",
        "18_calendar_margin.py",
        "19_income_rating.py",
        "21_cli_export.py",
        "22_futures_bars.py",
])
def test_credential_examples_run_with_demo_snapshot(name):
    if name in ("07_stocks_industry_batch.py", "08_pandas_analysis.py"):
        pytest.importorskip("pandas")
    result = _run_example(name, demo=True)
    assert result.returncode == 0, result.stderr
    assert "演示模式" in result.stdout


def test_20_anonymous_trial_degrades_gracefully():
    """匿名示例在服务端未开启时应打印注册指引并正常退出（不抛异常）。

    该示例的前提是服务端开启匿名试用；CI 无外网也不该失败，
    因此断言的是「优雅降级」而非取数成功。
    """
    result = _run_example("20_anonymous_trial.py")
    assert result.returncode == 0, result.stderr
    assert ("匿名试用" in result.stdout) or ("注册" in result.stdout)


def test_examples_index_covers_dir():
    """examples/README.md 课程表必须覆盖目录里每个脚本（防孤儿示例）。"""
    index = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    scripts = sorted(p.name for p in EXAMPLES.glob("*.py"))
    assert len(scripts) == 22, f"示例应恰为 22 个（编号课程），实际 {len(scripts)}：{scripts}"
    for name in scripts:
        assert f"`{name}`" in index, f"examples/README.md 缺 {name} 的索引行"
