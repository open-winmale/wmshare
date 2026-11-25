#!/usr/bin/env python3
"""生成 docs/changelog.xml：CHANGELOG.md → RSS 2.0 订阅源（变更公告）。

只收录正式版本段（跳过 `[Unreleased]`），按 Added/Changed/Deprecated/Removed/
Fixed/Security 分类；`Deprecated` / `Removed` 即接口变更公告的机器可读入口。

Usage:
  python3 tools/gen_changelog_feed.py          # write docs/changelog.xml
  python3 tools/gen_changelog_feed.py --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"
OUT = REPO / "docs" / "changelog.xml"
SITE = "https://github.com/open-winmale/wmshare"
MAX_ITEMS = 20

HEAD_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$")
CAT_RE = re.compile(r"^### (Added|Changed|Deprecated|Removed|Fixed|Security)\s*$")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _rfc822(iso: str) -> str:
    d = date.fromisoformat(iso)
    return (f"{WEEKDAYS[d.weekday()]}, {d.day:02d} {MONTHS[d.month - 1]} "
            f"{d.year} 00:00:00 +0800")


def parse_changelog(text: str) -> list[dict]:
    versions: list[dict] = []
    cur: dict | None = None
    cat: str | None = None
    for line in text.splitlines():
        m = HEAD_RE.match(line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2), "items": []}
            versions.append(cur)
            cat = None
            continue
        if cur is None:
            continue
        m = CAT_RE.match(line)
        if m:
            cat = m.group(1)
            continue
        if line.startswith("## "):  # 下一个非版本段（如 Unreleased 之后的其它标题）
            cur, cat = None, None
            continue
        if cat and line.startswith("- "):
            cur["items"].append((cat, line[2:].strip()))
        elif cat and cur["items"] and line.startswith("  ") and line.strip():
            last_cat, last = cur["items"][-1]
            cur["items"][-1] = (last_cat, f"{last} {line.strip()}")
    return versions


def build() -> str:
    versions = parse_changelog(CHANGELOG.read_text(encoding="utf-8"))[:MAX_ITEMS]
    last = versions[0] if versions else {"version": "0.0.0", "date": "1970-01-01"}
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        "    <title>wmshare releases</title>",
        f"    <link>{SITE}</link>",
        "    <description>wmshare 版本变更与接口弃用公告（由 CHANGELOG.md 生成）</description>",
        "    <language>zh-CN</language>",
        f"    <lastBuildDate>{_rfc822(last['date'])}</lastBuildDate>",
        f'    <atom:link href="{SITE}/raw/main/docs/changelog.xml" rel="self" '
        'type="application/rss+xml"/>',
    ]
    for v in versions:
        title = f"wmshare {v['version']} ({v['date']})"
        link = f"{SITE}/releases/tag/v{v['version']}"
        blocks: list[str] = []
        for cat in ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"):
            items = [text for c, text in v["items"] if c == cat]
            if items:
                blocks.append(cat + "\n" + "\n".join(f"- {t}" for t in items))
        desc = "\n\n".join(blocks) or "—"
        out += [
            "    <item>",
            f"      <title>{html.escape(title)}</title>",
            f"      <link>{link}</link>",
            f'      <guid isPermaLink="false">wmshare:{v["version"]}</guid>',
            f"      <pubDate>{_rfc822(v['date'])}</pubDate>",
            f"      <description>{html.escape(desc)}</description>",
            "    </item>",
        ]
    out += ["  </channel>", "</rss>", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    body = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != body:
            print("gen_changelog_feed drift: docs/changelog.xml", file=sys.stderr)
            return 1
        print("gen_changelog_feed ok")
        return 0
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
