"""W1：送股/股权登记日两键的目录声明与 demo/live 同向语义。

防坑 4 在「新增 optional 字段」场景下的精确含义：live 侧目录声明必须带两键，
demo 快照因 as_of=2026-10-30 早于字段引入而缺键，属冻结预期、不算不同向。
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


def test_demo_snapshot_predates_new_fields_is_expected():
    """demo 快照冻结于字段引入前，缺两键是预期，不要求改快照。"""
    import json
    doc = json.loads((REPO / "src" / "wmshare" / "_demo_data.json").read_bytes())
    assert doc["as_of"] == "2026-10-30"
    rows = doc["data"]["dividend"]["history"]["000001"]
    assert rows and all("bonus_share" not in row and "record_date" not in row for row in rows)


def test_query_list_desc_and_docstring_mention_new_fields():
    """函数说明与 SDK docstring 字段清单同步（防文档漂移）。"""
    fn = wmshare.load().function("bonus.query_list")
    assert "bonus_share" in fn["returns"]["desc"]
    assert "record_date" in fn["returns"]["desc"]
    from wmshare.api import DividendApi
    doc = DividendApi.history.__doc__ or ""
    assert "bonus_share" in doc and "record_date" in doc
