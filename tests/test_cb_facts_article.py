"""cb.facts 与 cb.article 测试：事实包结构与"缺条目即拒绝成稿"的纪律。

用一份最小的合成快照跑通全链路，断言链条上的关键不变量：
口径层单调、闸门计数自洽、榜单无被剔除债、成稿数字必须在 facts 里找得到。
"""
from __future__ import annotations

import re

import pytest

from wmshare.cb import article as A
from wmshare.cb import facts as F


def _row(code: str, name: str, price: float, prem: float, **kw) -> dict:
    base = {
        "bondCode": code, "bondName": name, "stockCode": "600000",
        "stockName": "浦发银行", "bondPrice": price, "premiumRatio": prem / 100.0,
        "remainSize": 5.0e9, "issueScale": 6.0e9, "expireDate": "2029-11-06",
        "redeemTrig": 13.0, "stockPrice": 10.0, "convertPrice": 10.0,
        "redeemValue": 110.0, "couponIr": 0.015,
        "couponExplain": "第一年 0.20%、第二年 0.30%、第三年 0.50%",
        "transferValue": round(100.0 / (1 + prem / 100.0), 2),
        "resetFloor": 8.8, "asOf": "2026-11-06",
    }
    base.update(kw)
    return base


@pytest.fixture()
def payload() -> dict:
    rows = [
        _row("110001", "甲转债", 95.0, 2.0),          # 最低双低，偏债候选
        _row("110002", "乙转债", 110.0, 8.0),
        _row("110003", "丙转债", 120.0, 15.0),
        _row("110004", "丁转债", 105.0, 5.0, stockName="ST某某"),   # G2
        _row("110005", "戊转债", 102.0, 3.0, callHits=30),          # G3 met15
        _row("110006", "己转债", 100.0, 4.0, expireDate="2027-01-01"),  # G3 near
    ]
    events = [{"bond_code": "110002", "bond_name": "乙转债",
               "deal_type": "no_reset", "announce_date": "2026-10-01",
               "title": "关于不向下修正转股价格的公告", "stock_code": "600000"},
              {"bond_code": "110003", "bond_name": "丙转债",
               "deal_type": "reset_proposal", "announce_date": "2026-11-06",
               "title": "董事会提议向下修正", "stock_code": "600000",
               "meeting_date": "2026-11-20"}]
    return F.build_facts(rows, events, "2026-11-06")


def test_caliber_layers_are_monotonic(payload):
    layers = F.caliber_layers(
        [_row("110001", "甲", 95.0, 2.0), _row("110002", "乙", None, 3.0)],
        "2026-11-06", passed_n=1)
    assert layers["gate_base"] >= layers["quote_base"] >= layers["in_market"]


def test_gate_counts_reconcile(payload):
    gates = payload["gates"]
    assert sum(gates["ruleHits"].values()) == gates["excludedN"]
    assert gates["passedN"] + gates["excludedN"] == gates["baseN"]
    for reason, names in gates["byReason"].items():
        assert gates["ruleHits"][reason] == len(names)


def test_top_excludes_gated_bonds_and_is_sorted(payload):
    codes = [t["bondCode"] for t in payload["top"]]
    assert "110004" not in codes      # ST
    assert "110005" not in codes      # 已满足强赎
    assert "110006" not in codes      # 剩余不足半年
    dls = [t["double_low"] for t in payload["top"]]
    assert dls == sorted(dls)


def test_every_top_bond_has_core_facts(payload):
    ids = {f["id"] for f in payload["facts"] + payload["derived"]}
    for t in payload["top"]:
        code = t["bondCode"]
        for prefix in ("price", "prem", "dl", "nat", "cs", "rs"):
            assert f"{prefix}_{code}" in ids, f"缺 {prefix}_{code}"


def test_facts_carry_provenance(payload):
    for f in payload["facts"]:
        assert f["sources"] and f["as_of"] == "2026-11-06"
        assert f["value_text"] not in (None, "")


def test_probe_channel_statistics():
    closes = [100.0, 102.0, 98.0, 101.0, 99.0]
    ch = F.probe(closes, ["2026-11-02", "2026-11-03", "2026-11-04",
                          "2026-11-05", "2026-11-06"])
    assert ch["series_n"] == 5
    assert ch["current"] == 99.0
    assert ch["min"] == 98.0 and ch["max"] == 102.0
    assert ch["lower2"] < ch["lower1"] < ch["avg"] < ch["upper1"] < ch["upper2"]
    assert -2.5 < ch["z"] < 2.5
    assert 0.0 < ch["pct"] <= 1.0


def test_redeem_from_text_only_accepts_yuan_amount():
    assert F.redeem_from_text("到期赎回价为 112 元") == 112.0
    assert F.redeem_from_text("到期按面值的 110% 赎回") is None
    assert F.redeem_from_text(None) is None


# ---------------- 成稿器 ----------------
def test_article_refuses_when_fact_missing(payload):
    broken = dict(payload)
    broken["derived"] = [d for d in broken["derived"] if d["id"] != "mean_dl"]
    fa = A.Facts(broken)
    with pytest.raises(LookupError, match="mean_dl"):
        A.build_source(fa, "20261107", "2026-11-06", "c")


def test_article_contains_no_number_outside_facts(payload):
    """正文里出现的价格/百分比，必须能在 facts 的 value_text 里找到。"""
    fa = A.Facts(payload)
    src = A.build_source(fa, "20261107", "2026-11-06", "day20261107cb")
    known = {str(f["value_text"]) for f in payload["facts"] + payload["derived"]}
    known |= {str(t["double_low"]) for t in payload["top"]}
    # 只抽查「价格(元)」列：形如 | 95.00 | 的单元格
    for cell in re.findall(r"\| (\d+\.\d{2}) \|", src):
        assert any(cell in k for k in known), f"成稿出现无法追溯的数字 {cell}"


def test_article_structure_and_compliance(payload):
    fa = A.Facts(payload)
    src = A.build_source(fa, "20261107", "2026-11-06", "day20261107cb")
    for heading in ("## 01 今日温度", "## 02 双低榜", "## 03 三道闸",
                    "## 04 条款日历", "## 05 异动观察", "## 06 口径与复现"):
        assert heading in src
    for banned in ("目标价", "建议买入", "建议卖出", "满仓", "抄底"):
        assert banned not in src
    assert "不构成投资建议" in src


def test_article_rejects_empty_top():
    fa = A.Facts({"facts": [], "derived": [], "top": []})
    with pytest.raises(ValueError):
        A.build_source(fa, "20261107", "2026-11-06", "c")


def test_wechat_wrapper_adds_summary_and_link(payload):
    fa = A.Facts(payload)
    src = A.build_source(fa, "20261107", "2026-11-06", "day20261107cb")
    out = A.build_wechat(src, "day20261107cb", A.build_summary(fa))
    assert out.startswith(src.split("\n")[0])
    assert "摘要：" in out
    assert "utm_campaign=day20261107cb" in out
    assert A.BYLINE not in out
