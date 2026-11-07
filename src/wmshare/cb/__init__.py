"""可转债研究工具：估值、规则内核、事实构建、日更编排、成稿与图。

这一层是**纯计算**，不绑定任何发布渠道——同一个事实包既可以出公众号文章，
也可以出日报、周报或给自己的看板。数据来自 ``wmshare.Client`` 的 cbond 域：

.. code-block:: python

    from wmshare import Client
    from wmshare.cb import run_daily

    payload = run_daily(Client.from_env())
    print(payload["top"][0]["bondName"], payload["top"][0]["double_low"])

口径与可核对性约定：

- 价格单位＝元（面值 100），溢价率＝百分比数值（4.87 表示 +4.87%），双低＝价格 + 溢价率。
- 每个数字都带 ``sources`` 与 ``as_of``；成稿遇到缺条目直接拒绝，不补猜测值。
- 只写"参考区间/参考价位"，不写目标价、不写买卖建议。
"""
from wmshare.cb import facts, rules, valuation
from wmshare.cb.daily import DailyConfig, fetch_snapshot, run_daily
from wmshare.cb.facts import build_facts, caliber_layers, probe
from wmshare.cb.rules import (
    CALL_HITS_THRESHOLD,
    build_event_index,
    calendar,
    call_state,
    evaluate,
    gate_row,
    reset_state,
)
from wmshare.cb.valuation import (
    double_low,
    nature_class,
    premium_pct,
    remaining_years,
    redeem_value,
    ytm_after_tax,
    ytm_floor,
)

__all__ = [
    "CALL_HITS_THRESHOLD",
    "DailyConfig",
    "build_event_index",
    "build_facts",
    "caliber_layers",
    "calendar",
    "call_state",
    "double_low",
    "evaluate",
    "facts",
    "fetch_snapshot",
    "gate_row",
    "nature_class",
    "premium_pct",
    "probe",
    "redeem_value",
    "remaining_years",
    "reset_state",
    "rules",
    "run_daily",
    "valuation",
    "ytm_after_tax",
    "ytm_floor",
]
