"""生成 docs/INDICATORS.md：全量预置指标码导航（按数据类型分类，数据全部取自离线目录）。

背景：服务端已算好的指标码此前只存在于 metrics.json 与运行时目录 API，文档面仅有
精选码的生成表——开发者与 AI 发现不了现成的码就自己 eval 重算（EC 按标的数逐票
计费，代价高）。本页按数据类型（概览/股票行情/股票指标/行业/指数及ETF/宏观/期货/
可转债/港美）给全量码表与 raw 入口指路；分类为启发式（按前缀/主题前缀归类），
最终以 `cat.search` 为准。全部计数与码表由目录渲染，防手写漂移。

用法：
    python3 tools/gen_indicators.py            # 重新生成
    python3 tools/gen_indicators.py --check    # 漂移检查（CI / pytest 拦截手改）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import wmshare  # noqa: E402

OUT = REPO / "docs" / "INDICATORS.md"

UNIT_CN = {"percent": "百分数→小数", "yi_yuan": "亿元→元", "lot": "手→股"}

# 宏观主题前缀（启发式；ELEC=用电、POPULATION=人口、HOUSE=房地产、CPCA=乘用车产销、CR=汇率）。
# 未识别主题一律落「股票指标码」章——防丢码断言保证每个码必出现在恰一主表。
MACRO_THEMES = {
    "CPI", "GDP", "M1", "M2", "PPI", "PMI", "ELEC", "POPULATION", "HOUSE", "CPCA", "CR",
}

CHAPTER_TITLES = {
    "quotes": "股票行情与筛选",
    "stocks": "股票指标码",
    "industry": "行业数据",
    "index": "指数及 ETF",
    "macro": "宏观数据",
    "futures": "期货",
    "cbond": "可转债",
}

# 场景速查（场景, 指标码, 取数调用）——码与调用均须真实存在，build 内做防编造断言。
SCENES = [
    ("三年股息率均值 > 3%", "$BONUS_RATE_3Y_AVG_LAST",
     '`cli.indicator.metrics(sym, ["$BONUS_RATE_3Y_AVG_LAST"])`'),
    ("PE(TTM) 十年历史分位", "$PCT_PE_TTM_10Y_LAST",
     '`cli.indicator.get(sym, "$PCT_PE_TTM_10Y_LAST")`'),
    ("行业内 ROE 分位（1=行业最高）", "$CUR_IND_ROE_PCT_LAST",
     '`cli.indicator.get(sym, "$CUR_IND_ROE_PCT_LAST")`'),
    ("滚动归母 ROE", "$ROE_TTM_LAST",
     '`cli.indicator.metrics(sym, ["$ROE_TTM_LAST"])`'),
    ("行业 ROE(TTM) 均值", "$ID_ROE_TTM",
     '`cli.indicator.get(sym, "$ID_ROE_TTM")`'),
    ("沪深300 等权股息率", "$IDW_BONUS_RATE_HM",
     '`cli.indicator.get(sym, "$IDW_BONUS_RATE_HM")`'),
    ("期货主力连续收盘价", "$FUT_CLOSE",
     '`cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="cn.RB.SHF")`'),
    ("宏观 CPI 时序", "$CPI",
     '`cli.macro.query(...)`（`asof` / `spots` 取历史点列）'),
]


def esc(s: object) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def gh_slug(title: str) -> str:
    """GitHub 风格标题锚点：小写、去标点（保留连字符/空格/CJK）、空格转连字符。"""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def theme(code: str) -> str:
    body = code[1:]
    return body.split("_", 1)[0] if "_" in body else body


def classify(code: str) -> str:
    """主章归类（首匹配）。防丢码：未匹配一律落 stocks。"""
    if code.startswith("$FUT_"):
        return "futures"
    if code.startswith(("$INDEX_", "$IDW_")):
        return "index"
    if code.startswith(("$ID_", "$CUR_IND_")):
        return "industry"
    if code.startswith("$BOND_"):
        return "cbond"
    if code.startswith(("$MF_", "$VOL_", "$MA_", "$CHG_", "$AMPLITUDE_", "$c", "$x")):
        return "quotes"
    if theme(code) in MACRO_THEMES:
        return "macro"
    return "stocks"


def is_dead(m: dict) -> bool:
    return m.get("cn") == "drop stub"


def mk_cell(m: dict) -> str:
    if is_dead(m):
        return "⚠️ 死码"
    return "/".join(m.get("markets") or []) or "—"


def code_table(rows: list[dict]) -> list[str]:
    out = ["| 指标代码 | 中文 | 市场 |", "|---|---|---|"]
    for m in sorted(rows, key=lambda m: m["code"]):
        out.append(f"| `{m['code']}` | {esc(m.get('cn', ''))} | {mk_cell(m)} |")
    out.append("")
    return out


def group_block(g: dict) -> list[str]:
    """精选指标组：口径（caliber）+ 依赖 + 量级守护表（样式对齐 API.md 指标组节）。"""
    head = f"#### 指标组 {g['cn']}（{g['id']}）"
    cal = esc(g.get("caliber", ""))
    if g.get("unit"):
        cal += f"（单位：{esc(g['unit'])}）"
    if g.get("depends_on"):
        cal += "；依赖：" + "、".join(f"`{d}`" for d in g["depends_on"])
    lines = [head, "", cal, "", "| 指标代码 | 中文名 | 量级守护 |", "|---|---|---|"]
    for m in g.get("metrics") or []:
        parts = []
        if m.get("unit"):
            parts.append(UNIT_CN.get(m["unit"], m["unit"]))
        if m.get("range"):
            parts.append(f"范围 {m['range'][0]}…{m['range'][1]}")
        lines.append(f"| `{m['code']}` | {esc(m.get('cn', ''))} | {' · '.join(parts) or '—'} |")
    lines.append("")
    return lines


def toc_entry(title: str) -> str:
    return f"- [{title}](#{gh_slug(title)})"


def build() -> str:
    cat = wmshare.load()
    metrics = cat.metrics["metrics"]
    stats = cat.stats()
    from wmshare.api import FRIENDLY_INDEX

    total = len(metrics)
    assert total == stats["metric_catalog_total"], "metrics.json count 与条目数不一致"

    # ---- 分类与防丢码断言 ----
    buckets: dict[str, list[dict]] = {k: [] for k in CHAPTER_TITLES}
    for m in metrics:
        buckets[classify(m["code"])].append(m)
    assigned = [m["code"] for group in buckets.values() for m in group]
    assert len(assigned) == total, "分类出现重复或丢码"

    dead = [m for m in metrics if is_dead(m)]
    dead_codes = sorted(m["code"] for m in dead)

    groups = cat.domain("fund.indicators").get("metric_groups") or []
    g_by_id = {g["id"]: g for g in groups}
    quote_group = g_by_id.get("market_quote")
    stock_groups = [g for g in groups if g["id"] != "market_quote"]

    # 场景速查防编造断言：引用的码必须真实存在
    codes = {m["code"] for m in metrics}
    for _, code, _ in SCENES:
        assert code in codes, f"场景速查引用了目录外的码：{code}"
    syntax_examples = [
        "$PCT_PE_TTM_10Y_LAST", "$ID_ROE_TTM", "$CUR_IND_ROE_PCT_LAST",
        "$INDEX_AMOUNT_DAY", "$IDW_BONUS_RATE_HM", "$FUT_CLOSE",
        "$MF_ELG_NET", "$BOND_ISSUE_COUPON_IR", "$c_accel", "$xNT",
    ]
    for code in syntax_examples:
        assert code in codes, f"命名语法示例引用了目录外的码：{code}"

    # ---- 片段计数（命名语法表） ----
    def cnt(*frags: str) -> int:
        return sum(1 for m in metrics if any(f in m["code"] for f in frags))

    frag_rows = [
        ("`_LAST`", "最新截面值（不带 = 随最新财报期取值）", cnt("_LAST")),
        ("`_3Y` / `_5Y` / `_10Y` / `_3Q`", "回看窗口（年 / 季）", cnt("_3Y", "_5Y", "_10Y", "_3Q")),
        ("`_TTM`", "滚动十二个月口径", cnt("_TTM")),
        ("`_YOY`", "同比", cnt("_YOY")),
        ("`_AVG` / `_MIN` / `_TREND`", "窗口内均值 / 最低 / 趋势", cnt("_AVG", "_MIN", "_TREND")),
    ]
    fam_rows = [
        ("`$PCT_*`", "个股指标历史分位（0=最低 1=最高）", "$PCT_PE_TTM_10Y_LAST"),
        ("`$ID_*`", "行业均值 / 行业聚合", "$ID_ROE_TTM"),
        ("`$CUR_IND_*`", "当前三级行业内相对值 / 分位", "$CUR_IND_ROE_PCT_LAST"),
        ("`$INDEX_*`", "指数层行情与估值", "$INDEX_AMOUNT_DAY"),
        ("`$IDW_*`", "指数加权口径（等权 / 市值加权）", "$IDW_BONUS_RATE_HM"),
        ("`$FUT_*`", "期货主力连续（fut_symbol 指定合约）", "$FUT_CLOSE"),
        ("`$MF_*`", "个股资金流（超大/大/中/小单）", "$MF_ELG_NET"),
        ("`$BOND_*`", "可转债工具属性（条款/发行/转股）", "$BOND_ISSUE_COUPON_IR"),
        ("`$c_*` / `$x_*`", "筛选器条件与展示码", "$c_accel"),
    ]
    fam_lines = ["| 族前缀 | 含义 | 码数 | 示例 |", "|---|---|---|---|"]
    for fam, meaning, example in fam_rows:
        prefix_map = {
            "`$PCT_*`": "$PCT_", "`$ID_*`": "$ID_", "`$CUR_IND_*`": "$CUR_IND_",
            "`$INDEX_*`": "$INDEX_", "`$IDW_*`": "$IDW_", "`$FUT_*`": "$FUT_",
            "`$MF_*`": "$MF_", "`$BOND_*`": "$BOND_",
        }
        n = sum(1 for m in metrics if m["code"].startswith(prefix_map.get(fam, fam)))
        fam_lines.append(f"| {fam} | {meaning} | {n} | `{example}` |")
    fam_lines.append("")

    out: list[str] = [
        "<!-- GENERATED by tools/gen_indicators.py — do not hand-edit -->",
        "",
        "# 指标库导航（按数据类型分类）",
        "",
        f"> 服务端已把 **{total}** 个指标码算好直出：历史分位、多窗口均值/最低/趋势、行业均值与"
        "行业内分位、指数加权、期货主力连续、宏观时序……"
        "**取数前先在本页或 `cat.search` 找码——目录里有的码不要自己算**"
        "（eval 按标的数逐票计费 EC）。单位铁律：比率/涨跌幅/分位一律小数"
        "（0.0396 = 3.96%），金额=元、量=股。精选 "
        f"{stats['curated_metrics']} 码带口径与量级守护（违例抛 `DataError`）；"
        "其余码不做换算与守护，口径以返回值/cn 注释为准。分类为启发式，最终以 `cat.search` 为准。",
        "",
        f"全库：{stats['domains']} 个数据域 · {len(FRIENDLY_INDEX)} 个核心接口 · "
        f"{stats['functions']} 个底层函数 · **{total} 个指标码**"
        f"（精选 {stats['curated_metrics']} · 死码 {len(dead)}）。",
        "",
        "## 目录",
        "",
    ]
    toc_titles = [
        "概览", "命名语法", "股票行情与筛选", "股票指标码", "行业数据",
        "指数及 ETF", "宏观数据", "期货", "可转债", "港股与美股（市场限制视图）",
        "死码警示", "场景速查",
    ]
    for i, t in enumerate(toc_titles):
        out.append(toc_entry(f"{i + 1}. {t}"))
    out += [""]

    # ================= 1. 概览 =================
    overview_rows = [
        ("概览与检索（本节）", "`wmshare.load()` + `cat.*`（见下）", "—", "—"),
        ("股票行情与筛选", "`cli.kline` / `cli.screener` / `cli.moneyflow` / `cli.margin`",
         "`$MF_*` `$VOL_*` `$MA_*` `$CHG_*` `$AMPLITUDE_*` `$c_*` `$x_*` + market_quote 组",
         len(buckets["quotes"])),
        ("股票指标码", "`cli.indicator` / `cli.valuation` / `cli.dividend`",
         "`$PCT_*` + 其余主题组 + 10 组精选", len(buckets["stocks"])),
        ("行业数据", "`cli.stocks.industries` / `cli.stocks.industry_members`",
         "`$ID_*` `$CUR_IND_*`", len(buckets["industry"])),
        ("指数及 ETF", "`cli.index`；ETF 日 K 走 `cli.kline.bars`",
         "`$INDEX_*` `$IDW_*`", len(buckets["index"])),
        ("宏观数据", "`cli.macro`", "`$CPI_*` `$GDP_*` `$M1_*` `$M2_*` `$PPI_*` `$PMI_*` "
         "`$ELEC_*` `$POPULATION_*` `$HOUSE_*` `$CPCA_*` `$CR_*`", len(buckets["macro"])),
        ("期货", "`cli.indicator.get` + `fut_symbol`", "`$FUT_*`", len(buckets["futures"])),
        ("可转债", "`cli.cbond`", "`$BOND_*`", len(buckets["cbond"])),
        ("财务与预测（指路）", "`cli.statement` / `cli.segments` / `cli.estimates`",
         "码在股票指标码章主题组", "—"),
        ("披露与治理（指路）",
         "`cli.notice` / `cli.dividend` / `cli.equity` / `cli.filings` / `cli.workout`",
         "码在股票指标码章主题组（如 `$BONUS_*`）", "—"),
        ("港股与美股（视图）", "`cli.intl`", "markets 限制码",
         sum(1 for m in metrics if set(m.get("markets") or []) & {"hk", "us"})),
        ("上游死码（勿用）", "—", "`$*_LIVE` 残片", len(dead)),
    ]
    # 防丢码：各章桶之和必须等于全量（死码已含在桶内，「死码警示」节只是标记视图）
    partition = sum(len(v) for v in buckets.values())
    assert partition == total, f"概览总表码数合计 {partition} != {total}"

    out += [
        "## 1. 概览",
        "",
        "| 数据类型 | raw 入口 / 门面 | 指标码族 | 码数 | 详见 |",
        "|---|---|---|---|---|",
    ]
    slug_map = dict(zip(toc_titles, [f"{i + 1}." + t for i, t in enumerate(toc_titles)]))
    chapter_link = {
        "股票行情与筛选": "股票行情与筛选", "股票指标码": "股票指标码", "行业数据": "行业数据",
        "指数及 ETF": "指数及 ETF", "宏观数据": "宏观数据", "期货": "期货", "可转债": "可转债",
    }
    for name, entry, fam, n in overview_rows:
        if name in chapter_link:
            anchor = gh_slug(f"{list(slug_map).index(chapter_link[name]) + 1}. {chapter_link[name]}")
            cell = f"[{n}](#{anchor})"
        elif name == "港股与美股（视图）":
            anchor = gh_slug("10. 港股与美股（市场限制视图）")
            cell = f"[{n}](#{anchor})"
        elif name == "上游死码（勿用）":
            cell = f"[{n}](#{gh_slug('死码警示')})"
        else:
            cell = str(n)
        out.append(f"| {name} | {entry} | {fam} | {cell} |")
    out += [
        "",
        "### 目录检索索引",
        "",
        "| 需求 | 一行调用 |",
        "|---|---|",
        "| 关键词检索码（中文/英文） | `cat.search(\"股息\")` |",
        "| 指标组总览 | `cat.metric_groups()` |",
        "| 组内全部码 | `cat.metrics_in_group(\"dividend\")` |",
        "| 单码合同（含量级守护） | `cat.metric(\"$BONUS_RATE_3Y_AVG_LAST\")` |",
        "| 函数合同（参数/返回） | `cat.function(\"bonus.snapshot_yield_ttm\")` |",
        "| 域合同 | `cat.domain(\"market.kline\")` |",
        "| 全库统计 | `cat.stats()` |",
        "",
        "```bash",
        "python3 -c \"import wmshare; print(wmshare.load().search('股息'))\"",
        "```",
        "",
    ]

    # ================= 2. 命名语法 =================
    out += ["## 2. 命名语法", "", "码名语法：`$主题 + [窗口] + [统计量] + [后缀]`。", ""]
    out += ["| 片段 | 含义 | 码数 |", "|---|---|---|"]
    for frag, meaning, n in frag_rows:
        out.append(f"| {frag} | {meaning} | {n} |")
    out += ["", "族前缀速查：", ""]
    out += fam_lines

    # ================= 3. 股票行情与筛选 =================
    out += [
        "## 3. 股票行情与筛选",
        "",
        "raw 入口：日 K（三种复权）/ 周月 K / 1 分钟分时 / 盘中快照走 `cli.kline`；"
        "单票筛选器与全市场宽度走 `cli.screener`；个股资金流走 `cli.moneyflow`"
        "（日频 EOD；全市场一次取数 `cli.moneyflow.board()` 仅 A 股，"
        "`cli.moneyflow.live` 为外部源当日读数、非盘中行情）；两融走 `cli.margin`。"
        "以下为行情与筛选类的预置指标码。",
        "",
    ]
    if quote_group:
        out += group_block(quote_group)
    for fam_prefix, label in [
        ("$MF_", "`$MF_*` 资金流"), ("$VOL_", "`$VOL_*` 量能"), ("$MA_", "`$MA_*` 均线"),
        ("$CHG_", "`$CHG_*` 区间涨跌幅"), ("$AMPLITUDE_", "`$AMPLITUDE_*` 振幅"),
    ]:
        rows = buckets["quotes"]
        sub = [m for m in rows if m["code"].startswith(fam_prefix)]
        out += [f"#### {label}（{len(sub)} 码）", ""]
        out += code_table(sub)
    screen = [m for m in buckets["quotes"] if m["code"].startswith(("$c", "$x"))]
    out += [f"#### 筛选器条件与展示码（`$c_*` / `$x_*`，{len(screen)} 码）", ""]
    out += code_table(screen)

    # ================= 4. 股票指标码 =================
    out += [
        "## 4. 股票指标码",
        "",
        f"基本面与估值主战场：{len(stock_groups)} 组精选码（带口径与量级守护）+ "
        "其余通用码（分位族与主题前缀组）。取数 `cli.indicator.get(sym, code)` 或"
        "一次多码 `cli.indicator.metrics(sym, [code, ...])`。",
        "",
    ]
    for g in stock_groups:
        out += group_block(g)
    pct_rows = [m for m in buckets["stocks"] if m["code"].startswith("$PCT_")]
    out += [f"#### `$PCT_*` 历史分位（{len(pct_rows)} 码）", ""]
    out += code_table(pct_rows)
    routed = {"$PCT_"}
    rest = [m for m in buckets["stocks"] if not any(m["code"].startswith(p) for p in routed)]
    by_theme: dict[str, list[dict]] = {}
    for m in rest:
        by_theme.setdefault(theme(m["code"]), []).append(m)
    out += [f"#### 其余通用码（{len(rest)} 码，按主题前缀）", ""]
    for t in sorted(by_theme):
        rows = by_theme[t]
        out += [f"##### `${t}*`（{len(rows)} 码）", ""]
        out += code_table(rows)

    # ================= 5. 行业数据 =================
    out += [
        "## 5. 行业数据",
        "",
        "raw 入口：`cli.stocks.industries()` 行业目录（申万 sw2021、恒生 hsi）、"
        "`cli.stocks.industry_members()` 行业成分股。指标码两族："
        "`$ID_*` 行业均值/聚合（行业层），`$CUR_IND_*` 个股在当前三级行业内的"
        "相对值与分位（1 = 行业最高）。",
        "",
    ]
    for fam_prefix, label in [("$ID_", "`$ID_*` 行业均值 / 行业聚合"),
                              ("$CUR_IND_", "`$CUR_IND_*` 行业内相对值 / 分位")]:
        sub = [m for m in buckets["industry"] if m["code"].startswith(fam_prefix)]
        out += [f"#### {label}（{len(sub)} 码）", ""]
        out += code_table(sub)

    # ================= 6. 指数及 ETF =================
    out += [
        "## 6. 指数及 ETF",
        "",
        "raw 入口：`cli.index`（指数键列表、成分股、权重股、宽基估值时序）；"
        "场内 ETF 日 K 与个股同构走 `cli.kline.bars(\"510300\", n=30)`，"
        "`cli.kline.is_etf(...)` 判别场内基金（ETF 无分时/分钟源，`min1`/`live` 会被"
        "拦截，盘中取数用 `cli.kline.snapshot`）。指标码：`$INDEX_*` 指数层行情与估值、"
        "`$IDW_*` 指数加权口径（等权 / 市值加权 / 调和）。",
        "",
    ]
    for fam_prefix, label in [("$INDEX_", "`$INDEX_*` 指数层"),
                              ("$IDW_", "`$IDW_*` 指数加权口径")]:
        sub = [m for m in buckets["index"] if m["code"].startswith(fam_prefix)]
        out += [f"#### {label}（{len(sub)} 码）", ""]
        out += code_table(sub)

    # ================= 7. 宏观数据 =================
    out += [
        "## 7. 宏观数据",
        "",
        "raw 入口：`cli.macro.query(...)` 检索与取数、`cli.macro.asof(...)` as-of 点、"
        "`cli.macro.spots(...)` 采样点列、`cli.macro.bond_curve(...)` 中债收益率曲线；"
        "行业高频另有 `cli.macro.cpca_top(...)`（乘用车产销）。"
        "以下按主题前缀分表。",
        "",
    ]
    macro_themes = sorted({theme(m["code"]) for m in buckets["macro"]})
    for t in macro_themes:
        rows = [m for m in buckets["macro"] if theme(m["code"]) == t]
        out += [f"#### `${t}*`（{len(rows)} 码）", ""]
        out += code_table(rows)

    # ================= 8. 期货 =================
    out += [
        "## 8. 期货",
        "",
        "主力连续 K 线指标（日/周/月三族），经 `cli.indicator` 取数；"
        "指标实现引用期间上下文，`symbol` 传任意 A 股代码即可，合约键经 `fut_symbol` 指定：",
        "",
        "```python",
        'cli.indicator.get("600519", "$FUT_CLOSE")                          # 缺省合约 cn.SR.ZCE',
        'cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="cn.RB.SHF")  # 上期所螺纹钢主力',
        'cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="global.CL")  # 外盘 WTI 原油',
        "```",
        "",
        "量纲：价=报价单位（随品种）、volume/oi=手、amount=万元（原生口径）。",
        "",
    ]
    out += code_table(buckets["futures"])

    # ================= 9. 可转债 =================
    out += [
        "## 9. 可转债",
        "",
        "raw 入口：`cli.cbond`（合约快照、条款事件、正股关联、强赎触发计数、独立日 K "
        "与盘中 1 分钟）；日更管线 `cli.cbond.daily()` → `article()` → `figures()`。"
        "指标码 `$BOND_*` 为转债工具属性（条款/发行/转股）。",
        "",
    ]
    out += code_table(buckets["cbond"])

    # ================= 10. 港股与美股（视图） =================
    hkus = [m for m in metrics if set(m.get("markets") or []) & {"hk", "us"}]
    ch_by_code = {m["code"]: classify(m["code"]) for m in hkus}
    out += [
        "## 10. 港股与美股（市场限制视图）",
        "",
        "以下码带市场限制（markets 含 hk/us），仅在对应用户端可用"
        "（`Client(market=\"hk\"/\"us\")`）；raw 专项（CCASS/沽空/机构评级）走 "
        "`cli.intl`。主表归属见「所在章」列，本节为交叉引用视图。",
        "",
        "| 指标代码 | 中文 | 市场 | 所在章 |",
        "|---|---|---|---|",
    ]
    for m in sorted(hkus, key=lambda m: m["code"]):
        ch = CHAPTER_TITLES[ch_by_code[m["code"]]]
        out.append(f"| `{m['code']}` | {esc(m.get('cn', ''))} | {mk_cell(m)} | {ch} |")
    out += [""]

    # ================= 死码警示 =================
    out += [
        "## 死码警示",
        "",
        f"以下 **{len(dead_codes)}** 个码是上游未注册的死码（cn 为 \"drop stub\"），"
        "混入 `cli.indicator.metrics()` 会整批失败——写死任何码之前先 `cat.metric(code)` 验真：",
        "",
    ]
    for i in range(0, len(dead_codes), 6):
        out.append(" · ".join(f"`{c}`" for c in dead_codes[i:i + 6]))
    out += [""]

    # ================= 场景速查 =================
    out += ["## 场景速查", "", "| 场景 | 指标码 | 取数 |", "|---|---|---|"]
    for scene, code, call in SCENES:
        out.append(f"| {scene} | `{code}` | {call} |")
    out += [
        "",
        "更多取数姿势见 [GUIDE](GUIDE.md) 与 [API 参考](API.md)；"
        "接口级合同见 [API.md](API.md)。",
        "",
    ]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="漂移检查：不一致则退出码 1")
    args = ap.parse_args()

    body = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != body:
            print(f"indicators drift: {OUT.name}（重跑 python3 tools/gen_indicators.py 更新）")
            return 1
        print(f"indicators ok: {OUT.name}")
        return 0
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.name}（{len(body)} bytes）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
