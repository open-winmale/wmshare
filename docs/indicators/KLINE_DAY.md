# `$KLINE_DAY` — + STRING($DATE_SAS) + "\n市值:" + STRING($MV_DAY) + "\n收盘价:" + STRING($CLOSE_DAY) +
  "\n采样日:" + STRING($SAMPLING_DAY) +
  "\n陆股通持股比例:" + STRING($HOLD_RATIO_DAY) + "\n陆股通持股数量:" + STRING($HOLD_VOL_DAY)

**类型/市场**：股票指标码 · 未声明（以 `cat.search` 为准）
**单位/换算**：—（默认基础单位：率=小数 / 额=元 / 量=股）
**族前缀**：—

取数：`cli.indicator.get("600519", "$KLINE_DAY")` · 多码 `cli.indicator.metrics("600519", ["$KLINE_DAY"])`

检索与批量见 [GUIDE](../GUIDE.md)；全量码表 [INDICATORS.md](../INDICATORS.md)；
目录核实用 `cat.search("$KLINE_DAY")` / `cat.function("indicator.get")`。
