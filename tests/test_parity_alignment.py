"""首批形态对齐接口的离线契约测试（不联网、不需凭证）。

覆盖四件事：列转行数值锚点、截面字段与指标码一一对应、所有指标码经目录校验、
字段绑定的**语义**（scope/topic/unit_kind 对齐 + 有 curated 守护 + 不是聚合/别名码）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wmshare.api import BASIC_FIELDS, FINANCIAL_FIELDS, FRIENDLY_INDEX
from wmshare.catalog import load

CAT = load()
SIDECAR = (Path(__file__).resolve().parents[1] / "src" / "wmshare" / "_catalog"
           / "generated" / "metric_taxonomy.json")
TAX = {r["code"]: r for r in json.loads(SIDECAR.read_text(encoding="utf-8"))["metrics"]}

# 字段语义 <-> (scope, topic, unit_kind)。绑定错码（行业聚合、无窗口均值、
# 扣非 EPS）会在这一层直接暴露，而不是等用户算出错误估值才被发现。
FIELD_INTENT: dict[str, tuple[str, str, str]] = {
    "pe_ttm": ("stock", "valuation", "multiple"),
    "pb": ("stock", "valuation", "multiple"),
    "turnover_rate": ("stock", "quote", "ratio"),
    "total_mv": ("stock", "quote", "money"),
    "roe_ttm": ("stock", "profitability", "ratio"),
    "roe_avg": ("stock", "profitability", "ratio"),
    "eps_ttm": ("stock", "scale", "per_share"),
}

# 明确不能绑的码：行业聚合族、纯别名（点值）、无固定窗口均值、扣非 EPS。
FORBIDDEN = {
    "$ID_MV_LAST": "行业/指数聚合（SUMS），单标的返回 nil",
    "$PB": "纯别名 = $PB_TTM 点值，不是最新截面",
    "$ROE_AVG": "全部 Q4 历史平均，无固定窗口",
    "$EPS_DPPR_TTM_LAST": "扣非 EPS，字段名 eps_ttm 会误导",
}


class _Session:
    """只满足 Client 构造；本文件的用例全部替换掉 call / eval_result。"""

    def post(self, *args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("离线用例不得发起网络请求")


def _client():
    from wmshare.client import Client
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=CAT, session=_Session())


def test_field_codes_all_registered():
    """零编造：每个字段绑定的指标码都必须在指标目录内。"""
    for field, code in {**BASIC_FIELDS, **FINANCIAL_FIELDS}.items():
        assert code.startswith("$")
        assert CAT.metric(code) is not None, f"{field} 的指标码未登记：{code}"


def test_field_sets_are_fixed_and_disjoint():
    assert list(BASIC_FIELDS) == ["pe_ttm", "pb", "turnover_rate", "total_mv"]
    assert list(FINANCIAL_FIELDS) == ["roe_ttm", "roe_avg", "eps_ttm"]
    assert not (set(BASIC_FIELDS) & set(FINANCIAL_FIELDS))


@pytest.mark.parametrize("field,code", sorted({**BASIC_FIELDS, **FINANCIAL_FIELDS}.items()))
def test_field_code_semantics(field, code):
    """绑定码的 scope/topic/unit_kind 必须与字段语义一致。"""
    assert code not in FORBIDDEN, f"{field} 绑定了禁用码 {code}：{FORBIDDEN.get(code)}"
    row = TAX[code]
    actual = (row["scope"], row["topic"], row["unit_kind"])
    assert actual == FIELD_INTENT[field], f"{field}→{code} 分类不匹配：{actual}"


@pytest.mark.parametrize("field,code", sorted({**BASIC_FIELDS, **FINANCIAL_FIELDS}.items()))
def test_field_code_has_catalog_guard(field, code):
    """对外字段必须有 curated 守护（range），否则量级错误会静默通过。"""
    assert CAT.metric_meta(code) is not None, (
        f"{field}→{code} 没有 curated units/range 声明；"
        "请先把它加进 fund.indicators.yaml 的对应指标组")


def test_cbond_bars_column_to_row_numeric_anchor(monkeypatch):
    """数值锚点：列式窗口按位对齐转成行式，date 取采样名前 10 位。"""
    cli = _client()
    raw = {
        "samplingName": ["2026-11-13 00:00:00", "2026-11-12 00:00:00"],
        "open": [101.0, 100.0],
        "high": [103.0, 102.0],
        "low": [100.0, 99.0],
        "close": [102.0, 101.0],
        "volume": [1000, 900],
        "amount": [102000.0, 90900.0],
    }
    seen: dict = {}

    def fake_call(name, **kwargs):
        seen["name"], seen["kwargs"] = name, kwargs
        return raw

    monkeypatch.setattr(cli, "call", fake_call)
    rows = cli.cbond.bars("113050", n=2)
    assert seen["name"] == "cbond.kline_window"
    assert seen["kwargs"] == {"code": "113050", "n": 2}
    assert rows == [
        {"date": "2026-11-13", "open": 101.0, "high": 103.0, "low": 100.0,
         "close": 102.0, "volume": 1000, "amount": 102000.0},
        {"date": "2026-11-12", "open": 100.0, "high": 102.0, "low": 99.0,
         "close": 101.0, "volume": 900, "amount": 90900.0},
    ]


def test_cbond_bars_handles_missing_column_and_empty(monkeypatch):
    """缺列补 None、空窗口返回空列表、非 MAP 形态原值透传。"""
    cli = _client()
    monkeypatch.setattr(cli, "call",
                        lambda name, **kw: {"samplingName": ["2026-11-13"], "close": [102.0]})
    assert cli.cbond.bars("113050") == [
        {"date": "2026-11-13", "open": None, "high": None, "low": None,
         "close": 102.0, "volume": None, "amount": None},
    ]
    monkeypatch.setattr(cli, "call", lambda name, **kw: {"samplingName": []})
    assert cli.cbond.bars("113050") == []
    monkeypatch.setattr(cli, "call", lambda name, **kw: ["opaque"])
    assert cli.cbond.bars("113050") == ["opaque"]


def test_basic_and_financials_return_named_fields(monkeypatch):
    """截面接口返回固定字段名，且确实批量取了绑定的指标码。"""
    cli = _client()
    seen: list[str] = []

    def fake_eval(xs, **kwargs):
        seen.append(xs)
        return {c: 0.15 for c in list(BASIC_FIELDS.values()) + list(FINANCIAL_FIELDS.values())}

    monkeypatch.setattr(cli, "eval_result", fake_eval)
    basic = cli.indicator.basic("600519")
    fin = cli.indicator.financials("600519")
    assert list(basic) == list(BASIC_FIELDS)
    assert list(fin) == list(FINANCIAL_FIELDS)
    assert all(v == 0.15 for v in list(basic.values()) + list(fin.values()))
    for code in BASIC_FIELDS.values():
        assert any(code in xs for xs in seen), f"未取数 {code}"


def test_new_methods_registered_in_friendly_index():
    """三个新方法必须进核心接口索引，否则文档 / OpenAPI 生成物会漏。"""
    ids = {(ns, m) for _, ns, m, _, _ in FRIENDLY_INDEX}
    assert {("cbond", "bars"), ("indicator", "basic"),
            ("indicator", "financials")} <= ids
