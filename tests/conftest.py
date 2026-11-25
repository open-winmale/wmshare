import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# 仓根入 path：tests 里 `from tools import xxx`（如 audit_units）在任意环境可用
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True, scope="session")
def _allow_fake_hosts_in_tests():
    """测试夹具大量用 https://t / https://t.example 这类假主机构造 Client
    （FakeSession 不产生真实网络请求，也就没有凭证外发）。默认 host 白名单
    上线后，逐个改 60+ 处构造点不如在测试会话统一显式 opt-in；新增的
    test_host_allowlist.py 会用 monkeypatch.delenv 单独验证默认严格策略。
    """
    key = "WMSHARE_ALLOW_CUSTOM_HOST"
    old = os.environ.get(key)
    os.environ[key] = "1"
    yield
    if old is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old
