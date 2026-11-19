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

- **【P0 数据正确性，2026-11-19 消费端发现】`kline.bars(sym, n=5, adj=None)`
  对 600519 返回后复权价**：`close` 末值 **12473.67**（真实不复权收盘
  **1442.66**），整 5 行都被污染；`n=3/4/6/7/10` 全部正常，`000858`/`601318`/
  `600036` 的 `n=5` 也正常 → 疑为服务端某已物化 **hfq 切片与 n=5 请求的缓存键
  碰撞**（命中后按未复权口径返回，静默错价）。附证：该批
  `volume×close/amount = 8.70`（≈复权因子），而 SDK 单位不变量只在
  `validate=True` 时拦截——默认客户端会直接 `DataError`，`validate=False`
  则**静默拿到错价**。同时实测 `adj` 参数在 n=3/4/6 上完全无效（三种 adj 返回
  同值），需一并核查。复现（2.4.0 源码，2026-11-19 三次稳定复现）：

  ```python
  c = wmshare.Client.from_env(validate=False)
  c.kline.bars("600519", n=5, adj=None)["close"].iloc[-1]   # 12473.67  ← 错
  c.kline.bars("600519", n=4, adj=None)["close"].iloc[-1]   # 1442.66   ← 对
  ```

  影响面：任何消费 `n=5` 窗口的调用方会拿到静默错价（wmshare-qlib 的
  hfq+raw 双取若落在该窗口，factor 计算随之失真）。**未修**，需服务端侧排查
  缓存键；在此之前消费端不要把 `n=5` 当作安全窗口。

- ~~**kernel 读面 `limit≤0→200` 默认对其他 catalog 的影响**~~ **已排查闭环
  （2026-11-19）**：逐域实测 `limit=0` 行为——`kline.query_bars` 返 **0 行**、
  `moneyflow.query_bars` 返 200 行（kernel 默认，非域默认 20）、
  `bonus.query_list` 恰好 33 行（< 200 默认，无差异）。已在包装层统一归一：
  `kline.store_window_limit`（≤0→120，覆盖 5 个窗口入口）、
  `moneyflow.store_limit`（≤0→20，含 anchor 变体）、`bonus.store_query` 内联；
  `forecast` 三个入口原已走 `clamp_limit`；`intl/estimates/margin/equity/
  filings` 用 `{"unwrap":"list"}` 无 limit 参数，不受影响。
