"""运行时端点策略：SDK 唯一允许把凭证 POST 过去的主机。

单一事实源：``Client`` 的 base_url 校验、``SECURITY.md`` 的 Scope notes、
``tools/check_leak.py`` 的 ``ALLOWED_MARKERS`` 都以此为准（后者由
``tests/test_host_allowlist.py::test_leak_gate_markers_match_endpoints`` 锁死）。

OAuth token 请求以 form POST 明文携带 ``client_secret``，所以构造期必须拦
host，传输层还必须关闭自动重定向（307/308 会重放整个 POST body）。任何
放宽都要显式 opt-in，默认关闭。
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

ALLOWED_API_HOSTS: frozenset[str] = frozenset({
    "api.winmale.com",
    "test-api.winmale.com",
})
LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

ALLOW_CUSTOM_HOST_ENV = "WMSHARE_ALLOW_CUSTOM_HOST"
HOST_POLICY_ENV = "WMSHARE_HOST_POLICY"
HOST_POLICY_LEGACY = "legacy"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _usage_error(message: str) -> Exception:
    # 延迟导入：check_leak.py / 测试可独立加载本模块常量而不触发包初始化。
    from wmshare.errors import UsageError

    return UsageError(message, code="config")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


def host_policy_relaxed(*, explicit: bool = False) -> bool:
    """是否允许自定义 host：显式构造参数 > 环境变量 > 全局 legacy 热降级。"""
    if explicit:
        return True
    if _env_truthy(ALLOW_CUSTOM_HOST_ENV):
        return True
    return os.getenv(HOST_POLICY_ENV, "").strip().lower() == HOST_POLICY_LEGACY


def validate_base_url(url: str, *, allow_custom_host: bool = False) -> str:
    """校验并返回 strip 后的 base_url；不合规抛 ``UsageError(code="config")``。

    校验顺序刻意把 scheme 检查放在最前（既有测试依赖 "HTTPS" 文案），随后补
    userinfo / path / query / fragment 与 host 白名单。错误消息不回显完整 URL，
    避免把带 secret 的 userinfo 写进日志或 traceback。
    """
    clean = str(url).strip()
    parsed = urlsplit(clean)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and not (
            parsed.scheme == "http" and host in LOOPBACK_HOSTS):
        raise _usage_error(
            "base_url 必须使用 HTTPS；本地网关可用 http://localhost、"
            "http://127.0.0.1 或 http://[::1]")
    if parsed.username or parsed.password:
        raise _usage_error("base_url 不得包含用户名/密码（userinfo）")
    if parsed.query or parsed.fragment:
        raise _usage_error("base_url 不得包含 query 或 fragment")
    if parsed.path.strip("/"):
        raise _usage_error("base_url 不得包含路径；SDK 会自行拼接 /v1/...")
    if not host:
        raise _usage_error("base_url 缺少有效 host")
    if host in ALLOWED_API_HOSTS or host in LOOPBACK_HOSTS:
        return clean
    if host_policy_relaxed(explicit=allow_custom_host):
        return clean
    raise _usage_error(
        "base_url 指向非官方主机：SDK 会向其明文 POST client_secret，默认拒绝。"
        f"仅允许 {', '.join(sorted(ALLOWED_API_HOSTS))} 与本地回环；"
        "自建代理请显式传 allow_custom_host=True 或设置 "
        f"{ALLOW_CUSTOM_HOST_ENV}=1；紧急回退可设 "
        f"{HOST_POLICY_ENV}={HOST_POLICY_LEGACY}（详见 SECURITY.md）")


__all__ = [
    "ALLOWED_API_HOSTS",
    "ALLOW_CUSTOM_HOST_ENV",
    "HOST_POLICY_ENV",
    "HOST_POLICY_LEGACY",
    "LOOPBACK_HOSTS",
    "host_policy_relaxed",
    "validate_base_url",
]
