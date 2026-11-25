"""W1：送股/股权登记日两键的目录声明契约。

live 侧目录声明必须带两键（optional：港股等场景可缺）；快照载体已随 demo
模式移除（3.0.0），回放夹具的数据字节锚见 test_replay_fixture。
"""
from __future__ import annotations

import wmshare


def test_bonus_fmt_maps_declares_new_fields_optional():
    """两键在规范化分红行 shape 里声明为 optional，原值透传、无单位守护。"""
    fn = wmshare.load().function("bonus.fmt_maps")
    fields = {f["name"]: f for f in fn["returns_shape"]["items"]["fields"]}
    for key in ("bonus_share", "record_date"):
        assert key in fields, f"fmt_maps.shape 缺 {key}"
        assert fields[key].get("optional") is True, f"{key} 应为 optional（港股常缺）"




def test_query_list_desc_and_docstring_mention_new_fields():
    """函数说明与 SDK docstring 字段清单同步（防文档漂移）。"""
    fn = wmshare.load().function("bonus.query_list")
    assert "bonus_share" in fn["returns"]["desc"]
    assert "record_date" in fn["returns"]["desc"]
    from wmshare.api import DividendApi
    doc = DividendApi.history.__doc__ or ""
    assert "bonus_share" in doc and "record_date" in doc
