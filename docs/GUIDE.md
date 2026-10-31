# wmshare 使用指南

本指南是 **how-to + 解释层**：会做什么 → 怎么做好。其他层各有其位——
教程看 [README](../README.md) 与 [examples/](../examples/README.md)（可运行课程），
接口参考看 [API.md](API.md)（116 个核心接口，生成物），
AI 用法看 [AI.md](AI.md)。

> 代码块里的输出注释都是**真实运行结果**（2026-10-29，cn 市场，免费档凭证），
> 数值会随行情变化，口径与量级不会。README、SKILL 与演示客户端（`demo_client()`）
> 里的示例值取自更早日期的实测快照，同一指标不同日数值不同（如 TTM 股息率
> 0.0396→0.0379），属正常漂移。

## 1. 安装与凭证

```bash
pip install wmshare                  # 基础安装
pip install "wmshare[dataframe]"     # 可选：pandas 支持（_df=True）
python3 -c "import wmshare; print(wmshare.__version__)"   # 验证安装
```

不配凭证先试：`cli = wmshare.demo_client()`——随包离线演示客户端（2026-10-30
真实 API 固定快照；10 只演示宇宙 + 当日真实全市场 screener，
**非实时数据**），调用面覆盖公开示例；examples/ 的凭证示例都支持
`--demo` 旗标零凭证试跑。看真实数据按下节配凭证。

凭证在开放平台（`https://open.winmale.com`）控制台的「我的 → 开放平台 → 我的应用」页获取，
`AppId（Client ID）` 与 `API Key（Client Secret）` **两个值缺一不可**。配置任选其一：

```bash
# 方式一：环境变量
export WMSHARE_CLIENT_ID=<AppId> WMSHARE_CLIENT_SECRET=<API Key>
# 方式二：凭证文件 ~/.wmshare/credentials.env（KEY=VALUE 每行一条）
# 方式三：构造参数 cli = wmshare.Client(client_id="...", client_secret="...")
```

遇到 401/403/429 不要猜：**错误消息自带完整修复步骤**（申请步骤、配置方法、
续跑位置），直接照做或整段贴给 AI（见 [AI.md](AI.md)）。

## 2. 核心概念

### 2.1 双层 API：门面 + 目录

- **门面层** `cli.<命名空间>.<方法>()`：20 个命名空间、116 个核心接口，方法名动宾化可猜
  （`kline.bars`、`dividend.yield_ttm`、`screener.screen_limit_up`）。
- **目录层** `cli.call("<域>.<函数名>", ...)`：252 个底层函数按目录合同直调，
  参数名以 `cat.function(name)["params"]` 为准。门面未包装的函数经属性直达
  （如 `cli.dividend.index_where_high_yield_5()`）；目录之外的名字显式报错——
  门面不遮蔽目录函数，252 个都能直达。

两层的名字对不上是常态：目录按上游域组织，门面按使用视角命名（如目录 `bonus` 对应
门面 `dividend`），17 个域挂 20 个门面。不必背映射——`cat.search("分红")` 一查即得；
`cli.call` 的域与函数名以 `cat.functions_by_domain()` 为准。

### 2.2 目录先行（防臆造）

指标码、函数名、参数**先查离线目录**（随包分发、纯本地、零网络零额度），禁止编造：

```python
import wmshare

cat = wmshare.load()
cat.search("股息")                    # 中英文关键字混搜函数 + 指标码
cat.function("bonus.snapshot_yield_ttm")["params"]   # 任意函数的参数/返回/示例合同
cat.metric("$PE_TTM_LAST")            # 指标条目（精选码带单位与守护声明）
cat.metrics_in_group("dividend")      # 指标组内全部精选码
cat.symbols_search("茅台")            # 代码/名称/全拼/拼音首字母搜标的
cat.functions_by_domain()             # 按域列全部函数名（cli.call 的域名以此为准）
```

### 2.3 单位铁律与数据守护

| 维度 | 单位 | 示例 |
|---|---|---|
| 比率 / 涨跌幅 / 分位 | **小数** | 0.0396 = 3.96%；0.42 = 42% 分位 |
| 金额 / 价格 / 市值 | 元（报表原币） | — |
| 股数 / 成交量 | 股 | — |

