#!/usr/bin/env python3
"""Leak gate before publishing to GitHub (ROADMAP M1.1).

Scans all git-tracked files for:
  - internal hostnames / NAS paths / developer machine paths
  - secret-looking assignments (CLIENT_SECRET=..., token literals)
  - tracked files outside the public whitelist (CONTRIBUTING.md 入库白名单),
    so internal planning/process docs can never slip back into the repo
Exits 1 on any hit. Wired into CI (gates job) and pre-push habit.

Usage: python3 tools/check_leak.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 内置体验 appid 的针值：明文入库即成痕迹（同下方第三方禁词表先例），
# 故以 XOR+base64 混淆 blob 存放。任何跟踪文件出现明文（含 README/测试/示例）一律视为泄漏
_EXPERIENCE_BLOB = "LTcFNSo/NAUjYzAsMjA0N25jMTZpPzZoUGk/bmtpY245PjtvOGM4OTs/OT9raDlvYz45PmhpYmg4am9pODhsY2psbmluP2xqPA=="
_EXPERIENCE_KEY = 0x5A


def _experience_needles() -> list[str]:
    """解码内置体验 appid/secret 针值（两行）。"""
    import base64

    raw = bytes(b ^ _EXPERIENCE_KEY for b in base64.b64decode(_EXPERIENCE_BLOB))
    return [w for w in raw.decode("utf-8").splitlines() if w]


# 内部域名 / 基础设施路径（对外不可见的信息）
FORBIDDEN_SUBSTRINGS = [
    "code.yepless.cn",
    "datanas",
    "less.server",
    "skillhub-releases",
    "winmale/.skillhub",
] + _experience_needles()

# 第三方产品/数据商引用：项目规范禁止出现（含竞品对标与数据来源点名）。
# 词表本身也是第三方内容——明文入库即成痕迹，故以 XOR+base64 混淆 blob 存放
# （同 _experience.py 先例；历史上该表曾明文入库，1.8.1 起混淆化）。
_WORDS_BLOB = "Li8pMjsoP1AtOz4zLi9QvNbMv8bqv9/OUDsxKTI7KD9QODs1KS41OTFQPzspLjc1ND8jUL7ixrLu+FC8zOq87/BQKTM0O1Cy3+Sy9PVQLj80OT80LlCy28C84MpQvcrcvMfVvuHbUDYzIjM0PSg/NFC/7fK85/RQs8HwvcrZUCIvPyszL1C/ytay0Ouz++BQs830su74UDMtPzQ5OzNQa2owKzE7ULPawLLk5L7l+1AuPiJQBjgtMzQ+BjhQvuLdv+TNUDg2NTU3OD8oPVA8MzR3PyIuKDs5LlAoKi4uOzhQvNTCs93LULLbwL/051AwNTM0Ky87NC5QvevpvffKUCgzOT8rLzs0LlAuKQU5NT4/UD83BSk/OTM+"
_WORDS_KEY = 0x5A


def thirdparty_words() -> list[str]:
    """解码第三方禁词表（含词边界型正则片段，如 \\bwind\\b）。"""
    import base64

    raw = bytes(b ^ _WORDS_KEY for b in base64.b64decode(_WORDS_BLOB))
    return [w for w in raw.decode("utf-8").splitlines() if w]


def thirdparty_pattern() -> re.Pattern:
    """编译第三方禁词正则；守护测试（test_docs）复用同一来源，避免字面量二次入库。"""
    parts = [w if w.startswith("\\b") else re.escape(w) for w in thirdparty_words()]
    return re.compile("|".join(parts), re.IGNORECASE)


THIRDPARTY_RE = thirdparty_pattern()

# 开发者机器路径
FORBIDDEN_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9_]+/"),
    re.compile(r"/home/[A-Za-z0-9_]+/winmale"),
]

# 标的名 fixture（腾讯控股等）所在测试文件豁免第三方扫描；其余扫描照常
THIRDPARTY_SKIP = {"tests/test_symbols.py"}

# 标的数据可包含外部公开 URL 或公司名，可能与禁词撞名；这是「API 返回值」，
# 不是文档里的第三方推荐/对标。豁免只限第三方词扫描；内部标识、机器路径和
# 凭证扫描仍照常执行。
THIRDPARTY_SKIP_PREFIXES = (
    "src/wmshare/_catalog/symbols/",
    "src/wmshare/_demo_data.json",
)

# 凭证赋值（带字面量）
SECRET_RE = re.compile(
    r"(CLIENT_SECRET|client_secret|ACCESS_TOKEN|access_token|api[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    re.IGNORECASE,
)

# 允许出现的公开端点（SDK 的合法目标），不在此列的内网域名会被上面的规则拦下
ALLOWED_MARKERS = ("api.winmale.com", "test-api.winmale.com")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True)
    return [REPO / p for p in out.stdout.splitlines() if p.strip()]


# 允许进入公开仓库的路径白名单（CONTRIBUTING.md「入库白名单」的机器可执行版）。
# 白名单之外任何被 git 跟踪的文件一律视为泄漏——内部规划/流程/路线图文档
# 曾经因只扫关键词而漏网，这里从路径层面兜底。
ALLOWED_PATH_PREFIXES = (
    "src/",
    "tests/",
    "examples/",
    "docs/",
    "tools/",
    ".github/",
)
ALLOWED_PATHS = {
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "NOTICE",
    "AGENTS.md",
    "llms.txt",
    "llms-full.txt",
    "pyproject.toml",
    "server.json",
    ".gitignore",
}


def disallowed_tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True)
    bad: list[str] = []
    for raw in out.stdout.splitlines():
        rel = raw.strip()
        if not rel:
            continue
        if rel.startswith(ALLOWED_PATH_PREFIXES) or rel in ALLOWED_PATHS:
            continue
        bad.append(rel)
    return bad


def _scannable_text(path: Path, raw: str) -> str:
    """ipynb 先剥掉嵌入的 base64 图片载荷再扫：随机 base64 会撞禁词正则
    （图片字节是图表像素，不是行文里的第三方引用——与 THIRDPARTY_SKIP_PREFIXES
    的「API 返回值豁免」同一性质）。其余文件按原文扫描。"""
    if path.suffix != ".ipynb":
        return raw
    try:
        nb = json.loads(raw)
    except ValueError:
        return raw
    for cell in nb.get("cells", []):
        for out in cell.get("outputs", []):
            data = out.get("data")
            if isinstance(data, dict):
                for key in [k for k in data if k.startswith("image/")]:
                    del data[key]
    return json.dumps(nb, ensure_ascii=False)


def scan() -> list[str]:
    findings: list[str] = []
    self_rel = Path(__file__).resolve().relative_to(REPO).as_posix()
    for path in tracked_files():
        if not path.is_file() or path.relative_to(REPO).as_posix() == self_rel:
            continue  # 规则定义文件本身含被扫描字面量，排除
        try:
            text = _scannable_text(path, path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        rel = path.relative_to(REPO).as_posix()
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in text:
                findings.append(f"{rel}: 含内部标识 {needle!r}")
        for pat in FORBIDDEN_PATTERNS:
            m = pat.search(text)
            if m:
                findings.append(f"{rel}: 含机器路径 {m.group(0)!r}")
        if not (rel in THIRDPARTY_SKIP
                or rel.startswith(THIRDPARTY_SKIP_PREFIXES)):
            if THIRDPARTY_RE.search(text):
                findings.append(f"{rel}: 含第三方引用（项目规范禁止）")

        m = SECRET_RE.search(text)
        if m:
            findings.append(f"{rel}: 疑似凭证字面量 {m.group(0)[:40]!r}")
    return findings


def main() -> int:
    findings = scan()
    for rel in disallowed_tracked_files():
        findings.append(f"{rel}: 白名单外文件被 git 跟踪（见 CONTRIBUTING.md 入库白名单，"
                        f"内部规划/流程文档一律不入库）")
    if findings:
        print("FAIL: 泄漏扫描发现以下问题：", file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        return 1
    n = len(tracked_files())
    print(f"leak gate ok ({n} tracked files clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
