"""漂移门禁测试：generated 与 scripts SoT 一致；domains 通过合同校验。

scripts 仓不存在时跳过 extractor --check（CI 外环境）。
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *cmd], cwd=REPO,
                          capture_output=True, text=True)


def test_validate_catalog_green():
    r = _run(["tools/validate_catalog.py"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_api_docs_no_drift():
    r = _run(["tools/gen_api_docs.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_typed_api_no_drift():
    r = _run(["tools/gen_typed_api.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_openapi_no_drift():
    r = _run(["tools/gen_openapi.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_llms_no_drift():
    r = _run(["tools/gen_llms.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_indicators_no_drift():
    r = _run(["tools/gen_indicators.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_extractor_check_no_drift():
    r = _run(["tools/extract_from_scripts.py", "--check"])
    out = r.stdout + r.stderr
    if "not found" in out and "upstream" in out:
        import pytest
        pytest.skip("upstream 不可见（维护者本机才有），跳过 extractor 漂移检查")
    assert r.returncode == 0, out
