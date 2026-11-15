# 指标适配层（可选工具）

`wmshare.indicator_adapter` 是一个**可选的适配工具**，不替代、不修改现有接口：

- `cli.indicator.get` / `cli.indicator.metrics` 的签名和行为不变；
- `Catalog.metric_groups` / `metrics_in_group` / `search` 不变；
- `metrics.json` 仍是原来的扁平码表，适配层读取独立的
  `_catalog/generated/metric_taxonomy.json`；
- 适配层只调用现有 `indicator.metrics`，不新增服务端能力。

它的用途是把 2,752 个指标码按“数据对象 / 主题 / 周期 / 口径 / 单位”分类，并明确
**哪些码可以确定性组合、哪些只能扁平地一个个取**。

## 1. 三步找码

```python
import wmshare
from wmshare.indicator_adapter import IndicatorAdapter

cli = wmshare.demo_client()          # 演示数据；真实数据用 Client.from_env()
ad = IndicatorAdapter(cli)

ad.scopes()                          # 股票/行业/指数/宏观/期货/可转债/选股条件
ad.topics("stock")                   # 估值/盈利/成长/行情/分红/股东……
```

`scopes()` 和 `topics()` 返回 `{id, cn, count}`，只读目录，不取数、不消耗额度。

## 2. 看“能不能组合”

```python
g = ad.combinable_groups(scope="stock", topic="valuation")
g["groups"]   # 可组合组：同 unit_kind/period/window/caliber/market
g["flat"]     # 不能组合：unknown 字段或 dead 码，附 reason
```

一个可组合组长这样：

```python
{
  "group_id": "multiple|ttm|none|-|shared",
  "unit_kind": "multiple",
  "period": "ttm",
  "window": "none",
  "caliber": [],
  "market": "shared",
  "codes": ["$EV_EBITDA_LAST", "$PE_TTM_LAST", "$PS_TTM_LAST"],
  "count": 3,
}
```

规则是确定性的：

- 只有 `unit_kind / period / window / caliber / market` **完全一致**的码才进同一组；
- `period=unknown`、`window=unknown`、`unit_kind=unknown`、`caliber=[unknown]` 或
  `status=dead` 的码一律进 `flat`；
- 不同组之间**不会**被合并成一次 eval。

`group_id` 是可复算的分隔字符串：`unit_kind|period|window|caliber|market`，
`caliber` 为空时写 `-`。日常使用不必手写它，用 `period/window/unit_kind` 过滤即可。

> `group_id` 只表示“可以同批取数”，**不代表数值可以直接相加/相除/排序比较**。
> 跨码比较仍要看 `topic`、`period`、`window`、`caliber`；长表把这些列逐行给出。

## 3. 取一组：长表优先

```python
pe_group = next(x for x in g["groups"] if "$PE_TTM_LAST" in x["codes"])
rows = ad.table("600519", pe_group["codes"])
```

`table` 的行为：

- 同组码合并成一次 `indicator.metrics` 调用；
- `flat` 码逐个调用；
- 返回**一行一个码**的长表，不会把异构口径塞进一个 dict；
- 每行带 `period/window/caliber/unit_kind/stat/min_history/group_id/combinable/reason`；
- `dead` 码和市场不兼容码返回 `status="excluded"`、`value=None`、`reason` 明确，不静默丢码；
- `on_error="skip"` 时失败行带 `error`，不拖垮整表；
- `_df=True` 返回 pandas DataFrame（需要安装 pandas）。

行字段示例：

```python
{
  "code": "$PE_TTM_LAST",
  "value": 21.18,
  "scope": "stock",
  "topic": "valuation",
  "period": "ttm",
  "window": "none",
  "caliber": [],
  "stat": "last",
  "unit_kind": "multiple",
  "min_history": "none",
  "status": "active",
  "group_id": "multiple|ttm|none|-|shared",
  "combinable": True,
  "reason": None,
  "error": None,
}
```

## 4. 多标的：小列表用 `many`

```python
res = ad.many(["600519", "000001"], g["groups"][0]["codes"])
res.results       # {symbol: {code: value}}
res.requests      # 真实 eval 次数：标的数 × (同组数 + flat 码数)
res.metric_meta   # code -> period/window/caliber/unit_kind/stat/group_id
res.to_df()       # 每标的一行，指标码为列（需要 pandas）
```

平台没有“跨标的指标 eval”能力，`many` 是客户端逐标的 fan-out；`requests` 如实计数，
不会把 N 个标的包装成“1 次请求”。

**全市场截面不要用 `many`**：用现有 `screener.query(fields=codes, _df=True)`，
它由服务端索引一次查完，适合 A 股最新 EOD。

## 5. 与字段型 SDK 的习惯对齐

常见字段型 SDK 的典型习惯是：用 `fields` 选列、返回 DataFrame、用日期区间取历史。
对应关系如下（只做习惯说明，不涉及任何第三方产品）：

| 常见习惯 | wmshare 对应 |
|---|---|
| `fields` 选列 | `codes=[...]` |
| 返回 DataFrame | `ad.table(..., _df=True)` / `ad.many(...).to_df()` |
| 单票多字段 | `cli.indicator.metrics(symbol, codes)`（现有接口） |
| 小列表多标的 | `ad.many(symbols, codes)` |
| 按交易日全市场截面 | `cli.screener.query(fields=codes, _df=True)` |
| 按报告期/日期取历史 | 见下方“能力边界”，指标码本身不是历史接口 |

## 6. 单位换算

wmshare 返回值统一基础单位，迁移时最容易错的是百分数、万元、手：

| 常见口径 | wmshare 口径 |
|---|---|
| 百分数 `3.96` | 小数 `0.0396` |
| 万元 `12345` | 元 `123450000` |
| 手 `100` | 股 `10000` |
| 千元 `500` | 元 `500000` |
| 倍 `21.18` | 倍 `21.18`（不变） |

指标码里的 `(％)`/`(亿)` 等中文后缀是命名遗留，不代表返回值单位；以目录声明和
`unit_kind` 为准。

## 7. 能力边界

- `indicator.metrics` / `ad.table` 取的是**当前/截面值**，不接受 `start_date/end_date`；
- 历史估值：`cli.index.trend`（指数/行业，约 14 年周频）、
  `cli.valuation.hist_stats`（个股，≤3 年）；
- 历史财报：`cli.statements.*`（按报告期）；
- 宏观时序：`cli.macro.query` / `cli.macro.spots`；
- 没有“任意指标码的历史序列”接口；不要按日期区间 SDK 的预期使用指标码。

## 8. 旧接口不变

已有代码不需要迁移：

```python
cli.indicator.get("600519", "$PE_TTM_LAST")          # 不变
cli.indicator.metrics("600519", ["$PE_TTM_LAST"])    # 不变
```

适配层只在需要“按分类找码 / 判断能否组合 / 长表对齐口径”时使用。
