# 服务端候选与卫生窗待办（未排期）

> 仓纪律：`CHANGELOG.md` 的 `[Unreleased]` 保持为空（发版抽取器要求，见
> `tests/test_changelog_section.py`），未排期项一律登记在本文件。
> 本清单由 2026-11-19 消费端盘点产出，均不改现有合同；落地后应在此标记
> 状态并同步 CHANGELOG 的对应版本段。

## `valuation.daily_basic` 增强候选

| 候选 | 预期效果 | 状态 |
|---|---|---|
| 分页 + `truncated` 标志 | 消除 >1,500 日（≈6 年）区间的静默缺席 | **已落地 2.4.0**（2026-11-19，`meta.window` + SDK 自动翻页） |
| `begin/end` ts 下推 | 现为 XS 拉全窗后过滤，EC 随扫描而非请求跨度 | **已落地 2.4.1**（2026-11-19，kernel `window`+`anchorTs` 锚点下推；13 天窗口 11,944→249 EC，实测 6 标的 × 6 跨度逐行等价）。~~原结论「依赖上游 kernel 能力」是未实测的误判~~ |
| coverage API | 可用日期/符号发现 | **已落地 2.4.0**（`cli.valuation.daily_basic_coverage`） |
| 多票批量路由 | 消灭逐票调度开销（EC 仍按票计价） | **已落地 2.4.0**（`valuation.daily_basic_multi` + SDK 门面；全市场扩容仍前置 wmshare-qlib 扩容评审） |
| `estimate_cost` 再校准 | 表累积 >3y 后全史 18,317 EC 档失真 | **已校准 2.4.0**（分页后不再单次全史；多票按票数线性） |

## 卫生窗待办

- ~~**【P0 数据正确性，2026-11-19 消费端发现】`kline.bars(sym, n=5, adj=None)`
  对 600519 返回后复权价**~~ **已修复并 live 验证（2026-11-19）**：
  `close` 末值曾是 **12473.67**（真实不复权收盘 **1442.66**），整 5 行都被污染。
  **根因不在 n=5，而在复权口径串号**——任何「同票同窗口、不同 adj」的调用都会
  双向互相污染（先调者胜）：
  `kline.rows_fingerprint` 的结果缓存键只有 `symbol + 行数 + 首末采样时间戳`，
  nr/qfq/hfq 读三个不同库但这三项完全相同 → 键必然碰撞。`n=5` 只是恰好撞上
  一条已被 hfq 填过的旧条目，所以看起来像「n=5 专属 bug」。

  修复过程（script 仓，两轮）：`893c7267` 先把 `catalog` 加进指纹，但 XS 侧
  `rows[0].catalog` **实测恒为 nil**（v2.Rec 不含该字段），等于加了空串、无效；
  `ee87a56e`（v4）改用**行内数值指纹**（首末行 open/close/volume/amount 采样）
  ——口径不同则价格差达复权因子量级，键必不同；日频 EOD 不可变，命中率不受损。

  live 复验（2026-11-19，部署后）：
  `kline.bars("600519", n=5, adj=None)` → **1442.66**（正确）；
  `n=203` 的 nr/hfq 比值 **8.4464**（≈复权因子，口径隔离生效）；
  双向顺序测试（先 nr 后 hfq / 先 hfq 后 nr）均不再串号。
  交叉回归（消费端独立复验，4 标的 × 5 窗口 × 2 口径 = 20 组）：0 不一致，
  各票复权因子清晰分离（600519 ≈8.65×、000858 ≈21.2×、601318 ≈3.30×、
  600036 ≈6.66×）；wmshare-qlib `dump-history --live` 的 hfq+raw 双取路径
  恢复（`integrity.ok=true`、`null_values=0`、EC 3,712）。

  残留提醒：`validate=False` 下 SDK 仍不拦量级异常（这是该开关的定义），
  但错价源头已消除；`_raw=True` 始终可作独立核对口径。


