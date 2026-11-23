# examples：可运行示例（渐进式课程）

**编号即学习路径**：每个脚本独立可跑；输出里的数值都带单位注释——读输出就能学会
「率/分位=小数（0.0396 = 3.96%）、金额=元、量=股」的基础口径。
22 个示例的测试策略：4 个纯离线在 CI 里子进程真实执行（02/03/09/12）；其余在 CI
注入离线回放夹具端到端跑 `main(cli)`（签名/输出不回退）；20 号需服务端开启匿名
试用（未开启时优雅降级）。运行时统一 `main(cli=None)`，无凭证自动回落匿名试用。
可放心照抄。

## 运行

```bash
pip install wmshare                    # 仓库开发：pip install -e .
python examples/01_quickstart.py       # 无凭证自动匿名试用（免注册、真实数据、需网络）
export WMSHARE_CLIENT_ID=... WMSHARE_CLIENT_SECRET=...   # 长期额度：配置自己的凭证
```

- **零凭证可跑**（不联网）：`02_catalog_tour`、`03_error_handling`、`09_ai_skill_setup`
- **零凭证可跑**（联网，自动匿名）：其余全部——真实数据、免费额度、免注册
- **依赖**：pandas 自 2.0 起是核心依赖，无需额外 extra（`08_pandas_analysis` 直接用）

## 课程表

