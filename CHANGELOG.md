# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> 兼容政策：2.0 前 minor 版本可能携带行为变更，均在对应版本段以「行为变更」标注；
> 升级前请扫一眼 Removed / Changed 段。

## [Unreleased]

## [1.14.1] - 2026-11-10

### Removed
- README 移除贡献者向内容：安装节「开发者安装见 CONTRIBUTING.md」、「更多」节贡献指南行、
  「给 AI」节死码警示行（死码清单下沉 docs/INDICATORS.md 与 SKILL.md；README 只留用户内容，
  PyPI 长描述同步瘦身）

## [1.14.0] - 2026-11-10

### Added
- **可转债债底与弹性指标（`cb` 子包 v4）**——`cb.valuation` 新增四条口径：
  `pure_bond_value`（纯债价值/债底，剩余票息 + 到期赎回价按收益率曲线逐笔贴现，
  与 `ytm_after_tax` 共用同一份现金流模型）、`ytm_pretax`（同一 IRR 骨架不扣利息税，
  只为与第三方「到期税前收益」可比）、`annualized_vol`（转债自身 20 日年化波动率）、
  `turnover_pct`（换手率 = 成交额 / 转债流通市值，即剩余规模×价格/100；分母用面值
  会把高价债整体放大 5 倍）。`cb.facts` 的 states 白名单补上此前
  取到即丢弃的 `convertPrice`/`redeemTrig`/`resaleTrig`/`issueScale`，并派生
  `reset_room_pct`（下修空间）、`convert_progress_pct`（转股进度）、
  `floor_buffer_pct`（价格距债底的空间，负值=已跌破债底）与 `field_coverage`。
  `DailyConfig` 新增 `enrich`/`curves` 开关；默认预算 30→60。
- **全表批量日 K 与收益率曲线取数**——`cb.daily` 用 `call_batch` 一次 eval 拼 MAP
  拉全表日 K（每批 ≤120 只 = 1 次 HTTP；逐票 311 次会先撞 429），并用
  `macro.bond_curve` 取「中债中短期票据收益率曲线(AAA)」与「中债国债收益率曲线」
  的 1/3/5/7/10 年点，作为债底的主口径与上界。曲线名写错会静默返回 `None`，
  故在常量处注明逐字匹配要求。
- **`cb.article` 榜单换列**——12 列宽度不变，进「债底 / 下跌空间 / 换手率」、
  出「剩余规模 / 剩余年限 / 下修状态」（后者移入完整版面板逐只可查）。

### Changed
- **`cb.facts` 纯债价值不扣利息税、贴现率不外推**——两条都是口径选择而非实现细节：
  债底按通行定义用毛票息；曲线在两端平推，避免凭斜率造出市场上不存在的利率。
  无评级输入故统一用 AAA 曲线，评级更低的债真实债底低于该值，对外必须标「自算口径」。
- **周 K / 月 K：`cli.kline.bars(freq="W"/"M")`（market.kline v1.5.0）**——新增上游周期读
  接口 `kline.query_bars_period[_adj]`（`period` 取 D/W/M，采样频率常量为字面量分支），
  SDK 侧 `freq` 接受 D/daily、W/week、M/month 别名，未知值抛 `UsageError`（不静默降级）。
  周/月为**服务端预派生**（由日线先复权再聚合，日期=周期末交易日），非客户端重采样；
  一次解锁 CN/HK/US 三市场周期 K（此前上游查询把采样频率硬编码为日频，CN/HK 库内已有的
  周/月文档也读不到）。指数键只有日频，`freq` 非 D 返回空列表
- **美股周/月 K 产出链（airflow `market.us.kline_week_month`）**：照港股既有做法从
  `mkt_kline_us` 日线本地聚合派生（`tasks/us_kline_week_month.py`，复用
  `aggregate_daily_bars`；incremental 值比对 + rebuild 全写 + 有界孤儿清理 + 跑后自检），
  weekly 变体周六 11:00（晚于美股日线 05:30 全池作业）。此前美股只有日线产出，
  `sampling_type=3/2` 为空，周/月查询返回 0 行；后复权仍无产出（外部 hfq 端点实测
  与不复权逐位相同，不可用），after 维持历史快照
- **全市场资金流快照 `cli.moneyflow.board()`**（market.moneyflow v1.1.0 扩展）：
  服务端索引一次取数返回全市场最新资金流行（symbol/name/net_mf/net_mv_ratio/
  lg_net/elg_net/md_net/sm_net/industry，按主力净流入降序；仅 A 股非停牌）——
  替代「全市场逐票批量」的正解：EC 只花一次求值的计算量，不再是 标的数 × 单票
  成本。日频 EOD 口径，非交易日数据不变；demo 客户端同步支持（演示宇宙罐头）
- **SDK 来源标记 `X-WM-Client`**：所有请求携带 `wmshare-py/<版本>`（MCP 层为
  `wmshare-mcp/<版本>`），开放平台网关落库 call_log `client` 字段——审计可区分
  SDK/MCP/裸 HTTP（配合网关侧记录；旧网关忽略此头，无兼容性影响）
- **EC 消耗可见性**：开放 API 按计算量（EC）计费，批量省请求次数**不省 EC**。
  `Client.last_ec_cost` 读取网关回传的每次消耗；单次超过
  `Client(ec_warn_threshold=100_000)`（可调/可关）SDK 主动告警；
  `BatchResult.ec_cost` 汇总各批消耗；`cli.moneyflow.last/bars` 传 ≥200 只的
  大列表时提示 EC 语义（2026-11 全市场资金流逐票批量事故的防线）
- **指数趋势分位服务端化 `cli.index.trend(key, window="5y")`（market.index v1.3.0 扩展）**：
  分位改由服务端按所选窗口（3y/5y/10y）计算——`pct.pe/pb/pe_med` 各含
  `{p, p3, p5, p10, n*, trunc}` 束，口径 `rank0/(n-1)` 并列取中点；`win_trunc=true`
  表示缓存序列盖不住所选窗口、相关分位为 `null`（不拿短窗口冒充长窗口）。
  `points`/`base` 序列明确为**降序（新→旧）**；股息率无历史序列、不出分位
- **键分组 `cli.index.universe_keys(group="broad")`**：`broad`（11 宽基，默认）/
  `industry`（申万一级 31，运行时读行业名录）/`dividend`（红利 14）/`all`；
  服务端预热 cron 与调用方共用同一份键清单（单一事实源）

### Fixed
- **trend 分位方向事故**：早期实现用 `reversed(pts)` 取当前值，实际取到**最旧点**，
  把 2020 年的分位当今天展示；`tests/test_index_trend.py` 四条断言锁死
  points 降序、基准点取最新、分位公式与 as_of 不早于最新点
- `cb.valuation` 文档注释竞品词中性化（check_leak 门禁）；`cb.rules.num` 改
  `TypeGuard[float]`（mypy 九处 `Any | None` 报错清零，调用点零改动）

### Changed
- `docs/notebooks/index_daily.ipynb` 榜单扩到 **56 键**（宽基 11 + 申万一级行业 31 +
  红利 14）：档位 = 该键自身历史分位三色灯（<30% 绿 / 30~70% 黄 / >70% 红），
  附独立复算校验 cell；`AGENTS.md` 新增最高优先级规则「先查已有指标，再写计算代码」
- `cb` 双低 notebook/example 的税后 YTM 升级为与日更线**同源**的双口径
  （`wmshare.cb.valuation.ytm_after_tax`：`basis` 分档 schedule/constant 标注，
  下限口径兜底）——notebook 不再另写近似公式，两处口径不再分叉；通道拨测
  对 K 线入库滞后改为「按 K 线自身最后日期计算并标注双日期」
