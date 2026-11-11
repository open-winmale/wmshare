"""R1 / M5：llms-full 有指标族摘要、不内联 INDICATORS 全文、体积受预算约束。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "gen_llms.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_llms_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_full_text_has_brief_and_respects_budget():
    mod = _load()
    content = mod.build_llms_full_txt()
    size = len(content.encode("utf-8"))
    assert size < mod.FULL_SIZE_BUDGET
    assert "指标族摘要" in content and "未内联进本文件" in content
    # 摘要按目录生成，族 id 不能写死在生成器里
    import wmshare
    for group in wmshare.load().metric_groups():
        assert f"`{group['id']}`" in content


def test_indicators_full_text_is_not_inlined():
    mod = _load()
    assert "docs/INDICATORS.md" not in mod.FULL_PARTS
    assert mod.FULL_SIZE_BUDGET < 400_000  # 内联 205 KB 会直接击穿
    content = mod.build_llms_full_txt()
    assert "## 4. 股票指标码" not in content  # INDICATORS 全文的独有 H2


def test_llms_txt_optional_section_states_not_inlined():
    mod = _load()
    text = mod.build_llms_txt()
    assert "## Optional" in text
    assert "**未内联**进 llms-full.txt" in text
    assert "指标族摘要" in text


def test_budget_is_a_hard_assertion(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "FULL_SIZE_BUDGET", 1000)
    with pytest.raises(ValueError, match="超过预算"):
        mod.build_llms_full_txt()
