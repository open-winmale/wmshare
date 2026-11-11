"""M10：仓内许可一致性门禁的机器锚点。

锚定三件事，防止门禁被改坏或声明漂移：
  1. ``tools/check_license.py --check`` 在干净树上退出 0；
  2. ``ci.yml`` 真正接入了许可一致性门禁 step；
  3. ``SECURITY.md`` 含有 BSD-3-Clause 声明（5 处互校之一）；
  4. 破坏性探针：pyproject 许可被改掉时应红，验证门禁不是空转。
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
SECURITY = REPO / "SECURITY.md"


def _load_check_license():
    spec = importlib.util.spec_from_file_location(
        "check_license_under_test", REPO / "tools" / "check_license.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_license_passes_on_clean_tree():
    r = subprocess.run(
        [sys.executable, "tools/check_license.py", "--check"],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "BSD-3-Clause" in r.stdout


def test_ci_wires_license_gate():
    ci = CI.read_text(encoding="utf-8")
    assert "python tools/check_license.py --check" in ci, (
        "ci.yml 未接入许可一致性门禁")


def test_security_md_declares_license():
    assert "BSD-3-Clause" in SECURITY.read_text(encoding="utf-8"), (
        "SECURITY.md 缺少 BSD-3-Clause 许可声明（5 处互校之一）")


def test_check_license_detects_inconsistent_pyproject(monkeypatch):
    """破坏性探针：pyproject 许可被改掉时应红，验证门禁不是空转。

    不走真实文件（sandbox 下 pytest 的定名临时目录会与已有目录冲突），
    改为 monkeypatch ``_read`` 把 pyproject 内容替换成 MIT，断言 collect() 报出不一致。
    """
    cl = _load_check_license()
    good = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    bad_text = re.sub(r'^license\s*=\s*"[^"]+"', 'license = "MIT"', good, flags=re.M)
    real_read = cl._read

    def fake_read(p):
        if Path(p).name == "pyproject.toml":
            return bad_text
        return real_read(p)

    monkeypatch.setattr(cl, "_read", fake_read)
    canonical, sources, forbidden = cl.collect()
    assert sources["pyproject.toml::project.license"] != canonical
    assert any(got != canonical for got in sources.values())

