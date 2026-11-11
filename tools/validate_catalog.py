#!/usr/bin/env python3
"""Validate domain catalog (src/wmshare/_catalog/domains/*.yaml) against schema + generated inventory.

Gates:
  1. domain YAML is valid against _catalog/schema/domain.schema.json
  2. every functions[].name exists in generated/inventory.json (anti-fabrication)
  3. returns.shape_ref=inventory requires the inventory entry to carry returns_shape
  4. metric_groups[].metrics[].code exists in metrics.json
  5. domain id matches filename stem
  6. inventory 反向差集：inventory 里多出来的函数必须在 INTERNAL_HELPERS 显式登记，
     且 function_count 与 functions 列表长度一致（上游新增 helper 不能静默漏检）

Usage: python3 tools/validate_catalog.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wmshare.catalog import catalog_dir  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOMAINS = catalog_dir() / "domains"
SCHEMA = json.loads((catalog_dir() / "schema" / "domain.schema.json").read_text(encoding="utf-8"))
INVENTORY = json.loads((catalog_dir() / "generated" / "inventory.json").read_text(encoding="utf-8"))
METRICS = json.loads((catalog_dir() / "generated" / "metrics.json").read_text(encoding="utf-8"))

INV_FUNCS = {f["name"]: f for f in INVENTORY["functions"]}
METRIC_CODES = {m["code"] for m in METRICS["metrics"]}

# 上游 inventory 里的内部 helper 不是可调用目录函数，域 YAML 不收录。
# 显式列出而非「忽略所有差集」：上游新增 helper 必须先在此登记（或补域声明），
# 否则 validate_catalog 报错，避免真实可调用函数被静默漏掉。
INTERNAL_HELPERS = {
    "segments.clamp_limit",
    "segments.dim_to_ui_tab",
    "segments.normalize_dim",
    "segments.normalize_source",
    "segments.take_limit",
    "segments.ui_tab_to_dim",
}


def reverse_diff(inventory: dict, curated: set[str],
                 helpers: set[str] = INTERNAL_HELPERS) -> list[str]:
    """Gate 6：inventory 反向差集 + function_count 自洽。纯函数，便于单测。"""
    errors: list[str] = []
    funcs = inventory["functions"]
    if inventory.get("function_count") != len(funcs):
        errors.append(
            f"inventory.function_count={inventory.get('function_count')} "
            f"!= len(functions)={len(funcs)}（生成物不自洽）")
    extra = {f["name"] for f in funcs} - curated
    unexpected = sorted(extra - helpers)
    stale = sorted(helpers - extra)
    if unexpected:
        errors.append(
            f"inventory 有 {len(unexpected)} 个未登记的内部函数（上游新增？）："
            f"{unexpected}；请在 INTERNAL_HELPERS 登记或补域 YAML 声明")
    if stale:
        errors.append(
            f"INTERNAL_HELPERS 有 {len(stale)} 个名字已不在反向差集（已被收录或上游删除）："
            f"{stale}；请同步更新白名单")
    return errors


def main() -> int:
    errors: list[str] = []
    curated: set[str] = set()
    files = sorted(DOMAINS.glob("*.yaml"))
    if not files:
        print("no domain files found", file=sys.stderr)
        return 1

    total_fns = raw_fns = computed_fns = 0
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        where = str(path.relative_to(REPO))
        try:
            jsonschema.validate(doc, SCHEMA)
        except jsonschema.ValidationError as e:
            errors.append(f"{where}: schema: {'/'.join(str(p) for p in e.absolute_path)}: {e.message}")
            continue
        if doc["id"] != path.stem:
            errors.append(f"{where}: id {doc['id']!r} != filename stem {path.stem!r}")
        for fn in doc.get("functions") or []:
            total_fns += 1
            kind = fn.get("kind") or doc["kind"]
            if kind == "raw":
                raw_fns += 1
            elif kind == "computed":
                computed_fns += 1
            name = fn["name"]
            curated.add(name)
            inv = INV_FUNCS.get(name)
            if inv is None:
                errors.append(f"{where}: function {name} not in inventory (fabricated or upstream-removed)")
                continue
            ret = fn.get("returns") or {}
            if ret.get("shape_ref") == "inventory" and not inv.get("returns_shape"):
                errors.append(f"{where}: {name} uses shape_ref=inventory but inventory has no returns_shape")
            # curated params must agree with inventory param names (order-insensitive)
            cur = [p["name"] for p in fn.get("params") or []]
            invp = [p["name"] for p in inv.get("params") or []]
            if cur and sorted(cur) != sorted(invp):
                errors.append(f"{where}: {name} params {cur} != inventory {invp}")
        for grp in doc.get("metric_groups") or []:
            for m in grp.get("metrics") or []:
                if m["code"] not in METRIC_CODES:
                    errors.append(f"{where}: metric {m['code']} not in metrics.json")
        print(f"ok   {where}: id={doc['id']} kind={doc['kind']} "
              f"functions={len(doc.get('functions') or [])} "
              f"metric_groups={len(doc.get('metric_groups') or [])}")

    errors.extend(reverse_diff(INVENTORY, curated))
    print(f"\ninventory 反向差集：{len(INV_FUNCS) - len(curated)} 个内部 helper"
          f"（allowlist {len(INTERNAL_HELPERS)} 个），function_count={INVENTORY.get('function_count')}")

    if errors:
        print("\nFAIL:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"\ncatalog valid: {len(files)} domains, {total_fns} functions "
          f"(raw={raw_fns}, computed={computed_fns})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
