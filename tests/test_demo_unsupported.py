"""demo 客户端不得对未回放的函数返回「假绿」空结果（R1 / S3）。"""
from __future__ import annotations

import pytest

import wmshare
from wmshare.errors import CatalogError, UsageError


@pytest.fixture(scope="module")
def cli():
    return wmshare.demo_client()


def test_unknown_catalog_function_raises(cli):
    with pytest.raises(UsageError) as err:
        cli.call("kline.no_such_fn", sym="600519")
    assert err.value.code == "demo_unsupported"


def test_no_fake_empty_success(cli):
    """旧行为 return [] 会让 Agent 把「没数据」误读成「调用成功、结果为空」。"""
    try:
        result = cli.call("dividend.no_such_fn", sym="600519")
    except UsageError:
        return
    raise AssertionError(f"未回放函数仍返回了伪成功结果：{result!r}")


def test_message_points_to_catalog_and_live_client(cli):
    with pytest.raises(UsageError) as err:
        cli.call("market.no_such_fn")
    msg = str(err.value)
    assert "functions_by_domain()" in msg and "Client.from_env()" in msg
    assert "不伪造空结果" in msg


def test_batch_uses_the_same_contract(cli):
    with pytest.raises(UsageError) as err:
        cli.call_batch("kline.no_such_fn", ["600519"])
    assert err.value.code == "demo_unsupported"
    assert "批量函数" in str(err.value) and "Client.from_env()" in str(err.value)


def test_known_replay_branches_still_work(cli):
    assert cli.call("kline.query_bars", sym="600519", limit=3)
    assert cli.call("kline.snapshot", sym="600519")["close"] > 0
    assert 0 <= cli.call("bonus.snapshot_yield_ttm", sym="600519") < 1


def test_same_direction_as_real_catalog_validation(cli):
    """真实目录对编造函数名同样拒绝，demo 不应成为唯一放行的入口。"""
    with pytest.raises(CatalogError):
        wmshare.load().function("kline.no_such_fn")
    with pytest.raises(UsageError) as err:
        cli.call("kline.no_such_fn")
    assert err.value.code == "demo_unsupported"
