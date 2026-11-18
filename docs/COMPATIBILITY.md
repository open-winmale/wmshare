# 兼容与弃用政策

本文是**对外承诺**：SDK 公开面怎么变、变之前给多久、怎么迁移。内部实现（私有函数、
缓存 key、脚本层实现）不在此列。

## 1. 适用范围

| 属于公开面（受本政策约束） | 不属于（可随时调整） |
|---|---|
| `cli.<ns>.<method>` 门面方法名与签名 | 以 `_` 开头的客户端选项实现细节 |
| `cli.call` / `cli.call_batch` / `cli.batch_all` 语义 | 服务端 XS 脚本内部函数 |
| 返回形态（DataFrame/信封/行数组）、字段名、单位、序列方向 | 预热缓存 key 与 TTL |
| 异常类型与 `code` 取值（见 [ERRORS.md](ERRORS.md)） | 日志文案、警告措辞 |
| 随包目录：目录函数名、指标码、`units.yaml` 声明 | demo 快照的具体数值（数据快照会重拍） |

数据契约（单位、方向、信封键名）与接口签名同级：改它们算 MAJOR。

## 2. 版本语义

| 版本位 | 允许的变更 | 例子 |
|---|---|---|
| **MAJOR** | 删除/重命名接口、返回形态变化、默认单位或序列方向变化、异常体系重构 | 2.0.0 废除 `_df`、序列改升序 |
| **MINOR** | 新增接口/字段/可选参数；**行为修正**（须在 CHANGELOG `Changed` 标注） | 2.0.0 新增 `cli.calendar`；2.1.0 新增 `valuation.daily_basic` |
| **PATCH** | 缺陷修复、文档/生成物同步、无行为变化 | 2.0.1 修 demo `cost_estimate` |

新增**可选**参数、返回**新增**列不算破坏性变更；删除列、改列义、改单位算。

## 3. 弃用流程（Deprecation）

1. **标记**：在 docstring 写 `.. deprecated:: x.y.z`，运行时触发
   `DeprecationWarning`（异常场景用 `UsageError(code="deprecated")`），消息里写明
   **替代写法**与**计划移除版本**。
2. **窗口**：至少保留 **1 个 MINOR 版本**（即标记版本的下一个 MINOR 之后才可移除）。
   窗口内新旧并存，结果必须一致。
3. **移除**：只能在下一个 **MAJOR**；同版本 CHANGELOG `Removed` + 迁移指南。
4. **例外**：安全漏洞或数据正确性缺陷可立即移除/改正，须在 CHANGELOG 明示原因。

## 4. 别名与迁移表

历史改名不静默丢弃，登记在此（新条目随弃用流程追加）：

| 旧写法 | 新写法 | 起始 | 状态 |
|---|---|---|---|
| `cli.call(..., _df=True)` | 门面默认 DataFrame；底层用 `_raw=True` 取原始行 | 2.0.0 | 已移除（调用即报 `UsageError`） |
| `cli.kline.bars(..., _df=False)` | 同上（`_df` 参数已废除） | 2.0.0 | 已移除 |
| `_units="native"` 之外的原生单位默认 | 默认基础单位（率=小数/额=元/量=股） | 2.0.0 | 已切换（逃生口 `_units="native"` / `native=True`） |

> 2.0.0 是无兼容负担的一次性大版本：全部破坏性变更集中在该版本，未做渐进弃用；
> 自 2.0.1 起按本文流程执行。

## 5. 变更公告模板（写入 CHANGELOG 对应版本段）

```markdown
### Added
- `cli.ns.method(...)`：一句话能力 + 关键参数 + 返回形态。

### Changed
- 行为变更：<接口> 从 <旧> 改为 <新>；影响面 <谁>；迁移：<一行代码>。

### Deprecated
- `cli.ns.old(...)`：原因；替代 `cli.ns.new(...)`；计划在 x.(y+1).0 移除。

### Removed
- `cli.ns.gone(...)`：移除版本与迁移路径（MAJOR 段才允许）。
```

## 6. 改动检查清单

任何触及公开面的 PR 必须同时更新（缺一即被门禁拦截）：

1. 目录 yaml（`src/wmshare/_catalog/domains/*.yaml`）与 `units.yaml`（如涉及单位）；
2. 六个生成物：`docs/API.md`、`docs/fields.json`、`docs/openapi.json`、
   `docs/swagger.html`、`llms.txt`、`llms-full.txt`、`docs/INDICATORS.md`
   （`tools/gen_* --check` 校验，禁止手改）；
3. `CHANGELOG.md` 对应版本段（按第 5 节模板）；
4. 测试：新行为用例 + 旧行为回归（弃用窗口内两者都要过）；
5. `tools/check_version.py --check` 六处版本一致。

回滚策略：发布后发现问题，优先**补丁版**修复；无法补丁的破坏性回退按 MAJOR 处理，
并在 CHANGELOG 说明影响面与替代方案。