- **文档大改版**：新增 `docs/INDICATORS.md`——全量 2,752 个指标码按数据类型分章导航
  （概览/股票行情/股票指标/行业/指数及ETF/宏观/期货/可转债/港美视图 + 命名语法 +
  死码警示 + 场景速查；`tools/gen_indicators.py` 生成，漂移与引用门禁接线）；
  README 重构「基本功能 / 特色功能 / 给 AI」三分章；计数口径全库收口
  （2,752 码 / 131 接口 / 134 可兜底 / 269 函数 / 14 示例，llms.txt 动态化 +
  防回归门禁）；GUIDE 新增「数据在哪找」速查与「预置码 vs eval 自算」EC 实测
- **moneyflow live 口径修正**：`moneyflow.query_last_live` 定性为「外部公开源当日读数
  （非盘中行情、非 Level2、仅 A 股）」——目录合同 / docstring / README 同步修正，
  无行为变化；README `cli.moneyflow` 行移除「盘中」表述
- **美股日 K 调度转正 + EOD 盖回翻闸（2026-11-09）**：上游 us_kline_daily daily DAG
  解除暂停并补齐暂停窗口缺口（force_days=10 幂等滚动重写），运维开关 `us_dayk_eod`
  翻 `true`（日K齐套门闩 + skip_read 盖回 tip + 抽检 store bar 与预期一致）；
  test_live 新鲜度门禁收紧（末根 ≥ 今天-5 自然日），README/GUIDE 注记更新为日更常态

## [1.12.0] - 2026-11-07

### Added
- **可转债全市场面板 `cli.cbond.board()`（market.cbond v1.2.0）**：一次调用返回全市场
  转债面板 = 快照行 + 每债最新条款事件 + 盘中债价 overlay（`bondPercent`）+ 强赎触发计数
  （`callHits`/`callWindow`，服务端 30 交易日窗统计）+ 下修地板价测算
  （`resetFloor`/`resetP1`/`resetP20`/`resetBps` 等）+ 正股市值/PE/PB/股息
  （`stockMv`/`stockPe`/`stockPb`/`stockDiv`）。`premiumRatio`/`couponIr` 与
  `latest_quotes` 同口径（SDK 换算为小数）。notebook 新增
  `docs/notebooks/cb_double_low.ipynb`（双低榜 + 强赎/下修观测 + 估值通道拨测，
  2026-11-07 真实数据，守护测试 tests/test_cb_notebook.py）
- **指数估值趋势 `cli.index.trend(key)` + `cli.index.universe_keys()`（market.index v1.3.0）**：
  周频整体法 PE/PB 序列（平台 cron 预热缓存）——`trend` 返回 `{ok, as_of, density, n,
  points:[{date,pe,pb}], pe_pct, pb_pct}`（分位为最新值在序列中的位置，样本 <60 点为 None，
  指数估值分位的推荐基座）；`universe_keys` 返回已注册成分宇宙的宽基键清单（榜单场景
  推荐取值域，区别于返回全部注册键的 `keys()`）。notebook 新增 `notebooks/index_daily.ipynb`
  （指数估值榜 + 通道拨测能力，自包含实现）
- **宏观数据域 `cli.macro`（market.macro，11 函数）**：宏观指标时序/单值/原生期点/采样频率
  （`macro.query/asof/spots/sampling_of`，指标码与 $ 前缀可省）、中债收益率按曲线名+期限
  （`bond_curve`，小数口径）、行业情报单值（乘联会厂商排行/手机品牌周份额/新势力周销量与
  月交付/家电月度产销）。宏观数值为上游原生口径：$CPI 等价格指数=点（上年同期=100）、
  $GDP/$M2=元——11 函数全部经 PROD 活体探针实证后定版
- **期货指标码层**：`$FUT_*` 主力连续 K 线 27 码补齐 `markets=["cn"]` 市场标注（此前共享
  路径无标注，hk/us 客户端调用必 500）；`cli.indicator.get/metrics` 新增 `fut_symbol` 参数
  （ARGS 透传合约键：国内 `cn.SR.ZCE`/`cn.RB.SHF`，外盘 `global.CL`；`symbol` 传任意 A 股
  代码绑定期间上下文）。函数级 sys/fut 域挂账 ROADMAP
- **美股日 K 恢复入库**：上游 us_kline_daily 管线（外部行情源主源+互证腿）已落库，
  README 市场覆盖矩阵与注记更新（调度常态化验收中，偶发 T-1/T-2）；`cli.kline.bars("AAPL")`
  不再返回停更快照；test_live 新增美股日K结构断言（新鲜度门禁待调度常态化后收紧）
- 文档参考层重构（对齐主流数据平台逐接口形态）：docs/API.md 按资产类别分章（A 股行情与
  选股/可转债/指数/期货/宏观/财务基本面/信息披露与公司行动/港股与美股/参考数据），每核心
  接口独立小节（说明/输入参数表/输出字段表/可执行示例），期货章为 `$FUT_*` 指标码专题表；
  test_docs 解析层同步重写（块解析 + 参数表逐签名对账）
- examples 新增 `13_futures_macro.py`（期货指标码姿势 + 宏观时序/中债收益率，--demo 可试跑）；
  演示客户端补 macro 域与期货指标罐头

### Changed
- 计数口径：18 个数据域 / 263 个底层函数 / 127 个核心接口（+macro 11 接口）；README 顶格
  291 行，能力一览补 `cli.macro` 行、我想做 X 补宏观/期货行
- GUIDE 新增 §6.1 宏观与期货（含美股日 K 注记更新）；SKILL.md 同步计数与意图表
- 指标码目录基线定为 **2639**：以 1.11.0 同步的 d8c900bb 为锚，剔除 20 个 ops 弃用
  drop-stub 与 93 个选股策略克隆幽灵（全目录实测实锤无数据/收割残留），保留上游扩展采集的 481 个真数据码（振幅/技术面/分析师
  覆盖/公司资料）；extractor 源排除表按此更新

- README 首屏演示从动画 GIF 换成**真实 JupyterLab 实拍截图** `docs/img/quickstart.png`：
  本地起真 Jupyter 打开 `docs/notebooks/quickstart.ipynb`（选股实战：批量拿全市场股息率
  12 次请求 → 逐票取 PE/十年分位 → 筛出「高股息 + 低估值」前 8），PROD 真跑后截图；
  notebook 随包入库（含真实输出、页脚标实测日期 2026-10-30），README「更多」挂链接，
  读者可下载复跑或上传云端 Notebook。旧 GIF（580KB）与 Pillow 生成器（gen_quickstart_gif /
  gen_quickstart_png）移除；新增 tests/test_quickstart_notebook.py 守 notebook 有效性与同源性

### Fixed
- `CatalogError.__str__` 不再继承 `KeyError` 的 repr 引号；程序化兼容保持不变。

## [1.11.0] - 2026-11-07

### Added
- 本地 MCP server 入口 `wmshare-mcp`（`[project.scripts]` + 随包 server.json，
  `examples/12_mcp_server.py` 覆盖安装、setup/doctor 自检与最小 client 配置），
  新增可选依赖 extra `mcp`
- 指标码目录同步上游 d8c900bb：上游扩展采集的 481 个真数据码入库
  （振幅/技术面/分析师覆盖/公司资料）

### Changed
- 演示客户端重写为快照架构：`_demo_data.json` 固定快照（内容哈希钉死）+ schema 校验

## [1.10.0] - 2026-10-30

### Added
- `wmshare.demo_client()`：随包离线演示客户端（罐头快照、零凭证、不联网），调用面与真实
  `Client` 一致（门面命名空间 + 批量入口 + 公告轮询器桩）；README 新增「不配凭证，先看输出」
  首跑块，干净环境实测装完到看到输出 0.5 秒内
