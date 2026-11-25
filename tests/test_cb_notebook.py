"""cb 双低 notebook 守护：ipynb 存在、已执行、含 board 调用与实测日期（不引 nbformat 依赖）。"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NB = REPO / "docs" / "notebooks" / "cb_double_low.ipynb"


def _nb() -> dict:
    return json.loads(NB.read_text(encoding="utf-8"))


def test_notebook_is_valid_and_executed():
    nb = _nb()
    assert nb["nbformat"] == 4
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) >= 2, "notebook 缺少代码单元"
    assert any(c.get("execution_count") for c in code_cells), "notebook 未执行"
    assert any(c.get("outputs") for c in code_cells), "notebook 没有嵌入输出"


def test_notebook_uses_official_facade_only():
    """只用官方 facade（cli.cbond.* + cb.valuation），不得出现底层 call 直调。"""
    src = "\n".join("".join(c["source"]) for c in _nb()["cells"]
                    if c["cell_type"] == "code")
    assert "cli.cbond.board()" in src, "双低榜数据源应为 cli.cbond.board()"
    assert "cli.cbond.event_list()" in src
    assert "cli.cbond.kline_window" in src
    assert "wmshare.cb.valuation" in src and "ytm_after_tax" in src, \
        "YTM 必须与日更线同源（wmshare.cb.valuation），不得在 notebook 另写近似公式"
    assert "cli.call(" not in src and ".call(\"" not in src, "不得绕过 facade 直调底层 call"


def test_notebook_carries_date_stamp_and_no_secrets():
    text = json.dumps(_nb(), ensure_ascii=False)
    assert "2026-11-07" in text and "真实数据" in text, "notebook 缺少实测日期标注"
    assert "basis" in text, "YTM 档位标注（schedule/constant）应出现在口径与表格中"
    assert "client_secret" not in text.lower(), "notebook 不得出现密钥字段"
