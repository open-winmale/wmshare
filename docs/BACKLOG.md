# 服务端候选与卫生窗待办（未排期）

> 仓纪律：`CHANGELOG.md` 的 `[Unreleased]` 保持为空（发版抽取器要求，见
> `tests/test_changelog_section.py`），未排期项一律登记在本文件。
> 本清单由 2026-11-19 消费端盘点产出，均不改现有合同；落地后应在此标记
> 状态并同步 CHANGELOG 的对应版本段。

## `valuation.daily_basic` 增强候选

| 候选 | 预期效果 | 状态 |
|---|---|---|
| 分页 + `truncated` 标志 | 消除 >1,500 日（≈6 年）区间的静默缺席（LIMITS §1） | 未排期 |
| `begin/end` ts 下推 | 现为 XS 拉全窗后过滤，EC 随扫描而非请求跨度；下推后读成本随窗口走 | 未排期 |
| coverage API | 可用日期/符号发现（现仅 envelope `as_of` 可探） | 未排期 |
| 多票批量路由 | 消灭逐票 1,707 EC 地板（扩全市场前置于 wmshare-qlib 仓 docs/full-market-expansion-review.md 扩容评审） | 未排期 |
| `estimate_cost` 再校准 | 表累积 >3y 后全史 18,317 EC 档失真 | 未排期 |

## 卫生窗待办

- **kernel 读面 `limit≤0→200` 默认对其他 catalog 的影响**：2026-11-19 在
  `valuation.daily_basic` 上暴露为读窗回归（当日修复，见 CHANGELOG 2.3.1）；
  同一默认作用于全部 V2 catalog 的 `store.query` 读路径，哪些业务依赖
  「传 0 = 不限量」语义未逐一排查，卫生窗过一遍。
