# 新增接口规范

本文是**操作手册**：新增或修改一个接口时，要动哪些文件、过哪些门禁、基线在哪里。
规范本体（契约条款）见 [../CONTRIBUTING.md](../CONTRIBUTING.md)，兼容与弃用见
[COMPATIBILITY.md](COMPATIBILITY.md)，硬限制见 [LIMITS.md](LIMITS.md)，代理视角摘要见
[../AGENTS.md](../AGENTS.md)。

两条约定贯穿全文：

1. **数字基线不写进文档**：域数/函数数/示例数/工具数等一律以各测试内的基线常量为准，
   本文只给出位置。写死即漂移——示例计数曾漂移两个目录代际才被发现，根治手法是
   让脚本从目录动态打印而非写死字面量。
2. **生成物一律重生成**：`docs/API.md`、`docs/fields.json`、`docs/openapi.json`、
   `docs/swagger.html`、`llms.txt`、`llms-full.txt`、`docs/INDICATORS.md`、
   `docs/ERRORS.md`、`docs/api_pack.json` 等全部由 `tools/gen_*.py` 产出，手改会被
   `--check` 门禁拦截；改源头后重跑生成器。完整门禁命令清单见 [../AGENTS.md](../AGENTS.md) 首节。

## 1. 先选路线：三种落地形态

| 路线 | 适用场景 | 最小文件集 | 参照范例 |
|---|---|---|---|
| **A 目录注册全量** | 新数据域，或服务端已有函数首次进目录 | 第 2 节级联表（最全） | `disc.income` 新域（rating/diagnose/calendar/decomp 四接口） |
| **B eval 组合门面** | 已有序列的组合暴露，不新增目录函数 | `src/wmshare/api/__init__.py` + `docs/API.md`（同提交重生成）+ `tests/test_api.py` | `index.members_history`：FRIENDLY_INDEX 按组合接口形态登记，合同（PIT 语义）写进 docstring，目录重生成顺延下次发版 |
| **C 变体** | 新 MCP 直达工具 / 新 CLI 动词 | 见 2.3 | MCP 直达层扩展、`wmshare` 主命令 |

拿不准时：**能走 B 不开 A**（组合面不动目录）；目录里没有的函数只能走 A。

## 2. 路线 A：目录注册全量级联

| # | 层 | 文件 / 动作 | 要点 |
|---|---|---|---|
| 1 | 目录源 | `src/wmshare/_catalog/domains/<域>.yaml` | 手写；字段语义见第 3 节；units/ranges/checks 非空声明；**域 version 需 bump** |
| 2 | 目录生成物 | `python tools/extract_from_scripts.py` | 重生成 `_catalog/generated/{inventory,metrics,metric_taxonomy}.json`，禁止手改 |
| 3 | 类型层 | `python tools/gen_typed_api.py` | `src/wmshare/api/_generated.py` |
| 4 | 门面层 | `src/wmshare/api/__init__.py` | FRIENDLY_INDEX 登记 + docstring 计数 + DOC_META（api_pack 暴露面） |
| 5 | 客户端 | `src/wmshare/client.py` | 薄路由；新错误码同提交登记 `tools/gen_errors.py` MEANINGS |
| 6 | 离线夹具 | `tests/replay_client.py` | 新门面须同步夹具（见第 7 节）；未拍摄面显式 `replay_unsupported` |
| 7 | MCP | `src/wmshare/mcp/apis.py` | 路由 + description（能力 + 实测 EC 档位）+ 可执行示例；如需直达工具另改 `tools.py`/`server.py`/`constants.py`（见 2.3） |
| 8 | docs 生成物 | gen_api_docs / gen_openapi / gen_indicators / gen_llms / gen_errors | API.md、fields.json、api_pack.json、openapi、swagger、INDICATORS、llms、ERRORS |
| 9 | 手写文档 | `README.md`、`docs/{README,AI,GUIDE}.md`、`src/wmshare/skills/wmshare/SKILL.md`（+`scenes/`） | 计数级联见第 6 节 |
| 10 | 示例 | `examples/NN_主题.py` + `examples/README.md` 课程表 + `tests/test_examples.py` 基线 | 约定见第 6 节 |
| 11 | 测试基线 | test_catalog / test_guard_baseline / test_audit_drift / test_mcp_apis | 见第 5 节 |
| 12 | live | `tests/test_live.py` + `tests/test_live_coverage.py` | 每个核心接口一条 live 冒烟 |
| 13 | 登记 | `docs/BACKLOG.md`、`CHANGELOG.md`、目录 upstream_rev 锚点 | 候选条目改为已上线；变更按版本段登记 |

