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
    assert result["warnings"]  # shape 声明滞后是发现项，不掩盖
    assert result["strict"] is False
    info = result["info"]
    assert info["guard_declared"] == 50
    assert info["functions"] == 288
    assert info["markets"]["total"] == 2752
    assert info["markets"]["declared"] == 569
    assert info["markets"]["undeclared"] == 2183
    assert info["markets"]["by_market"] == {"cn": 498, "hk": 25, "us": 46}
    assert info["matrix_sections"] >= 1


def test_drift_does_not_require_credentials(monkeypatch):
    """drift 必须在构造 Client 之前分流：离线静态检查不该要凭证。"""
    mod = _load()

    def boom(*_a, **_kw):
        raise AssertionError("drift 不应构造 Client.from_env()")

    monkeypatch.setattr(mod.wmshare.Client, "from_env", staticmethod(boom))
    assert mod.main(["drift"]) == 0


def test_strict_upgrades_shape_warnings_to_failure(capsys):
    mod = _load()
    assert mod.main(["drift", "--strict", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["pass"] is False and result["strict"] is True
    assert result["warnings"]


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
