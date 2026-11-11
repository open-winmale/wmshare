# wmshare 使用指南

本指南是 **how-to + 解释层**：会做什么 → 怎么做好。其他层各有其位——
教程看 [README](../README.md) 与 [examples/](../examples/README.md)（可运行课程），
接口参考看 [API.md](API.md)（按资产类别分章的 132 个核心接口，生成物），
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
**非实时数据**），调用面覆盖公开示例（例外：`screener.query` 依赖全市场索引列、
`backtest` 的 pb/ps/pr 估值规则依赖对应序列，演示快照都没有，均显式报
`demo_unsupported`；`backtest` 的均线与 pe 规则可用 120 根演示日 K 真跑）；
examples/ 的凭证示例都支持 `--demo` 旗标零凭证试跑。看真实数据按下节配凭证。

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

- **门面层** `cli.<命名空间>.<方法>()`：22 个命名空间、132 个核心接口，方法名动宾化可猜
  （`kline.bars`、`dividend.yield_ttm`、`screener.screen_limit_up`）。
- **目录层** `cli.call("<域>.<函数名>", ...)`：269 个底层函数按目录合同直调，
  参数名以 `cat.function(name)["params"]` 为准。门面未包装的函数经属性直达
  （如 `cli.dividend.index_where_high_yield_5()`）；目录之外的名字显式报错——
  门面不遮蔽目录函数，269 个都能直达。

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

### 2.6 数据在哪找（按数据类型速查）

| 要找什么 | 在哪 | `cat.search` 关键词 |
|---|---|---|
| ETF 日 K / 判别场内基金 | `cli.kline.bars("510300")`、`cli.kline.is_etf`（ETF 无分钟线，盘中用 `live`/`snapshot`） | ETF |
| 全市场筛选 / 涨跌宽度 | `cli.screener`（`query` 条件选股 + 单票筛选器 + 全景/分桶/涨跌榜） | 筛选 |
| 指数成分 / 权重 / **指数与行业估值历史** / 指数层指标码 | `cli.index`（`trend` 取周频 PE/PB 序列与 3/5/10 年分位；全量码见 INDICATORS.md「指数及 ETF」章） | 指数 |
| 盈利预测 / 业绩预告 | `cli.estimates`（`year_mark`：A=实际、E=预测）+ `cli.forecast`（预告/快报/日历） | 预测 |
| 分红 / 股息率 | `cli.dividend`（`disc.bonus` 域 45 个函数）+ dividend 指标组 | 股息 |
| 行业目录 / 成分股 / 行业均值与行业内分位 / **行业估值历史** | `cli.stocks.industries()`、`cli.stocks.industry_members()`、`cli.index.trend("industry.SXX")`（码族见 INDICATORS.md「行业数据」章） | 行业 |
| 宏观 / 中债收益率 / 期货主力 | `cli.macro`、`cli.indicator.get(sym, "$FUT_CLOSE", fut_symbol="cn.RB.SHF")` | 宏观 |

全量指标码按数据类型的分章导航（每类码数、命名语法与死码清单）见 [INDICATORS.md](INDICATORS.md)；
选码纪律：**目录里有的码不要自己算**（eval 按标的数逐票计费 EC）。

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

# 周 K / 月 K（服务端预派生：日期=周期末交易日，OHLC 由日线聚合）
cli.kline.bars("600519", n=20, freq="W")            # 周 K；freq="M" 为月 K
cli.kline.bars("AAPL", n=12, freq="M", adj="qfq")   # 月 K + 前复权

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

# 可转债：全市场面板（一次调用 = 快照 + 最新条款事件 + 盘中债价 + 强赎/下修观测）
b = cli.cbond.board()                   # 行 = 快照行 + event/callHits/resetFloor/bondPercent
# premiumRatio 为小数（0.0702 = 7.02%，与 latest_quotes 同口径，SDK 已换算）
# callHits = 服务端 30 交易日窗「正股收盘 ≥ 强赎触发价」天数（勿以单日价判定）
# resetFloor = 下修地板价测算（仅下修提案/实施中的债有值）；stockName 含 ST 即风险警示

