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

- ~~**【P0 数据正确性，2026-11-19 消费端发现】`kline.bars(sym, n=5, adj=None)`
  对 600519 返回后复权价**~~ **已修复并 live 验证（2026-11-19）**：
  `close` 末值曾是 **12473.67**（真实不复权收盘 **1442.66**），整 5 行都被污染。
  **根因不在 n=5，而在复权口径串号**——任何「同票同窗口、不同 adj」的调用都会
  双向互相污染（先调者胜）：
  `kline.rows_fingerprint` 的结果缓存键只有 `symbol + 行数 + 首末采样时间戳`，
  nr/qfq/hfq 读三个不同库但这三项完全相同 → 键必然碰撞。`n=5` 只是恰好撞上
  一条已被 hfq 填过的旧条目，所以看起来像「n=5 专属 bug」。

  修复过程（script 仓，两轮）：`893c7267` 先把 `catalog` 加进指纹，但 XS 侧
  `rows[0].catalog` **实测恒为 nil**（v2.Rec 不含该字段），等于加了空串、无效；
  `ee87a56e`（v4）改用**行内数值指纹**（首末行 open/close/volume/amount 采样）
  ——口径不同则价格差达复权因子量级，键必不同；日频 EOD 不可变，命中率不受损。

  live 复验（2026-11-19，部署后）：
  `kline.bars("600519", n=5, adj=None)` → **1442.66**（正确）；
  `n=203` 的 nr/hfq 比值 **8.4464**（≈复权因子，口径隔离生效）；
  双向顺序测试（先 nr 后 hfq / 先 hfq 后 nr）均不再串号。
  交叉回归（消费端独立复验，4 标的 × 5 窗口 × 2 口径 = 20 组）：0 不一致，
  各票复权因子清晰分离（600519 ≈8.65×、000858 ≈21.2×、601318 ≈3.30×、
  600036 ≈6.66×）；wmshare-qlib `dump-history --live` 的 hfq+raw 双取路径
  恢复（`integrity.ok=true`、`null_values=0`、EC 3,712）。

  残留提醒：`validate=False` 下 SDK 仍不拦量级异常（这是该开关的定义），
  但错价源头已消除；`_raw=True` 始终可作独立核对口径。


- ~~**kernel 读面 `limit≤0→200` 默认对其他 catalog 的影响**~~ **已排查闭环
  （2026-11-19）**：逐域实测 `limit=0` 行为——`kline.query_bars` 返 **0 行**、
  `moneyflow.query_bars` 返 200 行（kernel 默认，非域默认 20）、
  `bonus.query_list` 恰好 33 行（< 200 默认，无差异）。已在包装层统一归一：
  `kline.store_window_limit`（≤0→120，覆盖 5 个窗口入口）、
  `moneyflow.store_limit`（≤0→20，含 anchor 变体）、`bonus.store_query` 内联；
  `forecast` 三个入口原已走 `clamp_limit`；`intl/estimates/margin/equity/
  filings` 用 `{"unwrap":"list"}` 无 limit 参数，不受影响。

## 已发布面遗留（登记不装死）

- **2026-11-25 P0：估值宽表市值族前视/冻结（已修、已部署、已 repair 并全量重写）**：
  `valuation.daily_basic` 的 `total_mv/circ_mv/turnover_rate/dv_ttm` 此前用
  metric 层 `$MV_LAST/$MV_FREE_LAST/$TURNOVER_RATE_LAST/$BONUS_RATE_TTM_LAST`
  配 `AT(锚日, ITER(...))` 求值。这四个码的 memo cachetype 是 symbol 级、定义里
  带 `LAST(store.latest(...))`（`../script/sys/metric/shared/kline.xs:154,182`），
  **取的是求值时刻的 K 线 tip**——`AT` 只改求值锚、不会让 `LAST` 回到锚日。
  实测后果（600519，总股本 1,250,081,601）：11-19/11-20/11-23 三行的
  `total_mv` 分别等于 11-20/11-23/11-24 收盘 × 股本（前视一天，误差 0）；
  11-06～11-18 九个交易日四字段完全冻结（11-18 事故修复把同一 tip 写进多行）。
  修法：行日期由 K 线交易日决定，市值族从同一行的 `close` 与**当日**股本算出
  （`total_mv = close × 当日总股本`），结构上不可能错位；同批新增
  `total_share/float_share` 两列使行内自洽可验（`total_mv / total_share == close`）。
  防复发：`daily_data_guard` 新增 `valuation_daily_mv_consistency` detector
  （行内自洽 + 跨日不冻结 + **数据日不超前**，近 10 交易日抽样 300 票）。
  存量修复：`pipeline.cn.valuation_daily.manual` 传 `{"repair_mv_days": 60}`
  重写近 N 个交易日整行（2026-11-25 已执行：600519 等 10 票 × 6 交易日抽查
  `total_mv / total_share` 与当日收盘 **diff 0.0000%**，全票 0 错值）。
  repair 窗口中更早的历史行仍保持旧口径（诚实缺列 `total_share/float_share`），
  市值族在窗口外不再保证行内自洽——需要用旧口径时请以 `as_of` 与 repair 窗口为准。
  **收口实证（2026-11-25/26）**：三层缺陷修完后对全市场 5,695 票整轮 radd 重写，
  展开 `data.list` 按集合比对最近 11 个交易日 `V2 == raw`（0 missing / 0 extra），
  `V2@11-25 == raw@11-25 == 0`；生产 detector `status=ok`、phantom/orphan/frozen 全 0、
  `share_coverage=1.0`，且 `rows_checked(2664) > sampled_symbols(297)`（抽样健康判据）；
  API `as_of` 全部回落到 11-24，`total_mv/total_share` 反推价与同日收盘逐票零误差。
