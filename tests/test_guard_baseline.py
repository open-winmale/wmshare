"""P1 #6/#10 防回归基线：覆盖率、发现项与零守护域清单不得恶化。

**不刷覆盖率**：零守护域多为公告/文本类，补 ranges 必须有实测分布
（test_unit_meta 规则 2：range 界须以实测分布为准，不凭空猜界）。
本测试把现状冻结成下限：后续合同化批次只能让数字变好，不能悄悄变差。
"""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD_TOOL = REPO / "tools" / "guard_coverage.py"
AUDIT_TOOL = REPO / "tools" / "audit_units.py"
AUDIT_REPORT = REPO / ".internal" / "UNIT_AUDIT.md"

# 实测（2026-11-14）：8 个有函数但 guarded=0 的域；fund.indicators 为 0 函数域，不计。
ZERO_GUARD_BASELINE = {
    "disc.bonus", "disc.filings", "disc.notice", "disc.workout",
    "market.macro", "market.margin", "market.moneyflow", "market.stocks",
}
DRIFT_WARN_BASELINE = 29


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_guard_coverage_cannot_regress():
    mod = _load(GUARD_TOOL, "guard_coverage_baseline")
    result = mod.collect(mod.DEFAULT_DOMAINS)
    assert result["functions"] == 288
    assert result["guarded"] >= 50
    assert result["ratio"] >= 0.173611
    zero = {name for name, stat in result["per_domain"].items()
            if stat["functions"] > 0 and stat["guarded"] == 0}
    assert zero <= ZERO_GUARD_BASELINE, f"新增零守护域：{sorted(zero - ZERO_GUARD_BASELINE)}"


def test_drift_errors_stay_zero_and_warnings_cannot_grow(capsys):
    mod = _load(AUDIT_TOOL, "audit_units_baseline")
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert mod.main(["drift", "--json"]) == 0
    result = json.loads(buf.getvalue())
    assert result["errors"] == []
    assert len(result["warnings"]) <= DRIFT_WARN_BASELINE, (
        "shape 声明滞后项变多，说明新声明未同步 returns.shape")


def test_audit_report_has_no_wrong_declarations():
    """审计发现项：WRONG-DECL 必须为零；FIX-PERCENT 只剩已判定不修的 1 项。"""
    if not AUDIT_REPORT.is_file():
        return  # 报告由联网 matrix 生成，CI 外可能缺失
    text = AUDIT_REPORT.read_text(encoding="utf-8")
    summary = text.split("## 汇总")[-1]
    assert "WRONG-DECL" not in summary
    fix_line = next((l for l in summary.splitlines() if "FIX-PERCENT" in l), "")
    assert fix_line and int(fix_line.split(":")[-1].strip()) <= 1
