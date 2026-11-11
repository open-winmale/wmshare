#!/usr/bin/env python3
"""版本一致性门禁（发版 / CI 必跑）：六处声明必须同指一个版本号。

锁死的六处（任一处腐化即失败，并逐处列出实际值）：
  1. src/wmshare/__init__.py::__version__          （基准）
  2. pyproject.toml::project.version
  3. server.json::version
  4. server.json::packages[0].version
  5. docs/openapi.json::info.version
  6. CHANGELOG.md 顶部 release 段（跳过 [Unreleased]）

另锁 SECURITY.md：当前 minor 线表头 == 基准 major.minor，
Last reviewed 的 as_of == 基准完整版本号。

全程只读；不依赖 wmshare 运行时与第三方包，便于在门禁环境独立执行。

Usage: python3 tools/check_version.py [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "src" / "wmshare" / "__init__.py"
PYPROJECT = REPO / "pyproject.toml"
SERVER_JSON = REPO / "server.json"
OPENAPI = REPO / "docs" / "openapi.json"
CHANGELOG = REPO / "CHANGELOG.md"
SECURITY = REPO / "SECURITY.md"

MISSING = "（缺失）"


def _match(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.M)
    if not m:
        return MISSING
    return m.group(1)


def collect() -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (baseline, six sources, security checks)."""
    init = INIT.read_text(encoding="utf-8")
    baseline = _match(r'__version__\s*=\s*"([^"]+)"', init)
    if baseline == MISSING:
        raise ValueError(f"{INIT} 里找不到 __version__，无法作为互校基准")

    server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    packages = server.get("packages") or [{}]
    sources = {
        "src/wmshare/__init__.py::__version__": baseline,
        "pyproject.toml::project.version": _match(
            r'^version\s*=\s*"([^"]+)"',
            PYPROJECT.read_text(encoding="utf-8")),
        "server.json::version": str(server.get("version") or MISSING),
        "server.json::packages[0].version": str(packages[0].get("version") or MISSING),
        "docs/openapi.json::info.version": str(
            json.loads(OPENAPI.read_text(encoding="utf-8")).get("info", {}).get("version")
            or MISSING),
        "CHANGELOG.md::top release": _match(
            r"^##\s*\[(\d+\.\d+\.\d+[^\]]*)\]",
            CHANGELOG.read_text(encoding="utf-8")),
    }

    sec_text = SECURITY.read_text(encoding="utf-8")
    minor = ".".join(baseline.split(".")[:2])
    security = {
        "SECURITY.md::当前 minor 线": _match(
            r"^\|\s*(\d+\.\d+)\.x\s*\|\s*✅（当前 minor 线）", sec_text),
        "SECURITY.md::Last reviewed as_of": _match(r"as_of\s*`([^`]+)`", sec_text),
    }
    return baseline, sources, {"minor": minor, **security}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="只读互校（默认行为；显式给出便于 CI 声明意图）")
    ap.parse_args(argv)

    try:
        baseline, sources, security = collect()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"check_version: 读取版本声明失败：{exc}", file=sys.stderr)
        return 2

    security_rows = [
        ("SECURITY.md::当前 minor 线",
         security["SECURITY.md::当前 minor 线"], security["minor"]),
        ("SECURITY.md::Last reviewed as_of",
         security["SECURITY.md::Last reviewed as_of"], baseline),
    ]
    mismatches = [(where, got) for where, got in sources.items() if got != baseline]
    mismatches += [(where, got) for where, got, expected in security_rows if got != expected]

    if mismatches:
        bad = {where for where, _ in mismatches}
        print("check_version FAIL：版本声明不一致（逐处实际值如下）", file=sys.stderr)
        for where, got in sources.items():
            print(f"  {'✗' if where in bad else '·'} {where}: {got}", file=sys.stderr)
        for where, got, expected in security_rows:
            print(f"  {'✗' if where in bad else '·'} {where}: {got}（应为 {expected}）",
                  file=sys.stderr)
        print(f"  基准 = src/wmshare/__init__.py::__version__ = {baseline}", file=sys.stderr)
        return 1

    print(f"check_version ok：六处版本声明均为 {baseline}"
          f"（SECURITY.md 当前 minor 线 {security['minor']}.x / as_of {baseline}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