| # | 脚本 | 阶段 | 前提 | 学到什么 | 对应文档 |
|---|---|---|---|---|---|
| 01 | `01_quickstart.py` | 入门 | 匿名/凭证 | 行情/财务/披露/参考四类取数一次过；批量绕开 429 | GUIDE·单票菜谱、批量取数 |
| 02 | `02_catalog_tour.py` | 入门 | **离线** | 目录先行：`cat.search`、函数合同、指标组（防臆造） | GUIDE·核心概念 |
| 03 | `03_error_handling.py` | 入门 | **离线** | WmshareError 家族、按类型分支、code/status 程序化处理 | GUIDE·故障排查 |
| 04 | `04_screener.py` | 进阶 | 匿名/凭证 | 全市场条件选股（一条表达式，count=真命中数）；涨停/均线/放量单票筛选；全景/分桶/涨跌榜；`*_pct` 百分数例外 | GUIDE·单票菜谱 |
| 05 | `05_dividend_screener.py` | 进阶 | 匿名/凭证 | 分红质量筛选；call_batch 票级批量；底层函数属性直达 | GUIDE·单票菜谱 |
| 06 | `06_indicator_tour.py` | 进阶 | 匿名/凭证 | 指标码体系：`cat.search`→分位/TTM→`hist_stats`，小数读法 | GUIDE·核心概念 |
| 07 | `07_stocks_industry_batch.py` | 生产 | 匿名/凭证 | 全市场列表→行业成分→batch_all/batch_iter/call_batch 三入口分工 | GUIDE·批量取数 |
| 08 | `08_pandas_analysis.py` | 生产 | 匿名/凭证 | 门面默认 DataFrame（date 升序）：MA20/动量/资金流/分红表 | GUIDE·pandas |
| 09 | `09_ai_skill_setup.py` | AI | **离线** | skill 自检与装入 agent；AI 正确行为的验证标准 | AI.md（全文） |
| 10 | `10_notice_monitor.py` | 进阶 | 匿名/凭证 | 公告轮询器：poll_now 手动一轮、ack/at-least-once、seek_oldest 重置 | GUIDE·公告变更订阅 |
| 11 | `11_statements_tour.py` | 进阶 | 匿名/凭证 | 三大报表科目行结构、合并 vs 母公司（diffp 小数）、审计意见 | GUIDE·单票菜谱 |
| 12 | `12_mcp_server.py` | AI | **离线自检** | `wmshare-mcp` 安装自检、凭证写入、最小 MCP 配置、29 个工具入口与 friendly API 兜底 | README·MCP server、AI·MCP 路径 |
| 13 | `13_futures_macro.py` | 进阶 | 匿名/凭证 | 期货主力指标码（fut_symbol 换合约/外盘）、宏观时序与中债收益率（原生口径） | GUIDE·§6.1、API·期货/宏观章 |
| 14 | `14_cbond_double_low.py` | 生产 | 匿名/凭证 | 前半手工算双低（board 原始字段，看清在市口径）；后半 `cbond.daily()` 一条链路出事实包 + `article()` 成稿 + `figures()` 出图；缺条目即抛错不补猜测值 | GUIDE·单票菜谱·可转债、docs/notebooks/cb_double_low.ipynb |
| 15 | `15_backtest_ma.py` | 进阶 | 匿名/凭证 | 单股均线买卖点回测：逐笔成交明细（买/卖、费用、盈亏、持有天数）+ 净值/回撤汇总；固定口径次日开盘、T+1、整手 | GUIDE·单票菜谱·单股回测 |
| 16 | `16_metric_adapter.py` | 进阶 | 匿名/凭证 | 指标适配层：scope/topic 找码、combinable_groups 看组合边界、table 长表、many 小列表多标的 | docs/METRIC_ADAPTER.md |
| 17 | `17_prr_dividend_screen.py` | 生产 | 匿名/凭证 | 三维红利排雷：硬卡点全压一条 where（count=真命中数）→ 本地剔金融、现金流覆盖、PRR 分位与 CHI 排名 | GUIDE·单票菜谱 |
| 18 | `18_calendar_margin.py` | 2.0 新面 | 匿名/凭证 | 交易日历（回测窗口前置）+ 市场级两融汇总（杠杆水位）+ 标的名单资格判定 | API·market.calendar / market.margin |
| 19 | `19_income_rating.py` | 2.5 收息场景 | 匿名/凭证（收息面依赖 cron 物化） | 收息流闭环：全市场排行（四维评分）→ 批量诊断 → 分红日历 → N 年拿息拆解；COLD_CACHE 与批量纪律 | API·disc.income / dividend.rating·diagnose·calendar·decomp |
| 20 | `20_anonymous_trial.py` | 匿名试用 | 需服务端开启匿名试用（未开启时打印注册指引） | `Client.anonymous()` 免注册取真实数据；匿名额度边界与升级路径 | README「零凭证先试」 |
| 21 | `21_cli_export.py` | 成品出口 | 匿名/凭证（xlsx 需 `wmshare[excel]`） | `wmshare.export` 三件套：`to_markdown`（as_of+单位口径表头）、`write` 按扩展名分派、`write_bundle` + manifest.json；命令行同能力见 README「不写 Python」节 | README·命令行出成品 |
| 22 | `22_futures_bars.py` | 2.9 期货新面 | 匿名/凭证 | `futures.bars` 与 kline.bars 同形（date=周期起点/升序/DF）、日频只含交易日、周/月线=上游周期 bar、begin/end 与 n 二选一、按行计费先估后取 | GUIDE·§6.1、API·期货章 |
| 23 | `23_fx_reserves.py` | 3.0 外汇与储备新面 | 匿名/凭证 | `fx.rate/history/list` 的「每 1 单位外币」口径（上游每 100 外币已 /100）、中间价 vs 中行牌价、`macro.reserves*` 值=美元数值且黄金为市值口径、SDR 无生产者如实标注 | GUIDE·§6.2、API·宏观章 |
| 24 | `24_us_macro.py` | 3.1 美宏观新面 | 匿名/凭证 | 主题树零取数成本、中文检索、`series_meta().units` 是唯一口径来源（GDP 十亿美元 / UNRATE 百分数 / PAYEMS 千人）、点序列 date 升序且空值不补 0、需授权序列 has_data=False | GUIDE·§6.2、API·宏观章 |
| 25 | `25_limit_price.py` | 3.1 涨跌停价新面 | 匿名/凭证 | 规则价=前收盘×(1±带宽) 四舍五入到分；带宽只看代码号段（30x/68x=20%、北交所=30%、其余=10%）；收盘价==规则价即当日封板；rule=unbounded/delisting 时价格为空不猜 | GUIDE·§6.1、API·证券与行业基础章 |
| 26 | `26_board_moneyflow.py` | 3.1 板块资金流新面 | 匿名/凭证 | 三源（ths 概念/行业、dc 概念+行业）各成体系不跨源映射；额=元（THS 原值亿元已换算）、率=小数、板块指数=点位；单日榜按主力净额降序；ths 有买卖总额、dc 有四档单量，缺失为空 | GUIDE·§6.1、API·板块资金流章 |
| 27 | `27_block_trade.py` | 3.1 大宗交易新面 | 匿名/凭证 | 行内只有证券代码（名称需 join stocks/info）；额=元、量=股（上游万元/万股已换算）；单日榜成交额降序、单票历史 date 升序；同票同日多笔各一行；成交额≈价×量可自检 | GUIDE·§6.1、API·大宗交易章 |
| 28 | `28_stock_lifecycle.py` | 3.3 ST/停复牌史新面 | 匿名/凭证 | 停复牌按交易日（S/R）、简称变更按生效日；ST 判定=简称含 ST（覆盖 *ST/SST）；lifecycle 合并派生 rename/st_enter/st_exit/suspend/resume，日期升序；不含上市/退市事件 | GUIDE·§6.1、API·证券与行业基础章 |
| 29 | `29_concept_tags.py` | 3.3 概念标签新面 | 匿名/凭证 | 概念标签=索引物化数组（$CONCEPT_TAGS，去 s: 前缀）；含指数/风格标签不做分流；concept_members 名称包含匹配、代码升序；当前截面无 PIT 历史，不能回测历史成份 | GUIDE·§6.1、API·板块章 |

## 约定（新增示例请遵守）

- 文件名 `NN_主题.py`（两位编号，接在现有最大编号后）；
- docstring 固定四行元信息：**前提 / 运行 / 学到 / 文档**；
- 骨架 `def main(cli=None)` + `__main__` 捕获 `WmshareError` 打印原文（消息自带修复步骤）；
- 客户端统一 `main(cli=None)` 内 `wmshare.Client.from_env()`（无凭证自动匿名试用）；
  离线测试注入回放夹具或打桩客户端（见 `tests/test_examples.py`）；
- 打印值带单位注释；新增后同步本表，并在 `tests/test_examples.py` 加对应测试（CI 会拦截漏网的示例）。
