# `$VOLUME_DAY` — 成交量(前复权)

**类型/市场**：股票指标码 · 未声明（以 `cat.search` 为准）
**单位/换算**：`lot` → `shares`（指标层为手；cli.kline.bars 已换算为股）
**族前缀**：—

取数：`cli.indicator.get("600519", "$VOLUME_DAY")` · 多码 `cli.indicator.metrics("600519", ["$VOLUME_DAY"])`

检索与批量见 [GUIDE](../GUIDE.md)；全量码表 [INDICATORS.md](../INDICATORS.md)；
目录核实用 `cat.search("$VOLUME_DAY")` / `cat.function("indicator.get")`。
