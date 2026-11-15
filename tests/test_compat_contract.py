"""兼容性契约：新旧接口边界不能被适配层改动。

适配层是可选工具，不允许修改：
- metrics.json schema/字段
- IndicatorApi.metrics/get 签名
- Catalog 既有公开方法签名
- FRIENDLY_INDEX 既有条目
- docs/openapi.json 既有 operation
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from wmshare.api import FRIENDLY_INDEX, IndicatorApi
from wmshare.catalog import Catalog, load

REPO = Path(__file__).resolve().parents[1]
METRICS = REPO / "src" / "wmshare" / "_catalog" / "generated" / "metrics.json"
OPENAPI = REPO / "docs" / "openapi.json"


def test_metrics_json_schema_and_fields_unchanged():
    doc = json.loads(METRICS.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 2
    assert doc["count"] == len(doc["metrics"]) == 2752
    allowed = {"code", "cn", "markets", "gated"}
    for row in doc["metrics"]:
        assert set(row) <= allowed, f"{row['code']} 出现了 metrics.json 之外的字段"
        assert row["code"].startswith("$")


def test_indicator_api_signatures_unchanged():
    assert list(inspect.signature(IndicatorApi.get).parameters) == [
        "self", "symbol", "code", "fut_symbol"]
    assert list(inspect.signature(IndicatorApi.metrics).parameters) == [
        "self", "symbol", "codes", "fut_symbol"]


def test_catalog_public_signatures_unchanged():
    assert list(inspect.signature(Catalog.metric).parameters) == ["self", "code"]
    assert list(inspect.signature(Catalog.metric_meta).parameters) == ["self", "code"]
    assert list(inspect.signature(Catalog.metric_groups).parameters) == ["self"]
    assert list(inspect.signature(Catalog.metrics_in_group).parameters) == [
        "self", "group_id"]
    assert list(inspect.signature(Catalog.search).parameters) == [
        "self", "query", "kind", "limit"]


def test_existing_friendly_index_entries_still_present():
    ids = {(ns, method) for _, ns, method, _, _ in FRIENDLY_INDEX}
    required = {
        ("indicator", "get"), ("indicator", "metrics"),
        ("kline", "bars"), ("cbond", "kline_window"),
        ("screener", "query"), ("index", "trend"),
        ("valuation", "hist_stats"),
    }
    assert required <= ids


def test_adapter_is_not_registered_as_core_interface():
    ids = {(ns, method) for _, ns, method, _, _ in FRIENDLY_INDEX}
    assert ("indicator", "metrics_table") not in ids
    assert ("indicator", "metrics_many") not in ids


def test_openapi_keeps_existing_operations():
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    ops = {op.get("operationId") for path in spec["paths"].values()
           for op in path.values() if isinstance(op, dict)}
    assert {"indicator_get", "indicator_metrics", "kline_bars",
            "screener_query"} <= ops


def test_catalog_loads_without_sidecar_contract_changes():
    cat = load()
    # 旧目录入口仍返回原有结构；sidecar 不参与 Catalog 装载。
    groups = cat.metric_groups()
    assert groups and all({"id", "cn", "domain", "count"} <= set(g) for g in groups)
    assert cat.metric("$PE_TTM_LAST")["code"] == "$PE_TTM_LAST"