- ~~**kernel 读面 `limit≤0→200` 默认对其他 catalog 的影响**~~ **已排查闭环
  （2026-11-19）**：逐域实测 `limit=0` 行为——`kline.query_bars` 返 **0 行**、
  `moneyflow.query_bars` 返 200 行（kernel 默认，非域默认 20）、
  `bonus.query_list` 恰好 33 行（< 200 默认，无差异）。已在包装层统一归一：
  `kline.store_window_limit`（≤0→120，覆盖 5 个窗口入口）、
  `moneyflow.store_limit`（≤0→20，含 anchor 变体）、`bonus.store_query` 内联；
  `forecast` 三个入口原已走 `clamp_limit`；`intl/estimates/margin/equity/
  filings` 用 `{"unwrap":"list"}` 无 limit 参数，不受影响。

## 已发布面遗留（登记不装死）

- **2026-11-25 P0：估值宽表市值族前视/冻结（已修，待部署+repair）**：
  `valuation.daily_basic` 的 `total_mv/circ_mv/turnover_rate/dv_ttm` 此前用
  metric 层 `$MV_LAST/$MV_FREE_LAST/$TURNOVER_RATE_LAST/$BONUS_RATE_TTM_LAST`
  配 `AT(锚日, ITER(...))` 求值。这四个码的 memo cachetype 是 symbol 级、定义里
  带 `LAST(store.latest(...))`（`../script/sys/metric/shared/kline.xs:154,182`），
  **取的是求值时刻的 K 线 tip**——`AT` 只改求值锚、不会让 `LAST` 回到锚日。
  实测后果（600519，总股本 1,250,081,601）：11-19/11-20/11-23 三行的
  `total_mv` 分别等于 11-20/11-23/11-24 收盘 × 股本（前视一天，误差 0）；
  11-06～11-18 九个交易日四字段完全冻结（11-18 事故修复把同一 tip 写进多行）。
  修法：行日期由 K 线交易日决定，市值族从同一行的 `close` 与**当日**股本算出
  （`total_mv = close × 当日总股本`），结构上不可能错位；同批新增
  `total_share/float_share` 两列使行内自洽可验（`total_mv / total_share == close`）。
  防复发：`daily_data_guard` 新增 `valuation_daily_mv_consistency` detector
  （行内自洽 + 跨日不冻结 + **数据日不超前**，近 10 交易日抽样 300 票）。
  存量修复：`pipeline.cn.valuation_daily.manual` 传 `{"repair_mv_days": 60}`
  重写近 N 个交易日整行（2026-11-25 已执行：600519 等 10 票 × 6 交易日抽查
  `total_mv / total_share` 与当日收盘 **diff 0.0000%**，全票 0 错值）。
  repair 窗口中更早的历史行仍保持旧口径（诚实缺列 `total_share/float_share`），
  市值族在窗口外不再保证行内自洽——需要用旧口径时请以 `as_of` 与 repair 窗口为准。
- **2026-11-25 验收发现的第二个缺陷：无行情支撑的「当日伪行」（已修，待部署）**：
  首轮 repair 成功后仍有一半标的（实测 3,069 / 5,695 票）带
  `trade_date=2026-11-25` 的行，形态固定为「3~4 个字段、无
  `total_share/float_share`、无 `pe_ttm/pb/ps/pr`，`total_mv` **严格等于**
  前一日值」（1,408/1,408 抽样全中）——旧口径 `$*_LAST` 冻结 tip 的另一面。
  11-25 的 K 线要到 16:10 才落库，这些行没有任何行情支撑，却被 clean 洗成
  V2 文档把 `as_of` 顶到 11-25（API 面 `as_of=2026-11-25` 而当日无行）。
  根因：`_merge_raw_doc_rows` 的「旧行按 trade_date 全保留」在**整窗重算**
  模式下也是无条件保留，所以 repair 只重写 K 线覆盖的交易日、伪日永不清除。
  修法：`replace_symbol_rows(..., authoritative_window=(lo, hi))`——整窗重算
  （backfill/repair）时，`day >= lo` 的旧行必须由本轮结果背书，本轮没有即删；
  `lo` 取「N 个交易日前的日历日」（**不能取结果最小日**，否则 backfill 的
  PE-only 历史会被全删）。增量模式不传窗口（只产前沿+补行，不能拿它删别日）。
  检测：detector 增加 `phantom_symbols/phantom_count`（行的 `trade_date` 晚于
  「交易日历里已过 16:10 的最近交易日」即判伪日，占比 >1% → error）。
