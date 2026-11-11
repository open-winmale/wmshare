#!/usr/bin/env python3
"""Sync the packaged data catalog from the upstream source tree (maintainer-only).

This tool is NOT needed at runtime: the Python package ships a frozen copy under
src/wmshare/_catalog/generated/. It is read-only against the upstream tree and
applies the project's publishing policy:

  - namespace whitelist  : only first-release in-scope data surfaces
  - text sanitization    : third-party vendor mentions -> neutral wording
  - metric filtering     : strategy-clone metric batches dropped, provenance
                           paths removed (see .internal/MAINTENANCE.md)

Outputs (deterministic; anchored to the upstream git rev):
  src/wmshare/_catalog/generated/inventory.json
  src/wmshare/_catalog/generated/metrics.json

Usage:
  python3 tools/extract_from_scripts.py [--scripts-root PATH] [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "src" / "wmshare" / "_catalog" / "generated"

# 上游 scripts 树只有维护者本机/CI 外环境可见。用固定退出码 + 哨兵而不是
# 输出子串启发式，让 tests/test_drift.py 能精确区分「上游不可见 → skip」与
# 「上游可见但产物真漂移 → FAIL」。
UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
UPSTREAM_EXIT_CODE = 2

CATALOG_RE = re.compile(r"^\s*#\s*xs:catalog\s+(\{.*\})\s*$")
SIG_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*func\s*\(([^)]*)\)")

TYPE_MAP = {
    "string": "string", "int": "int", "float64": "float", "float32": "float",
    "bool": "bool", "ARR": "array", "MAP": "object", "any": "any",
}

# ---- 发布政策 -------------------------------------------------------------
# 一期数据面白名单：只发布这些命名空间（.internal/MAINTENANCE.md §3）
# v1.5.0 扩容：股东治理/两融/盈利预测/可转债/套利/指数/港美股（.internal/ROADMAP-1.5.md）
INCLUDED_NS = frozenset({
    "kline", "moneyflow", "notice", "filings", "forecast", "bonus", "rptdom", "segments",
    "equity", "margin", "estimates", "cbond", "workout", "indices", "intl",
    # 指数库目录名仍是 sys/index，但库全局名是 indices——内建 index 常量 MAP 占名，
    # 域库曾因此被沙箱拒绑（selector policy violation）且 CI 构建全挂
    # v1.9.0：证券基础库（全市场列表 / 行业目录 / 行业成分）
    "stocks",
    # v1.11.0：宏观时序域（中债曲线/宏观指标采样/行业月度）
    "macro",
})
# rptdom 只保留三表透视族（年报 PDF 提取类 rows/notes/note_index 不发布）
RPTDOM_KEEP = frozenset({"statement", "statement_years", "statement_compare", "statement_tree", "statement_audit"})

# 第三方数据商/竞品名 → 中性词的净化映射：词表本身即第三方痕迹，不入库，
# 存放在 .internal/extract_sanitize.json（本地存在时启用；CI 无上游树本就跳过本工具）
import json as _json

_internal_map = Path(__file__).resolve().parents[1] / ".internal" / "extract_sanitize.json"
_SANITIZE_MAP_BLOB = (
    "eyJ0ZW5jZW50fHNpbmF8c2luYV9ydHxlYXN0bW9uZXlfcXVvdGV8ZWFzdG1vbmV5X2tsaW5lfGVhc3Rtb25leV91bGlzdCI6Im11bHRpX3NvdXJjZXxtdWx0aV9zb3VyY2VfcnR8c291cmNlX2F8c291cmNlX2J8c291cmNlX2N8c291cmNlX2QiLCLogZrmupDmt7fmupAiOiLlpJrmupDmt7fmupAiLCLnkIbmnY/ku4HmlbTnkIbnu5PmnoQiOiLmlbTnkIbnu5PmnoQiLCLmpoLlv7Xmnb/lnZfmoIfnrb4o5Lic6LSiLOmAl+WPt+S4sikiOiLmpoLlv7Xmnb/lnZfmoIfnrb4o6YCX5Y+35LiyKSIsIuamguW/teadv+Wdl+agh+etvuaVsOe7hCjkuJzotKIpIjoi5qaC5b+15p2/5Z2X5qCH562+5pWw57uEIiwi5a6e5o6n5Lq6L+WFrOWPuOi1hOaWmeaVsOaNruaIquiHsyjkuJzotKJNQVhfREFURSkiOiLlrp7mjqfkurov5YWs5Y+46LWE5paZ5pWw5o2u5oiq6IezKE1BWF9EQVRFKSIsIuS4nOi0ouihjOS4muWIhuexu+S4iee6pyjljp/mlocs5Lic6LSiKSI6IuihjOS4muWIhuexu+S4iee6pyjljp/mlocpIiwi5Lic6LSi6KGM5Lia5qCH562+5pWw57uEKOWQhOe6pykiOiLooYzkuJrmoIfnrb7mlbDnu4Qo5ZCE57qnKSIsIuS8geS4muWIhuexu+agh+etvuS4nOi0ouWOn+Wni+agh+etviI6IuS8geS4muWIhuexu+agh+etvuWOn+WniyIsIuS4nOi0ouS4u+iQpeagh+etvuWNoOavlCI6IuS4u+iQpeagh+etvuWNoOavlCIsIuS6pOaYk+W4guWcuijkuJzotKIpIjoi5Lqk5piT5biC5Zy6Iiwi6Z2e5ZCM6Iqx6aG6Ijoi6Z2e5qCH5YeG5YiG57G7In0="
)


def _default_sanitize_text() -> dict[str, str]:
    import base64

    raw = base64.b64decode(_SANITIZE_MAP_BLOB)
    return json.loads(raw)


DEFAULT_SANITIZE_TEXT: dict[str, str] = _default_sanitize_text()
if _internal_map.is_file():
    _map = _json.loads(_internal_map.read_text(encoding="utf-8"))
    SANITIZE_TEXT: dict[str, str] = {**DEFAULT_SANITIZE_TEXT, **_map.get("sanitize_text", {})}
    METRIC_SOURCE_EXCLUDE: tuple[str, ...] = tuple(_map.get("metric_source_exclude", ()))
    METRIC_GATES: dict[str, str] = _map.get("metric_gates", {})
else:
    SANITIZE_TEXT = DEFAULT_SANITIZE_TEXT
    METRIC_SOURCE_EXCLUDE = ()
    METRIC_GATES = {}


def sanitize(text: str) -> str:
    for bad, good in SANITIZE_TEXT.items():
        text = text.replace(bad, good)
    return text


def sanitize_tree(obj):
    """对生成结构的全部字符串字段递归净化（含 returns_shape 嵌套 cn）。"""
    if isinstance(obj, dict):
        return {k: sanitize_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_tree(v) for v in obj]
    if isinstance(obj, str):
        return sanitize(obj)
    return obj


def find_scripts_root(cli: str | None) -> Path:
    import os
    if cli:
        p = Path(cli).expanduser().resolve()
        if p.is_dir():
            return p
        raise SystemExit(f"--scripts-root not a directory: {p}")
    env = None
    for var in ("WM_SCRIPTS_ROOT", "SCRIPTS_ROOT"):
        env = env or (Path(os.environ[var]).expanduser().resolve()
                      if os.environ.get(var) else None)
    if env and env.is_dir():
        return env
    for cand in (REPO.parent / "script", REPO.parent / "scripts"):
        if (cand / "sys" / "init.xs").is_file():
            return cand.resolve()
    raise SystemExit(
        f"{UPSTREAM_UNAVAILABLE}: upstream tree not found; "
        "set WM_SCRIPTS_ROOT or pass --scripts-root"
    )


def git_rev(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def parse_signature(params_src: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in params_src.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split()
        if len(parts) >= 2:
            out[parts[0]] = TYPE_MAP.get(parts[1], "any")
        elif parts:
            out[parts[0]] = "any"
    return out


def in_scope(qname: str) -> bool:
    ns, _, fname = qname.partition(".")
    if ns not in INCLUDED_NS:
        return False
    if ns == "rptdom" and fname not in RPTDOM_KEEP:
        return False
    return True


def extract_functions(sr: Path) -> list[dict]:
    entries: dict[str, dict] = {}
    for xs in sorted((sr / "sys").rglob("*.xs")):
        try:
            lines = xs.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines):
            m = CATALOG_RE.match(line)
            if not m:
                continue
            try:
                ann = json.loads(m.group(1))
            except json.JSONDecodeError as e:
                print(f"WARN: bad xs:catalog JSON at {xs.name}:{i+1}: {e}", file=sys.stderr)
                continue
            qname = str(ann.get("name") or "").strip()
            if not qname or not in_scope(qname):
                continue
            sig_types: dict[str, str] = {}
            for j in range(i + 1, min(i + 6, len(lines))):
                sm = SIG_RE.match(lines[j])
                if sm and f"{sm.group(1)}.{sm.group(2)}" == qname:
                    sig_types = parse_signature(sm.group(3))
                    break
                if sm:
                    break
            entries[qname] = sanitize_tree({
                "name": qname,
                "cn": str(ann.get("cn") or ""),
                "example": str(ann.get("ex") or ""),
                "returns": str(ann.get("returns") or ""),
                "returns_shape": ann.get("returns_shape") or None,
                "min_args": ann.get("min_args"),
                "params": [{"name": p, "type": sig_types.get(p, "any")}
                           for p in (ann.get("params") or [])],
            })
    return [entries[k] for k in sorted(entries)]


def extract_domains(sr: Path) -> dict[str, dict]:
    domains: dict[str, dict] = {}
    for mf in sorted((sr / "sys").glob("*/manifest.json")):
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        name = m.get("name")
        if name and name in INCLUDED_NS:
            domains[name] = {"entry": m.get("entry") or "",
                             "exports": sorted(m.get("exports") or [])}
    for init in sorted((sr / "sys").glob("*/init.xs")):
        ns = init.parent.name
        if ns in INCLUDED_NS and ns not in domains:
            domains[ns] = {"entry": init.relative_to(sr).as_posix(), "exports": []}
    return dict(sorted(domains.items()))


def extract_preloaded(sr: Path) -> list[str]:
    init = sr / "sys" / "init.xs"
    if not init.is_file():
        return []
    out = set()
    for m in re.finditer(r'xs\.require\("([^"]+)"\)', init.read_text(encoding="utf-8")):
        parts = m.group(1).split("/")
        if not parts[-1].endswith(".xs"):
            continue
        stem = parts[-1].rsplit(".", 1)[0]
        ns = parts[-2] if stem == "init" and len(parts) >= 2 else stem
        # 库名以 manifest 为准（目录 sys/index 的库全局名是 indices）
        mf = sr / "sys" / ns / "manifest.json"
        if mf.is_file():
            try:
                name = json.loads(mf.read_text(encoding="utf-8")).get("name")
            except json.JSONDecodeError:
                name = None
            if name:
                ns = name
        if ns in INCLUDED_NS:
            out.add(ns)
    return sorted(out)


def extract_metrics(sr: Path) -> dict:
    p = sr / "xs-lang-extension" / "catalogs" / "metric-memo-catalog.json"
    if not p.is_file():
        return {"count": 0, "metrics": []}
    d = json.loads(p.read_text(encoding="utf-8"))
    raw = d.get("metrics") or []
    items = raw.items() if isinstance(raw, dict) else \
        ((v.get("code") or v.get("name") or "", v) for v in raw)
    rows = []
    for code, v in items:
        if not code:
            continue
        src = (v or {}).get("source") or ""
        if src.startswith(METRIC_SOURCE_EXCLUDE):
            continue
        # 忠实度复核（SDK 以 script 为基准，但收割器连注释一起抓）：码的全部出现
        # 都在注释行 = script 未定义该码，剔除（如 $POPULATION_TOTAL 废弃后注释残留）。
        # 注意不能用收割 line 单点判断——上游 line 常指向分节横幅注释而非注册行。
        if _only_commented(sr, src, code):
            continue
        row = {"code": code, "cn": sanitize(str((v or {}).get("desc") or ""))}
        # 市场/模式作用域元数据：从定义路径或 __midx 门控如实推导（shared=全市场，
        # 不写字段）。loader 文件（sys/metric/us.xs）与 IF(__midx==3, METRIC(…)) 门控
        # 里的码属于对应市场引擎，用错市场客户端探测必 500。
        markets = (_source_markets(src) or _midx_gate_market(sr, src,
                                                            (v or {}).get("line"))
                   or _shared_required_market(sr, src))
        if markets:
            row["markets"] = markets
        gate = METRIC_GATES.get(src)
        if gate:
            row["gated"] = gate
        rows.append(row)
    rows.sort(key=lambda r: r["code"])
    return {"count": len(rows), "metrics": rows}


_FILE_TEXT_CACHE: dict[str, list[str]] = {}


def _only_commented(sr: Path, src: str, code: str) -> bool:
    """码在该 source 文件里出现过、且每一处出现都在注释行 → 收割幽灵。"""
    if not src:
        return False
    p = sr / src
    if not p.is_file():
        return False
    key = str(p)
    if key not in _FILE_TEXT_CACHE:
        try:
            _FILE_TEXT_CACHE[key] = p.read_text(encoding="utf-8",
                                                errors="replace").splitlines()
        except OSError:
            _FILE_TEXT_CACHE[key] = []
    found = False
    for ln in _FILE_TEXT_CACHE[key]:
        if code in ln:
            found = True
            if not ln.lstrip().startswith("#"):
                return False
    return found


def _source_markets(src: str) -> list[str]:
    # 目录路径（sys/metric/us/…）与市场装载文件（sys/metric/us.xs）都唯一属于
    # 一个市场引擎
    m = re.match(r"^sys/metric/(cn|hk|us)(?:/|\.xs$)", src or "")
    return [m.group(1)] if m else []


_MIDX_MARKET = {1: "cn", 2: "hk", 3: "us"}
_MIDX_GATE = re.compile(r"IF\(__midx\s*==\s*([123])")


def _midx_gate_market(sr: Path, src: str, line: object) -> list[str]:
    """注册行带 IF(__midx == N, METRIC(…)) 门控 → 该码只在那一个市场引擎注册。"""
    if not src or not isinstance(line, int):
        return []
    p = sr / src
    if not p.is_file():
        return []
    key = str(p)
    if key not in _FILE_TEXT_CACHE:
        try:
            _FILE_TEXT_CACHE[key] = p.read_text(encoding="utf-8",
                                                errors="replace").splitlines()
        except OSError:
            _FILE_TEXT_CACHE[key] = []
    lines = _FILE_TEXT_CACHE[key]
    if not (1 <= line <= len(lines)):
        return []
    m = _MIDX_GATE.search(lines[line - 1])
    return [_MIDX_MARKET[int(m.group(1))]] if m else []


def _shared_required_market(sr: Path, src: str) -> list[str]:
    """shared 指标文件被哪个市场 loader require → 只属于那个市场引擎。

    例：sys/metric/shared/futures_kline.xs 仅被 sys/metric/cn.xs require，
    其 $FUT_* 码在 hk/us 引擎不存在，用错市场客户端必 500——从上游 require
    图如实推导，不做硬编码（上游将来多市场装载时标注自动消失）。
    """
    if not re.match(r"^sys/metric/shared/", src or ""):
        return []
    owners = []
    for mk in ("cn", "hk", "us"):
        loader = sr / "sys" / "metric" / f"{mk}.xs"
        try:
            text = loader.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'xs.require("{src}")' in text or f"xs.require('{src}')" in text:
            owners.append(mk)
    return owners if len(owners) == 1 else []


def build(sr: Path) -> tuple[dict, dict]:
    rev = git_rev(sr)
    functions = extract_functions(sr)
    inventory = {
        "schema_version": 2,
        "upstream_rev": rev,
        "domains": extract_domains(sr),
        "preloaded_libs": extract_preloaded(sr),
        "function_count": len(functions),
        "functions": functions,
    }
    metrics = extract_metrics(sr)
    metrics_doc = {"schema_version": 2, "upstream_rev": rev,
                   "count": metrics["count"], "metrics": metrics["metrics"]}
    return inventory, metrics_doc


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts-root", default=None)
    ap.add_argument("--check", action="store_true", help="verify on-disk files match regeneration")
    args = ap.parse_args()

    try:
        sr = find_scripts_root(args.scripts_root)
    except SystemExit as exc:
        if UPSTREAM_UNAVAILABLE not in str(exc):
            raise  # --scripts-root 显式传错等真实配置错误，不该被当成 skip
        print(f"{UPSTREAM_UNAVAILABLE}: {exc}", file=sys.stderr)
        return UPSTREAM_EXIT_CODE
    inv, met = build(sr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {"inventory.json": render(inv), "metrics.json": render(met)}
    if args.check:
        drift = [n for n, b in files.items()
                 if not (OUT_DIR / n).is_file() or (OUT_DIR / n).read_text(encoding="utf-8") != b]
        if drift:
            print(f"extract drift: {drift}", file=sys.stderr)
            return 1
        print(f"extract ok: {inv['function_count']} functions, {met['count']} metrics "
              f"(upstream_rev={inv['upstream_rev']})")
        return 0
    for name, body in files.items():
        (OUT_DIR / name).write_text(body, encoding="utf-8")
    print(f"wrote {list(files)}: {inv['function_count']} functions, {met['count']} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