# 可转债：条款事件流（下修提案/实施、强赎/不强赎、回售、除权调价、转股期等 9 类）
evs = cli.cbond.event_list()            # 90 日回看；行含 convert_price_old/new 与公告原文链接

# 可转债：转债日 K（列式 MAP：open/close/high/low/volume/amount；samplingName 日期降序）
kw = cli.cbond.kline_window("113050", 60)

# 可转债：一条链路跑完一期日更（取数 → 三道闸 → 事实包 → 成稿 → 出图）
payload = cli.cbond.daily(top_n=20, budget=30)
# payload 含三层口径（全表 1066 / 行情基座 / 闸门基座）、三道闸剔除明细、
# 七态强赎与五态下修状态机、事件日历、每只债的可追溯事实条目
art = cli.cbond.article(payload, date="20261107")   # {source, wechat, summary}
figs = cli.cbond.figures(payload, "/tmp/cb", date="20261107")  # 需 pip install "wmshare[figures]"

# 完整实战见 docs/notebooks/cb_double_low.ipynb（双低榜 + 强赎/下修观测 + 通道拨测）

# 指数：成分股（按市值权重取前 N）/ 权重股 / 估值时序
cli.index.members("index.hs300", "mv", 10)

# 选股筛选器（一行布尔；停牌恒 False）
cli.screener.screen_limit_up("600519")      # 今日涨停？
cli.screener.screen_above_ma20("600519")    # 站上 20 日线？
cli.screener.screen_volume_spike("600519")  # 放量？

# 全市场条件选股：一条表达式扫服务端索引（不是逐票 eval，也不本地过滤）
res = cli.screener.query(
    "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15 && !$IS_ST",
    order="$BONUS_RATE_3Y_AVG_LAST", limit=10)
res["count"]                                 # 全市场命中数（不受 limit 截断）
res["rows"][0]                               # {'symbol': '900948', 'name': '伊泰B股',
                                             #  '$BONUS_RATE_3Y_AVG_LAST': 0.2104, ...}
cli.screener.query("$ROE_TTM_LAST > 0.30", limit=0)   # 只要命中数（不拉行）

# 全市场宽度（服务端索引直出；*_pct 是百分数数值、median_pct 是小数）
cli.screener.index_breadth_summary()
# {'total': 5685, 'up': 540, 'down': 5002, 'up_pct': 9.5, 'median_pct': -0.0154, ...}
# total = 当日参与涨跌统计的家数（全市场列表是 5,691，含停牌等不参与统计的）
cli.screener.index_top_movers(limit=10)     # 涨幅榜（desc=False 跌幅榜）

# 公司档案
cli.info.profile("600519")
```

### 3.1 单股回测：买卖点 → 成交明细

一条调用出「金叉买 / 死叉卖」的逐笔成交与净值汇总。取全历史需要放开单次上限：

```python
cli = wmshare.Client.from_env(max_limit=None)      # 默认 500 根不够长区间回测
res = cli.backtest.run("600519", fast=5, slow=20)  # 收盘价 5/20 日均线交叉
res["trades"][:2]
# [{'date': '2026-07-16', 'side': 'buy', 'price': 1252.0, 'shares': 700,
#   'amount': 876400.0, 'fee': 262.92, 'reason': '金叉'},
#  {'date': '2026-08-06', 'side': 'sell', 'price': 1310.0, 'shares': 700,
#   'amount': 917000.0, 'fee': 733.6, 'pnl': 39603.48, 'ret': 0.045175,
#   'hold_days': 24, 'reason': '死叉'}]
res["summary"]
# {'total_return': 0.0689, 'cagr': 0.184, 'max_drawdown': -0.0861, 'sharpe': 1.06,
#  'n_trades': 4, 'win_rate': 0.5, 'avg_hold_days': 12.75, 'buy_hold_return': 0.1022}