- examples 新增 `10_notice_monitor.py`（公告轮询器：poll_now / ack / seek_oldest）与
  `11_statements_tour.py`（三大报表 + 合并 vs 母公司 + 审计意见）；凭证示例全部支持
  `--demo` 旗标零凭证试跑（演示分支打印「非真实行情」提示）
- README 首屏演示 GIF（`docs/img/quickstart.gif`，由 `tools/gen_quickstart_gif.py` 用
  Pillow 确定性生成，录的是演示客户端真实输出、数值不随行情漂移）
- docs/README.md 导航新增「五个高频任务」表：任务 → 可运行示例 → 文档章节三处索引打通
- 美股代码归一：`normalize_symbol` 按随包代码表把带交易所后缀/分隔符的美股代码消解为
  注册裸码（`AAPL.O` / `AAPL.N` → `AAPL`，`BRK.B` / `BRK-B` → `BRK_B`；代码表未命中不改写），
  eval 锚点、目录调用、`call_batch` / `batch_iter`、`kline.batch_live` 五条路径统一

### Changed
- README 首屏改为窄定位（给 Python 量化开发者的中文财经数据 SDK：预计算指标 + 批量绕限流），
  快速上手重排为「装 → 演示 → 凭证 → 真数据」四步；英文 TL;DR 压缩到 5 行
- tests/fake_client.py 收敛为 `wmshare._demo.demo_client()` 的薄封装（单一事实源）；演示
  罐头值与 README 已守护的 probe 样本对齐（TTM 股息率 0.0379→0.0396、PE 十年分位 0.2115→0.42）
- `call` / `call_batch` / 批量入口对「指标码当函数名」的误用给出可执行指引（一票多码用
  `indicator.metrics`，全市场指标逐票调用）；README / API.md / GUIDE 同步「指标码不是批量 `name`」

### Fixed
- 美股指标 `_LAST` 族 HTTP 500 / 十年分位静默返回 0：根因是带后缀的美股代码（如 `AAPL.O`）
  在网关查不到注册项、指标脚本的 symbol 未绑定——并非引擎缺数据（裸代码当日即正常：AAPL
  PE 39.49、十年分位 0.7858）。经上述代码归一后恢复可用；残余的 undefined variable "symbol"
  翻译成带「美股用裸代码」指引的 `DataError`。同日曾落地的 `_LAST` 全族拦截与目录市场作用域
  拦截均已撤回（`$BE_RATE` 等三市场可取数而目录标 cn 专属，作用域拦截会误伤）
- CI 自 1.9.2 起常红：README 示例块的 `to_df()` 在不装 pandas 的 CI 执行时抛错；测试桩改为
  pandas-free 批结果替身，新测试文件一律 `importorskip`
- docs/GUIDE §8 公告轮询示例写了不存在的 `poller.run()`，改为真实 API
  `poll_now()` / `start()` / `stop()`
- CONTRIBUTING.md 运行示例一节的旧示例文件名（5 处）与泄漏门禁常量名漂移

## [1.9.2] - 2026-10-30

### Added

- **文档四层体系**（Diátaxis：教程 / 怎么做 / 参考 / 解释）：`docs/README.md` 导航页、
  `docs/GUIDE.md` 使用指南（单票菜谱、全市场与行业、批量取数、多市场、pandas、
  公告订阅、故障排查、FAQ，菜谱输出全部活体验证）、`docs/AI.md`（用 AI 学会并用好 SDK：
  三条接入路径、提示词模板、AI 常见错误对照表、凭证安全红线）、`AGENTS.md`
  （AI 编码代理的仓库约定，对齐 agents.md 惯例）。
- `llms.txt` / `llms-full.txt`（`tools/gen_llms.py` 生成，落地 ROADMAP M4.1）：AI 友好文档索引
  与全文拼接，含按域单行锚点与「何时不要用」负向节；`--check` 进 CI 与 pytest 漂移门禁。
- **examples 重构为 9 个编号课程**（`NN_主题.py`，编号即学习路径）：新增
  `06_indicator_tour`（指标码体系漫游）与 `09_ai_skill_setup`（skill 装入 agent，离线），
  3 个示例零凭证可跑；新增 `examples/README.md` 索引页（三阶课程表 + 新增示例约定）。
- **API.md 新增「Client 方法（批量取数）」章**：`call/call_batch/batch_iter/batch_all`
  签名表（随源码实时生成）+ 请求次数守恒三原则 + 可离线执行示例。
- 测试基建：共享 `tests/fake_client.py`（按接口派发罐头数据），9/9 示例 CI 端到端覆盖；
  示例 AST 校验全量推广（`cli.*`/`$码`/`cat.*` 全查，曾据此发现 `screener.screen_up_today`
  误用）；文档引用校验扩到 GUIDE/AI；`test_examples_index_covers_dir` 防孤儿示例。

### Changed

- **目录对齐上游并带作用域元数据**（「SDK 以 script 为基准」）：指标目录 2197→**2158**
  （剔除 39 个收割幽灵：ops drop-stub 的 `$*_LIVE`、注释残留、tests/strategy 注册），
  精选常用指标 75→**74**（`$PB_LAST` 为幽灵）；指标条目新增 `markets`（us 23/hk 16）与
  `gated`（dev 19）作用域标注；extractor 忠实度规则（注释幽灵文件级复核、loader 文件
  形态、`__midx` 门检测）。
- README：标题下加徽章行（PyPI/Python/CI/License）、「更多」区改文档中心 + 示例课程入口；
  示例 docstring 统一四行元信息（前提/运行/学到/文档）；公开文档去导流话术（Gitee 风控
  判定「纯广告导流」致 README 不渲染）+ 新手可懂性整改（三行上手不依赖可选依赖等）。
- 门禁面扩大：CTA 禁词扫描覆盖全部新增公开文档（含 AGENTS.md 与 llms.txt）；
  CI wheel 冒烟随示例改名更新。

### Fixed

- **`cli.screener.index_breadth_bins/bin_industries` 的 label/bin 带服务端排序前缀**
  （`i_涨停`/`h_+5%~10%` 直接透给用户）→ 友好层剥除。
- **`equity.query_hgt` 目录 range `[0,1]` 误拦正常数据**：实测沪港通持股变动比例
  -0.85~+10.34、占比到 2.07 → 修正 `[-1,50]/[0,20]/[0,20]`，调用不再 `DataError`。
- **examples/08 与 GUIDE pandas 菜谱**：`bars` 按日期降序返回、`_df=True` 保持该顺序，
  直接 `iloc[-1]` 算 MA20 落在最老一段——先 `sort_values("date")` 再算。

## [1.9.1] - 2026-10-29

### Fixed

- **跨市场混批会静默返回错误数据**（实测发现）：cn 客户端批量混入 `00700` 时网关不拒
  （`checkMarketMatch` 只校验请求锚点，不校验 `xs_lines` 内代码），但该港股标的的 close/percent
  与 hk 客户端结果不符（387.6 vs 377.6、+0.62% vs -2.58%，涨跌方向都相反）——本市场引擎
  上下文解析他市场符号会走错数据管线。现在 `batch_all`/`batch_iter`/`call_batch`/
  `kline.batch_live` 发请求前用随包代码表校验，混入他市场代码即 `UsageError`，消息指出
  归属市场并给出「A 股 12 批 + 港股 6 批 + 美股 11 批 = 29 次请求」的分市场改法；
  代码表外的代码（新股/ETF）放行不误伤。常规同市场批量只加载本市场代码表（毫秒级、带缓存）。
