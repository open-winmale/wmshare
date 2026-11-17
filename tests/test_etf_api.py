"""W3 护栏 5：ETF 组合门面的离线契约测试（9 方法全覆盖 + 三护栏回归）。

组合方法不进目录合同（test_contract 不覆盖），本文件是它们的主要离线质量门禁：
护栏 1 转义/limit、护栏 2 本地数值守护、护栏 3 错误分类、方法集合锁定。
每 view 一个 fake-session 单测（签名 + 生成脚本 + 数值锚点），注入与错误分支单列。

脚本侧 9 视图（含 fund_asset/etf_rank）的真实字段见 S3 的 skillhub_etf.xs 契约。
"""
from __future__ import annotations

import json

import pytest

from wmshare.api import COMPOSITE_METHODS, FRIENDLY_NAMESPACES
from wmshare.errors import ApiError, DataError, UsageError

EtfApi = FRIENDLY_NAMESPACES["etf"]
VIEWS = ("card", "nav", "share", "div", "portfolio", "profile", "premium", "asset", "rank")
_VIEW_FOR_METHOD = {"asset": "fund_asset", "rank": "etf_rank"}

# 每 view 一条数值锚点（fake 返回值含一个该 view 的特征数值字段，验证透传不丢）。
# 字段名与 script 侧各 build 的真实返回对齐（见 S3 的 etf.xs；改前务必核对，防假绿）。
ANCHORS = {
    "card": {"view": "card", "quote": {"close": 3.87}},
    "nav": {"view": "nav", "latest": {"unit_nav": 3.87}},
    "share": {"view": "share", "fd_share": 285.5299},     # 亿份（上游原值；SDK ×1e8）
    "div": {"view": "div", "rows": [{"amount": 0.052}]},
    "portfolio": {"view": "portfolio", "holdings": [{"code": "600519"}]},
    "profile": {"view": "profile", "profile": {"short_name": "沪深300ETF"}},
    "premium": {"view": "premium", "premium_pct": 0.25},
    "asset": {"view": "fund_asset", "stock_ratio": 96.3, "net_asset": 12.5},
    "rank": {"view": "etf_rank", "chg_w1": 2.15, "net_asset": 12.5},
}


class FakeSession:
    def __init__(self, result=None, exc=None):
        self.result = result if result is not None else {"ok": True, "view": "card"}
        self.exc = exc
        self.calls = []

    def eval_result(self, xs, **kw):
        self.calls.append({"xs": xs, "kw": kw})
        if self.exc is not None:
            raise self.exc
        return self.result


def _api(sess=None, result=None, exc=None):
    return EtfApi(sess or FakeSession(result, exc))


# ---- 护栏 5：9 view 全覆盖（签名 + 脚本 + 数值锚点）----
@pytest.mark.parametrize("view", VIEWS)
def test_every_view_builds_script_and_passes_result(view):
    anchor = dict(ANCHORS[view])
    anchor["ok"] = True
    sess = FakeSession(anchor)
    api = _api(sess)
    got = getattr(api, view)("cn.510300")
    # 2.0 统一信封：业务字段进 data，view 进 meta
    assert isinstance(got, dict) and got["ok"] is True
    assert got["meta"]["view"] == view  # meta 记 SDK 方法名；script view 见 xs 断言
    got = got["data"]
    # 生成脚本：require + return skhub.etf_build(字面量, view, mode, limit)
    xs = sess.calls[0]["xs"]
    assert len(xs) == 2
    assert xs[0] == 'xs.require("xs/skillhub/lib/init.xs")'
    line = xs[1]
    assert line.startswith("return skhub.etf_build(")
    assert json.dumps(_VIEW_FOR_METHOD.get(view, view)) in line  # 方法名→script view 映射
    assert json.dumps("510300") in line                          # normalize_symbol 去前缀
    assert sess.calls[0]["kw"] == {"symbol": "510300", "market": "cn"}


# ---- 护栏 1：转义（注入）与 limit 严格校验 ----
def test_injection_symbol_is_json_escaped():
    sess = FakeSession({"ok": True, "view": "card"})
    _api(sess).card('a" + "X')
    line = sess.calls[0]["xs"][1]
    # 注入串整体被 json.dumps 成单个字面量，不得拼出合法 XS 表达式
    assert json.dumps('A" + "X', ensure_ascii=False) in line
    assert 'etf_build("A" + "X"' not in line


@pytest.mark.parametrize("bad", ["abc", 0, 501, True, 1.5])
def test_limit_rejects_non_int_or_out_of_range(bad):
    with pytest.raises(UsageError):
        _api().rank("510300", limit=bad)


@pytest.mark.parametrize("bad", [0, -1, 501])
def test_limit_boundary_rejects(bad):
    with pytest.raises(UsageError):
        _api().rank("510300", limit=bad)


def test_limit_valid_injects_literal():
    sess = FakeSession({"ok": True, "view": "etf_rank"})
    _api(sess).rank("510300", limit=30)
    assert "30" in sess.calls[0]["xs"][1]


