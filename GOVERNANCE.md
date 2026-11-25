# 治理

wmshare 目前采用**单人维护 + 社区协作**模式。

## 决策权与合并权限

- [@deadkingyy](https://github.com/deadkingyy) 是唯一拥有合并权限的维护者，
  对方向性决策（数据域覆盖、接口设计、版本节奏）负责。
- `main` 分支受 GitHub Rulesets 保护：禁止删除分支、禁止 force push，
  bypass 名单为空（维护者本人也绕不过）。
- 贡献者通过 Pull Request 提交改动，由维护者 review 后合并。

## 各类改动的入口

| 改动类型 | 入口 | 说明 |
|---|---|---|
| 缺陷报告 | GitHub Issues（bug 模板） | 附复现代码 |
| 功能/指标建议 | GitHub Discussions「Ideas & 指标码请求」 | 维护者定期评估进 roadmap |
| 文档 / 示例 / 单测 | Pull Request | 见 [CONTRIBUTING.md](CONTRIBUTING.md) 门禁清单 |
| 新数据域 / 新指标码 | GitHub Issues | 随包目录是维护者同步的发布物，贡献者无需自行重建 |
| 安全漏洞 | [SECURITY.md](SECURITY.md) 私密通道 | 不走公开 issue |

## 版本与兼容

- 遵循语义化版本；破坏性变更（如 1.19.0 将最低 Python 提至 3.11）在
  `CHANGELOG.md` 对应版本段显著标注并给出影响说明。
- 指标码的新增、口径变化与死码都在 [docs/INDICATORS.md](docs/INDICATORS.md)
  （含「死码警示」章）与 `CHANGELOG.md` 留痕，不静默变更。
- 单元口径（比率/涨跌幅=小数、金额/价格/市值=元、成交量=股）是公开契约，
  变更视同破坏性变更。

## 治理变更

维护者结构或决策流程变化时更新本文件，历史见提交记录。
