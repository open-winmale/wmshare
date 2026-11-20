"""匿名试用凭据模块测试。

核心保护对象：匿名凭据**不得**写入或覆盖付费凭据文件。
"""
from __future__ import annotations

import json
import os
import stat
import urllib.error
from pathlib import Path

import pytest

from wmshare import _anon
from wmshare.errors import AuthError, TransportError


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    """把匿名凭据路径指向临时目录，避免污染真实 ~/.wmshare。"""
    anon_path = tmp_path / "anon_credentials.env"
    monkeypatch.setenv("WMSHARE_ANON_CREDENTIALS", str(anon_path))
    return tmp_path, anon_path


def test_save_uses_0600(isolated_home):
    _, anon_path = isolated_home
    wrote = _anon.save_anon_credentials(
        {"client_id": "anon_open_abc", "client_secret": "s3cret", "ec_balance": 500000})
    assert wrote == anon_path
    mode = stat.S_IMODE(anon_path.stat().st_mode)
    assert mode == 0o600, f"匿名凭据权限应为 0600，实际 {oct(mode)}"


def test_save_never_touches_paid_credentials_file(tmp_path, monkeypatch):
    """写入匿名凭据后，付费凭据文件必须原样保留。

    这是 1.7.0 下线方案后最容易回归的点：两个身份共用一份平铺 KEY=VALUE 文件时，
    后者必然覆盖前者，用户会静默失去付费额度。
    """
    paid = tmp_path / "credentials.env"
    paid.write_text("WMSHARE_CLIENT_ID=paid_id\nWMSHARE_CLIENT_SECRET=paid_sec\n",
                    encoding="utf-8")
    paid_before = paid.read_text(encoding="utf-8")

    anon_path = tmp_path / "anon_credentials.env"
    monkeypatch.setenv("WMSHARE_ANON_CREDENTIALS", str(anon_path))
    monkeypatch.setattr(_anon, "DEFAULT_CREDENTIAL_PATH", paid)

    _anon.save_anon_credentials(
        {"client_id": "anon_open_x", "client_secret": "anon_sec"})

    assert paid.read_text(encoding="utf-8") == paid_before
    assert "paid_id" in paid.read_text(encoding="utf-8")
    assert anon_path.is_file()
    assert "anon_open_x" in anon_path.read_text(encoding="utf-8")


def test_save_refuses_paid_path(tmp_path, monkeypatch):
    """显式传入付费凭据路径时必须拒绝（双保险断言）。"""
    paid = tmp_path / "credentials.env"
    monkeypatch.setattr(_anon, "DEFAULT_CREDENTIAL_PATH", paid)
    with pytest.raises(AuthError):
        _anon.save_anon_credentials(
            {"client_id": "x", "client_secret": "y"}, path=paid)
    assert not paid.exists()


def test_load_roundtrip(isolated_home):
    _anon.save_anon_credentials(
        {"client_id": "anon_open_r", "client_secret": "sec", "ec_balance": 500000})
    loaded = _anon.load_anon_credentials()
    assert loaded is not None
    assert loaded["client_id"] == "anon_open_r"
    assert loaded["client_secret"] == "sec"
    assert loaded["ec_balance"] == "500000"


def test_load_missing_returns_none(isolated_home):
    assert _anon.load_anon_credentials() is None


def test_load_incomplete_returns_none(isolated_home):
    _, anon_path = isolated_home
    anon_path.write_text("WMSHARE_CLIENT_ID=only_id\n", encoding="utf-8")
    assert _anon.load_anon_credentials() is None


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_request_unwraps_envelope(monkeypatch):
    payload = {"ok": True, "as_of": "2026-11-20", "data": {
        "client_id": "anon_open_z", "client_secret": "zz", "ec_balance": 500000}, "meta": {}}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))
    creds = _anon.request_anon_credentials("https://example.invalid")
    assert creds["client_id"] == "anon_open_z"


def test_request_404_maps_to_anon_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.HTTPError(
            "u", 404, "Not Found", {}, __import__("io").BytesIO(b"{}"))
    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(AuthError) as ei:
        _anon.request_anon_credentials("https://example.invalid")
    assert ei.value.code == "anon_unavailable"


def test_request_429_maps_to_anon_quota(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.HTTPError(
            "u", 429, "Too Many", {}, __import__("io").BytesIO(b"{}"))
    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(AuthError) as ei:
        _anon.request_anon_credentials("https://example.invalid")
    assert ei.value.code == "anon_quota"


def test_request_network_error(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("boom")
    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(TransportError):
        _anon.request_anon_credentials("https://example.invalid")


def test_client_anonymous_reuses_saved(isolated_home, monkeypatch):
    """本地已有匿名凭据时必须直接复用，不再发起网络申领（不消耗名额）。"""
    from wmshare import Client

    _anon.save_anon_credentials(
        {"client_id": "anon_open_saved", "client_secret": "sec"})

    def _no_network(*a, **k):
        raise AssertionError("已有本地凭据时不应发起申领请求")

    monkeypatch.setattr("urllib.request.urlopen", _no_network)
    cli = Client.anonymous()
    assert cli.client_id == "anon_open_saved"
    assert cli.client_secret == "sec"


def test_client_anonymous_fetches_when_absent(isolated_home, monkeypatch):
    from wmshare import Client

    payload = {"ok": True, "data": {
        "client_id": "anon_open_new", "client_secret": "newsec", "ec_balance": 500000}}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))
    cli = Client.anonymous()
    assert cli.client_id == "anon_open_new"
    # 落到独立文件，且可被再次读取复用。
    assert _anon.load_anon_credentials()["client_id"] == "anon_open_new"
