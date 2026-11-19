# 贡献指南与项目规范

感谢关注 wmshare。本文件同时是**内容规范**：违反任一条会被 CI 门禁拦截。

## 2.0 接口契约（改接口前必读，破坏性变更已定版）

- **返回形态**：门面（`cli.ns.method`）行表/序列默认 pandas DataFrame（date 升序=旧→新，
  统一经 `to_output_frame` 收口）；面板/时序组合面用统一信封 `{ok, as_of, data, meta}`；
  底层 `cli.call` 保持规范化行数组。`_df` 参数已废除；`_raw=True` 是唯一原始口径逃生口。
- **单位**：率=小数/额=元/量=股全库默认。`units.yaml` 的 overrides/facades 是**运行时
  换算声明**（`ledger_convert` / `apply_facade_units` 消费），不是纯文档；新增偏离口径
  的码必须登记台账 + `test_units_ledger` 锚点。
- **内部函数**：目录标 `internal: true` 的辅助（fmt_* 等）不进任何门面属性直达；
  新增内部辅助默认标 internal。
- **新接口验收**：目录 yaml（units/ranges/checks 非空）→ FRIENDLY_INDEX → 六 gen 再生成
  → INDICATORS 锚点 → examples 课程表条目 → demo 同形（DF/升序/信封；未回放面显式
  `demo_unsupported`）→ 计数级联（README/AI/GUIDE/SKILL/llms/docs/README）。

## 提交前门禁（全部必须通过）

```bash
python3 tools/check_leak.py         # 内容规范扫描（见下）
python3 tools/validate_catalog.py   # 域目录合同 + 防编造回溯
python3 tools/extract_metric_taxonomy.py --check  # 指标适配层 sidecar 漂移
python3 tools/validate_metric_taxonomy.py         # sidecar 与 metrics.json 1:1
python3 tools/validate_units.py                   # 单位台账（手/亿元/百分数）
python3 tools/check_version.py --check  # 六处版本声明互校（含 SECURITY.md 表头）
python3 tools/guard_coverage.py --min 0.203333  # 守护声明覆盖率下限（防回退；阈值以 tests/test_guard_baseline.py 基线为准）
python3 tools/gen_api_docs.py       # 重生成 docs/API.md + docs/fields.json（改了目录必须重跑）
python3 tools/gen_typed_api.py      # 重生成类型化门面 docs 同源
python3 tools/gen_openapi.py        # 重生成 docs/openapi.json + swagger.html
python3 tools/gen_llms.py           # 重生成 llms.txt / llms-full.txt（AI 分发面）
python3 tools/gen_indicators.py     # 重生成 docs/INDICATORS.md + docs/indicators/（逐码单页）
python3 tools/gen_errors.py         # 重生成 docs/ERRORS.md（错误码字典）
python3 tools/gen_data_calendar.py  # 重生成 docs/DATA_CALENDAR.md（需兄弟仓 airflow）
python3 tools/gen_changelog_feed.py # 重生成 docs/changelog.xml（RSS 变更公告）
pytest --cov=wmshare --cov-branch --cov-fail-under=85   # 全部测试（不联网）+ 行/分支覆盖率门禁
python3 -m mypy                     # 类型检查
```

真实取数冒烟（需要凭证）：`WMSHARE_LIVE=1 pytest tests/test_live.py`——覆盖全部
`FRIENDLY_INDEX` 核心接口与多个标的，做数值合理性断言（日期有序、价格为正、率类口径等）。
需要已配置的凭证（WMSHARE_* 环境变量或 ~/.wmshare/credentials.env）。

文档一致性由 `tests/test_docs.py` 强制：API.md 的参数/示例/指标组/附录与目录逐项比对，
README 代码块真实执行，README 引用的指标代码与接口必须存在，docstring 单位口径必须与
目录一致。改了文档或接口后直接跑 pytest 即可发现不一致。

CI（`.github/workflows/ci.yml`）在每次 push/PR 上跑同样的门禁。

## 内容规范（check_leak 强制）

1. **禁止第三方产品/数据商引用**：不得出现任何第三方数据产品、数据商或竞品名称
   （包括对标措辞、数据来源点名、商标）。描述数据来源使用中性词（"交易所披露"、
   "平台数据源"等）。新增禁用词在 `tools/check_leak.py` 的 `THIRDPARTY_RE` 维护。
   **公开文档零竞品名**：README 由测试断言禁止出现任何竞品名（差异化卖点一律自证式
   表述，防回潮）；CHANGELOG 允许保留历史对比记录（豁免面见 `tools/check_leak.py` 的 `THIRDPARTY_SKIP` / `THIRDPARTY_SKIP_PREFIXES`）；
   其余名称、其余位置一律禁止。
