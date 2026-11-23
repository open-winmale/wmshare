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
import math
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _introspect import (  # noqa: E402
    COMPOSITE_EXAMPLES, COMPOSITE_NOTES, EXAMPLE_VALUES, FALLBACK_RETURNS,
    METHOD_EXAMPLE_VALUES, RETURNS_OVERRIDES, SYMBOL_EXAMPLES, field_cn,
    is_internal_catalog_name, method_doc, method_example, method_params,
    return_shape_for, underlying_fn,
)
from wmshare.api import (  # noqa: E402
    COMPOSITE_METHODS, DOC_META, FRIENDLY_INDEX, FRIENDLY_NAMESPACES)
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
    ("A 股行情与选股", ["kline", "screener", "backtest", "moneyflow", "margin", "calendar", "stocks", "toplist"]),
    ("可转债", ["cbond"]),
    ("指数", ["index"]),
    ("期货", ["futures"]),  # 2.0：连续合约快照门面（$FUT_* 指标码求值封装）
    ("宏观", ["macro"]),
    ("财务基本面", ["statements", "segments", "valuation", "estimates", "indicator"]),
    ("信息披露与公司行动", ["notice", "filings", "pdf_doc", "forecast", "dividend", "equity", "workout"]),
    ("港股与美股", ["intl"]),
    ("基金与 ETF", ["etf"]),  # 组合门面（无核心接口），读 skillhub etf_build 九视图
    ("参考数据", ["info"]),
]
# 指标组挂靠章：该 category 的域（fund.indicators）指标组渲染在章内接口之后
CHAPTER_METRIC_CATEGORIES: dict[str, list[str]] = {"财务基本面": ["fundamentals"]}

# 友好层参数说明兜底表（docstring 未写 :param 的高频参数；其余落「—」）
PARAM_DOCS: dict[str, str] = {
    "symbol": "6 位裸码（自动归一前缀/后缀；港股 5 位、美股字母码）",
    "n": "根数",
    "limit": "返回条数上限",
    "begin": "开始日期 YYYY-MM-DD（含端点）",
    "end": "结束日期 YYYY-MM-DD（含端点）",
    "window": "窗口（\"7d\"/\"1m\"/…/\"5y\" 或天数）",
    "keyword": "标题/类型正则（可空）",
    "top_n": "只取前 N 条",
    "sort_by": "排序字段",
    "years": "最近 N 个报告期",
    "idx": "宽度索引（None=服务端解析全市场）",
    "points": "采样点数",
    "mode": "返回模式（\"latest\"=最新一条 / \"series\"=序列；ETF 九视图共用）",
    "kind": "报告类型（all | annual | semi | quarter）",
    "date": "日期 YYYY-MM-DD（也接受 YYYYMMDD 与 date/datetime）",
    "category": "公告类别（如 \"回购\"/\"减持\"）",
    "min_yield": "股息率门槛（小数，0.04=4%）",
    "min_pct": "估值分位门槛（0~1 小数）",
    "fut_symbol": "期货连续合约键（如 \"cn.RB.SHF\"；$FUT_* 需要）",
    "native": "True=保留上游原生单位（默认换算基础单位）",
    "codes": "指标码列表（$ 开头）",
    "skip": "翻页跳过条数",
    "url": "公告 PDF 原文链接（与 file_key 至少给一个）",
    "file_key": "文档键（search 返回行的 file_key 字段）",
    "source_url": "原文链接（与 file_key 至少给一个）",
}

# 按 ns 覆写兜底表：仅 A 股数据的门面，symbol 不得宣传港美（真多市场门面
# kline/notice/intl/stocks/info/indicator 不在表内——indicator 明确支持美股
# 标的与 $FUT_* 期货码；etf 为 A 股场内基金，statements/valuation 为 A 股报表
# 与每日估值）。
PARAM_DOCS_CN_ONLY: dict[str, dict[str, str]] = {
    ns: {"symbol": "6 位 A 股裸码（自动归一前缀/后缀）"}
    for ns in ("margin", "moneyflow", "screener", "dividend", "equity",
               "filings", "forecast", "segments", "estimates", "workout",
               "cbond", "backtest", "index", "macro",
               "etf", "valuation", "statements")
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
                + (f"（{field_cn(f)}）" if field_cn(f) else "")
                for f in fields)
            desc += "；字段 " + detail
    return esc(desc)