- 文档：README 批量章节补「市场边界」段、SKILL 坑位加一条、三个批量入口 docstring 标注。

## [1.9.0] - 2026-10-29

### Added

- **证券基础库 `cli.stocks`**（新数据域 market.stocks，底层 sys/stocks，17 域/252 函数）：
  `list()` 全市场证券列表一次出全表（symbol/name/exchange/三级行业/is_st/上市日期；
  A≈5.7k / 港≈2.8k / 美≈5.6k 行，cn/hk 上游每日刷新）、`industries(level)` 行业目录
  （申万 sw2021 三级 31 个一级 / 恒生 hsi）、`industry_members(industry)` 行业成分股
  （支持行业键 `industry.S48`、代码 `S48`、**中文名**（含模糊匹配，多候选报错列候选））。
  美股：列表与个股行业码可用；行业目录树上游未灌数（如实注记于 README 矩阵与 docstring）。
- **批量取数通用升级（单次 ≤500）**：任意单标的接口**传 list 即批量**（`Client.call`
  检测标的参数为 list/tuple 自动转 `call_batch`，如 `cli.kline.last(["600519", "000001"])`，
  返回 `BatchResult`；`kline.bars/moneyflow.last/dividend.last` 等后处理方法逐标的映射）；
  `BatchResult.to_df()` 出带 symbol 列的长表；`kline.batch_live` 补上限校验（此前缺口）。
  超限 `LimitError` 文案附分批写法引导。
- **分批执行器（批量绕开 429 的正式入口）**：`batch_all(name, codes)` 自动切片并聚合
  （A 股 5,691 家 → **12 次请求**，逐票则 5,691 次；服务端按请求次数限流，免费档
  500 次/小时、5,000 次/日）；`batch_iter(...)` 逐批产出，供边取边落盘/进度/中断。
  `on_error` 为**批级**语义（`"skip"` 跳过失败批，失败批记 `batch#3[1000:1500]`）。
  **429 在任何模式下都停止并给续跑位置**（消息含已完成标的数与 `codes[done:]` 切片）。
  `BatchResult` 新增 `requests` 字段（实际请求数，可直接对比标的数）。
- 新示例 `examples/stocks_industry_batch.py`（全市场代码池→分批→请求数对比→行业聚合）。

### Changed

- **批量入口参数命名与语义校准**（1.9.0 内，随首发定型）：
  - `batch_all`/`batch_iter` 的 `on_error` → **`on_batch_error`**：与
    `call_batch(on_error=)` 的**票级**语义彻底区分（同名不同义是认知陷阱；
    `call_batch` 为已发布 API，名称与语义保持不变）；
  - 批量入口**不再提供 `_df`**：它会让每标的值变成 DataFrame，聚合后 `to_df()`
    产出 `{"symbol", "value": <DataFrame>}` 的失真长表；长表统一用 `to_df()`；
  - `batch_iter` 改为「外壳 + 内部生成器」：**参数校验在调用时立即抛出**，
    不再延迟到首次迭代（生成器惰性校验会让错误配置静默通过）；
  - README 补三接口参数对照表（用途/请求数/关键参数与默认值），行数上限 275→287。
- **批量进入新手必经动线**（此前接口与专章都在，但「三行上手」与 SKILL 决策树前几条
  全是单票示例，用户学完首页就会写 `for code in codes: ...` 逐票取数、正好撞 429）：
  README 三行上手改批量示例（上限 287→289）、SKILL 决策树把「全市场/上百只取数」
  提到第 3 条并明写反例、`examples/quickstart.py` 末尾加全市场批量段。

### Fixed

- **版本双源漂移**：`src/wmshare/__init__.py` 的 `__version__` 停留在 1.8.1，而
  `pyproject.toml` 已 bump 到 1.9.0——wheel 元数据正确但 `import wmshare` 报旧版本
  （发布前隔离安装时才发现）。已修正并新增 `test_version_single_source_of_truth`
  直接比对 pyproject，防再犯。
- **按市场默认求值锚点**：无标的参数的函数（如目录类）此前固定 A 股锚点 `600519`，
  hk/us 客户端必报 `MARKET_MISMATCH`；现按市场取 `600519/00700/AAPL`。
- `call_batch` 超限报错补分批引导（「请分批，如 `codes[i:i+500]`；或直接用 `batch_all()`」），
  与 `kline.batch_live` 文案对齐——此前 SKILL 已写分批提示而实现没有。
- README 新增「批量取数」专章（限流机制、三种用法、分批策略、批级容错反模式），
  行数上限 250→275（已先压缩镜像/生态/示例段落并删除旧批量 bullet）。
  **明确警示**：`call_batch(on_error="skip")` 是逐票请求，12 批会放大成 5,691 次、
  正好制造 429；容错请用 `batch_all(on_error="skip")`（批级）。
- README/SKILL/API.md/openapi 同步 17 域、252 函数、116 核心接口计数；目录同步上游
  （新增 stocks 域，`tools/extract_from_scripts.py` 白名单扩容）。

## [1.8.1] - 2026-10-28

### Fixed

- 凭证文案消歧：开放平台「两个值都要复制（缺一不可）」——AppId（Client ID）与
  API Key（Client Secret），「任选其一」仅修饰配置方式；README/SKILL/401 错误消息
  三处同步（README 改用页面真实标签，env 示例 `<AppId>`/`<API Key>` 占位映射）。
- tests/test_symbols 修复陈旧关键词：hk 检索用例改按公司名检索（命中 00700），
  原关键词为 vendor-comparison 时代遗留、离线目录无法命中（1.8.0 起红）。
- 目录同步上游 rev（8c83cf49 → 56547eeb，合同零变化）。

## [1.8.0] - 2026-10-28

### Changed

- **开源协议改为 BSD-3-Clause**（对齐主流数据接口库形态）：代码可自由使用、修改、
  再分发（含商业用途），保留版权声明即可。历史脉络：1.4.2/1.4.3 曾为 MIT，1.4.4 起为
  PolyForm Noncommercial；本次放开代码许可后，云端数据服务的账号/额度约束收口到
  开放平台服务条款（取数仍需凭证，免费额度注册即得）。README「使用限制（必读）」节
  改写为「许可与数据服务」；SKILL/错误指引/OpenAPI/示例/CONTRIBUTING 同步去「非商业」
  限定。GitHub License tab 由此正确识别 BSD 3-Clause。
- **README 定位改覆盖式**：「A股为主」→「覆盖 A 股、港股、美股」；市场覆盖矩阵按
  live 探针逐族实测重写（探针脚本 `.internal/probe_hk_us.py` 可复跑）。

### Fixed

- **市场覆盖矩阵纠错**（此前 hk/us 标注与真实数据面不符，三层证据：airflow 摄取清单、
  上游域库、生产工具实证 + 本次逐族探针）：指标库 hk/us 全量可用（hk 969 码 / us 898 码）；
  分红 hk/us ✅；公告 hk ✅；财报清单 hk ✅；股东治理拆行——高管名册/高管增减持/
  股本变更 hk ✅（us 仅股本变更 ✅），十大股东/质押/解禁/机构持仓等确为 cn-only；
  全市场选股 hk 标注「部分」（单票筛选可用，高息池索引暂缺）。

### Added

- ROADMAP 记录 HK 接口缺口：equity 十大流通股东/回购上游已有 hk 数据管线
  （hk.freeholder / hk.gphghgmx），store 硬编码 cn 前缀待上游路由化，SDK 侧零改动即可点亮。

## [1.7.3] - 2026-10-28

### Changed

