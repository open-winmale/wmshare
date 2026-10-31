"""统一异常体系：全部继承 WmshareError，并带 code/status 便于程序化分类。

CatalogError 同时继承 KeyError，兼容既有 `except KeyError` 用法。
"""
from __future__ import annotations

# 401/403/429 的统一引导文案：错误消息里直接给出可执行的申请步骤，
# 避免用户只看到原始 HTTP 状态而不知道下一步做什么。
APPID_GUIDANCE = (
    "申请自己的 AppID：打开 https://open.winmale.com 登录 → "
    "右上角「我的」→「开放平台」→「我的应用」→「查看应用信息」，复制两个值（缺一不可）：client_id 与 api-key；"
    "然后设置 WMSHARE_CLIENT_ID / WMSHARE_CLIENT_SECRET，"
    "或写入 ~/.wmshare/credentials.env。"
)


class WmshareError(RuntimeError):
    """带修复建议的统一错误基类。"""

    def __init__(self, message: str, *, code: str = "", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class AuthError(WmshareError):
    """凭证缺失/无效/被拒（OAuth 400/401/403 或 eval 401/403）。

    凭证缺失、无效、被撤销都会落到这里；消息包含申请与配置自己
    AppID 的步骤，程序可用 ``code`` / ``status`` 分类。
    """


class UsageError(WmshareError):
    """调用方式错误：未知/缺失参数、_df 依赖缺失等。"""


class LimitError(WmshareError):
    """请求体积/窗口超限，或服务端限流（HTTP 429）。

    客户端 ``max_limit``/日期区间用 ``code="limit"``/``"range"``；
    服务端限流用 ``code="rate_limited"`` 且 ``status=429``，消息包含
    重试建议和申请自己的 AppID 的步骤。
    """


class TransportError(WmshareError):
    """网络层失败（连接/超时，重试耗尽）。"""


class ServerError(WmshareError):
    """服务端 5xx。"""


class ApiError(WmshareError):
    """服务端返回业务错误（success=false 或其他 4xx）。"""


class DataError(WmshareError):
    """返回数据未通过单位量级守护或关系不变量校验（code="range" / "invariant"）。

    换算声明与实际数据不符、上游口径变化都会在这里暴露，而不是把错误量级的
    数据静默交给用户。消息包含字段/实际值/期望范围与逃生口：
    ``_raw=True``（上游原始行）、``_units="native"``（保留上游原单位）、
    ``Client(validate=False)``（关闭校验、保留换算）。
    """


class StreamResetError(WmshareError):
    """公告订阅流的消费进度已超出保留期（服务端事件已过 TTL）。

    用 ``seek_oldest(market)`` 重置进度，之后只能读回保留期内剩余数据；
    保持进度不落后通常意味着缩短轮询间隔或提高消费吞吐。
    """


class CatalogError(WmshareError, KeyError):
    """目录中不存在该函数/域/指标/不兼容版本（同时兼容 KeyError 捕获）。"""

    def __str__(self) -> str:
        # KeyError.__str__ 会再加一层 repr 引号；SDK 用户看到的应是普通消息。
        return str(self.args[0]) if self.args else ""
