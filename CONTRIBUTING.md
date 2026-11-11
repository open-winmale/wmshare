# 贡献指南与项目规范

感谢关注 wmshare。本文件同时是**内容规范**：违反任一条会被 CI 门禁拦截。

## 提交前门禁（全部必须通过）

```bash
python3 tools/check_leak.py         # 内容规范扫描（见下）
python3 tools/validate_catalog.py   # 域目录合同 + 防编造回溯
python3 tools/check_version.py --check  # 六处版本声明互校（含 SECURITY.md 表头）
python3 tools/guard_coverage.py --min 0.156  # 守护声明覆盖率下限（防回退）
python3 tools/gen_api_docs.py       # 重生成 docs/API.md（改了目录必须重跑）
python3 tools/gen_typed_api.py      # 重生成类型化门面 docs 同源
python3 tools/gen_openapi.py        # 重生成 docs/openapi.json + swagger.html
python3 tools/gen_llms.py           # 重生成 llms.txt / llms-full.txt（AI 分发面）
python3 tools/gen_indicators.py     # 重生成 docs/INDICATORS.md（指标码导航）
pytest --cov=wmshare --cov-branch --cov-fail-under=85   # 全部测试（不联网）+ 行/分支覆盖率门禁
python3 -m mypy                     # 类型检查
```

真实取数冒烟（需要凭证）：`WMSHARE_LIVE=1 pytest tests/test_live.py`——覆盖全部 44 个
核心接口与多个标的，做数值合理性断言（日期有序、价格为正、率类口径等）。
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
3. **文档白名单**：对外文档只允许 README / LICENSE / CONTRIBUTING / docs/API.md / examples。
   方案、计划、路线图、内部流程文档一律不入库。
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

## 提交信息

- 使用简明前缀：`feat(scope):` / `fix(scope):` / `docs:` / `test:` / `chore:`；
- 一次提交一个语义；改目录必须同提交重生成 API.md。
