"""audit_units 离线冒烟：罐头客户端（数值取自真实 probe 样本）驱动审计全流程。

不联网；分别验证全通过（退出码 0）与违例（退出码 1，报告含 FAIL 行）。
"""
import types

import pytest

import wmshare
from tools import audit_units


def audit_client(mv_free=None, bonus_rate=0.0396):
    """构造通过全部检查的罐头客户端；可用参数注入违例。"""
    bar = {"date": "2026-10-20", "close": 1331.88, "volume": 3413500.0,
           "amount": 4525398959.0, "percent": 0.005215}
    metrics = {"$CLOSE_LAST": 1337.0, "$MV_LAST": 1.67e12,
               "$MV_FREE_LAST": mv_free if mv_free is not None else 1.6e12,
               "$AMOUNT_LAST": 4.5e9, "$BONUS_TTM": 6.5e10,
               "$BONUS_RATE_TTM_LAST": bonus_rate, "$ROE_TTM_LAST": 0.332,
               "$TL_RATE_LAST": 0.152, "$TR_TTM_LAST": 1.73e11,
               "$NP_TTM_LAST": 8.4e10}

    class Client:
        def __init__(self):
            self.kline = types.SimpleNamespace(bars=lambda *a, **k: [dict(bar)])
            self.dividend = types.SimpleNamespace(
                yield_ttm=lambda *a, **k: bonus_rate)
            self.indicator = types.SimpleNamespace(metrics=lambda s, codes: dict(metrics))
            self.statements = types.SimpleNamespace(compare=lambda *a, **k: [])
            self.catalog = wmshare.load()

        @classmethod
        def from_env(cls, *a, **k):
            return cls()

        def call(self, name, **kw):
            return [dict(bar)]

    return Client


def test_audit_passes_on_canned_data(monkeypatch, capsys):
    monkeypatch.setattr(audit_units.wmshare, "Client", audit_client())
    rc = audit_units.main(["--universe", "600519,000001", "--etf", "510300",
                           "--compare-syms", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAIL" not in out
    assert "kline.volume_amount" in out and "cross.yield_identity" in out
    assert "510300" in out  # ETF 也在审计范围


def test_audit_fails_on_violation(monkeypatch, capsys):
    monkeypatch.setattr(audit_units.wmshare, "Client", audit_client(mv_free=9.9e12))
    rc = audit_units.main(["--universe", "600519", "--etf", "", "--compare-syms", "0"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "indicator.mv_free_le_mv" in out


def test_audit_reports_sdk_data_error(monkeypatch, capsys):
    from wmshare import DataError

    class Boom(audit_client()):
        def call(self, name, **kw):
            raise DataError("kline.query_bars: 字段 volume 超出声明范围 [0, 1e12]"
                            "（量级守护）。如需原始口径：_raw=True 或 _units=\"native\"",
                            code="range")

    monkeypatch.setattr(audit_units.wmshare, "Client", Boom)
    rc = audit_units.main(["--universe", "600519", "--etf", "", "--compare-syms", "0"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "DataError" in out


@pytest.mark.parametrize("empty", ["", " "])
def test_audit_empty_universe_ok(monkeypatch, empty):
    monkeypatch.setattr(audit_units.wmshare, "Client", audit_client())
    assert audit_units.main(["--universe", empty, "--etf", "",
                             "--compare-syms", "0"]) == 0


# ---- matrix：全量逐字段审计（离线罐头） ----

def matrix_client(monorow: dict | None = None, strip_ranges_from: str | None = None):
    """罐头客户端：call() 恒返单行数组（数值取自真实 probe 量级）。

    strip_ranges_from：把该函数的 ranges 声明从目录桩里剥掉，用于测 WRONG-DECL 路径
    （有 range 的小口径字段走一致性判定，纯量级启发式只对无 range 的声明生效）。
    """
    row = monorow if monorow is not None else {
        "accum_pledge_tsr": 30.0,      # 百分数原值（声明 percent → DECLARED-OK）
        "pledgor_name": "贵州茅台酒厂集团",
        "pledge_num": 1.7e8,
    }
    real = wmshare.load()

    class CatalogShim:
        def function(self, name):
            fn = dict(real.function(name))
            if strip_ranges_from and name == strip_ranges_from:
                fn = {k: v for k, v in fn.items() if k != "ranges"}
            return fn

        def __getattr__(self, attr):
            return getattr(real, attr)

    class Client(audit_client()):
        def __init__(self):
            super().__init__()
            self._real_catalog = real
            self.catalog = CatalogShim()

        def call(self, name, **kw):
            return [dict(row)]

    return Client


def test_matrix_classifies_declared_percent(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(audit_units.wmshare, "Client", matrix_client())
    monkeypatch.setattr(audit_units, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(audit_units, "REPORT_PATH", tmp_path / "UNIT_AUDIT.md")
    rc = audit_units.main(["matrix", "--only", "query_pledge_detail"])
    report = (tmp_path / "UNIT_AUDIT.md").read_text(encoding="utf-8")
    assert "DECLARED-OK" in report          # accum_pledge_tsr=30.0 原值百分数，声明正确
    assert "RAW-NOTED" in report            # hold_num 金额/股数语义未声明 → 人工判定项
    assert rc == 0


def test_matrix_flags_wrong_declaration(monkeypatch, capsys, tmp_path):
    # 原值已是小数（0.3）却声明 percent 且无 range 兜底 → WRONG-DECL，退出码 1
    monkeypatch.setattr(audit_units.wmshare, "Client", matrix_client(
        {"accum_pledge_tsr": 0.3, "pledge_num": 1.7e8},
        strip_ranges_from="equity.query_pledge_detail"))
    monkeypatch.setattr(audit_units, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(audit_units, "REPORT_PATH", tmp_path / "UNIT_AUDIT.md")
    rc = audit_units.main(["matrix", "--only", "query_pledge_detail"])
    report = (tmp_path / "UNIT_AUDIT.md").read_text(encoding="utf-8")
    assert "WRONG-DECL" in report and "percent 换算会再除 100" in report
    assert rc == 1


def test_matrix_caches_and_skips_refetch(monkeypatch, capsys, tmp_path):
    calls = {"n": 0}
    base = matrix_client()

    class Counting(base):
        def call(self, name, **kw):
            calls["n"] += 1
            return super().call(name, **kw)

    monkeypatch.setattr(audit_units.wmshare, "Client", Counting)
    monkeypatch.setattr(audit_units, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(audit_units, "REPORT_PATH", tmp_path / "UNIT_AUDIT.md")
    audit_units.main(["matrix", "--only", "query_pledge_detail"])
    first = calls["n"]
    audit_units.main(["matrix", "--only", "query_pledge_detail"])
    assert calls["n"] == first              # 第二次全部命中缓存，不再取数
