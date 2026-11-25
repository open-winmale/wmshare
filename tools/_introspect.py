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

# 内部目录命名空间的唯一事实源在包内（``wmshare.catalog``）——运行时收口
# （client 属性直达 / 目录检索）与文档生成物都要用同一份集合，不能各存一份。
from wmshare.catalog import (  # noqa: E402,F401
    INTERNAL_CATALOG_NS,
    is_internal_name as is_internal_catalog_name,
)

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
    # 2.0 新面（fut_code 必填缺表会落 … 占位并打红示例执行测试）
    ("futures", "get"): {"fut_code": '"RB.SHF"', "field": '"close"'},
    # 批次1 暴露层：类目键真实示例；PDF 定位参数指向取值来源
    ("notice", "category_regex"): {"key": '"buyback"'},
    ("toplist", "by_date"): {"trade_date": '"2026-11-18"', "limit": "10"},
    # 板块资金流：来源与交易日是必填（缺表会让示例落 … 占位并打红示例执行测试）
    ("board", "moneyflow"): {"src": '"ths_concept"',
                             "trade_date": '"2026-11-20"', "limit": "10"},
    ("board", "moneyflow_last"): {"src": '"ths_concept"', "limit": "10"},
    # 大宗交易：单日榜需交易日；单票历史用裸码
    ("blocktrade", "by_date"): {"trade_date": '"2026-11-20"', "limit": "10"},
    ("blocktrade", "by_symbol"): {"limit": "10"},
    # ST/停复牌史：停复牌可带区间；简称史/时间轴按票
    ("stocks", "suspend_history"): {"begin": '"2026-01-01"', "end": '"2026-11-23"'},
    # 历史涨跌停价：n 与 begin/end 互斥，示例取 n 缺省形态
    ("stocks", "limit_price_history"): {"n": "30", "_skip": ("begin", "end")},
    # 概念：concept_members 的概念名必须给真实值（占位会打红示例执行测试）
    ("board", "concepts_of"): {},
    ("board", "concept_members"): {"name": '"白酒"', "limit": "10"},
    ("board", "concept_list"): {"limit": "20"},
    ("stocks", "name_history"): {},
    ("stocks", "lifecycle"): {},
    ("pdf_doc", "find_by_url"): {"url": '"<公告行 url 字段>"'},
    ("pdf_doc", "find_by_key"): {"file_key": '"<search() 行 file_key 字段>"'},
    # pdf_doc 读面 2026-11-24 起要求「至少给一个」定位参数，示例必须带真实 file_key
    ("pdf_doc", "read_text"): {"file_key": '"24ee091286398acebd9c44f354b64b8a73f8522f"'},
    ("pdf_doc", "read_markdown"): {"file_key": '"24ee091286398acebd9c44f354b64b8a73f8522f"',
                                   "_skip": ("source_url", "stock_code", "period")},
    ("pdf_doc", "status"): {"file_key": '"24ee091286398acebd9c44f354b64b8a73f8522f"'},
    ("futures", "snapshot"): {"fut_code": '"RB.SHF"'},
    ("futures", "bars"): {"fut_code": '"AL.SHF"', "freq": '"m"', "_skip": ("n", "begin", "end")},  # 互斥组：示例取 n 缺省形态
    ("calendar", "is_open"): {"date": '"2026-01-05"'},
    ("calendar", "next"): {"date": '"2026-01-30"', "n": "3"},
    ("margin", "market_summary"): {"limit": "6"},
    ("margin", "universe"): {"limit": "20"},
    ("statements", "compare"): {"kind": '"income"'},
    ("statements", "tree"): {"kind": '"balance"'},
    ("statements", "years"): {"kind": '"income"'},
    ("valuation", "hist_stats"): {"metric": '"pe"', "window": '"3y"'},
    # 多票估值序列：symbols 必须是 list/tuple（裸串会被拒）
    ("valuation", "daily_basic_multi"): {
        "symbols": '["600519", "000001"]', "begin": '"2026-11-01"',
        "end": '"2026-11-18"', "fields": '["pe_ttm"]'},
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
    # 指数估值趋势：window 只接受 3y/5y/10y（通用 "3m" 会产生非法示例）
    ("index", "trend"): {"window": '"5y"'},
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

