#!/usr/bin/env python3
"""输出指标分类 sidecar 的分布与低置信清单（只读）。

用法:
  python tools/report_metric_taxonomy.py
  python tools/report_metric_taxonomy.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "src" / "wmshare" / "_catalog" / "generated" / "metric_taxonomy.json"
METRICS = REPO / "src" / "wmshare" / "_catalog" / "generated" / "metrics.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(sidecar: Path = SIDECAR, metrics: Path = METRICS) -> dict:
    tax = _load(sidecar)
    cn = {m["code"]: m.get("cn", "") for m in _load(metrics)["metrics"]}
    rows = tax["metrics"]
    n = len(rows)
    other = [{"code": r["code"], "cn": cn.get(r["code"], ""), "scope": r["scope"]}
             for r in rows if r["topic"] == "other"]
    unit_unknown = [{"code": r["code"], "cn": cn.get(r["code"], ""), "topic": r["topic"]}
                    for r in rows if r["unit_kind"] == "unknown"]
    return {
        "count": n,
        "stats": tax.get("stats") or {},
        "topics": dict(sorted(Counter(r["topic"] for r in rows).items())),
        "periods": dict(sorted(Counter(r["period"] for r in rows).items())),
        "windows": dict(sorted(Counter(r["window"] for r in rows).items())),
        "unit_kinds": dict(sorted(Counter(r["unit_kind"] for r in rows).items())),
        "other": other,
        "unit_unknown": unit_unknown,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sidecar", type=Path, default=SIDECAR)
    ap.add_argument("--metrics", type=Path, default=METRICS)
    args = ap.parse_args(argv)
    try:
        report = build_report(args.sidecar, args.metrics)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    s = report["stats"]
    print(f"metric taxonomy: {report['count']} codes")
    print(f"  other={s.get('other', 0):.2%}  "
          f"caliber_unknown={s.get('caliber_unknown', 0):.2%}  "
          f"unit_unknown={s.get('unit_unknown', 0):.2%}  dead={s.get('dead', 0)}")
    for key in ("topics", "periods", "windows", "unit_kinds"):
        print(f"  {key}: {report[key]}")
    if report["other"]:
        print("  other codes:")
        for row in report["other"]:
            print(f"    {row['code']} | {row['cn']} | {row['scope']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
