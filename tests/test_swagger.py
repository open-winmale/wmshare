"""Swagger 单文件页面：语法与内联 spec 的防回归检查（离线）。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HTML = REPO / "docs" / "swagger.html"
SPEC = REPO / "docs" / "openapi.json"


def test_swagger_inlines_spec_and_uses_valid_constructor():
    text = HTML.read_text(encoding="utf-8")
    assert "window.SwaggerUIBundle({" in text
    assert "window SwaggerUIBundle" not in text
    assert "spec:" in text
    assert "/v1/analysis/xs/eval" in text
    # openapi.json 仍是可独立导入的合同文件
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.1")


def test_swagger_inline_javascript_syntax(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用，跳过 JS 语法检查")
    text = HTML.read_text(encoding="utf-8")
    m = re.search(r"<script>\s*(.*?)</script>", text, re.S)
    assert m, "swagger.html 缺少内联 script"
    script = tmp_path / "swagger_check.js"
    script.write_text(m.group(1), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
