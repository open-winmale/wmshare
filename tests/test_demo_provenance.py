"""R1 / S7：demo 快照版本与当前包/上游版本必须在 status() 与 repr() 里可对照。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import wmshare
from wmshare._demo import DEMO_SNAPSHOT_PROVENANCE
from wmshare.mcp import tools
from wmshare.mcp.core import MCPRuntime

REPO = Path(__file__).resolve().parents[1]


def test_status_exposes_snapshot_vs_current_versions():
    result = tools.status(MCPRuntime(market="cn", demo=True))
    snap = result["data"]["demo_snapshot"]
    assert snap["snapshot_as_of"] == DEMO_SNAPSHOT_PROVENANCE["as_of"]
    assert snap["snapshot_sdk_version"] == DEMO_SNAPSHOT_PROVENANCE["snapshot_sdk_version"]
    assert snap["snapshot_catalog_rev"] == DEMO_SNAPSHOT_PROVENANCE["snapshot_catalog_rev"]
    assert snap["current_sdk_version"] == wmshare.__version__
    assert snap["current_upstream_rev"] == wmshare.load().stats()["upstream_rev"]
    # 这是本条的真实价值：两者不同，才需要显式对照
    assert snap["snapshot_sdk_version"] != snap["current_sdk_version"]


def test_repr_shows_both_versions():
    text = repr(wmshare.demo_client())
    assert "as_of=2026-10-30" in text and "非实时行情" in text
    assert DEMO_SNAPSHOT_PROVENANCE["snapshot_sdk_version"] in text
    assert DEMO_SNAPSHOT_PROVENANCE["snapshot_catalog_rev"] in text
    assert wmshare.__version__ in text and "快照不随发版更新" in text
    assert len(text.splitlines()) >= 3


# 独立于 HEAD 的固定基线：CI 是干净 checkout，`git show HEAD:<file>` 与工作树
# 永远相等（恒真），且 sdist/wheel 里没有 .git 会直接报错。用 sha256 锚定才能
# 真正拦住「已提交的快照数据被改动」。
SNAPSHOT_SHA256 = (
    "c28f3c56359811dd4f666f4812743abf88c9b3f1b9d004df290379de9c354741"
)


def test_snapshot_data_file_is_untouched():
    rel = "src/wmshare/_demo_data.json"
    digest = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    assert digest == SNAPSHOT_SHA256, (
        "demo 快照数据字节发生变化；若确为有意更新，须同步本常量并重放快照测试")