- **README 店面对齐主流形态（授权信息收进正典位置）**：删除顶部 5 枚 shields.io 徽章
  （国内镜像站加载失败成破图外链）与「⚠️ 许可声明」前置块；英文 TL;DR 去掉重复的
  授权尾句。授权只在两处：LICENSE 文件（GitHub/Gitee License tab 显示全文）与文末
  「使用限制（必读）」节；正文开头留一行指针。纯文档发布，随包代码与 1.7.2 一致。
- 随包目录同步上游 rev（f095ac92：上游估值行业名归一调整，SDK 合同零变化）。


## [1.7.2] - 2026-10-28

### Added

- **国内镜像安装指引**：README/SKILL 安装节补国内镜像用法——清华等主流镜像源随 PyPI 自动同步
  （1.7.1 已实测清华源可装），阿里云偶有滞后；镜像装不到最新版时回官方源。
  纯文档发布，随包代码与 1.7.1 一致，发布目的是刷新 PyPI 项目页。
- 随包目录同步上游 rev（b9b1291e：上游公告窗口/港股公告提醒调整，SDK 合同零变化）。


## [1.7.1] - 2026-10-28

### Fixed

- **店面与文档对齐 1.7.0 行为**：pyproject 描述、README 英文 TL;DR、OpenAPI/Swagger
  intro 仍写「开箱即用，内置体验 AppID」（1.7.0 已下线），全部改为「凭证必填、注册即得、
  错误消息即指引」口径；LICENSE 清除 `<<beginOptional>>` 模板占位符与 81 行起的整段
  重复正文。
- **SKILL.md 撤下过期拦截断言**：`kline.live`/`min1` 自 1.5.0 根因修复并部署，意图决策树
  不再提示「被服务端策略拦截」；凭证文件说明补 KEY 名示例。
- docs/API.md 补两条已知边界（域 notes 数据驱动）：fund.statements 港美三大报表合同已
  预留、数据未上线（调用返回空）；bonus.query_count_window 上游 count 聚合缺陷恒 0
  （SDK window_stats 已绕开，直调该函数得 0）。

### Added

- **更名迁移指引**（补记：PyPI 发行名/导入名自 1.6.0 起由 wm-finpipe/finpipe 更名为
  **wmshare**）：旧配置 `FINPIPE_*` 环境变量与 `~/.finpipe/credentials.env` 不再被读取，
  缺凭证报错时检测到旧配置残留会附迁移提示。
- README 动线补全：配置凭证节补凭证文件 KEY 名与构造参数两种示例、安装节补验证命令、
  「更多」补 examples/ 入口。
- `Client.__dir__`：`dir(cli)` 可见全部友好门面与底层命名空间（IDE 补全可达）。
- `catalog.load()` 同路径进程内单例缓存（重复 `Client()` 不再重复解析目录）。
- 公告订阅端点 404 时给「未开放，请勿反复重试」专门提示；5xx 与网络失败错误消息补
  自救动作；`SECURITY.md` supported versions 更新至 1.7.x；bug 报告模板对齐凭证必填
  前提；test_docs 新增「体验 AppID/零配置」禁语门禁防回潮。

### Changed

- README 市场覆盖矩阵撤下「公告变更订阅」行：网关未对外开放前不作对外承诺（代码保留，
  开放后回归）。
- README 精炼上限 240 → 250 行：新增内容均为上手动线必需（凭证两种示例、验证命令、
  examples 入口）。

## [1.7.0] - 2026-10-27

### Removed

- **下线内置体验 AppID（行为变更）**：`wmshare.Client()` 不再零配置——缺凭证在构造期
  抛 `AuthError(code="config")` 并附申请指引；随包混淆 blob（`_experience.py`）删除。
  凭证三选一：构造参数 / `WMSHARE_CLIENT_ID`+`WMSHARE_CLIENT_SECRET` 环境变量 /
  `~/.wmshare/credentials.env`（非商业免费、注册即得）。README/SKILL/API.md/CONTRIBUTING/
  examples 同步改为「配置凭证」前置；服务端体验应用同步停用（已装旧包的内置凭证将
  401，错误消息即指引）。

### Fixed

- **v1.5.0 五新域上线（上游 two commits 部署 pipeline-5206/5208）+ SDK 配套**：此前
  equity/margin/estimates/index/intl 在生产全部不可用——上游 `sys/index` 库全局名
  `index` 与 XS 内建常量 MAP（`index.hs300` 等指数键）撞名，域库绑定被沙箱按策略
  拒绝（selector policy violation），build-init-baseline 编 init 链先炸 → CI 流水线
  连续两次 9 秒失败、从未部署；`cli.index` 更是静默返回 None。修复：上游库全局名
  改 `indices`（目录与指数键字面量不动），SDK 合同函数前缀同步 `index.*` →
  `indices.*`（`market.index` 1.1.0；**`cli.index` 门面不变**，仅 `call("index.*")`
  底层名变更）。
- **港美 K 线量额守护误拦**：`lot`（手→股 ×100）是 cn 专属换算（港美上游即披露股），
  此前对港美也 ×100 致 `volume_amount` 不变量必炸、用户被迫 `validate=False`。
  `apply_units` 增加 `market` 上下文，`lot` 仅在 `market="cn"` 生效（`market.kline`
  1.4.0，实测 00700/AAPL 默认校验直出）。
- **`margin.latest` 500**（上游 3e83de31→4d9b5ab2 部署）：单行 MAP 直传
  `fmt_maps(rows ARR)` 报 "rows expects arr"——上游规范化器放宽 any、MAP 输入按
  单行返回。
- **intl 市场语义如实标注**（`market.intl` 1.1.0）：网关按标的注册市场校验，
  `cli.intl` 须用对应市场客户端（cn 客户端调港美股代码 400 market mismatch），
  此前"自动识别、不受 market 参数影响"的表述与部署现实不符；门面 docstring、
  域合同、README 同步纠正。`test_live` 五新域冒烟去掉部署前 xfail 转真，intl 用例
  改用对应市场客户端。
- **全量单位审计：8 个字段的 percent 换算声明实锤错误并移除（行为变更：值恢复真实
  量级，变大 100 倍）**。`tools/audit_units.py matrix` 以 `_units="native"` 逐接口实测
  发现：corp.equity 的 hold_num_ratio/pledge_ratio/avg_pledge_ratio/institution_summary
  total_shares_ratio/change_ratio/hgt free_shares_ratio/total_shares_ratio、indices.weights
  weight、intl.query_shareholders total_shares_ratio 上游 fmt 早已预换算为小数，
  SDK 的 percent 声明把值再除 100（如茅台第一大股东持股比例 0.545 曾输出 0.00545）。
  v1.5.0 域库彼时从未成功部署，声明未经真实数据检验。同接口内混排口径逐字段标注
  （institution_summary 仅 all_shares_ratio、hgt 仅 add_shares_pct 仍为百分数）。
- **cbond.latest_quotes 新增 premiumRatio/couponIr 百分数换算（行为变更：值变为小数，
  缩小 100 倍）**：转股溢价率实测 2-238（百分数数值）、票面利率 0.1-0.2，此前未声明。
- **v1.5.0 挂账的歧义字段全部核验结案**：executives.salary=元/年（实测 2e5-1.1e6）、
  reorg.deal_amount=元、violation.punish_amt=元、capital_change.total_shares=股、
  holdernum 比例族=小数、pledge_market.pledge_ratio_total=小数（上游 inventory cn
  「百分数」为遗留标注）——全部补 ranges 量级守护；guarantee_amt、exec_change 族
  待样本（茅台无质押/担保/增减持数据），保持披露原值并在 notes 列明。
- **声明元规则生效**（tests/test_unit_meta.py）：units 字段必须存在于 returns_shape；
  percent 声明必须配 ranges 或 notes 标注「量级豁免」（diffp 先例）。审计矩阵
  （.internal/UNIT_AUDIT.md）落地后规则 2 自动启用，现全部声明合规。
