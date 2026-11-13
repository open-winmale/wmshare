"""tools/validate_units.py 的负例测试。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from tools import validate_units as V

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"


def _base():
    ledger = yaml.safe_load((CATALOG / "units.yaml").read_text(encoding="utf-8"))
    metrics = json.loads((CATALOG / "generated" / "metrics.json").read_text(encoding="utf-8"))
    sidecar = json.loads(
        (CATALOG / "generated" / "metric_taxonomy.json").read_text(encoding="utf-8"))
    return ledger, metrics, sidecar


def _write(tmp_path: Path, ledger: dict, metrics: dict, sidecar: dict):
    paths = (tmp_path / "units.yaml", tmp_path / "metrics.json",
             tmp_path / "metric_taxonomy.json")
    paths[0].write_text(yaml.safe_dump(ledger, allow_unicode=True), encoding="utf-8")
    paths[1].write_text(json.dumps(metrics), encoding="utf-8")
    paths[2].write_text(json.dumps(sidecar), encoding="utf-8")
    return paths


def test_real_ledger_is_valid():
    assert V.validate() == []


def test_unknown_code_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    broken["overrides"]["$NO_SUCH_CODE"] = {
        "base_unit": "shares", "native_unit": "lot", "note": "x"}
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("$NO_SUCH_CODE" in e and "metrics.json" in e for e in errors)


def test_base_equals_native_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    broken["overrides"]["$VOLUME_DAY"]["native_unit"] = "shares"
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("base_unit == native_unit" in e for e in errors)


def test_missing_note_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    del broken["overrides"]["$VOLUME_DAY"]["note"]
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("note" in e for e in errors)


def test_invalid_vocab_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    broken["overrides"]["$VOLUME_DAY"]["native_unit"] = "bogus_unit"
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("不在词表内" in e for e in errors)


def test_missing_volume_family_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    del broken["overrides"]["$VOLUME"]
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("成交量族未登记" in e for e in errors)


def test_base_unit_must_match_sidecar_unit_kind(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    broken["overrides"]["$VOLUME_DAY"]["base_unit"] = "ratio"
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("与 sidecar unit_kind" in e for e in errors)


def test_invariant_unknown_code_is_rejected(tmp_path):
    ledger, metrics, sidecar = _base()
    broken = copy.deepcopy(ledger)
    broken["invariants"] = [{"id": "x", "desc": "y", "codes": ["$NOT_A_CODE"]}]
    errors = V.validate(*_write(tmp_path, broken, metrics, sidecar))
    assert any("目录外的码" in e for e in errors)