- **2026-11-25 验收发现的第二个缺陷：无行情支撑的「当日伪行」（已修并部署）**：
  首轮 repair 成功后仍有一半标的（实测 3,069 / 5,695 票）带
  `trade_date=2026-11-25` 的行，形态固定为「3~4 个字段、无
  `total_share/float_share`、无 `pe_ttm/pb/ps/pr`，`total_mv` **严格等于**
  前一日值」（1,408/1,408 抽样全中）——旧口径 `$*_LAST` 冻结 tip 的另一面。
  11-25 的 K 线要到 16:10 才落库，这些行没有任何行情支撑，却被 clean 洗成
  V2 文档把 `as_of` 顶到 11-25（API 面 `as_of=2026-11-25` 而当日无行）。
  根因：`_merge_raw_doc_rows` 的「旧行按 trade_date 全保留」在**整窗重算**
  模式下也是无条件保留，所以 repair 只重写 K 线覆盖的交易日、伪日永不清除。
  修法：`replace_symbol_rows(..., authoritative_window=(lo, hi))`——整窗重算
  （backfill/repair）时，`day >= lo` 的旧行必须由本轮结果背书，本轮没有即删；
  `lo` 取「N 个交易日前的日历日」（**不能取结果最小日**，否则 backfill 的
  PE-only 历史会被全删）。增量模式不传窗口（只产前沿+补行，不能拿它删别日）。
  检测：detector 增加 `phantom_symbols/phantom_count`（行的 `trade_date` 晚于
  「已有行情支撑的最晚一天」即判伪日，占比 >1% → error）。上界取 **raw 层
  全市场最大数据日**而不是「日历 + 已过 16:10」：后者假设 K 线当天 16:10 必
  落库，实测会迟（2026-11-25 17:30 仍没有 11-25 的 K 线），于是 16:10 之后
  白底写满伪行的表反而判 ok——事故正好落在这个窗口里。
  该 detector 自身还有两个缺陷一并修了（同样属于「绿了但没测到」）：
  ① 窗口下界取 `days[0]`，而 `_trade_dates_le` 是**降序**返回 → 检查范围退化成
  最新一天，采样只覆盖 300 票 × 1 行；② 单次 `find(ts>=floor).sort(ts,-1)
  .limit(300*10)` 在分组前全局截断，1,067 万条「一票一行」的集合里只够取到
  最新一天的部分票。两者叠加使 `frozen`（同票跨日 `total_mv` 连续多日同值）
  **永久假阴性**，生产征兆是 `rows_checked == sampled_symbols`。改为
  `min(days)` 作下界 + 「先 `distinct('symbol')` 定票、再按票取各自窗口」；
  冻结阈值同时由 3 提到 5（低价股在 1 分钱价位连续 3 日平收是真实行情，
  实测 000980 三连平 1.44 元、301558 两连平 5.55 元，事故形态是 9 连平）。
- **2026-11-25 验收发现的第三个缺陷：radd 的 V2 删除静默空转（已修）**：
  第二个缺陷修好 raw、`build` 与 `clean` 双双 success 之后，V2 层的 3,069
  条 11-25 文档**一条没少**，API 对 301558/688798/900953 仍报
  `as_of=2026-11-25`。根因不在估值链路，而在 `bssaa` 的
  `_delete_v2_for_radd`：它把 `v2_catalog` 写死成 `alt.bssaa`，而
  `dual_write_delete` 用 `v2_collection_for(catalog, symbol)` 选物理表——
  普通 `bssaa` 表恰好对得上（`alt.bssaa` 是分片 catalog → `alt_bssaa_cn`），
  独立 catalog 的表就打到别的集合上：`valuation_daily` 的真实物理表是
  `alt_valuation_daily`，删除却指向 `alt_bssaa_cn`，`delete_many` 匹配 0 条
  且不报错。于是 `radd`（删除后全量重写）退化成「只 upsert 本轮产出的行」，
  **范围之外（未来日）的旧文档永久留存**——`clean` 报 success 并不代表旧档
  已清。修法：`v2_catalog = resolve_catalog(dest_db, dest_collection) or
  "alt.bssaa"`；未映射的 collection 仍回退旧值。已按修好的路径先对 3,067 票
  重跑一次 radd，再对全市场 5,695 票整轮重写，使 V2 == raw；`as_of` 回落到
  11-24（900953 回落到其真实的 2024-06-11）。
  同一坑的旁证：`index_members_daily` 等独立 catalog 的表有同样风险。
  **2026-11-26 穷举审计**（248 条清洗规则的全部 dest，`resolve_catalog` 逐条反解）：
  共 6 个 distinct dest，**全部有映射、0 个落回 `alt.bssaa`**；其中 3 个是独立 catalog：
  - `cn/valuation_daily` → `alt.valuation_daily` → 物理表 `alt_valuation_daily`（1,062 万行）
  - `cn/index_members_daily` → `alt.index_members_daily` → `alt_index_members_daily`（12 行快照）
  - `common/bssaa` → **`eco.macro`** → `eco_macro`（74 万行；汇率/沪深港通资金流/大盘资金流DC 3 条规则）
  修复后这三张表的 radd 删除各打自己的物理表。新增契约单测：
  `test_bssaa_radd_delete_tiering.py` 里参数化断言三张独立表各命中自己的 catalog，
  并断言「248 条规则的全部 dest 都必须能反解出 catalog」（未映射即 fail，防止未来
  新增独立 catalog 表时又静默回退）。
  **待观察**：`eco_macro` 的 `currencyrate.PROPS` 此前若走 radd，删除一直是空转，
  可能残留过期键——下次汇率 DAG 跑完后抽查该表 `currencyrate` 行集合是否收敛。