def doc_hidden(fn: dict) -> bool:
    """脚本专用/内部辅助函数不进公开文档（保留在目录中，cli.call 仍可调）。"""
    if fn.get("status") == "internal":
        return True
    name = fn["name"]
    if is_internal_catalog_name(name):
        return True  # 内部命名空间：用户侧只见友好门面 cli.statements.*
    short = name.split(".", 1)[-1]
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


def ns_notes(ns: str) -> list[str]:
    """命名空间节头注记：类 docstring 正文（去首句标题行与 :param 行）。

    边界/可用性说明写在类 docstring 里即自动流进正文节头——生成器单一事实
    源，正文与附录（域 yaml notes）两处口径同源。docstring 硬换行按段并行。
    """
    import re as _re
    doc = inspect.getdoc(FRIENDLY_NAMESPACES[ns]) or ""
    paras: list[str] = []
    buf: list[str] = []
    in_bullet = False  # 上一弹点是否待续行（硬换行的条目内容并入该弹点）
    for ln in doc.strip().splitlines()[1:]:
        t = ln.strip()
        if not t or t.startswith(":param"):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            in_bullet = False
            continue
        if t.startswith("- "):  # 条目行各自成弹点（边界/约定清单）
            if buf:
                paras.append(" ".join(buf))
                buf = []
            paras.append(t[2:])
            in_bullet = True
            continue
        if in_bullet and paras:
            paras[-1] += t  # 条目续行（docstring 79 列硬换行）
            continue
        buf.append(t)
    if buf:
        paras.append(" ".join(buf))
    return [_re.sub(r"``([^`]+)``", r"`\1`", p) for p in paras]


# ---------------------------------------------------------------- 每接口小节
# 友好层参数名 → 目录合同参数名的别名（目录里多为 sym/stk/code/stock_code，
# 名字对不上会让目录真值永远输给通用兜底——曾致「港股 5 位、美股字母码」
# 一句兜底文案铺满仅 A 股门面的系统性误导）。
_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("sym", "stk", "code", "stock_code"),
}


def _param_desc(ns: str, method: str, p, fn: dict) -> str:
    """参数说明：友好层 docstring :param → 目录同名（含别名）参数 desc → 按 ns 覆写兜底 → 通用兜底表 → —。"""
    if getattr(p, "desc", ""):
        return esc(p.desc)
    names = (p.name,) + _PARAM_ALIASES.get(p.name, ())
    for cp in fn.get("params") or []:
        if cp.get("name") in names and cp.get("desc"):
            return esc(cp["desc"])
    ov = PARAM_DOCS_CN_ONLY.get(ns, {}).get(p.name)
    if ov:
        return ov
    return PARAM_DOCS.get(p.name, "—")


# 单位 token → 中文口径（与 units.yaml CONVERSIONS 词表一致；新增 token 由
# validate_units 在前置门禁拦截，本表只负责渲染）。
UNIT_CN: dict[str, str] = {
    "percent": "百分数→小数",
    "yi_yuan": "亿元→元",
    "lot": "手→股",
}


def _field_unit(fn: dict, name: str) -> str:
    tok = (fn.get("units") or {}).get(name)
    return UNIT_CN.get(tok, esc(tok)) if tok else "—"