- intl 港股盈利预测披露原文口径注记：纯利=百万（港元）、每股盈利/每股股息=仙
  （cents），不做换算。

### Added

- **单位审计器 `tools/audit_units.py matrix`**：113 核心接口逐字段单位矩阵（native
  实测 × 声明因子 × inventory cn 线索 × 求和锚判定），缓存断点续跑、报告写
  `.internal/UNIT_AUDIT.md`；原 cross 跨接口一致性模式保留为默认。
- fund.segments 1.0.1：returns_shape 三处重复 `kind: array` 块去重（YAML 静默取后者
  的目录卫生缺陷）。

### Changed

- **README 去授权化 + 新增「市场覆盖」矩阵**：删除「免费额度与凭证」章节（申请步骤与
  配置方法本就内置于 401/403/429 错误消息与 AI skill，README 不再重复；快速上手仅留
  一行指针）；腾出的篇幅换成 cn/hk/us 市场覆盖矩阵——逐能力标注三市场支持度，并如实
  注记实测边界（美股日 K 停更于 2026-03-13：上游美股价量为 live-only 策略，最新价量走
  `cli.kline.live / snapshot`；港美股三大报表合同已预留、数据未上线）。联动：
  `gen_api_docs.py` 能力总览措辞改为"错误消息即完整指引"并重生成 `docs/API.md`；
  `CONTRIBUTING.md` 同步去 README 章节引用。

## [1.6.0] - 2026-10-27

### Added

- **公告变更订阅轮询器 `NoticePoller`（`cli.notice_poller(...)`）**：消息队列消费组
  语义——事件流、消费进度与 ack 全在服务端（与取数同一 base_url、同一 OAuth
  Bearer），SDK 侧本地 daemon 定时线程轮询轻量探针（poll，O(1)），有新公告才逐市场
  read 分批拉平、回调 `on_events`、ack 确认；无新事件时零 read。消费进度按
  `(group, consumer)` 标识存服务端，ack 前崩溃自动重投（at-least-once）；回调抛异常
  不杀线程、该批不 ack 下轮重投。服务端事件保留 7 天，进度落后超期时 read 抛新增的
  `StreamResetError`，用 `seek_oldest(market)` 重置游标到保留期内最早可用 seq。
  支持 `cn`/`hk` 双市场、limit 客户端先行钳制（≤200）、指数退避 + 抖动、`status()`
  快照（polls/reads/交付数/积压/最近错误，可接心跳监控）、上下文管理器与完全自驱
  （`poll_now()` / `read(market)` + `ack(...)`）。新增 15 个合同级离线用例
  （FakeStreamServer 假会话，不联网、不真实等待）。
- Client 内部提取 `_post_authed`（Bearer POST + 401 清令牌重试一次），eval 与公告
  订阅共用；行为无变化。

## [1.5.0] - 2026-10-27

### Added

- **数据面扩容（v1.5.0 主体）**：新增 7 个数据域——`corp.equity` 股东与股本（十大股东/
  股东户数/股权质押五族/限售解禁/机构持股/沪港通/国家队/高管名册与增减持/股本结构/
  回购方案与执行/并购重组/关联交易/一致行动人/对外担保/诉讼处罚）、`market.margin`
  个股融资融券、`fund.estimates` 盈利预测与研报（机构预测/明细/评级统计/个股研报）、
  `market.cbond` 可转债（合约快照/条款事件/正股关联/强赎计数/日K/盘中）、`disc.workout`
  契约套利、`market.index` 指数（成分/权重/宽基估值时序）、`market.intl` 港美股披露
  （CCASS/主要股东/机构评级/盈利预测/沽空/美股发行）。目录 **10→16 域、164→249 底层
  函数、64→113 核心接口**；新增 7 个友好门面 `cli.equity/margin/estimates/cbond/
  workout/index/intl`；60 个新合同级离线用例（tests/test_domains_v15.py）。
  比例字段统一由百分数换算为小数；歧义口径字段（高管薪酬/股本结构等）保持披露原值
  并在目录 notes 标注，待平台部署后 live 核验补齐 ranges/checks。
  上游配套（scripts 仓 d2ecfe9b，需平台部署后 live 才通）：新增 sys/equity、sys/margin、
  sys/estimates、sys/index、sys/intl 五域库，sys/cbond 补 13 个 xs:catalog 注解与
  manifest，boot chain 挂载（CROSS_REPO_CHANGES #9）。
- README「特性」按「数据要全 / 数据要准 / 特色数据」重构，能力一览表收录 7 个新门面；
  瘦身上限 215→240 行（实际 224）；SKILL.md 计数同步。

### Changed

- **公开文档补"可验证事实链"**：README 能力一览写明日 K 数据深度（个股/ETF 自上市首日
  起全覆盖，最早 1991 年，实测锚定：000002/000001 自 1991 年上市首日、600519 自
  2001-08-27、601398 自 2006-10-27）；「单位与数据守护」补数据深度与超深回溯逃生口；
  免费额度小节明确自有 AppID 在非商业用途下即为正式服务。
- 目录精选表补收 README 头牌示例码 `$CUR_IND_ROE_PCT_LAST`（行业内 ROE 分位，
  精选 74 → 75），并修正该示例的预期输出（0.08 → 1.0：2026-10-24 实测茅台行业
  ROE 分位=1.0，即行业最高——原示例注释值无实测依据且"越小越靠前"的语义说明有误）。
- 随包目录同步上游 rev（066985a8，函数/指标合同零变化）；symbols manifest hk 计数
  对齐实际名单（2655 → 2673）。
- **根因修复：live/min1/is_etf/bars_live 的 403 POLICY_DENIED（上游 script a9bce960）**。
  根因不是权限配置也不是体验池限制：`kline.is_etf` 的 per-eval 缓存写
  （`kline._etf_cache[bare] = v`）是对预存命名空间全局的写 = `state.write.runtime`，
  OpenAPI 沙箱按设计拒绝任何外部调用方写共享状态；`etf_block→is_etf` 是四类查询的
  公共首行入口，一处缓存写导致全部 403（「不允许调用 assign」是引擎对 LHS 不可静态
  判定赋值的保守 fallback 标签）；batch_live 不经该入口所以幸存。上游修复确立
  「查询路径不落写」纪律：is_etf 去缓存改纯读（每调用 1 次 ref_info 点查，与旧
  skhub.is_etf 同代价），`query_bars_live` 的死代码运行时写改正。已上线并实测：
  live/min1 返回盘中数据、is_etf 判定正常。SDK 侧保留 403 策略拒绝的专门错误引导
  （权限范围 ≠ 额度，勿重试、指引开放平台）。
- **根因修复：`screen_quality` 部分传参错绑（SDK `_build_call_line` 参数洞不补位）**。
  调用字面量按位置绑定，未传的中段参数曾被整体跳过——`screen_quality(sym, payout_max=1.5)`
  会生成 `(sym, 1.5)`，1.5 错进 `payout_min` 槽。现中段未传参数补 `nil` 保位（尾部未传
  仍省略）。此前"茅台误判 False"的两处误诊一并更正：①那不是数据回填问题——筛选读
  TTM 派息指标（$BONUS_TTM_RATE_LAST），不读 history 记录的 payout_ratio 列（该列
  回填滞后仅影响明细展示）；②默认 False 是「精品」窗口设计使然——默认要求股息率>3%
  且派息率 ∈[30%,70%]，茅台 ~80% 派息率出界属设计。README/SKILL 示例与坑位清单按
  真实语义改写。

## [1.4.2] - 2026-10-26

### Changed