- **`circ_mv` / `float_share` 用错了股本口径（2026-11-26 定位，构建侧已修）**：
  上游 `cn.equity_change.PROPS.<sym>` 的 props 里「流通股份」**实测恒等于「总股份」**
  （600519 16 档 / 000001 63 档 / 301558 17 档逐档相等），真实自由流通口径是
  **「无限售股份」**——同一份 props 里就有值：
  301558 2025-12-31 档 总股本 790,540,023 / 无限售 219,481,852（IPO 锁定 72%），
  2026-09-28 档 无限售 790,045,023（解禁后）；000001 也有 19,405,684,991 vs
  19,405,918,198 的真实差额。
  旧构建取「流通股份」→ `float_share` 恒等于 `total_share`、`circ_mv` 恒等于 `total_mv`
  （301558 这类次新股的 `circ_mv` **虚增 3.6 倍**，任何以它为权重的筛选/加权都偏）。
  修法（airflow `tasks/valuation_marks.py`）：`EQUITY_FREE_KEY` 改为「无限售股份」，
  缺失时回退「流通股份」（早年档位）；`circ_mv = close × 无限售股份`。
  **影响面（2026-11-26 全量聚合，取每票最新股本档）**：6,167 票有股本档，
  **3,082 票（50%）的 `无限售/总股本 < 99%`**，最极端的次新股只流通 4~8%：
  688801 4.16%（旧 `circ_mv` 虚增 **24 倍**）、688781 4.16%、001399 5.81%、
  301689 6.20%、688828 6.51%——这些票的流通市值/自由流通加权此前全错。
  **已部署 + 全市场 repair 完成（2026-11-26 实测闭环）**：airflow `29624377` 当日
  部署后，`pipeline.cn.valuation_daily.manual` 全市场 60 交易日 repair 一次跑通：
  **5,695 票 / 340,682 行 / failed=0 / 实测 5,342,688 EC（≈938 EC/票）**；build
  ≈21.5 分钟，clean 全表重投影 ≈54 分钟（run 总时长 75 分钟，瓶颈在 clean）。
  旧估「6k EC/票 / 全市场 ≈34M EC」高估约 7 倍——repair 成本是每票固定 2 次
  eval，与窗口天数弱相关。验收（raw 层 + V2 投影 + 全表对账三层）：
  688801 全 48 行 ratio 0.0416（无限售 17,900,325/430,351,728，「虚增 24 倍」消除）；
  301558 窗内 0.2782 → 09-18/09-21 档 0.2798/0.2795 → 09-28 解禁档 0.9994，阶梯正确；
  recon 全历史 missing=0 / extra=0 / circ>total=0，`circ==total` 由 10,613,862 降至
  **10,403,738**（窗内 34.07 万行中 21.78 万行实现 circ<total 真实区分）。
  **残留清偿（2026-11-26 全史 backfill 已跑完）**：mv_days=1000 整票重算全市场 =
  5,695 票 / 528.8 万行 / failed=0 / **66,183,864 EC（≈12.5 EC/行，EC 近乎按行
  计费）**，build 48 分钟 + clean 54 分钟；recon 三零保持，`circ==total`
  10,403,738 → **6,945,193**（repair→backfill 累计消除旧口径 366.9 万行）。
  残余 ≈695 万行 = pre-2022-11 尾巴（kline 单查 1,000 根硬上限，引擎分页是
  平台级新工程，登记不排期）+ 真全流通票（口径自然相等）。
  **放行前 review 抓出并修复的两个连环缺陷**（airflow `dcdaa6d8`）：
  ① 档位阶梯 50 条截断——equity_change PROPS 是月度快照节奏（000333 有 670 档），
  `store.query` 默认 50 条只够 ~4 个月，整窗重算产「壳行」；诊断指纹=壳行止日
  与各票第 50 档生效日逐日对齐；修=`DEEP_LADDER_FETCH_LIMIT=1000`（仅整窗重算
  传），26 票重跑 327,516 EC 清壳，全表扫残留仅 920067×3 行（北交所上游档位
  缺口，登记）。② K 线窗（1000 根≈4 年）> 序列窗（3y 硬上限）→ 权威窗整行
  替换把 2022-11..2023-11 带的 PE-only 旧行冲成无 PE 行（≈140 万行）；修=
  `CARRY_FIELDS`{pe_ttm,pb,ps,pr,dv_ttm}+序列地板 `carry_before` 窗外回带
  （回带源必须含被权威窗 prune 的行）。build 前抢救 710,799 行/4,376 票 PE
  快照；early-clean ≈1,319 票 band PE 不可恢复（诚实登记）。
  **回带实绩（2026-11-26 夜，回带结果数字已回填）**：CARRY 实测只救回少数
  （restore 复扫 95% 快照行仍缺值，勿当已闭环）；`valuation_pe_band_restore.py`
  （--apply 门控、只补缺失列、幂等可重跑、排在日更 build 段后防 17:05 竞态）
  补齐可补 676,359 行（raw 676,019 + 验证批 340 / V2 676,018 + 验证批 340
  + 首跑已落 1），余 34,440 行 = 行已带值或行缺失；recon 全历史三零保持、
  `circ==total` 6,945,193 逐位不变（只补列不动行集）。首跑曾因「投影取文档
  + 整文档 ReplaceOne」抹掉 V2 身份字段撞 `uk_symbol_catalog_ts` 唯一索引
  崩批（1 文档已按同 ts 镜像手工恢复）——批处理写库必须 `$set` 只碰目标
  字段，且真实退出码勿经 `| tail` 吞掉。
  **oplog 兜底评审结案（2026-11-27，终态=永久缺口）**：三证据——存储
  Mongo 为 standalone（`isMaster` 无 setName，7.0.3，oplog 物理不存在）+
  服务凭据对 local 库无权限 + 全仓无 mongodump 例程（ops 文档均为操作级
  一次性备份）；且 band PE 文档本体为 ≈3 年前插入，任何日志类兜底都够
  不到。≈1,319 early-clean 票 + 34,440 行残留维持诚实缺档，不再排期。
  SDK 侧口径说明与 4.3.0 CHANGELOG `Changed` 已随 `b24f007` 先行落地，数据面本次对齐。
