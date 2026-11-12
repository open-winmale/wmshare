---
name: Data report / 数据异常反馈
about: Report a value that looks wrong — a metric code, a price, a ratio / 报告某个数不对：指标值、价格、比率
title: "[data] "
labels: question
assignees: ""
---

**指标 / Metric**
指标码或接口名，例如 `valuation.pe_ttm`、`market.kline`、`screen.industry_rank`。
Metric code or endpoint name.

**标的 / Symbol**
证券代码（如 `600519.SH`、`00700.HK`、`AAPL.US`）。

**日期或报告期 / Date or period**
出问题的日期或报告期，例如 `2026-11-11`、`2025Q3`。

**期望值 / Expected value**
你期望的数值，并说明来源（官网、交易所公告、其他数据源、自己按公式计算的）。
The value you expected, plus where it comes from.

**实际值 / Actual value**
SDK 返回的数值，附最小复现代码。

```python
import wmshare
cli = wmshare.Client.from_env()   # 需已配置凭证（WMSHARE_* 环境变量或 ~/.wmshare/credentials.env）
# 最小可复现代码 / minimal reproduction
```

**凭证档位 / Credential tier**
- [ ] demo 离线
- [ ] 免费档
- [ ] 其他（请说明）

**环境 / Environment**
- SDK 版本：`python -c "import wmshare; print(wmshare.__version__)"`
- Python 版本：
- 操作系统：

**其他 / Additional context**
相关的文档段落、目录合同版本输出等。