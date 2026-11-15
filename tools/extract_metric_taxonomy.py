#!/usr/bin/env python3
"""生成指标分类 sidecar：generated/metric_taxonomy.json。

只读取现有 metrics.json、fund.indicators.yaml、可选上游 metric memo catalog，
不修改 metrics.json / Catalog / API。sidecar 供可选的 IndicatorAdapter 使用。

用法:
  python tools/extract_metric_taxonomy.py            # 写入 sidecar
  python tools/extract_metric_taxonomy.py --check    # 漂移检查（CI）
  python tools/extract_metric_taxonomy.py --output /tmp/metric_taxonomy.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"
METRICS = CATALOG / "generated" / "metrics.json"
TAXONOMY = CATALOG / "taxonomy.yaml"
CURATED = CATALOG / "domains" / "fund.indicators.yaml"
OUTPUT = CATALOG / "generated" / "metric_taxonomy.json"
UPSTREAM_MEMO = REPO.parent / "script" / "xs-lang-extension" / "catalogs" / "metric-memo-catalog.json"

_TOPIC_PREFIXES = ("$CUR_IND_", "$IDW_", "$ID_", "$INDEX_")
_PROFILE_PREFIXES = (
    "$NAME", "$CODE", "$EM2016", "$IND", "$ORG", "$IPO", "$LIST", "$CCY",
    "$ASB", "$IS_", "$EMP_NUM", "$BENCH", "$SAS", "$REPORT_PERIOD",
    "$RDATE", "$FY", "$YEARDAY", "$DATE",
)

# 上游来源映射只在 tools/ 里维护，不进 wheel（taxonomy.yaml 不携带来源路径）。
MACRO_SOURCES = frozenset({
    "sys/metric/cn/macro.xs",
    "sys/metric/us/macro.xs",
    "sys/metric/hk/macro.xs",
})

SOURCE_TOPICS = {
    "sys/metric/shared/op.xs": "statements",
    "sys/metric/shared/op_clean.xs": "statements",
    "sys/metric/cn/comp.xs": "statements",
    "sys/metric/begin.xs": "statements",
    "sys/metric/basic.xs": "disclosure",
    "sys/metric/shared/syms_base.xs": "statements",
    "sys/metric/shared/bonus.xs": "dividend",
    "sys/metric/org.xs": "profile",
    "sys/metric/shared/kline.xs": "quote",
    "sys/metric/shared/kline_cn.xs": "quote",
    "sys/metric/cn/index_quote.xs": "quote",
    "sys/metric/shared/futures_kline.xs": "quote",
    "sys/metric/hroe_b2.xs": "profitability",
    "sys/metric/cn/forecast.xs": "estimates",
    "sys/metric/shared/pr_dingning.xs": "valuation",
    "sys/metric/cn/syms.xs": "statements",
    "sys/metric/shared/syms_ev_base.xs": "statements",
    "sys/metric/shares.xs": "quote",
    "sys/metric/shared/cyclical.xs": "profile",
    "eod_tech_tip.xs": "quote",
    "sys/metric/screen.xs": "growth",
    "sys/metric/cn/screen_cn.xs": "growth",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _topic_code(code: str) -> str:
    for prefix in _TOPIC_PREFIXES:
        if code.startswith(prefix):
            return "$" + code[len(prefix):]
    return code


def _scope_of(code: str, source: str, cfg: dict[str, Any]) -> str:
    if source in MACRO_SOURCES:
        return "macro"
    if code.startswith("$FUT_"):
        return "futures"
    if code.startswith(("$INDEX_", "$IDW_")):
        return "index"
    if code.startswith(("$ID_", "$CUR_IND_")):
        return "industry"
    if code.startswith("$BOND_"):
        return "cbond"
    if code.startswith(("$c_", "$c", "$x_", "$x")):
        return "screener"
    theme = code[1:].split("_", 1)[0] if "_" in code[1:] else code[1:]
    if theme in set(cfg.get("macro_themes") or []):
        return "macro"
    return "stock"


def _topic_of(code: str, source: str, scope: str, cfg: dict[str, Any]) -> str:
    if scope == "macro":
        return "macro"
    if scope == "screener":
        return "screener"
    if scope == "futures":
        return "quote"
    if scope == "cbond":
        return "terms"
    if code.startswith("$BOND_"):
        return "terms"
    probe = _topic_code(code)
    for rule in cfg.get("topic_rules") or []:
        if re.search(rule["pattern"], probe):
            return rule["topic"]
    name = source.rsplit("/", 1)[-1]
    if name.endswith("technical.xs"):
        return "quote"
    if name.endswith("_metrics.xs") or name == "metrics.xs":
        return "statements"
    if name.endswith("eod_tech_tip.xs"):
        return "quote"
    if name.endswith("_events.xs"):
        return "ownership"
    source_topic = SOURCE_TOPICS.get(source)
    if not source_topic:
        source_topic = SOURCE_TOPICS.get(name)
    if source_topic:
        return source_topic
    if source.startswith(("sys/metric/shared/", "sys/metric/cn/",
                          "sys/metric/us/", "sys/metric/hk/")):
        return "statements"
    if code.startswith(_PROFILE_PREFIXES):
        return "profile"
    return "other"


def _window_of(code: str) -> str:
    m = re.search(r"_(1Y|3Y|5Y|10Y|3Q|YTD)(?:_|$)", code)
    return m.group(1).lower() if m else "none"


def _period_of(code: str, scope: str, topic: str, window: str) -> str:
    if scope == "macro":
        return "quarterly" if code in ("$GDP", "$PMI", "$ASSET_INVEST", "$FIXED_ASSET") else "monthly"
    if scope in ("futures", "cbond"):
        return "snapshot"
    if scope in ("index", "industry") and topic == "quote":
        return "snapshot"
    if "_TTM" in code or "_YOY" in code:
        return "ttm"
    if re.search(r"_(WEEK)(?:_|$)", code):
        return "weekly"
    if re.search(r"_(DAY)(?:_|$)", code):
        return "daily"
    if topic in ("profile", "terms", "disclosure", "quote"):
        return "snapshot"
    if topic in ("statements", "estimates"):
        return "latest_report"
    if window != "none":
        return "multi_year"
    if topic in (
        "valuation", "profitability", "growth", "scale", "cashflow",
        "solvency", "efficiency", "dividend", "ownership",
    ):
        return "latest_report"
    return "snapshot"


def _caliber_of(code: str, cn: str, cfg: dict[str, Any]) -> list[str]:
    text = f"{code} {cn}"
    pairs = [
        ("parent", ("归母", "母公司", "属母")),
        ("deducted", ("扣非",)),
        ("consolidated", ("合并",)),
        ("free_float", ("流通",)),
        ("total", ("总市值", "总股本", "总资产", "总负债")),
        ("overall", ("整体法", "行业整体", "行业均值", "行业合计")),
        ("median", ("中位数", "中位")),
        ("weighted", ("加权",)),
        ("equal_weight", ("等权",)),
        ("before_tax", ("税前",)),
        ("after_tax", ("税后",)),
    ]
    out: list[str] = []
    for name, keywords in pairs:
        if any(k in text for k in keywords):
            out.append(name)
    # 复权：先判「不复权/无复权」——它们字面上包含「复权」，否则会同时命中 adjusted。
    if any(k in text for k in ("不复权", "无复权")):
        out.append("unadjusted")
    elif any(k in text for k in ("前复权", "后复权", "复权")):
        out.append("adjusted")
    if code.startswith("$IDW_"):
        out.append("equal_weight" if "_HM" in code else "weighted")
    if code.startswith(("$ID_", "$CUR_IND_")):
        out.append("overall")
    if code.startswith("$MV_FREE"):
        out.append("free_float")
    elif code.startswith("$MV_"):
        out.append("total")
    return list(dict.fromkeys(out))


def _unit_kind_of(code: str, cn: str, topic: str, group_unit: str) -> str:
    if "PCT" in code or "分位" in cn:
        return "percentile"
    # 成交量族先判：$VOLUME_AR_DAY 的 "AR" 是「后复权」后缀，不是年化收益。
    if code.startswith("$VOLUME") or re.search(r"\((?:股|万股|亿股)\)", cn) \
            or code.startswith(("$SHARES", "$TOTAL_SHARE", "$FLOAT_SHARE", "$FREE_SHARE")):
        return "shares"
    if code in ("$PE", "$PB", "$PS", "$PCF", "$PEG", "$PR", "$EV_EBIT", "$EV_EBITDA"):
        return "multiple"
    # 倍数优先于「率→ratio」：cn 里「市盈率/市净率/市销率/市现率/市赚率/EV/…」的
    # 返回值是倍数，不是百分数。57 个码曾因「率」字被误标成 ratio。
    if re.search(r"市盈率|市净率|市销率|市现率|市赚率|EV/|倍数", cn):
        return "multiple"
    if "_YOY" in code or "_AR_" in code:
        return "ratio"
    if re.search(r"\((?:元/股|元每股)\)", cn) or "每股" in cn or code.startswith(
            ("$DPS", "$EPS", "$CEPS", "$BPS")):
        return "per_share"
    if re.search(r"\((?:天)\)", cn) or "天数" in cn or "_DAYS" in code:
        return "days"
    if re.search(r"\((?:倍)\)", cn) or code.startswith(
            ("$PE_", "$PB_", "$PS_", "$PCF_", "$PEG_", "$EV_EBIT", "$EV_EBITDA", "$PR_")):
        return "multiple"
    if re.search(r"\((?:点|指数点)\)", cn) or code in ("$CPI", "$PPI"):
        return "index_point"
    if re.search(r"\((?:%|％)\)", cn) or any(k in cn for k in ("率", "比例", "占比", "幅")) \
            or code.startswith(("$PERCENT", "$CHG", "$AMPLITUDE", "$BIAS", "$ROE",
                                "$ROA", "$ROIC", "$GM", "$ALPHA", "$BETA", "$ROI")):
        return "ratio"
    if re.search(r"\((?:元|万元|亿元|亿)\)", cn) or any(
            k in cn for k in ("金额", "收入", "利润", "市值", "现金")) or code.startswith(
            ("$AMOUNT", "$MV", "$TR", "$NP", "$NPTS", "$DPPR", "$OC", "$OIE",
             "$EBITDA", "$CASH", "$EV", "$CORE_NP", "$EXPENSE", "$BONUS_TTM", "$MF_")):
        return "money"
    if re.search(r"价格|收盘价|开盘价|最高价|最低价", cn) or code.startswith(
            ("$CLOSE", "$OPEN", "$HIGH", "$LOW", "$AVG_DAY", "$MA_", "$PRICE")):
        return "price"
    if "_NUM" in code or any(k in cn for k in ("家数", "数量", "户数")):
        return "count"
    if code.startswith(("$CAIBAO_", "$NAME", "$CODE", "$EM2016", "$CSRC_INDUSTRY",
                        "$ORG", "$CCY", "$ASB", "$BLGAINIAN", "$CONCEPT",
                        "$ANALYST_RATING")):
        return "text"
    if "是否" in cn or code.startswith(("$IS_", "$HAS_")):
        return "bool"
    if topic == "statements":
        return "ratio" if (re.search(r"率|比例|占比|周转|天数", cn) or "_RATE" in code) else "money"
    if topic == "terms":
        if re.search(r"率|比例|溢价", cn) or any(k in code for k in ("RATIO", "COUPON", "PREMIUM")):
            return "ratio"
        if re.search(r"价格|面值|转股价", cn) or "PRICE" in code:
            return "price"
        if re.search(r"规模|金额|余额", cn) or "FUNDS" in code:
            return "money"
        return "text"
    if topic == "macro":
        if re.search(r"指数|PMI|景气", cn):
            return "index_point"
        if re.search(r"率|同比|增长|占比", cn):
            return "ratio"
        if re.search(r"金额|亿元|万亿|元", cn):
            return "money"
        return "index_point"
    if topic == "quote":
        if re.search(r"BOLL_(LOWER|MID|UPPER)", code):
            return "price"
        if re.search(r"BOLL_(WIDTH|POSITION)", code):
            return "ratio"
        if re.search(r"BOLL|RSI|KDJ|MACD|CCI|WR|OBV|DMI|PSY|VR|ROC|MTM|TRIX|"
                     r"DPO|AROON|BBI|ENV|ASI|EMV|FI|VWAP", code):
            return "ratio"
        return "unknown"
    if topic in ("profile", "disclosure"):
        return "text"
    if topic == "estimates":
        if "_NUM" in code or "家数" in cn:
            return "count"
        return "ratio" if ("SCORE" in code or "评级系数" in cn) else "text"
    if topic == "screener":
        return "bool" if code.startswith(("$c", "$x")) else "ratio"
    if topic == "valuation":
        return "multiple"
    if topic in ("profitability", "growth", "solvency", "efficiency", "cashflow", "dividend"):
        if "元" in group_unit:
            return "money"
        if "倍" in group_unit:
            return "multiple"
        return "ratio"
    if "元/股" in group_unit:
        return "per_share"
    if "元" in group_unit:
        return "money"
    if "倍" in group_unit:
        return "multiple"
    return "unknown"


def _curated_groups(cfg: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    doc = _load_yaml(CURATED)
    group_topics = cfg.get("group_topics") or {}
    out: dict[str, tuple[str, str, str]] = {}
    for group in doc.get("metric_groups") or []:
        scope, topic = group_topics.get(group["id"], ("stock", "other"))
        for metric in group.get("metrics") or []:
            out[metric["code"]] = (scope, topic, group.get("unit", ""))
    return out


# 注册行解析：METRIC($A, <expr>, "cn", "tag1", "tag2", ...)
_REG_LINE = re.compile(r'(?:METRIC|metric\.add)\(\s*"?(\$[A-Za-z0-9_]+)"?\s*,(.*)$')
_ALIAS_EXPR = re.compile(r'^\s*(\$[A-Za-z0-9_]+)\s*,')
_TAGS_RE = re.compile(r'"([a-z_]+)"')
_TTM_REF = re.compile(r'\$[A-Za-z0-9_]*_TTM(?:_LAST)?\b')
# 上游 tag → 分类 period。last/kline 是「取值方式」，不是周期，不参与映射。
_TAG_PERIOD = {"ttm": "ttm"}


def _scan_upstream(script: Path) -> dict[str, dict[str, Any]]:
    """扫描上游注册行，抽取每码的计算 tag 与纯别名目标。

    返回 {code: {"tags": set[str], "alias": str | None, "expr": str}}。
    上游不可见时返回空 dict（分类退回启发式）。
    """
    out: dict[str, dict[str, Any]] = {}
    base = script / "sys" / "metric"
    if not base.is_dir():
        return out
    for path in base.rglob("*.xs"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _REG_LINE.search(line)
            if not m:
                continue
            code, rest = m.group(1), m.group(2)
            expr, _, quoted = rest.partition('"')
            tags = set(_TAGS_RE.findall(quoted.split(")", 1)[0])) if quoted else set()
            alias_m = _ALIAS_EXPR.match(expr)
            entry = out.setdefault(code, {"tags": set(), "alias": None, "expr": ""})
            entry["tags"] |= tags
            if not entry["expr"]:
                entry["expr"] = expr.strip()
            if alias_m and code not in (entry["alias"] or ""):
                entry["alias"] = alias_m.group(1)
    return out


def _period_from_upstream(row: dict[str, Any], upstream: dict[str, Any]) -> str | None:
    """上游信号 → period：tag 优先，其次「表达式引用 _TTM」。"""
    tags = upstream.get("tags") or set()
    for tag, period in _TAG_PERIOD.items():
        if tag in tags:
            return period
    if _TTM_REF.search(upstream.get("expr") or ""):
        return "ttm"
    return None


def build(taxonomy_path: Path = TAXONOMY, metrics_path: Path = METRICS,
          upstream_path: Path = UPSTREAM_MEMO,
          script_root: Path | None = None) -> dict[str, Any]:
    cfg = _load_yaml(taxonomy_path)
    doc = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics = doc["metrics"]
    upstream: dict[str, Any] = {}
    if upstream_path.is_file():
        upstream = json.loads(upstream_path.read_text(encoding="utf-8")).get("metrics") or {}
    script = script_root or upstream_path.parents[2]
    regs = _scan_upstream(script)
    curated = _curated_groups(cfg)
    overrides = cfg.get("code_overrides") or {}

    rows: list[dict[str, Any]] = []
    for metric in metrics:
        code = metric["code"]
        cn = metric.get("cn", "")
        source = (upstream.get(code) or {}).get("source", "")
        scope = _scope_of(code, source, cfg)
        topic = _topic_of(code, source, scope, cfg)
        group_unit = ""
        if code in curated:
            scope, topic, group_unit = curated[code]
        window = _window_of(code)
        period = _period_of(code, scope, topic, window)
        # 上游 tag / 表达式优先于码名启发式（码名猜不出 $EV_EBITDA 的分母是 TTM）。
        tag_period = _period_from_upstream({}, regs.get(code) or {})
        if tag_period:
            period = tag_period
        row = {
            "code": code,
            "scope": scope,
            "topic": topic,
            "period": period,
            "window": window,
            "caliber": _caliber_of(code, cn, cfg),
            "unit_kind": _unit_kind_of(code, cn, topic, group_unit),
            "status": "dead" if cn == "drop stub" else "active",
        }
        row.update(overrides.get(code) or {})
        rows.append(row)

    # 纯别名传播：METRIC($A, $B, ...) 且 $B 紧跟逗号（无运算）→ A 继承 B 的分类。
    by_code = {r["code"]: r for r in rows}
    for _ in range(3):  # 别名链有界（A→B→C）
        changed = False
        for code, reg in regs.items():
            target = reg.get("alias")
            src_row = by_code.get(target) if target else None
            row = by_code.get(code)
            if not src_row or not row:
                continue
            if row["code"] in (overrides.get(code) or {}):
                continue  # 显式覆盖不跟随
            # 自带 period 相关 tag（ttm）的不跟随别名；kline/last 不是周期，照常跟随。
            if _period_from_upstream({}, reg) is not None:
                continue
            for field in ("period", "window", "unit_kind"):
                if row[field] != src_row[field]:
                    row[field] = src_row[field]
                    changed = True
            if row["caliber"] != src_row["caliber"]:
                row["caliber"] = list(src_row["caliber"])
                changed = True
        if not changed:
            break

    rows.sort(key=lambda r: r["code"])
    n = len(rows)
    other = sum(1 for r in rows if r["topic"] == "other")
    caliber_unknown = sum(1 for r in rows if "unknown" in r["caliber"])
    unit_unknown = sum(1 for r in rows if r["unit_kind"] == "unknown")
    stats = {
        "count": n,
        "other": round(other / n, 6) if n else 0.0,
        "caliber_unknown": round(caliber_unknown / n, 6) if n else 0.0,
        "unit_unknown": round(unit_unknown / n, 6) if n else 0.0,
        "dead": sum(1 for r in rows if r["status"] == "dead"),
        "scopes": _counts(rows, "scope"),
        "topics": _counts(rows, "topic"),
        "periods": _counts(rows, "period"),
        "windows": _counts(rows, "window"),
        "unit_kinds": _counts(rows, "unit_kind"),
    }
    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "upstream_rev": doc.get("upstream_rev", ""),
        "taxonomy_version": str(cfg.get("taxonomy_version") or ""),
        "stats": stats,
        "metrics": rows,
    }


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = row[key]
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="只检查 sidecar 是否漂移")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--taxonomy", type=Path, default=TAXONOMY)
    ap.add_argument("--metrics", type=Path, default=METRICS)
    ap.add_argument("--upstream", type=Path, default=UPSTREAM_MEMO)
    args = ap.parse_args(argv)

    # source/banner 分类需要上游 memo；干净 checkout 没有 ../script 时：
    # --check 显式跳过（sidecar 仍是提交物，validate_metric_taxonomy 继续校验 1:1），
    # 生成模式必须要求上游，避免写出 20% other 的降级 sidecar。
    if not args.upstream.is_file():
        if args.check:
            print(f"SKIP: 上游 memo 不可见（{args.upstream}），跳过 sidecar 漂移检查；"
                  "validate_metric_taxonomy 仍校验 1:1", file=sys.stderr)
            return 0
        print(f"ERROR: 上游 memo 不可见（{args.upstream}）；生成 sidecar 需要 ../script",
              file=sys.stderr)
        return 2

    try:
        payload = build(args.taxonomy, args.metrics, args.upstream)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    text = dumps(payload)
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != text:
            print(f"FAIL: {args.output} 已漂移；请运行 python tools/extract_metric_taxonomy.py",
                  file=sys.stderr)
            return 1
        print(f"OK: {args.output} 与 taxonomy/metrics 一致")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({payload['stats']['count']} codes, "
          f"other={payload['stats']['other']:.2%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
