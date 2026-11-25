"""S5 遗留项：CI 覆盖率策略的机器锚点。

只校验**覆盖率 step 的 run 命令行本身**。不锚定注释文本：注释里出现
`--cov-branch` 字样会让「删掉 run 里的 --cov-branch」这类改动假绿，
而改写注释措辞又会误拒合法输入——两种都是不可信的门禁。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO / "pyproject.toml"


def _coverage_run_line() -> str:
    """只返回覆盖率 step 的 run: 命令行，不含上方注释。"""
    for line in CI.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*run:\s*pytest\s", line):
            return line.strip()
    raise AssertionError("ci.yml 找不到覆盖率 step 的 run 命令")


def test_ci_coverage_step_enables_branch_coverage():
    run = _coverage_run_line()
    assert "--cov=wmshare" in run
    assert "--cov-branch" in run
    assert "--cov-fail-under=85" in run


def test_fail_under_matches_pyproject_baseline():
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r"^fail_under\s*=\s*(\d+)$", text, re.M)
    assert m and int(m.group(1)) == 85
    assert "--cov-fail-under=85" in _coverage_run_line()


def test_branch_mode_always_keeps_explicit_floor():
    """开分支口径必须同时带显式阈值，防止只加 --cov-branch 让门禁空转。"""
    run = _coverage_run_line()
    if "--cov-branch" in run:
        assert re.search(r"--cov-fail-under=\d+", run), (
            "启用 --cov-branch 时必须显式给出 --cov-fail-under")


def test_coverage_step_runs_after_install():
    """覆盖率 step 必须在依赖安装之后，避免未装依赖时的假绿/假红。"""
    lines = CI.read_text(encoding="utf-8").splitlines()
    install = next(i for i, line in enumerate(lines)
                   if re.match(r"^\s*run: pip install", line))
    coverage = next(i for i, line in enumerate(lines)
                    if re.match(r"^\s*run: pytest", line))
    assert install < coverage
