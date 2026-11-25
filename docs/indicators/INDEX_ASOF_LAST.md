# `$INDEX_ASOF_LAST` — 指数最新行情 asof

**类型/市场**：指数及 ETF · 未声明（以 `cat.search` 为准）
**单位/换算**：—（默认基础单位：率=小数 / 额=元 / 量=股）
**族前缀**：`$INDEX_*`（指数层行情与估值）

取数：`cli.indicator.get("600519", "$INDEX_ASOF_LAST")` · 多码 `cli.indicator.metrics("600519", ["$INDEX_ASOF_LAST"])`

检索与批量见 [GUIDE](../GUIDE.md)；全量码表 [INDICATORS.md](../INDICATORS.md)；
目录核实用 `cat.search("$INDEX_ASOF_LAST")` / `cat.function("indicator.get")`。