def _field_range(fn: dict, name: str) -> str:
    rng = (fn.get("ranges") or {}).get(name)
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        return "—"
    return f"[{rng[0]:g}, {rng[1]:g}]"


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
        guarded = bool(fn.get("units") or fn.get("ranges"))
        if guarded:
            out += ["**输出字段**", "",
                    "| 字段 | 类型 | 单位/换算 | 守护范围 | 说明 |",
                    "|---|---|---|---|---|"]
        else:
            out += ["**输出字段**", "",
                    "| 字段 | 类型 | 说明 |", "|---|---|---|"]
        for f in fields:
            t = TYPE_SHORT.get(f.get("type", "any"), f.get("type", "any"))
            if f.get("optional"):
                t += "?"
            if guarded:
                out.append(f"| `{f['name']}` | {t} | {_field_unit(fn, f['name'])} "
                           f"| {_field_range(fn, f['name'])} "
                           f"| {esc(field_cn(f)) or '—'} |")
            else:
                out.append(f"| `{f['name']}` | {t} | {esc(field_cn(f)) or '—'} |")
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
                # 组合接口同样不许参数说明落 `—`（PARAM_DOCS 兜底与核心接口一致）
                desc = esc(p.desc) or PARAM_DOCS.get(p.name, "—")
                out.append(f"| `{p.name}` | {p.json_type} | "
                           f"{'是' if p.required else '否'} | {dflt} | {desc} |")
            out.append("")
    examples = COMPOSITE_EXAMPLES.get(ns) or []
    if examples:
        out += ["**示例**", "", "```python"]
        out += examples
        out += ["```", ""]
    return out