- **`float_share` 与 `total_share` 相等（上游口径）**：股本变动快照披露的
- **`float_share` 与 `total_share` 相等（上游口径）**：股本变动快照披露的
  「流通股份」实测恒等于「总股份」；真实可流通口径是「无限售股份」，当前不进表。
  需要自由流通市值时暂无逐日源（`daily_basic.circ_mv` 因此等于 `total_mv`）。
- **数据质量审计 2026-11-24 六项结论**（来源 `.internal/data_quality_report.json`，
  处置已在版本线重置前随 3.7.1 落地，随 4.0.0 基线继承）：
  - `valuation.daily_basic` / `daily_basic_multi` date 非升序：**已修**（门面按
    `(date, field)` / `(symbol, date, field)` 排序；服务端原生为日期降序）。
  - `index.members_history` 空窗口 `ok=False`：**非缺陷**——契约写明 `count==0`
    表示「尚无快照」；物化表快照自 2026-11-20 起，更早窗口空是诚实的（live：
    11-01..11-20 返 300 行、6 月窗口 0 行）。
  - `notice.read_text` `no_pdf_url`：**非缺陷**，无 PDF 链接的受控结果（note 引导传 url）。
  - `pdf_doc.read_text/read_markdown` 空参 `ok=False`：**审计误用**（无参数调用）；
    门面已补 `UsageError(code="params")` 前置校验，不再打上游。
  - `pdf_doc.find_by_url` 全失败：**审计用错字段**；实测传 `search` 行的
    `source_url`（形如 `pdf_doc://filing/600519/2018-12-31`）可命中。
  - `pdf_doc.search` `text_chars` 超声明：**已修**——上限 1e7→5e7（巨型年报实测
    1,450 万字符）。
  - `etf.nav` `net_asset` 差 6 个量级：**上游异常**（2026-11-24 全 ETF 实测 1e18
    量级，疑管道口径变更）；门面把该字段置空并在 `data.note` 说明，净值/份额
    照常返回，等上游修复。
- **汇率/储备未纳入新鲜度看板**：`../airflow/data_monitor/stats_config.py` 的
  `STATS_CHECKS` 无 `currencyrate` 与 `currency.reserve.*` 条目（上游 Go 采集链已
  paused）。故 `docs/DATA_CALENDAR.md` 不含这两项——**不伪造新鲜度条目**，
  待上游恢复生产后补登记。
- **美宏观无新鲜度阈值**：`fred.*` 同样不在 `STATS_CHECKS`；序列更新频率随
  各序列原生频率（D/W/M/Q）而异，单一阈值无意义。点序列取回后以末点日期自判。

## 上游指标目录缺席（登记待办，SDK 侧不伪造）

- `$BOND_YIELD_GOV_10Y`（十年国债收益率）：服务端指标层已在产（`AT(sym, $BOND_YIELD_GOV_10Y)`
  live 实测 2026-11-20 返回 0.0168），但上游 `metric-memo-catalog.json` 未收录——wmshare
  指标目录（2983 码）查不到该码。消费方：`income.diagnose`/`income.rating_rows` 的
  bond_yield_10y 字段（服务端直出不受影响，仅 SDK 指标目录检索缺）。同 `$BUYBACK_AMT*`
  缺席先例，登记上游待办，SDK 不伪造。

## 覆盖面补齐队列（2026-11-23 对标盘点，逐项全链路）

> 与主流 token 制数据 SDK 的全量对标（内部矩阵，不入库）后产出的缺口队列。
> 每项 = 一个独立覆盖单元，走完整链路（airflow 采集 → script 读面 → 暴露门禁），
> 一个数据一个数据补，不并批。

