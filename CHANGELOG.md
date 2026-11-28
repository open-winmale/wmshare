# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> 兼容政策：见 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)——破坏性变更只能在
> MAJOR；弃用至少保留 1 个 MINOR，并在 `Deprecated` 段登记替代写法与移除版本。
> 升级前请扫一眼 Removed / Changed / Deprecated 段。

## [4.7.1] - 2026-11-28

### Fixed

- **股东增减持两处源端边界**：①`change_ratio`/`after_ratio` 上游偶发 >100%（源缺陷；
  全史实测 after_ratio 1,383/482,345 行、change_ratio 143 行）此前会落键并打穿量级
  守护，令**整次** `holdertrade.by_date`/`by_symbol` 抛 DataError——现按缺失处理
  （不落键、不补 0），守护范围保持 [0,1] 不放宽。

### Changed

- **`holdertrade.by_symbol` 单次上限 200 条**（服务端受控报错，不静默截断）：逐行
  `.append()` 收集按长度计费且超线性，实测 limit=20 ≈7,111 EC、limit=500 ≈107 万 EC，
  故收口到 200；`estimate_cost` 改为按 limit 估算（≈4,000 EC 底 + 超线性项，
  例如 limit=100 ≈4.6~7.9 万 EC）。更长历史用 `by_date` 按公告日取。

## [4.7.0] - 2026-11-28

> 4.6.0 未单独发版，本版一并发布其变更（MCP outputSchema、friendly API 示例、
> action 枚举同源等，见下一条目）。

### Added

- **股东增减持新域 `market.holdertrade`**：`cli.holdertrade.by_date`（单公告日
  全市场，按变动股数降序）/ `cli.holdertrade.by_symbol`（单票全史，date 升序）。
  字段 date / symbol / holder / holder_type / holder_role / direction /
  change_vol / change_ratio / after_share / after_ratio / avg_price；量=股、
  率=小数、价=元。可选字段源端为 NaN 时**省略键**（不补 0），调用方以缺失
  判断「未披露」。数据链路四层（raw `cn_holder_trade` 一公告日一档 → BSSAA
  清洗 `cn.holdertrade.LIST` → 脚本域 → SDK/MCP），全史 2010-01 起，@daily
  日更。附 `examples/35_holder_trade.py`；MCP 走
  `wmshare_market(domain="holdertrade", action="by_date"|"by_symbol")`。
  口径：上游不返回交易发生日列，行只有公告日；holder_type G=高管 / C=大股东
  （≥5%，含机构）/ P=机构投资者，以源披露为准。
- **`estimate_cost` 补 holdertrade 两档实测**（`model="measured"`，按生产
  `metering.ec_cost` 冷/热实测校准，数值与日期见 note）。

## [4.6.0] - 2026-11-27

### Added

- **MCP 全部工具字段级 outputSchema**：protocol 层把工具返回注解就地覆写为
  `core.Envelope`（函数式 TypedDict，规避 ForwardRef 探测吃掉 `NotRequired`
  的坑），29 个工具的 outputSchema 从宽松 object 变 `{ok, as_of, data, meta}`
  字段级契约，成功/错误两路径均过 FastMCP 双重校验；新增 `wmshare://envelope`
  resource 说明信封结构与两形态差异。
- **friendly API 路由示例零占位可执行**：`_example` 只产出可执行字面量
  （规则推导 + 手工表 15 条），30 条 `<REQUIRED>` 棘轮清零并删除生产点；
  自动示例统一 `cli.` 前缀，description 带返回形态后缀；新增全路由
  ast.parse + 签名绑定门禁，示例不可执行直接红。
- **wmshare_market action 枚举同源**：action 参数 description 与
  `MARKET_ACTIONS` 常量同源等值断言，杜绝枚举清单双处漂移。

### Fixed

- **MCP 通用网关拦截内部名**：`tools.call` / `batch` / `cost` 三入口统一拦截
  `is_internal_name` 与目录 `internal: true` 项（catalog 分支复用已加载 fn），
  内部域不再可绕道通用网关直调；新增 6 组合参数化网关测试。
- **`*_pct` 口径统一小数**：MCP instructions 与 `wmshare://units` 的百分数
  旧口径写法（80.3%）统一为小数（0.803=80.3%），examples/04 与 README
  few-shot 同步；test_docs 口径门禁扩到 8 个 Agent 面 + stale_claims。