# 组合接口的文档补充：说明纯计算内核所在包（自备数据时不联网、不计 EC）
COMPOSITE_NOTES: dict[str, str] = {
    "cbond": "纯计算内核在 `wmshare.cb`（valuation / rules / facts / article），"
             "自备面板数据时不联网。",
    "backtest": "纯计算内核在 `wmshare.backtest`（`run_backtest` / `ma_cross_signals` / "
                "`valuation_signals` / `valuation_by_date`），自备 bars/signals 时"
                "不联网、不计 EC。",
    "statements": "读取脚本与平台专业版三表页同构：一次 `store.query` 窗口批量取回 "
                  "fin_income / fin_balance / fin_cashflow / fin_indicator 宽表全部期次，"
                  "按「披露科目原文 × 期次」透视成行式（披露原币，季度粒度；"
                  "period=\"quarter\" 为季报全档，期次键 \"2026:Q1\"）。"
                  "不经过目录合同的单位换算与量级守护层。",
    "etf": "读取已发布的 skillhub `skhub.etf_build` 脚本（九视图：card/nav/share/div/"
           "portfolio/profile/premium/asset/rank）；不走目录合同的单位换算层，"
           "由 SDK 本地补数值守护（量级/不变量异常抛 DataError）。"
           "取数与目录函数同端点、同价计费，不省 EC；落库为原生口径（比例/百分数/亿元），禁二次换算。",
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
    "statements": [
        "rows = cli.statements.income(\"600519\", years=3)      # 利润表近 3 个年报",
        "rows[0][\"vals\"]                                      # {年份: 值}，披露原币",
        "q = cli.statements.income(\"600519\", period=\"quarter\")  # 季报全档（键 2026:Q1）",
        "h = cli.statements.indicators(\"00700\", years=2)      # 主要指标（hk）",
        "audit = cli.statements.audit(\"600519\")               # 审计意见（按年报，cn）",
    ],
    "etf": [
        "card = cli.etf.card(\"510300\")                        # 档案卡（合并档案/净值/份额/分红）",
        "nav = cli.etf.nav(\"510300\")                          # 净值 + 规模（net_asset 亿元）",
        "asset = cli.etf.asset(\"510300\")                      # 资产配置（五类占净值比，→fund_asset）",
        "rank = cli.etf.rank(\"510300\")                        # 榜单指标（→etf_rank）",
        "series = cli.etf.nav(\"510300\", mode=\"series\")       # 净值序列（默认 latest；仅 nav 消费 mode）",
    ],
}

# 返回说明覆盖（目录 shape 过粗的动态列表返回，按上游实现补字段级说明；
# pct_of_total 为百分数数值（52.3=52.3%），涨跌幅/median_pct 为小数）
RETURNS_OVERRIDES = {
    # cbond.bars 底层是 kline_window（列式 MAP），包装后返回行数组：
    # 必须覆盖 shape，否则文档会照抄 MAP 列结构。
    ("cbond", "bars"): (
        "ARR · 行 {date, open, high, low, close, volume, amount}"
        "（列式窗口按位转行；量=张，价/额=元；不复权）"),
    ("screener", "index_breadth_bins"):
        "ARR · 行 label:str（档位） count:int pct_of_total:float（百分数，52.3=52.3%）",
    ("screener", "index_breadth_bin_industries"):
        "ARR · 行 bin:str（档位） industry:str（行业代码，如 industry.S77） count:int",
}

