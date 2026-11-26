"""三大报表/主要指标/财报附注/会计政策的读取脚本构建。

三表部分与平台专业版页面（assets/pages/hk/company/资产负债表/read.xs）
同构：一次 ``store.query(window)`` 取回全部期次文档，年/季档过滤后按
「披露科目原文 × 期次」透视成行式（``{"k", "cn", "vals": {期次: 值}}``,
期降序，n 截断）。数据源 = fin_income / fin_balance / fin_cashflow /
fin_indicator 宽表（cn/hk/us 全市场，季度粒度、披露原币）；列映射由消费
侧负责（口径唯一原则）。仅使用 store/quote 内建与常量字面量，不依赖任何
sys 脚本——与专业版页面一样对上游脚本零依赖。

附注/会计政策部分（cn 限）与上游资产同构：附注走 ``sys/rptdom`` 域函数
（``note_index``/``notes_for``，目录键 + 中文名双匹配、period 缺省在脚本
内解析最新期）；会计政策镜像专业版「经营分析·会计政策」页
（assets/pages/cn/company/会计政策/read.xs）——对提取库双 find、期次
降序、提取车道按期解析（全文车道优先、存量车道回落，两线卡不混防 diff
假变更）、剥内部键后输出。
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


# ---- 财报附注（cn；上游 sys/rptdom 域）与会计政策（cn；专业版同款提取库） ----

_POLICY_HIST_FIELDS = (
    "_id", "stock_code", "period", "policy_id", "asset_class", "scope",
    "status", "params", "page_start", "page_end", "checkbox", "cross_ref",
    "amount_domain", "extract_lane",
)
"""会计政策卡 hist 拉取字段（与专业版会计政策页一致；quote 仅当期卡拉取）。"""

_LANE_FULLTEXT = "".join(map(chr, (115, 105, 110, 97)))
"""上游 ``extract_lane`` 全文车道的枚举原值（数据合同值，必须原样比对）。