# 换规则：PE/PB 估值买卖点（估值 <= buy 买、>= sell 卖）
res = cli.backtest.run("600519", rule="pe", buy=20, sell=40,
                       begin="2023-11-01", end="2026-11-01")
res["caliber"]["valuation"]   # {'metric': 'pe', 'window': '3y'}
```

**估值规则的上限**：单股估值序列只有 `cli.valuation.hist_stats` 的 **≤3 年日频**
（PE/PB/PS/PR，公告日 TTM、无未来函数），所以 `rule="pe"` 之类最多回测 3 年；
区间更早的部分会自动剔除并给 warning，亏损期等没有估值的日子当日不出信号。
`rule` 可取值：`ma_cross`（默认）/ `pe` / `pb` / `ps` / `pr`。

固定口径（不另有开关）：信号当根收盘后确定、**次日开盘**成交（T+1）；100 股整手；
佣金 0.03%（最低 5 元）、卖出印花 0.05%；一字板（`open==high==low==close`）与
零量（停牌占位）顺延到下一根，次数见 `caliber["skipped"]`；期末持仓按最后一根
收盘平仓（`reason="期末平仓"`）。

取数成本：不传 `begin/end` 时取全历史 1 万根，约 **40 万 EC**（EC 按请求行数计费）；
只看近两年就显式传区间，只取该区间需要的根数，EC 降到几万——
`cli.backtest.run("600519", fast=5, slow=20, begin="2024-01-01", end="2026-11-01")`。

**两层分工（别把内核当入口）**：`cli.backtest.run` 是**取数入口**——K 线（与 PE/PB 规则的
估值序列）走服务端，请求次数与 EC 照常计；`wmshare.backtest` 下的
`run_backtest(bars, signals, cash=...)`、`ma_cross_signals`、`valuation_signals`、
`valuation_by_date` 是**纯计算内核**，自己准备 `bars`/`signals` 时不联网、不计 EC。

**不建模**（别当撮合级结果用）：历史 ST 与 ST 的 5% 涨跌停、涨跌停排队与部分成交、
分红税与送转（`adj="qfq"` 只调价格，`"nr"` 不复权会把分红日当亏损）、分钟级、
组合/加仓/做空、止损止盈（需要就把规则并进买卖点判断或自己拿到 `trades` 后二次加工）。

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

### 4.1 指数与行业的历史估值（14 年周频 PE/PB）

这是本 SDK 里**计算量最重**的一类数据：每个键的每一期估值，都要把该指数/行业**全部成分股**
的市值与归母净利润 TTM 汇总后相除。沪深 300 一个点 = 300 家公司的汇总；31 个申万一级行业
连起来覆盖全 A 股。周频 14 年就是「56 个键 × 约 730 期 × 每期数百至数千成分股」的量级，
单键单次全量重算实测约 **3.2M fuel / 39 秒**。所以它**不在请求时现算**，而是服务端 cron
预热成缓存，`cli.index.trend` 只读缓存——这也是它能在一次调用里返回 730 个历史点的原因。

```python
import wmshare
cli = wmshare.Client.from_env()

t = cli.index.trend("index.hs300", "5y")     # 宽基：11 个键（index.hs300/csi500/sz50/…）
t["n"], t["points"][0], t["points"][-1]      # 730 个周频点；points[0] 是最新点（新→旧）
t["pe_pct"], t["pb_pct"]                     # 0.7671 / 0.5753（小数，0.7671 = 76.7% 分位）
t["pe_pct_window"]                           # '5y'：实际生效的分位窗口

for k in cli.index.universe_keys("industry"):    # 申万一级 31 个键
    r = cli.index.trend(k, "5y")
    print(k, r["points"][0]["pe"], r["pe_pct"])
