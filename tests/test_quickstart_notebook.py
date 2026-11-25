"""首屏 notebook 守护：ipynb 存在、已执行、含选股实战调用与实测日期（不引 nbformat 依赖）。"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NB = REPO / "docs" / "notebooks" / "quickstart.ipynb"


def _nb() -> dict:
    return json.loads(NB.read_text(encoding="utf-8"))


def test_notebook_is_valid_and_executed():
    nb = _nb()
    assert nb["nbformat"] == 4
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) >= 2, "notebook 缺少代码单元"
    assert any(c.get("execution_count") for c in code_cells), "notebook 未执行"
    assert any(c.get("outputs") for c in code_cells), "notebook 没有嵌入输出"


def test_notebook_matches_readme_scenario():
    """notebook 代码 = README「选股实战」同一段逻辑（批量股息率 → 逐票 PE/十年分位 → 过滤）。"""
    src = "\n".join("".join(c["source"]) for c in _nb()["cells"]
                    if c["cell_type"] == "code")
    assert 'batch_all("bonus.snapshot_yield_ttm"' in src
    assert "$PCT_PE_TTM_10Y_LAST" in src and "pct <= 0.5" in src
    assert "Client.from_env()" in src


def test_notebook_carries_date_stamp_and_no_secrets():
    text = json.dumps(_nb(), ensure_ascii=False)
    assert "2026-10-30" in text and "真实数据" in text, "notebook 缺少实测日期标注"
    assert "client_secret" not in text.lower(), "notebook 不得出现密钥字段"