# 返回说明兜底（FRIENDLY_INDEX 底层列不可回溯目录 shape 的核心接口）
FALLBACK_RETURNS = {
    ("statements", "balance"): "ARR · 科目行 {k: 披露科目原文, cn: 同名, vals: {期次: 值}}（披露原币）",
    ("statements", "income"): "ARR · 科目行 {k: 披露科目原文, cn: 同名, vals: {期次: 值}}（披露原币）",
    ("statements", "cashflow"): "ARR · 科目行 {k: 披露科目原文, cn: 同名, vals: {期次: 值}}（披露原币）",
    ("statements", "indicators"): "ARR · 指标行 {k: 指标原文列名, cn: 同名, vals: {期次: 值}}",
    ("indicator", "get"): "数值 · 单指标当前值",
    ("indicator", "metrics"): "MAP · {code: 值}",
    ("indicator", "basic"):
        "MAP · {pe_ttm, pb, turnover_rate, total_mv}（最新 TTM 估值；市值=元）",
    ("indicator", "financials"):
        "MAP · {roe_ttm, roe_avg, eps_ttm}（roe_avg=近3年平均；eps_ttm=归母）",
    ("futures", "get"):
        "标量 · 最新一根周期 bar 的字段值（价=元、量=手、额=万元；`$码` 透传上游口径）",
    ("futures", "snapshot"):
        "MAP · {字段: 值, date}（最新一根周期 bar；date=周期起点口径）",
    ("futures", "bars"):
        "DF · 历史K线（date 升序；日频只含交易日、无周末占位行；日频 11 字段/周月 8 字段，"
        "价=元、量=手、额=万元；date 为周期起点口径：月=当月 1 日、周=ISO 周一、日=当日）",
    ("valuation", "daily_basic"):
        "MAP · {ok, as_of, data: [{date, symbol, field, value}], meta}"
        "（8 字段长表，date 升序；as_of=表内最新行日期；"
        "meta.window.truncated 标读窗口截断）",
    ("valuation", "daily_basic_multi"):
        "MAP · {ok, as_of, data: [{date, symbol, field, value}], meta}"
        "（多票长表，行合同与 daily_basic 一致；meta.per_symbol 给每票"
        " count/oldest_scanned/truncated）",
    ("valuation", "daily_basic_coverage"):
        "MAP · {ok, as_of, data: {as_of, oldest_scanned, scan_days, scan_limit,"
        " truncated, pages}}（不拉序列，只探可用范围）",
    ("dividend", "window_stats"):
        "MAP · {dps: 每股股利合计(元/股), total: 总分红(元), count: 次数}"
        "（按除权日计、截至今天）",
    ("cbond", "bars"):
        "ARR · 行 date/open/high/low/close/volume/amount（列式转行；量=张，价/额=元）",
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
    # etf 九视图（组合门面，不回溯目录 shape；字段来自 skhub.etf_build 各 build）。
    ("etf", "card"):
        "MAP · {ok, view, symbol, quote, premium（嵌套MAP）, nav, share, div, portfolio, profile, freshness}",
    ("etf", "nav"):
        "MAP · {ok, view, symbol, latest, net_asset（{date,亿元}；常缺回落 fund_nav）}",
    ("etf", "share"):
        "MAP · {ok, view, symbol, date, fd_share（亿份）}",
    ("etf", "div"):
        "MAP · {ok, view, symbol, rows: 历史分红行}",
    ("etf", "portfolio"):
        "MAP · {ok, view, symbol, date, holdings: 最新披露季 top10（空数组=未披露）}",
    ("etf", "profile"):
        "MAP · {ok, view, symbol, profile: {基金公司/跟踪标的/费率等}}",
    ("etf", "premium"):
        "MAP · {ok, view, symbol, close, quote_date, unit_nav, nav_date, premium_pct（折溢价率%）}",
    ("etf", "asset"):
        "MAP · {ok, view, symbol, date, stock/bond/cash/other/fund_ratio（占净值%），"
        "net_asset（亿元）；按季披露}",
    ("etf", "rank"):
        "MAP · {ok, view, symbol, asof, chg_w1/m1/m3（涨幅%）, avg_amount, flow_20,"
        "premium_mean, net_asset（亿元；常缺回落 fund_nav）}",
    # 2.5：收息场景闭环（sys/income 直通/组合面，合同在 disc.income.yaml）
    ("dividend", "rating"):
        "MAP · {ok, as_of, data: {rows: [{rank, symbol, name, industry, yield_ttm,"
        " score: {total, grade, dimensions, flags}, dividend_score, gate_pass}],"
        " facets_industries}, meta}（股息分降序，过资格门块在前；COLD_CACHE 时"
        " ok=false + meta.cache=miss）",
    ("dividend", "diagnose"):
        "MAP · {ok, data: {items: [{symbol, found, score: {total, grade, dimensions,"
        " flags, parts}, floor_explain, rank, bond_yield_10y}]}, meta}（原生批量；"
        "include_history=True 另带 dividend_history/dps_rpt）",
    ("dividend", "calendar"):
        "MAP · {ok, data: {from, to, count, events: [分红事件（公告/登记/除息/到账"
        " 四日期）], stocks: {代码: {name, yield, mv}}}, meta}",
    ("dividend", "decomp"):
        "MAP · {ok, data: {items: [{code, years, total_return, price_return,"
        " dividend_return, cagr_*, monthly: 月末累计序列, yearly: 逐年表,"
        " attribution}]}, meta}（差值口径：hfq−nr，含再投效应；≤10 票批量）",
    # 2.5 并发会话：指数成分日快照（前向 PIT，同事 members_daily 门面）
    ("index", "members_history"):
        "MAP · {ok, as_of, data: {key, begin, end, members: [{symbol, name, weight,"
        " …]}}}（begin 时点的成分名单快照）",
    ("stocks", "limit_price_history"):
        "历史涨跌停价行表：date/name/close/high/low/percent/basis/limit_up/"
        "limit_down/band/rule/is_st，date 升序（basis=除权参考前收；"
        "rule=ipo/unbounded/no_price 时价格为空）",
}
# 无目录 shape 的核心门面返回说明补全（取自各方法 docstring 首句，人话口径；
# 开放平台接口文档站的「返回」段直接渲染该文本——不加 ARR·/MAP· 前缀，
# kind 由生成器按形态归类）。
FALLBACK_RETURNS.update({
    ("margin", "query"): "个股两融历史行表：trade_date/fin_buy_amt/fin_repay_amt/fin_balance 等，date 升序",
    ("margin", "latest"): "最新一日两融单行，字段同 query()",
    ("calendar", "next"): "某日之后 N 个交易日（date 升序；不足 N 个如实返回）",
    ("toplist", "by_date"): "指定交易日的全市场龙虎榜行表（席位买卖/净额/上榜原因等，date 升序）",
    ("toplist", "by_symbol"): "单票上榜历史（最近事件行，按日期升序）",
    ("index", "valuation"): "宽基估值时序（信封：data.series 为 d/pe/pb 序列，按 d 升序）",
    ("futures", "mapping"): "主力换月映射行表（主力连续码 → 当日实际合约；date 升序）",
    ("estimates", "query_forecast"): "机构盈利预测（逐年 EPS/PE，A=实际 E=预测）",
    ("estimates", "query_forecast_detail"): "盈利预测明细（机构/研究员/归母净利/评级）",
    ("estimates", "query_rating"): "评级统计（综合评级与买卖家数按窗口）",
    ("estimates", "query_reports"): "个股研报列表（标题/机构/作者/行业/报告链接）",
    ("notice", "list"): "单票公告行表：date/title/type/url/pdf_url，date 升序",
    ("notice", "recent"): "全市场近期公告行表：date/title/type/symbol/url，date 升序（cn/hk）",
    ("notice", "by_category"): "按类别查公告行表（如「回购」），date 升序（cn/hk）",
    ("notice", "find"): "按日期区间查单票公告行表，date 升序（begin/end 均含当日）",
    ("notice", "on_date"): "指定日期的全市场公告行表（date 格式 YYYY-MM-DD；cn/hk）",
    ("pdf_doc", "read_text"): "MAP：{ok, status, file_key, text, text_truncated, source_url}（正文前 4000 字预览；未就绪不入队）",
    ("pdf_doc", "read_markdown"): "MAP：财报 markdown 挂接正文 / 经营评述",
    ("pdf_doc", "status"): "MAP：文档转换状态（status/convert_policy/kind/has_markdown/task）",
    ("equity", "query_holder10"): "最新一期十大股东行表（holder_name/hold_num/hold_num_ratio）",
    ("equity", "query_holdernum"): "最新股东户数单行（end_date/hold_focus/avg_hold_amt）",
    ("equity", "query_pledge_detail"): "主要股东质押明细行表（质押家数/数量/比例/状态）",
    ("equity", "query_pledge_summary"): "公司质押比例时序（trade_date/pledge_ratio/质押股数/质押市值）",
    ("equity", "query_pledge_market"): "市场整体质押时序（全市场口径，不传标的）",
    ("equity", "query_pledge_industry"): "行业质押比例（全市场按行业，不传标的）",
    ("equity", "query_pledge_org"): "质押机构分布（质权人类型维度，不传标的）",
    ("equity", "query_institution_detail"): "机构持股明细（机构 × 报告期持股数/市值/占比）",
    ("equity", "query_institution_summary"): "机构持仓占比时序（机构家数/合计占比/环比变动）",
    ("equity", "query_hgt"): "沪港通持股行表（机构/持股数/市值/占比变动）",
    ("equity", "query_national_team"): "国家队持股（证券主体 × 报告期持股占比）",
    ("equity", "query_release"): "限售解禁日程行表（解禁日期/数量/占比/类型）",
    ("equity", "query_buyback_plan"): "回购方案全览单行（进度/价格上限/金额上限/起始日）",
    ("equity", "query_buyback_detail"): "回购执行明细单行（已回购股数/金额/公告日）",
    ("equity", "buyback_snapshot"): "回购六口径快照（exec/plan × 近1年/累计 × 含/不含注销式）",
    ("equity", "query_reorg"): "并购重组行表（进度/交易金额/公告日）",
    ("equity", "query_related_trade"): "关联交易行表（关联方/交易金额/公告日）",
    ("equity", "query_concert"): "一致行动人行表（组合名称/合计持股比例）",
    ("equity", "query_guarantee"): "对外担保行表（担保方/金额/是否履行完毕）",
    ("equity", "query_litigation"): "诉讼记录行表（案名/涉案金额/原告/被告）",
    ("equity", "query_violation"): "违规处罚行表（类型/处分/罚款金额）",
    ("equity", "query_executives"): "高管名册行表（姓名/职务/薪酬/持股）",
    ("equity", "query_exec_change"): "高管增减持最新一行（日期/高管/变动股数/均价）",
    ("equity", "query_exec_change_at"): "指定报告期的高管增减持单行",
    ("equity", "query_capital_change"): "股本结构最新一行（总股本/流通股本）",
    ("equity", "query_capital_change_at"): "指定报告期的股本结构单行",
    ("intl", "query_ccass"): "港股 CCASS 经纪持仓行表（经纪商/持股数/占发行股比）",
    ("intl", "query_shareholders"): "港股主要股东/董事权益行表（股东/持股数/占总股比）",
    ("intl", "query_org_rating"): "港股机构评级行表（机构/评级/目标价，披露币种）",
    ("intl", "query_profit_forecast"): "港股盈利预测（披露原文中文键：财政年度/纯利/每股盈利等）",
    ("intl", "query_sellshort"): "港美沽空（沽空量/占比，shares=股）",
    ("intl", "issue_info"): "美股发行信息快照（发行价/数量/日期，以披露源为准）",
    # 3.6：两次取数的组合面（不新增目录函数，returns 靠本表兜底）
    ("kline", "adj_factor"):
        "DataFrame · date/factor（累计复权因子 = 后复权收盘 ÷ 不复权收盘，"
        "ipo 起算；需归一因子时除以末值）",
    ("index", "bars"):
        "DataFrame · date/open/high/low/close/volume/amount/percent（SDK 聚合；"
        "date=周期内最后交易日，含未走完的当前周期）",
})


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
    cls_descs = parse_docstring(inspect.getdoc(cls))[2]
    if not descs:  # 参数说明全在类 docstring 时（如 StatementsApi 旧式）
        descs = cls_descs
    else:
        # 方法级与类级按参数名合并：方法 docstring 只写新增参数时，
        # 其余参数（scope/years 等）仍继承类级说明，不落「—」
        _merged = dict(cls_descs)
        _merged.update(descs)
        descs = _merged
    for p in out:
        p.desc = descs.get(p.name, "")
    return out