- **`float_share` 与 `total_share` 相等（上游口径）**（历史记录，保留备查）：股本变动快照披露的
  「流通股份」实测恒等于「总股份」；真实可流通口径是「无限售股份」，**该字段上游有值**
  ——见上一条。
- **数据质量审计 2026-11-24 六项结论**（来源 `.internal/data_quality_report.json`，
  处置已在版本线重置前随 3.7.1 落地，随 4.0.0 基线继承）：
  - `valuation.daily_basic` / `daily_basic_multi` date 非升序：**已修**（门面按
    `(date, field)` / `(symbol, date, field)` 排序；服务端原生为日期降序）。
  - `index.members_history` 空窗口 `ok=False`：**非缺陷**——契约写明 `count==0`
    表示「尚无快照」；物化表快照自 2026-11-20 起，更早窗口空是诚实的（live：
    11-01..11-20 返 300 行、6 月窗口 0 行）。
  - `notice.read_text` `no_pdf_url`：**非缺陷**，无 PDF 链接的受控结果（note 引导传 url）。
  - `pdf_doc.read_text/read_markdown` 空参 `ok=False`：**审计误用**（无参数调用）；
    门面已补 `UsageError(code="params")` 前置校验，不再打上游。
  - `pdf_doc.find_by_url` 全失败：**审计用错字段**；实测传 `search` 行的
    `source_url`（形如 `pdf_doc://filing/600519/2018-12-31`）可命中。
  - `pdf_doc.search` `text_chars` 超声明：**已修**——上限 1e7→5e7（巨型年报实测
    1,450 万字符）。
  - `etf.nav` `net_asset` 差 6 个量级：**上游异常**（2026-11-24 全 ETF 实测 1e18
    量级，疑管道口径变更）；门面把该字段置空并在 `data.note` 说明，净值/份额
    照常返回，等上游修复。
- **汇率/储备未纳入新鲜度看板**：`../airflow/data_monitor/stats_config.py` 的
  `STATS_CHECKS` 无 `currencyrate` 与 `currency.reserve.*` 条目（上游 Go 采集链已
  paused）。故 `docs/DATA_CALENDAR.md` 不含这两项——**不伪造新鲜度条目**，
  待上游恢复生产后补登记。
- **美宏观无新鲜度阈值**：`fred.*` 同样不在 `STATS_CHECKS`；序列更新频率随
  各序列原生频率（D/W/M/Q）而异，单一阈值无意义。点序列取回后以末点日期自判。

## 上游指标目录缺席（登记待办，SDK 侧不伪造）

- `$BOND_YIELD_GOV_10Y`（十年国债收益率）：服务端指标层已在产（`AT(sym, $BOND_YIELD_GOV_10Y)`
  live 实测 2026-11-20 返回 0.0168），但上游 `metric-memo-catalog.json` 未收录——wmshare
  指标目录（2983 码）查不到该码。消费方：`income.diagnose`/`income.rating_rows` 的
  bond_yield_10y 字段（服务端直出不受影响，仅 SDK 指标目录检索缺）。同 `$BUYBACK_AMT*`
  缺席先例，登记上游待办，SDK 不伪造。

## 覆盖面补齐队列（2026-11-23 对标盘点，逐项全链路）

> 与主流 token 制数据 SDK 的全量对标（内部矩阵，不入库）后产出的缺口队列。
> 每项 = 一个独立覆盖单元，走完整链路（airflow 采集 → script 读面 → 暴露门禁），
> 一个数据一个数据补，不并批。