唯一例外：`cli.screener` 宽度接口的 `up_pct`/`down_pct`/`pct_of_total` 是**百分数数值**
（80.3 = 80.3%），同返回的 `median_pct` 与涨跌幅仍是小数。
每次返回前 SDK 做量级与关系不变量校验，违例抛 `DataError`——**数据在报警，不要吞掉**。
逃生口：`_raw=True`（返回上游原始行，字段名与规范化后不同）、`_units="native"`
（保留上游原单位，如 volume=手、百分数不折算）、`Client(validate=False)`（关校验留换算）。

### 2.4 限流模型：按请求次数计

服务端按**请求次数**限流（免费档 500 次/小时、5,000 次/日），与数据量无关——
一次批量请求取 500 家和一次单票请求都算 1 次。所以：**多标的一律走批量**（第 5 章），
`for code in codes: cli.kline.bars(code)` 这种逐票循环是撞 429 的最短路径。

### 2.5 多市场

`Client(market="cn" | "hk" | "us")`，缺省 cn。代码与市场不匹配服务端直接拒绝
（cn 查 `00700` 报 market mismatch）。批次不能跨市场（第 5.4 节）。

美股用**裸代码**（`AAPL`、`BRK_B`）：带交易所后缀的 `AAPL.O`/`BRK.N` 上游会当成宏观序列，
指标脚本里的 `symbol` 变量不绑定（`_LAST` 族 500、分位静默返 0）。SDK 已按随包代码表
自动归一（`AAPL.O`→`AAPL`、`BRK.B`/`BRK-B`→`BRK_B`），归一无命中时才原样上送。

## 3. 单票菜谱

可运行版本：`examples/01_quickstart.py`、`04_screener.py`、`05_dividend_screener.py`、
`06_indicator_tour.py`、`11_statements_tour.py`；公告订阅见 `10_notice_monitor.py`。

```python
import wmshare

cli = wmshare.Client.from_env()

# 最近 N 根日 K（按日期降序；percent 为小数）
cli.kline.bars("600519", n=3)
# [{'date': '2026-10-29', 'close': 1354, 'percent': 0.017471}, ...]

# 日期区间 K 线（单次区间上限 5 年；adj="qfq"/"hfq" 复权）
cli.kline.bars("600519", begin="2026-01-01", end="2026-06-30")

# 盘中：最新快照 / 实时（休市时 live 返回最近收盘快照）
cli.kline.snapshot("600519")            # {'close': ..., 'chg_20d': ...}
cli.kline.min1("600519")                # 当日 1 分钟分时

# 主力资金净流入（元）
cli.moneyflow.last("600519")            # net_mf = 821186700（8.2 亿元）

# 三大报表（多期科目行：cn 中文名 / k 科目键 / vals 各期值）
cli.statements.income("600519", years=1)    # 25 行科目
cli.statements.balance("600519", years=3)
cli.statements.compare("600519")            # 合并 vs 母公司
# 完整可运行版：examples/11_statements_tour.py（含审计意见、diffp 小数读法）

# 指标码取数（码先查目录；分位 0=最低 1=最高）
cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")   # 0.2115（近 10 年 21% 分位）
cli.indicator.get("600519", "$CUR_IND_ROE_PCT_LAST")  # 1.0（ROE 同行业最高）
cli.indicator.metrics("600519", ["$PE_TTM_LAST", "$ROE_TTM_LAST"])  # 批量取多码

# 估值历史统计（窗口上限 3 年）
st = cli.valuation.hist_stats("600519", metric="pe", window="3y")
f"当前={st['current']:.1f} 中位={st['median']:.1f} 位置={st['pct']:.0%}"
# '当前=20.8 中位=20.6 位置=54%'

# 分红：TTM 股息率（小数）/ 历史 / 质量筛选
cli.dividend.yield_ttm("600519")        # 0.0379（3.79%）
cli.dividend.history("600519")          # 明细行：ex_div / dps（元/股）/ payout_ratio
cli.dividend.screen_quality("600519")   # False——默认精品窗口=股息率>3% 且派息率 30%–70%，
#   茅台派息率 ~80% 出界属设计而非误判；放宽窗口才为 True：
cli.dividend.screen_quality("600519", min_yield=0.02, payout_max=1.5)  # True

# 公告与披露信号
cli.notice.list("600519", window="3m", limit=3)
cli.notice.has_buyback("600519", "6m")  # True
# 公告变更「订阅」轮询是另一套：§8 / examples/10_notice_monitor.py

# 股东治理：十大股东 / 质押 / 解禁
cli.equity.query_holder10("600519")
# 10 行；首行 {'holder_name': '中国贵州茅台酒厂(集团)有限责任公司',
#             'hold_num': 681282935, 'hold_num_ratio': 0.545, ...}
cli.equity.query_pledge_summary("600519")
cli.equity.query_release("600519")

# 两融（近 20 日明细行：融资余额/买入额/偿还额、融券余量…）
cli.margin.query("600519")

# 可转债：正股关联（无存续转债返回空表）
cli.cbond.of_stock("000001")            # 1 只：bondName / bondPrice / convertPrice …

# 指数：成分股（按市值权重取前 N）/ 权重股 / 估值时序
cli.index.members("index.hs300", "mv", 10)

# 选股筛选器（一行布尔；停牌恒 False）
cli.screener.screen_limit_up("600519")      # 今日涨停？
cli.screener.screen_above_ma20("600519")    # 站上 20 日线？
cli.screener.screen_volume_spike("600519")  # 放量？

# 全市场宽度（服务端索引直出；*_pct 是百分数数值、median_pct 是小数）
cli.screener.index_breadth_summary()
# {'total': 5685, 'up': 540, 'down': 5002, 'up_pct': 9.5, 'median_pct': -0.0154, ...}
# total = 当日参与涨跌统计的家数（全市场列表是 5,691，含停牌等不参与统计的）
cli.screener.index_top_movers(limit=10)     # 涨幅榜（desc=False 跌幅榜）

# 公司档案
cli.info.profile("600519")
```

