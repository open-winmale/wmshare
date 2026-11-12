# wmshare

[![PyPI](https://img.shields.io/pypi/v/wmshare)](https://pypi.org/project/wmshare/) [![Python](https://img.shields.io/pypi/pyversions/wmshare)](https://pypi.org/project/wmshare/) [![CI](https://github.com/open-winmale/wmshare/actions/workflows/ci.yml/badge.svg)](https://github.com/open-winmale/wmshare/actions/workflows/ci.yml) [![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

> **English TL;DR** — `wmshare` is a BSD-3-Clause Python SDK for China A-share / Hong Kong / US
> market data: k-line, intraday, money flow, statements, screener, whole-market batch, and
> **2,752 server-precomputed metrics** (percentile ranks, multi-window averages, industry-relative
> ranks — no DIY computation). Ships an offline catalog, data guards and AI skill. **Credentials
> required** on open.winmale.com; try offline first with `wmshare.demo_client()` (frozen snapshot;
> not live). **Install**: `pip install wmshare`. **Full English quickstart**: [docs/QUICKSTART_EN.md](docs/QUICKSTART_EN.md).

给 Python 量化开发者的中文财经数据 SDK：一行接口拿到清洗好的 A股/港股/美股数据——
估值分位、TTM 股息率等指标**服务端算好直出**，全市场批量 **12 次请求**绕开限流。
凭证在开放平台（open.winmale.com）获取后即可取数；各市场逐能力明细见[「市场覆盖」](#市场覆盖)。

## 目录

[基本功能](#基本功能) · [特色功能](#特色功能) · [快速上手](#快速上手) · [给 AI / Agent](#给-ai--agent) ·
[主站、开放平台与 SkillHub](#主站开放平台与-skillhub) · [市场覆盖](#市场覆盖) · [我想做 X → 用哪一行](#我想做-x--用哪一行) · [批量取数](#批量取数) ·
[指数与行业估值历史](#指数与行业估值历史) · [单位与数据守护](#单位与数据守护) ·
[许可与数据服务](#许可与数据服务) · [更多](#更多)

![notebook 实战：Jupyter 里 10 行代码筛出高股息 + PE 十年低位的股票（2026-10-30 真实数据）](docs/img/quickstart.png)

## 零凭证先试

装完就能跑，不用注册、不联网（随包内置 2026-10-30 固定快照，非实时数据）：

```python
import wmshare

cli = wmshare.demo_client()
print(f"{cli.dividend.yield_ttm('600519'):.2%}")        # 3.73%
print(cli.screener.index_breadth_summary()["total"])   # 5686
```

接真实行情只换一行：`cli = wmshare.Client.from_env()`（凭证配置见下节）。
指标怎么选、每条能替你省掉哪些计算，见[我想做 X → 用哪一行](#我想做-x--用哪一行)。

## 快速上手

### 安装

```bash
pip install wmshare                  # 基础安装
pip install "wmshare[dataframe]"     # 可选：pandas 支持（_df=True）
pip install "wmshare[mcp]"           # 可选：本地 MCP server
python3 -c "import wmshare; print(wmshare.__version__)"   # 验证安装
```

国内直连不稳时换清华源：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple wmshare`（镜像滞后时回官方源）；升级 `pip install -U wmshare`（Windows 用 `py -m pip install -U wmshare`）。

### 配置凭证

凭证在 [开放平台](https://open.winmale.com)「我的 → 开放平台 → 我的应用」页获取 `AppId（Client ID）` 与 `API Key（Client Secret）` 两个值（缺一不可），配置方式任选其一：

```bash
export WMSHARE_CLIENT_ID=<AppId> WMSHARE_CLIENT_SECRET=<API Key>   # 方式一：环境变量
# 方式二：~/.wmshare/credentials.env（KEY=VALUE 每行一条）
# 方式三：构造参数 cli = wmshare.Client(client_id="...", client_secret="...")
```

<!-- mcp-name: io.github.open-winmale/wmshare -->

### 选股实战：一条表达式筛出「三年股息均值 > 3% 且 ROE > 15%」

条件写成一条表达式交给服务端索引引擎扫全市场（不是逐票请求、也不是本地过滤）：
`count` 是**真实命中数**，`rows` 只是前 N 条——不会把 topN 当成全市场结果：

```python
import wmshare
cli = wmshare.Client.from_env()
res = cli.screener.query(
    "$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15"
    " && !$IS_ST && !$IS_SUSPEND",
    order="$BONUS_RATE_3Y_AVG_LAST", limit=10,
)
print(res["count"])            # 全市场命中数（不是 10）；2026-11-10 实测 108
for r in res["rows"][:5]:
    print(f'{r["symbol"]}  {r["name"]}  '
          f'三年股息率均值 {r["$BONUS_RATE_3Y_AVG_LAST"]:.2%}  '
          f'ROE {r["$ROE_TTM_LAST"]:.2%}')
# 900948  伊泰B股  三年股息率均值 21.04%  ROE 16.31%
```

`where` 用 XS 语法（`&&` / `||` / `!`，比率一律小数），`$码` 必须是目录内真码；
要分页续取用 `offset`，只要命中数用 `limit=0`。没配凭证也能先看调用面：
`cli = wmshare.demo_client()`（同签名、不联网）——`query` 需真实凭证，离线快照只存
10 只演示宇宙 + 当日全市场 screener，非实时数据；换成 `Client.from_env()` 即接真实数据。

## 基本功能

随包离线目录：**18 个数据域 · 288 个底层函数 · 2752 个指标代码**；友好层 **132 个核心接口**，
按使用视角组织为（11 个指标组、74 个精选常用指标代码，`cat.search("中文")` 可编程检索）：

| 门面 | 核心能力 | 单位口径 |
|---|---|---|
| `cli.kline` | 日 K 三种复权（自上市首日起全覆盖，最早 1991 年）、周 K/月 K、最新/盘中快照、1 分钟分时（个股；ETF 无分钟源，查询被拦截）、ETF/指数 | 价格=元、量=股、涨跌幅=小数 |
| `cli.screener` | 全市场条件选股（`query`，一条 `$码` 表达式出命中数与前 N 行）+ 单票筛选器（涨停/均线/动量/回撤/放量）+ 全市场涨跌全景/分桶/行业分布/涨跌榜 | 阈值=小数；涨跌家数统计的 `*_pct`=百分数数值 |
| `cli.backtest` | 单股买卖点回测（取数 + 本地撮合；纯内核 `wmshare.backtest` 可自备数据）：均线金叉/死叉 或 PE/PB/PS/PR 估值阈值（估值序列 ≤3 年）→ 成交明细 + 净值/回撤/胜率（次日开盘成交、T+1、100 股整手、佣金/印花固定） | 价格=元、收益=小数 |
| `cli.moneyflow` | 主力/超大单/大单/中单/小单净流入（日频） | 金额=元 |
| `cli.statements` | 三大报表多期、合并 vs 母公司、目录树、审计意见 | 报表原币元 |
| `cli.segments` | 经营分部：分产品/业务/区域收入构成 | 元；比率=小数 |
| `cli.indicator` | 按指标码取数：估值/盈利/成长/现金流/杜邦、期货主力连续（`$FUT_CLOSE` 等 27 码 + `fut_symbol`）；全量码表见 [INDICATORS.md](docs/INDICATORS.md) | 比率=小数 |
| `cli.valuation` | PE/PB/PS/市赚率(PR)的历史统计与分位（窗口上限 3 年） | 分位=小数 |
| `cli.notice` | 公告检索、回购/减持信号 | — |
| `cli.filings` | 定期报告清单与最新 | — |
| `cli.forecast` | 业绩预告/快报、财报披露日历 | 同比=小数 |
| `cli.dividend` | 分红历史、TTM 股息率/派息率、11 个质量筛选器 | 率=小数、DPS=元/股 |
| `cli.equity` | 股东治理：十大股东/股东户数/质押/解禁/机构持仓/沪港通/国家队/高管增减持/股本/回购/并购重组/关联交易/担保/诉讼 | 比例=小数、金额=元、量=股 |
| `cli.margin` | 个股融资融券（融资买入/偿还/余额、融券卖出/偿还/余量） | 金额=元、量=股 |
| `cli.estimates` | 机构盈利预测（逐年 EPS/PE）、预测明细、评级统计、个股研报 | EPS=元/股、PE=倍 |
| `cli.cbond` | 可转债合约快照、条款事件、正股关联、强赎计数、日 K 与盘中 1 分钟；`daily/article/figures` 一条链路出日更图文 | 价格=元（面值 100） |
| `cli.workout` | 契约套利条款（要约收购/换股/现金选择权）看板与单票查询 | 价格=元 |
| `cli.index` | 指数键列表、成分股（市值/估值中枢）、权重股、**指数与申万一级行业的估值趋势**（周频整体法 PE/PB，约 14 年，带 3/5/10 年分位） | 市值=元、比率=小数、权重=小数 |
| `cli.stocks` | 全市场证券列表（代码/名称/交易所/三级行业/上市日/ST）、行业目录（申万/恒生）、行业成分股（中文名直达） | listed=YYYY-MM-DD、is_st=布尔 |
| `cli.intl` | 港股 CCASS（中央结算持仓）/主要股东/机构评级/盈利预测，港美沽空，美股发行信息 | 量=股、占比=小数、价格=披露币种 |
| `cli.macro` | 宏观时序/as-of/采样频率（$CPI/$GDP/$M2…）、中债收益率按期限、行业情报单值 | 上游原值（价格指数=点、流量存量=元、收益率=小数） |
| `cli.info` | 公司档案（名称/行业/组织类型/上市日期） | — |

## 特色功能

**服务端预计算，先查目录再写代码**——目录里有的码不要自己算（eval 按标的数逐票计费 EC）：

- **预置指标库（2,752 个指标码，11 组精选 74 码带量级守护）**：历史分位（`$PCT_PE_TTM_10Y_LAST`
  = PE 十年分位）、多窗口均值/最低/趋势（`$BONUS_RATE_3Y_AVG_LAST` = 近3年股息率TTM均值）、
  行业内分位（`$CUR_IND_ROE_PCT_LAST`，1=行业最高）、行业均值（`$ID_ROE_TTM`）、指数加权股息率
  （`$IDW_BONUS_RATE_HM`）、期货主力连续（`$FUT_CLOSE`）、宏观时序（`$CPI`）。命名语法
  `$主题+[窗口 3Y/5Y/10Y]+[统计量 TTM/YOY/AVG/MIN/TREND]+[_LAST]`；**全量码表按数据类型分章**
  （概览/股票行情/股票指标/行业/指数及ETF/宏观/期货/可转债/港美）见
  [docs/INDICATORS.md](docs/INDICATORS.md)。
- **全市场批量**：`cli.batch_all(name, codes)` 把 A 股 5,691 家压成 **12 次请求**绕开限流。
- **全市场筛选服务端直出**：`cli.screener.query("$ROE_TTM_LAST > 0.15")` 一条表达式扫全市场索引
  （`count`=真实命中数）；涨跌全景/分桶/行业分布/涨跌榜同走服务端预计算索引，毫秒级。
- **离线目录防编造**：288 个底层函数、132 个核心接口、2,752 个指标码离线可查
  （`cat.search("中文")`），目录之外的名字显式报错。
- **零凭证离线试跑**：`wmshare.demo_client()`（同签名、不联网，2026-10-30 固定快照；非实时数据）。
- **数据守护**：全库单位统一（比率=小数、金额=元、量=股），返回前量级/不变量校验，违例抛 `DataError`。

## 给 AI / Agent

- **先查目录再写代码**（一行验证）：
  `python3 -c "import wmshare; print(wmshare.load().search('股息'))"`
- **本地 MCP server**：20 个 task tools；全部 136 个 friendly API——132 登记 + 4 组合——均可用
  `wmshare_call(target=..., mode="api")` 兜底，macro 域仅此路径。配置：`pip install "wmshare[mcp]"`
  → `wmshare-mcp setup --client-id <AppId> --client-secret-stdin --market cn`（提示后粘贴 API Key，
  `wmshare-mcp doctor` 体检）；客户端最小配置
  `{"mcpServers":{"wmshare":{"command":"wmshare-mcp","args":[]}}}`；接入路径详见 [AI 用法](docs/AI.md)。
- **skill 随包分发**：`wmshare.skill_dir()` 可复制进 `.agents`/`.zcode`/`.claude` 的 `skills/`。
- **AI 友好索引**：[llms.txt](llms.txt)（索引）/ [llms-full.txt](llms-full.txt)（全文拼接，大上下文直读）。

## 主站、开放平台与 SkillHub

同一套数据有三层入口，按使用方式选：

- **[winmale.com](https://winmale.com)（主站）**——不想写代码就看结果。工具按投资者类型分开：
  - 找低估：市赚率阶梯、银行 PB 阶梯、行业贵不贵、格雷厄姆选股
  - 做定投：**指数定投**（估值评级榜单 + 定投回测，宽基/行业/红利/主题，整体法与中位数双口径）
  - 做套利：**可转债**（转股成本对正股价，转股有起始日）、套利股（已公告要约）、两地折价（A/H）
  - 读财报：**财报专业版**（资产负债表/利润表/现金流量表/主要指标十年表页，A 股与港股同构）
  - 跟机构：抄作业（13F 持仓）；另有 ETF 精选、全榜排行、市场拥挤、宏观与海关等，共 25 个内置应用
  - 工作台：市场总览、行业涨跌热力图、估值排行（低估/合理/高估）；分免费版 / 基础版 / Pro 三档
- **[open.winmale.com](https://open.winmale.com)（开放平台）**——把数据接进自己的系统：
  XS 求值 API、Playground 在线调试、数据目录（指标与分析脚本可浏览试跑）、
  12 篇接入文档（认证/错误码/限速与 EC 配额/缓存重试）、下载中心与控制台。
  **本 SDK 就是它的官方 Python 封装。**
- **[SkillHub](https://open.winmale.com/skillhub)**——在 AI 助手里用自然语言提问：
  37 个金融 Skill + 5 个投研 Role 整包一键装进 Cursor / Claude / WorkBuddy，
  登录后复制安装话术交给助手完成，即可取数、读财报、跑筛选。

> 与本 SDK 的分工：主站给「想直接拿到结果」的人，开放平台给「要接进自己系统」的开发者，
> SkillHub 给「想在 AI 里问」的使用者；wmshare 是开放平台的 Python 封装，负责第三条路的取数层。

## 市场覆盖

| 数据能力 | A股 cn | 港股 hk | 美股 us |
|---|---|---|---|
| 日 K 三种复权 / 周 K·月 K（服务端派生）/ 1 分钟分时 / 盘中快照 | ✅ 全量 | ✅ | 日 K 日更 + 周/月 K 派生；快照/盘中新鲜（注记见下） |
| 指标库（2,752 码：估值/盈利/成长/分红/分位/振幅/技术面） | ✅ | ✅ | ✅（用裸代码 `AAPL`；`AAPL.O` 由 SDK 归一） |
| 分红：历史、TTM 股息率/派息率、质量筛选 | ✅ | ✅ | ✅（窗口口径固定） |
| 公告与披露信号 | ✅ | ✅ | — |
| 财报清单与最新披露 | ✅ | ✅ | — |
| 股东治理：高管名册 / 高管增减持 / 股本变更 | ✅ | ✅ | ✅（仅股本变更） |
| 股东治理：十大股东 / 质押 / 解禁 / 机构持仓 / 重组 / 担保 / 诉讼 / 股东户数 | ✅ | — | — |
| 全市场选股：单票筛选器 / 涨跌全景 / 高息池 | ✅ | 部分（单票筛选可用；高息池索引暂缺） | — |
| 港美专项：CCASS / 主要股东 / 机构评级 / 盈利预测（`cli.intl`） | — | ✅ | — |
| 港美专项：沽空（`cli.intl.query_sellshort`） | — | ✅ | ✅ |
| 港美专项：发行信息（`cli.intl.issue_info`） | — | — | ✅ |
| 资金流 / 两融 / 可转债 / 业绩预告 / 盈利预测研报 / 经营分部 / 契约套利 | ✅ | — | — |
| 全市场列表 / 行业目录 / 行业成分（`cli.stocks`） | ✅ | ✅ | 列表 ✅（美股代码表手动刷新有滞后）；行业目录树暂缺 |
| 离线代码表 + 检索（`cat.symbols_search`） | ✅ | ✅ | ✅ |

市场切换：`Client(market="cn" / "hk" / "us")`，缺省 cn；代码与市场不匹配会被服务端直接拒绝（如 cn 市场查
`00700` 报 market mismatch）。美股用裸代码（`AAPL`/`BRK_B`），`AAPL.O`/`BRK.B` 由 SDK 按代码表自动归一；`cli.intl` 港美股披露也要用对应市场客户端调用。

如实注记（2026-11-09 实测）：港/美列 ✅ 均经 live 探针逐族验证；美股用裸代码（`AAPL`/`BRK_B`，带后缀会被当宏观序列，SDK 按代码表归一）；美股日 K 日更，周/月 K 由日线派生，后复权无外部因子源，分时仅美股盘中（北京夜间）有值。深研宽表暂仅 cn；hk 十大流通股东与回购管线已有、SDK 接口待路由。

## 我想做 X → 用哪一行

| 我想做… | 一行接口 | 省掉的计算 |
|---|---|---|
| 看 TTM 股息率 | `cli.dividend.yield_ttm(sym)` | 拉全部分红史→截 TTM 窗→查市值→相除 |
| 判断估值贵不贵 | `cli.indicator.get(sym, "$PCT_PE_TTM_10Y_LAST")` | 拉十年估值史自己算百分位 |
| 看估值历史均值/中位/分位 | `cli.valuation.hist_stats(sym, "pe", "3y")` | 拉 3 年估值序列→自己算统计量 |
| 看公司在行业里的位置 | `$CUR_IND_ROE_PCT_LAST`（行业内 ROE 分位，1=行业最高） | 拉全行业成分→逐票取 ROE→排序 |
| 筛高股息且派息可持续 | `cli.dividend.screen_quality(sym)` | 自写股息/派息率质量模型 |
| 全市场按任意指标组合选股 | `cli.screener.query("$BONUS_RATE_3Y_AVG_LAST > 0.03 && $ROE_TTM_LAST > 0.15")` | 先批量拉全市场→本地过滤（还容易漏样本） |
| 回测这只票的均线买卖点 | `cli.backtest.run("600519", fast=5, slow=20)` | 拉 K 线→自己写撮合/费用→算净值回撤 |
| 回测 PE/PB 估值买卖点 | `cli.backtest.run("600519", rule="pe", buy=20, sell=40)` | 拉估值序列→自己判买卖→算净值（估值序列平台最多 3 年） |
| 站上 20 日线了吗 | `cli.screener.screen_above_ma20(sym)` | 拉 K 线→算均线→比较 |
| 全市场今天涨跌如何 | `cli.screener.index_breadth_summary()` | 全市场扫描→聚合统计 |
| 看最新十大股东 | `cli.equity.query_holder10(sym)` | 翻定期报告→抄股东名单 |
| 质押比例高不高 | `cli.equity.query_pledge_summary(sym)` | 翻质押公告→逐笔累加 |
| 下半年解禁压力大吗 | `cli.equity.query_release(sym)` | 翻解禁公告→手工排期 |
| 两融余额什么水平 | `cli.margin.query(sym)` | 翻交易所两融披露→对日期 |
| 券商怎么看这只票 | `cli.estimates.query_forecast(sym)` | 汇总各家研报预测→自己算均值 |
| 沪深300 都有谁 | `cli.index.members("index.hs300", "mv", 10)` | 找成分表→自己拉行情 |
| 这票正股有哪些转债 | `cli.cbond.of_stock(sym)` | 翻转债名录→逐只对正股 |
| 港股筹码在谁手里 | `cli.intl.query_ccass(sym)` | 上披露易→逐日查 CCASS |
| 今日涨幅榜前十 | `cli.screener.index_top_movers(limit=10)` | 全市场扫描→排序→取头部 |
| 近半年有无回购/减持 | `cli.notice.has_buyback(sym, "6m")` | 拉公告列表→分类匹配→截窗 |
| 合并与母公司差多少 | `cli.statements.compare(sym)` | 双表对齐→逐科目相除 |
| 拿全市场代码池 | `cli.stocks.list()` | 逐页拼列表→核对代码格式 |
| 银行股都有谁 | `cli.stocks.industry_members("银行")` | 查行业分类→逐票打标签 |
| 取 CPI/GDP 宏观时序 | `cli.macro.query("$CPI", 6)` | 找数据源→对齐期间→自己建时序 |
| 看期货主力连续行情 | `cli.indicator.get(sym, "$FUT_CLOSE", fut_symbol="cn.RB.SHF")` | 找期货源→清洗对齐 |

**常用示例（输出为预期量级）**：

```python
import wmshare

cli = wmshare.Client.from_env()

# TTM 股息率：小数口径，0.0396 = 3.96%
print(cli.dividend.yield_ttm("600519"))                      # 0.0396

# 估值温度计：PE(TTM) 处于近 10 年 42% 分位（小数）
print(cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST"))   # 0.42

# 行业定位：ROE 在同行业内的分位（1.0 = 行业最高；茅台 ROE 为行业之最）
print(cli.indicator.get("600519", "$CUR_IND_ROE_PCT_LAST"))  # 1.0

# 全市场涨跌全景：服务端索引直出，免本地扫描（*_pct 百分数、median_pct 小数）
print(cli.screener.index_breadth_summary())
# {'total': 5685, 'up': 4567, 'down': 934, 'flat': 184, 'up_pct': 80.3, ...}

# 全市场列表 / 行业成分（中文名直达，也可传 "S48"）/ 批量：单标的接口传 list 即批量（≤500/批）
rows = cli.stocks.list()                 # A 股 ≈5.7k 行：代码/名称/交易所/行业/上市日；港/美换 market
df = cli.call_batch("kline.snapshot", ["600519", "000001"]).to_df()   # 带 symbol 列的长表；to_df 需 pandas
```

以上能力全部在离线目录可查（`cat = wmshare.load()` 后）：`cat.search("分位")`、`cat.metrics_in_group("dividend")`；
全量指标码导航见 [INDICATORS.md](docs/INDICATORS.md)。

## 批量取数

服务端按**请求次数**限流（免费档 500 次/小时、5,000 次/日）：逐票取 A 股 5,691 家 = 5,691 次请求
必然撞 429，批量只需 **12 次**。三入口——一站式、逐批、单批：

```python
import wmshare
cli = wmshare.Client.from_env()
codes = [r["symbol"] for r in cli.stocks.list()]      # 全市场代码池（港/美换 market）
res = cli.batch_all("kline.snapshot", codes)           # ① 一站式：自动分批聚合
print(len(res.results), res.requests)                  # 5,691 12
for i, part in enumerate(cli.batch_iter("dividend.history", codes), 1):
    print(f"第 {i} 批 {len(part.results)} 家")          # ② 逐批：可进度、可中断、可落盘
cli.call_batch("kline.snapshot", ["600519", "000001"]) # ③ 单批（≤500），to_df() 出长表
```

要点：`name` 必须是**目录函数名**（指标码不能批量，一票多码用 `cli.indicator.metrics(sym, codes)`）；
容错用批级 `batch_all(on_batch_error="skip")`，**勿用 `call_batch(on_error="skip")`**（逐票放大、
正好制造 429）；一个批次只能同一市场；批量省请求次数**不省 EC**——全市场最新快照优先服务端直出
`cli.moneyflow.board()`。参数/续跑/分批策略明细见 [GUIDE · 批量取数](docs/GUIDE.md)。

## 指数与行业估值历史

**本 SDK 计算量最重的一类数据**：每个「点」都是该指数/行业**全部成分股**的市值与归母净利润
TTM 汇总相除（沪深 300 一点 = 300 家汇总；31 个申万一级连起来覆盖全 A 股）。周频 14 年
= 56 键 × 约 730 期 × 每期数百至数千成分股，单键全量重算实测 **3.2M fuel / 39 秒**，
故由服务端 cron 预热、接口只读缓存——所以一次调用就能拿到 730 个历史点：

```python
import wmshare
cli = wmshare.demo_client()                              # 离线可跑；真实数据换 Client.from_env()
t = cli.index.trend("index.hs300", "5y")                 # 宽基 11 + 申万一级 31 + 红利 14 键
t["points"][0], t["n"]                                   # 最新点（序列新→旧）, 730（demo 为 120）
t["pe_pct"], t["pe_pct_window"], t["pct"]["pe"]["p3"]    # 5y 分位, '5y', 3y 分位（三档一次给全）
```

口径：**整体法** `Σ市值/Σ归母净利润TTM`（PB 用不含商誉净资产，分母≤0 时 PE 为空）；周频约
730 点跨 14.5 年；分位 `rank0/(n-1)` 并列取中点，窗口盖不住时返回 `None` 而非降级（10y 实测
9.98 年 → `pe_pct=None`）；行业整体亏损时 `pe_missing=True`，是「无 PE」不是缺数据。股息率
只有当前值、无历史序列。**指标码 `$PCT_PE_TTM_10Y_LAST` 这类分位码按个股绑定、不随指数/行业键
切换**，指数/行业分位只能走 `trend`。完整算法、更新时点与四类返回值陷阱见
[GUIDE · 指数与行业的历史估值](docs/GUIDE.md)，榜单实战见
[docs/notebooks/index_daily.ipynb](docs/notebooks/index_daily.ipynb)。

## 单位与数据守护

全库统一基础单位：**比率 / 涨跌幅 = 小数**（0.01 = 1%，ROE 0.332 = 33.2%）、
**金额 / 价格 / 市值 = 元**（报表原币）、**成交量 = 股**；各接口单位口径见「基本功能」表。
返回前做量级与关系不变量校验，违例抛 `DataError`——错误的量级到不了你的代码。
需要脚本原始口径时：`_raw=True`（上游原始行）、`_units="native"`（保留上游原单位，如手/百分数）、`Client(validate=False)`（关校验留换算）。

数据深度：个股/ETF 日 K 覆盖**自上市首日以来的全部交易日**（最早 1991 年）；单次区间上限 5 年、
默认单次 500 根（`Client(max_limit=...)` 可调）；深回溯老数据可能触发守护，整段历史时 `validate=False`。

## 许可与数据服务

- 代码采用 [BSD-3-Clause](LICENSE)：可自由使用、修改、再分发（**含商业用途**），保留版权声明即可。
- 云端数据服务需 [开放平台](https://open.winmale.com) 账号：免费档 500 次/小时、5,000 次/日，更高额度以平台为准。
  **多标的一律走批量接口**（逐票循环是最容易撞 429 的写法，见「批量取数」）。
- 数据仅供研究参考，不构成任何投资建议。

## 更多

- **AI 原生**：随包 [SKILL.md](src/wmshare/skills/wmshare/SKILL.md)、[AI 用法](docs/AI.md)、本地 MCP server（skill 可复制进 .agents/.zcode/.claude 的 skills/）；生态工具 [big-winner](https://github.com/open-winmale/big-winner)。
- **文档中心 [docs/](docs/README.md)**：使用指南 GUIDE（单票菜谱/批量/多市场/故障排查）· 指标库 [INDICATORS.md](docs/INDICATORS.md)（全量指标码按数据类型分章）· AI 用法 · llms.txt 索引 · [API 参考](docs/API.md)（按资产类别分章的 132 个核心接口 + 指标组）
- **可转债日更管线**：`cli.cbond.daily()` → `article()` → `figures()` 一条命令出图文（三层口径 + 三道闸 + 状态机 + 事件日历，每个数字带 `sources` 与 `as_of`，缺条目抛错而非补猜测值）；实战 notebook 见 [docs/notebooks/cb_double_low.ipynb](docs/notebooks/cb_double_low.ipynb)（2026-11-07 真实数据）
- **示例课程 [examples/](examples/README.md)**：15 个编号示例（入门→进阶→生产→AI），全部支持演示客户端离线试跑，CI 端到端覆盖
- **问题反馈 / 交流**：QQ 群 `1127142074`（搜索「wmshare开源交流群」）——使用问题、数据口径、bug 反馈欢迎进群，也欢迎 [GitHub Issues](https://github.com/open-winmale/wmshare/issues)
- **维护者与治理**：[MAINTAINERS.md](MAINTAINERS.md)（响应承诺与发版流程）· [GOVERNANCE.md](GOVERNANCE.md) · [行为准则](CODE_OF_CONDUCT.md)

![wmshare开源交流群 QQ 群二维码（群号 1127142074，扫一扫加入）](docs/img/qq_group_qr.png)
