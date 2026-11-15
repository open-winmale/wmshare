"""单位口径审计：跨接口一致性核验（cross）+ 全量接口逐字段单位矩阵（matrix）。

维护者命令（联网）：
    python tools/audit_units.py                       # cross：样本宇宙 + 跨接口一致性（默认）
    python tools/audit_units.py matrix                # matrix：113 核心接口逐字段单位审计
    python tools/audit_units.py matrix --only equity  # 只跑某域
    python tools/audit_units.py matrix --refresh      # 忽略缓存重取

离线（不联网、不需要凭证，可在 CI 里跑）：
    python tools/audit_units.py drift                 # 目录声明 vs 上游的静态漂移
    python tools/audit_units.py drift --json         # 机器可读报告

drift 比对三类：returns_shape 字段集（悬空声明）、markets 可用性（指标码市场声明
覆盖率）、checks 适用性（不变量是否注册 / percent 是否配量级守护）。
ERROR 影响退出码；markets 覆盖率与 shape 覆盖上游属 INFO（P2 跨仓待办），不拦门禁。

SDK 默认调用路径（call() / indicator.get）已内置换算 + 量级守护 + 行内不变量。
cross 在其之上补**跨接口**一致性核验（数据是否对所有公司同口径，而非单一样本）。
matrix 以 `_units="native"` 逐接口取脚本原值，对每个数值字段给出判定：
  DECLARED-OK   已声明换算且原值口径与声明一致（native ≈ 基础单位 × 因子）
  WRONG-DECL    已声明但原值已是基础单位（换算会把值弄错）→ 修声明
  FIX-PERCENT   未声明但证据指向百分数 → 补 units: percent
  DECIMAL-RAW   未声明、实测已是小数/元等基础单位 → 建议补 ranges 固化
  RAW-NOTED     披露原文口径存疑（万/元两说等）→ 保持原值 + notes 说明
  NO-DATA       样本标的下无数据（不代表能力缺失）
报告写 .internal/UNIT_AUDIT.md；原始响应缓存 .internal/audit-cache/（断点续跑省额度）。
存在 WRONG-DECL 时退出码 1；FIX-PERCENT/RAW-NOTED 属发现项，不影响退出码。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import wmshare
from wmshare import DataError

DEFAULT_UNIVERSE = ["600519", "601318", "300750", "688981", "601857"]
DEFAULT_ETF = "510300"
METRIC_CODES = [
    "$CLOSE_LAST", "$MV_LAST", "$MV_FREE_LAST", "$AMOUNT_LAST",
    "$BONUS_TTM", "$BONUS_RATE_TTM_LAST", "$ROE_TTM_LAST", "$TL_RATE_LAST",
    "$TR_TTM_LAST", "$NP_TTM_LAST",
]

# AMOUNT_LAST（live 截面）与 EOD bars amount 的时间戳不同，只校验同量级（同为中心元）
AMOUNT_SCALE_RATIO = (0.02, 50.0)

REPO = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO / ".internal" / "audit-cache"
REPORT_PATH = REPO / ".internal" / "UNIT_AUDIT.md"
THROTTLE_SEC = 0.4

# ---- matrix：live 合法样例参数（对齐 tests/test_contract.py SAMPLES，但值必须真实可取） ----
SAMPLE_PARAMS: dict[str, object] = {
    "sym": "600519",
    "syms": ["600519"],
    "stock_code": "600519",
    "category": "回购",
    "date": "2026-06-30",
    "domain": "fin.income_statement",
    "type_key": "annual",
    "type_regex": "年报",
    "window": "3y",
    "from_date": "2026-01-01",
    "to_date": "2026-03-31",
    "limit": 5,
    "market": "cn",
    "min_chg": 0.01,
    "idx": None,
    "key": "index.hs300",
    "kind": "annual",
}
# 域级客户端与标的覆盖（intl 按市场路由；indices 用 cn 客户端 + 指数键）
MATRIX_OVERRIDES: dict[str, dict] = {
    # catalog_name 前缀 → {"market": ..., "sym": ...}
    "intl.query_ccass": {"market": "hk", "sym": "00700"},
    "intl.query_shareholders": {"market": "hk", "sym": "00700"},
    "intl.query_org_rating": {"market": "hk", "sym": "00700"},
    "intl.query_profit_forecast": {"market": "hk", "sym": "00700"},
    "intl.query_sellshort": {"market": "hk", "sym": "00700"},
    "intl.issue_info": {"market": "us", "sym": "BRK_B"},
}
SPECIAL_PROBES = ("指标代码直查", "指标代码批量直查", "组合接口（宿主 HIST_STATS）",
                  "bonus.query_*_window", "kline.query_bars[_adj]")

# 字段名 → 比例语义提示（判定用；大小写不敏感子串）
RATIO_NAME_HINTS = ("ratio", "pct", "tsr", "percent", "rate", "ratio_")
MONEY_NAME_HINTS = ("amt", "amount", "balance", "total", "salary", "deal", "profit",
                    "revenue", "cost", "tr", "buy", "sell", "net", "mv", "cap")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, check: str, detail: str) -> None:
        self.rows.append((ok, check, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {check:<28} {detail}")

    def ok(self) -> bool:
        return all(r[0] for r in self.rows)


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def audit_symbol(rep: Report, cli: wmshare.Client, sym: str, with_fundamentals: bool = True) -> None:
    # 1) K 线：volume(股)×close≈amount(元)——SDK 运行时已守护，这里复核并记录
    bars = cli.call("kline.query_bars", sym=sym, limit=3)
    bar = bars[-1] if bars else {}
    v, c, a = bar.get("volume"), bar.get("close"), bar.get("amount")
    if v and c and a:
        ratio = v * c / a
        rep.add(0.4 <= ratio <= 2.5, "kline.volume_amount",
                f"{sym}: volume={v:.0f}股 ratio={ratio:.3f}")
    else:
        rep.add(False, "kline.volume_amount", f"{sym}: bars 缺 volume/close/amount")

    if not with_fundamentals:
        return

    # 2) 指标层：runtime 已做 range 守护（违例抛 DataError）；补跨接口一致性
    try:
        m = cli.indicator.metrics(sym, METRIC_CODES)
    except DataError as e:
        rep.add(False, "indicator.range", f"{sym}: {e}")
        return
    mv, mv_free = m.get("$MV_LAST"), m.get("$MV_FREE_LAST")
    if mv and mv_free:
        rep.add(mv_free <= mv * 1.01, "indicator.mv_free_le_mv",
                f"{sym}: MV_FREE/MV={mv_free / mv:.3f}")
    amount_last = m.get("$AMOUNT_LAST")
    if amount_last and v and a:
        scale = amount_last / a
        lo, hi = AMOUNT_SCALE_RATIO
        rep.add(lo <= scale <= hi, "indicator.amount_scale_yuan",
                f"{sym}: $AMOUNT_LAST/bars.amount={scale:.3g}（同为中心元则接近 1）")
    # 3) 跨接口恒等：yield_ttm == $BONUS_RATE_TTM_LAST
    rate = m.get("$BONUS_RATE_TTM_LAST")
    if rate:
        y = cli.dividend.yield_ttm(sym)
        rep.add(y is not None and abs(y - rate) <= 1e-9, "cross.yield_identity",
                f"{sym}: yield_ttm={y} vs $BONUS_RATE_TTM_LAST={rate}")


# ---------------------------------------------------------------------------
# matrix：全量接口逐字段单位审计
# ---------------------------------------------------------------------------

def _flatten_rows(result: object) -> tuple[str, list[dict]]:
    """把接口返回规整成 (形态, 行列表)，覆盖 行数组/单行 MAP/容器 MAP。"""
    if isinstance(result, list):
        return "array", [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        if not result:
            return "empty", []
        dict_vals = [v for v in result.values() if isinstance(v, list)
                     and v and all(isinstance(x, dict) for x in v)]
        if dict_vals:  # 容器 MAP（如 forecast.snapshot / workout.board.deals）
            rows: list[dict] = []
            for v in dict_vals:
                rows.extend(v)
            return "container", rows
        return "object", [result]
    return "empty", []


def _field_cn_hints(fn: dict) -> dict[str, str]:
    """从 returns_shape 抽 字段→中文描述（inventory cn 常带“百分数/万/亿”线索）。"""
    hints: dict[str, str] = {}
    shape = (fn.get("returns_shape") or {})
    items = shape.get("items") if isinstance(shape, dict) else None
    fields = (items or {}).get("fields") if isinstance(items, dict) else None
    for f in fields or []:
        if isinstance(f, dict) and f.get("name"):
            hints[str(f["name"])] = str(f.get("cn") or "")
    return hints


def _stats(nums: list[float]) -> str:
    if not nums:
        return "n=0"
    if len(nums) == 1:
        return f"n=1 v={nums[0]:.6g}"
    return (f"n={len(nums)} min={min(nums):.4g} med={statistics.median(nums):.4g} "
            f"max={max(nums):.4g}")


def _classify_field(field: str, nums: list[float], token: str | None,
                    cn_hint: str, range_hi: float | None = None) -> tuple[str, str]:
    """返回 (verdict, 说明)。nums 为 native 口径实测值。"""
    med = statistics.median(nums) if nums else 0.0
    hint = cn_hint.lower()
    name_l = field.lower()
    ratio_named = any(h in name_l for h in RATIO_NAME_HINTS)

    if max(nums) == 0 and min(nums) == 0:
        return "SAMPLE-NULL", "样本全 0（缺数占位），无法判定口径——换 symbol 复核"

    if token == "percent":
        # 声明过 range 的小口径字段（票面利率 0.2% 等）以因子一致性为准：
        # native×0.01 落在声明 range 内即自洽（纯量级启发式对 <1.5% 的利率会误判）
        if range_hi is not None and max(nums) * 0.01 <= range_hi:
            return "DECLARED-OK", (f"换算后落在声明 range（≤{range_hi:g}），小口径字段自洽"
                                   f"（{_stats(nums)}）")
        # 原值应为百分数：典型 >1.5；若中位数 ≤1.5 且 max≤2 说明已是小数 → 声明错
        if med <= 1.5 and max(nums) <= 2.0:
            return "WRONG-DECL", f"原值已是小数（{_stats(nums)}），percent 换算会再除 100"
        return "DECLARED-OK", f"原值百分数口径（{_stats(nums)}）→ 换算后小数"
    if token == "lot":
        return "DECLARED-OK", "lot 换算由 volume_amount 不变量另行守护（cross 模式）"

    # 未声明字段
    if "百分数" in cn_hint or "%" in cn_hint:
        if med <= 1.5 and max(nums) <= 2.0:
            return "CONFLICT", f"inventory cn 称百分数但实测小数（{_stats(nums)}）"
        return "FIX-PERCENT", f"inventory cn 称百分数且实测百分数（{_stats(nums)}）→ 补 units: percent"
    if ratio_named or "占比" in cn_hint or "比例" in cn_hint:
        if 0 < med <= 1.5 and max(nums) <= 2.0:
            return "DECIMAL-RAW", f"比例语义、实测小数（{_stats(nums)}）→ 建议补 range 固化"
        if med > 1.5:
            return "FIX-PERCENT", f"比例语义、实测百分数形态（{_stats(nums)}）→ 补 units: percent"
    if any(h in name_l for h in MONEY_NAME_HINTS) or "元" in cn_hint:
        if abs(med) >= 1e6:
            return "DECIMAL-RAW", f"金额量级 ≈ 元（{_stats(nums)}）"
        if 1e2 <= abs(med) < 1e6:
            return "RAW-NOTED", f"金额量级可疑（{_stats(nums)}）——万/元两说，需人工判定"
    return "RAW-NOTED", f"未声明（{_stats(nums)}）"


def _ratio_sum_anchor(rows: list[dict]) -> list[str]:
    """行内比例求和锚：同名字段跨行求和 ≈1 → 小数，≈100 → 百分数。"""
    out: list[str] = []
    ratio_fields: set[str] = set()
    for r in rows[:50]:
        for k, v in r.items():
            if _is_num(v) and any(h in k.lower() for h in RATIO_NAME_HINTS):
                ratio_fields.add(k)
    for k in sorted(ratio_fields):
        s = sum(v for r in rows[:50] if _is_num(r.get(k)) for v in [r[k]])
        if 0.95 <= s <= 1.05:
            out.append(f"{k}: 列和≈1 → 小数")
        elif 95 <= s <= 105:
            out.append(f"{k}: 列和≈100 → 百分数")
    return out


def run_matrix(cli: wmshare.Client, rep: Report, only: str | None, refresh: bool,
               limit_domains: int = 0) -> int:
    from wmshare.api import FRIENDLY_INDEX

    # 合并目录视图不含 params（合同在 inventory.json，与 tests/test_contract.py 同源）
    inv_raw = json.loads((Path(wmshare.__file__).parent / "_catalog" / "generated"
                          / "inventory.json").read_text(encoding="utf-8"))
    inv = {f["name"]: f for f in inv_raw["functions"]}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cat = cli.catalog
    clients: dict[str, wmshare.Client] = {"cn": cli}

    def client_for(market: str) -> wmshare.Client:
        if market not in clients:
            clients[market] = wmshare.Client.from_env(market=market)
        return clients[market]

    lines: list[str] = ["# 单位口径审计矩阵（native 实测）", "",
                        f"- wmshare {wmshare.__version__} | upstream_rev "
                        f"{cat.stats().get('upstream_rev')}", ""]
    verdict_count: dict[str, int] = {}
    wrong = 0

    for entry in FRIENDLY_INDEX:
        category, ns, method, cn_title, cat_name = entry
        if only and only not in ns and only not in cat_name:
            continue
        if cat_name in SPECIAL_PROBES or "." not in cat_name:
            lines += [f"## {ns}.{method}（{cn_title}）", "",
                      f"- 特殊接口（{cat_name}）：单位由指标精选 range/既有 cross 恒等式守护，矩阵略。", ""]
            continue
        try:
            fn = cat.function(cat_name)
        except Exception as e:
            rep.add(False, "matrix.catalog", f"{cat_name}: {e}")
            continue

        ov = next((v for pre, v in MATRIX_OVERRIDES.items() if cat_name.startswith(pre)), None)
        market = (ov or {}).get("market", "cn")
        # 填参规则：名字在 SAMPLE_PARAMS 里的标量参数一律填（idx=None → 服务端
        # LatestIndexKey 解析；limit 压到 5 省额度），再加 min_args 覆盖的必填项兜底；
        # MATRIX_OVERRIDES 的 sym/syms/stock_code 覆盖一切默认
        inv_fn = inv.get(cat_name, {})
        required_n = int(inv_fn.get("min_args") or 0)
        kwargs: dict[str, object] = {}
        for i, p in enumerate(inv_fn.get("params") or []):
            name = p["name"]
            if name in ("sym", "syms", "stock_code") and ov and name in ov:
                kwargs[name] = ov[name]
            elif name in SAMPLE_PARAMS:
                kwargs[name] = SAMPLE_PARAMS[name]
            elif i < required_n:
                kwargs[name] = "x"

        cache_key = cat_name.replace("/", "_")
        cache_file = CACHE_DIR / f"{cache_key}.json"
        status, rows, err = "OK", [], ""
        if cache_file.exists() and not refresh:
            blob = json.loads(cache_file.read_text(encoding="utf-8"))
            status, rows, err = blob["status"], blob["rows"], blob.get("err", "")
        else:
            try:
                res = client_for(market).call(cat_name, **dict(kwargs), _units="native")
                time.sleep(THROTTLE_SEC)
                _, rows = _flatten_rows(res)
            except wmshare.WmshareError as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
                status = "ERR"
            if status == "OK":  # 失败结果不落缓存，下次自动重试
                cache_file.write_text(json.dumps({"args": kwargs, "status": status,
                                                  "rows": rows, "err": err},
                                                 ensure_ascii=False), encoding="utf-8")

        lines += [f"## {ns}.{method}（{cn_title} · `{cat_name}`）", "",
                  f"- market={market} args={json.dumps(kwargs, ensure_ascii=False)} → {status}"
                  + (f"（{err}）" if err else ""), ""]
        if status != "OK":
            rep.add(False, f"matrix.{cat_name}", f"{market} 取数失败：{err}")
            continue
        if not rows:
            lines += ["- NO-DATA（样本标的下无数据）", ""]
            verdict_count["NO-DATA"] = verdict_count.get("NO-DATA", 0) + 1
            continue

        units_decl = fn.get("units") or {}
        hints = _field_cn_hints(fn)
        cols = sorted({k for r in rows[:50] for k in r})
        anchors = _ratio_sum_anchor(rows)
        lines += ["| 字段 | 声明 | native 实测 | inventory cn | 判定 |", "|---|---|---|---|---|"]
        for col in cols:
            nums = [v for r in rows[:50] if _is_num(v := r.get(col))]
            cn_hint = hints.get(col, "")
            if not nums:
                sample = next((r.get(col) for r in rows if r.get(col) is not None), None)
                lines.append(f"| {col} | {units_decl.get(col, '—')} | 非数值 {type(sample).__name__} "
                             f"| {cn_hint} | SKIP |")
                continue
            rng = (fn.get("ranges") or {}).get(col)
            range_hi = float(rng[1]) if isinstance(rng, list) and len(rng) == 2 else None
            verdict, why = _classify_field(col, nums, units_decl.get(col), cn_hint, range_hi)
            verdict_count[verdict] = verdict_count.get(verdict, 0) + 1
            if verdict == "WRONG-DECL":
                wrong += 1
                rep.add(False, f"matrix.{cat_name}.{col}", why)
            lines.append(f"| {col} | {units_decl.get(col, '—')} | {_stats(nums)} | {cn_hint} "
                         f"| {verdict}：{why} |")
        if anchors:
            lines += ["", "求和锚：" + "；".join(anchors)]
        lines.append("")

    lines += ["## 汇总", ""] + [f"- {k}: {v}" for k, v in sorted(verdict_count.items())]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep.add(True, "matrix.report", f"{REPORT_PATH}（WRONG-DECL={wrong}）")
    print(f"\n# 矩阵报告 → {REPORT_PATH}")
    print("# 判定汇总:", json.dumps(verdict_count, ensure_ascii=False))
    return 1 if wrong else 0


# ---- drift：离线静态漂移（目录声明 vs 上游 inventory / 指标 markets / checks 注册） ----

def _shape_fields(shape: dict | None) -> set[str]:
    """returns_shape 的字段名集合（兼容 array.items.fields / object.fields）。"""
    if not isinstance(shape, dict):
        return set()
    items = shape.get("items") if isinstance(shape.get("items"), dict) else shape
    fields = (items or {}).get("fields") or []
    return {f["name"] for f in fields if isinstance(f, dict) and f.get("name")}


def collect_drift(cat, inventory_doc: dict, metrics_doc: dict,
                  strict: bool = False) -> dict[str, Any]:
    """纯函数：只读目录与生成器产物，产出 drift 报告（便于正负例单测）。

    ERROR（默认拦）：未注册的 checks、percent 缺 ranges（尊重 notes「量级豁免」
    先例）——两者都是声明内部的自洽性，与上游 shape 无关。
    WARN（默认只报告）：units / ranges 字段不在 returns_shape。带 normalize_with
    的函数，catalog 取的是 fmt 函数的 shape（字段滞后），而守护声明按 normalize
    后实测字段书写；守护按运行时字段名匹配仍生效，属上游 shape 声明滞后。
    既存 test_unit_meta 规则 1 在 fields 为空时会跳过，本工具把这些滞后项显式化，
    需逐函数用域 YAML ``returns.shape`` 覆盖核实。``strict=True`` 可升级为失败。
    INFO：SDK 侧 shape 覆盖上游清单、指标码 markets 覆盖率、matrix 已覆盖节数。
    """
    from wmshare.units import CHECKS

    errors: list[str] = []
    warnings: list[str] = []
    manifest = cat.guard_manifest()
    inv_by_name = {f["name"]: f for f in inventory_doc.get("functions", [])}
    shape_overrides: list[str] = []

    for name, guards in manifest.items():
        fn = cat.function(name)
        fields = _shape_fields(fn.get("returns_shape"))
        unit_fields = set(guards.get("units") or {})
        range_fields = set(guards.get("ranges") or {})
        for kind, declared in (("units", unit_fields), ("ranges", range_fields)):
            if declared and fields:
                dangling = sorted(declared - fields)
                if dangling:
                    warnings.append(
                        f"shape: {name} {kind} 字段 {dangling} 不在 returns_shape"
                        "（疑似上游 shape 声明滞后，需逐函数核实 returns.shape 覆盖）")
        for cid in guards.get("checks") or []:
            if cid not in CHECKS:
                errors.append(
                    f"checks: {name} 不变量 {cid!r} 未注册（可用 {sorted(CHECKS)}）")
        notes = " ".join(fn.get("notes") or []) + " " + " ".join(
            (cat.domains.get(fn.get("domain"), {}) or {}).get("notes") or [])
        for f, tok in (guards.get("units") or {}).items():
            if tok == "percent" and f not in (guards.get("ranges") or {}) \
                    and "量级豁免" not in notes:
                errors.append(f"checks: {name}.{f} percent 声明缺 ranges 量级守护")

        inv_fields = _shape_fields(inv_by_name.get(name, {}).get("returns_shape"))
        if fields and inv_fields and fields != inv_fields:
            shape_overrides.append(name)

    metrics = metrics_doc.get("metrics") or []
    by_market: dict[str, int] = {}
    declared_markets = 0
    for m in metrics:
        ms = m.get("markets") or []
        if ms:
            declared_markets += 1
            for mk in ms:
                by_market[mk] = by_market.get(mk, 0) + 1

    audit_sections = 0
    if REPORT_PATH.is_file():
        audit_sections = sum(
            1 for line in REPORT_PATH.read_text(encoding="utf-8").splitlines()
            if line.startswith("## "))

    total_functions = cat.stats()["functions"]
    return {
        "errors": errors,
        "warnings": warnings,
        "strict": strict,
        "info": {
            "guard_declared": len(manifest),
            "functions": total_functions,
            "guard_ratio": round(len(manifest) / total_functions, 6)
            if total_functions else 0.0,
            "shape_overrides": sorted(shape_overrides),
            "markets": {
                "total": len(metrics),
                "declared": declared_markets,
                "undeclared": len(metrics) - declared_markets,
                "ratio": round(declared_markets / len(metrics), 6) if metrics else 0.0,
                "by_market": dict(sorted(by_market.items())),
            },
            "matrix_sections": audit_sections,
        },
        "pass": not (errors or (warnings if strict else [])),
    }


def run_drift(json_output: bool = False, strict: bool = False) -> int:
    """离线 drift 入口：读随包目录，不联网、不需要凭证。"""
    cat = wmshare.load()
    gen = REPO / "src" / "wmshare" / "_catalog" / "generated"
    inventory_doc = json.loads((gen / "inventory.json").read_text(encoding="utf-8"))
    metrics_doc = json.loads((gen / "metrics.json").read_text(encoding="utf-8"))
    result = collect_drift(cat, inventory_doc, metrics_doc, strict=strict)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["pass"] else 1
    info = result["info"]
    print(f"# drift 审计 | 声明 {info['guard_declared']}/{info['functions']} 函数 "
          f"({info['guard_ratio'] * 100:.2f}%)")
    print(f"# shape 覆盖上游 {len(info['shape_overrides'])} 处（INFO，跨仓待办）")
    m = info["markets"]
    print(f"# markets 声明 {m['declared']}/{m['total']} ({m['ratio'] * 100:.2f}%)，"
          f"缺 {m['undeclared']}（INFO，P2）· 分市场 {m['by_market']}")
    print(f"# matrix 已覆盖 {info['matrix_sections']} 节（INFO，扩矩阵需联网额度，单独排期）")
    print(f"# ERROR {len(result['errors'])} · WARN {len(result['warnings'])} "
          f"(strict={strict})")
    for e in result["errors"]:
        print("ERROR:", e)
    for w in result["warnings"]:
        print("WARN:", w)
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="单位口径审计（cross 跨接口一致性 / matrix 全量逐字段 / drift 离线静态漂移）")
    ap.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE),
                    help="cross：逗号分隔的样本宇宙")
    ap.add_argument("--etf", default=DEFAULT_ETF, help="cross：ETF 代码")
    ap.add_argument("--compare-syms", default=2, type=int,
                    help="cross：对前 N 家跑 statement_compare（配额友好；0 关闭）")
    ap.add_argument("mode", nargs="?", choices=("cross", "matrix", "drift"),
                    default="cross", help="cross（默认，联网）/ matrix（联网）/ drift（离线）")
    ap.add_argument("--only", default=None, help="matrix：只跑名字含该子串的接口")
    ap.add_argument("--refresh", action="store_true", help="matrix：忽略缓存重取")
    ap.add_argument("--json", action="store_true", help="drift：机器可读 JSON 输出")
    ap.add_argument("--strict", action="store_true",
                    help="drift：把 WARN（shape 声明滞后）升级为失败")
    args = ap.parse_args(argv)

    # drift 必须在构造 Client 之前分流：它是离线静态检查，不该要求凭证、不该联网。
    if args.mode == "drift":
        return run_drift(json_output=args.json, strict=args.strict)

    cli = wmshare.Client.from_env()
    rep = Report()

    if args.mode == "matrix":
        rc = run_matrix(cli, rep, args.only, args.refresh)
        return rc if rep.ok() else 1

    print(f"# 单位口径审计 | 样本宇宙 {args.universe} | ETF {args.etf}")
    print(f"# wmshare {wmshare.__version__} | catalog upstream_rev "
          f"{cli.catalog.stats().get('upstream_rev')}")

    universe = [s.strip() for s in args.universe.split(",") if s.strip()]
    for i, sym in enumerate(universe):
        try:
            audit_symbol(rep, cli, sym)
        except wmshare.WmshareError as e:
            rep.add(False, "call", f"{sym}: {type(e).__name__}: {e}")
    if args.etf:
        try:
            audit_symbol(rep, cli, args.etf, with_fundamentals=False)
        except wmshare.WmshareError as e:
            rep.add(False, "call", f"ETF {args.etf}: {type(e).__name__}: {e}")
    for sym in universe[:max(0, args.compare_syms)]:
        try:
            cli.statements.compare(sym, kind="income", years=1)
            rep.add(True, "statements.diffp_ratio", f"{sym}: SDK 不变量通过（diffp 小数口径）")
        except DataError as e:
            rep.add(False, "statements.diffp_ratio", f"{sym}: {e}")

    fails = sum(1 for r in rep.rows if not r[0])
    print(f"\n# 结果：{len(rep.rows) - fails}/{len(rep.rows)} 通过"
          + ("" if not fails else f"；{fails} 项 FAIL（单位口径可能已漂移，请核查目录声明）"))
    return 0 if rep.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