## 4. 全市场与行业

可运行版本：`examples/07_stocks_industry_batch.py`。

```python
rows = cli.stocks.list()          # 全市场证券列表，一次拿全
len(rows)                         # 5691（A 股；字段 symbol/name/exchange/industry/…）
rows[0]                           # {'exchange': 'sz', 'industry': 'industry.S480301',
                                  #  'industry_name': '股份制银行', 'is_st': False,
                                  #  'listed': '1991-04-03', 'name': '平安银行',
                                  #  'symbol': '000001'}

cli.stocks.industries(1)          # 一级行业目录（申万），31 个：S11 农林牧渔、S22 基础化工…
cli.stocks.industry_members("银行")   # 中文名直达（也可传 "S48" 代码），42 家
```

新鲜度注记：cn/hk 列表随上游每日刷新；**us universe 为手动刷新**（新上市/退市有滞后，
个别行 symbol 为空会被 `stocks.list()` 自动剔除）。

## 5. 批量取数（绕开 429 的正解）

可运行版本：`examples/07_stocks_industry_batch.py`。

### 5.1 三个入口怎么选

| 入口 | 用途 | 请求数（N 个标的） | 关键参数 |
|---|---|---|---|
| `batch_all(name, symbols)` | 一站式：自动分批并聚合 | ⌈N/500⌉ | `on_batch_error="raise"/"skip"` |
| `batch_iter(name, symbols)` | 逐批流式：进度/中断/落盘 | ⌈N/500⌉ | 逐批 yield `BatchResult` |
| `call_batch(name, symbols)` | 单批（≤500） | 1 | `on_error` 是**票级**，勿做容错 |

### 5.2 一站式：全市场 = 12 次请求

```python
codes = [r["symbol"] for r in cli.stocks.list()]
res = cli.batch_all("kline.snapshot", codes)
len(res.results), res.requests    # (5691, 12)——逐票要 5,691 次，批量 12 次
res.to_df()                       # 每标的一行长表（symbol 列在前；需 pandas）
```

实测（2026-10-30，免费档）：500 标的单批 0.7–4 秒（随网络波动），A 股全市场 12 批 9–16 秒
一次跑完，0 错误；20 只银行股单批 0.06 秒 1 次请求。
历史类多行结果（`kline.bars`/`dividend.history`）建议改用 `batch_iter` 边取边落盘。

