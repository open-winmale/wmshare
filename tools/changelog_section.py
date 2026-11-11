#!/usr/bin/env python3
"""从 CHANGELOG.md 抽取某个版本的正文，供 GitHub Release 使用。

发版后 ``gh release create`` 需要一段 release notes；手抄容易与 CHANGELOG 漂移，
故统一从这里抽。规则与 ``check_version.py`` 的「顶部 release 段」解析保持一致：
版本段标题形如 ``## [1.16.3] - 2026-11-11``，正文到下一个 ``## `` 为止；
``[Unreleased]`` 是空段，永远不带日期，也不会被误当成某个版本。

全程只读，输出可含 Markdown 原样内容（各级标题、列表）。找不到版本即非零退出，
避免 CI 用空 body 发出一个没有说明的 Release。

Usage:
    python3 tools/changelog_section.py 1.16.3           # 打到 stdout
    python3 tools/changelog_section.py v1.16.3 --check  # 只校验存在（接受 v 前缀）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"

# `## [1.16.3] - 2026-11-11` / `## [Unreleased]`
_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\S+))?\s*$")


def normalize(version: str) -> str:
    """去掉 tag 的 ``v`` 前缀与空白。"""
    return version.strip().lstrip("vV")


def section(text: str, version: str) -> str:
    """返回该版本的正文（不含标题行）；版本不存在或缺正文时抛 KeyError。"""
    want = normalize(version)
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if not m:
            continue
        if start is not None:
            body = "\n".join(lines[start:i]).strip()
            if body:
                return body
            raise KeyError(f"版本 {want} 的段落为空")
        if normalize(m.group("version")) == want:
            start = i + 1
    if start is not None:
        body = "\n".join(lines[start:]).strip()
        if body:
            return body
        raise KeyError(f"版本 {want} 的段落为空")
    raise KeyError(f"CHANGELOG.md 中找不到版本 {want}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抽取 CHANGELOG 某版本的正文")
    parser.add_argument("version", help="版本号（可带 v 前缀，如 v1.16.3）")
    parser.add_argument("--check", action="store_true", help="只校验该版本存在且非空")
    args = parser.parse_args(argv)

    body = section(CHANGELOG.read_text(encoding="utf-8"), args.version)
    if args.check:
        print(f"OK  版本 {normalize(args.version)} 正文 {len(body.splitlines())} 行")
        return 0
    print(body)
    return 0


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：把 KeyError 转成人读的错误 + 非零退出码。"""
    try:
        return main(argv)
    except KeyError as exc:
        print(f"FAIL  {exc.args[0]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