- **错误码全集补登**：`gen_errors` 扫描扩为双模式（`self.code` 赋值 +
  `code or` 兜底，`\b` 防误报），补登 10 个漏网码（gateway_policy /
  credential_required / auth / catalog / tool 与 client.py HTTP 映射兜底
  5 项）；SECURITY.md demo/as_of 过时描述对齐现行网关策略。

## [4.5.0] - 2026-11-26

### Added

- **放行内部报表域的附注提取三函数进目录（`cli.call` 直调；4.4.0 组合面的底层原函数）**：
  `note_index`（附注角标）/ `notes_for`（附注明细卡）/ `note_stmt_values`（报表行值），
  挂内部命名空间下（属性面/搜索/文档/MCP 不露出，直调形如
  `cli.call("<内部域>.notes_for", sym=…, code=…, period=…)`）。目录合同
  （params/returns/example）落 `fund.statements.yaml` v1.4.0，
  inventory 上游 rev 前进至 `edf8dd2d`（388 = 374 对外 + 14 内部）。
  - **口径警示（与认证三表分离）**：`note_stmt_values` 是提取车道重建的报表行值
    （全文车道优先、存量回落，构建期定线），**不是** `fin.balance/fin.income/fin.cashflow`
    认证宽表——重述调整与车道回落会造成两源差异，对账必须先与
    `cli.statements.balance/income/cashflow` diff 核对、以三表为准；正式数值结论一律
    用三表组合面。`notes_for` 返回披露原文提取卡（原值字符串+千分位），非结构化报表数字。
  - 内部域属性锁不松：`cli.rptdom` 属性访问 / `cat.search` / friendly 属性 / docs / MCP
    仍不露出（仅 `cli.call` 直调）。
  - EC 档位实测（2026-11-26 test-api）：notes_for 显式期 ≈4.2k 起（随域数放大）、
    note_index ≈68 万、note_stmt_values ≈5.4k；已登记 `estimate_cost`。

### Changed

- **inventory 上游同步（964affe0 → edf8dd2d）**：上游新增 `kline.bars(sym, begin, end)`
  （区间日 K 直调）暂登记 INTERNAL_HELPERS 不进目录——与 friendly 组合面
  `cli.kline.bars` 同名，公开待独立评估（EC 档位/区间护栏/双面歧义）。

## [4.4.0] - 2026-11-26

### Added

- **`cli.statements.notes` / `notes_index` / `policies`：财报附注与会计政策组合门面（仅 A 股）**，
  与平台专业版「经营分析·会计政策」页及 skill 侧 `wm-statements view=notes` 同构，读取脚本镜像上游实现：
  - `notes(symbol, code, period=None)` → 附注明细卡 `{found, code, cn, period, source, sections}`。
    科目认目录代码（MFNS/IO/PPE 等 53 码）也认中文名（脚本内按附注目录双匹配）；
    `period` 缺省在脚本内解析该科目最新期（单次请求）；`found=false` = 该科目该期
    尚未入附注库（覆盖以返回为准，勿外推）；`source` 为平台提取车道标识（全文车道
    优先、存量车道回落）。不做聊天侧的段数截断，返回全量卡片。
  - `notes_index(symbol)` → 附注覆盖角标 DataFrame `{code, cn, period}`（code 升序、
    期内 period 降序；periods 为各提取车道并集）。查明细前先探覆盖，避免空跑。
  - `policies(symbol, period=None, hist_years=0, with_quote=True)` → 会计政策卡
    `{symbol, periods, period, cards, hist}`（镜像专业版页合同）：当期全套卡含
    `quote` 政策原文串；`hist` 全期历史卡**不含 quote**（体积控制），`hist_years>0`
    截最近 N 期。提取车道按期解析（全文车道优先、无车道存量回落，两线卡不混），
    跨期 diff 不出假变更；`period` 不在期次表回落最新年报；仅年报期（12-31）。
  - MCP `wmshare_statement` 同步新增 `notes` / `notes_index` / `policies` 三个 action
    （新增 `code` / `period` / `hist_years` / `with_quote` 参数）。
  - **EC 成本（2026-11-26 test-api 实测，已登记 `estimate_cost`）**：`notes` 显式期
    ≈1.4 万 EC、缺省期先跑全量角标解析 ≈68 万 EC（**例行查询请显式传期**）；
    `notes_index` ≈97 万 EC/次（近沙箱计算上限，勿循环调用）；`policies` ≈3.8 万~7.3 万 EC。
  - 组合门面（eval 读取脚本），不新增目录函数、不经过目录合同的单位换算与量级守护层；
    附注库覆盖为持续扩充的白名单制，以 `notes_index` / `found` 返回为准。