| # | 数据项 | 定性 | 链路 | 状态 |
|---|---|---|---|---|
| 1 | 期货日线/周月线历史序列 | 补暴露面 | wmshare 目录 | **已上线**（`cli.futures.bars` 门面 2.9.0 + `futures.query_bars` store 直读进目录，2026-11-23——全历史长窗/结算·持仓字段/同日复跑缓存，分工见 API.md 期货节） |
| 2 | 官方储备（外汇储备/黄金储备/SDR） | **已上线 3.0+**：`cli.macro.reserves/reserves_history/reserves_asof`（月频外汇+黄金，值=美元数值）；**遗留**：SDR 上游无生产者（`available=False` 如实标注）、黄金仅市值口径无吨数/盎司、国别维度待走 FRED 目录核（丢队列④） | script → wmshare | 已上线（部分） |
| 3 | 外汇（人民币中间价/日线/基础信息） | **已上线 3.0+**：`cli.fx.rate/history/bars/list`（采集零新增，数据日更在库）；口径=每 1 单位外币折人民币（上游每 100 外币已 /100 归一），中间价与中行牌价分列 | script → wmshare | 已上线 |
| 4 | FRED 美宏观序列暴露 | **已上线（3.2）**：`cli.us_macro.topics/search/series_meta/points`（精选 88 条 × 11 主题）；单位随序列而变（读 `series_meta().units`）、空值不补 0、需授权序列 `has_data=False` 永不抓取。**遗留**：web 页面读面 `fred.points`/`fred.series` 是「新→旧 + 期间码 year」契约，已标 internal 不进 SDK | wmshare（域 yaml + fred 读面） | 已上线 |
| 5 | 股东人数历史序列（现仅最新值） | **已上线 3.2**：`cli.equity.query_holdernum_history(symbol, limit)` 读 raw 层单票多期档（600519 实测 108 期、2001-12-31 起），日期升序、比例=小数、与 `query_holdernum` 同口径；单票上限 300 期 | script 历史读面 → wmshare 条目 | 已上线 |
| 6 | 每日涨跌停价格 | **已上线 3.2（当日快照）+ 已实现历史序列（3.4.0 已发版）**：快照 `cli.stocks.limit_price/limit_prices` 规则价=前收盘×(1±带宽) 四舍五入到分，带宽按代码号段（30x/68x=20%、北交所=30%、其余=10%）；历史 `cli.stocks.limit_price_history` 逐日给 basis/limit_up/limit_down/band/rule，basis 用 hfq/nr 因子还原交易所除权参考价（实测 600519 2024-06-19 得 1490.62），主板 ST 5%（至 2026-05-05）/10%（2026-05-06 起；2026 年样本实测切换日）、创业板 2020-08-24 前 10% 后 20%、科创板 20%、北交所 30%，IPO 前 N 日 rule=ipo。**遗留**：当日快照按板块带宽（主板 ST 10%，与 2026-05-06 起制度一致）且除权日仍用原始前收（全市场索引无 hfq 因子）；历史退市整理期无逐日源 | script 派生 → wmshare 暴露 | 已上线（快照+历史） |
| 7 | 概念板块（分类/成份/每日行情） | **已上线 3.2 + 3.3 + 3.5**：①资金流 `cli.board.moneyflow/moneyflow_last`（ths 概念/行业 + dc 概念·行业）；②概念标签 `cli.board.concepts_of`（单票 tags，≈90 EC）与 `concept_members`（名称包含匹配，代码升序；冷 ≈8.1 万 EC、当日 memo ≈200）；③目录 `cli.board.concept_list`（3.5：周更物化档 memo 点查 ≈110 EC，周六 09:00 片 / 09:15 merge，最多滞后一周；members 物化序、门面本地升序）。~~暂缓~~已闭环：物化一次实测 ≈318 万 EC（81,875 对；XS 逐元素 ~5-10 EC/op 是地板，投影 ≈15 万 只占零头），日更 ≈8.8 亿/年不可持续 → **周更 cron**（周六 09:00 片 / 09:15 merge，TTL 720h，年 ≈1.2 亿）——「cron 预算另议」落点，2026-11-24 实测后按推荐默认执行 | 小步暴露 → script cron 物化（airflow 零改动） → wmshare 域 | 已上线（资金流+标签/成份+目录） |
| 8 | 大宗交易 | **已上线 3.3**：`cli.blocktrade.by_date/by_symbol`（额=元/量=股/价=元；单日榜成交额降序、单票 date 升序）；2010 至今全量回补 4,100/4,100 交易日、67.9 万行；B 股 price 为外币、amount 为人民币（口径差已在接口 notes 注明，不做汇率换算） | airflow → script → wmshare | 已上线 |
| 9 | ST/停复牌变动历史（现仅时点旗标） | **已上线 3.3**：`cli.stocks.suspend_history/name_history/lifecycle`（停复牌按交易日、简称变更按生效日；ST 段由简称含 ST 判定；时间轴 rename/st_enter/st_exit/suspend/resume 日期升序）；采集 1999 起停复牌 644k 行 + 2000 起简称变更 13k 行，单票读面走清洗档点查（≈200-800 EC）；**遗留**：历史涨跌停价（⑥）已由 3.4 历史序列闭环（namechange ST 段 + hfq/nr 因子），无需再续接 | airflow → script → wmshare | 已上线 |
| 10 | 金交所现货（Au/Ag/Pt 日线） | **已上线 4.2.0**：`cli.gold.symbols/bars/query_bars`（价=元/克、量=千克、额=元；口径实测 `volume×1000×close ≈ amount`）。数据本就在库日更（airflow `market.cn.gold_spot_daily` 17:30 → `mkt.futures_kline` exchange=SGE），此前读不到的原因是 `futures.norm_symbol` 会 UPPER 品种段，而 V2 键大小写敏感（`cn.Au99.99.SGE`）→ 恒返 0 行。独立成域而非改 futures 归一器（后者会波及全部期货键）。**遗留**：`percent` 由 `change1` 派生（上游 pre_settle/pre_close 恒 0、percent 为 nil）；远期/租赁报价合约（`*.FWD`）无 OHLC 不入库 | script → wmshare（采集零新增） | 已上线 |
| 11 | 每日股本（total_share/float_share） | **已上线 4.1.0**：并入 `valuation.daily_basic` 字段（与市值族同源，`total_mv = close × total_share` 行内恒等）。**遗留**：上游披露的「流通股份」恒等于「总股份」，真实可流通口径是「无限售股份」——无逐日源，故 `circ_mv == total_mv` | wmshare（airflow 物化） | 已上线（口径受限） |
| 12 | 复权因子（累计 hfq/nr） | **已上线 4.2.0**：`cli.kline.adj_factor`（组合面，两次取数内积；实测 600519 近三日 8.6469 恒定）。**口径**：累计因子（ipo 起算、长期递增）；归一因子 `factor / factor.iloc[-1]`。**遗留**：美股 hfq 无国内因子源，factor 恒 1 | wmshare（组合面，零目录改动） | 已上线 |
| 13 | 指数周/月 K 线 | **已上线 4.2.0**：`cli.index.bars(key, freq="W"/"M")`（SDK 聚合；上游不派生指数周月 K）。date=周期内最后交易日，percent 由周期末收盘重算，含未走完的当前周期 | wmshare（组合面，零目录改动） | 已上线 |