def method_doc(cls: type, method: str) -> tuple[str, str]:
    return parse_docstring(inspect.getdoc(getattr(cls, method)))[:2]


# symbol 参数的示例值：默认是 A 股代码；转债/指数/港美股命名空间用各自真实代码。
SYMBOL_EXAMPLES = {
    "cbond": '"113050"',
    "index": '"index.hs300"',
    "intl": '"00700"',
}


def method_example(ns: str, method: str, params: list[Param]) -> str:
    """机械生成调用示例：symbol 位置用该命名空间的真实代码，其余取示例值表。

    无示例值的必填参数以 … 占位。symbol 不能一律写 "600519"——转债/指数接口
    用股票代码会是跑不通的示例。
    """
    overrides = METHOD_EXAMPLE_VALUES.get((ns, method), {})
    values = {**EXAMPLE_VALUES, **overrides}
    skip = overrides.get("_skip") or ()  # 显式不参与示例的参数（互斥组，如 n vs begin/end）
    parts: list[str] = []
    if any(p.name == "symbol" for p in params):
        parts.append(SYMBOL_EXAMPLES.get(ns, '"600519"'))
    for p in params:
        if p.name == "symbol" or p.name in skip:
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


# 上游 inventory 的字段中文名滞后于 SDK 换算：SDK 已把「手」×100 成「股」、
# 「亿」×1e8 成「元」，但字段 cn 仍写原生口径。文档与 openapi 统一在此归一，
# 避免 docs/API.md 顶部「volume=股、金额=元」与输出字段表 / schema 自相矛盾。
FIELD_CN_UNIT_FIX = {"量(手)": "量(股)", "市值亿": "市值(元)"}


def field_cn(f: dict) -> str:
    """字段中文名（按 SDK 换算后口径归一）。"""
    cn = f.get("cn", "") or ""
    return FIELD_CN_UNIT_FIX.get(cn, cn)


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
        cn = field_cn(f)
        if cn:
            prop["description"] = cn
        props[f["name"]] = prop
    return {"type": "object", "properties": props}
