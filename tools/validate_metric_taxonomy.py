#!/usr/bin/env python3
"""校验指标分类 sidecar 与 metrics.json 的 1:1 合同（阻塞 CI）。

检查:
  1. schema_version / code 集合 / 无重复
  2. 七个分类字段的枚举合法性
  3. status=dead 恰为 cn == "drop stub" 的码
  4. 74 个 curated 码的 scope/topic 与 fund.indicators.yaml 的组映射一致
  5. other / caliber_unknown 比例不超过 taxonomy.yaml 的 quality 阈值
  6. stats 与逐条统计一致

用法:
  python tools/validate_metric_taxonomy.py
  python tools/validate_metric_taxonomy.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"
SIDECAR = CATALOG / "generated" / "metric_taxonomy.json"
METRICS = CATALOG / "generated" / "metrics.json"
TAXONOMY = CATALOG / "taxonomy.yaml"
CURATED = CATALOG / "domains" / "fund.indicators.yaml"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def validate(sidecar_path: Path = SIDECAR, metrics_path: Path = METRICS,
             taxonomy_path: Path = TAXONOMY, curated_path: Path = CURATED) -> list[str]:
    errors: list[str] = []
    tax = _load_json(sidecar_path)
    metrics_doc = _load_json(metrics_path)
    cfg = _load_yaml(taxonomy_path)
    curated_doc = _load_yaml(curated_path)

    if tax.get("schema_version") != 1:
        errors.append(f"schema_version 应为 1，实际 {tax.get('schema_version')!r}")
    rows = tax.get("metrics") or []
    if not isinstance(rows, list):
        return errors + ["metrics 必须是数组"]
    codes = [r.get("code") for r in rows]
    if len(codes) != len(set(codes)):
        dup = [c for c, n in Counter(codes).items() if n > 1]
        errors.append(f"sidecar 存在重复码：{dup[:10]}")
    metric_by_code = {m["code"]: m for m in metrics_doc.get("metrics") or []}
    if set(codes) != set(metric_by_code):
        missing = sorted(set(metric_by_code) - set(codes))
        extra = sorted(set(codes) - set(metric_by_code))
        errors.append(f"sidecar 与 metrics.json 不 1:1；缺 {missing[:10]}；多 {extra[:10]}")
    if tax.get("stats", {}).get("count") != len(rows):
        errors.append("stats.count 与条目数不一致")

    enums = {
        "scope": set((cfg.get("scopes") or {}).keys()),
        "topic": set((cfg.get("topics") or {}).keys()),
        "period": set((cfg.get("periods") or {}).keys()),
        "window": set((cfg.get("windows") or {}).keys()),
        "unit_kind": set((cfg.get("unit_kinds") or {}).keys()),
        "status": {"active", "dead"},
    }
    calibers = set((cfg.get("calibers") or {}).keys())
    for row in rows:
        code = row.get("code")
        for field, allowed in enums.items():
            value = row.get(field)
            if value not in allowed:
                errors.append(f"{code}: {field}={value!r} 不在枚举内")
        cal = row.get("caliber")
        if not isinstance(cal, list):
            errors.append(f"{code}: caliber 必须是数组")
        else:
            bad = [c for c in cal if c not in calibers]
            if bad:
                errors.append(f"{code}: caliber 含未知值 {bad}")

    dead_expected = {c for c, m in metric_by_code.items() if m.get("cn") == "drop stub"}
    dead_actual = {r["code"] for r in rows if r.get("status") == "dead"}
    if dead_actual != dead_expected:
        errors.append(
            f"dead 码不一致；缺 {sorted(dead_expected - dead_actual)[:10]}；"
            f"多 {sorted(dead_actual - dead_expected)[:10]}")
    if len(dead_actual) != 20:
        errors.append(f"dead 码应为 20 个，实际 {len(dead_actual)}")

    group_topics = cfg.get("group_topics") or {}
    curated_by_code: dict[str, tuple[str, str]] = {}
    for group in curated_doc.get("metric_groups") or []:
        scope, topic = group_topics.get(group["id"], ("stock", "other"))
        for metric in group.get("metrics") or []:
            curated_by_code[metric["code"]] = (scope, topic)
    side_by_code = {r["code"]: r for r in rows}
    for code, (scope, topic) in curated_by_code.items():
        row = side_by_code.get(code)
        if row is None:
            errors.append(f"curated 码不在 sidecar：{code}")
            continue
        if (row.get("scope"), row.get("topic")) != (scope, topic):
            errors.append(
                f"curated 码 {code} 分类不一致："
                f"sidecar={row.get('scope')}/{row.get('topic')}，"
                f"group={scope}/{topic}")

    n = len(rows) or 1
    other_ratio = sum(1 for r in rows if r.get("topic") == "other") / n
    caliber_unknown_ratio = sum(
        1 for r in rows if "unknown" in (r.get("caliber") or [])) / n
    quality = cfg.get("quality") or {}
    if other_ratio > float(quality.get("other_max", 0.05)):
        errors.append(f"topic=other 占比 {other_ratio:.2%} 超过阈值")
    if caliber_unknown_ratio > float(quality.get("caliber_unknown_max", 0.30)):
        errors.append(f"caliber=unknown 占比 {caliber_unknown_ratio:.2%} 超过阈值")

    stats = tax.get("stats") or {}
    recomputed = {
        "other": round(other_ratio, 6),
        "caliber_unknown": round(caliber_unknown_ratio, 6),
        "dead": len(dead_actual),
    }
    for key, value in recomputed.items():
        if stats.get(key) != value:
            errors.append(f"stats.{key}={stats.get(key)!r} 与逐条统计 {value!r} 不一致")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sidecar", type=Path, default=SIDECAR)
    ap.add_argument("--metrics", type=Path, default=METRICS)
    ap.add_argument("--taxonomy", type=Path, default=TAXONOMY)
    ap.add_argument("--curated", type=Path, default=CURATED)
    args = ap.parse_args(argv)
    try:
        errors = validate(args.sidecar, args.metrics, args.taxonomy, args.curated)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    payload = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
    else:
        print(f"OK: {args.sidecar}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