- **README 二次瘦身（274 → 206 行）**：整删「数据正确性保障」（事故历史/三层机制/审计流程
  等工程内部叙事）与「口径速查」细则表；不可再省的事实浓缩为 5 行「单位与数据守护」
  小节（基础单位 / DataError 守护 / `_raw`·`_units`·`validate=False` 逃生口）；「更多」删
  维护者审计条目；English quick start 与中文快速上手重复，一并移除（英文读者由顶部
  TL;DR 覆盖）。纯文档 + 目录同步发布，随包代码与 1.4.1 一致；发布目的之一是刷新
  PyPI 项目页描述。
- 随包目录同步上游 rev（0343968a：rptdom 内部实现修复，合同零变化）。

## [1.4.3] - 2026-10-26

### Changed

- **开源协议由 PolyForm Noncommercial 1.0.0 改为 MIT**：代码可自由使用、修改、再分发
  （含商业用途），保留版权声明即可。LICENSE/pyproject/README/CONTRIBUTING/SKILL/
  生成文档同步改写；云端数据服务仍需开放平台账号与配额（服务条款与代码许可相互独立）。
- README 免费口径改写：注册开放平台账号即得免费额度（不再限定非商业用途）。

## [1.4.4] - 2026-10-26

### Changed

- **开源协议回退为 PolyForm Noncommercial 1.0.0**（撤销 1.4.3 的 MIT 改版，恢复限制
  商业使用）：LICENSE/pyproject/README/CONTRIBUTING/SKILL/生成文档全部回退。
  说明：PyPI 上已发布的 1.4.2/1.4.3 版本按其上传时的 MIT 许可提供，无法撤回；
  自本版本起恢复非商业限定。云端数据服务仍需开放平台账号与配额。
- README 免费口径恢复非商业限定表述。

## [1.4.1] - 2026-10-24

### Changed

- **README 店面化重构（495 → 274 行）**：按用户定版要求移除「与主流数据服务对比」整节
  （含价格表与官方页注释）、「wmshare 的劣势」节、九个数据域详解长文、「指标体系」
  长文与「数据范围」节——README 零竞品名、差异化卖点改自证式表述，并新增
  `test_readme_no_competitor_names`（防回潮）与 `test_readme_is_lean`（行数 ≤280，
  防再膨胀）守护；新增「目录」导航与「能力一览」一屏表（12 个门面 × 能力 × 单位口径）；
  「我想做 X」速查表、可执行示例、数据正确性保障、口径速查、免费额度与凭证保留。
  本次为纯文档发布，随包代码与 1.4.0 一致；发布目的之一是刷新 PyPI 项目页描述。
- README 生态工具「波段」介绍与工具实现对齐：区间设置只保留**推荐区间**（四条约束
  自动搜点）与**自定义区间**两种来源，移除通道轨表述（工具侧 1c1cfa3 已删该选项）。

## [1.4.0] - 2026-10-24

### Added

