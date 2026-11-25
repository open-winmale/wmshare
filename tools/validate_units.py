#!/usr/bin/env python3
"""校验指标单位台账（units.yaml）与目录/分类的一致性。

检查:
  1. 台账里的码必须存在于 metrics.json
  2. base_unit / native_unit 必须是合法词表
  3. base_unit 必须与 sidecar 的 unit_kind 一致（台账只登记「偏离基础单位」的码）
  4. native_unit 不得与 base_unit 相同（相同就不该登记）
  5. 成交量族必须全部登记（防上游改单位后无人发现）
  6. invariants 引用的码必须存在

用法:
  python tools/validate_units.py
  python tools/validate_units.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"
UNITS = CATALOG / "units.yaml"
METRICS = CATALOG / "generated" / "metrics.json"
SIDECAR = CATALOG / "generated" / "metric_taxonomy.json"

UNIT_VOCAB = {
    "ratio", "percent", "money", "yi_yuan", "price", "shares", "lot", "zhang",
    "per_share", "multiple", "days", "percentile", "index_point", "count",
    "text", "bool",
}

# unit_kind → 可接受的 native_unit（基础单位等价类）
BASE_OF = {
    "ratio": {"ratio"},
    "money": {"money"},
    "price": {"price"},
    "shares": {"shares"},
    "per_share": {"per_share"},
    "multiple": {"multiple"},
    "days": {"days"},
    "percentile": {"percentile"},
    "index_point": {"index_point"},
    "count": {"count"},
    "text": {"text"},
    "bool": {"bool"},
}

# 必须出现在台账里的成交量族（指标层为手）
REQUIRED_LOT_CODES = {
    "$VOLUME", "$VOLUME_DAY", "$VOLUME_LAST", "$VOLUME_NR_DAY",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def validate(units_path: Path = UNITS, metrics_path: Path = METRICS,
             sidecar_path: Path = SIDECAR) -> list[str]:
    errors: list[str] = []
    ledger = _load_yaml(units_path)
    metrics_doc = json.loads(metrics_path.read_text(encoding="utf-8"))
    codes = {m["code"] for m in metrics_doc.get("metrics") or []}
    side = {r["code"]: r for r in
            json.loads(sidecar_path.read_text(encoding="utf-8")).get("metrics") or []}

    if ledger.get("schema_version") != 1:
        errors.append(f"schema_version 应为 1，实际 {ledger.get('schema_version')!r}")

    overrides = ledger.get("overrides") or {}
    if not isinstance(overrides, dict):
        return errors + ["overrides 必须是 mapping"]

    for code, spec in overrides.items():
        if code not in codes:
            errors.append(f"{code}: 不在 metrics.json")
            continue
        if not isinstance(spec, dict):
            errors.append(f"{code}: 条目必须是 mapping")
            continue
        base = spec.get("base_unit")
        native = spec.get("native_unit")
        if base not in UNIT_VOCAB:
            errors.append(f"{code}: base_unit={base!r} 不在词表内")
        if native not in UNIT_VOCAB:
            errors.append(f"{code}: native_unit={native!r} 不在词表内")
        if base == native:
            errors.append(f"{code}: base_unit == native_unit（{base}），不该登记")
        if not spec.get("note"):
            errors.append(f"{code}: 缺少 note（须写明实测依据）")
        row = side.get(code)
        if row is not None and base in UNIT_VOCAB:
            allowed = BASE_OF.get(row["unit_kind"], set())
            if base not in allowed and row["unit_kind"] != "unknown":
                errors.append(
                    f"{code}: base_unit={base} 与 sidecar unit_kind={row['unit_kind']} 不一致")

    missing_lot = REQUIRED_LOT_CODES - set(overrides)
    if missing_lot:
        errors.append(f"成交量族未登记为 lot：{sorted(missing_lot)}")

    for inv in ledger.get("invariants") or []:
        for code in inv.get("codes") or []:
            if code not in codes:
                errors.append(f"invariant {inv.get('id')}: 引用了目录外的码 {code}")

    # 门面接口：字段单位必须来自词表，且必须写明不变量或 note（防口径失传）。
    for name, spec in (ledger.get("facades") or {}).items():
        if not isinstance(spec, dict):
            errors.append(f"facades.{name}: 必须是 mapping")
            continue
        fields = spec.get("fields") or {}
        if not fields:
            errors.append(f"facades.{name}: 缺 fields")
        for field, unit in fields.items():
            if unit not in UNIT_VOCAB:
                errors.append(f"facades.{name}.{field}: {unit!r} 不在词表内")
        if not (spec.get("invariant") or spec.get("note")):
            errors.append(f"facades.{name}: 需写明 invariant 或 note")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--units", type=Path, default=UNITS)
    ap.add_argument("--metrics", type=Path, default=METRICS)
    ap.add_argument("--sidecar", type=Path, default=SIDECAR)
    args = ap.parse_args(argv)
    try:
        errors = validate(args.units, args.metrics, args.sidecar)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
    elif errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
    else:
        print(f"OK: {args.units}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