## 本轮对标复验结论（2026-11-25）

- **已闭环、无需再做**：期货仓单/结算/持仓（3.7.0）、可转债 P1 四项（评级/票息/
  十大持有人/转股结果均在 `cbond.terms`/`holders`/`latest_share`）、LPR
  （`$LPR_1Y/$LPR_5Y` 在指标目录）。
- **无上源、登记不做**：SHIBOR（script/airflow 全仓无落库）、沪深港通十大成交股
  （上游无落库 + 交易所披露口径已收紧）、基金公司/基金经理主档（无源）、
  龙虎榜营业部席位明细（`sys/toplist/query.xs` 明示上游无落库）、
  十大流通股东（只有总口径）、增发/IPO/退市史（`disc.events` 只覆盖业绩披露，
  `stocks.lifecycle` 明示无上市/退市日期源）、高管简历（`query_executives` 无该字段）。
- **研报探针结论（2026-11-26 no-go → 2026-11-27 清洗链已盘活，更新）**：raw 层
  **有数据**、清洗档曾**全空**，根因是**清洗从未被执行**（规则在但无任何自动
  路径会跑；采集 DAG 亦从未排程、纯手动）。2026-11-27 修复+实跑：
  - 实 dump 校准推翻两条旧判断：行业报告真实行键就是 `INDUSTRY_CODE`（82 个
    行业码，「无对应清洗规则」系注释样例拿错集合的误判）；策略/行业顶层
    `stock_code='global'` 占位使 `FROM_RECORD/stock_code` 可用
  - 真缺陷=宏观规则两处拼写（source `cn_marco`→`cn_macro`、name_prefix 同样
    拼错），已修；个股/行业/策略三条规则实跑产出：
    `cn.research_report.LIST.*` **终局 126,692 行/4,874 票**（2026-11-27 下午
    cnall 全量重拉后终验；早盘 2,601 票/17,381 行 → ×7.3）、行业 **8,619 行/82
    符号**、策略 **230 行/1 global 符号**；guard 零产出巡检 `status=ok`
  - **采集链四层断裂当天全修**（上游采集库升级打断采集、raw 停在
    2024 的真根因链）：①签名只剩 `(symbol)`→`ak_params={}`+operator 注入；
    ②无研报关股票（次新 301xxx）KeyError('infoCode')→compat 垫片归一 0 行
    空表；③新版中文列 schema≠2024 存量英文键→transform 七键改名（bssaa
    规则 quota/dt 硬依赖，不归一则 radd 会冲掉历史清洗档）；④transform 真
    契约=(symbol, df, totol_pages)→整信封（镜像 default_transform_func）。
    终局重拉 4,713 成功/17 网络失败（0.36%），全绿无熔断；早盘 71,433 行
    中文键一次性 munge 收敛、复扫零残留
  - **行业/策略/宏观重新采集不可用**：装版上游采集库无研报入口（report_type
    拆分消亡），需直连数据源站点接口（另立项；细节见 airflow 仓当日提交链）；宏观清洗规则修复已部署就位，
    数据面等采集落地即可跑
  - **仍未建（另立项，维持登记）**：研报 PDF 正文抓取/解析层（raw 只存
    `REPORT_URL` 链接；`pdf_doc` 是公告域与研报无关）、SDK 研报域暴露
    （公开面走 INTERFACE_SPEC 独立流程）、script `研究报告.个股研报.xs` 空壳
    实现、采集/清洗日更调度（生产行为变更，盘活验证后单独确认）

## 口径核验批结论（2026-11-26：5 项待核定论 + 2 项生产探针）

> 只读核验（live 探针 + 生产库只读查询）；探针脚本与逐字段对照在 `.internal/`
> （不入库）。live 探针消耗 ≈215 万 EC：statements 2.4k-6.1k/次、HK kline 窗口
> 读 ≈36k/次、转债 `event_rows_of` 一次 703,582 EC（LIST 档全表载入）——重读面
> 接口勿在循环里逐票调用。

- **港美股财报三表 ✅ 实证通过**：`statements.income/balance/cashflow/indicators`
  三市场路由（6 位→cn / 5 位→hk / 其余→us）live 全通且非空（00700 四表 994~
  6,402 行、美股同），科目=披露原文、披露原币。此前「是否支持港美股待核」定论：
  支持，且对面为独立付费档、本端免费档含。
