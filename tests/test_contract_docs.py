"""契约文档与实现一致性：COMPATIBILITY / LIMITS / ERRORS / fields.json。

这些文档是「对外承诺」，不能手改漂移：
- LIMITS.md 的数字必须与 Client 构造默认值/模块常量一致；
- ERRORS.md 必须等于 gen_errors 的生成结果（错误码全集来自源码扫描）；
- fields.json 必须覆盖全部目录函数且字段/单位与目录声明一致。
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import yaml

from wmshare.catalog import load
from wmshare.client import NATIVE_FULL_MARKET_MIN, SPLICE_WARN_MIN, Client

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"


def _load_tool(name: str):
    path = REPO / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compatibility_doc_exists_and_linked():
    doc = DOCS / "COMPATIBILITY.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "MAJOR" in text and "MINOR" in text
    assert "至少保留" in text  # 弃用窗口承诺
    for name in ("CONTRIBUTING.md", "AGENTS.md", "CHANGELOG.md"):
        assert "COMPATIBILITY.md" in (REPO / name).read_text(encoding="utf-8"), name


def test_limits_doc_matches_code_defaults():
    text = (DOCS / "LIMITS.md").read_text(encoding="utf-8")
    sig = inspect.signature(Client.__init__).parameters
    assert f"**{sig['max_limit'].default}**" in text
    assert f"`retries={sig['retries'].default}`" in text
    assert f"`backoff={sig['backoff'].default}s`" in text
    assert f"**{NATIVE_FULL_MARKET_MIN:,}**" in text
    assert f"**{SPLICE_WARN_MIN}**" in text
    assert f"**{sig['ec_warn_threshold'].default:,}**" in text


def test_errors_doc_in_sync():
    tool = _load_tool("gen_errors")
    assert (DOCS / "ERRORS.md").read_text(encoding="utf-8") == tool.build()


def test_fields_json_covers_catalog_and_units():
    payload = json.loads((DOCS / "fields.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    domains = [yaml.safe_load(p.read_text(encoding="utf-8"))
               for p in sorted((REPO / "src/wmshare/_catalog/domains").glob("*.yaml"))]
    sys.path.insert(0, str(REPO / "tools"))
    from _introspect import is_internal_catalog_name

    expected = sum(1 for d in domains for f in d.get("functions") or []
                   if not f.get("internal")
                   and not is_internal_catalog_name(str(f.get("name", ""))))
    assert payload["count"] == expected
    names = [f["name"] for d in payload["domains"] for f in d["functions"]]
    assert len(names) == len(set(names))
    # 内部函数不进对外字段字典（内部命名空间由 visibility 测试另行拦截）
    assert all(f["internal"] is False for d in payload["domains"] for f in d["functions"])

    fn = next(f for d in payload["domains"] for f in d["functions"]
              if f["name"] == "kline.query_bars")
    by_name = {f["name"]: f for f in fn["fields"]}
    assert by_name["volume"]["unit"] == "手→股"
    assert by_name["percent"]["range"] == [-1, 30]
    assert fn["checks"] == ["volume_amount"]


def test_indicator_pages_sample_matches_metrics_json():
    """逐码单页抽查：页面里的码与中文名必须与 metrics.json 同源（5 个跨章样本）。"""
    metrics = json.loads(
        (REPO / "src/wmshare/_catalog/generated/metrics.json").read_text(encoding="utf-8"))
    by_code = {m["code"]: m for m in metrics["metrics"]}
    for code in ("$PCT_PE_TTM_10Y_LAST", "$ID_ROE_TTM", "$FUT_CLOSE",
                 "$MF_ELG_NET", "$CPI"):
        page = DOCS / "indicators" / f"{code.lstrip('$')}.md"
        assert page.is_file(), page
        text = page.read_text(encoding="utf-8")
        assert f"`{code}`" in text
        assert (by_code[code].get("cn") or "") in text
    index = (DOCS / "indicators" / "README.md").read_text(encoding="utf-8")
    assert f"共 **{stats_count()}** 个预置指标码" in index


def stats_count() -> int:
    metrics = json.loads(
        (REPO / "src/wmshare/_catalog/generated/metrics.json").read_text(encoding="utf-8"))
    return len(metrics["metrics"])


def test_anchor_entry_points_share_bar_contract():
    """锚点切片入口必须与正排查询同款行合同（含单位换算），否则切片结果口径不一。

    kline.bars / moneyflow.bars 的区间完整性建立在「每片与全量同口径」上：
    如果锚点函数缺 normalize_with，切片结果就是未转换的原始值（volume 手 vs 股）。
    """
    cat = load()
    for base, anchor in (
        ("kline.query_bars", "kline.query_at_anchor"),
        ("kline.query_bars_adj", "kline.query_at_anchor_adj"),
        ("moneyflow.query_bars", "moneyflow.query_bars_anchor"),
    ):
        base_fn, anchor_fn = cat.function(base), cat.function(anchor)
        assert anchor_fn is not None, anchor
        assert anchor_fn.get("normalize_with") == base_fn.get("normalize_with"), (
            f"{anchor} 的 normalize_with 必须与 {base} 一致")
        assert (anchor_fn.get("units") or {}) == (base_fn.get("units") or {}), (
            f"{anchor} 的 units 声明必须与 {base} 一致")
