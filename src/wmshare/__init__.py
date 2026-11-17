"""wmshare — WinMale 个股开放数据 SDK。

机器可读数据目录（catalog/）+ OpenAPI 取数客户端。2.0 标准化契约：

  - 单位：比率/涨跌幅/占比=小数（0.332=33.2%）、金额/价格/市值=元（报表原币）、
    股数/成交量=股（units.yaml 台账登记码由 SDK 默认换算；``native=True`` /
    ``_units="native"`` 取上游原值）；
  - 返回：门面（``cli.ns.method``）查询/序列类默认 pandas DataFrame（``date``
    列 ISO、按日期升序=旧→新），面板/时序组合面返回统一信封
    ``{ok, as_of, data, meta}``；底层 ``cli.call`` 保持规范化行数组；
  - 日期入参统一 ``YYYY-MM-DD``（``normalize_date`` 可归一）；
  - 每次返回都经过目录声明的量级守护与关系不变量校验（违例抛 DataError）。

    import wmshare

    cat = wmshare.load()                             # 数据目录（域/函数/参数/返回 schema）
    fn = cat.function("kline.query_bars")

    cli = wmshare.demo_client()                      # 零凭证先试：离线演示数据（固定快照）
    cli = wmshare.Client.from_env()                  # 接真实数据：读 WMSHARE_CLIENT_ID/SECRET
    bars = cli.kline.bars("600519", n=30)            # -> DataFrame（date 升序）
    rows = cli.call("kline.query_bars", sym="600519", limit=30)   # 底层行数组
    # _units="native" / native=True 保留上游原单位；_raw=True 返回上游原始行；
    # Client(validate=False) 关闭校验（换算仍执行）
"""
from wmshare._demo import demo_client
from wmshare.catalog import Catalog, load
from wmshare.client import BatchResult, Client, normalize_date, normalize_symbol
from wmshare.errors import (
    ApiError, AuthError, CatalogError, DataError, WmshareError, LimitError,
    ServerError, StreamResetError, TransportError, UsageError,
)
from wmshare.notice_stream import NoticePoller, NoticeStreamEvent

__version__ = "2.0.1"

__all__ = [
    "Catalog", "load", "Client", "BatchResult", "normalize_symbol",
    "normalize_date", "__version__",
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
