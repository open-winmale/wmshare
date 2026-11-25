"""成品出口层测试：扩展名分派、缺依赖报错、manifest、口径表头。

export 不进目录/不进 FRIENDLY_INDEX，没有计数门禁——它的合同就是
「同一份数据按扩展名落成可直接交付的文件，缺依赖显式报错不静默降级」。
"""
from __future__ import annotations

import json

import pytest

from wmshare import export
from wmshare.errors import UsageError

ENVELOPE = {"ok": True, "as_of": "2026-11-19",
            "data": {"count": 2, "rows": [
                {"symbol": "600519", "name": "贵州茅台", "$ROE_TTM_LAST": 0.31},
                {"symbol": "000001", "name": "平安银行", "$ROE_TTM_LAST": 0.10},
            ]}, "meta": {}}


def test_to_markdown_carries_as_of_and_units(tmp_path):
    md = export.to_markdown(ENVELOPE, title="冒烟")
    assert md.startswith("# 冒烟")
    assert "2026-11-19" in md                       # 信封 as_of 进表头
    assert "比率/涨跌幅/占比=小数" in md             # 单位口径约定
    assert "0.31" in md and "600519" in md          # 数据行


def test_to_markdown_unwraps_rows_and_accepts_frame():
    pytest.importorskip("pandas")
    import pandas as pd

    md1 = export.to_markdown({"rows": [{"a": 1}]}, title="t")
    assert "| a |" in md1
    md2 = export.to_markdown(pd.DataFrame([{"a": 1, "b": None}]), title="t")
    assert "| 1 |" in md2
    empty = export.to_markdown(pd.DataFrame([]), title="t")
    assert "无数据行" in empty


def test_to_markdown_escapes_pipes_and_caps_rows():
    rows = [{"name": f"含|竖线{i}", "v": i} for i in range(60)]
    md = export.to_markdown(rows, title="t", max_rows=10)
    assert "含\\|竖线" in md                        # 竖线转义，表格不被撑破
    assert "另 50 行略" in md                       # 超限提示引导换 csv/xlsx


def test_write_dispatches_by_suffix(tmp_path):
    p1 = export.write(ENVELOPE, tmp_path / "r.md")
    assert "2026-11-19" in p1.read_text(encoding="utf-8")
    p2 = export.write(ENVELOPE, tmp_path / "r.csv")
    assert "symbol" in p2.read_text(encoding="utf-8-sig")


def test_write_md_passthrough_for_finished_text(tmp_path):
    """已是 Markdown 成品的 str（如 cbond.article 源稿）原样落盘，不二次包装。"""
    src = "# 已成稿\n\n- 数据截至：2026-11-19"
    p = export.write(src, tmp_path / "article.md")
    assert p.read_text(encoding="utf-8") == src


def test_write_xlsx_and_png(tmp_path):
    pytest.importorskip("openpyxl")
    pytest.importorskip("matplotlib")
    p3 = export.write(ENVELOPE, tmp_path / "r.xlsx")
    assert p3.stat().st_size > 0
    p4 = export.write(ENVELOPE, tmp_path / "r.png")
    assert p4.stat().st_size > 0


def test_write_unknown_suffix_raises(tmp_path):
    with pytest.raises(UsageError) as ei:
        export.write(ENVELOPE, tmp_path / "r.parquet")
    assert ei.value.code == "params"


def test_write_scalar_to_csv_is_rejected_with_hint(tmp_path):
    with pytest.raises(UsageError) as ei:
        export.write({"ok": True, "data": 3.14, "meta": {}}, tmp_path / "s.csv")
    assert ei.value.code == "params"


def test_write_bundle_manifest_records_rows_and_as_of(tmp_path):
    written = export.write_bundle({"a.md": ENVELOPE, "b.csv": ENVELOPE},
                                  tmp_path / "bundle")
    names = {p.name for p in written.values()}
    assert names == {"a.md", "b.csv", "manifest.json"}
    manifest = json.loads((tmp_path / "bundle" / "manifest.json").read_text())
    assert manifest["as_of"] == "2026-11-19"
    assert {f["file"]: f["rows"] for f in manifest["files"]} == {"a.md": 2, "b.csv": 2}
    assert manifest["wmshare_version"] == __import__("wmshare").__version__


def test_xlsx_without_openpyxl_reports_install_command(tmp_path, monkeypatch):
    """缺可选依赖给安装命令而不是裸 ImportError（不静默降级）。"""
    import builtins

    real_import = builtins.__import__

    def _no_openpyxl(name, *a, **k):
        if name == "openpyxl":
            raise ImportError("No module named 'openpyxl'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_openpyxl)
    pytest.importorskip("matplotlib")
    with pytest.raises(UsageError) as ei:
        export.write(ENVELOPE, tmp_path / "r.xlsx")
    assert ei.value.code == "extra"
    assert 'wmshare[excel]' in str(ei.value)
