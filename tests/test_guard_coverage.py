"""guard_coverage 的负向锚点：空声明不得刷分 / 越界先验 / JSON 自带判定。"""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "guard_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("guard_coverage_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_empty_guard_declaration_does_not_count():
    mod = _load()
    for empty in ({}, {"units": None}, {"ranges": []}, {"checks": []},
                  {"units": {}, "ranges": [], "checks": ""}):
        assert mod.has_guard(empty) is False, empty
    assert mod.has_guard({"units": {"volume": "lot"}}) is True
    assert mod.has_guard({"ranges": {"percent": [-1, 30]}}) is True
    assert mod.has_guard({"checks": ["volume_amount"]}) is True


def test_collect_is_self_consistent_and_floor_is_enforced():
    mod = _load()
    result = mod.collect(mod.DEFAULT_DOMAINS)
    assert result["domains"] == 18
    assert 0 < result["guarded"] <= result["functions"]
    assert result["ratio"] == round(result["guarded"] / result["functions"], 6)
    floor = str(result["ratio"])
    assert mod.main(["--min", floor]) == 0
    assert mod.main(["--min", str(result["ratio"] + 0.001)]) == 1


def test_min_out_of_range_is_rejected_before_report(capsys):
    mod = _load()
    assert mod.main(["--min", "1.5"]) == 2
    assert "guard coverage:" not in capsys.readouterr().out  # 不能先打印正常报表


def test_json_output_carries_pass_and_floor():
    mod = _load()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(["--json", "--min", "1.0"])
    assert rc == 1
    payload = json.loads(buf.getvalue())
    assert payload["pass"] is False and payload["floor"] == 1.0

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(["--json"])
    assert rc == 0
    assert json.loads(buf.getvalue())["pass"] is True