### 2.3 路线 C 变体要点

- **MCP 直达工具**：一级工具数焊死在 `len(TOOL_NAMES)`（`tests/test_mcp_server.py`）；
  README「N 个 task tools」与 status caps 断言在 `tests/test_mcp_apis.py`；
  每个 action 枚举必须与 friendly 门面反射集等值（`tests/test_mcp_tools_matrix.py`）——
  路由映射到某工具后，该工具 action 枚举缺方法属真实缺陷（曾发生，靠等值断言拦截）；
  llms 随工具数变化重生成。
- **CLI 动词**：`pyproject.toml` entry point + README 命令行节（受行数预算约束）+
  `server.json`；argparse 子 parser 与顶层共享 namespace 会先填 defaults，布尔旗标须
  在子层显式 `default=SUPPRESS`（否则静默改写顶层参数走错客户端，实测耗过 EC）。

## 3. 目录 yaml 字段语义

schema：[../src/wmshare/_catalog/schema/domain.schema.json](../src/wmshare/_catalog/schema/domain.schema.json)，一域一文件。函数级关键字段：

| 字段 | 取值与规则 |
|---|---|
| `layer` | `L0`=原始行表 / `L1`=规范化辅助层（fmt_* 等，默认 `internal: true`） |
| `internal` | `true` 则不进任何门面属性直达；cron 专用函数必须标，不给 SDK 用户直调 |
| `checks` | 量纲检查器 id（`volume_amount` / `date_iso` / `diffp_ratio` 等，取值见既有域 yaml 用法）；引用未注册 id = ERROR |
| `ranges` | 字段量级界 `[min,max]`，**必须以实测分布为准，不凭空猜界**；`percent` 类声明必须配 ranges（缺即 ERROR） |
| `units` / `unit` | 字段级单位声明；偏离基础单位（率=小数/额=元/量=股）的码必须登记台账（第 4 节） |
| `normalize_with` | 指向 L1 规范化函数；声明与实现漂移由 `python -m tools.audit_units drift --strict` 拦 |
| `params` / `returns` | returns 用 shape/shape_ref 声明返回形态；字段级返回表只增不减（`FIELD_TABLE_MIN`） |
| `example` | 可绑定真实签名的示例（禁省略号占位；MCP 侧禁 `<REQUIRED>`） |

防编造链：`functions[].name` 必须能回溯 `generated/inventory.json`（`tools/validate_catalog.py`）；
上游新增 helper 未登记 → inventory 反向差集 FAIL，登记 `INTERNAL_HELPERS` 后重跑。

## 4. 单位台账（units.yaml）

- 默认口径铁律：**率=小数、额=元、量=股**全库默认。
- 偏离口径的指标码必须登记 `overrides`（`base_unit`/`native_unit`/`note`），
  必要时配 `invariants` 锚点；校验：`python tools/validate_units.py` +
  `tests/test_units_ledger.py`。
- `facades` 段是**运行时换算声明**（`ledger_convert` / `apply_facade_units` 消费），
  不是纯文档——改 token 即改行为。

## 5. 数据质量守护（ratchet 索引）

新增函数必须 units/ranges/checks **至少一项非空**——空声明刷分无效（`has_guard`
要求内容非空，`tools/guard_coverage.py`）；零守护域有白名单（`ZERO_GUARD_BASELINE`），
给白名单域加函数而无数值守护直接红。

