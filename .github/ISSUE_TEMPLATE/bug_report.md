---
name: Bug report / 缺陷报告
about: Report something that doesn't work as documented / 报告与文档不符的行为
title: "[bug] "
labels: bug
assignees: ""
---

**描述 / Description**
简明描述遇到的问题。A clear and concise description of the bug.

**复现代码 / Reproduction**

```python
import wmshare
cli = wmshare.Client.from_env()   # 需已配置凭证（WMSHARE_* 环境变量或 ~/.wmshare/credentials.env）
# 最小可复现代码 / minimal reproduction
```

> 1.7.0 起 SDK 不再内置体验 AppID：构造 `Client()` 缺凭证会直接抛 `AuthError(code="config")`，
> 这不是 bug。凭证问题请先按错误消息里的指引配置。

**期望行为 / Expected behavior**
你期望发生什么？What did you expect to happen?

**实际行为 / Actual behavior**
实际发生了什么（含完整错误信息 / `WmshareError` 的 `code` 与 `status`）？
What actually happened (full error message, `WmshareError.code` / `status`)?

**环境 / Environment**
- SDK 版本：`python -c "import wmshare; print(wmshare.__version__)"`
- Python 版本：
- 操作系统：

**其他 / Additional context**
目录合同版本（`wmshare.Catalog` 相关输出）、相关文档段落等。
