"""P0-A：运行时端点 / 凭证边界回归测试。

默认策略必须严格；放宽只能来自显式构造参数或部署方环境变量。
所有用例都用 FakeSession 或构造期失败，不产生任何真实网络请求。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import requests

from wmshare._credentials import read_credentials_file
from wmshare._endpoints import (
    ALLOWED_API_HOSTS,
    ALLOW_CUSTOM_HOST_ENV,
    HOST_POLICY_ENV,
    validate_base_url,
)
from wmshare.catalog import catalog_dir
from wmshare.client import Client, _redact
from wmshare.errors import CatalogError, UsageError

REPO = Path(__file__).resolve().parents[1]
_FAKE_HOST = "https://t.example"


@pytest.fixture
def strict(monkeypatch):
    """清掉所有放宽开关，回到默认部署策略。"""
    monkeypatch.delenv(ALLOW_CUSTOM_HOST_ENV, raising=False)
    monkeypatch.delenv(HOST_POLICY_ENV, raising=False)
    return monkeypatch


def _client(**kw):
    params = {"client_id": "id", "client_secret": "sec", "base_url": _FAKE_HOST}
    params.update(kw)
    return Client(**params)


def test_default_rejects_arbitrary_https_host(strict):
    with pytest.raises(UsageError, match="非官方主机"):
        _client()
    with pytest.raises(UsageError, match="非官方主机"):
        Client.from_env({
            "WMSHARE_CLIENT_ID": "id",
            "WMSHARE_CLIENT_SECRET": "sec",
            "WMSHARE_BASE_URL": "https://attacker.example",
        })


@pytest.mark.parametrize("host", sorted(ALLOWED_API_HOSTS))
def test_official_hosts_allowed_without_optin(strict, host):
    assert validate_base_url(f"https://{host}") == f"https://{host}"


@pytest.mark.parametrize("url", [
    "http://localhost", "http://localhost:8765", "http://127.0.0.1:9000",
    "http://[::1]:9000",
])
def test_loopback_http_allowed_without_optin(strict, url):
    assert validate_base_url(url) == url


def test_explicit_optin_allows_custom_host(strict):
    c = _client(allow_custom_host=True)
    assert c.base_url == _FAKE_HOST


def test_env_optin_allows_custom_host(strict):
    strict.setenv(ALLOW_CUSTOM_HOST_ENV, "1")
    assert validate_base_url(_FAKE_HOST) == _FAKE_HOST


def test_legacy_policy_allows_custom_host(strict):
    strict.setenv(HOST_POLICY_ENV, "legacy")
    assert validate_base_url(_FAKE_HOST) == _FAKE_HOST


@pytest.mark.parametrize("url,match", [
    ("https://user:pw@api.winmale.com", "userinfo"),
    ("https://api.winmale.com/v1", "路径"),
    ("https://api.winmale.com?x=1", "query"),
    ("https://api.winmale.com#frag", "fragment"),
    ("http://api.winmale.com", "HTTPS"),
])
def test_url_shape_is_rejected_even_on_official_host(strict, url, match):
    with pytest.raises(UsageError, match=match):
        validate_base_url(url)


def test_error_message_does_not_echo_secrets(strict):
    with pytest.raises(UsageError) as exc:
        validate_base_url("https://user:supersecret@evil.example")
    assert "supersecret" not in str(exc.value)
    assert "evil.example" not in str(exc.value)


def test_redirect_does_not_replay_secret(monkeypatch):
    seen: dict = {}

    def fake_post(self, url, **kw):
        seen.update(kw)

        class R:
            status_code = 200

        return R()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    c = _client(base_url="https://api.winmale.com")
    c._post("https://api.winmale.com/v1/oauth/token",
            data={"client_secret": "sec"})
    assert seen.get("allow_redirects") is False, (
        "307/308 会重放含 client_secret 的 POST body，必须禁自动重定向")


def test_fake_session_without_redirect_param_still_works(monkeypatch):
    class FakeSession:
        headers: dict = {}

        def post(self, url, json=None, data=None, headers=None, timeout=None):
            class R:
                status_code = 200

            return R()

    c = _client(session=FakeSession())
    assert c._post("https://t.example/v1/oauth/token", data={}).status_code == 200


def test_redact_masks_known_secret_bearer_and_pairs():
    secret = "SUPERSECRETVALUE1234"
    text = ("client_secret=" + secret + " & "
            "Authorization: Bearer abc.def-ghi & client_id: some-client-id")
    out = _redact(text, secret)
    assert secret not in out
    assert "abc.def-ghi" not in out
    assert "some-client-id" not in out
    assert out.count("***") >= 3


def test_redact_leaves_clean_text_unchanged():
    clean = "请求被限流（HTTP 429），请稍后重试"
    assert _redact(clean, "unused-secret") == clean


def test_error_detail_redacts_upstream_echo():
    class Resp:
        text = '{"error":{"message":"echo client_secret=TOPSECRET123456"}}'

        def json(self):
            return {"error": {"message": "echo client_secret=TOPSECRET123456"}}

    c = _client(base_url="https://api.winmale.com",
                client_id="cid", client_secret="TOPSECRET123456")
    _, detail = c._error_detail(Resp())  # type: ignore[arg-type]
    assert "TOPSECRET123456" not in detail
    assert "***" in detail


def test_credential_file_mode_warns(tmp_path):
    p = tmp_path / "credentials.env"
    p.write_text("WMSHARE_CLIENT_ID=abc\n", encoding="utf-8")
    p.chmod(0o644)
    with pytest.warns(UserWarning, match="chmod 600"):
        values = read_credentials_file(p, env={})
    assert values["WMSHARE_CLIENT_ID"] == "abc"


def test_strict_cred_mode_rejects_loose_permissions(tmp_path):
    p = tmp_path / "credentials.env"
    p.write_text("WMSHARE_CLIENT_ID=abc\n", encoding="utf-8")
    p.chmod(0o644)
    with pytest.raises(UsageError, match="权限"):
        read_credentials_file(p, env={"WMSHARE_STRICT_CRED_MODE": "1"})


def test_credential_file_0600_is_silent(tmp_path):
    import warnings

    p = tmp_path / "credentials.env"
    p.write_text("WMSHARE_CLIENT_ID=abc\n", encoding="utf-8")
    p.chmod(0o600)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        values = read_credentials_file(p, env={})
    assert not [w for w in record if "chmod 600" in str(w.message)]
    assert values["WMSHARE_CLIENT_ID"] == "abc"


def test_catalog_dir_requires_double_optin(monkeypatch, tmp_path):
    monkeypatch.setenv("WMSHARE_CATALOG_DIR", str(tmp_path))
    monkeypatch.delenv("WMSHARE_ALLOW_CUSTOM_CATALOG", raising=False)
    with pytest.raises(CatalogError, match="显式开启"):
        catalog_dir()
    monkeypatch.setenv("WMSHARE_ALLOW_CUSTOM_CATALOG", "1")
    (tmp_path / "domains").mkdir()
    with pytest.raises(FileNotFoundError, match="generated/inventory.json"):
        catalog_dir()
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "inventory.json").write_text("{}", encoding="utf-8")
    (tmp_path / "generated" / "metrics.json").write_text("{}", encoding="utf-8")
    assert catalog_dir() == tmp_path.resolve()


def test_leak_gate_markers_match_endpoints():
    """运行期白名单与 leak gate 的公开端点标记不得各写一份后漂移。"""
    src = (REPO / "tools/check_leak.py").read_text(encoding="utf-8")
    m = re.search(r"ALLOWED_MARKERS\s*=\s*\(([^)]*)\)", src)
    assert m, "check_leak.py 的 ALLOWED_MARKERS 形式变了，请同步本断言"
    markers = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert markers == set(ALLOWED_API_HOSTS)
