"""离线回放夹具完整性合同：数据字节锚、加载校验、显式不支持语义。

demo 模式已于 3.0.0 移除；tests/fixtures/replay_data.json 是冻结的测试夹具，
字节级锚定防止无意改动（夹具坏了 CI 会假绿，宁红勿假）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from replay_client import load_replay_snapshot, replay_client
from wmshare.errors import UsageError

REPO = Path(__file__).resolve().parents[1]

# 字节级锚：CI 是干净 checkout，快照数据被改动即红；若确为有意更新，
# 须同步本常量并复核 content_hash。
REPLAY_DATA_SHA256 = (
    "e4b72dd7acb59e8d7bf9f4d376d280e6185b25fd3321b670029c4e78ae5ab3a6"
)


def test_replay_data_file_is_untouched():
    rel = "tests/fixtures/replay_data.json"
    digest = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
    assert digest == REPLAY_DATA_SHA256, (
        "回放夹具数据字节发生变化；若确为有意更新，须同步本常量并复核 content_hash")


def test_load_replay_snapshot_passes_validation():
    doc = load_replay_snapshot()
    assert doc["as_of"] == "2026-11-19"
    assert doc["market"] == "cn"
    assert doc["data"]["universe"]


def test_unbacked_call_raises_replay_unsupported():
    cli = replay_client()
    # cbond 是整域未拍摄命名空间：任意方法可点出、调用即显式报错
    with pytest.raises(UsageError) as ei:
        cli.cbond.daily()
    assert ei.value.code == "replay_unsupported"
    assert "functions_by_domain" in str(ei.value)
    assert "Client.from_env()" in str(ei.value)


def test_unknown_symbol_raises_replay_symbol():
    cli = replay_client()
    with pytest.raises(UsageError) as ei:
        cli.kline.bars("999999", n=5)
    assert ei.value.code == "replay_symbol"


def test_repr_shows_snapshot_provenance():
    text = repr(replay_client())
    assert "非实时行情" in text
    assert "Client.from_env()" in text
    assert len(text.splitlines()) >= 2
