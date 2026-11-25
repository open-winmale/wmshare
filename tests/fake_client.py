"""共享假客户端：单源自 tests/replay_client（离线回放夹具），示例测试端到端跑 main(cli)。

罐头值一律基础单位口径（率/分位=小数、金额=元、量=股），与真实返回同构——
示例测试因此同时是「返回长这样」的可执行文档。签名校验由
test_interface_quality 的签名门禁负责。数据见 tests/fixtures/replay_data.json。
"""
from __future__ import annotations

from replay_client import replay_client


def fake_client():
    """覆盖全部示例 cli.* 调用面的回放客户端（离线固定快照，非实时行情）。"""
    return replay_client()


def fake_runtime(market: str = "cn"):
    """MCPRuntime 预注入回放客户端（离线）：client() 命中 _clients 缓存即不联网。"""
    from wmshare.mcp.core import MCPRuntime

    rt = MCPRuntime(market=market)
    rt._clients[market] = fake_client()
    return rt
