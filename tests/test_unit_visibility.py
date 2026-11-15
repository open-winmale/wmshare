"""P1 #8/#9 回归：单位与守护声明的机器可读出口 + 文档单位口径一致性。

背景：inventory.json 是上游脚本抽取的 SoT，其 functions 不带域级
``units`` / ``ranges`` / ``checks``；这些声明此前只在 ``cat.function()`` 的
合并视图里逐条可见。SDK 侧出口是 ``Catalog.guard_manifest()``，由
openapi（operation 级 ``x-wmshare-guards``）与 llms.txt / llms-full.txt
（机器可读段）对外带出；MCP 的 wmshare_contract 本就直接返回 cat.function()。

文档口径：docs/API.md 输出字段表必须按 SDK 换算后口径（量=股、市值=元），
不得与顶部基础单位表矛盾。指标码中文名属上游原生口径命名，另在文档中显式说明。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import wmshare

REPO = Path(__file__).resolve().parents[1]
GUARD_KEYS = ("units", "ranges", "checks")
# _core_paths 把底层目录函数写进 description，格式固定：底层目录函数 `ns.fn`
_UNDERLYING_RE = re.compile(r"底层目录函数 `([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`")


def test_guard_manifest_is_complete_and_json_safe():
    cat = wmshare.load()
    man = cat.guard_manifest()
    assert man == dict(sorted(man.items()))
    assert len(man) >= 50
    assert json.loads(json.dumps(man, ensure_ascii=False)) == man
    for names in cat.functions_by_domain().values():
        for name in names:
            fn = cat.function(name)
            has = any(fn.get(k) for k in GUARD_KEYS)
            assert (name in man) == has, name
            if has:
                assert man[name] == {k: fn[k] for k in GUARD_KEYS if fn.get(k)}


def test_openapi_exposes_guards_for_every_mapped_operation():
    cat = wmshare.load()
    man = cat.guard_manifest()
    spec = json.loads((REPO / "docs" / "openapi.json").read_text(encoding="utf-8"))
    mapped = declared = 0
    for path, item in spec["paths"].items():
        op = item.get("post") or {}
        m = _UNDERLYING_RE.search(op.get("description", ""))
        if not m:
            continue
        mapped += 1
        expected = man.get(m.group(1))
        assert op.get("x-wmshare-guards") == expected, (path, m.group(1))
        declared += bool(expected)
    assert mapped >= 100 and declared >= 30, (mapped, declared)


def test_llms_carry_machine_readable_guard_section():
    man = wmshare.load().guard_manifest()
    for name in ("llms.txt", "llms-full.txt"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "## 单位与守护声明（机器可读）" in text
        for fn_name in man:
            assert f"- `{fn_name}`: " in text, (name, fn_name)


def test_api_docs_field_table_uses_base_units():
    text = (REPO / "docs" / "API.md").read_text(encoding="utf-8")
    assert "volume=股" in text and "amount=元" in text
    assert "市值亿" not in text
    # 输出字段表行（| `field` | type | 说明 |）不得再写上游原生口径
    for line in text.splitlines():
        if re.match(r"^\| `[a-zA-Z_][a-zA-Z0-9_]*` \| ", line):
            assert "量(手)" not in line and "市值亿" not in line, line
    assert "指标码中文名" in text  # 上游命名与 SDK 单位的区别须显式说明


def test_openapi_schema_descriptions_use_base_units():
    text = (REPO / "docs" / "openapi.json").read_text(encoding="utf-8")
    assert '"量(手)"' not in text
    assert '"市值亿"' not in text
    assert "量(股)" in text


def test_mcp_contract_reads_catalog_function():
    """MCP 侧单位声明来自 cat.function 合并视图；server.json 只是注册清单。"""
    src = (REPO / "src" / "wmshare" / "mcp" / "tools.py").read_text(encoding="utf-8")
    assert "cat.function(str(name))" in src
    server = json.loads((REPO / "server.json").read_text(encoding="utf-8"))
    assert "tools" not in server  # 注册清单不含工具定义，声明不应写在这里