## [4.3.0] - 2026-11-26

### Changed

- **`valuation.daily_basic` 的 `circ_mv` / `float_share` 改用「无限售股份」（自由流通口径）**。
  此前取上游股本快照的「流通股份」，实测该字段恒等于「总股份」（600519 16 档 /
  000001 63 档 / 301558 17 档逐档核对）——于是 `circ_mv ≡ total_mv`，次新股的自由
  流通市值被大幅高估：最极端 688801 只流通 4.16%（虚增约 24 倍）、688781 4.16%、
  001399 5.81%，全市场 **3,082 / 6,167 票**受影响。
  现在 `circ_mv = 当日收盘 × 当日无限售股份`，行内仍满足
  `circ_mv / float_share == 当日 close`，常态 `circ_mv ≤ total_mv`。
  - **影响面**：只改数值口径；签名、信封、字段集均不变（仍 10 字段）。
  - **历史边界**：只有 repair 窗口（默认近 60 交易日）内的行被重写，窗口外的旧行
    仍是「流通股份」口径，同一条序列可能出现一次跳变。
  - **迁移**：需要口径一致的长历史请用 `total_mv`；或先用
    `cli.valuation.daily_basic(symbol, begin=…, end=…)` 确认该区间的口径边界。

### Fixed

- `cli.equity.query_buyback_detail` / `query_buyback_plan` 对港股标的返回 `None`
  （调用方 `len()` 直接崩）→ 改为空行数组 / 空表；`query_buyback_detail` 的
  **返回形态保持不变**（历史契约是行数组，不经 `_out`），只把 `None` 归一为 `[]`。
- `cli.equity.query_holder10` 对非 A 股标的静默返回空表 → 改为抛
  `UsageError(code="market")` 并指向港股替代入口 `cli.intl.query_shareholders`
  （口径不同：主要股东权益披露，不是「十大流通股东」）。

## [4.2.2] - 2026-11-25

### Fixed

- **内部目录命名空间不再对外暴露底层函数名**。此前隐藏规则只落在文档生成器，
  运行时完全没有过滤：内部命名空间的五个函数属性直达、`dir(cli)` 补全可见、
  `cat.search("报表")` 首条即命中内部函数。Agent 照着检索结果调用，又撞上
  该函数要求 `fin.*` 全名 domain，形成误导路径。现在统一由
  `wmshare.catalog.INTERNAL_CATALOG_NS` 收口：
  - `cat.search()` 跳过内部命名空间（MCP `wmshare_search` 随之修复）
  - `dir(cli)` 不再列出；内部命名空间的属性直达报错并给出替代指引
  - `cli.statements.statement` / `statement_years` / `statement_compare` /
    `statement_tree` 四条动态透传一并关闭——它们此前会经 `_Api.__getattr__`
    绕过 Client 层拦截，把内部函数漏回给用户
  - MCP `wmshare_contract(kind="function")` 与
    `wmshare://catalog/function/{name}` 资源对内部函数拒绝并给替代指引；
    `api_routes` 的 `catalog_function` 字段对内部底层置 `null`
  - 类型化门面不再生成内部命名空间类；`gen_llms` / `gen_api_docs` 略去整域
    notes（此前 `llms-full.txt` 与 `docs/API.md` 会输出「domain 取值
    fin.balance_sheet / ...」这类内部参数契约）
  - 保留 `cli.call()` 对内部函数的底层直调（`cli.statements.audit` 依赖它）、
    `cat.function()` 目录查询，以及 `cat.namespaces()` / `stats()` 的全量口径

  对外接口 `cli.statements.balance / income / cashflow / indicators / audit`
  行为完全一致，无需迁移。

- 内部三表透视族的 `domain` 参数补齐取值说明，并给其中两个函数补上与另两个
  一致的 enum 声明（此前四者对同一参数口径不一）。

## [4.2.1] - 2026-11-25

### Fixed

- 站点接口文档生成：`kline.adj_factor` / `index.bars` 两条组合面在
  `tools/_introspect.py::FALLBACK_RETURNS` 补返回说明（站点生成器
  `scripts/gen-api-docs.py` 要求每个接口有返回说明与字段表，缺则拒绝生成并
  报「返回说明与字段表双缺」）。接口行为与 4.2.0 完全一致。

