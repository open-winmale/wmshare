# 服务端候选与卫生窗待办（未排期）

> 仓纪律：`CHANGELOG.md` 的 `[Unreleased]` 保持为空（发版抽取器要求，见
> `tests/test_changelog_section.py`），未排期项一律登记在本文件。
> 本清单由 2026-11-19 消费端盘点产出，均不改现有合同；落地后应在此标记
> 状态并同步 CHANGELOG 的对应版本段。

## `valuation.daily_basic` 增强候选

| 候选 | 预期效果 | 状态 |
|---|---|---|
| 分页 + `truncated` 标志 | 消除 >1,500 日（≈6 年）区间的静默缺席 | **已落地 2.4.0**（2026-11-19，`meta.window` + SDK 自动翻页） |
| `begin/end` ts 下推 | 现为 XS 拉全窗后过滤，EC 随扫描而非请求跨度 | 未排期（**依赖 kernel 日文档级过滤**，store_query 按 per-symbol 键整读，SDK/script 侧无法下推） |
| coverage API | 可用日期/符号发现 | **已落地 2.4.0**（`cli.valuation.daily_basic_coverage`） |
| 多票批量路由 | 消灭逐票调度开销（EC 仍按票计价） | **已落地 2.4.0**（`valuation.daily_basic_multi` + SDK 门面；全市场扩容仍前置 wmshare-qlib 扩容评审） |
| `estimate_cost` 再校准 | 表累积 >3y 后全史 18,317 EC 档失真 | **已校准 2.4.0**（分页后不再单次全史；多票按票数线性） |

## 卫生窗待办

- ~~**kernel 读面 `limit≤0→200` 默认对其他 catalog 的影响**~~ **已排查闭环
  （2026-11-19）**：逐域实测 `limit=0` 行为——`kline.query_bars` 返 **0 行**、
  `moneyflow.query_bars` 返 200 行（kernel 默认，非域默认 20）、
  `bonus.query_list` 恰好 33 行（< 200 默认，无差异）。已在包装层统一归一：
  `kline.store_window_limit`（≤0→120，覆盖 5 个窗口入口）、
  `moneyflow.store_limit`（≤0→20，含 anchor 变体）、`bonus.store_query` 内联；
  `forecast` 三个入口原已走 `clamp_limit`；`intl/estimates/margin/equity/
  filings` 用 `{"unwrap":"list"}` 无 limit 参数，不受影响。
