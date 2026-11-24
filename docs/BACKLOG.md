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

- **3.0.1 发布说明漏记外汇/储备**：`[3.0.1]` 段只写期货修复，`cli.fx` 四接口与
  `cli.macro.reserves*` 三接口零字提及（代码与 `market.fx.yaml` 确在该 tag 内）。
  处置：**下一个版本的 CHANGELOG 段补记**（不改已发布的 Release 正文）。
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
| 6 | 每日涨跌停价格 | **已上线 3.2（当日快照）+ 已实现历史序列（待 3.4.0 发版）**：快照 `cli.stocks.limit_price/limit_prices` 规则价=前收盘×(1±带宽) 四舍五入到分，带宽按代码号段（30x/68x=20%、北交所=30%、其余=10%）；历史 `cli.stocks.limit_price_history` 逐日给 basis/limit_up/limit_down/band/rule，basis 用 hfq/nr 因子还原交易所除权参考价（实测 600519 2024-06-19 得 1490.62），主板 ST 5%（至 2026-05-05）/10%（2026-05-06 起；2026 年样本实测切换日）、创业板 2020-08-24 前 10% 后 20%、科创板 20%、北交所 30%，IPO 前 N 日 rule=ipo。**遗留**：当日快照按板块带宽（主板 ST 10%，与 2026-05-06 起制度一致）且除权日仍用原始前收（全市场索引无 hfq 因子）；历史退市整理期无逐日源 | script 派生 → wmshare 暴露 | 已上线（快照+历史） |
| 7 | 概念板块（分类/成份/每日行情） | **已上线 3.2 + 3.3**：①资金流 `cli.board.moneyflow/moneyflow_last`（ths 概念/行业 + dc 概念·行业）；②概念标签 `cli.board.concepts_of`（单票 tags，≈90 EC）与 `concept_members`（名称包含匹配，代码升序；冷 ≈8.1 万 EC、当日 memo ≈200）；成份为当前截面、历史 PIT 不可得。**暂缓**：`concept_list` 目录需全市场 tags 投影，实测冷态 ≈300 万 EC——不适合直连暴露，待改为日更物化档（cron 预算/权限另议） | 小步暴露 → airflow 新采集 → wmshare 域 | 已上线（资金流+标签/成份） |
| 8 | 大宗交易 | **已上线 3.3**：`cli.blocktrade.by_date/by_symbol`（额=元/量=股/价=元；单日榜成交额降序、单票 date 升序）；2010 至今全量回补 4,100/4,100 交易日、67.9 万行；B 股 price 为外币、amount 为人民币（口径差已在接口 notes 注明，不做汇率换算） | airflow → script → wmshare | 已上线 |
| 9 | ST/停复牌变动历史（现仅时点旗标） | **已上线 3.3**：`cli.stocks.suspend_history/name_history/lifecycle`（停复牌按交易日、简称变更按生效日；ST 段由简称含 ST 判定；时间轴 rename/st_enter/st_exit/suspend/resume 日期升序）；采集 1999 起停复牌 644k 行 + 2000 起简称变更 13k 行，单票读面走清洗档点查（≈200-800 EC）；**遗留**：历史涨跌停价（⑥）已由 3.4 历史序列闭环（namechange ST 段 + hfq/nr 因子），无需再续接 | airflow → script → wmshare | 已上线 |

长线另立项（不入常规批次）：期权（合约/行情）、历史分钟线（平台级大工程）。
不做清单：LOF/场外/货基、游资名录/热榜/竞价明细、第三方源资金流变体、中信行业、
韩国宏观、组合 CRUD、tick、实时 WS 推送。
