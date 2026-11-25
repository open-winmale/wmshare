<!-- 提交前请先阅读 CONTRIBUTING.md。PR 必须通过 CI 门禁：pytest + mypy + coverage≥85% + check_leak.py -->

## 这个 PR 做了什么 / What does this PR do?

<!-- 一句话说明变更目的与内容 -->

## 变更类型 / Type of change

- [ ] Bug fix（修复，不破坏现有接口）
- [ ] New feature（新能力，向后兼容）
- [ ] Breaking change（破坏性变更，需在 CHANGELOG 标注）
- [ ] Docs / examples only（仅文档或示例）

## 自查清单 / Checklist

- [ ] 测试覆盖了变更行为（`pytest`，不联网）
- [ ] `mypy src/wmshare` 通过
- [ ] `python3 tools/check_leak.py` 通过（无密钥/机器路径/第三方引用/白名单外文件）
- [ ] 有公开接口变更时：`docs/API.md` 与 OpenAPI 已同步（CI 有漂移门禁）
- [ ] `CHANGELOG.md` 的 Unreleased 段已更新
- [ ] 未包含内部规划/流程文档（入库白名单见 CONTRIBUTING.md）

## 关联 issue / Related issues

<!-- 例如：Fixes #123 -->
