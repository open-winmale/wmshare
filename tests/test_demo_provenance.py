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
    # 2.0 起快照随发版重拍：拍摄版本可能与当前版本相同，此时以 as_of/上游 rev
    # 作为对照锚（不同版本的对照仍是主用途，但不再强制不同）
    assert isinstance(snap["snapshot_sdk_version"], str)


def test_repr_shows_both_versions():
    text = repr(wmshare.demo_client())
    assert f"as_of={DEMO_SNAPSHOT_PROVENANCE['as_of']}" in text and "非实时行情" in text
    assert DEMO_SNAPSHOT_PROVENANCE["snapshot_sdk_version"] in text
    assert DEMO_SNAPSHOT_PROVENANCE["snapshot_catalog_rev"] in text
    assert wmshare.__version__ in text and "快照不随发版更新" in text
    assert len(text.splitlines()) >= 3


# 独立于 HEAD 的固定基线：CI 是干净 checkout，`git show HEAD:<file>` 与工作树
# 永远相等（恒真），且 sdist/wheel 里没有 .git 会直接报错。用 sha256 锚定才能
# 真正拦住「已提交的快照数据被改动」。
SNAPSHOT_SHA256 = (
    "cb1c1d15dd6f5c44b7de4df8572cd6f09a84148fe4d6d554fd17bd9f934bd389"
)


def test_snapshot_data_file_is_untouched():
    rel = "src/wmshare/_demo_data.json"
    digest = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    assert digest == SNAPSHOT_SHA256, (
        "demo 快照数据字节发生变化；若确为有意更新，须同步本常量并重放快照测试")
