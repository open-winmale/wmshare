"""validate_catalog 的 Gate 6：inventory 反向差集 allowlist 与计数自洽。"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "validate_catalog.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_catalog_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _real_curated(mod):
    from wmshare.catalog import load
    return {name for names in load().functions_by_domain().values() for name in names}


def test_real_inventory_reverse_diff_is_empty():
    mod = _load()
    assert mod.reverse_diff(mod.INVENTORY, _real_curated(mod)) == []
    # 不硬编码 275 / 6：上游新增 helper 且已登记 allowlist 是合法演进。
    # 只锁自洽关系：inventory 条目数 == 目录函数数 + 内部 helper 数。
    curated = _real_curated(mod)
    assert len(mod.INVENTORY["functions"]) == len(curated) + len(mod.INTERNAL_HELPERS)
    assert mod.INVENTORY["function_count"] == len(mod.INVENTORY["functions"])


def test_upstream_new_helper_without_allowlist_is_rejected():
    mod = _load()
    inventory = copy.deepcopy(mod.INVENTORY)
    inventory["functions"].append({"name": "segments.new_helper", "params": []})
    inventory["function_count"] += 1
    errors = mod.reverse_diff(inventory, _real_curated(mod))
    assert len(errors) == 1 and "segments.new_helper" in errors[0]


def test_stale_allowlist_entry_is_rejected():
    mod = _load()
    errors = mod.reverse_diff(mod.INVENTORY, _real_curated(mod),
                              helpers=mod.INTERNAL_HELPERS | {"segments.gone"})
    assert any("segments.gone" in e for e in errors)


def test_function_count_mismatch_is_rejected():
    mod = _load()
    inventory = dict(mod.INVENTORY)
    inventory["function_count"] = 999
    errors = mod.reverse_diff(inventory, _real_curated(mod))
    assert any("function_count=999" in e for e in errors)
