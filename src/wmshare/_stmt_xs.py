"""三大报表/主要指标的读取脚本构建（专业版同款 fin_* 宽表窗口读取）。

生成的 XS 与平台专业版页面（assets/pages/hk/company/资产负债表/read.xs）
同构：一次 ``store.query(window)`` 取回全部期次文档，年/季档过滤后按
「披露科目原文 × 期次」透视成行式（``{"k", "cn", "vals": {期次: 值}}``,
期降序，n 截断）。数据源 = fin_income / fin_balance / fin_cashflow /
fin_indicator 宽表（cn/hk/us 全市场，季度粒度、披露原币）；列映射由消费
侧负责（口径唯一原则）。仅使用 store/quote 内建与常量字面量，不依赖任何
sys 脚本——与专业版页面一样对上游脚本零依赖。
"""

from __future__ import annotations

_MAX_PERIODS = 12
"""期数上限，与专业版前端默认窗口（n=12）对齐。"""

_META_COLS = (
    "CreatedAt", "UpdatedAt", "catalog", "midx", "monthNum", "orgCode",
    "orgType", "orgTypeName", "quoteName", "report", "samplingTs",
    "samplingType", "samplingName", "samplingStart", "securityCode",
    "securityNameAbbr", "settleDate", "statuses", "symbol", "tip",
    "secucode", "updateDate", "noticeDate", "accountingStandard",
    "exchange", "fiscalYear", "annual", "sampling", "currency",
    "currencyName", "opinionType", "samplingEnd", "reportDate",
    "reportType", "reportDateName", "listingState", "securityTypeCode",
)
"""宽表簿记列（非科目行），透视时剔除。"""


def infer_market(symbol: str) -> str:
    """按代码形态推市场：6 位数字=cn、5 位数字=hk、其余（字母码）=us。"""
    s = str(symbol or "").strip()
    if s.isdigit():
        return "cn" if len(s) == 6 else "hk"
    return "us"


def build_statement_xs(catalog: str, symbol: str, years: int, period: str) -> list[str]:
    """生成一次窗口批量读取 + 透视的 XS 行列表。

    ``catalog`` 为宽表 store 名（fin.income 等）；``period="annual"`` 只留
    Q4 年报档（vals 键=纯年份），``"quarter"`` 为季报全档（键=``2026:Q1``）；
    ``years`` 为期数（1..12），文档不足时按实际返回（缺期不填补）。
    """
    years = max(1, min(int(years), _MAX_PERIODS))
    sym = str(symbol).strip()
    q_cap = max(8, min(years * (1 if period == "quarter" else 4), 200))
    meta_pairs = ", ".join(f'"{c}": 1' for c in _META_COLS)
    lines = [
        f'sym := "{sym}"',
        "key := quote.market(sym) + \".\" + sym",
        f'docs := DEFAULT(store.query("{catalog}", key, {q_cap}, '
        '{"window": true, "samplingtype": samplingtype.Quarter}), [])',
        "kept := []",
        "for _, d := range docs {",
        f'  if "{period}" == "annual" && STRING(DEFAULT(d.sampling, "Q4")) != "Q4" {{',
        "    continue",
        "  }",
        "  kept = kept.append(d)",
        "}",
        # 新→旧排序（annual+sampling 拼串比较，等长档位字符串序即时间序）
        "for i := 0; i < LEN(kept); i++ {",
        "  for j := i + 1; j < LEN(kept); j++ {",
        '    ki := STRING(DEFAULT(kept[i].annual, 0)) + STRING(DEFAULT(kept[i].sampling, "Q4"))',
        '    kj := STRING(DEFAULT(kept[j].annual, 0)) + STRING(DEFAULT(kept[j].sampling, "Q4"))',
        "    if ki < kj {",
        "      tmp := kept[i]",
        "      kept[i] = kept[j]",
        "      kept[j] = tmp",
        "    }",
        "  }",
        "}",
        f"if LEN(kept) > {years} {{",
        "    kept2 := []",
        f"    for t := 0; t < {years}; t++ {{",
        "        kept2 = kept2.append(kept[t])",
        "    }",
        "    kept = kept2",
        "}",
        f"META := {{{meta_pairs}}}",
        "out := []",
        "if LEN(kept) > 0 {",
        "  for _, col := range KEYS(kept[0]) {",
        "    c := STRING(col)",
        '    if !ISNIL(META[c]) {',
        "      continue",
        "    }",
        "    vals := {}",
        "    for _, d := range kept {",
        '      y := STRING(DEFAULT(d.annual, ""))',
        '      q := STRING(DEFAULT(d.sampling, "Q4"))',
        f'      kY := IF("{period}" == "annual", y, y + ":" + q)',
        "      v := DEFAULT(d[c], nil)",
        "      if !ISNIL(v) {",
        "        vals[kY] = v",
        "      }",
        "    }",
        "    if LEN(vals) == 0 {",
        "      continue",
        "    }",
        '    out = out.append({"k": c, "cn": c, "vals": vals})',
        "  }",
        "}",
        "return out",
    ]
    return lines
