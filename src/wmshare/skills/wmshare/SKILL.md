---
name: wmshare
description: 用 wmshare Python SDK 取 A 股数据：K 线（三种复权）、盘中快照、1 分钟分时、资金流、三大报表、2158 个指标码、选股筛选与全市场涨跌全景、分红、公告、公司档案。配置开放平台凭证后即可取数；随包离线目录可编程查询，指标码/函数名先查目录、禁止臆造。用户要 A 股行情/财务/指标/选股/分红/公告数据时用本 skill，即使用户没点名 wmshare。
when_to_use: 用户需要 A 股个股或全市场数据（价格、财务、指标、筛选、分红、公告）来回答问题、做分析或写代码时。
---

# wmshare：A 股个股数据 SDK

wmshare 是覆盖 A 股、港股、美股的 Python 财经数据 SDK（BSD-3-Clause 开源，云端数据服务需账号与配额）。本 skill 教你怎么把它
用对：先装好、先查目录、按单位铁律读数、按决策树选接口。

**它不是**：回测框架（没有撮合/仓位管理）；数据库（数据经云端 API 运行时获取，
不随包分发）；全品类数据超市（17 个数据域，覆盖 A 股个股常用研究数据，
基金净值/期货/期权/债券未覆盖）。

## 1. 环境前置

```bash
python3 -c "import wmshare; print(wmshare.__version__)"   # 探测
# 缺失则安装（国内推荐清华等主流镜像，随 PyPI 自动同步；镜像滞后时指官方源）：
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple wmshare
```

零凭证语法试跑：`cli = wmshare.demo_client()`（2026-10-30 真实 API 固定快照；10 只演示宇宙 + 当日全市场 screener，**非实时数据**），调用面覆盖公开示例，用于无凭证时验证代码形态；真实取数必须配置下方凭证。

凭证必填（SDK 不再内置体验 AppID）：在开放平台获取 client_id/api-key，
配置其一（构造参数 / WMSHARE_CLIENT_ID+WMSHARE_CLIENT_SECRET 环境变量 /
~/.wmshare/credentials.env 凭证文件）即可取数：


1. 打开 open.winmale.com，登录后在「我的 → 开放平台 → 我的应用」获取凭证；
2. 右上角「我的」→「开放平台」→ 左侧「我的应用」→「查看应用信息」，
   **两个值都要复制**（缺一不可）：AppId（Client ID）与 API Key（Client Secret）；
3. 配置其一：`export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...`，
   或凭证文件 `~/.wmshare/credentials.env`（内容两行：`WMSHARE_CLIENT_ID=你的client_id` 与 `WMSHARE_CLIENT_SECRET=你的api-key`）。

## 2. 单位铁律（读数前必读）

返回值统一**基础单位**，不要自己再换算：

| 维度 | 单位 | 示例 |
|---|---|---|
| 比率 / 涨跌幅 / 分位 | 小数 | 0.0396 = 3.96%；0.01 = 1%；0.42 = 42% 分位 |
| 金额 / 价格 / 市值 | 元（报表原币） | — |
| 股数 / 成交量 | 股 | — |

例外要在读数时留意：`cli.screener` 宽度接口（全景/分桶）的 `up_pct`/`down_pct`/
`pct_of_total` 是**百分数数值**（80.3 = 80.3%），同返回里的 `median_pct` 与
涨跌幅仍是小数——字段级口径以各方法 docstring 为准。

每次返回前 SDK 做量级守护与关系不变量校验，违例抛 `DataError`（含字段/实际值/
期望范围）——**这是数据在报警，不要 try/except 吞掉**。逃生口：`_raw=True`
（上游原始行）、`_units="native"`（保留上游原单位）、`Client(validate=False)`
（关校验留换算）。

## 3. 目录先行（防臆造，AI 最重要的纪律）

**指标码、函数名、参数必须先查离线目录，禁止编造 `$XXX` 码或猜函数名**。
目录随包分发、纯本地读文件、零网络：

```python
import wmshare

cat = wmshare.load()                                    # 数据目录对象
hits = cat.search("股息")                                # 函数 + 指标码混合检索（中文口语可查）
cat.function("bonus.snapshot_yield_ttm")["params"]       # 任意函数的参数/返回/示例合同
cat.metric("$PE_TTM_LAST")                               # 指标条目（精选码带单位与守护声明）
cat.metrics_in_group("dividend")                         # 指标组内全部精选指标
```

检索返回的函数一律可用两种方式调用：`cli.call("<域>.<函数名>", ...)`（按目录参数名
传参）或友好层方法（见下节决策树）。

## 4. 意图 → 接口决策树

