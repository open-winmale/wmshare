# `$BOND_SECUCODE` — 证券代码

**类型/市场**：可转债 · 未声明（以 `cat.search` 为准）
**单位/换算**：—（默认基础单位：率=小数 / 额=元 / 量=股）
**族前缀**：`$BOND_*`（可转债工具属性（条款/发行/转股））

取数：`cli.indicator.get("600519", "$BOND_SECUCODE")` · 多码 `cli.indicator.metrics("600519", ["$BOND_SECUCODE"])`

检索与批量见 [GUIDE](../GUIDE.md)；全量码表 [INDICATORS.md](../INDICATORS.md)；
目录核实用 `cat.search("$BOND_SECUCODE")` / `cat.function("indicator.get")`。
