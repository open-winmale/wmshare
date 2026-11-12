# 维护者

## 当前维护者

| GitHub | 负责范围 |
|---|---|
| [@deadkingyy](https://github.com/deadkingyy) | SDK 核心、数据目录（catalog）、文档、发布流程 |

## 响应承诺

- **GitHub Issues / Discussions Q&A**：工作日 24 小时内首次回应（节假日顺延）。
- **安全漏洞**：走 [SECURITY.md](SECURITY.md) 的私密披露通道，不走公开 issue；
  确认后 5 个工作日内给出响应。
- **数据异常反馈**：附上 symbol、日期、期望值与实际值，可显著加快核对。

## 发版流程（维护者备忘）

1. 更新 `src/wmshare/__init__.py::__version__` 与 `CHANGELOG.md` 版本段
   （`tools/check_version.py` 会做六处版本声明互校）。
2. 打 tag `vX.Y.Z` 并推送到 Gitee 与 GitHub——CI（`.github/workflows/release.yml`）
   自动完成：tag ↔ `__version__` 互校 → 抽取 CHANGELOG 版本段建 GitHub Release
   → 构建 sdist/wheel → twine check → 发布 PyPI（需 repo Secret `PYPI_TOKEN`）。
3. **MCP registry 上架仍为人工步骤**（JWT 短时效，每次发布前重新登录）：

   ```bash
   # 等 PyPI 发布可见后约 20 秒再执行，否则 registry 校验包版本会 404
   mcp-publisher login github -token "$(gh auth token)"
   mcp-publisher publish server.json
   ```

4. 验证：`https://pypi.org/pypi/wmshare/<版本>/json` 返回 200（项目级 JSON 与
   国内镜像有滞后，一律用版本级端点核对）；registry 查询 `isLatest=true`。
