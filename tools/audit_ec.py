#!/usr/bin/env python3
"""内部 EC 审计：固定面板实测消耗，与 estimate_cost 对账（维护者工具，不对外）。

**消耗真实 EC**——默认只打印将执行的面板，加 `--run` 才真正发请求。
结果写 `.internal/EC_AUDIT.md`（gitignore 内）+ JSON，供维护者校准成本模型、
跟踪高消耗接口的回归。**不进 CI、不进公开文档**：对外成本信息只有运行时
`cli.cost_estimate` 与 `docs/LIMITS.md` 的硬限制。

用法：
    python3 tools/audit_ec.py            # 只打印面板与预估（不联网）
    python3 tools/audit_ec.py --run      # 实测（需凭证；消耗面板标注的真实 EC）
    python3 tools/audit_ec.py --run --heavy  # 追加高成本面板（≈10 万+ EC，慎用）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wmshare.client import Client, estimate_cost  # noqa: E402

OUT_MD = REPO / ".internal" / "EC_AUDIT.md"
OUT_JSON = REPO / ".internal" / "ec_audit.json"

# (场景说明, 目录函数, kwargs)——默认面板：单次 ≤ 1 万 EC
PANEL: list[tuple[str, str, dict]] = [
    ("日 K 120 根", "kline.query_bars", {"sym": "600519", "limit": 120}),
    ("资金流 20 日", "moneyflow.query_bars", {"sym": "600519", "limit": 20}),
    ("分红列表 20 条", "bonus.query_list", {"sym": "600519", "limit": 20}),
    ("转债条款 20 条", "cbond.query", {"code": "113050", "limit": 20}),
    ("单票快照（首触/复跑）", "kline.snapshot", {"sym": "600519"}),
    ("批量原生 3 票", "kline.snapshot", {"symbol": ["600519", "000001", "510300"]}),
    ("选股轻列 50 行", "screener.query",
     {"limit": 50, "where": "$ROE_TTM_LAST > 0.15"}),
    ("选股 count-only", "screener.query", {"limit": 0, "where": "$ROE_TTM_LAST > 0.15"}),
    ("交易日历一年", "calendar.days", {"begin": "2026-01-01", "end": "2026-12-31"}),
    ("两融汇总默认 60 行", "margin.market_summary", {"limit": 60}),
    ("估值统计（缓存）", "valuation.hist_stats",
     {"sym": "600519", "metric": "pe", "window": "3y"}),
    ("每日估值（物化表）", "valuation.daily_basic",
     {"sym": "600519", "begin": "2026-11-01", "end": "2026-11-17"}),
    ("概念目录（物化档点查）", "board.concept_list", {"limit": 20}),
    ("股东增减持 单日档", "holdertrade.by_date",
     {"date": "2026-11-27", "limit": 10}),
    ("股东增减持 单票 5 条", "holdertrade.by_symbol",
     {"symbol": "600519", "limit": 5}),
]

# 高成本面板（--heavy）：单次 ≥ 5 万 EC，合计可能 ≥ 30 万 EC
HEAVY_PANEL: list[tuple[str, str, dict]] = [
    ("两融名单 500 行", "margin.universe", {"limit": 500}),
    ("批量原生 500 票", "kline.snapshot",
     {"symbol": [f"{i:06d}" for i in range(500)]}),
    ("回测 1 年区间", "backtest.run",
     {"symbol": "600519", "begin": "2025-01-01", "end": "2025-12-31"}),
    ("全市场快照捷径", "kline.snapshot",
     {"symbol": [f"{i:06d}" for i in range(4000)]}),
]


def _panel_cost(panel: list[tuple[str, str, dict]]) -> list[dict]:
    rows = []
    for scene, name, kw in panel:
        est = estimate_cost(name, kw)
        rows.append({"scene": scene, "name": name, "params": kw,
                     "est_lo": est.get("ec_lo"), "est_hi": est.get("ec_hi"),
                     "model": est.get("model") or "", "note": est.get("note") or ""})
    return rows


def _run_panel(client: Client, panel: list[tuple[str, str, dict]]) -> list[dict]:
    rows = []
    for scene, name, kw in panel:
        est = estimate_cost(name, kw)
        row: dict = {"scene": scene, "name": name, "params": kw,
                     "est_lo": est.get("ec_lo"), "est_hi": est.get("ec_hi"),
                     "measured": None, "error": ""}
        try:
            client.call(name, **kw)
            row["measured"] = client.last_ec_cost or 0
        except Exception as exc:  # noqa: BLE001 —— 单项失败不拖垮整个面板
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
        rows.append(row)
    return rows


def _render(rows: list[dict], *, measured: bool, generated_at: str) -> str:
    out = [
        "# EC 审计（内部）",
        "",
        f"- 生成时间：{generated_at}",
        "- 实测方式：`tools/audit_ec.py --run`（消耗真实 EC；维护者工具，不进 CI/文档）",
        "- 用途：校准 `estimate_cost` 模型、跟踪高消耗接口回归。**不要把本页数字同步进"
        "公开文档**——对外口径只有运行时预估与硬限制。",
        "",
        "| 场景 | 接口 | 预估 lo~hi | 实测 | 偏差 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lo, hi = r.get("est_lo"), r.get("est_hi")
        est = "—" if lo is None else f"{lo:,}~{hi:,}"
        measured = "—" if r.get("measured") is None else f"{r['measured']:,}"
        if r.get("measured") is not None and lo:
            mid = (lo + hi) / 2
            dev = f"{(r['measured'] - mid) / mid:+.0%}" if mid else "—"
        else:
            dev = "—"
        note = (r.get("note") or r.get("error") or "").replace("|", "\\|")
        out.append(f"| {r['scene']} | `{r['name']}` | {est} | {measured} | {dev} | {note} |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="store_true", help="实测（消耗真实 EC，需凭证）")
    ap.add_argument("--heavy", action="store_true", help="追加高成本面板（≈30 万+ EC）")
    args = ap.parse_args()
    panel = PANEL + (HEAVY_PANEL if args.heavy else [])
    if not args.run:
        print("== 面板预估（未联网；加 --run 实测，消耗真实 EC）==")
        for r in _panel_cost(panel):
            lo, hi = r["est_lo"], r["est_hi"]
            est = "无模型" if lo is None else f"{lo:,}~{hi:,} EC"
            print(f"  {r['scene']:<18} {r['name']:<26} {est}")
        return 0

    client = Client.from_env()
    generated_at = datetime.now().replace(microsecond=0).isoformat()
    rows = _run_panel(client, panel)
    (REPO / ".internal").mkdir(exist_ok=True)
    OUT_MD.write_text(_render(rows, measured=True, generated_at=generated_at),
                      encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"generated_at": generated_at, "rows": rows},
                                   ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    total = sum(r.get("measured") or 0 for r in rows)
    print(f"wrote {OUT_MD.relative_to(REPO)} / {OUT_JSON.relative_to(REPO)}"
          f"（{len(rows)} 项，实测合计 {total:,} EC）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
