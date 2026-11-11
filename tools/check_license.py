#!/usr/bin/env python3
"""许可证一致性门禁（发版 / CI 必跑）：仓内所有 BSD-3-Clause 声明必须一致，
且不得混入与 BSD-3-Clause 不兼容的许可措辞（非商业 / PolyForm / MIT 等）。

一致性检查点（任一腐化即失败，并逐处列出实际值）：
  1. LICENSE 文件首行声明的 SPDX（规范化为 BSD-3-Clause）
  2. pyproject.toml::project.license
  3. CONTRIBUTING.md 许可政策段
  4. docs/openapi.json::info.license.name
  5. SECURITY.md 许可声明

不兼容措辞扫描：在**手写当前声明文档**里搜索「非商业 / PolyForm / MIT」等会与
BSD-3-Clause 冲突的用语，命中即失败。刻意**排除 CHANGELOG.md**——它记录的是历史
许可变迁（1.4.2/1.4.3 曾为 MIT、PolyForm、非商业），属解释性内容而非当前声明，
不应让门禁对历史记录假红；仓外平台侧的 PyPI/GitHub 历史 SPDX 不在本仓库内，
无法自动校验，需在发布平台侧人工确认。

全程只读；不依赖 wmshare 运行时与第三方包，便于在门禁环境独立执行。

Usage: python3 tools/check_license.py [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LICENSE = REPO / "LICENSE"
PYPROJECT = REPO / "pyproject.toml"
CONTRIBUTING = REPO / "CONTRIBUTING.md"
OPENAPI = REPO / "docs" / "openapi.json"
SECURITY = REPO / "SECURITY.md"

CANONICAL = "BSD-3-Clause"

# 手写「当前许可声明」文档（均在 check_leak 白名单内）。
# 刻意排除 CHANGELOG.md：它记载历史许可变迁，属解释性内容，不应假红。
SCAN_TARGETS = (
    "README.md",
    "README.en.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "docs/openapi.json",
)
# 词边界匹配，避免 LIMITED / LIMIT_EXCEEDED 等误命中。
FORBIDDEN_RE = re.compile(r"\b(MIT|PolyForm|非商业)\b")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"读取 {p.name} 失败：{exc}") from exc


def _license_spdx_from_text(text: str) -> str:
    """从 LICENSE 文本推断规范 SPDX（首行声明）。"""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if "BSD-3-Clause" in first or "BSD 3-Clause" in first:
        return CANONICAL
    raise ValueError(f"LICENSE 首行未识别为 {CANONICAL}：{first!r}")


def collect() -> tuple[str, dict[str, str], list[str]]:
    """Return (canonical, sources, forbidden_hits)."""
    license_text = _read(LICENSE)
    canonical = _license_spdx_from_text(license_text)

    pyproject = _read(PYPROJECT)
    m = re.search(r'^license\s*=\s*"([^"]+)"', pyproject, re.M)
    spdx_pyproject = m.group(1) if m else "(缺失)"

    openapi = json.loads(_read(OPENAPI))
    spdx_openapi = openapi.get("info", {}).get("license", {}).get("name", "(缺失)")

    contributing = _read(CONTRIBUTING)
    spdx_contributing = CANONICAL if CANONICAL in contributing else "(缺失)"

    security = _read(SECURITY)
    spdx_security = CANONICAL if CANONICAL in security else "(缺失)"

    sources = {
        "LICENSE（首行规范）": canonical,
        "pyproject.toml::project.license": spdx_pyproject,
        "CONTRIBUTING.md::许可政策": spdx_contributing,
        "docs/openapi.json::info.license.name": spdx_openapi,
        "SECURITY.md::许可声明": spdx_security,
    }

    forbidden_hits: list[str] = []
    for rel in SCAN_TARGETS:
        p = REPO / rel
        if not p.exists():
            continue  # 可选文档（如 README.en.md）缺失不视为失败
        for term in FORBIDDEN_RE.findall(_read(p)):
            forbidden_hits.append(f"{rel}: 命中不兼容措辞 {term!r}")
    return canonical, sources, forbidden_hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="只读校验（默认行为；显式给出便于 CI 声明意图）")
    ap.parse_args(argv)

    try:
        canonical, sources, forbidden = collect()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"check_license: 校验失败：{exc}", file=sys.stderr)
        return 2

    bad = {where for where, got in sources.items() if got != canonical}
    if bad:
        print("check_license FAIL：许可声明不一致（逐处实际值如下）", file=sys.stderr)
        for where, got in sources.items():
            print(f"  {'✗' if where in bad else '·'} {where}: {got}", file=sys.stderr)
        print(f"  基准 = LICENSE 首行规范 = {canonical}", file=sys.stderr)
        return 1

    if forbidden:
        print("check_license FAIL：发现与 BSD-3-Clause 不兼容的许可措辞：",
              file=sys.stderr)
        for hit in forbidden:
            print(f"  ✗ {hit}", file=sys.stderr)
        print("  仓外平台侧（PyPI/GitHub 历史发布）的 SPDX 不在本仓库内，"
              "需人工确认；本仓库当前声明文档不得引入冲突措辞。", file=sys.stderr)
        return 1

    print(f"check_license ok：仓内许可声明均为 {canonical}（未见不兼容措辞）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
