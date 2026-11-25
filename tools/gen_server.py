#!/usr/bin/env python3
"""从 src/wmshare/__init__.py::__version__ 生成仓库根的 server.json（MCP server 注册清单）。

server.json 是 MCP 注册清单（schema: static.modelcontextprotocol.io/.../server.schema.json），
版本号出现两处（顶层 ``version`` + ``packages[0].version``），历史上手填易与 SDK 版本漂移。
改为由单一事实源 ``__version__`` 生成，``--check`` 做漂移门禁：与已提交 server.json 不一致即非零退出。

设计要点：
  - 全程只读依赖 ``__init__.py`` 文本解析（不 import wmshare，避免门禁环境引入运行时依赖副作用）。
  - 以当前 server.json 为模板，仅覆写两处版本号，保持其它字段 / 顺序不变，
    故常态下磁盘文件零 diff（机制改造，不改交付物内容）。
  - pyproject 同步声明 ``dynamic = ["version"]`` + ``attr = "wmshare.__version__"``，
    构建时由 setuptools 从同一基准注入，六处版本声明收敛到单一来源。

Usage:
    python3 tools/gen_server.py           # 用 __version__ 重写 server.json
    python3 tools/gen_server.py --check   # 仅校验与生成结果一致（CI 门禁）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "src" / "wmshare" / "__init__.py"
SERVER_JSON = REPO / "server.json"
_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


def read_version() -> str:
    """从 __init__.py 文本解析 __version__（与 check_version 基准同源）。"""
    m = _VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{INIT} 里找不到 __version__，无法作为生成基准")
    return m.group(1)


def expected_json(version: str) -> str:
    """以当前 server.json 为模板，仅覆写两处版本号，其它字段 / 顺序不变。"""
    data = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    data["version"] = version
    data["packages"][0]["version"] = version
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="只校验，不写入")
    args = ap.parse_args(argv)

    version = read_version()
    text = expected_json(version)
    current = SERVER_JSON.read_text(encoding="utf-8") if SERVER_JSON.exists() else ""
    if args.check:
        if text != current:
            print("gen_server FAIL：server.json 与 __version__ 生成结果漂移", file=sys.stderr)
            print(f"  基准 __version__ = {version}", file=sys.stderr)
            print("  运行 python tools/gen_server.py 重新生成后提交", file=sys.stderr)
            return 1
        print(f"gen_server ok：server.json 两处版本号 == __version__ ({version})")
        return 0
    SERVER_JSON.write_text(text, encoding="utf-8")
    print(f"gen_server：已用 __version__={version} 重写 server.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
