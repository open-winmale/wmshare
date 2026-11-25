# `$FUT_VOLUME` — 期货成交量(手)

**类型/市场**：期货 · cn
**单位/换算**：—（期货原生口径：价=元、量/持仓=手、额=万元；不做换算）
**族前缀**：`$FUT_*`（期货主力连续（fut_symbol 指定合约））

取数：`cli.indicator.get("600519", "$FUT_VOLUME")` · 多码 `cli.indicator.metrics("600519", ["$FUT_VOLUME"])`

检索与批量见 [GUIDE](../GUIDE.md)；全量码表 [INDICATORS.md](../INDICATORS.md)；
目录核实用 `cat.search("$FUT_VOLUME")` / `cat.function("indicator.get")`。