- README「更多」新增生态工具入口：[big-winner](https://github.com/open-winmale/big-winner)
  （基于本 SDK 构建）——收息佬（分红日历/持仓透视/派息稳定性）与波段（估值通道/
  推荐区间/安全边界/波段 vs 长持回放）。
- **AI 原生 skill（随 wheel 分发）**：Agent Skills 格式的 `SKILL.md`
  （`wmshare.skill_dir()` 定位，`skills/wmshare/*.md` 进 package-data），教 AI
  agent 正确使用 SDK——环境前置与 AppID 申请引导、单位铁律（小数/元/股 +
  混口径标注）、目录先行防臆造指标码、意图→接口决策树、工作流与返回解读、
  坑位清单、错误处理速查。装入方式：复制到 agent 的 skill 发现目录
  （`~/.agents/skills/` 等）。新增 `tests/test_skill.py`：frontmatter 合法性、
  **文中全部调用防臆造守护**（命名空间/方法/目录函数逐一校验 + 签名可绑定）、
  wheel 分发声明、关键措辞守护。
- **数据接口「选股与全景」**：新 `cli.screener` 门面，核心接口 52 → 64。
  单票一行布尔筛选：`screen_limit_up` / `screen_limit_down`（涨停/跌停，阈值
  ±0.10 小数）、`screen_above_ma20` / `screen_ma60_up` / `screen_breakout_ma20`
  （均线/趋势）、`screen_momentum_20d(min_chg=0.10)` / `screen_pullback_20d(min_chg=-0.10)`
  （动量/回撤，小数阈值；pullback 语义为涨幅**上限**）、
  `screen_volume_spike(min_ratio=1.5)`（5 日量比）；全市场宽度（服务端预计算
  索引直出，`idx` 不传 = 服务端解析 A 股最新查询索引）：`index_breadth_summary`
  （涨跌家数/占比/中位数）、`index_breadth_bins`（9 档分桶）、
  `index_breadth_bin_industries`（分桶×行业）、`index_top_movers`（涨跌榜，
  行含 symbol/name/percent）。kline 目录其余筛选函数经 `cli.screener.*` 属性直达。
- README 新增「选股与全景」独立小节（筛选阈值表 + 宽度返回口径表 + 可执行示例）；
  API.md 核心接口表改为按命名空间分节（生成器自动成节）；口径速查新增「筛选阈值」
  行（宽度返回的 `*_pct`/`pct_of_total` 为百分数数值、涨跌幅/中位数为小数）。
- 示例 `examples/screener.py`；`.internal/ROADMAP-1.3.md` 规划二期任意条件选股
  （上游 `kline.index_query`）与三期策略库候选。

### Fixed

- **选股门面对齐审查修复**：三个列表返回的宽度接口（`index_breadth_bins` /
  `index_breadth_bin_industries` / `index_top_movers`）补 `_df=True` 支持
  （对齐模块「返回列表的方法支持 _df」承诺）；`index_top_movers` 的 `limit` 在
  eval 拼脚本路径补 `Client(max_limit=...)` / 10000 行硬上限钳制（此前只走目录
  路径才受钳制）；门面模块 docstring 底层函数计数 155 → 164 并加测试守护；
  README 与示例中 `index_where_*` 的表述修正为「服务端筛选条件表达式」
  （原文案误写为可直接使用的股票池）。
- 宽度接口索引键：臆造字面量 `"index.cn.all"` 实测 500（索引键为动态 cache_key，
  无稳定字面量）；`cli.screener` 宽度四件套改为 `idx=None` 时由服务端
  `LatestIndexKey()` 解析。README/速查表中旧键示例已移除。
- 上游配套（7615b7ea，待部署）：`kline.index_top_movers` 原返回行仅含行号与
  `$` 原始字段、无标的代码——改 `INDEX_ROW_VALUES_MANY_SPEC` 投影并拍平为
  `{symbol, name, percent}`；SDK live 测试对部署前的旧形态 xfail。

### Docs

- README「与主流数据服务对比」章节：优势与劣势两面陈述（免费额度/单位口径/数据守护/
  衍生指标 vs 覆盖面/数据积累/生态/商用许可）。第三方名门禁为此开唯一例外：
  仅 README 允许点名竞品（check_leak.py 的文件级例外，1.8.1 起取消），
  其余第三方名在全部文件仍然禁止；对比章节由测试守护必须保持两面陈述。
  「衍生计算」行升级为 `cli.screener` 选股门面口径；实时行情行明确免费提供
  盘中快照与当日 1 分钟分时（主流数据服务的实时分钟为 1000 元/月的独立权限）。

## [1.3.1] - 2026-10-24

### Changed

- `cli.valuation.hist_stats` 窗口白名单新增 **"6m"**（引擎支持 `<数字><单位>` 通用
  窗口，实测 6m 可用）：`("6m", "1y", "2y", "3y")`，上限仍为 3 年。

## [1.3.0] - 2026-10-24

### Added

- **数据接口「估值历史统计」**：`cli.valuation.hist_stats(symbol, metric="pe", window="3y")`
  ——与平台 web「估值通道」取数同源（宿主 HIST_STATS），返回窗口内每日 PE/PB/PS/市赚率
  序列与统计量（avg/current/median/min/max/pct）。窗口白名单 1y/2y/3y（上限 3 年）；
  亏损期 PE 无数据、净资产为负期间不参与。下游工具（big-winner 必赢佬）以此为数据源。
- 核心接口 51 → 52。

## [1.2.0] - 2026-10-23

### Added

- **新数据域「经营分部」（`fund.segments`）**：主营构成多维分解——分产品
  （`cli.segments.products`）、分业务（`business`）、分区域境内外（`region`）、
  主营标签占比（`income`），外加四维合并快照（`snapshot`）、披露覆盖度
  （`coverage`）与可用报告期（`periods`）。数据来自定期报告分部披露的平台清洗
  归一（clean 口径，默认），可选披露明细（`source="raw"`）。
- 行结构统一 `{name, tr, tr_text, cost, margin, ratio}`：收入/成本=元、毛利率/占比/
  同比=小数（margin 服务端算好直出）；量级守护随 1.1.0 单位契约自动生效
  （tr/cost/margin/ratio/pct/yoy 均已声明范围，误口径会抛 `DataError`）。
- 核心接口 44 → 51（新增 segments 7 个）；底层函数 155 → 164（10 个数据域）；
  README「产品线/业务分部口径一期未纳入」欠账兑现。
- 提取器命名空间白名单 += segments（上游 `sys/segments`，18 个公开函数策展收录
  9 个；inventory 全量收录 15 个带合同注记的条目）。

## [1.1.0] - 2026-10-23

### Changed（breaking：返回数值口径）

- **全库统一基础单位，SDK 单点自动换算**：比率/涨跌幅/占比=小数、金额/价格/市值=元
  （报表原币）、股数/成交量=股。上游脚本永远输出原生口径，`call()` 在返回前按随包
  目录的 YAML 声明做唯一一次换算。本次实际换算的字段：
  - `kline.query_bars / query_last / query_bars_adj / query_last_live` 的 `volume`：
    手 → 股（×100，A 股/港美/ETF 同口径）；
  - `rptdom.statement_compare` 的 `diffp`（差额占比）：百分数 → 小数；
  - `forecast.yjyg_*` 的 `np_amp_* / rev_amp_*` 与 `yjkb_*` 的 `np_yoy / rev_yoy / roe`：
    百分数 → 小数（含 `forecast.snapshot` 嵌套行）。
- **指标层金额口径文档修正**：实测全部为**元**（历史文档误标"亿元"；上游 cn 名中的
  "(%)"/"(亿)" 后缀是命名遗留，不代表数值口径），数值本身未变。

### Added

- **数据正确性保障（三层防线）**：① 目录声明式单位契约（函数级 `units`/`ranges`/`checks`
  与指标级 `unit`/`range`，schema 同步扩展，装载期即校验声明合法性）；② 返回前量级守护 +
  关系不变量（`diffp_ratio`、`volume_amount`），违例抛新异常 `DataError`（含字段/实际值/
  期望范围与逃生口指引），换算声明错误会被数据自动暴露；③ `tools/audit_units.py`
  样本宇宙审计（不同板块/行业/规模 + ETF，全部关系型断言）+ CI 每交易日夜间自动执行。
- **逃生口参数**（语义有测试守护）：`_units="native"` 保留脚本输出单位（字段名仍规范化）、
  `_raw=True` 返回 store 原始行、`Client(validate=False)` 保留换算关闭校验。
- 精选指标量级守护：精选组指标声明量级范围（分位 [0,1]、股息率 [0,1]、市值 (0,1e14) 元等），
  `indicator.get/metrics` 返回前校验。
- README 新增「指标体系：算好的增值数据」（速查表 + 可执行示例 + 预期输出注释）与
  「数据正确性保障」章节；README 示例注释值由离线罐头测试守护，不再腐烂。
- docs/API.md 新增「数据目录（离线）」章节（`wmshare.load()` + Catalog 方法表），
  函数附录新增「单位与守护」列，指标组表新增「量级守护」列。

### Fixed

- README 的 `cat.search()` 行内引用补充 `cat = wmshare.load()` 装载步骤；
  示例风格统一为 `wmshare.load()`。
- kline 复权 `query_bars_adj` 不套 `volume_amount` 不变量（复权价与成交额不可比）。
- `rptdom.statement_tree` 派生行口径文档化（pct 行=原生百分数、`fmt="x"` 行=倍数、
  科目行=元）；树视图适合展示核对，跨接口运算用 `compare()`。
- 目录 upstream rev 同步至上游 454585e5（函数/指标计数不变）。

## [1.0.0] - 2026-10-22

First stable release. Install from source until the PyPI publication is enabled.

### Fixed

- Source-install instructions are now the documented path until the PyPI
  release; removed the not-yet-published `pip install wmshare` requirement.
- OAuth 401/403 and eval 401/403/429 now always raise `WmshareError` subclasses
  (`AuthError` / `LimitError`) with actionable AppID registration steps, instead
  of leaking `requests.HTTPError` or misclassifying 429 as `ApiError`.
- Notice query methods now return normalized flat rows (`date/title/url/...`)
  via `notice.fmt_maps`; `dividend.last()` now matches `history()` with flat
  fields instead of raw store rows.
- `last()` documentation/OpenAPI responses now describe a single object (or
  `None`), not the underlying array.
- Indicator ratio units corrected: metric-layer ratios are decimals
  (`0.332 = 33.2%`), not percentages (`15.0 = 15%`). Forecast yoy fields remain
  percentages.
- Dynamic facade now binds positional arguments to catalog parameter names.
- `_raw=True` with date ranges raises a clear `UsageError` for kline/moneyflow;
  notice windows reject unknown tokens instead of silently using 30 days.
- `notice.find()` normalizes `stock_code`; injected HTTP sessions are no longer
  closed by `Client.close()`.
- Swagger page fixed (`window.SwaggerUIBundle`) and now inlines the OpenAPI spec
  so it opens directly from disk.
- Untracked internal planning documents (`.zcode/`) from the public repository;
  `tools/check_leak.py` now fails on any tracked file outside the public whitelist
  (see CONTRIBUTING.md).
- Added PolyForm-required `Required Notice` line to LICENSE.

### Added

- PyPI metadata: classifiers, keywords, author (improves PyPI discoverability).
- Repository hygiene files: `CHANGELOG.md`, `SECURITY.md`, GitHub issue/PR templates.
- CI matrix extended to Python 3.10 / 3.11 / 3.12 / 3.13, plus wheel clean-install
  and Swagger syntax smoke checks.
- Friendly facade: unknown methods on namespace classes now delegate to the
  underlying `call()` — all 155 catalog functions are reachable via the typed
  facade (e.g. `cli.kline.screen_above_ma20(...)`), no more AttributeError.
- Dividend screeners promoted to the facade: `cli.dividend.screen_quality(...)` etc.
- New examples: `catalog_tour.py`, `dividend_screener.py`, `pandas_analysis.py`,
  `error_handling.py`.

## [0.1.0] - 2026-09

### Added

- Initial public release: 9 data domains (k-line, money flow, statements,
  indicators, notices, periodic reports, earnings events, dividends, reference),
  41 typed facade methods, 155 catalog functions, 2,197 metric codes,
  offline machine-readable catalog, zero-config trial appid,
  batch calls (`call_batch`), optional pandas support (`_df=True`).
