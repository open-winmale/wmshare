#!/usr/bin/env python3
"""版本一致性门禁（发版 / CI 必跑）：六处声明必须同指一个版本号。

锁死的六处（任一处腐化即失败，并逐处列出实际值）：
  1. src/wmshare/__init__.py::__version__          （基准，单一事实源）
  2. pyproject.toml::project.version               （static）或 dynamic→wmshare.__version__
  3. server.json::version
  4. server.json::packages[0].version
  5. docs/openapi.json::info.version
  6. CHANGELOG.md 顶部 release 段（跳过 [Unreleased]）

pyproject 支持两种声明：
  - static：project.version = "x.y.z"（旧写法，仍校验值相等）
  - dynamic：project.dynamic 含 "version" 且 tool.setuptools.dynamic.version.attr
    == "wmshare.__version__"（M3 起推荐：构建时由 __init__ 注入，零重复硬编码）

另锁 SECURITY.md：当前 minor 线表头 == 基准 major.minor，
Last reviewed 的 as_of == 基准完整版本号。

全程只读；不依赖 wmshare 运行时与第三方包（tomllib 为 3.11+ 标准库，
3.10 回退 tomli，后者为 dev 依赖），便于在门禁环境独立执行。

Usage: python3 tools/check_version.py [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.10：dev 依赖 tomli
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "src" / "wmshare" / "__init__.py"
PYPROJECT = REPO / "pyproject.toml"
SERVER_JSON = REPO / "server.json"
OPENAPI = REPO / "docs" / "openapi.json"
CHANGELOG = REPO / "CHANGELOG.md"
SECURITY = REPO / "SECURITY.md"

MISSING = "（缺失）"
EXPECTED_DYNAMIC_ATTR = "wmshare.__version__"


def _match(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.M)
    if not m:
        return MISSING
    return m.group(1)


def _pyproject_version(baseline: str) -> tuple[str, bool]:
    """返回 (报告值, 是否与基准一致)。兼容 static 与 dynamic 两种声明。"""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    proj = data.get("project", {}) or {}
    if "version" in proj:  # static：直接比对值
        val = str(proj["version"])
        return val, val == baseline
    dyn = proj.get("dynamic", []) or []
    if "version" in dyn:  # dynamic：校验 attr 指向基准模块
        tool = data.get("tool", {}) or {}
        st = tool.get("setuptools", {}) or {}
        attr = (st.get("dynamic", {}) or {}).get("version", {}) or {}
        attr = attr.get("attr")
        if attr != EXPECTED_DYNAMIC_ATTR:
            return f"dynamic→{attr}", False
        # attr 指向基准模块，构建时由 __init__ 注入，必然与基准一致。
        return f"dynamic→{EXPECTED_DYNAMIC_ATTR}", True
    return MISSING, False


def collect() -> tuple[str, dict[str, tuple[str, bool]], dict[str, str]]:
    """Return (baseline, six sources as (value, ok), security checks)."""
    init = INIT.read_text(encoding="utf-8")
    baseline = _match(r'__version__\s*=\s*"([^"]+)"', init)
    if baseline == MISSING:
        raise ValueError(f"{INIT} 里找不到 __version__，无法作为互校基准")

    server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    packages = server.get("packages") or [{}]
    openapi_ver = str(
        json.loads(OPENAPI.read_text(encoding="utf-8")).get("info", {}).get("version")
        or MISSING)
    changelog_ver = _match(
        r"^##\s*\[(\d+\.\d+\.\d+[^\]]*)\]", CHANGELOG.read_text(encoding="utf-8"))

    pyproj_val, pyproj_ok = _pyproject_version(baseline)

    sources = {
        "src/wmshare/__init__.py::__version__": (baseline, True),
        "pyproject.toml::project.version": (pyproj_val, pyproj_ok),
        "server.json::version": (str(server.get("version") or MISSING),
                                 str(server.get("version")) == baseline),
        "server.json::packages[0].version": (str(packages[0].get("version") or MISSING),
                                             str(packages[0].get("version")) == baseline),
        "docs/openapi.json::info.version": (openapi_ver, openapi_ver == baseline),
        "CHANGELOG.md::top release": (changelog_ver, changelog_ver == baseline),
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
    mismatches = [(where, got) for where, (got, ok) in sources.items() if not ok]
    mismatches += [(where, got) for where, got, expected in security_rows if got != expected]

    if mismatches:
        bad = {where for where, _ in mismatches}
        print("check_version FAIL：版本声明不一致（逐处实际值如下）", file=sys.stderr)
        for where, (got, ok) in sources.items():
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
