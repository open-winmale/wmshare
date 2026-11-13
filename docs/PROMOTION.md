# wmshare 推广执行手册（PROMOTION）

> 目的：把"外部曝光 P0"从策略变成团队 / agent 可直接勾选执行的清单。
> 配套策略文档见工作区 `wmshare-promotion-plan.md`（平台分层、量级反差、内容钩子论证）。
> 本文件只讲**做什么、去哪做、填什么、怎么衡量**。

---

## 0. 当前漏斗状态（已闭合，勿重复做功）

| 项目 | 状态 | 证据 |
|---|---|---|
| 版本一致性（GitHub / PyPI / CHANGELOG） | ✅ 已闭合 | PyPI = 1.19.0（2026-11-12 上传，`>=3.11`），与 tag / CHANGELOG 一致；release CI 自动发版 |
| 品牌拼写（仓库内） | ✅ 已干净 | 全仓无 `washare` 误拼；外部误拼仅存于站外旧文（不在本仓，需作者改） |
| MCP 官方 Registry | ✅ 已收录 1.19.0 | registry.modelcontextprotocol.io 搜 `wmshare` 最新 1.19.0（2026-11-12） |
| README 承接漏斗 | ✅ 完整 | 零凭证 `demo_client()` → 凭证配置 → `Client.from_env()`；口径数字一致（18 域 / 288 函数 / 2752 指标码 / 132 接口） |
| server.json | ✅ 当前 1.19.0 | 描述已含关键词（Python SDK / 2752 metrics / A-share HK US / AI agents） |

**北极星指标**：注册 → 取凭证 → 首次真实调用 → 7 日复用。`star` 只是信任信号，不追。

---

## 1. 渠道矩阵与逐站提交清单

### 1.1 MCP / Agent 目录（竞品≈0，优先级最高）

| 站点 | 入口 | 提交方式 | 关键字段 | 状态 |
|---|---|---|---|---|
| 官方 MCP Registry | registry.modelcontextprotocol.io | 随发版自动（已通） | server.json | ✅ 已收录 1.19.0 |
| Glama | glama.ai/mcp/servers → Add | 认领 / 提交 `io.github.open-winmale/wmshare` | name, description, repo | ✅ 已认领+构建通过+Release 0.1.0 已发布（2026-11-13；glama.json 声明维护者，Dockerfile 构建检查通过入搜索索引，Auto-Release 已开，Discovery score 33%→67%） |
| Smithery | smithery.ai → publish | 连 GitHub 或贴 server.json | command `wmshare-mcp`, transport stdio | ☐ 待提交 |
| mcp.so | mcp.so → add server | 提交仓库 URL | repo, readme | ☐ 待提交 |
| VS Code @mcp gallery | 市场内 @mcp | 经官方 Registry 自动同步 | — | ☐ 确认已同步 |
| Cline Marketplace | 其扩展内 MCP 市场 | PR 或提交 | server.json | ☐ 待提交 |
| LobeHub | lopehub.com/mcp | 提交 server | repo | ☐ 待提交 |
| awesome-mcp-servers | GitHub 仓库 PR | 加一行到 README 列表 | name + link + desc | ✅ PR 已发 punkpeye#19365（2026-11-13，待合并） |
| awesome-quant（GitHub 量化导航库） | wilsonfreitas/awesome-quant PR | Market Data & Data Sources 段首加一行 | `- [wmshare](url) - \`Python\` \`MCP\` - desc.` | ✅ PR 已发 wilsonfreitas#1014（2026-11-13，待合并） |

> 统一提交话术（描述字段直接复用 server.json 新描述）：
> "Python SDK wmshare local MCP server: offline catalog discovery, 2,752 server-precomputed A-share/HK/US metrics, and market-data tools for AI agents."

### 1.2 AI 助手技能市场（随包 skill 分发）

| 入口 | 动作 | 字段 | 状态 |
|---|---|---|---|
| Cursor | 复制 `wmshare.skill_dir()` 到 `~/.cursor/skills/` | SKILL.md 已随包 | ☐ 写一段安装 guide |
| Claude | 复制到 `~/.claude/skills/` | 同上 | ☐ |
| WorkBuddy | 技能市场 / 软链 `~/.workbuddy/skills/` | 同上 | ☐ |
| SkillHub | open.winmale.com/skillhub | 已在主站体系 | ✅ 37 skill 已装 |

### 1.3 中文开发者内容 + 选型 SEO

> 具体平台名不入库（leak gate 第三方禁词含若干中文社区名，字面提及即拦截），站名对照见工作区配套策略文档。

