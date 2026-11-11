#!/usr/bin/env python3
"""SECURITY.md 支持版本表与包版本一致性门禁（发版时必跑）。

锁死两件事（表头腐化即发版失败）：
  1. 「✅（当前 minor 线）」行的 major.minor 与 `wmshare.__version__` 一致；
  2. 「Last reviewed」行的 as_of 与完整版本号一致。

Usage: python3 tools/check_version.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECURITY = REPO / "SECURITY.md"
INIT = REPO / "src" / "wmshare" / "__init__.py"


def main() -> int:
    init = INIT.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    if not m:
        print(f"check_version: {INIT} 里找不到 __version__", file=sys.stderr)
        return 1
    version = m.group(1)
    minor = ".".join(version.split(".")[:2])

    text = SECURITY.read_text(encoding="utf-8")
    cur = re.search(r"^\|\s*(\d+\.\d+)\.x\s*\|\s*✅（当前 minor 线）", text, re.M)
    if not cur:
        print("check_version: SECURITY.md 缺少「✅（当前 minor 线）」支持行", file=sys.stderr)
        return 1
    if cur.group(1) != minor:
        print(f"check_version: SECURITY.md 当前支持行 {cur.group(1)}.x ≠ 包版本 {minor}.x"
              f"（发版必须同步支持版本表）", file=sys.stderr)
        return 1

    as_of = re.search(r"as_of `([^`]+)`", text)
    if not as_of or as_of.group(1) != version:
        got = as_of.group(1) if as_of else "（缺失）"
        print(f"check_version: SECURITY.md Last reviewed as_of {got} ≠ {version}", file=sys.stderr)
        return 1

    print(f"check_version ok（SECURITY.md 当前支持线 {minor}.x = __version__ {version}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