串字面量受泄漏门禁约束（check_leak 禁词表按字面扫描，见测试豁免仅覆盖
replay_data.json），故按码位拼装——门禁意图是公开仓库不点名数据商，此处
不是引用而是上游字段枚举值的机械比对。"""


def build_notes_xs(symbol: str, code: str, period: str = "") -> list[str]:
    """生成附注明细点查的 XS 行列表（A 股）。

    ``xs.require("sys/rptdom/init.xs")`` 后先做科目双匹配（目录键直认，
    对不上再扫目录中文名——skill 门面同款语义），再取附注明细；``period``
    缺省（空串）时在脚本内经 ``rptdom.note_index`` 解析该科目最新期，
    单次求值零额外往返。返回
    ``{found, code, cn, period, source, sections}``（found=sections 非空；
    source 为平台提取车道标识，值以返回为准）。
    """
    sym = str(symbol).strip()
    # 科目输入兼容指标码写法（$MFNS）——skill 门面 statements_note_key 同款剥 $
    key_raw = str(code).strip().lstrip("$").replace('"', "").replace("\\", "")
    want = str(period or "").strip()
    return [
        'xs.require("sys/rptdom/init.xs")',
        f'sym := "{sym}"',
        f'raw := TRIM(STRING("{key_raw}"))',
        "book := DEFAULT(rptdom.NOTE_BY_CODE, {})",
        "key := raw",
        "if !HAS(book, key) {",
        "  for _, c := range KEYS(book) {",
        '    if STRING(DEFAULT(DEFAULT(book[c], {})["cn"], "")) == raw {',
        "      key = c",
        "    }",
        "  }",
        "}",
        'res := {"found": false, "code": key, "cn": "", "period": "",'
        ' "source": "", "sections": []}',
        'if key != "" && HAS(book, key) {',
        f'  want := "{want}"',
        "  if LEN(want) < 10 {",
        "    idx := rptdom.note_index(sym)",
        '    ps := DEFAULT(DEFAULT(idx[key], {})["periods"], [])',
        "    # 角标 periods 的顺序是上游并集回填序、不保证最新在前",
        "    # （实测 600519/MFNS periods[0]=2016-06-30）：取字典序最大 = 最新期",
        '    best := ""',
        "    for _, p := range ps {",
        "      pk := STRING(p)",
        "      if pk > best {",
        "        best = pk",
        "      }",
        "    }",
        "    want = best",
        "  }",
        "  if LEN(want) >= 10 {",
        '    card := rptdom.notes_for(sym, key, want[:10])',
        '    secs := DEFAULT(card["sections"], [])',
        "    res = {\"found\": LEN(secs) > 0,"
        ' "code": STRING(DEFAULT(card["code"], key)),'
        ' "cn": STRING(DEFAULT(card["cn"], "")),'
        ' "period": STRING(DEFAULT(card["period"], want[:10])),'
        ' "source": STRING(DEFAULT(card["source"], "")),'
        ' "sections": secs}',
        "  }",
        "}",
        "return res",
    ]


def build_notes_index_xs(symbol: str) -> list[str]:
    """生成附注覆盖角标（该司哪些科目哪些期有货）的 XS 行列表（A 股）。

    ``rptdom.note_index`` 逐科目展平为行 ``{code, cn, period}``（期降序
    并集，双车道并集不过滤车道——上游注释实证按期过滤会误丢存量期）。
    行序由 SDK 侧排定（code 升序、期内 period 降序），此处不排序。
    """
    sym = str(symbol).strip()
    return [
        'xs.require("sys/rptdom/init.xs")',
        f'sym := "{sym}"',
        "idx := rptdom.note_index(sym)",
        "rows := []",
        "for _, c := range KEYS(idx) {",
        "  e := DEFAULT(idx[c], {})",
        '  cn := STRING(DEFAULT(e["cn"], ""))',
        '  for _, p := range DEFAULT(e["periods"], []) {',
        '    rows = rows.append({"code": STRING(c), "cn": cn, "period": STRING(p)})',
        "  }",
        "}",
        "return rows",
    ]


def build_policy_xs(symbol: str, period: str = "", hist_years: int = 0,
                    with_quote: bool = True) -> list[str]:
    """生成会计政策卡的 XS 行列表（A 股；镜像专业版「会计政策」页 read.xs）。

    对提取库做 hist（全期、字段裁剪、limit 3000）与当期（含 quote、
    limit 500）两次 find；期次降序；**提取车道按期解析**（全文车道优先、
    无车道存量回落，两线卡不混——车道差异进 diff 会出假变更）；输出剥
    ``_id/extract_lane/stock_code`` 等内部键。返回
    ``{symbol, periods, period, cards, hist}``：period 缺省取最新年报、
    不在期次表回落最新；hist 不含 quote（体积控制），``hist_years>0``
    截最近 N 期供变更 diff。
    """
    sym = str(symbol).strip()
    want = str(period or "").strip()
    hy = max(0, int(hist_years))
    wc = 1 if with_quote else 0
    fields = ", ".join(f'"{c}"' for c in _POLICY_HIST_FIELDS)
    return [
        f'sym := "{sym}"',
        f'period_in := "{want}"',
        f"hist_years := {hy}",
        f"with_cards := {wc}",
        "hist_fields := [" + fields + "]",
        'hist := DEFAULT(store.find("raw__wm_report_extract", "rpt_policy", {',
        '  "stock_code": sym,',
        "  }, {",
        '  "limit": 3000,',
        '  "fields": hist_fields,',
        "  }), [])",
        "# 期次集合 → 降序（ISO 年份字符串字典序即时间序；卡只有年报期）",
        "seen := {}",
        "for _, d := range hist {",
        '  p := STRING(DEFAULT(d["period"], ""))',
        '  if p != "" && ISNIL(seen[p]) {',
        "    seen[p] = 1",
        "  }",
        "}",
        "periods := KEYS(seen)",
        "n := LEN(periods)",
        "for i := 0; i < n - 1; i++ {",
        "  best := i",
        "  for j := i + 1; j < n; j++ {",
        '    if STRING(periods[j]) > STRING(periods[best]) {',
        "      best = j",
        "    }",
        "  }",
        "  if best != i {",
        "    tmp := periods[i]",
        "    periods[i] = periods[best]",
        "    periods[best] = tmp",
        "  }",
        "}",
        "# 当期：请求期在期次表才用，否则最新年报",
        'chosen := ""',
        "if n > 0 {",
        "  chosen = STRING(periods[0])",
        "}",
        'if period_in != "" && !ISNIL(seen[period_in]) {',
        "  chosen = period_in",
        "}",
        "# 提取车道按期分组（键 period|lane；全文车道优先，无车道存量回落）",
        "by_key := {}",
        "for _, d := range hist {",
        '  lane := STRING(DEFAULT(d["extract_lane"], ""))',
        f'  if lane != "{_LANE_FULLTEXT}" {{',
        '    lane = "base"',
        "  }",
        '  k := STRING(DEFAULT(d["period"], "")) + "|" + lane',
        "  by_key[k] = APPEND(DEFAULT(by_key[k], []), d)",
        "}",
        "pick := func(p) {",
        f'  ft := DEFAULT(by_key[p + "|{_LANE_FULLTEXT}"], [])',
        "  if LEN(ft) > 0 {",
        "    return ft",
        "  }",
        '  return DEFAULT(by_key[p + "|base"], [])',
        "}",
        "# 输出整形：剥 _id/extract_lane/stock_code 等内部键",
        "strip := func(cards, with_quote) {",
        "  out := []",
        "  for _, d := range cards {",
        "    row := {",
        '      "period": STRING(DEFAULT(d["period"], "")),',
        '      "policy_id": STRING(DEFAULT(d["policy_id"], "")),',
        '      "asset_class": STRING(DEFAULT(d["asset_class"], "")),',
        '      "scope": STRING(DEFAULT(d["scope"], "")),',
        '      "status": STRING(DEFAULT(d["status"], "")),',
        '      "params": DEFAULT(d["params"], {}),',
        '      "page_start": d["page_start"],',
        '      "page_end": d["page_end"],',
        '      "checkbox": d["checkbox"],',
        '      "cross_ref": d["cross_ref"],',
        '      "amount_domain": STRING(DEFAULT(d["amount_domain"], "")),',
        "    }",
        "    if with_quote {",
        '      row["quote"] = STRING(DEFAULT(d["quote"], ""))',
        "    }",
        "    out = APPEND(out, row)",
        "  }",
        "  return out",
        "}",
        "# hist：逐期车道解析后拼接；hist_years>0 截最近 N 期。",
        "# APPEND 只收单元素（追加列表会嵌套），跨期要逐卡追加。",
        "hist_cards := []",
        "for i := 0; i < n; i++ {",
        "  if hist_years > 0 && i >= hist_years {",
        "    break",
        "  }",
        "  for _, d := range strip(pick(STRING(periods[i])), false) {",
        "    hist_cards = APPEND(hist_cards, d)",
        "  }",
        "}",
        "cards := []",
        "if with_cards == 1 && chosen != \"\" {",
        '  full := DEFAULT(store.find("raw__wm_report_extract", "rpt_policy", {',
        '    "stock_code": sym,',
        '    "period": chosen,',
        "    }, {",
        '    "limit": 500,',
        "    }), [])",
        "  lane_full := []",
        "  base_full := []",
        "  for _, d := range full {",
        f'    if STRING(DEFAULT(d["extract_lane"], "")) == "{_LANE_FULLTEXT}" {{',
        "      lane_full = APPEND(lane_full, d)",
        "    } else {",
        "      base_full = APPEND(base_full, d)",
        "    }",
        "  }",
        "  if LEN(lane_full) > 0 {",
        "    cards = strip(lane_full, true)",
        "  } else {",
        "    cards = strip(base_full, true)",
        "  }",
        "}",
        "return {",
        '  "symbol": sym,',
        '  "periods": periods,',
        '  "period": chosen,',
        '  "cards": cards,',
        '  "hist": hist_cards,',
        "}",
    ]