- **龙虎榜 P1 缺陷（已修复 2026-11-26，script `f4c3a52e7`）**：raw `cn_top_list`
  （3,118 天）近 25 个交易日 **19 天 `float_values`/`turnover_rate` NaN 污染** →
  eval 返回打穿网关（HTTP 200「不合法 JSON」）；`by_date` 仅 6 个健康日
  （10-22/28/29、11-05/17/18）可用，`by_symbol` 拉单票全历史几乎必撞污染日 =
  **门面生产态大面积不可用**。**读链 NaN 归一已修+部署+验收**（污染日
  `by_date` 恢复可用）；采集侧写链归一根治登记不排期。字段面定论：聚合口径
  （`seat_*`/`net_*`/`reason`/`amount_ratio`）已覆盖可覆盖部分，逐席位/营业部
  明细上游无落库=维持不做；11-21/11-14 空=周六非交易日（行为正确）。
- **ETF 基准 ✅**：`etf.profile.benchmark` 6/6 类型实测有值（宽基/行业/债券/
  QDII/创业板/科创，均「指数×100%」）。缺口登记：①基准指数**主档**（对面为
  独立 8000 分接口：基日/基点/发布机构/调整周期）=低优；②`p_value` 单位不一
  （511010=100 其余=1）**已归一（2026-11-26 小修批）**——skillhub `_etf_profile`
  读链统一小数口径（>1 视为百分数 /100，0-1 与 nil 透传；本地 kernel 4 断言 +
  `xs/tests/domain/skillhub_etf.xs` 用例落库）。代码级跟踪指数字段本端上游亦无=非缺口。
- **intl.fmt_maps row_kind ✅（2026-11-26 小修批）**：五源共用规范化补行种判别——
  `row_kind` ∈ `ccass/holder/rating/short/forecast`（各源签名键互斥按判别力排序，
  不命中=""；上游加源显式补分支不猜）；fmt_maps memo 缓存键 v2→v3；wmshare
  `market.intl.yaml` shape 同步。本地 kernel 六例断言全过（含空行=""）。
- **转债 ✅/登记**：发行要素核心 `cbond.board` 行已覆盖（规模/票息+分年票息表/
  期限/起息到期/上市日/转股期/赎回价/转股价）；「发行过程面」（中签率/老股东
  配售/网下发行/包销）上游无源=不做。转股价变动：**近 111 天窗口完整可还原**
  （event 行带 `convert_price_old/new/eff`+公告日+PDF；693 行中 61 条下修；
  history 台阶可见：三角转债 22.69→17.67），全历史无源（上游=90 文档滚动窗）
  →「转股价全历史变更序列」登记缺口。
- **复权口径声明修正（yaml notes + adj_factor docstring 已改，gen 全绿）**：
  live 实测推翻「美股 hfq 恒 1」旧声明——美股 after=历史快照（AAPL 因子
  ≈232.6、快照尾端 2026-03-13 不日更、快照窗口外 hfq 缺行→`adj_factor` 返空）；
  **港股 hfq 因子真实**（00700 累计 5.9453，ipo 起算）；港股 qfq 在无除权窗内
  =不复权（符合前复权语义），**跨除权窗已验 PASS（2026-11-26 实测 ≈7.2 万 EC）**：
  00700.HK 2026-01-01..11-25 全窗 221 根，qfq/nr 比值仅 {0.988483, 1.0} 两值，
  跳变边界=**2026-05-15 除权日**（05-14 nr 460.20 → qfq 454.90，扣减 ≈年度股息
  5.30），除权后 133 根恒 1.0（锚点=最新价）——qfq 跨除权真实调整、语义正确。
  与对面口径差：对面=前复权因子
  （close×factor=前复权价），本端=后复权累计（归一因子自行除以末值）。
- **期权：生产实证无源**——10 库集合名 opt 零命中、期货交易所枚举仅 6 家期货所
  （无期权市场）、上游接口文档 opt_* 标「待补未接线」。立项=全链路新采集
  （合约主档+日行情新 raw 源 → 新 catalog），排期另议。
- **历史分钟线：平台无档实锤**——datastore K 线族（日/周/月 × nr/qfq/hfq 分表）
  period 仅 `sampling_type=5` 日档、`*min*` 集合零命中；分钟只存 script 仓
  Redis memo（TTL 14 天、仅当日、30s 有损滚桶；设计文档明确「历史多日分时
  落库」为 non-goal；仅 HK 有收盘补桶 seal job，CN 无）；无任何积累 DAG。
  体量：CN ≈5,400 票 × 240 分钟 ≈130 万行/日（年 ≈3.2 亿行/市场）；
  **读面=日线 240 倍**（65-80 EC/行 → 单票单日 ≈1.6-2 万 EC，批量/全市场
  回放完全不可读，只可单票短窗）。路线：A=从今日起每日 seal 落库（CN 补
  seal job → airflow → datastore 新 catalog；14 天外无回补，越晚启动丢越多）；
  B=外购。均平台级，排期另议。

长线另立项（不入常规批次）：**期权** 与 **历史分钟线**——两者都是平台级工程，
本轮只立要点、不做实现；上游探针已于 2026-11-26 完成（结论见上节），排期另议。