```

**覆盖范围**（三类键共 56 个，均有预热缓存）：

| 组 | 个数 | 键形如 | 取值 |
|---|---|---|---|
| 宽基指数 | 11 | `index.hs300` / `index.csi500` / `index.sz50` / `index.cybz` / `index.star50` / `index.shzs` … | `universe_keys("broad")` |
| 申万一级行业 | 31 | `industry.S11`（农林牧渔）… | `universe_keys("industry")` |
| 红利指数 | 14 | `index.csidividend` / `index.ssedividend` … | `universe_keys("dividend")` |

外加伪键 `energy`（煤炭 + 石油石化 + 公用事业三行业合并，月频）。**申万二级/三级（L2/L3）
不预热**——`trend` 对这类键返回 `ok=False`（不会静默给假数据）；中信行业分类无此数据。

#### 口径算法

**① 指标公式（整体法）**

```
PE(TTM) = Σ 成分股市值 / Σ 成分股归母净利润(TTM)     # $ID_PE_TTM_TOTAL
PB      = Σ 成分股市值 / Σ 成分股净资产(不含商誉)    # $ID_PB_TTM_TOTAL
```

即**整体法**（aggregate method）：先汇总全成分股的市值与利润，再相除。这与「逐票算 PE 再
平均」完全不同——后者会被小市值高 PE 股拖偏。分母 Σ归母净利润 ≤ 0 时（该行业整体亏损）
PE 返回空值，而不是负数或 0：因此某些行业在特定时期**本来就没有 PE**。

另附月频 `pe_med`（成分股中正 PE 的中位数，剔除 PE≤0 的亏损股），用于对照「中位数视角」。

**② 采样与深度**

- 回溯窗口 `cursor.ds(3650)` ≈ **14.5 年**，取这个长度是为了让 10 年分位窗口有足够样本
  （若只取 2430 个交易日 ≈ 6.6 年，10 年分位必然截断）。
- 周采样每 5 个交易日取一点 → 约 **730 点**；月采样每 21 个交易日 → 约 174 点（用于中位数）。
- 增量更新在头部按日补点（每周最多 5 个日点），周六全量重算后重锚回周网格。

**③ 分位算法**

```python
rank0 = (小于当前值的样本数 + 小于等于当前值的样本数 - 1) / 2   # 并列取中点
分位  = rank0 / (n - 1)                                        # 归一到 [0, 1]
```

- 只统计**正数样本**（PE/PB 为空的期次跳过），`n` 是该窗口内的有效样本数。
- 测的是 `points[0]`（最新点），窗口下界 = asof 回退 N 个**日历年**。
- **窗口盖不住时给 `None`，绝不降级**：沪深 300 缓存跨 2016-11-16 → 2026-11-09（9.98 年），
  所以 `window="10y"` 的 `pe_pct` 是 `None` 且 `pct.pe.trunc10=True`——不拿 9.98 年冒充 10 年。
- 一次调用返回三档（`pct.pe.p3/p5/p10`），`window` 只决定 `pe_pct` 取哪一档，不改变序列长度。

**④ 更新时点**

cron 每交易日收盘后分批增量（16:20 宽基、16:23/16:26 申万一级前后半、16:29 红利），
周六 4 个 job 全量重算。`as_of` 是数据截止日；缓存未命中返回 `ok=False`，不会拿旧值冒充。

#### 读返回时要注意的四件事

| 现象 | 含义 |
|---|---|
| `points` 是**新→旧** | `points[0]` 是最新点。写成 `points[-1]` 会拿到 2016 年的值 |
| `pe_pct` 为 `None` 且 `pe_missing=True` | 该主体**当前无 PE**（行业整体亏损），不是数据缺失 |
| `pe_pct` 为 `None` 且 `win_trunc=True` | 窗口盖不住（如 10y），可降窗口重取 |
| `dv_has_history=False` | 股息率**只有当前值、无历史序列**，因此没有股息率分位 |

实战榜单（三组键 × 估值 + 通道拨测 + 星级）见
[docs/notebooks/index_daily.ipynb](notebooks/index_daily.ipynb)。

## 5. 批量取数（绕开 429 的正解）

可运行版本：`examples/07_stocks_industry_batch.py`。

### 5.1 三个入口怎么选

| 入口 | 用途 | 请求数（N 个标的） | 关键参数 |
|---|---|---|---|
| `batch_all(name, symbols)` | 一站式：自动分批并聚合 | ⌈N/500⌉ | `on_batch_error="raise"/"skip"` |
| `batch_iter(name, symbols)` | 逐批流式：进度/中断/落盘 | ⌈N/500⌉ | 逐批 yield `BatchResult` |
| `call_batch(name, symbols)` | 单批（≤500） | 1 | `on_error` 是**票级**，勿做容错 |

**批量省的是请求次数，不是 EC。** 开放平台开放 API 按计算量（EC）计费：
多标的批量在服务端仍按标的数逐票计算，一轮全市场 ≈ 12 批 × 每标的固定成本，
重放几百遍就是数亿 EC。两个习惯：① `BatchResult.ec_cost` 与
`cli.last_ec_cost` 会回传每次消耗，单次超过 `Client(ec_warn_threshold=…)`
（默认 10 万）SDK 直接告警；② 全市场**最新快照**类数据（资金流等）优先用
服务端一次取数接口（如 `cli.moneyflow.board()`），逐票批量留给确需逐票
历史的场景，并配合 `batch_iter` 边取边落盘。

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
- **`name` 必须是目录函数名**（269 个，`cat.functions_by_domain()` 可查）；指标码不是
  函数名——一票多码用 `cli.indicator.metrics(sym, codes)`（传 `"indicator.get"` 会报
  `CatalogError`）。**全市场按指标条件选股不要逐票批量**：一条表达式交给
  `cli.screener.query(...)`（服务端索引引擎，见第 3 章与 10.1）。

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
us.kline.bars("AAPL", n=5)            # 美股日 K 日更常态（上游管线调度转正，见注记）
us.kline.bars("AAPL", n=5, freq="W")  # 美股周 K（日线派生；月用 freq="M"）
us.intl.query_sellshort("AAPL")       # 美股沽空
```

