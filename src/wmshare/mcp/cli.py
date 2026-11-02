"""Command-line entry point for the local MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import wmshare
from wmshare.mcp.constants import MARKETS


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="wmshare-mcp",
        description="wmshare 本地 MCP server 与安装自检工具",
    )
    result.add_argument("--check", action="store_true", help="校验安装与工具注册后退出")
    result.add_argument("--demo", action="store_true", help="启动离线演示快照模式")
    result.add_argument("--market", choices=MARKETS, help="默认市场")
    sub = result.add_subparsers(dest="command")
    setup_parser = sub.add_parser("setup", help="安全写入开放平台凭证")
    setup_parser.add_argument("--client-id", required=True)
    setup_parser.add_argument("--client-secret", help="不推荐：会进入 shell history/process list")
    setup_parser.add_argument(
        "--client-secret-stdin",
        action="store_true",
        help="从 stdin 读取 API Key（推荐）",
    )
    setup_parser.add_argument("--market", choices=MARKETS, default="cn")
    setup_parser.add_argument(
        "--credentials-path",
        help="默认使用 WMSHARE_CREDENTIALS 或 ~/.wmshare/credentials.env",
    )
    sub.add_parser("doctor", help="检查凭证、目录和市场配置")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            return _setup(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.check:
            return _check(args)
        return _serve(args)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


def _serve(args: argparse.Namespace) -> int:
    from wmshare.mcp.core import MCPRuntime, credential_values
    from wmshare.mcp.server import build_server

    market = args.market or credential_values()["WMSHARE_MARKET"] or "cn"
    demo = args.demo or os.getenv("WMSHARE_MCP_DEMO", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }
    server = build_server(MCPRuntime(market=market, demo=demo))
    server.run("stdio")
    return 0


def _check(args: argparse.Namespace) -> int:
    from wmshare.mcp.constants import TOOL_NAMES
    from wmshare.mcp.core import MCPRuntime, credential_status, credential_values
    from wmshare.mcp.server import build_server

    wmshare.load()
    market = args.market or credential_values()["WMSHARE_MARKET"] or "cn"
    demo = args.demo or os.getenv("WMSHARE_MCP_DEMO", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }
    server = build_server(MCPRuntime(market=market, demo=demo))

    async def listed() -> list[str]:
        response = await server.list_tools()
        return [item.name for item in response]

    names = asyncio.run(listed())
    if set(names) != set(TOOL_NAMES):
        missing = sorted(set(TOOL_NAMES) - set(names))
        extra = sorted(set(names) - set(TOOL_NAMES))
        raise RuntimeError(f"MCP tools 与合同不一致：missing={missing} extra={extra}")
    payload: dict[str, Any] = {
        "ok": True,
        "version": wmshare.__version__,
        "python": sys.version.split()[0],
        "market": market,
        "demo": demo,
        "tools": sorted(names),
        "credentials_configured": bool(credential_status()["configured"]),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from wmshare.mcp.core import credential_status, credential_values
    from wmshare.client import Client

    creds = credential_status()
    market = args.market or credential_values()["WMSHARE_MARKET"] or "cn"
    if market not in MARKETS:
        raise ValueError(f"WMSHARE_MARKET 只支持 {'/'.join(MARKETS)}，收到 {market!r}")
    catalog = wmshare.load().stats()
    client_ok = True
    client_error: str | None = None
    if creds["configured"]:
        try:
            Client.from_env(market=market)
        except Exception as exc:
            client_ok = False
            client_error = str(exc)
    ok = bool(creds["configured"] and client_ok)
    payload: dict[str, Any] = {
        "ok": ok,
        "version": wmshare.__version__,
        "python": sys.version.split()[0],
        "market": market,
        "credentials": {key: creds[key] for key in ("has_client_id", "has_client_secret", "configured")},
        "credential_path": creds["credential_path"],
        "catalog": catalog,
        "client_constructed": client_ok,
        "client_error": client_error,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


def _setup(args: argparse.Namespace) -> int:
    if args.client_secret_stdin and args.client_secret:
        raise ValueError("--client-secret-stdin 与 --client-secret 只能二选一")
    if not args.client_secret_stdin and not args.client_secret:
        raise ValueError("client_secret 必填：推荐 --client-secret-stdin")
    client_secret = args.client_secret
    if args.client_secret_stdin:
        client_secret = sys.stdin.readline().strip()
    if not args.client_id.strip() or not client_secret:
        raise ValueError("client_id 与 client_secret 不能为空")
    client_id = args.client_id.strip()
    client_secret = client_secret.strip()
    path = Path(
        args.credentials_path
        or os.getenv("WMSHARE_CREDENTIALS")
        or "~/.wmshare/credentials.env"
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    order: list[str] = []
    comments: list[str] = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            clean = raw.strip().removeprefix("export ").strip()
            if not clean or clean.startswith("#"):
                comments.append(raw)
                continue
            if "=" not in clean:
                comments.append(raw)
                continue
            key, _, value = clean.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in ("WMSHARE_CLIENT_ID", "WMSHARE_CLIENT_SECRET", "WMSHARE_MARKET"):
                if key not in order:
                    order.append(key)
                existing[key] = value
            else:
                if key not in order:
                    order.append(key)
                existing[key] = raw
    updates = {
        "WMSHARE_CLIENT_ID": client_id,
        "WMSHARE_CLIENT_SECRET": client_secret,
        "WMSHARE_MARKET": args.market,
    }
    for key, value in updates.items():
        if key not in order:
            order.append(key)
        existing[key] = value
    lines = list(comments)
    for key in order:
        raw_value = existing[key]
        if key in updates:
            lines.append(f"{key}={raw_value}")
        else:
            lines.append(raw_value)
    content = "\n".join(lines).rstrip() + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(json.dumps({
        "ok": True,
        "path": str(path),
        "market": args.market,
        "credential_written": True,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