- **期权（合约 / 行情 / 希腊字母）** 要点：
  - 上游：**已探针（2026-11-26）=无源实锤**（10 库 opt 零命中、期货交易所枚举无
    期权市场、上游文档 opt_* 标未接线）。立项=全链路新采集：合约主档（含到期/
    行权价/合约单位，定 symbol 编码规则）+ 日行情新 raw 源 → 新 catalog。
  - 数据量（粗估）：A 股 ETF 期权在挂合约约 1~3 千张/日，10 年 → 数百万至千万行级；
    商品期权另计。加合约主档（含到期/行权价/合约单位）。
  - EC：按行计费（60~75 EC/行），全历史单次拉取不可行 → 必须服务端物化 + 门面分页；
    隐含波动率/希腊字母若上游不给，自算需标的收盘 + 无风险利率 + 分红，属派生层工作。
  - 读面契约（草案）：`cli.option.contracts(underlying)`（在挂合约）、
    `bars(contract, n/begin/end)`、`chain(underlying, date)`（T 型报价 + IV）。
  - 阻塞点：无合约主档即无法定 symbol 编码规则，先探针。
- **历史分钟线** 要点（2026-11-28 P1 已落地，本条转为跟踪态）：
  - 上游：平台无历史分钟档（2026-11-26 探针实锤）；分时数据**每天在产生但从不
    落库**（memo TTL 14 天仅当日；HK 有补桶 seal、CN 无）。
  - **seal 路线定案 v3（2026-11-28，三次收敛后）**：XS store 写全通道 denied
    （adhoc 探针实证）→ b 安全组撤回（无鉴权 Redis 扩面+耦合内部信封）→
    上游分钟接口降兜底（读取权限已有但偏好不用）→ **定案：winmale 仓 Go maintenance
    handler**（`internal/sealmin1`，进程本就配置 memo Redis+存储 Mongo，
    `@maintenance:min1_seal_cn` 直调，`openapi_ec_weekly_topup` 先例）——零
    外购源、零安全组、零全局翻转。**分时语义=分钟收盘+量额累计（无 OHLC）**，
    读面差分沿用 9d4ec52 口径。
  - 存储（用户拍板：存储已切 V2，不建 V1 正表）：raw__min1/cn_kline_min 忠实
    日志（一键一日，可全量重建 V2）+ V2 `mkt.kline_min`/`mkt_kline_min` 读面
    （storage/v2 双写旁路；catalog 三件套已登记，check_v2_mapping 17↔17 PASS；
    不并入股票 kline 族——一行一文档 3.4 亿/年不可行的既有结论维持，票×日
    内嵌 ≤242 桶）。
  - 保留策略（已拍板）：滚动最近 1 年、无归档，稳态 ≈40 GB；TTL 机制 P1 设计项。
  - 状态（2026-11-28 当天发版闭环）：storage v1.0.166 / winmale 51966cd（test+prod
    已发）/ script 种子已入 cron（单 job 导入 `upserted=1 preserved_custom=407`）/
    airflow StatsCheck 已部署冒烟 PASS。管道已实弹验证：手动 trigger 全链 5.2s，
    首跑抓出 cnall symbols 文档数组 decode bug 当日修复；非交易日台账诚实记
    `sealed=0 missing=5695 bad=0`（5695 票 MGET 全部解信封成功）。**待周一首
    个交易日 15:40 自动实弹 + 10 交易日验收**（docs≈票数、V2 行数、幂等重跑）；
    读面 `cli.kline.min_bars` 后置 P3（units 台账锚点：量=股累计→差分、额=元）。
  - **历史回补定案（2026-11-28 spike 实测）**：2026-11-27（周五）全市场包已用
    `cmd/min1seal`（RunDay 目标日参数化）补档——5,695 票 raw+V2 双落（33.8s，
    missing=0）；更早深历史实测**无免费可行源**：上游分钟数据服务该档位限速
    1 次/小时（40203 实证，全市场回补数学上不可行）、站点直连 1 分钟仅近 5 个
    交易日、5 分钟仅 ~6 周。**可行路径=分钟数据服务升档位换频次**（升后全市场
    1 年 ≈33 万 calls，几小时~两周可拉完，写入时归一 seal bar 契约 +
    `source` 标记 + OHLC 附加字段）或**从 2026-11-27 起靠每日 seal 累积**。
    默认走后者（零成本），升档另议。
  - EC：单根 60~75 EC → 单票单日 ≈1.6-2 万 EC 维持原判；读面必须配额制 +
    memo 物化（P3 设计项）。不做实时推送（tick/WS 见不做清单）。
不做清单：LOF/场外/货基、游资名录/热榜/竞价明细、第三方源资金流变体、中信行业、
韩国宏观、组合 CRUD、tick、实时 WS 推送、DCE 仓单（反爬）。


## 目录重生成欠账（登记备忘，勿静默欠账）

- **`extract_from_scripts.py --check` 本地红（2026-11-26 登记）**：scripts 上游树自
  `upstream_rev 964affe0` 冻结后已前进（附注车道三函数、2026-10-19 车道切换等），
  `inventory.json` / `metrics.json` 漂移。**本次 4.4.0 未随带重生成**（4.4 是组合
  门面路线 B，不动目录；重生成会牵入上游新函数 → typed api/docs/计数基线/MCP
  路由全量级联，须独立发版窗口）。CI 无 scripts 树会自动 SKIP，本地红是唯一
  防线——下次发版前由维护者执行 `python tools/extract_from_scripts.py` 同步，
  并核对内部报表深研域的上游函数白名单（extractor 内常量）：附注三函数是否
  放行属产品决策，默认不放行——SDK 经 `cli.statements.notes` 组合门面消费，
  不直曝内部域函数名。
