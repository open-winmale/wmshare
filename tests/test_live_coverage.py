"""核心接口覆盖面的**静态**守护（不需要凭证、CI 每轮执行）。

`tests/test_live.py` 里同名的检查受 `WMSHARE_LIVE` 模块级 skip 门控，CI 永远
不执行——接口涨到 135 条却没人发现 live 冒烟漏了 5 条。这里只扫源码文本，
把它放进离线集合，新接口漏测会立刻红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

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


def test_us_macro_paging_contract():
    """美宏观分页契约（静态守护，不需要凭证）。

    2026-11-23 review 实测：`store.query` 单次内核硬顶 10000 行（DGS10 共 16927、
    DFF 共 26440），而客户端跨段拼接把 17k 行展平需 144M EC（append 深拷贝 O(n²)，
    比按窗口分两段取贵 128 倍）。约束落在源码与目录两处，任何一处回退都要红。
    """
    src = REPO.parent / "script" / "sys" / "fred" / "init.xs"
    if not src.is_file():
        pytest.skip("兄弟仓 ../script 不存在")
    text = src.read_text(encoding="utf-8")
    # ① 上限必须如实是 10000，不得再出现 20000 的 lim 钳位
    assert "if lim > 10000 {" in text, "points_asc 的 limit 上限应为 10000（store 单次硬顶）"
    assert "if lim > 20000 {" not in text, "旧的 20000 钳位会让调用方误以为能取 2 万行"
    # ② 不得再用逐行 append 组装点序列（O(n²)）
    assert "out = out.append({\n      \"id\"" not in text, \
        "点序列组装必须走 CONOF/CONFT 向量化，逐行 append 是 O(n²)（实测 129 倍差）"
    assert "CONOF(asc," in text, "应使用 CONOF 做反转 + 字段投影"
    # ③ 版本键探针必须显式声明 -samplingTs（与 fx/reserve 同范式）
    probe = re.search(r"probe :?= DEFAULT\(store\.query\(\"[^\"]+\", addr, 1,\s*\n?\s*(\{[^}]*\})",
                      text)
    assert probe is not None, "找不到 points_asc 的版本键探针"
    assert "-samplingTs" in probe.group(1), \
        "版本键探针须显式 order=-samplingTs：默认序不是合同，改默认会让键永不换新"
    # ④ 非法日期预校验必须在 DATE() 之前
    assert "fred.iso_date(sd) == false" in text, "begin 须先经 iso_date 校验再传 DATE()"
    assert "fred.iso_date(ed) == false" in text, "end 须先经 iso_date 校验再传 DATE()"