| # | 数据项 | 定性 | 链路 | 状态 |
|---|---|---|---|---|
| 1 | 期货日线/周月线历史序列 | 补暴露面 | wmshare 目录 | **已上线**（`cli.futures.bars` 门面 2.9.0 + `futures.query_bars` store 直读进目录，2026-11-23——全历史长窗/结算·持仓字段/同日复跑缓存，分工见 API.md 期货节） |
| 2 | 官方储备（外汇储备/黄金储备/SDR） | **已上线 3.0+**：`cli.macro.reserves/reserves_history/reserves_asof`（月频外汇+黄金，值=美元数值）；**遗留**：SDR 上游无生产者（`available=False` 如实标注）、黄金仅市值口径无吨数/盎司、国别维度待走 FRED 目录核（丢队列④） | script → wmshare | 已上线（部分） |
| 3 | 外汇（人民币中间价/日线/基础信息） | **已上线 3.0+**：`cli.fx.rate/history/bars/list`（采集零新增，数据日更在库）；口径=每 1 单位外币折人民币（上游每 100 外币已 /100 归一），中间价与中行牌价分列 | script → wmshare | 已上线 |
| 4 | FRED 美宏观序列暴露 | **已上线（3.2）**：`cli.us_macro.topics/search/series_meta/points`（精选 88 条 × 11 主题）；单位随序列而变（读 `series_meta().units`）、空值不补 0、需授权序列 `has_data=False` 永不抓取。**遗留**：web 页面读面 `fred.points`/`fred.series` 是「新→旧 + 期间码 year」契约，已标 internal 不进 SDK | wmshare（域 yaml + fred 读面） | 已上线 |
| 5 | 股东人数历史序列（现仅最新值） | **已上线 3.2**：`cli.equity.query_holdernum_history(symbol, limit)` 读 raw 层单票多期档（600519 实测 108 期、2001-12-31 起），日期升序、比例=小数、与 `query_holdernum` 同口径；单票上限 300 期 | script 历史读面 → wmshare 条目 | 已上线 |
| 6 | 每日涨跌停价格 | **已上线 3.2（当日快照）+ 已实现历史序列（3.4.0 已发版）**：快照 `cli.stocks.limit_price/limit_prices` 规则价=前收盘×(1±带宽) 四舍五入到分，带宽按代码号段（30x/68x=20%、北交所=30%、其余=10%）；历史 `cli.stocks.limit_price_history` 逐日给 basis/limit_up/limit_down/band/rule，basis 用 hfq/nr 因子还原交易所除权参考价（实测 600519 2024-06-19 得 1490.62），主板 ST 5%（至 2026-05-05）/10%（2026-05-06 起；2026 年样本实测切换日）、创业板 2020-08-24 前 10% 后 20%、科创板 20%、北交所 30%，IPO 前 N 日 rule=ipo。**遗留**：当日快照按板块带宽（主板 ST 10%，与 2026-05-06 起制度一致）且除权日仍用原始前收（全市场索引无 hfq 因子）；历史退市整理期无逐日源 | script 派生 → wmshare 暴露 | 已上线（快照+历史） |
| 7 | 概念板块（分类/成份/每日行情） | **已上线 3.2 + 3.3 + 3.5**：①资金流 `cli.board.moneyflow/moneyflow_last`（ths 概念/行业 + dc 概念·行业）；②概念标签 `cli.board.concepts_of`（单票 tags，≈90 EC）与 `concept_members`（名称包含匹配，代码升序；冷 ≈8.1 万 EC、当日 memo ≈200）；③目录 `cli.board.concept_list`（3.5：周更物化档 memo 点查 ≈110 EC，周六 09:00 片 / 09:15 merge，最多滞后一周；members 物化序、门面本地升序）。~~暂缓~~已闭环：物化一次实测 ≈318 万 EC（81,875 对；XS 逐元素 ~5-10 EC/op 是地板，投影 ≈15 万 只占零头），日更 ≈8.8 亿/年不可持续 → **周更 cron**（周六 09:00 片 / 09:15 merge，TTL 720h，年 ≈1.2 亿）——「cron 预算另议」落点，2026-11-24 实测后按推荐默认执行 | 小步暴露 → script cron 物化（airflow 零改动） → wmshare 域 | 已上线（资金流+标签/成份+目录） |
| 8 | 大宗交易 | **已上线 3.3**：`cli.blocktrade.by_date/by_symbol`（额=元/量=股/价=元；单日榜成交额降序、单票 date 升序）；2010 至今全量回补 4,100/4,100 交易日、67.9 万行；B 股 price 为外币、amount 为人民币（口径差已在接口 notes 注明，不做汇率换算） | airflow → script → wmshare | 已上线 |
| 9 | ST/停复牌变动历史（现仅时点旗标） | **已上线 3.3**：`cli.stocks.suspend_history/name_history/lifecycle`（停复牌按交易日、简称变更按生效日；ST 段由简称含 ST 判定；时间轴 rename/st_enter/st_exit/suspend/resume 日期升序）；采集 1999 起停复牌 644k 行 + 2000 起简称变更 13k 行，单票读面走清洗档点查（≈200-800 EC）；**遗留**：历史涨跌停价（⑥）已由 3.4 历史序列闭环（namechange ST 段 + hfq/nr 因子），无需再续接 | airflow → script → wmshare | 已上线 |
| 10 | 金交所现货（Au/Ag/Pt 日线） | **已上线 4.2.0**：`cli.gold.symbols/bars/query_bars`（价=元/克、量=千克、额=元；口径实测 `volume×1000×close ≈ amount`）。数据本就在库日更（airflow `market.cn.gold_spot_daily` 17:30 → `mkt.futures_kline` exchange=SGE），此前读不到的原因是 `futures.norm_symbol` 会 UPPER 品种段，而 V2 键大小写敏感（`cn.Au99.99.SGE`）→ 恒返 0 行。独立成域而非改 futures 归一器（后者会波及全部期货键）。**遗留**：`percent` 由 `change1` 派生（上游 pre_settle/pre_close 恒 0、percent 为 nil）；远期/租赁报价合约（`*.FWD`）无 OHLC 不入库 | script → wmshare（采集零新增） | 已上线 |
| 11 | 每日股本（total_share/float_share） | **已上线 4.1.0**：并入 `valuation.daily_basic` 字段（与市值族同源，`total_mv = close × total_share` 行内恒等）。**遗留**：上游披露的「流通股份」恒等于「总股份」，真实可流通口径是「无限售股份」——无逐日源，故 `circ_mv == total_mv` | wmshare（airflow 物化） | 已上线（口径受限） |
| 12 | 复权因子（累计 hfq/nr） | **已上线 4.2.0**：`cli.kline.adj_factor`（组合面，两次取数内积；实测 600519 近三日 8.6469 恒定）。**口径**：累计因子（ipo 起算、长期递增）；归一因子 `factor / factor.iloc[-1]`。**遗留**：美股 hfq 无国内因子源，factor 恒 1 | wmshare（组合面，零目录改动） | 已上线 |
| 13 | 指数周/月 K 线 | **已上线 4.2.0**：`cli.index.bars(key, freq="W"/"M")`（SDK 聚合；上游不派生指数周月 K）。date=周期内最后交易日，percent 由周期末收盘重算，含未走完的当前周期 | wmshare（组合面，零目录改动） | 已上线 |

