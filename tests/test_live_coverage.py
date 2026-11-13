"""核心接口覆盖面的**静态**守护（不需要凭证、CI 每轮执行）。

`tests/test_live.py` 里同名的检查受 `WMSHARE_LIVE` 模块级 skip 门控，CI 永远
不执行——接口涨到 135 条却没人发现 live 冒烟漏了 5 条。这里只扫源码文本，
把它放进离线集合，新接口漏测会立刻红。
"""
from __future__ import annotations

from pathlib import Path

from wmshare.api import FRIENDLY_INDEX

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "tests" / "test_live.py"
VERBATIM_GROUPS = {
    ("statements", "balance"): '["balance", "income", "cashflow"]',
    ("statements", "income"): '["balance", "income", "cashflow"]',
    ("statements", "cashflow"): '["balance", "income", "cashflow"]',
}


def test_every_core_interface_has_a_live_call():
    """FRIENDLY_INDEX 的每个核心接口都必须在 live 冒烟里有调用点。"""
    src = LIVE.read_text(encoding="utf-8")
    missing: list[str] = []
    for _, ns, method, _, _ in FRIENDLY_INDEX:
        needle = VERBATIM_GROUPS.get((ns, method))
        if needle is not None:
            if needle not in src:
                missing.append(f"{ns}.{method}")
            continue
        # 直接调用 <client>.ns.method(...) 或以可调用对象传入；
        # 客户端变量名可多样（cli / hk / us）。
        if f".{ns}.{method}(" not in src and f".{ns}.{method}," not in src:
            missing.append(f"{ns}.{method}")
    assert not missing, f"live 冒烟未覆盖：{missing}（共 {len(FRIENDLY_INDEX)} 个核心接口）"


def test_live_file_is_not_the_only_coverage_guard():
    """本文件与 test_live.py 各有一份检查；删掉本文件应是有意的评审决定。"""
    assert LIVE.is_file(), "test_live.py 不见了"
    assert "WMSHARE_LIVE" in LIVE.read_text(encoding="utf-8"), (
        "live 冒烟应仍受凭证门控；若已改为常跑请同步本说明")
