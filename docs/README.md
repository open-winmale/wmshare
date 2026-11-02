# 文档导航

wmshare 的文档按「教程 / 怎么做 / 参考 / 解释」四层组织
（[Diátaxis](https://diataxis.fr/) 文档框架），各层不混写。
按你的目标选入口：

| 我想… | 去哪 | 说明 |
|---|---|---|
| 5 分钟装好并跑通第一行 | [README](../README.md) | 店面：特性、安装、选股实战（真实数据）、凭证、离线演示 |
| 系统学一遍（可运行课程） | [examples/](../examples/README.md) | 12 个编号示例：离线优先、CI 全覆盖、输出带单位注释 |
| 完成某个具体任务 | [GUIDE.md](GUIDE.md) | 单票菜谱、全市场与行业、批量绕 429、多市场、pandas、公告订阅 |
| 查某个接口的参数与返回 | [API.md](API.md) | 116 个核心接口参考（生成物，随目录合同更新）；机器可读 [openapi.json](openapi.json) / [swagger.html](swagger.html) |
| 理解设计口径 | GUIDE · [核心概念](GUIDE.md#2-核心概念) | 双层 API、目录先行、单位铁律、限流模型 |
| 排查报错 | GUIDE · [故障排查](GUIDE.md#9-故障排查) | 错误家族表 + 按症状查 |
| 让 AI 正确使用本 SDK | [AI.md](AI.md) | MCP server / 装 skill / 文档作上下文 / 报错驱动；提示词模板与安全红线 |
| 给 AI 投喂全文 | [llms.txt](../llms.txt) · [llms-full.txt](../llms-full.txt) | AI 友好索引与全文拼接（生成物） |

## 五个高频任务：直接抄可运行的

| 任务 | 可运行示例 | 文档章节 |
|---|---|---|
| 筛高股息且派息可持续 | `examples/05_dividend_screener.py --demo` | GUIDE · 单票菜谱 |
| 看估值贵不贵（历史分位） | `examples/06_indicator_tour.py --demo` | GUIDE · 单票菜谱、核心概念 |
| 扫均线 / 全市场涨跌宽度 | `examples/04_screener.py --demo`、`examples/08_pandas_analysis.py` | GUIDE · 单票菜谱、pandas |
| 监控公告变更 | `examples/10_notice_monitor.py --demo` | GUIDE · 公告变更订阅 |
| 拉三大财务报表 | `examples/11_statements_tour.py --demo` | GUIDE · 单票菜谱 |
| 接入 AI MCP client | `examples/12_mcp_server.py` | README · MCP server、AI · MCP 路径 |

## 阅读路径建议

- **数据分析新手**：README 选股实战 → `examples/01→04→05` → GUIDE 单票菜谱 → GUIDE 故障排查
- **全市场/工程化用户**：GUIDE 第 5 章（批量）→ `examples/07、08` → GUIDE 配额实测
- **AI agent 开发者**：AI.md → `examples/09` / `examples/12` → 装 skill 或 MCP server → GUIDE 当参考

## 维护约定

- API.md / openapi.json / swagger.html / llms*.txt 是生成物：改 `tools/gen_*.py` 后重新生成，
  漂移由 CI 门禁拦截，不手改；
- 公开文档零竞品名、零导流话术（check_leak 与 test_docs 门禁强制）；
- 新示例必须带编号进课程表并在 tests 里端到端覆盖（约定见 [examples/README](../examples/README.md)）；
- 贡献流程见 [CONTRIBUTING](../CONTRIBUTING.md)，安全披露见 [SECURITY](../SECURITY.md)。
