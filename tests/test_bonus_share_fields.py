"""W1：送股/股权登记日两键的目录声明与 demo/live 同向语义。

防坑 4 在「新增 optional 字段」场景下的精确含义：live 侧目录声明必须带两键，
demo 快照（2026-11-17 重拍）已随 live 带两键；本组只锁「声明 optional +
两键在快照里出现」，缺键分支留给更早的历史快照（不再有在役样本）。
真正要防的是「demo 与 live 对同一已声明字段给出相反口径」（如序列方向），
不是「可选字段在旧快照里不存在」。
"""
from __future__ import annotations

from pathlib import Path

import wmshare

REPO = Path(__file__).resolve().parents[1]


def test_bonus_fmt_maps_declares_new_fields_optional():
    """两键在规范化分红行 shape 里声明为 optional，原值透传、无单位守护。"""
    fn = wmshare.load().function("bonus.fmt_maps")
    fields = {f["name"]: f for f in fn["returns_shape"]["items"]["fields"]}
    for key in ("bonus_share", "record_date"):
        assert key in fields, f"fmt_maps.shape 缺 {key}"
        assert fields[key].get("optional") is True, f"{key} 应为 optional（港股常缺）"


def test_demo_snapshot_carries_new_fields_since_2_0_recapture():
    """2026-11-17 重拍后 demo 与 live 同形：两键都出现（optional 声明仍保留，
    供港股等缺键场景；缺键不再有在役样本）。"""
    import json
    from wmshare._demo import DEMO_SNAPSHOT_PROVENANCE

    doc = json.loads((REPO / "src" / "wmshare" / "_demo_data.json").read_bytes())
    assert doc["as_of"] == DEMO_SNAPSHOT_PROVENANCE["as_of"]
    rows = doc["data"]["dividend"]["history"]["000001"]
    assert rows
    assert any("bonus_share" in row for row in rows)
    assert any("record_date" in row for row in rows)


def test_query_list_desc_and_docstring_mention_new_fields():
    """函数说明与 SDK docstring 字段清单同步（防文档漂移）。"""
    fn = wmshare.load().function("bonus.query_list")
    assert "bonus_share" in fn["returns"]["desc"]
    assert "record_date" in fn["returns"]["desc"]
    from wmshare.api import DividendApi
    doc = DividendApi.history.__doc__ or ""
    assert "bonus_share" in doc and "record_date" in doc
