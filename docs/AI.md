# 用 AI 学会并用好 wmshare

本页回答一个问题：**怎么让 AI（Claude Code、ZCode、Cursor、自建 agent…）第一次就写对
wmshare 取数代码**。优先用 MCP；没有 MCP 时用 skill 或文档上下文。

## 为什么这个 SDK 对 AI 友好

- **目录先行**：指标码与函数可编程检索（`cat.search("中文")`），AI 不需要"背"接口，
  查一下再用；编造的码在发请求前就被 `CatalogError` 拦下。
- **本地 MCP server**：20 个 task tools 覆盖发现、行情、财务、治理、披露、港美与批量；
  全部 135 个 friendly API（132 登记 + 3 组合接口）均可经 `wmshare_call(mode="api")` 兜底
  （macro 域 11 个接口仅此路径）。输出统一 units/rows/next_action。
- **skill 随包分发**：单位铁律、意图→接口决策树、坑位清单、错误速查，装进 agent 即生效
  （`wmshare.skill_dir()`）。
- **错误消息即修复指引**：401/403/429 的消息里就是申请与配置步骤，429 附批量续跑位置。
- **llms.txt**：仓库根的 AI 友好文档索引（[llms.txt 规范](https://llmstxt.org)），
  `llms-full.txt` 是全文拼接版，可直接投喂。

## 路径 A：MCP server（推荐，AI 直接调工具）

```bash
pip install "wmshare[mcp]"
wmshare-mcp setup --client-id <AppId> --client-secret-stdin --market cn
                                                        # 提示后粘贴 API Key
wmshare-mcp doctor && wmshare-mcp --check
```

客户端配置只写启动命令，不写密钥。JSON 型客户端：

```json
{"mcpServers":{"wmshare":{"command":"wmshare-mcp","args":[]}}}
```

TOML 型客户端：

```toml
[mcp_servers.wmshare]
command = "wmshare-mcp"
args = []
```

doctor 成功时看 `ok=true`、`credentials.configured=true`、`client_constructed=true`；失败时
`ok=false` 会给出凭证或 client 错误。零凭证仍可用 `wmshare_status`、`wmshare_search(kind="api")`、
`wmshare_contract(kind="api")` 发现合同；真实取数返回 `credential_required` 修复步骤，不静默降级。

Agent 工作流：

1. `wmshare_status` 看市场、凭证、目录和 capability coverage；
2. `wmshare_search` / `wmshare_contract` 找标的、函数、指标码、friendly API 与参数；
3. 高频意图优先用 20 个 task tools（statement、segments、dividend、estimates、corporate、
   market、intl、notice 等领域面都已 first-class 暴露）；
4. 多标的用 `wmshare_batch`；`params/raw/units` 会透传给 SDK `batch_iter`；
5. 长尾目录函数用 `wmshare_call(mode="catalog")`，长尾 friendly API 用
   `wmshare_call(mode="api")`；
6. 超限结果先读 `meta.next_action`，再改 `output=summary/count` 或缩小范围；
7. 429 时保留 `partial=true`、已完成结果、`resume_start`、`resume_symbols` 和
   `retry_after_seconds`，等待后续跑，不重试已完成部分。

429 响应关键字段示例：

```json
{"ok":false,"partial":true,"meta":{"resume_start":500,"resume_symbols":["600519"],"retry_after_seconds":3},"error":{"kind":"LimitError","code":"rate_limited"}}
```

## 路径 B：装 skill（无 MCP 时一条命令）

```bash
cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" ~/.agents/skills/wmshare
# 项目级按工具放入 .zcode/skills/ 或 .claude/skills/
```

装完无需再解释用法——AI 会在写代码前先查目录。验证方式（把这句话发给 AI）：

> 用 wmshare 帮我取 600519 近 30 根日 K，并给出 TTM 股息率与 PE 分位。

正确行为：先 `cat.search` 确认接口与指标码，再写 `cli.kline.bars("600519", n=30)` 与
`cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")`；涨跌幅/股息率/分位读小数
（0.0396 = 3.96%），不做二次换算。

## 路径 C：文档作上下文（无 skill / 无 MCP 的 agent）

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
   注意批量省的是请求次数不省 EC（开放 API 按计算量计费，多标的脚本按标的数
   逐票计价）——全市场最新快照类数据优先用服务端一次取数接口
   （如 cli.moneyflow.board()），大消耗看 BatchResult.ec_cost / cli.last_ec_cost；
4. 错误处理：捕获 WmshareError 并把消息原文打印/转述给我——消息自带修复步骤，
   DataError 是数据报警，不许静默吞掉。
凭证已通过 WMSHARE_CLIENT_ID / WMSHARE_CLIENT_SECRET 环境变量配置，
代码里用 wmshare.Client.from_env()，不要把密钥写进代码。
```

## 路径 D：报错驱动（零配置兜底）

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
| 把全市场塞进一次批量反复跑 | 请求次数省了，EC 按标的数逐票计价照全额扣——重放几百遍会打穿配额 | "最新快照类用 `cli.moneyflow.board()` 一次取数；确需逐票历史用 batch_iter 边取边落盘，别循环重放" |
| MCP 长结果塞爆上下文 | 后续推理变慢 | "改 `output=summary/count`，或缩小日期/标的范围" |
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
- **MCP 自检**：`wmshare-mcp --check` 零凭证校验 20 个工具注册；`wmshare-mcp doctor`
  额外检查凭证与市场配置；MCP resource `wmshare://coverage` 暴露能力矩阵。
- **编程自查**：`cat.search / cat.function / cat.metric / cat.symbols_search` 全部
  离线零额度，适合做 agent 工具调用前的静态校验。
