"""CLI setup, doctor, and installation self-check."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from wmshare.mcp.cli import main


def test_setup_writes_canonical_credentials_without_echo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "credentials.env"
    rc = main([
        "setup",
        "--client-id", "id-123",
        "--client-secret", "short-secret",
        "--market", "hk",
        "--credentials-path", str(path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {
        "ok": True,
        "path": str(path),
        "market": "hk",
        "credential_written": True,
    }
    assert path.read_text(encoding="utf-8") == (
        "WMSHARE_CLIENT_ID=id-123\n"
        "WMSHARE_CLIENT_SECRET=short-secret\n"
        "WMSHARE_MARKET=hk\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600
    captured = capsys.readouterr().out
    assert "short-secret" not in captured


def test_setup_preserves_other_settings_and_replaces_old_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "credentials.env"
    path.write_text(
        "# local settings\n"
        "WMSHARE_CLIENT_ID=old-id\n"
        "OTHER_SETTING=keep\n",
        encoding="utf-8",
    )
    rc = main([
        "setup", "--client-id", "new-id", "--client-secret", "new-secret-456789",
        "--market", "us", "--credentials-path", str(path),
    ])
    assert rc == 0
    text = path.read_text(encoding="utf-8")
    assert "# local settings" in text
    assert "OTHER_SETTING=keep" in text
    assert "old-id" not in text
    assert "new-id" in text


def test_setup_rejects_missing_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([
        "setup", "--client-id", "only-id",
        "--credentials-path", str(tmp_path / "credentials.env"),
    ])
    assert rc == 2
    assert "client_secret 必填" in capsys.readouterr().err


def test_check_registers_all_tools(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert len(payload["tools"]) == 20


def test_check_respects_runtime_flags(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--demo", "--market", "hk", "--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["market"] == "hk"
    assert payload["demo"] is True


def test_setup_rejects_empty_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([
        "setup", "--client-id", "id", "--client-secret", "",
        "--credentials-path", str(tmp_path / "credentials.env"),
    ])
    assert rc == 2
    assert "client_secret 必填" in capsys.readouterr().err


def test_setup_accepts_secret_from_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "credentials.env"
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-secret\n"))
    rc = main([
        "setup", "--client-id", "id", "--client-secret-stdin", "--market", "cn",
        "--credentials-path", str(path),
    ])
    assert rc == 0
    assert "stdin-secret" in path.read_text(encoding="utf-8")
    assert "stdin-secret" not in capsys.readouterr().out


def test_credential_status_ignores_similar_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from wmshare.mcp.core import credential_status

    path = tmp_path / "credentials.env"
    path.write_text("WMSHARE_CLIENT_ID_OLD=\nWMSHARE_CLIENT_SECRET_OLD=\n", encoding="utf-8")
    monkeypatch.setenv("WMSHARE_CREDENTIALS", str(path))
    status = credential_status()
    assert status["configured"] is False


def test_runtime_market_reads_credential_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from wmshare.mcp.core import credential_values
    from wmshare.mcp.server import runtime_from_env

    path = tmp_path / "credentials.env"
    path.write_text("WMSHARE_MARKET=hk\n", encoding="utf-8")
    monkeypatch.delenv("WMSHARE_MARKET", raising=False)
    monkeypatch.setenv("WMSHARE_CREDENTIALS", str(path))
    assert credential_values()["WMSHARE_MARKET"] == "hk"
    assert runtime_from_env().market == "hk"


def test_credential_status_reads_file_without_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from wmshare.mcp.core import credential_status

    for key in ("WMSHARE_CLIENT_ID", "WMSHARE_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "credentials.env"
    path.write_text("WMSHARE_CLIENT_ID=id\nWMSHARE_CLIENT_SECRET=secret\n", encoding="utf-8")
    monkeypatch.setenv("WMSHARE_CREDENTIALS", str(path))
    status = credential_status()
    assert status == {
        "has_client_id": True,
        "has_client_secret": True,
        "configured": True,
        "credential_path": str(path),
        "market": "cn",
    }