| 测试 | 强制什么 | 基线位置 |
|---|---|---|
| `tests/test_catalog.py` | 域/函数/原始/计算/指标总数 | 文件内断言常量 |
| `tests/test_guard_baseline.py` | 守护覆盖率只许变好；漂移 ERROR 恒零、WARN 不增 | `ZERO_GUARD_BASELINE` / `DRIFT_WARN_BASELINE` |
| `tests/test_audit_drift.py` | 目录与声明分布基线 | 文件内基线常量 |
| `tests/test_interface_quality.py` | 标的参数命名契约（`symbol` 排第一，禁 `sym/stk`）；方法级 `:param` 债务只减；字段表只增；错误码双向登记；MCP `<REQUIRED>` 占位只减 | `PARAM_DOC_DEBT` / `FIELD_TABLE_MIN` / 占位 baseline 集合 |
| `tests/test_data_contract.py` | 数据契约 ratchet | 文件内基线常量 |
| `tests/test_mcp_apis.py` / `tests/test_mcp_server.py` | 一级工具数焊死；路由集=friendly 门面反射全集；目录函数总数 | 文件内断言 |

CI 另挂独立下限 `guard_coverage.py --min`：阈值以 `tests/test_guard_baseline.py` 基线为准，
收紧时同步 ci.yml 与 [../AGENTS.md](../AGENTS.md) 两处。

## 6. 文档齐全性（计数级联）

计数改动必须全量级联——漏一处即门禁红，或更糟：文档漂移门禁扫不到的地方
（examples/ 曾不在计数扫描面，漂移两个目录代际才被发现）。

| 面 | 互校点 |
|---|---|
| `README.md` / `docs/API.md` | 「N 个底层函数 / N 个核心接口 / N 个指标代码…」== 目录实时值（`tests/test_docs.py`） |
| `docs/GUIDE.md` / `docs/AI.md` / `docs/README.md` / QUICKSTART_EN / `server.json` | 历史计数黑名单（`test_docs_no_stale_counts`） |
| `src/wmshare/api/__init__.py` docstring | 「N 个底层函数」== 目录实时值 |
| `llms.txt` / `llms-full.txt` | 头部计数 + 每个组合方法在列（`tests/test_docs.py`）；体积预算（`tests/test_llms_budget.py`） |
| `src/wmshare/skills/wmshare/SKILL.md` | 文中每个 `cli.*` / `cat.*` 引用必须真实可绑定（`tests/test_skill.py`） |
| `tests/test_mcp_apis.py` | README「N 个 task tools」== 路由数 |

示例（`examples/`）约定：文件名 `NN_主题.py` 顺延最大编号；docstring 四行元信息
（前提/运行/学到/文档）；`def main(cli=None)` 统一 `Client.from_env()`（无凭证自动免注册免费试用）；
打印值带单位注释；新增后同步 `examples/README.md` 课程表 +
`tests/test_examples.py` 基线。**计数用动态打印代替写死字面量**，从根上消除漂移。

README 行数预算：上限以 `tests/test_docs.py::test_readme_is_lean` 断言为准；
长内容下沉 docs/，先删后提限。

## 7. 离线夹具纪律

demo 模式已随 3.0.0 移除（免注册试用替代其用户面职责）；CI 离线测试由
`tests/replay_client.py`（冻结回放夹具，数据 `tests/fixtures/replay_data.json`）承担：

- **同形**：live 门面每个形参夹具必须能接收（逐参比对，`tests/test_interface_quality.py`，
  例外只走白名单）；未拍摄面显式抛 `UsageError(code="replay_unsupported")`，消息指路
  `functions_by_domain()` / `Client.from_env()`——**绝不返回空结果冒充成功，
  绝不 TypeError 静默吞参**。新增门面/改签名必须同步夹具（新方法可显式报错，
  但参数表必须对齐）。
- **同向**：序列方向以接口合同为准——门面行表默认 date 升序（旧→新），但服务端
  trend 类序列的 `base`/`med` 是新→旧，取「当前值」用 `points[0]`。夹具与 live 必须
  同向，改夹具后断言方向（历史 bug：夹具升序生成、live 用 `pts[-1]` 取值，
  分位错位而测试全绿）。
- 夹具数据是**冻结产物**（字节级 SHA 锚在 `tests/test_replay_fixture.py`）：
  不再重拍；**不要**把夹具与当前 sdk_version 做耦合断言（版本必然随发版漂移）。

## 8. EC 成本档位实测

- **先 probe 再写模型**：新接口成本档位必须以生产 `metering.ec_cost` probe 实测为准，
  禁止拍脑袋；`estimate_cost`（`src/wmshare/client.py`）新增分支并在 note 注明实测日期。
