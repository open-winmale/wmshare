# AGENTS.md

给 AI 编码代理（Claude Code、ZCode、Codex…）的仓库工作约定。人类贡献者的唯一事实源是
[CONTRIBUTING.md](CONTRIBUTING.md)，本文件只是代理视角的摘要；两者冲突时以 CONTRIBUTING 为准。

## 门禁（提交前全部跑一遍，CI 同款）

```bash
python tools/check_leak.py            # 泄漏 / 竞品名 / 凭证字面量
python tools/validate_catalog.py      # 目录合同 + 防编造
python tools/extract_metric_taxonomy.py --check  # 指标适配层 sidecar 漂移
python tools/validate_metric_taxonomy.py         # sidecar 与 metrics.json 1:1
python tools/validate_units.py                   # 单位台账（手/亿元/百分数）
python tools/check_version.py --check  # 六处版本声明互校（含 SECURITY.md 表头）
python tools/guard_coverage.py --min 0.156  # 守护声明覆盖率下限
python -m tools.audit_units drift --strict  # shape/units/ranges 声明漂移（ERROR/WARN 均拦）
python tools/gen_api_docs.py --check  # 以下五个是生成物漂移门禁
python tools/gen_typed_api.py --check
python tools/gen_openapi.py --check
python tools/gen_llms.py --check
python tools/gen_indicators.py --check
python -m mypy
pytest -q --cov-branch                # 离线全量（行/分支覆盖率 ≥85%，CI 同款）
```

## 硬规则

- **先查已有指标，再写计算代码（最高优先级）**：任何指标/序列/分位，动手算之前必须先在
  `../script` 与 wmshare 里找「是否已有算好的」——`cat.search` / `cat.function` 查指标码，
  再到 `../script` 的 `sys/**` 与 `web_echo/**` 里找现成函数/预热缓存。**自己从头重算等于
  重复造轮子且口径必然漂移**（历史教训：绕过平台序列自算分位，把 2020 年的分位当今天用）。
  只有确认「没有」或「有但不可用」时才自己算，且必须在注释里写明理由。
- **先查目录再写代码**：指标码/函数名/参数一律 `wmshare.load()` 后
  `cat.search / cat.function` 确认，禁止凭记忆编造；
- **公开文档零竞品名、零导流话术**（CTA 禁词表见 `tests/test_docs.py::test_docs_no_ad_diversion_cta`，
  Gitee 内容风控会拦截导流类措辞，故全库执行）；
- **生成物不手改**：docs/API.md、docs/openapi.json、docs/swagger.html、llms.txt、
  llms-full.txt、docs/INDICATORS.md 由 `tools/gen_*.py` 生成——改源头后重新生成，
  漂移门禁会拦截手改；
- **README ≤330 行**（`test_readme_is_lean`）：长内容下沉 docs/，先删后提限；
- **新增示例**：`NN_主题.py` 编号进 examples/ 课程表，docstring 四行元信息
  （前提/运行/学到/文档），`main(cli=None)` 可注入，tests 端到端覆盖，并加进 examples/README.md 索引；
- **文档引用全部受门禁校验**：README/GUIDE/AI 里的 `cli.*` 调用、`$指标码`、`cat.*` 方法、
  域 id 必须真实存在；
- **凭证纪律**：密钥只走环境变量或 `~/.wmshare/credentials.env`，任何密钥字面量不得入库；
- 提交信息用 conventional 前缀（`feat:`/`fix:`/`docs:`/`chore:`）。

## 2.0 接口契约（破坏性变更已定版，新代码必须遵守）

- **返回形态**：门面（`cli.ns.method`）行表/序列默认 DataFrame（date 升序=旧→新；
  `_out()` 收口）；面板/时序组合面用统一信封 `{ok, as_of, data, meta}`；
  底层 `cli.call` 保持行数组。`_df` 已废除，`_raw=True` 是唯一原始口径逃生口。
- **单位**：率=小数/额=元/量=股全库默认；台账（units.yaml overrides/facades）是
  **运行时换算声明**（`ledger_convert`/`apply_facade_units` 消费），不是纯文档；
  新增偏离口径的码必须登记台账 + `validate_units` 锚点测试。
- **内部函数**：目录标 `internal: true`（fmt_* 等）不进任何门面属性直达；
  新增辅助函数默认标 internal。
- **新接口验收模板**：目录 yaml（units/ranges/checks 非空声明）→ FRIENDLY_INDEX →
  六 gen 再生成 → INDICATORS 锚点 → examples 课程表条目 → demo 同形（DF/升序/信封，
  未回放面显式 `demo_unsupported`）→ 计数级联（README/AI/GUIDE/SKILL/llms）。

## 防坑清单（都踩过，别再踩）

1. **HIST_PCT 家族丢 key 绑定**：`$PCT_PE_TTM_3Y/5Y/10Y` 在指数/行业键上**不按 key 区分**，
   返回的是求值会话 `$SYMBOL` 的分位。给指数/行业算分位必须从序列自算（`index.trend`）。
2. **股息率没有历史序列**：`$ID_BONUS_RATE_TTM` 只能取当前值，`indices.valuation` 的 series
   只有 `d/pe/pb`。任何「股息率分位」都是造假。
3. **序列方向**：服务端 `indices.trend` 的 `base`/`med` 是**新→旧**（cursor.ds 顺序）。
   取「当前值」用 `points[0]`；`reversed(points)` 拿到的是最旧点（历史 bug 根因）。
4. **demo 与 live 必须同向**：`_demo.py` 曾按升序生成、用 `pts[-1]`，与 live 相反，
   导致 1143 个测试全绿也没抓到分位错位。改 demo 后要断言方向。
5. **预热缓存会冷**：`m_valtrend_series:v1:{key}` 依赖 cron。未命中的键必须优雅降级
   （显式标「缓存未命中」），不能当 0 或静默给错值。