## 本轮对标复验结论（2026-11-25）

- **已闭环、无需再做**：期货仓单/结算/持仓（3.7.0）、可转债 P1 四项（评级/票息/
  十大持有人/转股结果均在 `cbond.terms`/`holders`/`latest_share`）、LPR
  （`$LPR_1Y/$LPR_5Y` 在指标目录）。
- **无上源、登记不做**：SHIBOR（script/airflow 全仓无落库）、沪深港通十大成交股
  （上游无落库 + 交易所披露口径已收紧）、基金公司/基金经理主档（无源）、
  龙虎榜营业部席位明细（`sys/toplist/query.xs` 明示上游无落库）、
  十大流通股东（只有总口径）、增发/IPO/退市史（`disc.events` 只覆盖业绩披露，
  `stocks.lifecycle` 明示无上市/退市日期源）、高管简历（`query_executives` 无该字段）。
- **待探针**：行业/策略/宏观研报——airflow 有 manual 采集 DAG，落库路径未证；
  若已落库是 0.5 天的纯暴露，否则不做。

长线另立项（不入常规批次）：期权（合约/行情）、历史分钟线（平台级大工程）。
不做清单：LOF/场外/货基、游资名录/热榜/竞价明细、第三方源资金流变体、中信行业、
韩国宏观、组合 CRUD、tick、实时 WS 推送、DCE 仓单（反爬）。
