#!/usr/bin/env python3
"""生成 docs/DATA_CALENDAR.md：数据集 × 更新频率 × 过期阈值（读兄弟仓配置）。

数据源：`../airflow/data_monitor/stats_config.py` 的 `STATS_CHECKS`（AST 解析，
不 import、不依赖 airflow）。兄弟仓缺失时显式 SKIP（退出 0），与
`check-v2-mapping` 同语义——CI 在单仓环境不会假红。

注意：这里渲染的是**新鲜度看板配置**（何时算过期/预警），不是精确 cron；
精确调度在 airflow `dag_registry.yaml` / `task_catalog.yaml`。

Usage:
  python3 tools/gen_data_calendar.py          # write docs/DATA_CALENDAR.md
  python3 tools/gen_data_calendar.py --check  # exit 1 on drift（兄弟仓缺失则 SKIP）
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = REPO / "docs" / "DATA_CALENDAR.md"
SIBLING = REPO.parent / "airflow" / "data_monitor" / "stats_config.py"

try:  # 与 check_leak 同源脱敏：上游集合/标签里的数据商名不进公开文档
    from check_leak import THIRDPARTY_RE as _THIRDPARTY_RE
except Exception:  # pragma: no cover - tools 目录不在 sys.path 时降级为不脱敏
    _THIRDPARTY_RE = None


def _safe(text: object) -> str:
    s = str(text if text is not None else "")
    return _THIRDPARTY_RE.sub("第三方源", s) if _THIRDPARTY_RE else s

FREQ_CN = {
    "daily": "日",
    "monthly": "月",
    "quarterly_cn": "季（A 股）",
    "quarterly_hk": "季（港股）",
    "event_driven": "事件驱动",
    "timestamp": "时间戳",
}
PRIORITY_CN = {0: "P0", 1: "P1", 2: "P2"}
DEFAULTS = {
    "staleness_days": 0,
    "priority": 2,
    "scope": "symbol",
    "update_frequency": "daily",
    "warn_days": None,
}


def _parse_checks(path: Path) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if getattr(target, "id", "") != "STATS_CHECKS" or value is None:
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            continue
        checks: list[dict] = []
        for elt in value.elts:
            if not isinstance(elt, ast.Call):
                continue
            row = dict(DEFAULTS)
            row["_call"] = getattr(elt.func, "id", "")
            for kw in elt.keywords:
                if kw.arg is None:
                    continue
                try:
                    row[kw.arg] = ast.literal_eval(kw.value)
                except (ValueError, SyntaxError):
                    continue
            checks.append(row)
        return checks
    return []


def build() -> str:
    checks = _parse_checks(SIBLING)
    checks = [c for c in checks if c.get("_call") == "StatsCheck"]
    checks.sort(key=lambda c: (
        int(c.get("priority", 2)),
        str(c.get("group", "")),
        str(c.get("label", "")),
    ))
    n = len(checks)
    out = [
        "# 数据更新日历",
        "",
        "本页由 `tools/gen_data_calendar.py` 从兄弟仓 "
        "`../airflow/data_monitor/stats_config.py` 的 `STATS_CHECKS` 生成（禁止手改）。"
        "用途：说明每个数据集**多久没更新算过期**、提前预警阈值与优先级；"
        "精确 cron 见 airflow `dag_registry.yaml`。",
        "",
        f"共 **{n}** 个监控数据集。`过期阈值` = 最新业务期龄超过即 FAIL（红）；"
        "`预警阈值` = 提前降级 WARN（黄）。",
        "",
    ]
    groups = sorted({str(c.get("group", "")) for c in checks})
    out += [
        "## 分组概览",
        "",
        "| 分组 | 数据集数 | P0 | P1 | P2 |",
        "|---|---|---|---|---|",
    ]
    for g in groups:
        rows = [c for c in checks if str(c.get("group", "")) == g]
        p0 = sum(1 for c in rows if int(c.get("priority", 2)) == 0)
        p1 = sum(1 for c in rows if int(c.get("priority", 2)) == 1)
        p2 = sum(1 for c in rows if int(c.get("priority", 2)) == 2)
        out.append(f"| {_safe(g) or '—'} | {len(rows)} | {p0} | {p1} | {p2} |")
    out += [
        "",
        "## 数据集明细",
        "",
        "| 分组 | 数据集 | 市场 | 集合 | 更新频率 | 过期阈值 | 预警阈值 | 优先级 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in checks:
        warn = c.get("warn_days")
        out.append(
            "| {group} | {label} | {market} | `{coll}` | {freq} | {stale} 天 | "
            "{warn} | {prio} |".format(
                group=_safe(c.get("group", "")) or "—",
                label=_safe(c.get("label", "")) or "—",
                market=_safe(c.get("market", "")) or "—",
                coll=_safe(c.get("collection", "")),
                freq=FREQ_CN.get(str(c.get("update_frequency", "")), str(c.get("update_frequency", ""))),
                stale=int(c.get("staleness_days") or 0),
                warn=f"{int(warn)} 天" if warn is not None else "—",
                prio=PRIORITY_CN.get(int(c.get("priority", 2)), str(c.get("priority"))),
            ))
    out += [
        "",
        "## 口径说明",
        "",
        "1. **过期阈值**按数据类型的自然更新节奏设（日更类 3~7 天、季报类 100~120 天），"
        "不是统一 SLA；以本表为准。",
        "2. **预警阈值**用于「漏一期」在 T+1 被看见（早于过期阈值先黄），"
        "None = 未启用提前预警。",
        "3. 两融/日历等 2.0 新增面在 airflow 独立 DAG + `verify.freshness_hours` 中"
        "另有约束（48h 默认），见对应 DAG 定义。",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not SIBLING.is_file():
        print(f"gen_data_calendar skip: sibling config not found ({SIBLING})")
        return 0
    body = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != body:
            print("gen_data_calendar drift: docs/DATA_CALENDAR.md", file=sys.stderr)
            return 1
        print("gen_data_calendar ok")
        return 0
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