def futures_section() -> list[str]:
    """期货章：cli.futures 门面（2.0 新面）+ $FUT_* 指标码专题。"""
    rows = [m for m in CAT.metrics["metrics"] if m["code"].startswith("$FUT")]
    out = [
        "**2.0 新面** `cli.futures`：连续合约快照门面（锚定已内部封装，只需 `fut_code`；"
        "须 cn 客户端；量=手、金额=万元为期货原生口径）：",
        "",
        "```python",
        'cli.futures.snapshot("RB.SHF")                 # 日频 11 字段（open/close/volume(手)…）',
        'cli.futures.get("global.CL", "close")          # 外盘 WTI 收盘价',
        'cli.futures.snapshot("cn.SR.ZCE", freq="w")    # 周频 8 字段',
        "```",
        "",
        "指标码层等价形态（1.x 兼容姿势；`symbol` 传任意 A 股代码锚定）：",
        "",
        "```python",
        'cli.indicator.get("600519", "$FUT_CLOSE")                          # 缺省合约 cn.SR.ZCE',
        'cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="cn.RB.SHF")  # 上期所螺纹钢主力',
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
    import wmshare

    # 全市场代码池随包增长：批量请求数动态派生，杜绝「5,691 家 / 12 次」硬编码漂移。
    n_cn = wmshare.load().stats()["symbols"]["cn"]
    batches = math.ceil(n_cn / 500)

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
        f"（A 股 {n_cn:,} 家）必撞 429，批量把请求次数压到 ⌈N/batch_size⌉。",
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
        f'codes = [r["symbol"] for r in cli.stocks.list()]      # 全市场代码池（A 股 {n_cn:,} 家）',
        f'res = cli.batch_all("kline.snapshot", codes)          # {batches} 次请求，不是 {n_cn} 次',
        f"print(len(res.results), res.requests)                  # {n_cn} {batches}",
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
        "- **字段表口径**：输出字段说明中的量/市值一律按 SDK 换算后口径（量=股、市值=元）；"
        "上游原生口径只在 `_units=\"native\"` / `_raw=True` 下可见。"
        "逐函数声明见函数合同的「单位与守护声明」列，机器可读版见 "
        "[fields.json](fields.json)（字段/类型/单位/守护范围）与 "
        "[openapi.json](openapi.json) 的 `x-wmshare-guards`。",
        "- **指标码中文名**：指标清单里的「期货持仓量(手)」等是上游原生口径的**命名**，"
        "不代表 SDK 返回值单位；返回值一律以上述基础单位与逐函数声明为准。",
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
            # 2.0：cli.futures 门面接口小节（与 FRIENDLY_INDEX 一一对应）
            for ns in nss:
                rows = [r for r in by_chapter[title] if r[1] == ns]
                if not rows:
                    continue
                out += [f"### {ns_title(ns)}（`cli.{ns}`）", ""]
                notes = ns_notes(ns)
                for note in notes:
                    out += [f"- {note}"]
                out += [""]
                for _, ns_, method, cn, underlying in rows:
                    out += interface_block(ns_, method, cn, underlying, merged)
            continue
        for ns in nss:
            rows = [r for r in by_chapter[title] if r[1] == ns]
            if not rows and not COMPOSITE_METHODS.get(ns):
                continue
            out += [f"### {ns_title(ns)}（`cli.{ns}`）", ""]
            notes = ns_notes(ns)
            if notes:
                for note in notes:
                    out += [f"- {note}"]
                out += [""]
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


FIELDS_OUT = REPO / "docs" / "fields.json"


def _shape_fields(name: str) -> list[dict]:
    """inventory returns_shape → 字段字典行（无 shape 返回空表）。"""
    sh = (INV.get(name) or {}).get("returns_shape") or {}
    items = sh.get("items") if isinstance(sh.get("items"), dict) else sh
    out: list[dict] = []
    for f in (items or {}).get("fields") or []:
        if not f.get("name"):
            continue
        out.append({
            "name": f["name"],
            "type": f.get("type", "any"),
            "optional": bool(f.get("optional")),
            "desc": field_cn(f) or "",
        })
    return out


def build_fields_json() -> str:
    """机器可读字段字典：**公开**目录函数 × 返回字段/单位/守护范围。

    内部函数（``internal: true``，如 fmt_*/rptdom.*）不收录——它们不是对外合同，
    且 ``tests/test_internal_ns_visibility`` 会拦截内部命名空间出现在 docs/。
    数据全部来自离线目录（domains/*.yaml + generated/inventory.json），
    与 API.md 的输出字段表同源；供 MCP resource / 文档站点消费。
    """
    docs = [yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(DOMAINS.glob("*.yaml"))]
    domains: list[dict] = []
    total = 0
    for d in docs:
        fns: list[dict] = []
        for fn in d.get("functions") or []:
            name = fn.get("name")
            if not name:
                continue
            if fn.get("internal") or is_internal_catalog_name(name):
                # 内部函数/内部命名空间（rptdom 等）不得出现在对外资产里：
                # tests/test_internal_ns_visibility 会扫 docs/ 全部文件。
                continue
            units = fn.get("units") or {}
            ranges = fn.get("ranges") or {}
            fields = _shape_fields(name)
            for f in fields:
                if f["name"] in units:
                    tok = units[f["name"]]
                    f["unit"] = UNIT_CN.get(tok, tok)
                if f["name"] in ranges:
                    rng = ranges[f["name"]]
                    if isinstance(rng, (list, tuple)) and len(rng) == 2:
                        f["range"] = [rng[0], rng[1]]
            fns.append({
                "name": name,
                "cn": fn.get("cn") or "",
                "layer": fn.get("layer") or "",
                "internal": bool(fn.get("internal")),
                "units": units,
                "ranges": ranges,
                "checks": fn.get("checks") or [],
                "fields": fields,
            })
            total += 1
        domains.append({
            "id": d.get("id"),
            "kind": d.get("kind"),
            "data_origin": d.get("data_origin") or [],
            "functions": fns,
        })
    payload = {
        "schema_version": 1,
        "generated_by": "tools/gen_api_docs.py",
        "count": total,
        "domains": domains,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# api_pack.json：逐接口介绍 + 在线测试物料（供开放平台接口文档站消费）
# ---------------------------------------------------------------------------

API_PACK_OUT = REPO / "docs" / "api_pack.json"
API_PACK_SAMPLES = REPO / "docs" / "api_pack_samples.json"
API_PACK_BUDGET = 900_000   # 总量硬预算（字节）：超限即生成失败，防示例响应失控
ROW_CAP = 10              # 每接口示例响应最多保留行数
TEXT_CAP = 400             # 字符串字段截断长度（如公告 PDF 正文）
SAMPLE_ROW_CAP = 6          # 真实拍摄响应保留行数（更紧，控制体积）
SAMPLE_TEXT_CAP = 200


class _CaptureSession:
    """离线传输桩：记录 ``/v1/analysis/xs/eval`` 请求体，响应恒为空结果。

    与 tests/test_docs.FakeSession 同构，但目的不同：这里不是为了执行，
    而是让门面真实走一遍生产编译链（``_build_call_line`` + ``normalize_with``
    + require 头 + symbol 锚点），把**与 SDK 逐字等价**的 eval 请求体捕获进
    api_pack——开放平台接口文档的「一键测试」按钮据此直接打网关。
    """

    def __init__(self) -> None:
        self.headers: dict = {}
        self.eval_bodies: list[dict] = []

    def post(self, url: str, json: dict | None = None, data: object = None,
             headers: dict | None = None, timeout: object = None):  # noqa: A002
        if url.endswith("/v1/oauth/token"):
            payload: dict = {"data": {"access_token": "capture", "expires_in": 3600}}
        else:
            self.eval_bodies.append(dict(json or {}))
            payload = {"success": True, "data": {"result": []}}

        class _Resp:
            status_code = 200
            text = ""
            headers: dict = {}

            def json(self) -> dict:
                return payload

        return _Resp()


_CAPTURE_CLI: object | None = None


def _capture_client() -> object:
    """构造只用于编译捕获的 Client（哑凭证 + 记录桩，全程不发真实请求）。"""
    global _CAPTURE_CLI
    if _CAPTURE_CLI is None:
        from wmshare.client import Client
        _CAPTURE_CLI = Client(client_id="gen", client_secret="gen",
                              session=_CaptureSession(), max_limit=None)
    return _CAPTURE_CLI


def _example_kwargs(ns: str, method: str, params: list, minimal: bool) -> dict:
    """按 method_example 同源示例值表构造程序化 kwargs（值经 _py_literal 还原）。

    占位符（``"<…>"``，指向前置查询结果的）与非字面量参数一律省略；省略后
    缺必填参数时由门面调用自然抛错——该尝试按失败计，宁缺毋编。
    """
    values = {**EXAMPLE_VALUES, **METHOD_EXAMPLE_VALUES.get((ns, method), {})}
    kwargs: dict = {}
    for p in params:
        if p.name == "symbol":
            kwargs[p.name] = SYMBOL_EXAMPLES.get(ns, '"600519"').strip('"')
            continue
        raw = values.get(p.name)
        if raw is None or (minimal and not p.required):
            continue
        v = _py_literal(raw)
        if v is None:
            continue
        if isinstance(v, str) and "<" in v and ">" in v:
            continue  # 占位符不能当真实参数下发
        kwargs[p.name] = v
    return kwargs


def _attempt_kwargs_list(ns: str, method: str, params: list) -> list[dict]:
    """两组尝试参数：完整示例参数 → 最小参数（symbol + 必填）。

    第二组兜底「示例参数里含演示快照不支持的可选项」（如 kline.bars 的
    adj/begin/end）：测试 payload 用完整组，演示快照捕获可落最小组。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for kw in (_example_kwargs(ns, method, params, minimal=False),
               _example_kwargs(ns, method, params, minimal=True)):
        key = json.dumps(kw, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            out.append(kw)
    return out


def _payload_usable(body: dict) -> bool:
    """编译出的 eval 体是否对一键测试有用。

    三类判废（均显式置 null，不做半成品 payload）：
    - 锚点为空 / 空串占位实参（``pdf_doc.read_markdown("", …)``）：发到网关
      只会报错；
    - 引用内部目录命名空间（``xs.require("sys/rptdom/init.xs")`` 等）：生产
      等价 payload 必然含 require 行，但 tests/test_internal_ns_visibility
      禁止内部命名空间出现在 docs/——此类接口 test 置 null，UI 降级
      「到 Playground 自测」。
    """
    if not str(body.get("symbol") or "").strip():
        return False
    for ln in body.get("xs_lines") or []:
        if re.search(r"[(,]\s*\"\"", ln):
            return False
        m = re.match(r'xs\.require\("sys/([a-z0-9_]+)/', ln)
        if m and is_internal_catalog_name(f"{m.group(1)}.x"):
            return False
        for name in re.findall(r"\b([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\(", ln):
            if is_internal_catalog_name(name):
                return False
    return True


def _capture_eval_payload(ns: str, method: str, attempts: list[dict]) -> dict | None:
    """门面真实编译 → 捕获单次 eval 请求体；不可单次回放（组合链路）显式 None。"""
    cli = _capture_client()
    sess = cli.session  # type: ignore[attr-defined]
    for kw in attempts:
        sess.eval_bodies.clear()
        fn = getattr(getattr(cli, ns), method)
        try:
            fn(**kw)
        except Exception:
            pass  # 空桩响应下的后续整形可能报错；请求体已捕获即为有效
        if len(sess.eval_bodies) == 1:
            body = sess.eval_bodies[0]
            if not _payload_usable(body):
                continue
            return {"kwargs": kw, "path": "/v1/analysis/xs/eval", "body": body}
        if len(sess.eval_bodies) > 1:
            break  # 组合链路多次 eval：PlaygroundRun 单次代理无法一键回放
    return None


def _json_safe(v: object, depth: int = 0,
               row_cap: int = ROW_CAP, text_cap: int = TEXT_CAP) -> object:
    """示例响应行 → 可序列化 JSON：NaN/Inf→None、长文本截断、行数封顶。

    行列表取**尾部** row_cap 行——SDK 契约是 date 升序(旧→新),头部是最旧行,
    文档示例与新鲜度审计都要最新行。
    """
    if depth > 6:
        return str(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, str) and len(v) > text_cap:
        return v[:text_cap] + f"…(截断，原长 {len(v)})"
    if isinstance(v, dict):
        return {str(k): _json_safe(x, depth + 1, row_cap, text_cap) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x, depth + 1, row_cap, text_cap) for x in v[-row_cap:]]
    if hasattr(v, "to_dict"):  # DataFrame → 行数组
        return [_json_safe(r, depth + 1, row_cap, text_cap)
                for r in v.to_dict("records")[-row_cap:]]
    if hasattr(v, "results"):  # BatchResult → 逐票 MAP
        return _json_safe(dict(v.results), depth + 1, row_cap, text_cap)
    if v is None or isinstance(v, (bool, int, str)):
        return v
    return str(v)


_KIND_PREFIX = {"ARR": "array", "MAP": "object", "标量": "scalar", "数值": "scalar"}


def _pack_fields(fn: dict, fn_key: str) -> list[dict]:
    """返回字段表（TickDB 式两列语义）：字段 + 说明。

    shape 读目录本体（CAT.function），不走 generated/inventory.json——两者在
    returns_shape 上有漂移（inventory 缺新面），目录才是合同事实源。
    单位换算融进说明文字（量（手→股））；可空性与守护范围是内部 QA 机制，
    不进面向用户的文档面（机器合同仍在 fields.json / openapi x-wmshare-guards）。
    """
    try:
        sh = CAT.function(fn_key).get("returns_shape") or {}
    except Exception:
        sh = {}
    items = sh.get("items") if isinstance(sh.get("items"), dict) else sh
    fields = [f for f in (items or {}).get("fields") or [] if f.get("name")]
    units = fn.get("units") or {}
    out = []
    for f in fields:
        desc = field_cn(f) or ""
        tok = units.get(f["name"])
        if tok:
            unit = UNIT_CN.get(tok, tok)
            desc = f"{desc}（{unit}）" if desc else unit
        out.append({"name": f["name"], "desc": desc or "—"})
    return out


def _split_kind_prefix(desc: str) -> tuple[str, str]:
    """剥掉 FALLBACK_RETURNS 的「ARR · / MAP · / 标量 · / 数值 · 」前缀 → (kind, 余文)。"""
    for token, kind in _KIND_PREFIX.items():
        if desc.startswith(f"{token} · "):
            return kind, desc[len(token) + 3:]
    return "text", desc


def _pack_param(p, ns: str, method: str, fn: dict) -> dict:
    """TickDB 式参数行：参数 | 必填 | 说明（默认值融进说明，不设类型列）。"""
    desc = _param_desc(ns, method, p, fn)
    if p.default is not None and p.default != "None" and "默认" not in desc \
            and "可选" not in desc:
        desc = f"{desc}；默认 {p.default}" if desc else f"默认 {p.default}"
    return {"name": p.name, "required": p.required, "desc": desc}


def build_api_pack() -> str:
    """逐接口介绍 + 在线测试物料包 ``docs/api_pack.json``。

    开放平台「接口文档（逐接口介绍 + 在线测试）」的数据源，与 API.md 同源
    同口径（目录 yaml + FRIENDLY_INDEX + 运行时内省），不新增手写文案：

    - ``test``：门面真实编译出的 eval 请求体，站点一键测试与 SDK 调用逐字
      等价；组合链路（多次 eval）或参数不可静态确定时显式 ``null``。
    """
    docs = [yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(DOMAINS.glob("*.yaml"))]
    merged = {fn["name"]: fn for d in docs for fn in (d.get("functions") or [])}
    fn_domain = {fn["name"]: d["id"] for d in docs for fn in (d.get("functions") or [])}
    domain_meta = {d["id"]: d for d in docs}
    ns_chapter = {ns: title for title, nss in CHAPTERS for ns in nss}

    # ns → 域：该 ns 首个核心接口的底层目录函数所属域（与 API.md 域概览同源）；
    # 纯组合命名空间（backtest/etf，无目录函数）domain 显式 null，UI 回退章名。
    ns_domain: dict[str, str | None] = {}
    for _, ns, _, _, underlying in FRIENDLY_INDEX:
        if ns not in ns_domain:
            fk = underlying_fn(underlying)
            ns_domain[ns] = fn_domain.get(fk) if fk else None

    def _entry(ns: str, method: str, cn: str, underlying: str | None,
               composite: bool) -> dict:
        cls = FRIENDLY_NAMESPACES[ns]
        params = method_params(cls, method)
        fn = merged.get(underlying, {}) if underlying else {}
        inv = INV.get(underlying, {}) if underlying else {}
        entry: dict = {
            "key": f"{ns}.{method}",
            "ns": ns,
            "method": method,
            "cn": (method_doc(cls, method)[0] or cn) if composite else cn,
            "composite": composite,
            "desc": method_doc(cls, method)[0] or cn,
            "params": [_pack_param(p, ns, method, fn) for p in params],
        }
        if underlying:  # 目录函数支撑：shape 字段表 + 目录 notes
            shape = return_shape_for(CAT, ns, method, underlying)
            raw_desc = RETURNS_OVERRIDES.get((ns, method)) \
                or fmt_returns(fn, inv, shape=shape)
            kind, stripped = _split_kind_prefix(raw_desc)
            entry["returns"] = {
                # 字段表即返回说明（TickDB 式）；密文 desc 行与「ARR·/MAP·」
                # 形态前缀不上用户面（kind 由前缀或 shape 推导）
                "kind": (shape or {}).get("kind") or (kind if stripped else "array"),
                "desc": None if (shape and (shape.get("items") or shape).get("fields"))
                else (stripped or None),
                "fields": _pack_fields(fn, underlying),
            }
            entry["notes"] = fn.get("notes") or []
        else:  # eval 型门面（$CODE 求值/宿主 spec 等）与组合接口：无 shape
            kind, rest = _split_kind_prefix(FALLBACK_RETURNS.get((ns, method), ""))
            entry["returns"] = {"kind": kind, "desc": rest or None, "fields": []}
            entry["notes"] = []
        meta = DOC_META.get((ns, method)) or {}
        # 变体（page=宿主）不成独立页：渲染在宿主页 variants 表里
        entry["docs_visible"] = bool(meta.get("docs_visible", True)) and "page" not in meta
        if "page" in meta:
            entry["page"] = meta["page"]
            entry["variant"] = meta.get("variant") or cn
        entry["example"] = None if composite else method_example(ns, method, params)
        attempts = _attempt_kwargs_list(ns, method, params)
        # 组合链路（多次 eval）PlaygroundRun 单次代理不可回放，显式 null；
        # eval 型核心门面（$FUT_*/宿主 spec/档案指标等）同样是单次 eval，可测。
        entry["test"] = None if composite else _capture_eval_payload(ns, method, attempts)
        return entry

    namespaces_out: list[dict] = []
    for title, nss in CHAPTERS:
        for ns in nss:
            rows = [r for r in FRIENDLY_INDEX if r[1] == ns]
            comp_methods = sorted(COMPOSITE_METHODS.get(ns, ()))
            if not rows and not comp_methods:
                continue
            # 章类别：取该章首个核心接口的类别（纯组合章继承章类别）
            cat = rows[0][0] if rows else next(
                (r[0] for r in FRIENDLY_INDEX if ns_chapter[r[1]] == title), "market")
            dom_id = ns_domain.get(ns)
            dom = domain_meta.get(dom_id) if dom_id else None
            node: dict = {
                "ns": ns,
                "cn": ns_title(ns),
                "chapter": title,
                "category": cat,
                "domain": dom_id,
                "domain_cn": dom.get("cn") if dom else None,
                "domain_description": (dom.get("description") or "") if dom else None,
                "domain_units": dom.get("units") or {} if dom else None,
                "interfaces": [_entry(ns, m, cn, underlying_fn(u), False)
                               for _, _, m, cn, u in rows],
                "composites": [_entry(ns, m, m, None, True) for m in comp_methods],
            }
            if comp_methods and COMPOSITE_EXAMPLES.get(ns):
                node["composite_examples"] = COMPOSITE_EXAMPLES[ns]
            namespaces_out.append(node)

    # 变体归组：DOC_META 里 page= 指向宿主的条目,挂到宿主页 variants
    by_key = {i["key"]: i for n in namespaces_out
              for i in (*n["interfaces"], *n["composites"])}
    for key, item in by_key.items():
        host_key = item.get("page")
        if not host_key:
            continue
        host = by_key.get(host_key)
        if host is None:
            raise AssertionError(f"DOC_META 变体 {key} 的宿主 {host_key} 不存在")
        host.setdefault("variants", []).append({
            "key": key, "variant": item.get("variant") or key,
            "desc": item["desc"], "params": item["params"],
        })
    # 宿主页自身也可能被标为变体（不可能：宿主必须 docs_visible）——防呆已由上方断言覆盖

    ifaces = [i for n in namespaces_out for i in (*n["interfaces"], *n["composites"])]
    visible = [i for i in ifaces if i["docs_visible"]]

    # 真实拍摄样本（tools/generate_api_pack_samples.py 联网产出；离线缺省）
    samples_doc = None
    if API_PACK_SAMPLES.is_file():
        samples_doc = json.loads(API_PACK_SAMPLES.read_text(encoding="utf-8"))
    sample_map = {s["key"]: s for s in (samples_doc or {}).get("samples") or []}
    sampled = 0
    for i in ifaces:
        s = sample_map.get(i["key"])
        if s and "result" in s:  # result=None 也是真实响应（标的无该数据）
            i["sample"] = s
            sampled += 1

    payload = {
        "schema_version": 2,
        "generated_by": "tools/gen_api_docs.py",
        "meta": {
            "core": len(FRIENDLY_INDEX),
            "composite": sum(len(n["composites"]) for n in namespaces_out),
            "docs_visible": len(visible),
            "variants": sum(1 for i in ifaces if i.get("page")),
            "domains": len(docs),
            "categories": [{"key": c, "cn": CATEGORY_CN[c]} for c in CATEGORY_ORDER],
            "test_ready": sum(1 for i in ifaces if i.get("test")),
            "sampled": sampled,
            "samples_provenance": (samples_doc or {}).get("provenance"),
        },
        "namespaces": namespaces_out,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    size = len(body.encode("utf-8"))
    if size > API_PACK_BUDGET:
        raise AssertionError(f"api_pack {size}B 超预算 {API_PACK_BUDGET}B——"
                             "请收紧 ROW_CAP/TEXT_CAP/SAMPLE_ROW_CAP")
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    body = build()
    fields_body = build_fields_json()
    pack_body = build_api_pack()
    if args.check:
        bad = False
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != body:
            print("gen_api_docs drift: docs/API.md", file=sys.stderr)
            bad = True
        if not FIELDS_OUT.is_file() or FIELDS_OUT.read_text(encoding="utf-8") != fields_body:
            print("gen_api_docs drift: docs/fields.json", file=sys.stderr)
            bad = True
        if (not API_PACK_OUT.is_file()
                or API_PACK_OUT.read_text(encoding="utf-8") != pack_body):
            print("gen_api_docs drift: docs/api_pack.json", file=sys.stderr)
            bad = True
        if bad:
            return 1
        print("gen_api_docs ok")
        return 0
    OUT.write_text(body, encoding="utf-8")
    FIELDS_OUT.write_text(fields_body, encoding="utf-8")
    API_PACK_OUT.write_text(pack_body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(body)} bytes) + "
          f"{FIELDS_OUT.relative_to(REPO)} ({len(fields_body)} bytes) + "
          f"{API_PACK_OUT.relative_to(REPO)} ({len(pack_body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
