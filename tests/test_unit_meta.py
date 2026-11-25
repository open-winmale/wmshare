"""单位声明元规则：目录层声明本体的合法性（不联网，纯 yaml × schema 检查）。

两条规则（2026-10-27 单位审计立规）：
1. `units` 声明的字段必须存在于该函数 returns_shape（防声明指向不存在的字段）；
2. `percent` 换算声明必须配 `ranges` 量级守护，或在函数 notes 写明「量级豁免」+ 理由
   （先例：rptdom.statement_compare 的 diffp——合并值≈0 时合法地极大，范围界必然误报）。
   规则 2 在审计矩阵（.internal/UNIT_AUDIT.md，tools/audit_units.py matrix 产出）落地后
   启用——range 界须以实测分布为准，不凭空猜界。
"""
from __future__ import annotations

from pathlib import Path

from wmshare import load

EXEMPT_MARKER = "量级豁免"
AUDIT_REPORT = Path(__file__).resolve().parents[1] / ".internal" / "UNIT_AUDIT.md"


def _shape_fields(fn: dict) -> set[str]:
    shape = fn.get("returns_shape") or {}
    items = shape.get("items") if isinstance(shape, dict) else None
    fields = (items or {}).get("fields") if isinstance(items, dict) else None
    if not isinstance(fields, list):
        return set()
    return {f["name"] for f in fields if isinstance(f, dict) and f.get("name")}


def test_units_fields_exist_in_returns_shape():
    cat = load()
    bad = []
    for doc in cat.domains.values():
        for fn in doc.get("functions") or []:
            units = fn.get("units") or {}
            fields = _shape_fields(fn)
            if not units or not fields:
                continue
            for f in units:
                if f not in fields:
                    bad.append(f"{fn['name']}: units 字段 {f!r} 不在 returns_shape")
    assert not bad, "声明指向不存在的字段：\n" + "\n".join(bad)


def test_percent_declarations_have_range_or_exempt_note():
    if not AUDIT_REPORT.exists():
        import pytest
        pytest.skip("单位审计矩阵未落地（tools/audit_units.py matrix）——"
                    "range 界须以实测分布为准，启用前不凭空补界")
    cat = load()
    bad = []
    for doc in cat.domains.values():
        for fn in doc.get("functions") or []:
            units = fn.get("units") or {}
            ranges = fn.get("ranges") or {}
            notes = " ".join(fn.get("notes") or []) + " " + " ".join(doc.get("notes") or [])
            for f, tok in units.items():
                if tok == "percent" and f not in ranges and EXEMPT_MARKER not in notes:
                    bad.append(f"{fn['name']}.{f}: percent 声明缺 range 且 notes 无{EXEMPT_MARKER}标记")
    assert not bad, "percent 声明缺守护：\n" + "\n".join(bad)
