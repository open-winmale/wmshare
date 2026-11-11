"""版本一致性门禁：六处互校、SECURITY 表头、只读契约与负向验证。"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "check_version.py"
SOURCES = {
    "INIT": "src/wmshare/__init__.py",
    "PYPROJECT": "pyproject.toml",
    "SERVER_JSON": "server.json",
    "OPENAPI": "docs/openapi.json",
    "CHANGELOG": "CHANGELOG.md",
    "SECURITY": "SECURITY.md",
}


def _load():
    spec = importlib.util.spec_from_file_location("check_version_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tree(tmp_path):
    """把六处声明复制到临时树，让门禁只读写副本，绝不碰仓内文件。"""
    for attr, rel in SOURCES.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dest)
    mod = _load()
    for attr, rel in SOURCES.items():
        setattr(mod, attr, tmp_path / rel)
    mod.REPO = tmp_path
    return mod, tmp_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"负向测试锚点失效：{path.name} 找不到 {old!r}"
    _write(path, text.replace(old, new, 1))


def test_six_sources_agree_on_current_tree(tree, capsys):
    mod, _ = tree
    assert mod.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "六处版本声明均为" in out


def test_check_is_read_only(tree):
    mod, root = tree
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert mod.main(["--check"]) == 0
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_default_mode_equals_check(tree, capsys):
    mod, _ = tree
    assert mod.main([]) == 0
    assert "六处版本声明均为" in capsys.readouterr().out


def test_unknown_flag_is_rejected(tree):
    mod, _ = tree
    with pytest.raises(SystemExit) as err:
        mod.main(["--write"])
    assert err.value.code == 2


@pytest.mark.parametrize("attr,old_tmpl,new,marker", [
    ("PYPROJECT", 'version = "{V}"', 'version = "9.9.9"',
     "pyproject.toml::project.version"),
    ("INIT", '__version__ = "{V}"', '__version__ = "9.9.9"',
     "server.json::version"),
    ("CHANGELOG", "## [{V}]", "## [9.9.9]",
     "CHANGELOG.md::top release"),
])
def test_text_source_mismatch_is_reported(tree, capsys, attr, old_tmpl, new, marker):
    """任一文本声明的版本被改坏时，门禁必须报不一致并点名来源。

    ``old`` 由当前版本模板化——硬编码具体版本号会让这条测试在每次发版后失效。
    """
    import re

    mod, root = tree
    cur = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (root / SOURCES["INIT"]).read_text(encoding="utf-8")).group(1)
    _replace(root / SOURCES[attr], old_tmpl.format(V=cur), new)
    assert mod.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "版本声明不一致" in err and marker in err and "9.9.9" in err


@pytest.mark.parametrize("which", ["root", "package"])
def test_server_json_mismatch_is_reported(tree, capsys, which):
    mod, root = tree
    path = root / SOURCES["SERVER_JSON"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    if which == "root":
        doc["version"] = "9.9.9"
    else:
        doc["packages"][0]["version"] = "9.9.9"
    _write(path, json.dumps(doc, ensure_ascii=False, indent=2))
    assert mod.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "server.json::" in err and "9.9.9" in err


def test_openapi_mismatch_is_reported(tree, capsys):
    mod, root = tree
    path = root / SOURCES["OPENAPI"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["info"]["version"] = "9.9.9"
    _write(path, json.dumps(doc, ensure_ascii=False))
    assert mod.main(["--check"]) == 1
    assert "docs/openapi.json::info.version" in capsys.readouterr().err


@pytest.mark.parametrize("old_tmpl,new,marker,needle", [
    ("| {MINOR}.x  | ✅（当前 minor 线）", "| 9.9.x  | ✅（当前 minor 线）",
     "SECURITY.md::当前 minor 线", "9.9"),
    ("as_of `{V}`", "as_of `9.9.9`", "SECURITY.md::Last reviewed as_of", "9.9.9"),
])
def test_security_mismatch_is_reported(tree, capsys, old_tmpl, new, marker, needle):
    """SECURITY.md 表头/as_of 被改坏时必须报错（锚点随当前版本模板化，防发版后失效）。"""
    import re

    mod, root = tree
    cur = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (root / SOURCES["INIT"]).read_text(encoding="utf-8")).group(1)
    minor = ".".join(cur.split(".")[:2])
    _replace(root / SOURCES["SECURITY"],
             old_tmpl.format(V=cur, MINOR=minor), new)
    assert mod.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert marker in err and needle in err and f"✗ {marker}" in err