### 5.3 容错与续跑

- **批级容错**：`batch_all(..., on_batch_error="skip")` 跳过失败批继续，失败批进 `errors`
  （键形如 `batch#3[1000:1500]`）。**不要用 `call_batch(on_error="skip")` 做容错**——
  它逐票发请求，12 批会放大成 5,691 次、正好制造 429。
- **429 续跑**：限流在任何模式下都会停止并给出续跑位置——消息含已完成标的数与
  `codes[done:]` 切片，稍后续跑 `batch_all(name, codes[done:])` 即可，不要无脑重试。
- **算力超限**：单批触发 `CALC_LIMIT_EXCEEDED` 时减小 `batch_size`。
- 三个入口的 `name`/`symbols` 都是位置参数；`_raw=True`/`_units="native"` 通用；
  批量入口不提供 `_df`（长表用 `to_df()`）。
- **`name` 必须是目录函数名**（252 个，`cat.functions_by_domain()` 可查）；指标码不是
  函数名——一票多码用 `cli.indicator.metrics(sym, codes)`，全市场指标码只能逐票调用
  （传 `"indicator.get"` 会报 `CatalogError`）。

### 5.4 市场边界：一个批次只能一个市场

`Client(market="cn")` 只传 A 股代码。混入他市场代码 SDK 直接报 `UsageError`——
网关不校验批内代码，但错误市场的代码会在本市场引擎里走错数据管线，返回的
close/涨跌幅不可信（实测同一港股标的混批后涨跌方向都相反）。跨市场分别调用：
A 股 12 批 + 港股 6 批 + 美股 11 批 = 29 次请求。

## 6. 多市场与港美专项

```python
hk = wmshare.Client.from_env(market="hk")
hk.kline.last("00700")            # {'date': '2026-10-29', 'close': 377.6, 'percent': -0.0258}
cli.intl 挂在对应市场的客户端上（函数内部按标的代码路由港美数据族）：

# 港股 CCASS 筹码：按持仓占比排序
rows = sorted(hk.intl.query_ccass("00700"), key=lambda r: -(r["pct_of_issued"] or 0))
rows[0]["participant_name"], f"{rows[0]['pct_of_issued']:.2%}"
# ('THE HONGKONG AND SHANGHAI BANKING ', '32.36%')

hk.intl.query_shareholders("00700")   # 主要股东
hk.intl.query_sellshort("00700")      # 沽空

us = wmshare.Client.from_env(market="us")
us.kline.snapshot("AAPL")             # {'close': 348.91, 'percent': 0.0148}（当日新鲜）
us.intl.query_sellshort("AAPL")       # 美股沽空
```

注记：美股历史日 K 为停更快照（上游对美股价量走 live-only），最新价量用
`kline.live/snapshot`；港美专项覆盖矩阵见 [README](../README.md)「市场覆盖」。

## 7. pandas 与 DataFrame

可运行版本：`examples/08_pandas_analysis.py`。需要 `pip install "wmshare[dataframe]"`。

```python
df = cli.kline.bars("600519", n=120, _df=True).sort_values("date")
# bars 按日期降序返回（最新在前），先升序再算指标——直接 rolling 会算在最老一段上
df["ma20"] = df["close"].rolling(20).mean()

snap = cli.batch_all("kline.snapshot", codes).to_df()   # BatchResult 长表
snap.sort_values("percent", ascending=False).head()     # 全市场今日涨幅前十
```

## 8. 公告变更订阅（轮询器）

```python
poller = cli.notice_poller(group="my-app", consumer="worker-1",
                           on_events=lambda events: print(len(events)))
events = poller.poll_now()   # 手动一轮：探针 → 逐市场拉新 → 回调 → ack；返回本轮交付事件
poller.start()               # 或切后台：daemon 线程定时轮询；退出前 poller.stop()
```

消费进度按 `(group, consumer)` 存服务端，ack 前崩溃会重投（at-least-once）；
进度超保留期抛 `StreamResetError`，按消息用 `seek_oldest()` 重置。
完整可运行版：`examples/10_notice_monitor.py`（`--demo` 零凭证演示 ack 语义）。

