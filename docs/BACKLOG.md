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
| 1 | 期货日线/周月线历史序列 | 补暴露面 | **已上线**（`cli.futures.bars`，2.9.0；上游另有 `futures.query_bars` store 读面——低成本长窗+结算/持仓字段，暴露待排） |
| 2 | 官方储备（外汇储备/黄金储备/SDR） | 新数据（先核 FRED/OWID 复用） | airflow → script → wmshare | 待启动 |
| 3 | 外汇（人民币中间价/日线/基础信息） | 新数据 | airflow → script → wmshare | 待启动 |
| 4 | FRED 美宏观序列暴露 | 纯暴露层（`skhub.fred_build` 已有） | wmshare | 待启动 |
| 5 | 股东人数历史序列（现仅最新值） | 补历史读面 | script → wmshare | 先核底层留史 |
| 6 | 每日涨跌停价格 | 派生评估（交易所规则 vs 落字段） | 评估后定 | 待评估 |
| 7 | 概念板块（分类/成份/每日行情） | 新数据 | airflow → script → wmshare | 待启动 |
| 8 | 大宗交易 | 新数据 | airflow → script → wmshare | 待启动 |
| 9 | ST/停复牌变动历史（现仅时点旗标） | 新数据 | airflow → script → wmshare | 待启动 |

长线另立项（不入常规批次）：期权（合约/行情）、历史分钟线（平台级大工程）。
不做清单：LOF/场外/货基、游资名录/热榜/竞价明细、第三方源资金流变体、中信行业、
韩国宏观、组合 CRUD、tick、实时 WS 推送。