2. **禁止内部信息**：内网域名、基础设施路径、开发者机器路径、凭证字面量。
3. **文档白名单**：对外文档只允许 README / LICENSE / CONTRIBUTING / SECURITY / CHANGELOG /
   MAINTAINERS / GOVERNANCE / CODE_OF_CONDUCT / docs/API.md / examples
   （机器可执行版见 `tools/check_leak.py` 的 `ALLOWED_PATHS`）。
   方案、计划、路线图、内部流程文档一律不入库（Roadmap 类内容放 GitHub Discussions）。
4. **凭证纪律**：用户凭证只走环境变量或 `~/.wmshare/credentials.env`（gitignore 已覆盖
   `.env`），任何密钥字面量不得出现在代码、测试、文档中。
   `check_leak.py` 的 `FORBIDDEN_SUBSTRINGS` 中列为禁用——任何跟踪文件出现明文即 FAIL。

## 数据域与接口规范

- **随包目录是维护者同步的发布物**：`generated/` 清单由维护者从上游数据平台
  同步冻结（`tools/extract_from_scripts.py`，含命名空间白名单、文本净化与指标
  策展过滤）。贡献者**无需也无法**自行重建目录；新增数据域或指标请提 issue，
  由维护者评估后同步。发布的是上游指标的**策展子集**，README 与文档表述保持一致。
- 新增/修改数据域：在 `src/wmshare/_catalog/domains/<域>.yaml` 操作，必须
  bump 域 `version`（semver），并通过 `validate_catalog.py`（函数/指标码必须可回溯到
  `generated/` 清单，防编造）。
- 生成物 `src/wmshare/_catalog/generated/*.json` **禁止手改**：由维护者用
  `tools/extract_from_scripts.py` 从上游同步（含命名空间白名单与文本净化策略）。
- 友好 API（`src/wmshare/api/` 包）改动必须同步 `FRIENDLY_INDEX` 注册表
  （`tests/test_api.py` 强制两者一致），方法首参统一 `symbol`。
  **例外**：组合门面（`COMPOSITE_METHODS`，如 `etf`/`cbond`/`backtest`/`statements`）
  底层是跨接口封装、无单一目录函数，不进 `FRIENDLY_INDEX`。
- **组合门面准入规则**（护栏 6）：仅当能力**不在目录且无法经维护者同步**时才用
  组合门面；**数值口径类必须配套本地守护**（量级/不变量校验抛 `DataError`），
  并补文档注册（签名/返回说明/示例）与每 view 的离线 + live 测试。
  当前 `etf` 门面是过渡态（`etf_build` 九视图在 `xs/skillhub/`，不在 catalog 扫描面），
  满足目录化条件（能力进 `sys/` 目录或组合门面纳入门禁）后应迁回目录函数。
- 命名空间映射：友好层的 `statements`/`dividend` 对应目录命名空间
  `rptdom`/`bonus`（见 `src/wmshare/api/__init__.py` 的 `_FRIENDLY_NS_TO_CATALOG`）；
  未显式包装的目录函数经 `_Api.__getattr__` 目录感知委托直达，
  目录之外的名字必须 AttributeError（`tests/test_api.py` 强制）。

## 运行示例

```bash
pip install -e ".[dev,dataframe]"
python examples/01_quickstart.py       # 需要已配置的凭证；--demo 零凭证试跑
python examples/02_catalog_tour.py     # 离线示例（02/03/09 无需凭证）
python examples/08_pandas_analysis.py  # DataFrame 分析（需凭证 + pandas）
# 全部 11 个示例与课程表：examples/README.md
```

## 许可政策

- 整项目采用 **BSD-3-Clause**（见 LICENSE）：贡献即同意以该许可发布。
- 不得引入与 BSD-3-Clause 不兼容的第三方代码。

## 兼容与弃用

公开面（门面签名、返回字段、单位、信封、异常 `code`）的变更按
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) 执行：破坏性变更只能在 MAJOR；
弃用至少保留 1 个 MINOR，并在 CHANGELOG 的 `Deprecated` 段登记替代写法与移除版本。

## 接口质量标准

新增/修改接口必须过 `tests/test_interface_quality.py` 与 `tests/test_data_contract.py`
（ratchet：存量债务只许减少，新增缺口即红）：

- **规范性**：一句话 summary + 可绑定示例（无省略号占位）；参数说明/返回说明不得为
  `—`；有标的语义的参数必须叫 `symbol` 且排第一（禁 `sym/stk`）；错误码必须登记
  `docs/ERRORS.md`（双向一致）。
- **易用性**：MCP description 不得退化为兜底文案、示例不得含 `<REQUIRED>`；
  文档相对链接不悬空；示例数在 README/docs/README/仓库保持一致。
- **可理解性**：字段级返回表只增不减（`FIELD_TABLE_MIN`）；方法级 `:param` 债务
  ratchet（`PARAM_DOC_DEBT`）；单位/守护范围随目录声明进字段表。

## 提交信息

- 使用简明前缀：`feat(scope):` / `fix(scope):` / `docs:` / `test:` / `chore:`；
- 一次提交一个语义；改目录必须同提交重生成 API.md。