| 用户意图 | 一行调用 |
|---|---|
| 某股最近 N 根日 K | `cli.kline.bars("600519", n=30)`（`adj="qfq"/"hfq"` 复权） |
| 某股日期区间 K 线 | `cli.kline.bars("600519", begin="2026-01-01", end="2026-06-30")` |
| **全市场 / 上百只取数（避免 429）** | `cli.batch_all("kline.snapshot", [r["symbol"] for r in cli.stocks.list()])`——自动分批，A 股 5,691 家只发 **12 次请求**；**绝不要写 `for code in codes: cli.kline.bars(code)`（5,691 次请求必撞限流）** |
| 最新价 / 盘中快照 | `cli.kline.last("600519")`；盘中实时用 `cli.kline.snapshot("600519")` 或 `cli.kline.batch_live(["600519"])` 或 `cli.kline.live("600519")` |
| 当日 1 分钟分时 | `cli.kline.min1("600519")` |
| 今日涨停了吗 / 全市场涨停梯队 | `cli.screener.screen_limit_up("600519")` |
| 全市场今天涨跌如何 | `cli.screener.index_breadth_summary()` |
| 涨幅榜 / 跌幅榜 | `cli.screener.index_top_movers(limit=20)`（`desc=False` 跌幅） |
| 站上 20 日线了吗 / 放量了吗 | `cli.screener.screen_above_ma20(sym)` / `screen_volume_spike(sym)` |
| 资金流 | `cli.moneyflow.last(sym)` / `cli.moneyflow.bars(sym, n=20)` |
| 利润表 / 资产负债表 / 现金流 | `cli.statements.income(sym, years=5)` / `balance` / `cashflow` |
| 合并 vs 母公司 | `cli.statements.compare(sym)` |
| 估值指标当前值 | `cli.indicator.get(sym, "$PE_TTM_LAST")`（码先查目录） |
| 估值历史分位 | `cli.valuation.hist_stats(sym, metric="pe", window="3y")` |
| TTM 股息率 / 分红历史 | `cli.dividend.yield_ttm(sym)` / `cli.dividend.history(sym)` |
| 分红质量筛选 | `cli.dividend.screen_quality(sym)`（默认精品窗口：股息率>3% 且派息率 30%–70%；窗口不合适就显式传 min_yield/payout_min/payout_max） |
| 公告 / 有无回购 | `cli.notice.list(sym, window="3m")` / `cli.notice.has_buyback(sym, "6m")` |
| 业绩预告 | `cli.forecast.yjyg_latest(sym)` |
| 公司档案 | `cli.info.profile(sym)` |
| 全市场代码池（A/港/美全表） | `cli.stocks.list()`（行含 symbol/name/exchange/industry/listed；港/美换 `Client(market=...)`） |
| 行业目录 / 行业成分 | `cli.stocks.industries(1)`（申万/恒生；美股目录树暂缺）/ `cli.stocks.industry_members("银行")`（中文名或代码 S48） |
| 少量标的单批（≤500） | `cli.call_batch("kline.snapshot", ["600519", "000001"])` 或任意单标的接口传 list：`cli.kline.last(["600519", "000001"])`；`to_df()` 出每标的一行长表 |

完整 116 个核心接口与全部底层函数：仓库用户看 docs/GUIDE.md（上手）与
docs/API.md（参考）；pip 用户用 `cat.search(...)` / `cat.function(...)` 查（同一份合同）。

## 5. 工作流示例（返回长这样，从这些字段读）

```python
import wmshare

cli = wmshare.Client.from_env()

# 日 K：按日期降序；percent 为小数（0.005215 = 0.52%）、volume 为股
bars = cli.kline.bars("600519", n=5)
print(bars[0])
# {'date': '2026-10-20', 'close': 1331.88, 'volume': 3413500.0,
#  'amount': 4525398959.0, 'percent': 0.005215, 'open': ..., 'high': ..., 'low': ...}

# 全市场涨跌全景：服务端预计算索引直出；*_pct 是百分数数值、median_pct 是小数
s = cli.screener.index_breadth_summary()
print(s)
# {'total': 5685, 'up': 4567, 'down': 934, 'flat': 184,
#  'up_pct': 80.3, 'down_pct': 16.4, 'flat_pct': 3.2, 'median_pct': 0.015363}

# TTM 股息率：小数，0.0396 = 3.96%
print(cli.dividend.yield_ttm("600519"))        # 0.0396

# 估值温度计：PE(TTM) 近 10 年分位，0.42 = 42% 分位
print(cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST"))   # 0.42

# 窗口分红统计：dps 元/股、total 元、count 次（按除权日计）
print(cli.dividend.window_stats("600519", "3y"))   # {'dps': ..., 'total': ..., 'count': 6}
```

## 6. 坑位清单

- **率与涨跌幅都是小数**（0.04 = 4%）；业绩预告的同比才是百分数口径换算后的小数。
  唯一例外是 `cli.screener` 宽度接口的 `*_pct`/`pct_of_total`（百分数数值）。
- **window 白名单**：`"7d"/"1m"/"3m"/"6m"/"1y"/"3y"/"5y"` 或天数整数；未知 token
  显式报错（不会静默按 30 天处理）。
- **日期区间上限 5 年**（`begin/end` 含端点）；数据覆盖不足抛 `LimitError`，
  不会静默截断。