## [4.2.0] - 2026-11-25

### Added

- `cli.gold.symbols() / bars(symbol, n) / query_bars(symbol, begin, end, limit)`：
  **金交所现货日线**（Au99.99 / Au(T+D) / Ag(T+D) / Pt99.95 等）。数据本就在库
  日更（airflow 每交易日 17:30 → `mkt.futures_kline` 的 `exchange="SGE"` 品种族），
  此前读不到是因为期货归一器会 UPPER 品种段、而存储键大小写敏感。口径：
  **价=元/克、量=千克、额=元**（实测 `volume×1000×close ≈ amount`），与期货
  （元/吨、手、万元）不同，故独立成域。`percent` 由 `change1` 派生（上游
  `pre_settle/pre_close` 恒 0、`percent` 为 nil）。
- `cli.kline.adj_factor(symbol, n=120, begin=None, end=None)`：**累计复权因子**
  （`hfq_close / nr_close`，ipo 起算、长期递增）。组合面（两次取数内积），
  不新增目录函数；需要最新日恒为 1 的归一因子时除末值即可。
- `cli.index.bars(key, freq="W"|"M", n=120, begin=None, end=None)`：**指数周/月 K 线**
  （SDK 聚合；上游不派生指数周月 K）。`date`=周期内最后交易日，含未走完的当前
  周期，`percent` 由周期末收盘重算。此前 `kline.bars(freq="W")` 对指数报
  `UsageError(code="freq")`，该限制保留（语义不同：一个是原生派生、一个是聚合）。
- `valuation.daily_basic` / `daily_basic_multi` 新增 **`total_share` / `float_share`**
  两个字段（当日总股本 / 流通股本，单位股）——与市值族同源，故行内满足
  `total_mv / total_share ≈ close`，可用作市值口径的自检锚。字段全集 8 → 10。
  注意上游披露的「流通股份」实测恒等于「总股份」，故 `float_share == total_share`；
  真实可流通口径为「无限售股份」，无逐日源，暂不落。

### Changed

- **行为修正（数据正确性）**：`valuation.daily_basic` / `daily_basic_multi` 的
  `total_mv` / `circ_mv` / `turnover_rate` / `dv_ttm` 由「取物化时刻最新行情」
  改为「按行日期取当日值」。字段名、单位、返回形态均不变。
  - 缺陷事实：旧实现用 `$MV_LAST / $MV_FREE_LAST / $TURNOVER_RATE_LAST /
    $BONUS_RATE_TTM_LAST` 配 `AT(锚日)` 求「某日的市值族」，但这四个码的缓存
    级别是 symbol、定义里带 `LAST(store.latest(...))`——**取的是求值时刻的 K 线
    tip**，`AT` 只改求值锚不会让 `LAST` 回到锚日。实测（600519，总股本
    1,250,081,601）：11-19/11-20/11-23 三行的 `total_mv` 分别等于
    11-20/11-23/11-24 收盘 × 股本（**前视一天，误差为 0**）；11-06～11-18
    九个交易日四字段完全冻结（事故修复把同一 tip 写进多行）。
  - 影响面：2026-11-18 起物化的全部历史行中，市值族与换手率/股息率可能存在
    同日错位或整段冻结。`pe_ttm/pb/ps/pr` 走 `HIST_STATS` 序列，**不受影响**。
  - 迁移：无需改代码。历史行由 airflow `pipeline.cn.valuation_daily.manual`
    传 `{"repair_mv_days": 60}` 重写近 60 交易日整行（近窗自愈也会顺带刷新
    缺股本列的老行）。跨窗口的自查方法：`total_mv / total_share` 应等于当日
    `close`（偏差 >0.5% 即为旧口径遗留）。
  - 防复发：`daily_data_guard` 新增 `valuation_daily_mv_consistency` 检测器
    （行内自洽 + 跨日不冻结，近 10 交易日抽样 300 票），偏差或冻结即告警。

## [4.0.0] - 2026-11-25

### Changed

- **版本线重置（MAJOR）**：自本版本起仓库提交历史重置为单基线提交；版本号在
  旧线末版 3.7.1 之上叠加 MAJOR 至 4.0.0，已安装用户 `pip install -U wmshare`
  可正常升级，无版本号回退歧义。代码功能面与 3.7.1 完全一致，此前 1.7.0–3.7.1
  的发布记录与逐版发行说明可在 PyPI 历史版本页查阅。
