"""tools/validate_metric_taxonomy.py 的负例测试。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from tools import validate_metric_taxonomy as V
from tools import extract_metric_taxonomy as E

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, sidecar: dict, metrics: dict, taxonomy: dict,
           curated: dict) -> tuple[Path, Path, Path, Path]:
    paths = (tmp_path / "metric_taxonomy.json", tmp_path / "metrics.json",
             tmp_path / "taxonomy.yaml", tmp_path / "fund.indicators.yaml")
    paths[0].write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
    paths[1].write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    paths[2].write_text(yaml.safe_dump(taxonomy, allow_unicode=True), encoding="utf-8")
    paths[3].write_text(yaml.safe_dump(curated, allow_unicode=True), encoding="utf-8")
    return paths


def _base():
    sidecar = _load(CATALOG / "generated" / "metric_taxonomy.json")
    metrics = _load(CATALOG / "generated" / "metrics.json")
    taxonomy = yaml.safe_load((CATALOG / "taxonomy.yaml").read_text(encoding="utf-8"))
    curated = yaml.safe_load(
        (CATALOG / "domains" / "fund.indicators.yaml").read_text(encoding="utf-8"))
    return sidecar, metrics, taxonomy, curated


def test_real_sidecar_is_valid():
    sidecar, metrics, taxonomy, curated = _base()
    assert V.validate(
        CATALOG / "generated" / "metric_taxonomy.json",
        CATALOG / "generated" / "metrics.json",
        CATALOG / "taxonomy.yaml",
        CATALOG / "domains" / "fund.indicators.yaml",
    ) == []
    assert sidecar and metrics and taxonomy and curated


def test_missing_code_is_rejected(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    broken["metrics"] = broken["metrics"][1:]
    broken["stats"]["count"] = len(broken["metrics"])
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("不 1:1" in error or "stats.count" in error for error in errors)


def test_duplicate_code_is_rejected(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    broken["metrics"].append(copy.deepcopy(broken["metrics"][0]))
    broken["stats"]["count"] = len(broken["metrics"])
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("重复码" in error for error in errors)


def test_invalid_enum_is_rejected(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    broken["metrics"][0]["scope"] = "no_such_scope"
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("scope" in error and "枚举" in error for error in errors)


def test_dead_status_mismatch_is_rejected(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    dead = next(r for r in broken["metrics"] if r["status"] == "dead")
    dead["status"] = "active"
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("dead" in error for error in errors)


def test_other_ratio_threshold_is_enforced(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    for row in broken["metrics"]:
        if row["status"] == "active":
            row["topic"] = "other"
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("other" in error and "阈值" in error for error in errors)


def test_curated_mapping_mismatch_is_rejected(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    broken = copy.deepcopy(sidecar)
    row = next(r for r in broken["metrics"] if r["code"] == "$PE_TTM_LAST")
    row["scope"] = "industry"
    paths = _write(tmp_path, broken, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("curated" in error and "$PE_TTM_LAST" in error for error in errors)


def test_quality_threshold_from_taxonomy_is_used(tmp_path):
    sidecar, metrics, taxonomy, curated = _base()
    taxonomy = copy.deepcopy(taxonomy)
    taxonomy["quality"]["other_max"] = 0.0
    paths = _write(tmp_path, sidecar, metrics, taxonomy, curated)
    errors = V.validate(*paths)
    assert any("other" in error and "阈值" in error for error in errors)


def test_sidecar_check_skips_without_upstream(tmp_path, capsys):
    rc = E.main(["--check", "--upstream", str(tmp_path / "no_memo.json")])
    assert rc == 0
    assert "SKIP" in capsys.readouterr().err


def test_sidecar_generation_requires_upstream(tmp_path):
    rc = E.main(["--output", str(tmp_path / "out.json"),
                 "--upstream", str(tmp_path / "no_memo.json")])
    assert rc == 2
    assert not (tmp_path / "out.json").exists()
