"""index_daily notebook 守护：结构、口径、防回归（不引 nbformat 依赖）。

守护两类问题：
1. 结构漂移——builder 改了但 notebook 没重建；
2. 口径回归——三色灯退回「跨指数横向比较」而非**该键自身历史分位**，
   或分位基准点取错方向（历史事故：SDK 用 reversed(pts) 把最旧点当今天）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NB = REPO / "docs" / "notebooks" / "index_daily.ipynb"
BUILDER = REPO / "tools" / "build_index_daily_nb.py"


def _nb() -> dict:
    return json.loads(NB.read_text(encoding="utf-8"))


def _sources(kind: str) -> list[str]:
    return ["".join(c["source"]) for c in _nb()["cells"] if c["cell_type"] == kind]


def _all_src() -> str:
    return "\n".join(_sources("code"))


def test_notebook_matches_builder():
    """产物必须与 builder 同步重建（防止改了源码忘了落盘）。"""
    assert NB.exists(), "docs/notebooks/index_daily.ipynb 缺失"
    nb = _nb()
    assert nb["nbformat"] == 4
    builder = BUILDER.read_text(encoding="utf-8")
    # builder 里 CELLS 的每个 cell 标记数量应与产物一致
    assert builder.count('    md("""') + builder.count('    code("""') == len(nb["cells"]), \
        "builder 的 cell 数与 notebook 产物不一致，请重跑 tools/build_index_daily_nb.py"
    for cell in nb["cells"]:
        assert "".join(cell["source"]).strip(), "notebook 不应有空 cell"


def test_three_color_zones_use_own_percentile():
    """三色灯必须按自身历史分位切档，而不是盈利收益率跨指数比较。"""
    src = _all_src()
    assert "def zone_of_pct(" in src, "缺失 zone_of_pct（自身分位三档）"
    assert "ZONE_CUT = (0.30, 0.70)" in src, "档位阈值应为 绿<30% / 黄30~70% / 红>70%"
    # 旧口径（盈利收益率 vs 2×国债）不得再作为档位依据
    assert "zone_of(ey" not in src and "2 * rf" not in src, \
        "档位不应退回盈利收益率法（应使用自身历史分位）"
    for zone in ("绿档", "黄档", "红档"):
        assert zone in src, f"缺少 {zone}"


def test_percentile_anchors_on_latest_point():
    """复算函数必须用 points[0]（新→旧序列的最新点）作为当前值。"""
    src = _all_src()
    assert "points 是新→旧" in src or "新→旧" in src, "代码需注明序列方向"
    assert "cur = pts[0][col]" in src, "复算当前值必须取 pts[0]"
    assert "reversed(" not in src, "不得对序列做 reversed 后再取当前值（历史 bug）"


def test_window_and_measure_switches_exist():
    """必须有窗口（3y/5y/10y）与口径（整体法/中位数）切换。"""
    src = _all_src()
    assert 'WINDOW = "5y"' in src, "缺少窗口参数"
    for w in ("3y", "5y", "10y"):
        assert w in src, f"缺少窗口选项 {w}"
    assert 'MEASURE = "pe"' in src and "pe_med" in src, "缺少整体法/中位数口径切换"
    assert 'cli.index.trend(k, WINDOW)' in src, "trend 调用需传窗口参数"


def test_three_groups_covered():
    """宽基 / 行业 / 红利三组都要出榜（对齐对标产品的覆盖面）。"""
    src = _all_src()
    assert '("broad", "industry", "dividend")' in src, "必须遍历三组键"
    assert "industry_list(1)" in src, "行业键应由行业名录在运行时解析"
    for key in ("index.csidividend", "index.hs300"):
        assert key in src, f"缺关键示例键 {key}"


def test_rows_carry_date_and_sample():
    """每行必须带数据日期与样本数，缓存未命中要显式降级而非静默出错值。"""
    src = _all_src()
    for col in ("数据日期", "窗口", "样本", "窗口不足"):
        assert col in src, f"表格缺列 {col}"
    assert 't.get("as_of")' in src, "数据日期应取自 trend 的 as_of"
    assert "win_trunc" in src, "窗口不足必须显式标记"


def test_has_independent_recompute():
    """内置独立复算：SDK 分位与按序列重算必须逐位一致（防静默错值）。"""
    src = _all_src()
    assert "def pct_recompute(" in src, "缺少独立复算函数"
    assert "rank0" in src and "len(vals) - 1" in src, "复算须用 rank0/(n-1) 口径"
    assert "独立复算" in src, "需要打印复算对账结果"


def test_market_temperature_uses_pool_median():
    """市场温度取全池分位中位数，不是绿档占比。"""
    src = _all_src()
    assert "全池分位中位数" in src, "星级应由全池分位中位数决定"
    assert "mid < 20" in src and "mid < 80" in src, "星级档位未定义"


def test_no_leak_and_no_secrets():
    """notebook 不得含竞品名、数据商名或密钥字段。"""
    text = json.dumps(_nb(), ensure_ascii=False)
    for word in ("理杏仁", "雪球", "同花顺"):
        assert word not in text, f"notebook 不得出现第三方产品名：{word}"
    # 用词边界匹配 wind，否则会误伤 window/win_trunc 这类合法标识符
    assert not re.search(r"\bWind\b|\bwind\b(?!ow)", text), "notebook 不得出现数据商名"
    assert "client_secret" not in text.lower(), "notebook 不得出现密钥字段"
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text), "疑似出现 API key"


def test_disclaimer_present():
    """措辞红线：档位是参考区间、非官方阈值；不构成投资建议。"""
    text = json.dumps(_nb(), ensure_ascii=False)
    assert "非官方阈值" in text, "缺少『估值参考区间，非官方阈值』表述"
    assert "不构成任何投资建议" in text or "不构成投资建议" in text, "缺少免责声明"
    for banned in ("建议买入", "建议卖出", "目标价", "抄底"):
        assert banned not in text, f"不得出现投资建议类措辞：{banned}"
