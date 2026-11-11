"""单股回测：买卖点（均线 / PE·PB 阈值）→ 成交明细 / 净值 / 汇总（纯计算层）。

``cli.backtest.run`` 是取数入口；本层不联网、不依赖第三方库，便于单测与复用。
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
