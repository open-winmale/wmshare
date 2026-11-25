#!/usr/bin/env python3
"""Generate the typed namespace facade (src/wmshare/api/_generated.py) from the catalog.

每个数据域命名空间一个类型化类：签名与 docstring 来自目录合同（domains/*.yaml +
generated/inventory.json），运行时统一委托 client.call()。确定性输出；
`--check` 校验磁盘文件与重新生成一致（漂移门禁，接 tests/test_drift.py）。

Usage:
  python3 tools/gen_typed_api.py          # write src/wmshare/api/_generated.py
  python3 tools/gen_typed_api.py --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wmshare.catalog import INTERNAL_CATALOG_NS, Catalog, load  # noqa: E402

OUT = REPO / "src" / "wmshare" / "api" / "_generated.py"

TYPE_MAP = {"string": "str", "int": "int", "float": "float", "bool": "bool",
            "array": "list", "object": "dict", "any": "Any"}

HEADER = '''# -*- coding: utf-8 -*-
"""自动生成：目录驱动的类型化命名空间门面 —— 勿手改。

由 tools/gen_typed_api.py 从数据目录生成；方法签名与 docstring 来自目录合同，
运行时统一委托 ``client.call()``（参数校验、max_limit 上限、normalize_with
规范化均在该层生效）。2.0 返回契约：行数组默认经 ``to_output_frame`` 转
DataFrame（``_raw=True`` 透传原始行）。重新生成：

  python3 tools/gen_typed_api.py

命名解析优先级：友好层（wmshare.api 手写类）> 本层 > 通用 _Namespace。
"""
from __future__ import annotations

from typing import Any


def _out(value: Any, raw: bool) -> Any:
    """2.0 返回收口：行数组默认转 DataFrame（与友好门面同一函数）。"""
    if raw:
        return value
    from wmshare.client import to_output_frame
    return to_output_frame(value)
'''

BASE = '''

class _Ns:
    """类型化命名空间基类。"""

    def __init__(self, client: Any) -> None:
        self._client = client

'''


def clean(text: object) -> str:
    return " ".join(str(text if text is not None else "").split())


def esc_doc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"""', r'\"""')


def ann(t: str) -> str:
    return TYPE_MAP.get(t, "Any")


def fn_params(cat: Catalog, fn: dict) -> list[dict]:
    return fn.get("params") or cat.inventory_params(fn["name"])


def render_doc(fn: dict, params: list[dict]) -> str:
    lines = [clean(fn.get("cn")) or fn["name"].split(".", 1)[1]]
    pdescs = [(p["name"], clean(p.get("desc"))) for p in params if p.get("desc")]
    if pdescs:
        lines.append("")
        lines += [f":param {n}: {esc_doc(d)}" for n, d in pdescs]
    ret = clean((fn.get("returns") or {}).get("desc"))
    if ret:
        lines.append("")
        lines.append(f":returns: {esc_doc(ret)}")
    body = esc_doc("\n".join(lines))
    return body if "\n" in body else body + ""


def render_method(cat: Catalog, fn: dict) -> list[str]:
    name = fn["name"]
    short = name.split(".", 1)[1]
    params = fn_params(cat, fn)
    sig = ["self"]
    fixed: list[dict] = []
    opt: list[dict] = []
    for p in params:
        a = ann(p.get("type") or "any")
        if p.get("required") and "default" not in p:
            sig.append(f"{p['name']}: {a}")
            fixed.append(p)
        elif "default" in p:
            sig.append(f"{p['name']}: {a} = {p['default']!r}")
            opt.append(p)
        else:
            sig.append(f"{p['name']}: {a} | None = None")
            opt.append(p)
    sig += ["_raw: bool = False"]

    lines = [f"    def {short}({', '.join(sig)}) -> Any:"]
    doc = render_doc(fn, params)
    if "\n" in doc:
        lines.append(f'        """{doc}')
        lines.append('        """')
    else:
        lines.append(f'        """{doc}"""')

    fixed_kw = ", ".join(f'"{p["name"]}": {p["name"]}' for p in fixed)
    if not opt:
        head = f'        return _out(self._client.call("{name}"'
        if fixed:
            head += ", " + ", ".join(f"{p['name']}={p['name']}" for p in fixed)
        lines.append(head + ", _raw=_raw), _raw)")
    else:
        lines.append(f"        kw: dict[str, Any] = {{{fixed_kw}}}")
        for p in opt:
            lines.append(f"        if {p['name']} is not None:")
            lines.append(f'            kw["{p["name"]}"] = {p["name"]}')
        lines.append(f'        return _out(self._client.call("{name}", **kw, _raw=_raw), _raw)')
    return lines


def generate() -> str:
    cat = load()
    per_ns: dict[str, list[dict]] = {}
    skipped_internal = 0
    for dom_id in sorted(cat.domains):
        for fn in cat.domains[dom_id].get("functions") or []:
            ns = fn["name"].split(".", 1)[0]
            # 2.0 命名空间净化：internal: true（fmt_* 规范化辅助等内部函数）
            # 不再进类型化门面——属性直达噪音下架，仍可经 ``cli.call`` 调用。
            # 内部命名空间（INTERNAL_CATALOG_NS，如 rptdom）整域同办：它们是
            # 实现细节，对外只经友好门面（cli.statements.*）暴露；留着会让
            # Agent 搜到就照着调，撞上对普通用户无意义的参数契约。
            if fn.get("internal") or ns in INTERNAL_CATALOG_NS:
                skipped_internal += 1
                continue
            per_ns.setdefault(ns, []).append(cat.function(fn["name"]))

    out = [HEADER, BASE]
    entries = []
    for ns in sorted(per_ns):
        fns = per_ns[ns]
        dom = cat.domains[fns[0]["domain"]]
        cls = ns.capitalize() + "NS"
        entries.append(f'    "{ns}": {cls},')
        out.append(f"class {cls}(_Ns):")
        out.append(f'    """{esc_doc(clean(dom["cn"]))}（{dom["id"]}）"""')
        out.append("")
        for fn in fns:
            out += render_method(cat, fn)
            out.append("")
    out.append("NAMESPACES: dict[str, type[_Ns]] = {")
    out += entries
    out.append("}")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    body = generate()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != body:
            print("gen_typed_api drift:", OUT.relative_to(REPO), file=sys.stderr)
            return 1
        print("gen_typed_api ok")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