注记：美股日 K 已转日更常态（上游管线调度转正 + EOD 盖回翻闸，2026-11-09 验收；偶发 T-1 滞后属正常），最新价量以
`kline.live/snapshot` 为权威；港美专项覆盖矩阵见 [README](../README.md)「市场覆盖」。

### 6.1 宏观与期货

宏观走 `cli.macro`（上游原生口径：$CPI 等价格指数=点、$GDP/$M2=元；中债收益率=小数）：

```python
cli.macro.query("$CPI", 6)            # 时序：series 每点含 sas/annual/sampling/value（最新在前）
cli.macro.asof("$GDP")                # 最新单值（元；实测 107107120000000 ≈ 107.1 万亿）
cli.macro.sampling_of("$CPI")         # 原生频率 "month"/"quarter"/"year"/"day"
cli.macro.bond_curve("中债国债收益率曲线", "10年")   # 0.0168 = 1.68%（小数）
cli.macro.nev_monthly("零跑", "sales")               # 行业情报单值（名单精确匹配，掉榜 None）
```

期货走指标码层（主力连续，日/周/月三族；`symbol` 传任意 A 股代码绑定期间上下文，
合约键经 `fut_symbol` 指定——国内 `cn.SR.ZCE`（后缀非 .CZCE）/`cn.RB.SHF`，外盘 `global.CL`）：

```python
cli.indicator.get("600519", "$FUT_CLOSE")                           # 缺省 cn.SR.ZCE
cli.indicator.get("600519", "$FUT_CLOSE", fut_symbol="global.CL")   # 外盘 WTI
```

