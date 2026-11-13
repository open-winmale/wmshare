"""公司档案按市场选码 + 行情快照字段声明的契约回归（默认离线、零凭证可跑）。

运行（项目根目录）：
    PYTHONPATH=src python -m pytest -q tests/test_profile_snapshot_contract.py

联网冒烟（需凭证）：
    WMSHARE_LIVE_SMOKE=1 PYTHONPATH=src python -m pytest -q tests/test_profile_snapshot_contract.py

背景（2026-11-14 实测）：
  * ``InfoApi.profile`` 原先把 5 个指标码压进**一个**裸 eval，美股下
    ``$STYLE_INDUSTRY`` 是 undefined variable，一个码打挂整包 → HTTP 400；
    港股该码返回 ``None`` 而非缺失，cn 五码齐备。因此只需对 us 排除这一个码，
    不必逐码降级（后者把 1 次请求变成 5 次）。
  * ``kline.snapshot`` 上游实现返回 23 字段，但 ``xs:catalog`` 注释只列 4 个，
    导致目录 returns_shape / SDK docstring / docs 字段表全部滞后。本仓用
    ``returns.shape`` 精修覆盖补齐（catalog 中 YAML shape 优先于 inventory），
    不手改 generated 文件。

本文件钉住：cn/hk 的 XS 一字不变、us 只排除一个码、返回键集合跨市场稳定、
以及 23 字段声明与真实返回一致。
"""
from __future__ import annotations

import os

import pytest

import wmshare
from wmshare.catalog import load
from wmshare.client import Client

LIVE_SMOKE = pytest.mark.skipif(os.getenv("WMSHARE_LIVE_SMOKE") != "1",
                                reason="设置 WMSHARE_LIVE_SMOKE=1 才联网")

PROFILE_KEYS = {"name", "industry", "style_industry", "org_type", "listing_date"}
CN_XS = ('return {"name": $NAME, "industry": $INDUSTRY_CUR, '
         '"style_industry": $STYLE_INDUSTRY, "org_type": $ORG_ORGTYPE, '
         '"listing_date": $ORG_LISTINGDATE}')
US_XS = ('return {"name": $NAME, "industry": $INDUSTRY_CUR, '
         '"org_type": $ORG_ORGTYPE, "listing_date": $ORG_LISTINGDATE}')

# 上游 sys/kline/snapshot.xs 函数体的真实返回键（2026-11-14 live 实测）
SNAPSHOT_FIELDS = {
    "symbol", "name", "close", "percent", "volume", "amount", "mv", "mv_free",
    "kline_date", "kline_sas", "ma20", "ma60", "ma120", "chg_5d", "chg_10d",
    "chg_20d", "chg_90d", "roi_1y", "vol_ratio_5", "ma60_up", "industry",
    "is_suspend", "is_st",
}


class FakeSession:
    """只实现 Client 需要的 post；记录每次请求，返回结果可注入。"""

    def __init__(self, result: object = None) -> None:
        self.calls: list[dict] = []
        self.result = {"ok": True} if result is None else result

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        outer = self

        class R:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True, "data": {"result": outer.result}}

        return R()


def make_client(market: str = "cn", result: object = None) -> Client:
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  catalog=load(), session=FakeSession(result), market=market)


def last_xs(c: Client) -> list[str]:
    return [x for x in c.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


# ---------------------------------------------------------------- profile
@pytest.mark.parametrize("market", ["cn", "hk"])
def test_profile_xs_unchanged_outside_us(market):
    """cn/hk 仍走五码单请求，XS 字符串一字不变（兼容契约）。"""
    c = make_client(market)
    c.info.profile("600519")
    assert last_xs(c) == [CN_XS]


def test_profile_us_excludes_only_style_industry():
    """美股只剔除 $STYLE_INDUSTRY，其余四码仍在同一请求内。"""
    c = make_client("us")
    c.info.profile("AAPL")
    xs = last_xs(c)
    assert xs == [US_XS]
    assert "$STYLE_INDUSTRY" not in xs[0]
    for code in ("$NAME", "$INDUSTRY_CUR", "$ORG_ORGTYPE", "$ORG_LISTINGDATE"):
        assert code in xs[0], code
    assert len(xs) == 1


@pytest.mark.parametrize("market", ["cn", "us", "hk"])
def test_profile_key_set_stable_across_markets(market):
    """返回键集合不随市场变化，us 的 style_industry 显式为 None。"""
    c = make_client(market, result={"name": "贵州茅台", "industry": "industry.S340501",
                                    "style_industry": "大消费", "org_type": 1,
                                    "listing_date": "2001-08-27"})
    out = c.info.profile("600519")
    assert set(out) == PROFILE_KEYS
    assert out["name"] == "贵州茅台"
    if market == "us":
        assert out["style_industry"] is None
    else:
        assert out["style_industry"] == "大消费"


def test_profile_us_single_eval_not_five():
    """排除码不靠逐码降级：一次 profile 只发一个 eval 请求。"""
    c = make_client("us")
    c.info.profile("AAPL")
    evals = [x for x in c.session.calls if x["url"].endswith("/xs/eval")]
    assert len(evals) == 1


def test_profile_skip_table_is_minimal():
    """只登记实测不可用的市场/码，防止把排除表扩散成隐式能力表。"""
    from wmshare.api import InfoApi
    assert InfoApi._PROFILE_SKIP_BY_MARKET == {"us": {"$STYLE_INDUSTRY"}}


# ---------------------------------------------------------------- snapshot
def test_snapshot_shape_declares_all_23_fields():
    """目录精修形状与上游真实返回键集合完全一致。"""
    fn = load().function("kline.snapshot")
    shape = fn.get("returns_shape") or {}
    assert shape.get("kind") == "object"
    fields = {f["name"] for f in shape.get("fields") or []}
    assert fields == SNAPSHOT_FIELDS
    assert len(shape["fields"]) == 23


def test_snapshot_unit_declaration_points_at_declared_field():
    """units.volume=lot 指向的字段必须在形状里（防声明悬空）。"""
    fn = load().function("kline.snapshot")
    fields = {f["name"] for f in fn["returns_shape"]["fields"]}
    assert set(fn.get("units") or {}) <= fields


def test_snapshot_docstring_no_longer_claims_four_fields():
    """高层 docstring 不能继续只写 4 个字段。"""
    from wmshare.api import KlineApi
    text = KlineApi.snapshot.__doc__ or ""
    assert "23" in text
    assert "ma60_up" in text and "mv_free" in text


# ---------------------------------------------------------------- live smoke
@LIVE_SMOKE
def test_live_us_profile_no_longer_400():
    us = wmshare.Client.from_env(market="us")
    out = us.info.profile("AAPL")
    assert set(out) == PROFILE_KEYS
    assert out["style_industry"] is None
    assert out["name"]


@LIVE_SMOKE
@pytest.mark.parametrize("market,symbol", [("cn", "600519"), ("hk", "00700")])
def test_live_profile_preserves_full_codes(market, symbol):
    cli = wmshare.Client.from_env(market=market)
    out = cli.info.profile(symbol)
    assert set(out) == PROFILE_KEYS
    assert out["name"]


@LIVE_SMOKE
def test_live_snapshot_fields_match_declaration():
    cli = wmshare.Client.from_env()
    out = cli.call("kline.snapshot", sym="600519")
    assert isinstance(out, dict)
    assert set(out) == SNAPSHOT_FIELDS
