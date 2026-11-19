"""P1 #7 回归：audit_units.py drift 模式（离线、可分级、正负例）。

drift 比对 returns_shape 字段集 / 指标 markets 可用性 / checks 适用性，
默认只把「声明内部不自洽」当 ERROR；上游 shape 声明滞后是 WARN（--strict 升级）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "audit_units.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_units_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class FakeCat:
    """最小目录桩：只实现 collect_drift 用到的四个接口。"""

    def __init__(self, guards, shapes, domain_notes=None):
        self._guards = guards
        self._shapes = shapes
        self.domains = {"d": {"notes": domain_notes or []}}

    def guard_manifest(self):
        return self._guards

    def function(self, name):
        return {"name": name, "domain": "d", "notes": [],
                "returns_shape": {"kind": "object",
                                  "fields": [{"name": f} for f in self._shapes]}}

    def stats(self):
        return {"functions": 1}


INVENTORY = {"functions": []}


def test_drift_default_is_green_and_machine_readable(capsys):
    mod = _load()
    assert mod.main(["drift", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pass"] is True
    assert result["errors"] == []
    # 批 A/B/C（2026-11-16）后 shape 声明滞后清零；WARN 的发现能力由
    # test_collect_drift_catches_bad_declarations 与 strict monkeypatch 用例守护，
    # 这里只要求默认档不拦、报告机器可读。
    assert result["warnings"] == []
    assert result["strict"] is False
    info = result["info"]
    # guarded 65 = 63 + toplist.by_date/by_symbol（金额 ranges，批次3 2026-11-19）；
    # functions 316 = 311 + toplist 3 + futures.mapping/fmt_maps（mapping 无数值字段不守护）
    assert info["guard_declared"] == 65
    assert info["functions"] == 316
    assert info["markets"]["total"] == 2983
    assert info["markets"]["declared"] == 728
    assert info["markets"]["undeclared"] == 2255
    assert info["markets"]["by_market"] == {"cn": 658, "hk": 26, "us": 44}
    # .internal/UNIT_AUDIT.md 是本机联网 matrix 产物，不进 git 跟踪面；
    # CI 里不存在时 sections 为 0，只能要求非负，不能假设报告一定在。
    assert isinstance(info["matrix_sections"], int)
    assert info["matrix_sections"] >= 0
    if (REPO / ".internal" / "UNIT_AUDIT.md").is_file():
        assert info["matrix_sections"] >= 1


def test_drift_does_not_require_credentials(monkeypatch):
    """drift 必须在构造 Client 之前分流：离线静态检查不该要凭证。"""
    mod = _load()

    def boom(*_a, **_kw):
        raise AssertionError("drift 不应构造 Client.from_env()")

    monkeypatch.setattr(mod.wmshare.Client, "from_env", staticmethod(boom))
    assert mod.main(["drift"]) == 0


def test_drift_is_green_when_audit_report_missing(monkeypatch, capsys, tmp_path):
    """CI 不携带 .internal/UNIT_AUDIT.md（本机联网 matrix 产物），drift 仍须全绿。

    回归锚点：曾有一版断言 matrix_sections >= 1，导致三个 Python 版本的 CI 全红。
    """
    mod = _load()
    monkeypatch.setattr(mod, "REPORT_PATH", tmp_path / "missing.md")
    assert mod.main(["drift", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["info"]["matrix_sections"] == 0
    assert result["errors"] == [] and result["pass"] is True


def test_strict_upgrades_shape_warnings_to_failure(monkeypatch, capsys):
    """存量 WARN 已清零（drift 默认档 exit 0）；用注入的 WARN 验证 strict 升级语义。"""
    mod = _load()
    # 当前仓库状态：零 WARN，strict 也应全绿
    assert mod.main(["drift", "--strict", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True and out["warnings"] == []

    # 注入一条 WARN：strict 必须升级为失败
    real = mod.collect_drift

    def with_warning(cat, inventory_doc, metrics_doc, strict=False):
        result = real(cat, inventory_doc, metrics_doc, strict=strict)
        result["warnings"] = ["shape: x.fn units 字段 ['ghost'] 不在 returns_shape"]
        result["pass"] = False
        return result

    monkeypatch.setattr(mod, "collect_drift", with_warning)
    assert mod.main(["drift", "--strict", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is False and out["strict"] is True and out["warnings"]


def test_collect_drift_catches_bad_declarations():
    mod = _load()
    guards = {"x.fn": {
        "units": {"ghost": "percent", "pct": "percent", "volume": "lot"},
        "ranges": {"ghost": [-1, 1]},
        "checks": ["nope", "volume_amount"],
    }}
    result = mod.collect_drift(FakeCat(guards, ["pct", "volume"]), INVENTORY,
                               {"metrics": [{"code": "$A", "markets": ["cn"]},
                                            {"code": "$B"}]})
    assert result["pass"] is False
    assert any("未注册" in e for e in result["errors"])
    assert any("percent 声明缺 ranges" in e for e in result["errors"])
    assert any("units 字段 ['ghost']" in w for w in result["warnings"])
    assert any("ranges 字段 ['ghost']" in w for w in result["warnings"])
    assert result["info"]["markets"]["declared"] == 1
    assert result["info"]["markets"]["undeclared"] == 1
    assert result["info"]["markets"]["by_market"] == {"cn": 1}


def test_collect_drift_clean_fixture_is_green():
    mod = _load()
    guards = {"x.fn": {"units": {"pct": "percent"},
                       "ranges": {"pct": [-1, 1]},
                       "checks": ["volume_amount"]}}
    result = mod.collect_drift(FakeCat(guards, ["pct"]), INVENTORY,
                               {"metrics": [{"code": "$A", "markets": ["cn", "us"]},
                                            {"code": "$B", "markets": ["cn"]}]})
    assert result["errors"] == [] and result["warnings"] == []
    assert result["pass"] is True
    assert result["info"]["markets"]["by_market"] == {"cn": 2, "us": 1}


def test_exempt_note_suppresses_missing_range_error():
    mod = _load()
    guards = {"x.fn": {"units": {"pct": "percent"}}}
    cat = FakeCat(guards, ["pct"], domain_notes=["量级豁免：合并值≈0 时合法地极大"])
    result = mod.collect_drift(cat, INVENTORY, {"metrics": []})
    assert result["errors"] == [] and result["pass"] is True


def test_shape_fields_collects_nested_object_fields():
    """嵌套守护字段（segments.query_region 型 {domestic: {tr, ...}}）不算滞后。

    运行时 walk 会下探未声明键的嵌套容器，守护按字段名匹配到嵌套层；
    _shape_fields 须递归收集，否则合法声明被误报为 WARN。
    """
    mod = _load()
    shape = {"kind": "object", "fields": [
        {"name": "source", "type": "string"},
        {"name": "domestic", "type": "object", "fields": [
            {"name": "tr", "type": "float64"},
            {"name": "pct", "type": "float64"},
        ]},
        {"name": "rows", "type": "array",
         "items": {"kind": "object", "fields": [{"name": "margin"}]}},
    ]}
    assert mod._shape_fields(shape) == {"source", "domestic", "rows",
                                        "tr", "pct", "margin"}
    assert mod._shape_fields(None) == set()


def test_collect_drift_nested_guard_fields_are_not_stale():
    mod = _load()
    guards = {"x.fn": {"ranges": {"tr": [-1e13, 1e13], "pct": [0, 1],
                                  "ghost": [0, 1]}}}
    cat = FakeCat(guards, [])
    cat._shapes = []
    cat.function = lambda name: {"name": name, "domain": "d", "notes": [],
                                 "returns_shape": {"kind": "object", "fields": [
                                     {"name": "domestic", "type": "object",
                                      "fields": [{"name": "tr"},
                                                 {"name": "pct"}]}]}}
    result = mod.collect_drift(cat, INVENTORY, {"metrics": []})
    assert result["errors"] == []
    assert result["warnings"] == ["shape: x.fn ranges 字段 ['ghost'] 不在 returns_shape"
                                  "（疑似上游 shape 声明滞后，需逐函数核实 returns.shape 覆盖）"]