def test_unknown_view_and_mode_rejected():
    api = _api()
    with pytest.raises(UsageError):
        api._etf("bogus", "510300")
    with pytest.raises(UsageError):
        api._etf("card", "510300", mode="bogus")


# ---- 护栏 2：本地数值守护（DataError）----
@pytest.mark.parametrize("bad", [
    {"ok": True, "chg_w1": 2500},                    # 涨幅量级
    {"ok": True, "premium_pct": -500},               # 折溢价率越界
    {"ok": True, "net_asset": -1},                   # 规模非负
    {"ok": True, "fd_share": 1e15},                  # 份额越界（亿份，上限 1e6）
    {"ok": True, "fd_share": 1e7},                   # 旧 1e14 会放过 → 护栏有效性回归
    {"ok": True, "view": "fund_asset", "stock_ratio": 150},  # 占比越界
    {"ok": True, "view": "fund_asset", "stock_ratio": 80,
     "bond_ratio": 40},                              # 合计 >100
])
def test_guard_rejects_bad_magnitude(bad):
    view = "rank" if "chg_w1" in bad else ("asset" if bad.get("view") else "card")
    with pytest.raises(DataError):
        _api(FakeSession(bad))._guard_etf(bad, view)


@pytest.mark.parametrize("bad", [
    {"ok": False, "error": "NOT_ETF"},
    {"ok": False, "error": "NO_DATA"},
    {"ok": False},
])
def test_guard_rejects_not_ok(bad):
    with pytest.raises(DataError):
        _api(FakeSession(bad))._guard_etf(bad, "card")


def test_guard_skips_nil_without_touching():
    """落库 nil 字段跳过守护、不当 0（防坑 5：缓存未命中显式标注）。"""
    got = {"ok": True, "view": "rank", "chg_w1": None, "net_asset": None}
    assert _api(FakeSession(got))._guard_etf(got, "rank") is got


# ---- 护栏 3：错误分类 ----
@pytest.mark.parametrize("code,typ", [
    ("BAD_PARAM", UsageError),
    ("UNKNOWN_VIEW", UsageError),
    ("NOT_ETF", DataError),
    ("NO_DATA", DataError),
    ("INTERNAL", DataError),
])
def test_classify_etf_error(code, typ):
    assert isinstance(_api()._classify_etf_error(ApiError("x", code=code)), typ)


def test_eval_api_error_is_translated():
    sess = FakeSession(exc=ApiError("eval 失败: PARAM", code="PARAM"))
    with pytest.raises(UsageError):
        _api(sess).card("510300")


# ---- 护栏 5：方法集合锁定（防悄悄增删）----
def test_composite_etf_method_set_locked():
    assert COMPOSITE_METHODS["etf"] == set(VIEWS)
    for name in VIEWS:
        assert callable(getattr(EtfApi, name, None)), name


def test_anchor_fields_match_script_builds():
    """锚点字段名必须与 script 侧各 build 的真实返回对齐（防 fake 假绿）。

    FakeSession 回显 anchor 本身，`got[key] == val` 恒真、无法发现字段名写错；
    这里跨仓读取 S3 的 etf.xs，锁定每个 view 的特征字段确实出自对应 build。
    script 仓未 sibling checkout 时 skip（离线单仓环境）。
    """
    from pathlib import Path
    script_etf = (Path(__file__).resolve().parents[2] / "script" / "xs" /
                  "skillhub" / "lib" / "etf.xs")
    if not script_etf.exists():
        pytest.skip("script 仓未 sibling checkout")
    src = script_etf.read_text(encoding="utf-8")
    build_for = {
        "card": "etf_card_build", "nav": "etf_nav_build",
        "share": "etf_share_build", "div": "etf_div_build",
        "portfolio": "etf_portfolio_build", "profile": "etf_profile_build",
        "premium": "etf_premium_build", "asset": "etf_fund_asset_build",
        "rank": "etf_rank_build",
    }
    key_for = {
        "card": "quote", "nav": "latest", "share": "fd_share", "div": "rows",
        "portfolio": "holdings", "profile": "profile", "premium": "premium_pct",
        "asset": "stock_ratio", "rank": "chg_w1",
    }
    for view, build in build_for.items():
        marker = f"skhub.{build} = func"
        start = src.find(marker)
        assert start >= 0, f"script 无 build {build}"
        nxt = src.find("\nskhub.", start + len(marker))
        body = src[start:nxt if nxt > 0 else len(src)]
        key = key_for[view]
        assert f'"{key}":' in body, f"{view} 锚点字段 {key} 不在 script {build} 返回中"


def test_every_view_has_live_call_point():
    """组合方法不进 FRIENDLY_INDEX，test_live_coverage 不会提醒——这里锁死 live 调用点。"""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    live = (repo / "tests" / "test_live.py").read_text(encoding="utf-8")
    # test_etf_views 的参数化列表须含全部 9 view（getattr 动态调用，字面量在列表里）
    assert '"card", "nav", "share", "div", "portfolio", "profile", "premium", "asset", "rank"' in live
    assert "getattr(cli.etf, view)" in live