## 9. 故障排查

### 9.1 错误家族（都是 `WmshareError` 子类，带 `code`/`status` 可程序化分类）

| 异常 | 含义 | 怎么做 |
|---|---|---|
| `AuthError`（401/OAuth） | 凭证无效或过期 | 按消息申请并配置凭证（第 1 章） |
| `AuthError`（403 POLICY_DENIED） | AppID 无此接口权限范围 | 与额度无关、勿重试；到开放平台查应用权限或换接口 |
| `LimitError`（429） | 按请求次数限流 | 批量+续跑位置（第 5.3 节）；勿无脑重试 |
| `LimitError`（range/limit） | 区间/条数超上限 | 缩小 `begin/end` 或调 `Client(max_limit=...)` |
| `UsageError` | 参数不合法/跨市场混批 | 按消息修正；参数合同查 `cat.function()["params"]` |
| `DataError` | 量级守护/不变量违例 | **数据在报警**：核实口径，勿 try/except 吞掉 |
| `CatalogError` | 目录查无此函数/指标 | `cat.search()` 找正确名字，禁止臆造 |
| `StreamResetError` | 订阅进度超出服务端事件保留期 | `seek_oldest()` 重置（第 8 章）；保持不落后需缩短轮询间隔 |
| `TransportError` / `ServerError` | 网络 / 服务端 5xx | 可重试；持续失败再排查网络 |

### 9.2 按症状查

| 症状 | 多半是 | 出路 |
|---|---|---|
| 全市场跑一半撞 429 | 逐票循环或 `call_batch(on_error="skip")` 逐票放大 | 改 `batch_all`/`batch_iter`（第 5 章） |
| 数值大了 100 倍 | 把小数当百分数又 ×100，或字段本是百分数数值 | 回读第 2.3 节单位表 |
| 报「未知指标」 | AI 或记忆编造了不存在的指标码 | `cat.search("中文")` 查真码 |
| 批量结果里混入怪值 | 跨市场混批 | 分市场建 Client（第 5.4 节） |
| 拉十年 K 线报 LimitError | 区间超 5 年上限 | 分段拉取或缩窗口 |
| ETF 查不到 | 用了场内全称 | 6 位码直查（`510300`），`kline.is_etf()` 可判 |
| 空结果 | symbol 拼错 / 窗口无数据 / 该票无此类事件 | 先 `cat.symbols_search` 核对代码再下结论 |

## 10. 配额与性能实测

免费档：500 次/小时、5,000 次/日（更高额度与条款以开放平台为准）。
按请求次数计费意味着批量是乘法级省配额：全市场 4 个指标 × 12 批 = 48 次，
仍占小时额度不到 10%。实测基线（2026-10-29）：全市场 5,691 家快照 12 批约 9 秒、
0 错误；`res.requests` 字段可直接对比标的数看省了多少。

## 11. 用 AI 学会并用好 SDK

完整指南见 [AI.md](AI.md)。三句话版本：

1. **装 skill（一条命令）**：`cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" ~/.agents/skills/wmshare`，AI 自动获得目录先行、单位铁律、意图→接口决策树；
2. **没 skill 目录的 agent**：把本指南与 [API.md](API.md) 喂作上下文，或直接喂 `llms.txt`（仓库根，AI 友好索引）；
3. **报错驱动**：错误消息自带修复步骤，把 traceback 原样贴给 AI 即可定位。

## 12. FAQ

- **和直接下交易所数据比，图什么？** 目录先行 + 单位统一 + 数据守护 + 批量限流治理——
  取数正确性的工程问题 SDK 替你管了。
- **数据能离线吗？** 目录（252 函数/2752 指标码/代码表）随包离线；行情财报数据在云端，
  需凭证与额度。
- **支持哪些 Python？** ≥3.10；pandas 为可选依赖。
- **怎么贡献/报漏洞？** 见 [CONTRIBUTING](../CONTRIBUTING.md) 与 [SECURITY](../SECURITY.md)；
  agent 贡献者另见 [AGENTS.md](../AGENTS.md)。
