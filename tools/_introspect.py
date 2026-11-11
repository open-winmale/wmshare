#!/usr/bin/env python3
"""共享内省：友好层方法 → 参数/说明/示例/返回 schema（gen_api_docs 与 gen_openapi 共用）。

友好层注解为字符串形式（`from __future__ import annotations`），此处做轻量解析，
支持的注解集合即 api/ 包中实际使用的：str/int/float/bool/list[str]/dict 及 `X | None`。
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass

_PY2JSON = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
            "list": "array", "dict": "object", "list[str]": "array",
            "dict[str, Any]": "object", "Any": "object"}

# 示例值（按参数名；文档示例口径，非编造合同）
EXAMPLE_VALUES = {
    "adj": '"qfq"', "code": '"$PE_TTM_LAST"',
    "codes": '["$PE_TTM_LAST", "$ROE_TTM_LAST"]',
    "category": '"回购"', "begin": '"2026-01-01"', "end": '"2026-03-31"',
    "kind": '"annual"', "keyword": '"回购"', "window": '"3m"',
    "years": "3", "scope": '"合并"', "n": "30", "limit": "10",
    "symbols": '["600519", "000001"]', "date": '"2026-06-30"',
    "min_chg": "0.10", "min_ratio": "1.5", "desc": "True",
    "key": '"index.hs300"', "top_n": "10", "points": "8",
}

# 方法级示例值覆盖（同一参数名在不同接口语义不同，如 kind）
METHOD_EXAMPLE_VALUES = {
    ("statements", "compare"): {"kind": '"income"'},
    ("statements", "tree"): {"kind": '"balance"'},
    ("statements", "years"): {"kind": '"income"'},
    ("valuation", "hist_stats"): {"metric": '"pe"', "window": '"3y"'},
    # 回撤筛选的示例取上游默认语义（近 20 日跌超 10%）
    ("screener", "screen_pullback_20d"): {"min_chg": "-0.10"},
    # 全市场条件选股：示例用真实可跑的「三年股息均值 > 3% 且 ROE > 15%」
    ("screener", "query"): {
        "where": '"$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15"',
        "order": '"$BONUS_RATE_3Y_AVG_LAST"',
    },
    # 报告期变体（annual=年报年度 / sampling=报告期采样）
    ("equity", "query_exec_change_at"): {"annual": "2024", "sampling": '"Q4"'},
    ("equity", "query_capital_change_at"): {"annual": "2024", "sampling": '"Q4"'},
    # 强赎触发价（元，面值 100 口径的正股价示例）
    ("cbond", "call_hits"): {"trig": "130.0"},
    # 研究级组合接口：示例串成一条完整链路（取数 → 事实 → 成稿/出图）
    ("cbond", "article"): {"payload": "cli.cbond.daily(top_n=5)", "date": '"20261107"'},
    ("cbond", "figures"): {"payload": "cli.cbond.daily(top_n=5)",
                           "out_dir": '"/tmp/cb_figs"', "date": '"20261107"'},
    # 行业成分：中文名示例（引擎原生解析；SDK 侧另有模糊匹配兜底）
    ("stocks", "industry_members"): {"industry": '"银行"'},
    # 宏观（v1.11.0）：示例取活体实证过的取值（不可用股票指标码占位）
    ("macro", "query"): {"code": '"$CPI"', "n": "6"},
    ("macro", "asof"): {"code": '"$CPI"'},
    ("macro", "spots"): {"code": '"$GDP"', "n": "4"},
    ("macro", "sampling_of"): {"code": '"$GDP"'},
    ("macro", "bond_curve"): {"curve_name": '"中债国债收益率曲线"', "tenor": '"10年"'},
    ("macro", "nev_monthly"): {"brand": '"零跑"', "field": '"sales"'},
    ("macro", "nev_weekly"): {"brand": '"零跑"', "field": '"sales"'},
    ("macro", "avc_monthly"): {"category": '"消费级摄像头"', "field": '"volume"'},
    ("macro", "chinaiol_monthly"): {"category": '"洗衣机"', "field": '"volume"'},
    ("macro", "cpca_top"): {"manufacturer": '"比亚迪汽车"', "field": '"wholesale"'},
    ("macro", "phone_share"): {"brand": '"小米"', "field": '"share"'},
}

# 组合接口的文档示例（按命名空间；缺省不渲染示例块）
COMPOSITE_EXAMPLES: dict[str, list[str]] = {
    "cbond": [
        "payload = cli.cbond.daily(top_n=20)                  # 事实包（3 次请求）",
        "cli.cbond.article(payload, date=\"20261107\")          # 源稿 + 公众号稿",
        "cli.cbond.figures(payload, \"/tmp/cb\", date=\"20261107\")  # 需 wmshare[figures]",
    ],
    "backtest": [
        "res = cli.backtest.run(\"600519\", fast=5, slow=20)   # 均线金叉买 / 死叉卖",
        "res = cli.backtest.run(\"600519\", rule=\"pe\", buy=20, sell=40)  # 估值阈值（≤3 年）",
        "res[\"trades\"][:2]                                    # 成交明细（买/卖各一行）",
        "res[\"summary\"][\"max_drawdown\"]                      # 净值汇总（8 个数字）",
    ],
}

# 返回说明覆盖（目录 shape 过粗的动态列表返回，按上游实现补字段级说明；
# pct_of_total 为百分数数值（52.3=52.3%），涨跌幅/median_pct 为小数）
RETURNS_OVERRIDES = {
    ("screener", "index_breadth_bins"):
        "ARR · 行 label:str（档位） count:int pct_of_total:float（百分数，52.3=52.3%）",
    ("screener", "index_breadth_bin_industries"):
        "ARR · 行 bin:str（档位） industry:str（行业代码，如 industry.S77） count:int",
}

# 返回说明兜底（FRIENDLY_INDEX 底层列不可回溯目录 shape 的核心接口）
FALLBACK_RETURNS = {
    ("indicator", "get"): "数值 · 单指标当前值",
    ("indicator", "metrics"): "MAP · {code: 值}",
    ("info", "profile"): "MAP · 档案（name/industry/style_industry/org_type/listing_date）",
    ("valuation", "hist_stats"):
        "MAP · {avg, current, median, min, max, pct, count, series:[unix秒,值]}（窗口上限 3 年）",
    ("screener", "query"):
        "MAP · {count: 全市场命中数（不受 limit 截断）, rows: [{symbol, name, $码: 值}]}",
    ("cbond", "daily"):
        "MAP · {facts, derived, gates, states, top, scatter, calendar, featured_band,"
        " caliber_layers, coverage}（口径分层 + 三道闸 + 状态机 + 事件日历）",
    ("cbond", "article"):
        "MAP · {source, wechat, summary, date, campaign}（源稿与公众号稿）",
    ("cbond", "figures"):
        "MAP · {table, scatter, band_<code>: 图片路径}（需 wmshare[figures]）",
    ("backtest", "run"):
        "MAP · {trades: 成交明细, summary: 8 个汇总数字, equity: [{date, nav}], caliber}",
}

_PARAM_RE = re.compile(r"^:param (\w+):\s*(.*)$")

# JSON schema 类型映射（目录/returns_shape 用）
SHAPE_TYPE = {"string": "string", "int": "integer", "int64": "integer",
              "float": "number", "float64": "number", "bool": "boolean"}


@dataclass
class Param:
    name: str
    json_type: str      # string/integer/number/boolean/array/object
    py_ann: str         # 原注解串
    required: bool
    default: str | None = None
    desc: str = ""


def parse_docstring(doc: str | None) -> tuple[str, str, dict[str, str]]:
    """docstring → (summary 首行, body 其余文本, {param: desc})。"""
    if not doc:
        return "", "", {}
    lines = doc.strip().splitlines()
    summary = lines[0].strip()
    params: dict[str, str] = {}
    body: list[str] = []
    for ln in lines[1:]:
        m = _PARAM_RE.match(ln.strip())
        if m:
            params[m.group(1)] = m.group(2).strip()
        elif ln.strip():
            body.append(ln.strip())
    return summary, "、".join(body) if body else "", params


def _resolve(ann: object) -> tuple[str, str]:
    s = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
    s = s.strip()
    t = _PY2JSON.get(s)
    if t is None:
        t = _PY2JSON.get(s.split("|", 1)[0].strip(), "object")
    return t, s


def method_params(cls: type, method: str) -> list[Param]:
    """方法签名 → 业务参数列表（self/_raw/_df 等传输细节不进接口文档）。"""
    fn = getattr(cls, method)
    out: list[Param] = []
    for name, p in inspect.signature(fn).parameters.items():
        if name == "self" or name.startswith("_"):
            continue
        jt, py = _resolve(p.annotation)
        has_default = p.default is not inspect.Parameter.empty
        out.append(Param(name=name, json_type=jt, py_ann=py, required=not has_default,
                         default=repr(p.default) if has_default else None))
    descs = parse_docstring(inspect.getdoc(fn))[2]
    if not descs:  # 参数说明写在类 docstring 时（如 StatementsApi）
        descs = parse_docstring(inspect.getdoc(cls))[2]
    for p in out:
        p.desc = descs.get(p.name, "")
    return out


def method_doc(cls: type, method: str) -> tuple[str, str]:
    return parse_docstring(inspect.getdoc(getattr(cls, method)))[:2]


def method_example(ns: str, method: str, params: list[Param]) -> str:
    """机械生成调用示例：symbol 位置传 "600519"，其余取示例值表，无示例值的必填参数以 … 占位。"""
    overrides = METHOD_EXAMPLE_VALUES.get((ns, method), {})
    values = {**EXAMPLE_VALUES, **overrides}
    parts: list[str] = []
    if any(p.name == "symbol" for p in params):
        parts.append('"600519"')
    for p in params:
        if p.name == "symbol":
            continue
        if p.name in values:
            parts.append(f"{p.name}={values[p.name]}")
        elif p.required:
            parts.append(f"{p.name}=…")
    return f"cli.{ns}.{method}({', '.join(parts)})"


def underlying_fn(underlying: str) -> str | None:
    """FRIENDLY_INDEX 底层列 → 可回溯的目录函数名；不可映射（$CODE eval 等）返回 None。"""
    s = underlying.split("[")[0].strip()
    return s if re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", s) else None


# 友好层包装返回单个对象（底层是数组，取首行/None）；文档/OpenAPI 不能沿用数组 shape。
SINGLE_OBJECT_METHODS = {
    ("kline", "last"),
    ("moneyflow", "last"),
    ("dividend", "last"),
}


def return_shape_for(catalog: object, ns: str, method: str, underlying: str) -> dict | None:
    """核心接口的返回 shape：目录 shape + 单对象包装修正。"""
    fn_key = underlying_fn(underlying)
    if not fn_key:
        return None
    try:
        shape = catalog.function(fn_key).get("returns_shape")  # type: ignore[attr-defined]
    except Exception:
        return None
    if (ns, method) in SINGLE_OBJECT_METHODS and shape and shape.get("kind") == "array":
        items = shape.get("items") or {}
        return {
            "kind": "object",
            "cn": f"{items.get('cn') or '结果'} 或 None（无数据）",
            "fields": list(items.get("fields") or []),
        }
    return shape


def shape_to_schema(shape: dict | None) -> dict:
    """目录 returns_shape → JSON schema（OpenAPI 3.1 兼容）。"""
    if not shape:
        return {}
    out: dict = {}
    if shape.get("cn"):
        out["description"] = shape["cn"]
    kind = shape.get("kind")
    if kind == "array":
        out["type"] = "array"
        items = shape.get("items") or {}
        if items.get("fields"):
            out["items"] = _fields_object(items["fields"])
        elif items.get("type") in SHAPE_TYPE:
            out["items"] = {"type": SHAPE_TYPE[items["type"]]}
        return out
    if kind == "object" and shape.get("fields"):
        out.update(_fields_object(shape["fields"]))
    return out


def _fields_object(fields: list[dict]) -> dict:
    props = {}
    for f in fields:
        t = SHAPE_TYPE.get(f.get("type", "any"))
        prop: dict = {"type": t} if t else {}
        if f.get("cn"):
            prop["description"] = f["cn"]
        props[f["name"]] = prop
    return {"type": "object", "properties": props}
