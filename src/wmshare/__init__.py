"""wmshare — WinMale 个股开放数据 SDK。

机器可读数据目录（catalog/）+ OpenAPI 取数客户端。返回值统一基础单位：
比率/涨跌幅=小数（0.332=33.2%）、金额/价格/市值=元（报表原币）、股数/成交量=股；
每次返回都经过目录声明的量级守护与关系不变量校验（违例抛 DataError）。

    import wmshare

    cat = wmshare.load()                             # 数据目录（域/函数/参数/返回 schema）
    fn = cat.function("kline.query_bars")

    cli = wmshare.demo_client()                      # 零凭证先试：离线演示数据（固定快照）
    cli = wmshare.Client.from_env()                  # 接真实数据：读 WMSHARE_CLIENT_ID/SECRET
    bars = cli.call("kline.query_bars", sym="600519", limit=30)
    # _units="native" 保留上游原单位；_raw=True 返回上游原始行；
    # Client(validate=False) 关闭校验（换算仍执行）
"""
from wmshare._demo import demo_client
from wmshare.catalog import Catalog, load
from wmshare.client import BatchResult, Client, normalize_symbol
from wmshare.errors import (
    ApiError, AuthError, CatalogError, DataError, WmshareError, LimitError,
    ServerError, StreamResetError, TransportError, UsageError,
)
from wmshare.notice_stream import NoticePoller, NoticeStreamEvent

__version__ = "1.17.0"

__all__ = [
    "Catalog", "load", "Client", "BatchResult", "normalize_symbol", "__version__",
    "skill_dir", "demo_client",
    "NoticePoller", "NoticeStreamEvent",
    "WmshareError", "AuthError", "UsageError", "LimitError", "TransportError",
    "ServerError", "ApiError", "DataError", "CatalogError", "StreamResetError",
]


def skill_dir():
    """随包分发的 AI agent skill 目录（Agent Skills 格式，含 SKILL.md）。

    装入 agent（复制到其发现路径之一）::

        cp -r "$(python3 -c 'import wmshare; print(wmshare.skill_dir())')" \\
            ~/.agents/skills/wmshare
    """
    from pathlib import Path

    return Path(__file__).resolve().parent / "skills" / "wmshare"
