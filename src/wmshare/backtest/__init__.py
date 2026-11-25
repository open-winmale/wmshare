"""单股回测：买卖点（均线 / PE·PB 阈值）→ 成交明细 / 净值 / 汇总（纯计算层）。

两层分工（别把本包当公开入口）：

- **公开入口 `cli.backtest.run(...)`**：取日 K / 估值（走客户端，**服务端请求与 EC 照常计**，
  EC 按请求行数）+ 调本内核算成交与净值；
- **本包的 4 个函数**（``run_backtest`` / ``ma_cross_signals`` / ``valuation_signals`` /
  ``valuation_by_date``）：纯计算，不联网、不计 EC；自己准备 ``bars`` / ``signals``
  时可直接调用，例如 ``wmshare.backtest.run_backtest(bars, signals, cash=...)``。

口径（次日开盘成交、T+1、整手、佣金/印花、一字板顺延）见 ``engine`` 模块 docstring。
"""
from wmshare.backtest.engine import (
    FEE_RATE,
    LOT_SIZE,
    MIN_FEE,
    STAMP_DUTY,
    VALUATION_RULES,
    ma_cross_signals,
    run_backtest,
    valuation_by_date,
    valuation_signals,
)

__all__ = ["run_backtest", "ma_cross_signals", "valuation_signals", "valuation_by_date",
           "VALUATION_RULES", "LOT_SIZE", "FEE_RATE", "MIN_FEE", "STAMP_DUTY"]
