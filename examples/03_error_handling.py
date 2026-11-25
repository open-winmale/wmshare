"""错误处理：WmshareError 家族分类与 401/403/429 自带修复引导（假传输，零真实请求）。

前提：离线可跑（FakeSession 模拟 401/429，不联网、零凭证）
运行：python examples/03_error_handling.py
学到：按异常类型分支、记录 code/status 便于程序化处理；错误消息即修复指引
文档：docs/GUIDE.md（故障排查）；docs/AI.md（报错驱动接入）
"""
from __future__ import annotations

from wmshare import (
    AuthError, CatalogError, Client, WmshareError, LimitError, UsageError, load,
)


class _Resp:
    def __init__(self, status: int, body: dict, headers: dict | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body


class _FakeSession:
    """最小假传输：token_status / eval_status 可分别模拟 401 与 429。"""

    def __init__(self, *, token_status: int = 200, eval_status: int = 200):
        self.token_status = token_status
        self.eval_status = eval_status

    def post(self, url, **kwargs):
        if url.endswith("/v1/oauth/token"):
            if self.token_status != 200:
                return _Resp(self.token_status, {
                    "error": "invalid_client",
                    "error_description": "client authentication failed",
                })
            return _Resp(200, {"data": {"access_token": "demo-token", "expires_in": 3600}})
        return _Resp(self.eval_status, {
            "success": False,
            "error": {"code": "RATE_LIMITED", "message": "hourly request limit exceeded"},
        })


def _client(session: _FakeSession) -> Client:
    return Client(base_url="https://demo.invalid", client_id="demo", client_secret="demo",
                  catalog=load(), session=session, retries=0, backoff=0)


def safe_call(label: str, fn, *args, **kwargs):
    """生产代码推荐写法：按错误类型分支，保留 code/status 便于日志与重试。"""
    try:
        result = fn(*args, **kwargs)
        print(f"[ok] {label}: {str(result)[:60]}")
        return result
    except AuthError as e:
        print(f"[auth] {label}: HTTP {e.status} code={e.code}")
        print(f"       {e}")
    except LimitError as e:
        print(f"[limit] {label}: HTTP {e.status} code={e.code}")
        print(f"       {e}")
    except UsageError as e:
        print(f"[usage] {label}: code={e.code} → {e}")
    except CatalogError as e:
        print(f"[catalog] {label}: code={e.code} → {e}")
    except WmshareError as e:
        print(f"[error] {label}: code={e.code} status={e.status} → {e}")


def main() -> None:
    cat = load()

    # 1) OAuth 401：消息中直接包含 AppID 申请步骤
    auth_cli = _client(_FakeSession(token_status=401))
    safe_call("OAuth 401", auth_cli.kline.bars, "600519", n=1)

    # 2) eval 429：限流时同样引导申请自己的 AppID
    limit_cli = _client(_FakeSession(eval_status=429))
    safe_call("eval 429", limit_cli.kline.bars, "600519", n=1)

    # 3) 目录防编造：未知指标在发出请求前就被拦下（CatalogError）
    safe_call("未知指标", limit_cli.indicator.get, "600519", "$NOT_A_REAL_METRIC")

    # 4) 参数用法错误（UsageError）：窗口 token 拼错会显式报错
    safe_call("未知窗口", limit_cli.dividend.window_stats, "600519", "2w")

    # 5) 先查目录再调用，避免 CatalogError
    hits = cat.search("yield_ttm", kind="function")
    print(f"\n先查目录：{[h['name'] for h in hits]}")

    print("\n提示：AuthError / LimitError 的真实触发需要有效/受限凭证；"
          "\n      生产代码建议统一兜底 WmshareError 并记录 e.code / e.status。")


if __name__ == "__main__":
    main()
