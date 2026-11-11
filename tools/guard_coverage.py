#!/usr/bin/env python3
"""度量域目录中函数级守护声明（units / ranges / checks）的覆盖率。

只读工具：不写任何文件、不联网、不 import wmshare 运行时模块，只依赖 PyYAML，
因此可以在 CI 门禁与夜间审计里独立运行。统计口径与 validate_catalog.py 一致：
只数 functions 列表里的函数级声明，域顶层的 units 段不算。

退出码：0 达标 / 1 低于 --min / 2 输入错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DOMAINS = REPO / "src" / "wmshare" / "_catalog" / "domains"
GUARD_KEYS = ("units", "ranges", "checks")
_EMPTY = (None, [], {}, "")


def has_guard(fn: dict[str, Any]) -> bool:
    """守护声明必须以**非空内容**存在。

    只查键存在会被 ``units: null`` / ``ranges: []`` / ``checks: []`` 这类空声明
    刷高覆盖率（假绿）；空值不提供任何量级/不变量保护，不计入 guarded。
    """
    return any(fn.get(key) not in _EMPTY for key in GUARD_KEYS)


def collect(domains_dir: Path) -> dict[str, Any]:
    """逐域统计函数总数与带**有效**守护声明的函数数。"""
    if not domains_dir.is_dir():
        raise ValueError(f"域目录不存在：{domains_dir}")
    per_domain: dict[str, dict[str, int]] = {}
    for path in sorted(domains_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        functions = doc.get("functions") or []
        guarded = sum(1 for fn in functions
                      if isinstance(fn, dict) and has_guard(fn))
        per_domain[path.stem] = {
            "functions": len(functions),
            "guarded": guarded,
        }
    if not per_domain:
        raise ValueError(f"域目录下没有 YAML：{domains_dir}")
    total = sum(v["functions"] for v in per_domain.values())
    guarded = sum(v["guarded"] for v in per_domain.values())
    return {
        "domains": len(per_domain),
        "functions": total,
        "guarded": guarded,
        "ratio": round(guarded / total, 6) if total else 0.0,
        "per_domain": per_domain,
    }


def _human(result: dict[str, Any], by_domain: bool) -> str:
    head = (
        f"guard coverage: {result['domains']} domains / "
        f"{result['functions']} functions / {result['guarded']} guarded / "
        f"{result['ratio'] * 100:.2f}%"
    )
    if not by_domain:
        return head
    rows = [head]
    for name, stat in sorted(result["per_domain"].items()):
        n, g = stat["functions"], stat["guarded"]
        pct = g / n * 100 if n else 0.0
        rows.append(f"  {name:<24} {n:>4} / {g:>3} guarded  {pct:>6.2f}%")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog-dir", type=Path, default=DEFAULT_DOMAINS,
                    help="域 YAML 目录（默认随包 domains/）")
    ap.add_argument("--min", type=float, default=None,
                    help="覆盖率下限（0–1），低于则退出码 1")
    ap.add_argument("--by-domain", action="store_true", help="输出逐域明细")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    # 参数校验前置：越界时不要先打印一份看似正常的覆盖率报表。
    if args.min is not None and not 0.0 <= args.min <= 1.0:
        print("ERROR: --min 必须在 0–1 之间", file=sys.stderr)
        return 2

    try:
        result = collect(args.catalog_dir)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    passed = args.min is None or result["ratio"] >= args.min
    if args.json:
        # 机器可读输出必须自带判定结果，不能只靠退出码 / stderr 才知道红绿。
        payload = {**result, "floor": args.min, "pass": passed}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(_human(result, args.by_domain))

    if not passed:
        print(
            f"FAIL: guard coverage {result['ratio'] * 100:.2f}% "
            f"< floor {args.min * 100:.2f}% "
            f"({result['guarded']}/{result['functions']} guarded)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