- 没有成本模型的接口如实返回 `ec_lo=ec_hi=None`，不编造。
- 场景同步加进 `tools/audit_ec.py` 的 PANEL / HEAVY_PANEL 供后续对账（维护者工具，不进 CI）。
- **评估必须端到端**：memo 只覆盖取数，规范化（`fmt_maps` 逐行求值）是独立成本大头；
  「复跑变便宜」不等于「首次调用便宜」，冷热都要测。

## 9. 兼容与发版级联

- 公开面（签名/字段/单位/信封/异常 `code`）破坏性变更只能 MAJOR，按
  [COMPATIBILITY.md](COMPATIBILITY.md) 走弃用流程（窗口 ≥1 MINOR）；行为修正算
  MINOR，须在 CHANGELOG `Changed` 标注。
- 发版版本互校：六处版本源 + SECURITY 支持表（`python tools/check_version.py --check`）。
- CHANGELOG 对应版本段按模板写；`[Unreleased]` 恒空（`tests/test_changelog_section.py`）。
- **上游同步**：目录带 upstream_rev 锚点——上游仓未推送前不得先推本仓（外部会看到
  悬空 rev）；extractor 自动全收导致 `validate_catalog` 反向差集本地 FAIL 属预期，
  登记 `INTERNAL_HELPERS` 后重跑（CI 因上游不可见而 skip，本地红是唯一防线）。

## 10. 验收 checklist

### 路线 A（目录注册全量）

- [ ] 域 yaml 过 schema；units/ranges/checks 非空；ranges 界来自实测分布；域 version 已 bump
- [ ] 偏离单位的码已登记 units.yaml；`validate_units` + `audit_units drift --strict` 绿
- [ ] 目录生成物经 extract_from_scripts 重生成（未手改）
- [ ] gen_typed_api / gen_api_docs / gen_openapi / gen_indicators / gen_llms / gen_errors `--check` 全绿
- [ ] FRIENDLY_INDEX + DOC_META + client 薄路由 + `estimate_cost` 档位（实测）
- [ ] `tests/replay_client.py` 夹具同步（同形同向）；未拍摄面显式 `replay_unsupported`
- [ ] MCP 路由 + description（含实测 EC 档位）+ 可执行示例；新增直达工具则计数级联 + 枚举等值断言
- [ ] 计数级联全量（第 6 节表）；examples 课程表 + test_examples 基线
- [ ] test_catalog / test_guard_baseline / test_audit_drift / test_mcp_apis 基线同步
- [ ] live 冒烟入 test_live / test_live_coverage
- [ ] BACKLOG / CHANGELOG / upstream_rev 锚点登记
- [ ] [../AGENTS.md](../AGENTS.md) 门禁清单全绿（check_leak → … → pytest 全量）

### 路线 B（eval 组合门面）

- [ ] FRIENDLY_INDEX 组合形态登记；合同（PIT 等语义）写进 docstring 与 docs/API.md
- [ ] docs/API.md 同提交重生成；`tests/test_api.py` 用例
- [ ] 目录重生成顺延下次发版（登记备忘，勿静默欠账）

### 路线 C（MCP 工具 / CLI 动词）

- [ ] MCP：工具数级联（test_mcp_server / test_mcp_apis / README）+ 枚举等值断言 + llms 重生成 + 夹具同形
- [ ] CLI：pyproject entry point + README 命令行节 + server.json + 子 parser `default=SUPPRESS`

## 11. 已知缺口（登记不修复）

| 缺口 | 影响 | 处置 |
|---|---|---|
| 部分 ranges 用点路径键（嵌套字段），而审计匹配按行顶层 key——嵌套字段的量级界实际不生效，属装饰性合同 | guard 覆盖率计入但守护未真正执行 | 2026-11-23 成文登记；修复需改 `audit_units` / `guard_coverage` 两处匹配逻辑，另立任务 |

踩坑模式索引见 [../AGENTS.md](../AGENTS.md) 防坑清单（HIST_PCT 家族 key 绑定、
股息率无历史序列、序列方向、夹具/live 同向、预热缓存会冷、EC 只走既有范式、
能力对标优先于客户端砍量）。
