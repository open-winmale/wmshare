"""单位口径的离线锚点：台账、分类、恒等式一旦漂移必须立刻红。

这些用例不依赖网络，但用真实 live 值（2026-11-13，600519）做期望，
因此同时是「上游改了单位」和「我们改坏了分类」的回归网。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from wmshare.catalog import load

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "src" / "wmshare" / "_catalog"
UNITS = CATALOG / "units.yaml"
SIDECAR = CATALOG / "generated" / "metric_taxonomy.json"
LEDGER = yaml.safe_load(UNITS.read_text(encoding="utf-8"))
TAX = {r["code"]: r for r in json.loads(SIDECAR.read_text(encoding="utf-8"))["metrics"]}
CAT = load()


def test_ledger_covers_volume_family_as_lot():
    """指标层成交量是「手」——5 个码必须登记（2.0 起登记即默认换算为股）。"""
    for code in ("$VOLUME", "$VOLUME_DAY", "$VOLUME_LAST", "$VOLUME_NR_DAY",
                 "$VOLUME_AR_DAY"):  # 2026-11-18 补漏：后复权量同口径
        entry = LEDGER["overrides"][code]
        assert entry["native_unit"] == "lot", f"{code} 应登记为 lot"
        assert entry["base_unit"] == "shares"
        assert "手" in entry["note"]


def test_finish_metric_converts_ledger_codes_to_base():
    """2.0 单位标准化：台账登记码经 finish_metric 默认换算到基础单位。"""
    from wmshare.units import finish_metric
    # 成交量：手 → 股（×100）；range 按原生口径标注（手），同步缩放后校验
    meta = CAT.metric_meta("$VOLUME_LAST")
    assert meta is not None and meta["unit"] is None
    assert finish_metric(38330, meta, code="$VOLUME_LAST") == 3833000.0
    # 台账兜底码（非精选）：百分数 → 小数
    assert finish_metric(1.76, None, code="$ROC_TTM") == pytest.approx(0.0176)
    # native=True 逃生口：原值透传
    assert finish_metric(38330, meta, code="$VOLUME_LAST", native=True) == 38330
    assert finish_metric(1.76, None, code="$ROC_TTM", native=True) == 1.76


def test_ledger_convert_macro_codes():
    """宏观房地产 4 码亿元→元；台账外的码（$CPI 点）原样透传。"""
    from wmshare.units import ledger_convert
    assert ledger_convert("$RE_INVEST", 1234.5) == pytest.approx(1.2345e11)
    assert ledger_convert("re_value", 999.9) == pytest.approx(9.999e10)  # 大小写/$ 前缀可省
    assert ledger_convert("$CPI", 101.5) == 101.5  # 未登记码不换算
    assert ledger_convert("$RE_INVEST", None) is None


def test_volume_codes_classified_as_shares():
    for code in ("$VOLUME", "$VOLUME_DAY", "$VOLUME_LAST", "$VOLUME_NR_DAY",
                 "$VOLUME_AR_DAY"):
        assert TAX[code]["unit_kind"] == "shares", code
        assert TAX[code]["topic"] == "quote", code


def test_mv_last_is_yuan_not_yi_yuan():
    """$MV_LAST 值已是元（close × 总股本，live 实测精确相等）；cn 的 (亿) 是命名遗留。"""
    mv = TAX["$MV_LAST"]
    assert mv["unit_kind"] == "money"
    assert mv["code"] not in LEDGER["overrides"], "值已是基础单位，不该进台账"
    meta = CAT.metric_meta("$MV_LAST")
    assert meta and meta["unit"] is None, "不应声明 unit 换算（否则值会被再 ×1e8）"


def test_macro_real_estate_is_yi_yuan():
    """宏观房地产 4 码原值就是亿元。"""
    for code in ("$RE_INVEST", "$RE_INVEST_YTD", "$RE_VALUE", "$RE_VALUE_YTD"):
        assert LEDGER["overrides"][code]["native_unit"] == "yi_yuan", code


def test_unnormalized_percent_codes_are_registered():
    for code in ("$ROC_TTM", "$ROC_TTM_LAST",  # 2026-11-18 补漏：_LAST 变体同口径
                 "$BONUS_FUNDS_TOTAL_RATE"):
        assert LEDGER["overrides"][code]["native_unit"] == "percent", code


def test_multiple_units_not_mislabeled_ratio():
    """「市盈率/市净率/…」返回值是倍数；曾因「率」字被误标 ratio（57 码）。"""
    for code in ("$PE_TTM_LAST", "$PB_TTM_LAST", "$PS_TTM_LAST", "$PCF_TTM_LAST",
                 "$EV_EBITDA", "$PR_LAST", "$ID_PB_TTM_LAST", "$IDW_PE_LAST",
                 "$ID_PE_TTM_DPPR", "$ID_PE_TTM_TOTAL_LAST"):
        assert TAX[code]["unit_kind"] == "multiple", code


def test_ttm_dependent_codes_are_period_ttm():
    """分母是 TTM 流量的码，period 必须是 ttm（不能标 latest_report）。"""
    for code in ("$PE", "$PE_TTM_LAST", "$EV_EBITDA", "$PR_LAST", "$BE_RATE",
                 "$PE_TTM_DPPR_LAST"):
        assert TAX[code]["period"] == "ttm", code


def test_alias_follows_target_period():
    """纯别名 METRIC($A, $B) 的 period 必须与目标一致（$PE→$PE_TTM 等）。"""
    pairs = [("$PE", "$PE_TTM"), ("$PB", "$PB_TTM"), ("$VOLUME", "$VOLUME_DAY"),
             ("$AMOUNT", "$AMOUNT_DAY"), ("$MA120", "$AVG_DAY_120")]
    for alias, target in pairs:
        assert TAX[alias]["period"] == TAX[target]["period"], f"{alias} vs {target}"
        assert TAX[alias]["unit_kind"] == TAX[target]["unit_kind"], f"{alias} vs {target}"


def test_noadjust_caliber_not_mixed_with_adjusted():
    """「不复权」包含「复权」二字，不能同时命中 adjusted。"""
    assert TAX["$VOLUME_NR_DAY"]["caliber"] == ["unadjusted"]
    assert "adjusted" not in TAX["$VOLUME_NR_DAY"]["caliber"]


def test_parent_equity_codes_are_parent_caliber():
    """$SE / $SE_NOGW / $NPTS 都是归母口径，不是「合并」。"""
    assert TAX["$PB_NOGW_LAST"]["caliber"] == ["parent"]
    assert "consolidated" not in TAX["$PB_NOGW_LAST"]["caliber"]


def test_turnover_rate_matches_volume_identity():
    """换手率恒等式（live 实测）：$VOLUME_DAY*100/流通股本 == $TURNOVER_RATE。

    这条同时锁住两件事：成交量是手（×100 才成立），以及换手率是小数。
    """
    volume, free, turnover = 38330, 1250081601, 0.003066199836021745
    assert volume * 100 / free == pytest.approx(turnover, rel=1e-9)
    # 若成交量被改成股，这个比值会差 100 倍
    assert volume / free == pytest.approx(turnover / 100, rel=1e-9)


def test_mv_equals_close_times_shares():
    """$MV_LAST == $CLOSE_LAST × $EQUITY_TOTAL_SHARES_LAST（live 实测精确相等）。"""
    close, shares, mv = 1435.26, 1250081601, 1794192118651.26
    assert close * shares == pytest.approx(mv, rel=1e-12)


def test_newly_curated_codes_have_meta():
    """本轮新增的 curated 码必须有 meta（否则对外字段没有量级守护）。"""
    for code in ("$PB_TTM_LAST", "$PE_TTM_LAST", "$TURNOVER_RATE_LAST",
                 "$VOLUME_LAST", "$VOLUME_DAY"):
        assert CAT.metric_meta(code) is not None, code


def test_basic_and_financials_bindings_are_not_aggregates():
    """对外字段不能绑定行业聚合族（$ID_*）——它们的语义是「该组求和」。"""
    from wmshare.api import BASIC_FIELDS, FINANCIAL_FIELDS
    for field, code in {**BASIC_FIELDS, **FINANCIAL_FIELDS}.items():
        assert TAX[code]["scope"] == "stock", f"{field}→{code}"


def test_cbond_bars_volume_is_zhang():
    """转债日线成交量是「张」（面值口径），不是股。

    live 实测 2026-11-13（123291）：close=132, volume=220864, amount=29107595，
    amount/close=220512 ≈ volume。若上游改成「手」或「股」，这条会立刻红。
    """
    facade = LEDGER["facades"]["cbond.bars"]
    assert facade["fields"]["volume"] == "zhang"
    assert facade["fields"]["close"] == "price"
    assert facade["fields"]["amount"] == "money"
    assert "amount" in facade["invariant"] and "volume" in facade["invariant"]
    close, volume, amount = 132, 220864, 29107595
    assert amount / close == pytest.approx(volume, rel=0.01), \
        "amount/close 应≈volume（张）；偏离说明成交量口径变了"

