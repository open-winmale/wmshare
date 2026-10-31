# 用 AI 学会并用好 wmshare

本页回答一个问题：**怎么让 AI（Claude Code、ZCode、Cursor、自建 agent…）第一次就写对
wmshare 取数代码**。三条接入路径按成本从低到高排列，任选其一或叠加。

## 为什么这个 SDK 对 AI 友好

- **目录先行**：指标码与函数可编程检索（`cat.search("中文")`），AI 不需要"背"接口，
  查一下再用；编造的码在发请求前就被 `CatalogError` 拦下。
- **skill 随包分发**：单位铁律、意图→接口决策树、坑位清单、错误速查，装进 agent 即生效
  （`wmshare.skill_dir()`）。
- **错误消息即修复指引**：401/403/429 的消息里就是申请与配置步骤，429 附批量续跑位置。
- **llms.txt**：仓库根的 AI 友好文档索引（[llms.txt 规范](https://llmstxt.org)），
  `llms-full.txt` 是全文拼接版，可直接投喂。

## 路径 A：装 skill（推荐，一条命令）

```bash
cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" ~/.agents/skills/wmshare
# 项目级按工具放入 .zcode/skills/ 或 .claude/skills/
```

装完无需再解释用法——AI 会在写代码前先查目录。验证方式（把这句话发给 AI）：

> 用 wmshare 帮我取 600519 近 30 根日 K，并给出 TTM 股息率与 PE 分位。

正确行为：先 `cat.search` 确认接口与指标码，再写 `cli.kline.bars("600519", n=30)` 与
`cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")`；涨跌幅/股息率/分位读小数
（0.0396 = 3.96%），不做二次换算。

## 路径 B：文档作上下文（无 skill 机制的 agent）

把以下材料之一放进 system prompt / 项目上下文（按上下文预算从大到小）：
`llms-full.txt`（全文）→ `README.md + docs/GUIDE.md` → `docs/GUIDE.md + docs/API.md`。

可直接复制的提示词模板：

```text
你将帮我用 wmshare（Python 财经数据 SDK，覆盖 A/港/美）写取数与分析代码。规则：
1. 目录先行：任何指标码/函数名/参数先查离线目录（wmshare.load() 后 cat.search /
   cat.function），禁止凭记忆编造；
2. 单位铁律：比率/涨跌幅/分位一律小数（0.0396 = 3.96%、0.42 = 42% 分位），金额=元、
   量=股，不要做二次换算；cli.screener 宽度接口的 *_pct 例外，是百分数数值；
3. 批量铁律：多标的取数用 cli.batch_all / cli.batch_iter（自动分批，A 股 5,691 家
   只发 12 次请求），绝不写 for 循环逐票请求；一个批次只能同一个市场；
4. 错误处理：捕获 WmshareError 并把消息原文打印/转述给我——消息自带修复步骤，
   DataError 是数据报警，不许静默吞掉。
凭证已通过 WMSHARE_CLIENT_ID / WMSHARE_CLIENT_SECRET 环境变量配置，
代码里用 wmshare.Client.from_env()，不要把密钥写进代码。
```

## 路径 C：报错驱动（零配置兜底）

没有凭证、只想验证 AI 写的调用语法？用 `wmshare.demo_client()`——随包离线演示客户端（2026-10-30 真实 API 固定快照，非实时数据），调用面覆盖公开示例：让 AI 先在演示客户端上跑通代码形态，再接真实凭证取数。

错误消息本身就是为了"贴给 AI 能直接修"设计的：

| 看到的报错 | 消息里已包含 | AI 能直接做的事 |
|---|---|---|
| `AuthError` 401/403 | 申请 AppID 的步骤与三种配置方式 | 引导你配置凭证 |
| `LimitError` 429 | 已完成标的数与 `codes[done:]` 续跑切片 | 改写成 `batch_all(name, codes[done:])` 续跑 |
| `CatalogError` | "查目录"提示 | `cat.search` 找到正确码后重写 |
| `UsageError` | 参数合同出处（`cat.function()["params"]`） | 按合同修正参数名/类型 |

把 traceback **原样**贴给 AI（不要只截图摘要），这是成本最低的排障路径。

## AI 常见错误对照表

| AI 容易犯的错 | 后果 | 给 AI 的纠正指令 |
|---|---|---|
| 凭记忆编造指标码 | `CatalogError` | "先 `cat.search` 确认码存在，再写取数代码" |
| 把小数又 ×100 | 全部数值错 100 倍 | "返回值已是小数，展示时才格式化成百分比" |
| `for code in codes:` 逐票请求 | 全市场必撞 429 | "改 `cli.batch_all(name, codes)`，5,691 家=12 次请求" |
| 一个批次混 A 股与港股 | 数据静默错误 | "一个 Client 只服务一个市场，分三次跑（共 29 批）" |
| try/except 吞 `DataError` | 错误量级入库 | "DataError 是数据报警，先看消息再决定" |
| `up_pct` 当小数 | 差 100 倍 | "宽度接口的 `*_pct` 是百分数数值（80.3 = 80.3%）" |

自查一行命令（验证 AI 写的指标码是否存在）：

```bash
python3 -c "import wmshare; print(wmshare.load().metric('\$PE_TTM_LAST'))"
```

## 凭证安全（AI 协作红线）

- 密钥只放环境变量或 `~/.wmshare/credentials.env`（`.gitignore` 已覆盖 `.env`）；
- **不要**把 API Key 粘贴进对话、代码、issue 或让 AI 写死在脚本里；
- AI 只需要知道"凭证已配置"——代码统一 `wmshare.Client.from_env()`；
- 怀疑泄漏时到开放平台重置 API Key。

## 进阶

- **全文投喂**：`llms-full.txt`（README + 指南 + AI.md + API.md 拼接）适合大上下文
  agent；`llms.txt` 是带注释的链接索引，适合按需抓取。
- **skill 源文件**：`wmshare.skill_dir()` 返回随包路径，可直接读 `SKILL.md` 原文
  （不装目录、只要 AI 读一遍也有效）。
- **编程自查**：`cat.search / cat.function / cat.metric / cat.symbols_search` 全部
  离线零额度，适合做 agent 工具调用前的静态校验。