- **单次拉取上限**：`Client(max_limit=500)` 可调；超限显式报错（批量标的数同限，
  报错附分批写法与 `batch_all()` 提示）。
- **限流按请求次数计**（免费档 500 次/小时、5,000 次/日），所以：
  ①大批量一律走 `batch_all`/`batch_iter`（N 家 = ⌈N/500⌉ 次请求），不要自己逐票循环；
  ②**容错用 `batch_all(on_batch_error="skip")`（批级），绝不能用 `call_batch(on_error="skip")`**
  ——后者逐票发请求，12 批会放大成 5,691 次，正好制造 429；两个参数名不同是刻意的
  （`on_batch_error` 跳过整批，`on_error` 逐票请求）；批量入口也无 `_df`，长表用 `to_df()`；
  ③遇 429 会停止并给 `codes[done:]` 续跑位置，按提示稍后续跑，不要无脑重试；
  ④单批撞 `CALC_LIMIT_EXCEEDED`（算力超限）时减小 `batch_size`。
- **批量不能跨市场**：一个批次只能是同一市场（`Client(market="cn")` 只传 A 股）——实测
  网关不拒但数据是错的（cn 上下文里查该港股标的的 close/percent 与 hk 客户端不符，涨跌方向都相反）。
  SDK 已主动拦截报 `UsageError`；跨市场请分别建 Client：A 股 12 批 + 港股 6 批 + 美股 11 批。
- **stocks 域新鲜度**：cn/hk 全市场列表随上游每日刷；us universe 为手动刷新
  （新上市/退市有滞后），且美股行业目录树暂缺（`industries()` 恒空、
  `industry_members()` 不可用；列表行的 industry 字段仍有值）。
- **indicator.metrics 批内任一码失效会整批 500**：目录里存在个别上游未注册依赖的码
  （如 `$AMOUNT_LIVE` 这类原始 LIVE 码，单码也 500），混进 `cli.indicator.metrics`
  批量会中止整批；错误消息会点名未定义变量——把该码剔除后重试即可，其余码是好码。
  单码取值 `cli.indicator.get` 不受影响。
- **盘中语义**：休市时 `live`/`min1` 返回最近收盘快照 / 上一交易日；事件筛选
  （涨停等）以「当日有成交」为前置，停牌恒 `False`。
- **403「策略拒绝」（POLICY_DENIED）≠ 额度不足**：是 AppID 的接口权限范围限制
  （换 AppID 不解决、勿反复重试），按错误消息到开放平台检查应用权限，或改用
  无此限制的其他接口。
- **screen_quality 判 False 先看窗口语义**：默认 = 股息率>3% 且派息率 ∈[30%,70%]
  （「精品」定义——茅台 ~80% 派息率出界属设计而非误判）；窗口不合适就显式传阈值。
  分红 `history` 明细里最新记录的 net_profit/payout_ratio 列可能回填滞后为 0，
  只影响展示、不影响筛选与窗口统计（筛选走 TTM 派息指标）。判读用
  `cli.dividend.yield_ttm(sym)` 与 `cli.indicator.get(sym, "$BONUS_TTM_RATE_LAST")`。
- **宽度接口的 `idx` 不要传臆造键**：不传 = 服务端自动解析 A 股最新查询索引。
- **空结果 ≠ 市场为空**：先核对 symbol 与窗口再下结论。
- `_df=True` 转 DataFrame 需要安装 pandas（可选依赖）。
- ETF 用 6 位码直接查（如 `510300`）；`cli.kline.is_etf(sym)` 可判断。

## 7. 错误处理速查（都是 `WmshareError` 子类）

| 异常 | 含义 | 怎么做 |
|---|---|---|
| `AuthError`（401/OAuth） | 凭证无效或过期 | 按第 1 节申请自己的 AppID 并配置环境变量 |
| `AuthError`（403 策略拒绝） | AppID 无此接口权限范围 | 与额度无关，勿重试：按错误消息到 open.winmale.com 开放平台查应用权限，或改用无此限制的接口 |
| `LimitError` | 429 限流 / 超上限 | 稍等重试；批量/连跑可申请自己的 AppID 提额；区间类缩小 begin/end |
| `UsageError` | 参数不合法 | 按消息修正；参数合同查 `cat.function(name)["params"]` |
| `DataError` | 单位/守护校验违例 | 数据在报警：换指标或核实口径，勿静默吞掉 |
| `CatalogError` | 目录查无此函数/指标 | `cat.search(...)` 找正确名字，禁止臆造 |
| `TransportError` / `ServerError` | 网络 / 服务端 | 可重试；持续失败再排查凭证与网络 |

## 8. 装入 AI agent

skill 随包分发，复制到 agent 的 skill 目录即可被自动发现：

```bash
cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" ~/.agents/skills/wmshare
# 项目级：放进仓库的 .zcode/skills/ 或 .claude/skills/（各工具发现路径不同）
```

许可：BSD-3-Clause——代码可自由使用（含商业）；云端数据服务需开放平台账号与配额。