| 平台 | 内容形态 | 勾选 |
|---|---|---|
| 开发者内容站 A（技术社区） | 《A股数据 API 怎么选》横评 + 单点教程 | ☐ 草稿见工作区 `wmshare-comparison-article-draft.md` |
| 知乎 | 同主题回答 + "量化数据源踩坑" | ☐ |
| CSDN | 横评 + 快速上手 | ☐ |
| HelloGitHub | 月刊自荐 / 收录更新（旧数据 16 域 113 接口 → 18 域 288 函数） | ☐ 提更新 |
| GitCode | 镜像同步 + 收录信息更新 | ☐ |
| 开源中国 | 资讯 / 收录 | ☐ |

### 1.4 量化垂直社区（只讲工具与口径，不荐股）

| 社区 | 对口内容 | 勾选 |
|---|---|---|
| 集思录 | `cli.cbond` / `cli.workout` / A-H 折价一条链路图文 | ☐ |
| 量化平台 A（Python 回测社区） | 日更管线 notebook（服务端预计算省请求） | ☐ |
| 量化平台 B（券商系回测平台） | 接入教程 | ☐ |

### 1.5 自有资产互导

- [ ] 主站 25 应用 / 开放平台 12 文档 / SkillHub 37 skill 各加"Python 版（wmshare）"入口
- [ ] 4 个 org 仓库（wmshare / agent-skills / prism / wmshare-tools）互相链接
- [ ] QQ 群 `1127142074` 作为统一承接入口写进各平台 bio

---

## 2. 五个可复用内容钩子（零合规风险）

1. **「5,375 次请求 → 11 次」**——纯工程，适合 V2EX / 知乎 / 技术社区。
2. **「2,752 个指标码 vs 自己算十年分位」**——带真实耗时 / 请求数 / EC 的 benchmark。
3. **「0.25 变 25 会抛 `DataError`」**——静默错值叙事，生产用户最买账。
4. **「AI 写量化脚本为什么总编造函数名」**——离线目录 + `llms.txt` + MCP，蹭 Agent 热点。
5. **「可转债 / 要约套利一条链路出图文」**——集思录对口，纯方法论。

---

## 3. UTM 方案

- 主站：`https://winmale.com?utm_source=<渠道>&utm_medium=<平台>&utm_campaign=wmshare_p0`
- 开放平台：`https://open.winmale.com?utm_source=...`
- 每篇外发内容带独立 `utm_source`（juejin / zhihu / csdn / hellogithub / jisilu / jq），便于归因。
- 仓库内 `cb/article.py` 已有 `utm_source=wechat` 模板，新增平台时同步此处。

---

## 4. 转化漏斗指标（周报字段）

| 阶段 | 指标 | 采集点 |
|---|---|---|
| 曝光 | 各渠道阅读 / 点击 | 平台后台 + UTM |
| 安装 | PyPI 日下载（非镜像） | pypistats |
| 激活 | 凭证激活数 | 开放平台后台 |
| 复用 | 7 日留存 / 真实调用数 | 开放平台 EC 日志 |
| 口碑 | star / issues / 群新增 | GitHub + QQ 群 |

> 只看"曝光 → 安装 → 激活 → 7 日复用"为正且上升的渠道，砍掉无效项。

---

## 5. 90 天节奏

| 阶段 | 重点 | 交付 |
|---|---|---|
| 第 0–2 周（补漏） | 目录站认领/提交全跑一遍；横评草稿发布首篇；埋点就绪 | 一条可归因漏斗 |
| 第 3–6 周（铺渠道） | 每周 1 篇技术文（横评打底）；8 个 MCP/技能目录全提交；4 社区各 1 帖 | 每渠道独立 UTM |
| 第 7–12 周（沉淀） | 按转化砍无效；1 个可复现 notebook + 1 场答疑；高频 issue 反哺文档 | 首个"激活→7 日复用"基线 |

---

## 6. 护栏（硬约束，违反即撤）

- **合规判定 = "是否触及具体标的的买卖时点或仓位建议"**，不靠免责声明兜底。内容一律只讲工具 / 口径 / 方法论。
- **别讲成"免费无限"**：免费档 500 次/小时、5,000 次/日，且"批量省请求不省 EC"必须写清。
- 别追 star；别多平台原样复制同一篇（拼写错误就是这么扩散的）；版本名先对齐再投。
- 外部文章发布前核对：仓库内数字（18 域 / 288 函数 / 2752 指标码 / 132 接口 / 5375→11 请求）与 README 一致。
