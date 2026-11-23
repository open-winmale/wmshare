# 限制与配额

本文汇总 SDK 侧会主动拦你的硬限制、服务端配额语义与取数配方。目标是把「为什么被拦、
怎么绕」写在调用之前，而不是等报错。数值以代码常量为准（`tests/test_contract_docs.py`
校验本文与实现一致）。

## 1. 单次调用

| 限制 | 默认值 | 行为 | 突破方式 |
|---|---|---|---|
| `Client(max_limit=500)` 单次行数/标的数 | **500** | 批量标的数超限抛 `LimitError(code="limit")` | `batch_all()` 自动分批；或构造时显式放开 |
| 区间查询行数上限 | **10,000**/片 | `kline.bars` 日 K 与 `moneyflow.bars` 区间自动锚点切片补齐（每片 ≤ `max_limit`，覆盖 begin 即停，任意区间完整返回）；`dividend.history` 单次请求，超出显式报 `LimitError(code="range")` | 分红长区间：调大 `max_limit` 或收窄窗口 |
| 单一批次拼接票数告警 | **200** | 非原生路由接口逐票拼接 ≥200 票发 `UserWarning`（EC 随票数放大） | 用批量原生接口或 `batch_all()` 分批 |
| 批量原生「准全市场」捷径阈值 | **2,000** | ≥2,000 票改传空数组（与服务端全市场扫描阈值对齐：≥2000 的数组清单上游本来就按全市场扫描计费，空参捷径另享按日 memo，复跑 ≈28 EC）；停牌/索引外标的缺席 → `BatchResult.truncated=True` | 缺席标的用小清单补拉（<2,000 票走逐票按量路径，含停牌行，≈58 EC/票） |
| `margin.universe` 服务端上限 | **5,000** 行 | 默认 `limit=None` = 全量（≈4,010 行） | 按需传 `limit` 降 EC |
| `valuation.daily_basic` 返回窗口 | **1,500** 行（最新优先；XS 端 `DEFAULT_LIMIT`） | 2026-11-19 修复后实测：600519/000001 全量各回 **727 日**（2023-11-20 起，3y 全量可见）。背景：11-19 服务端发布波后 kernel 读面对 `limit≤0` 取 200 默认，曾使端点只回最新 ~200 交易日（11-19 午间发现，store 数据始终完好）；script `store_query` 包装层已把 ≤0 归一到 `DEFAULT_LIMIT`（commit `015032f2`，pipeline-5982）。计费按扫描行：floor ≈1,707 EC + ≈23 EC/日（估 `begin/end` 收窄，字段数几乎不加价） | 累积 >1,500 日（≈6 年）后更早区间**曾静默缺席**；**2.4.0 起**信封 `meta.window.truncated` 明示截断，SDK 按 `oldest_scanned` 自动向前翻页（上限 10 片 ≈15,000 交易日），跨窗口查询不再需要调用方手工拼接。可用范围可先查 [cli.valuation.daily_basic_coverage](API.md) |

## 2. 批量与全市场

| 场景 | 推荐入口 | 请求数 | EC 量级 |
|---|---|---|---|
| 全市场快照（A 股 ≈5,691 家） | `cli.batch_all("kline.snapshot", codes)` | **1** 次（原生路由不分批） | 60~90 EC/票 |
| 逐票快照（<3 票或关闭原生路由） | `cli.kline.snapshot([...])` | 1 次/票 | ≈10,250 EC/票（首算含均线回看） |
| 历史行批量（如全市场日 K） | `cli.batch_iter(...)` 边取边落盘 | ⌈N/500⌉ 次 | 按行计（≈60~75 EC/行） |
| 跨市场 | **禁止混批** | — | 按市场分别建 `Client(market=...)`（A 股 12 批 + 港股 6 批 + 美股 11 批 = 29 次请求） |

`BatchResult` 判读：`requests` = 实际请求次数、`requested` = 请求标的数、
`truncated` = 结果是否缺标的、`errors`/`error_details` = 失败项（`retryable` 标记）。

## 3. 限流与重试

| 项 | 值 | 说明 |
|---|---|---|
| 服务端请求限流（免费档） | **500 次/小时、5,000 次/日** | 429 按请求次数计；批量/分批是唯一正解 |
| 客户端重试 | `retries=2`、`backoff=0.5s`、抖动 `0.1` | 仅对瞬时故障（连接/超时/5xx）重试 |
| `Retry-After` 上限 | `max_retry_after=10s` | 服务端给更长等待时按上限截断 |
| 配额耗尽 | 不重试 | `QuotaError`：换默认应用凭证 / 等周补 / 升级或充值 |
| 限流耗尽 | 停止并给续跑位置 | 报错含已完成标的数 + `codes[done:]` 切片 |

### 匿名试用（无凭证自动领取）

一次性给足、用完即止（限频对齐正常注册用户免费档），不参与周补满；单 IP 与当日
发放名额由服务端限流，领满时报 `anon_quota`（次日再试或注册）。凭据独立存放
`~/.wmshare/anon_credentials.env`（不覆盖付费凭据文件），TTL 7 天失效，
`Client.anonymous(refresh=True)` 重领；额度余量以服务端 `ec_balance` 为准。
`WMSHARE_DISABLE_ANON=1` 可关闭自动回落。

## 4. EC 成本防护

| 项 | 值 | 说明 |
|---|---|---|
| 单次 EC 告警阈值 | **100,000** | `Client(ec_warn_threshold=...)` 可调；`None` 关闭 |
| 成本预估 | `cli.cost_estimate(name, **params)` | 纯离线返回 `{ec_lo, ec_hi, model, note}`；无模型如实返回 `None` |
| 列投影 `_fields=` | **不降 EC** | EC 按服务端物化行计，投影只收窄返回体 |
| 原生批量 vs 逐票 | 批量原生便宜约两个数量级 | 列表 ≥3 票自动走原生路由（`native_batch=True` 默认）；具体数字用 `cli.cost_estimate` 先估 |
| 大结果集复跑 | **第二次起近乎免费** | 全量/市场级结果（如 `margin.universe` 全量）在服务端按**数据版本**缓存：同一批数据反复读取只物化一次，数据日更后自动换键重算。不需要预热任务，也不会读到旧档 |

## 5. 参数与形态

| 限制 | 说明 |
|---|---|
| 日期 | 统一 ISO `YYYY-MM-DD`（也接受 `YYYYMMDD` 与 `date`/`datetime`）；起止需成对 |
| 序列方向 | 全库升序（旧→新）；取最新值用 `[-1]`/`last()`，不要 `[0]` |
| 市场 | `Client(market=...)` 只接受 `cn`/`hk`/`us`；期货/转债/指数在 `cn` 下走专域 |
| `_fields` | list[str] 或逗号串；未知字段报 `UsageError(code="params")`；统一信封不参与投影 |
| 单位 | 默认基础单位（率=小数/额=元/量=股）；逃生口 `_units="native"` / `native=True` / `_raw=True` |

## 6. 常用配方

```python
# 先估后取：避免盲目打满配额
est = cli.cost_estimate("margin.universe", limit=500)
rows = cli.margin.universe(limit=500, _fields=["security_code", "exchange"])

# 全市场快照：一次请求，缺标的显式判断
res = cli.batch_all("kline.snapshot", codes)
missing = [c for c in codes if c not in res.results] if res.truncated else []

# 历史批量：边取边落盘，避免内存峰值
for part in cli.batch_iter("kline.query_bars", codes, batch_size=200):
    write(part.results)
```
