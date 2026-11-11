#!/usr/bin/env python3
"""Render docs/API.md from the packaged catalog + friendly API registry.

按资产类别分章的核心参考：每章（行情/可转债/指数/期货/宏观/财务/披露/港美/参考）
内按命名空间分节，每个核心接口一个独立小节（说明/输入参数表/输出字段表/示例），
对齐主流数据平台逐接口文档形态；全量底层函数目录收进文末折叠附录。
Deterministic; `--check` verifies the on-disk doc matches (drift gate).

Usage:
  python3 tools/gen_api_docs.py          # write docs/API.md
  python3 tools/gen_api_docs.py --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _introspect import (  # noqa: E402
    COMPOSITE_EXAMPLES, COMPOSITE_NOTES, FALLBACK_RETURNS, RETURNS_OVERRIDES,
    method_doc, method_example, method_params, return_shape_for, underlying_fn,
)
from wmshare.api import (  # noqa: E402
    COMPOSITE_METHODS, FRIENDLY_INDEX, FRIENDLY_NAMESPACES)
from wmshare.catalog import catalog_dir, load  # noqa: E402

DOMAINS = catalog_dir() / "domains"
INVENTORY = json.loads((catalog_dir() / "generated" / "inventory.json").read_text(encoding="utf-8"))
INV = {f["name"]: f for f in INVENTORY["functions"]}
CAT = load()
OUT = REPO / "docs" / "API.md"

KIND_CN = {"raw": "原始数据", "computed": "指标", "mixed": "混合"}
CATEGORY_CN = {"market": "市场行情", "fundamentals": "财务基本面",
               "disclosure": "信息披露", "reference": "参考数据"}
CATEGORY_ORDER = ["market", "fundamentals", "disclosure", "reference"]

# 资产类别分章（文档主轴，对齐主流数据平台的目录形态）：
# 每章内按命名空间分节；无友好层命名空间的章（期货）为指标码专题。
# 断言：FRIENDLY_INDEX 的每个 ns 恰好归入一章（build() 内校验，防漂移漏收）。
CHAPTERS: list[tuple[str, list[str]]] = [
    ("A 股行情与选股", ["kline", "screener", "backtest", "moneyflow", "margin", "stocks"]),
    ("可转债", ["cbond"]),
    ("指数", ["index"]),
    ("期货", []),  # $FUT_* 指标码专题（指标码层，无函数级域）
    ("宏观", ["macro"]),
    ("财务基本面", ["statements", "segments", "valuation", "estimates", "indicator"]),
    ("信息披露与公司行动", ["notice", "filings", "forecast", "dividend", "equity", "workout"]),
    ("港股与美股", ["intl"]),
    ("参考数据", ["info"]),
]
# 指标组挂靠章：该 category 的域（fund.indicators）指标组渲染在章内接口之后
CHAPTER_METRIC_CATEGORIES: dict[str, list[str]] = {"财务基本面": ["fundamentals"]}

# 友好层参数说明兜底表（docstring 未写 :param 的高频参数；其余落「—」）
PARAM_DOCS: dict[str, str] = {
    "symbol": "6 位裸码（自动归一前缀/后缀；港股 5 位、美股字母码）",
    "n": "根数",
    "limit": "条数上限",
    "begin": "开始日期 YYYY-MM-DD（含端点）",
    "end": "结束日期 YYYY-MM-DD（含端点）",
    "window": "窗口（\"7d\"/\"1m\"/…/\"5y\" 或天数）",
    "keyword": "标题/类型正则（可空）",
    "top_n": "只取前 N 条",
    "sort_by": "排序字段",
    "years": "最近 N 个报告期",
    "idx": "宽度索引（None=服务端解析全市场）",
    "points": "采样点数",
}


def esc(s: object) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def gh_slug(title: str) -> str:
    """GitHub 风格标题锚点：小写、去标点（保留连字符/空格/CJK）、空格转连字符。"""
    import re
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


TYPE_SHORT = {"float64": "float", "int64": "int"}
UNIT_CN = {"percent": "百分数→小数", "yi_yuan": "亿元→元", "lot": "手→股"}


def fmt_guards(fn: dict) -> str:
    """单位换算与守护声明的紧凑渲染（无声明时为 —）。"""
    parts = [f"`{f}`:{UNIT_CN[u]}" for f, u in (fn.get("units") or {}).items()]
    rng = fn.get("ranges") or {}
    if rng:
        parts.append("量级界 " + "、".join(f"`{f}`" for f in rng))
    checks = [f"`{c}`" for c in fn.get("checks") or []]
    if checks:
        parts.append("不变量 " + "、".join(checks))
    return "；".join(parts) if parts else "—"


def fmt_params(fn: dict, inv: dict) -> str:
    params = fn.get("params")
    if not params:
        sig = inv.get("params") or []
        if not sig:
            return "—"
        return " · ".join(f"`{p['name']}:{p.get('type', 'any')}`" for p in sig) + "（签名）"
    parts = []
    for p in params:
        s = f"{p['name']}:{p['type']}"
        if not p.get("required") and "default" not in p:
            s += "?"
        if "default" in p:
            s += f"={json.dumps(p['default'], ensure_ascii=False)}"
        part = f"`{s}`"
        if p.get("desc"):
            part += f" — {esc(p['desc'])}"
        parts.append(part)
    return " · ".join(parts)


def fmt_returns(fn: dict, inv: dict, shape: dict | None = None) -> str:
    ret = fn.get("returns") or {}
    desc = ret.get("desc") or inv.get("returns") or "—"
    if shape is None and ret.get("shape_ref") == "inventory":
        shape = inv.get("returns_shape")
    if shape and shape.get("kind") == "object":
        desc = "MAP · " + (shape.get("cn") or "结果")
    if shape:
        fields = (shape.get("items") or shape).get("fields") or []
        if fields:
            detail = " / ".join(
                f"{f['name']}:{TYPE_SHORT.get(f.get('type', 'any'), f.get('type', 'any'))}"
                + ("?" if f.get("optional") else "")
                + (f"（{f['cn']}）" if f.get("cn") else "")
                for f in fields)
            desc += "；字段 " + detail
    return esc(desc)


def doc_hidden(fn: dict) -> bool:
    """脚本专用/内部辅助函数不进公开文档（保留在目录中，cli.call 仍可调）。"""
    if fn.get("status") == "internal":
        return True
    short = fn["name"].split(".", 1)[-1]
    return short.startswith(("index_where_", "index_field")) or short.endswith("_bin_expr")


def _split_top_args(s: str) -> list[str] | None:
    """按顶层逗号切分参数串；引号/括号不平衡时返回 None。"""
    args: list[str] = []
    depth, cur, quote = 0, "", ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if depth != 0 or quote:
        return None
    if cur.strip():
        args.append(cur.strip())
    return args


def _py_literal(js: str) -> object | None:
    """目录示例里的 JS 风格字面量 → Python 值；含标识符/调用（如 LatestIndexKey()）时返回 None。"""
    import ast
    import re
    t = js.strip()
    if not t:
        return None
    relaxed = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False",
                     re.sub(r"\b(?:nil|null)\b", "None", t)))
    for candidate in (t, relaxed):
        try:
            return ast.literal_eval(candidate)
        except (ValueError, SyntaxError):
            continue
    return None


def sdk_example(fn: dict, inv: dict) -> str:
    """把目录示例机械转写为 cli.call kwargs 形式；参数含非字面量时宁缺毋编（返回空串）。"""
    ex = fn.get("example") or inv.get("example") or ""
    if not ex or "(" not in ex or not ex.endswith(")"):
        return ""
    name, _, argstr = ex[:-1].partition("(")
    if name.strip() != fn["name"]:
        return ""
    args = _split_top_args(argstr)
    if args is None:
        return ""
    sig = fn.get("params") or inv.get("params") or []
    names = [p["name"] for p in sig]
    if len(args) > len(names):
        return ""
    vals = [_py_literal(a) for a in args]
    if not all(v is not None for v in vals):
        return ""
    kw = ", ".join(f"{n}={v!r}" for n, v in zip(names, vals))
    return f'cli.call("{fn["name"]}"{", " + kw if kw else ""})'


def ns_title(ns: str) -> str:
    """命名空间标题：取类 docstring 首句（到句号/括号/冒号为止），防编造。"""
    import inspect
    import re as _re
    doc = inspect.getdoc(FRIENDLY_NAMESPACES[ns]) or ""
    head = _re.split(r"[。：（(:]", doc.strip(), 1)[0].strip()
    return head or ns


# ---------------------------------------------------------------- 每接口小节
def _param_desc(ns: str, method: str, p, fn: dict) -> str:
    """参数说明：友好层 docstring :param → 目录同名参数 desc → 通用兜底表 → —。"""
    if getattr(p, "desc", ""):
        return esc(p.desc)
    for cp in fn.get("params") or []:
        if cp.get("name") == p.name and cp.get("desc"):
            return esc(cp["desc"])
    return PARAM_DOCS.get(p.name, "—")


def interface_block(ns: str, method: str, cn: str, underlying: str,
                    merged: dict[str, dict]) -> list[str]:
    """单接口小节：标题 + 一句话说明 + 输入参数表 + 输出 + 示例代码块。

    结构即测试合同（tests/test_docs.py 的解析正则与本函数同步演化）。
    """
    cls = FRIENDLY_NAMESPACES[ns]
    params = method_params(cls, method)
    fn_key = underlying_fn(underlying)
    fn = merged.get(fn_key, {}) if fn_key else {}
    inv = INV.get(fn_key, {}) if fn_key else {}
    desc = method_doc(cls, method)[0] or cn

    out = [f"#### `cli.{ns}.{method}` — {esc(cn)}", "", esc(desc), ""]

    # 输入参数表
    if params:
        out += ["**输入参数**", "",
                "| 参数 | 类型 | 必填 | 默认 | 说明 |", "|---|---|---|---|---|"]
        for p in params:
            req = "是" if p.required else "否"
            dflt = f"`{p.default}`" if p.default is not None else "—"
            out.append(f"| `{p.name}` | {p.json_type} | {req} | {dflt} "
                       f"| {_param_desc(ns, method, p, fn)} |")
        out.append("")
    else:
        out += ["**输入参数**：无。", ""]

    # 输出：shape 字段表优先，退化为说明行
    shape = return_shape_for(CAT, ns, method, underlying) if fn_key else None
    if fn_key:
        ret = fmt_returns(fn, inv, shape=shape)
        ret = RETURNS_OVERRIDES.get((ns, method), ret)
    else:
        ret = FALLBACK_RETURNS.get((ns, method), "—")
    fields = []
    if shape:
        fields = (shape.get("items") or shape).get("fields") or []
    if fields and (ns, method) not in RETURNS_OVERRIDES:
        out += ["**输出字段**", "",
                "| 字段 | 类型 | 说明 |", "|---|---|---|"]
        for f in fields:
            t = TYPE_SHORT.get(f.get("type", "any"), f.get("type", "any"))
            if f.get("optional"):
                t += "?"
            out.append(f"| `{f['name']}` | {t} | {esc(f.get('cn', '')) or '—'} |")
        out.append("")
    else:
        out += [f"**输出**：{ret}", ""]

    ex = method_example(ns, method, params)
    out += ["**示例**", "", "```python", ex, "```", ""]
    return out


def docstring_body(cls: type, method: str) -> list[str]:
    """方法 docstring 的正文段落：去首行摘要与 :param，按空行分段、段内并成一行。

    docstring 的硬换行只受 79 列约束，直接逐行输出会把一句话切成几个段落。
    """
    doc = inspect.getdoc(getattr(cls, method)) or ""
    paras: list[str] = []
    buf: list[str] = []
    for ln in doc.strip().splitlines()[1:]:
        t = ln.strip()
        if not t or t.startswith(":param"):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(t)
    if buf:
        paras.append(" ".join(buf))
    # docstring 里常用 reST 的双反引号标行内代码，Markdown 用单反引号
    return [re.sub(r"``([^`]+)``", r"`\1`", p) for p in paras]


def composite_section(ns: str) -> list[str]:
    """组合接口小节：跨目录函数的研究级封装（不回溯单一底层函数）。

    刻意用表 + 示例，而不是 ``#### `cli.ns.method` `` 小节——后者是
    「核心接口 ↔ 底层目录函数」一一映射的文档形态，被 tests/test_docs.py
    按 FRIENDLY_INDEX 逐条校验；组合接口没有对应的底层目录函数。
    """
    methods = sorted(COMPOSITE_METHODS.get(ns, ()))
    if not methods:
        return []
    cls = FRIENDLY_NAMESPACES[ns]
    out = ["#### 组合接口（研究级封装）", "",
           "以下方法同样是 `cli.<命名空间>.<方法>()` 门面，**可直接调用**；区别只在于底层"
           "不是单一目录函数，而是跨多个接口 + 本地计算串成一条链路。**取数仍走客户端**"
           "（请求次数与 EC 照常计，EC 按请求行数），本地只负责规则与汇总。", ""]
    note = COMPOSITE_NOTES.get(ns)
    if note:
        out += [note, ""]
    out += ["| 方法 | 签名 | 输出 |", "|---|---|---|"]
    for method in methods:
        params = method_params(cls, method)
        sig = ", ".join(f"{p.name}={p.default}" if p.default else p.name for p in params)
        ret = FALLBACK_RETURNS.get((ns, method), "—")
        out.append(f"| `cli.{ns}.{method}` | `{method}({esc(sig)})` | {esc(ret)} |")
    out.append("")
    for method in methods:
        summary, _ = method_doc(cls, method)
        out += [f"**`cli.{ns}.{method}`** — {esc(summary)}", ""]
        # parse_docstring 会把多行正文用「、」串起来（那是给一句话摘要用的），
        # 组合接口的正文是多段说明，这里直接按原文分行渲染。
        for line in docstring_body(cls, method):
            out += [esc(line) if not line.startswith("``") else line, ""]
        params = method_params(cls, method)
        if params:
            out += ["| 参数 | 类型 | 必填 | 默认 | 说明 |", "|---|---|---|---|---|"]
            for p in params:
                dflt = f"`{p.default}`" if p.default is not None else "—"
                out.append(f"| `{p.name}` | {p.json_type} | "
                           f"{'是' if p.required else '否'} | {dflt} | {esc(p.desc) or '—'} |")
            out.append("")
    examples = COMPOSITE_EXAMPLES.get(ns) or []
    if examples:
        out += ["**示例**", "", "```python"]
        out += examples
        out += ["```", ""]
    return out


def futures_section() -> list[str]:
    """期货章：$FUT_* 指标码专题（数据在 mkt.futures_kline，管线已在生产）。"""
    rows = [m for m in CAT.metrics["metrics"] if m["code"].startswith("$FUT")]
    out = [
        "期货数据走**指标码层**：主力连续 K 线指标（日/周/月三族），经 `cli.indicator` 取数。",
        "",
        "调用姿势（指标实现引用期间上下文，`symbol` 传任意 A 股代码即可；合约键经"
        " `fut_symbol` 指定，国内带市场前缀、后缀不是 .CZCE；外盘为 `global.` 前缀的 V2 键；"
        "eval 引擎须为 cn 客户端）：",
        "",
        "```python",
        'cli.indicator.get("600519", "$FUT_CLOSE")                          # 缺省合约 cn.SR.ZCE',
        'cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="cn.RB.SHF")  # 上期所螺纹钢主力',
        'cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="global.CL")  # 外盘 WTI 原油',
        "```",
        "",
        "| 指标代码 | 中文 | 市场 |", "|---|---|---|",
    ]
    for m in rows:
        out.append(f"| `{m['code']}` | {esc(m.get('cn', ''))} | "
                   f"{'/'.join(m.get('markets') or []) or '—'} |")
    out += ["", "量纲：价=报价单位（元/吨等随品种）、volume/oi=手、amount=万元（原生口径）。", ""]
    return out


def etf_note() -> list[str]:
    """A 股行情章内的场内 ETF 说明（ETF 日K与个股同构，无分钟线）。"""
    return [
        "### 场内 ETF 说明",
        "",
        "ETF 日 K 与个股同构：`cli.kline.bars(\"510300\", n=30)`；`cli.kline.is_etf(...)` "
        "判别场内基金。ETF 无分时/分钟源（`min1`/`live` 会被拦截），盘中取数用 "
        "`cli.kline.snapshot`。",
        "",
    ]


def metric_groups_lines(doc: dict) -> list[str]:
    curated = sum(len(g.get("metrics") or []) for g in doc.get("metric_groups") or [])
    lines: list[str] = [
        f"> 指标码全量 {CAT.stats()['metric_catalog_total']} 个：按数据类型分章的全量导航见"
        f" [INDICATORS.md](INDICATORS.md)（生成物）；本节为精选 {curated} 码。",
        "",
    ]
    for g in doc.get("metric_groups") or []:
        lines.append(f"#### 指标组 {g['cn']}（{g['id']}）")
        lines.append(f"{esc(g['caliber'])}" + (f"（单位 {esc(g['unit'])}）" if g.get("unit") else ""))
        lines.append("")
        lines += ["| 指标代码 | 中文名 | 量级守护 |", "|---|---|---|"]
        for m in g.get("metrics") or []:
            guard = ""
            if m.get("unit") or m.get("range"):
                unit = UNIT_CN.get(m.get("unit", ""), "")
                rng = f"范围 {m['range'][0]}…{m['range'][1]}" if m.get("range") else ""
                guard = " · ".join(x for x in (unit, rng) if x)
            lines.append(f"| `{m['code']}` | {esc(m.get('cn', ''))} | {guard} |")
        lines.append("")
    return lines


def render_domain(doc: dict) -> list[str]:
    """附录域节：域合同（描述/单位/notes）+ 底层函数表（不含指标组，其在文档主体）。"""
    kind = doc["kind"]
    lines = [
        f"#### {doc['cn']}（`{doc['id']}`）",
        "",
        f"**性质**：{KIND_CN.get(kind, kind)} · **版本**：{doc['version']}  ",
        f"{esc(doc['description']).strip()}",
    ]
    if doc.get("data_origin"):
        lines.append(f"数据来源：{'、'.join(doc['data_origin'])}。")
    if doc.get("units"):
        lines.append("单位口径：" + "；".join(f"{k}={esc(v)}" for k, v in doc["units"].items()) + "。")
    for n in doc.get("notes") or []:
        lines.append(f"- {esc(n)}")
    lines.append("")

    fns = [f for f in (doc.get("functions") or []) if not doc_hidden(f)]
    if fns:
        lines += ["| 函数 | 中文 | 性质 | 层 | 参数 | 返回 | 单位与守护 |",
                  "|---|---|---|---|---|---|---|"]
        for fn in fns:
            inv = INV.get(fn["name"], {})
            k = fn.get("kind") or kind
            ex = sdk_example(fn, inv)
            shape = None
            # 附录只对规范化函数与显式 shape_ref 展开字段，避免无关大 shape 膨胀。
            if fn.get("normalize_with") or (fn.get("returns") or {}).get("shape_ref") == "inventory":
                try:
                    shape = CAT.function(fn["name"]).get("returns_shape")
                except Exception:
                    shape = None
            status = f" ({fn['status']})" if fn.get("status") and fn["status"] != "stable" else ""
            lines.append(
                f"| `{fn['name']}` | {esc(fn['cn'])} | {KIND_CN.get(k, k)} | {fn['layer']}{status} | "
                f"{fmt_params(fn, inv)} | {fmt_returns(fn, inv, shape=shape)} | {fmt_guards(fn)} |"
                + (f" 例：`{esc(ex)}`" if ex else ""))
        lines.append("")
        hidden_n = len(doc.get("functions") or []) - len(fns)
        if hidden_n:
            lines.append(f"> 另有 {hidden_n} 个索引/内部辅助函数未列入本文档，仍可经 `cli.call(...)` 调用。")
            lines.append("")
    return lines


def client_batch_section(total_fn: int) -> list[str]:
    """Client 批量方法章：签名随源码实时取，天然不漂移。"""
    import inspect

    from wmshare.client import Client

    def sig(name: str) -> str:
        src = inspect.signature(getattr(Client, name))
        parts = []
        for p in list(src.parameters.values())[1:]:  # 跳过 self
            ann = p.annotation if p.annotation is not inspect.Parameter.empty else "any"
            ann = getattr(ann, "__name__", str(ann).replace("typing.", ""))
            piece = f"{p.name}: {ann}"
            if p.default is not inspect.Parameter.empty:
                piece += f" = {p.default!r}"
            parts.append(piece)
        return ", ".join(parts)

    rows = [
        ("`cli.call(name, sym, …)`", "单标的按目录合同调用；symbol 传 list 自动转批量"),
        ("`cli.call_batch(name, symbols, on_error='raise')`",
         "单批（≤500）：一次 HTTP 返回 {symbol: 结果}；on_error 为**票级**，勿做容错"),
        ("`cli.batch_iter(name, symbols, batch_size=500, on_batch_error='raise')`",
         "逐批流式：⌈N/batch_size⌉ 次请求，逐批 yield BatchResult（可进度/中断/落盘）"),
        ("`cli.batch_all(name, symbols, batch_size=500, on_batch_error='raise')`",
         "一站式分批聚合：请求次数 = ⌈N/batch_size⌉；to_df() 出带 symbol 列的长表"),
    ]
    out = [
        "## Client 方法（批量取数）",
        "",
        "服务端按**请求次数**限流（免费档 500 次/小时、5,000 次/日）：逐票取全市场"
        "（A 股 5,691 家）必撞 429，批量把请求次数压到 ⌈N/batch_size⌉。",
        "",
        "| 方法 | 说明 |",
        "|---|---|",
    ]
    out += [f"| {m} | {d} |" for m, d in rows]
    out += [
        "",
        "**三原则**：① 批次只能同一市场（跨市场混批 SDK 直接报错）；② 容错用批级"
        '`on_batch_error="skip"`（跳过失败批继续），**不要**用 `call_batch(on_error="skip")`'
        "——它是票级逐票请求，会放大请求数正好制造 429；③ 单批撞 `CALC_LIMIT_EXCEEDED`"
        "（算力超限）减小 `batch_size`，遇 429 停止并按消息里的 `codes[done:]` 续跑。",
        "",
        f"**指标码不是批量 `name`**：`name` 必须是目录函数名（{total_fn} 个，如 `kline.snapshot`），"
        "传 `indicator.get` 会报 CatalogError。一票多码用 `cli.indicator.metrics(sym, codes)`；"
        "全市场指标码没有批量入口，需逐票调用（指标取数是按 `(标的, 码)` 寻址，不是按标的切片）。",
        "",
        "```python",
        'codes = [r["symbol"] for r in cli.stocks.list()]      # 全市场代码池（A 股 5,691 家）',
        'res = cli.batch_all("kline.snapshot", codes)          # 12 次请求，不是 5,691 次',
        "print(len(res.results), res.requests)                  # 5691 12",
        "",
        'df = cli.batch_all("kline.snapshot", ["600519", "000001"]).to_df()   # 需 pandas',
        "```",
        "",
        "长任务用 `for part in cli.batch_iter(name, codes): …` 逐批落盘；429 时异常消息"
        "自带 `codes[done:]` 续跑位置。各方法完整签名（随源码生成）：",
        "",
    ]
    out += [f"- `{name}({sig(name)})`" for name in
            ("call", "call_batch", "batch_iter", "batch_all")]
    out += ["", "长任务也可用 `cli.notice_poller(...)` 订阅公告变更（见 GUIDE 第 8 章）。", ""]
    return out


def overview_table(docs: list[dict]) -> list[str]:
    """能力总览：数据域｜核心能力（L0 中文名）｜单位口径——全部取自目录，防编造。"""
    out = ["| 数据域 | 核心能力 | 单位口径 |", "|---|---|---|"]
    for d in sorted(docs, key=lambda x: (CATEGORY_ORDER.index(x["category"]), x["id"])):
        l0 = [f["cn"] for f in (d.get("functions") or []) if f.get("layer") == "L0"]
        if l0:
            capability = "、".join(l0[:5]) + ("…" if len(l0) > 5 else "")
        elif d.get("metric_groups"):
            capability = "指标组：" + "、".join(g["cn"] for g in d["metric_groups"][:5]) + "…"
        else:
            capability = "公司档案：名称/行业/组织类型/上市日期"
        units = "；".join(f"{k}={v}" for k, v in (d.get("units") or {}).items()) or "—"
        out.append(f"| `{d['id']}`（{d['cn']}） | {esc(capability)} | {esc(units)} |")
    out.append("")
    return out


def build() -> str:
    docs = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(DOMAINS.glob("*.yaml"))]
    total_fn = sum(len(d.get("functions") or []) for d in docs)
    total_groups = sum(len(d.get("metric_groups") or []) for d in docs)
    metric_count = json.loads(
        (catalog_dir() / "generated" / "metrics.json").read_text(encoding="utf-8"))["count"]
    by_cat = {cat: sorted((x for x in docs if x["category"] == cat), key=lambda x: x["id"])
              for cat in CATEGORY_ORDER}
    merged = {fn["name"]: fn for d in docs for fn in (d.get("functions") or [])}

    # 分章完备性：FRIENDLY_INDEX 每个 ns 恰好归入一章，防漂移漏收；
    # 纯组合命名空间（无核心接口，如 backtest）允许只挂在组合小节。
    chapter_ns = [ns for _, nss in CHAPTERS for ns in nss]
    index_ns = {ns for _, ns, _, _, _ in FRIENDLY_INDEX}
    composite_ns = {ns for ns, methods in COMPOSITE_METHODS.items() if methods}
    assert len(chapter_ns) == len(set(chapter_ns)), "CHAPTERS 命名空间重复"
    assert index_ns <= set(chapter_ns), f"未归章命名空间：{sorted(index_ns - set(chapter_ns))}"
    assert set(chapter_ns) - index_ns <= composite_ns, \
        f"章节含无核心接口的命名空间：{sorted(set(chapter_ns) - index_ns - composite_ns)}"
    by_chapter: dict[str, list[tuple]] = {title: [] for title, _ in CHAPTERS}
    ns_chapter = {ns: title for title, nss in CHAPTERS for ns in nss}
    for r in FRIENDLY_INDEX:
        by_chapter[ns_chapter[r[1]]].append(r)

    out = [
        "# API 参考",
        "",
        "<!-- GENERATED by tools/gen_api_docs.py — do not hand-edit -->",
        "",
        f"共 **{len(docs)}** 个数据域 · **{len(FRIENDLY_INDEX)}** 个核心接口 · "
        f"**{total_groups}** 个指标组（指标目录全量 {metric_count} 个指标代码）；"
        f"全量 {total_fn} 个底层函数见文末折叠附录。核心接口按资产类别分章，"
        "每接口一节（输入参数 / 输出字段 / 示例）。",
        "",
        "## 能力总览",
        "",
        "- **额度**：开放平台账号自带免费档额度（500 次/小时、5,000 次/日），"
        "更高额度与条款以开放平台为准。",
        "- **凭证即用**：在开放平台获取 client_id/api-key，"
        "构造参数 / `WMSHARE_*` 环境变量 / `~/.wmshare/credentials.env` 任一配置即可调用核心接口。",
        "- **认证与限流**：401/403 抛 `AuthError`，429 抛 `LimitError(code=\"rate_limited\")`；"
        "错误消息即完整指引——附有申请自己的 AppID 的步骤与配置方法。",
        "- **目录随包、离线可查**：全部函数与指标代码随 wheel 分发；命名空间带类型签名"
        "（`py.typed`），IDE 直接补全。",
        "- **单位统一 + 数据守护**：返回值统一基础单位（比率/涨跌幅=小数、金额/市值=元、"
        "A 股成交量=股）；每次返回前按目录声明做量级守护与关系不变量校验，违例抛 "
        "`DataError` 而非交给你错误量级的数据。取原始口径：`_raw=True`（上游原始行）、"
        "`_units=\"native\"`（保留上游原单位）、`Client(validate=False)`（关校验留换算）。",
        "",
    ]
    out += overview_table(docs)
    out += [
        "性质标注：**原始数据** = 披露/直采数据（含外部源算好的）；**指标** = 平台公式计算的派生指标。",
        "",
        "参数统一 `symbol`（6 位裸码）。机器可读合同：[openapi.json](openapi.json) · "
        "交互浏览：[swagger.html](swagger.html) · 完整优势与口径说明见 "
        "[README](../README.md)。",
        "",
        "| 分类 | 数据域 |", "|---|---|",
    ]
    for cat in CATEGORY_ORDER:
        cells = ", ".join(f"`{d['id']}`（{d['cn']}）" for d in by_cat[cat])
        out.append(f"| **{CATEGORY_CN[cat]}** | {cells} |")
    out += [
        "",
        "## 数据目录（离线）",
        "",
        "目录随包分发、纯本地读取（零网络）：",
        "",
        "```python",
        "import wmshare",
        "",
        "cat = wmshare.load()          # 数据目录对象（离线，不产生任何请求）",
        "hits = cat.search(\"股息\")     # 跨函数 + 指标代码混合检索（默认返回 ≤20 条）",
        "cat.function(\"bonus.snapshot_yield_ttm\")[\"params\"]   # 函数合同：参数/返回/示例",
        "```",
        "",
        "| 方法 | 说明 |", "|---|---|",
        f"| `cat.function(name)` | 函数合同：params / returns_shape / 单位与守护声明 / 示例 |",
        "| `cat.domain(id)` | 域合同：描述 / 单位口径 / notes |",
        "| `cat.metric(code)` | 指标条目（精选组带单位与守护声明） |",
        "| `cat.metric_meta(code)` | 精选指标的单位换算 / 量级守护声明 |",
        "| `cat.metric_groups()` | 全部指标组摘要（id / cn / 数量） |",
        "| `cat.metrics_in_group(group)` | 组内全部精选指标 |",
        f"| `cat.search(query, kind=, limit=)` | 函数 + 指标混合检索（kind: all/function/metric） |",
        "| `cat.functions_by_domain()` | 域 → 函数名清单 |",
        "| `cat.namespaces()` | 全部 XS 命名空间 |",
        "| `cat.inventory_params(name)` | 底层签名参数（L1 精简条目兜底） |",
        "| `cat.stats()` | 域 / 函数 / 指标计数与 upstream rev |",
        "",
    ]
    out += client_batch_section(total_fn)
    out += [
        "---",
        "",
        "# 核心接口参考（按资产类别）",
        "",
    ]

    for title, nss in CHAPTERS:
        out.append(f"## {title}")
        out.append("")
        if title == "期货":
            out += futures_section()
            continue
        for ns in nss:
            rows = [r for r in by_chapter[title] if r[1] == ns]
            if not rows and not COMPOSITE_METHODS.get(ns):
                continue
            out += [f"### {ns_title(ns)}（`cli.{ns}`）", ""]
            for _, ns_, method, cn, underlying in rows:
                out += interface_block(ns_, method, cn, underlying, merged)
            out += composite_section(ns)
            if ns == "kline":
                out += etf_note()
        if title == "港股与美股":
            out += [
                "### 多市场切换",
                "",
                "`Client(market=\"cn\" | \"hk\" | \"us\")` 决定数据市场：A 股 6 位裸码、"
                "港股 5 位、美股裸字母码（`AAPL.O` 等交易所后缀自动归一）；跨市场混批"
                "显式报错。港美股行情（K 线/快照/盘中）走 `cli.kline`，本页 intl 为港美"
                "**专域披露**（CCASS/沽空/评级等）。",
                "",
            ]
        metric_cats = CHAPTER_METRIC_CATEGORIES.get(title)
        if metric_cats:
            groups = [d for d in docs if d.get("category") in metric_cats and d.get("metric_groups")]
            if groups:
                out += ["---", ""]
                for d in groups:
                    out += metric_groups_lines(d)

    out += [
        "## 附录：全量底层函数目录（进阶）",
        "",
        "底层函数经 `cli.call(\"ns.fn\", ...)` 调用（友好层未覆盖的命名空间有类型化门面，"
        "如 `cli.bonus.query_list(...)`）；单位口径与域说明随域列出。",
        "",
        "<details>",
        "<summary><b>展开全量底层函数目录</b></summary>",
        "",
    ]
    for cat in CATEGORY_ORDER:
        out.append(f"### {CATEGORY_CN[cat]}")
        out.append("")
        for d in by_cat[cat]:
            out += render_domain(d)
    out += ["</details>", ""]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    body = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != body:
            print("gen_api_docs drift: docs/API.md", file=sys.stderr)
            return 1
        print("gen_api_docs ok")
        return 0
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