代码表与口径详见 [API.md](API.md)「期货」「宏观」两章。

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
按请求次数计费意味着批量是乘法级省**请求次数**：全市场 4 个指标 × 12 批 = 48 次，
仍占小时额度不到 10%。实测基线（2026-10-29）：全市场 5,691 家快照 12 批约 9 秒、
0 错误；`res.requests` 字段可直接对比标的数看省了多少。

注意口径：SDK 配额按请求次数算，开放平台 EC 按**计算量**算（第 5.1 节）——
批量对前者是省、对后者不省。EC 消耗经 `BatchResult.ec_cost` /
`cli.last_ec_cost` 可见，超大单次消耗 SDK 会主动告警。

### 10.1 全市场选股：一条索引查询 vs 逐票 eval vs topN 抽样（2026-11-10 实测）

同一道题「三年股息率均值 > 3% 且 ROE > 15%」（剔停牌/ST/B 股）三种做法的实测：

| 做法 | 请求 | EC | 命中数 |
|---|---|---|---|
| `cli.screener.query("$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15 && !$IS_ST && !$IS_SUSPEND", order=..., limit=10)` | 1 | **219**（count-only 70） | **108（全量）** |
| 逐票 `cli.indicator.metrics(sym, [...])` 扫全市场 | 5,691 | ≈45.6 万 | 108 |
| 先按 TTM 股息率排序取前 60，再逐票判 3Y 均值 + ROE | 12 + 60 | ≈5 千 | **8**（漏 100） |

- 逐票 eval 是 **EC 最贵**的路径：eval 按标的数逐票计价，全市场一轮 ≈45.6 万 EC，
  且 SDK 会触发阈值告警（`Client(ec_warn_threshold=None)` 可关）。
- `screener.query` 的 EC 随 where/order **引用列的物化成本**变化（轻列 70~500，
  重列如 `$NPTS_TTM_YOY_LAST` 实测 4.8 万），但**不随标的数放大**：一次请求扫完
  5,691 家。还是那句话：先 `cat.search` 查码，能用已物化的轻列就别绕重列。
- topN 抽样不仅省不了钱，还会**算错**：3Y 均值与 TTM 并不单调（例：立霸股份 TTM
  6.9%、3Y 均值 11.4%，进不了 top60），而且真命中 108 只、`[:60]` 这个截断本身就不够。
- 纪律：**先 `cat.search` 查码再写计算**；条件选股走 `cli.screener.query`；批量
  （`batch_all`）留给确需逐票历史的场景；全市场快照类优先服务端直出
  （`cli.moneyflow.board()`）。

## 11. 用 AI 学会并用好 SDK

完整指南见 [AI.md](AI.md)。三句话版本：

1. **装 skill（一条命令）**：`cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" ~/.agents/skills/wmshare`，AI 自动获得目录先行、单位铁律、意图→接口决策树；
2. **没 skill 目录的 agent**：把本指南与 [API.md](API.md) 喂作上下文，或直接喂 `llms.txt`（仓库根，AI 友好索引）；
3. **报错驱动**：错误消息自带修复步骤，把 traceback 原样贴给 AI 即可定位。

## 12. FAQ

- **和直接下交易所数据比，图什么？** 目录先行 + 单位统一 + 数据守护 + 批量限流治理——
  取数正确性的工程问题 SDK 替你管了。
- **数据能离线吗？** 目录（269 个函数/2752 个指标码/代码表）随包离线；行情财报数据在云端，
  需凭证与额度。
- **支持哪些 Python？** ≥3.10；pandas 为可选依赖。
- **怎么贡献/报漏洞？** 见 [CONTRIBUTING](../CONTRIBUTING.md) 与 [SECURITY](../SECURITY.md)；
  agent 贡献者另见 [AGENTS.md](../AGENTS.md)。
