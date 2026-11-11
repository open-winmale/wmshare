"""CHANGELOG 段落抽取器（GitHub Release body 来源）的契约测试。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "changelog_section", REPO / "tools" / "changelog_section.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()


def test_extracts_current_release_section():
    body = MOD.section((REPO / "CHANGELOG.md").read_text(encoding="utf-8"), "1.16.3")
    assert body.startswith("### ")
    assert "## [" not in body, "正文不应跨到下个版本段"
    assert len(body.splitlines()) > 5


def test_accepts_v_prefixed_tag():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert MOD.section(text, "v1.16.3") == MOD.section(text, "1.16.3")


def test_unreleased_section_is_empty_and_rejected():
    """[Unreleased] 无正文：绝不能拿它去发一个没有说明的 Release。"""
    with pytest.raises(KeyError):
        MOD.section((REPO / "CHANGELOG.md").read_text(encoding="utf-8"), "Unreleased")


def test_unknown_version_raises():
    with pytest.raises(KeyError):
        MOD.section("# Changelog\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- x\n", "9.9.9")


def test_last_section_runs_to_eof():
    text = "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- tail\n"
    assert MOD.section(text, "1.0.0") == "### Added\n- tail"


def test_check_mode_exits_zero(capsys):
    assert MOD.main(["1.16.3", "--check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_missing_version_exits_nonzero(monkeypatch, capsys):
    """CI 用 tag 抽 body；抽不到必须非零退出，不能静默发空 Release。"""
    monkeypatch.setattr(MOD, "CHANGELOG", Path(__file__))  # 该文件没有版本段
    assert MOD.run(["1.16.3"]) == 1
    assert "FAIL" in capsys.readouterr().err
