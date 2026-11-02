"""把 wmshare 作为本地 MCP server 接入 AI 客户端。

前提：离线自检零凭证；真实取数需开放平台 AppID
运行：python examples/12_mcp_server.py
学到：wmshare-mcp 安装、setup/doctor、最小 MCP client 配置与 20 个工具入口
文档：docs/AI.md（MCP 优先路径）、README.md（MCP server 快速开始）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


CLIENT_CONFIG = {
    "mcpServers": {
        "wmshare": {
            "command": "wmshare-mcp",
            "args": [],
        }
    }
}


def main() -> None:
    executable = shutil.which("wmshare-mcp")
    install_hint = '未安装；先执行 pip install "wmshare[mcp]"'
    print(f"wmshare-mcp 位置：{executable or install_hint}")
    if executable:
        result = subprocess.run(
            [executable, "--check"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="", file=sys.stderr)
            raise SystemExit(result.returncode)

    print("\n开放平台凭证只写本地凭证文件；不要写进代码或 MCP 配置：")
    print("  open.winmale.com → 我的应用 → 复制 client_id 与 api-key")
    print('  wmshare-mcp setup --client-id ... --client-secret-stdin --market cn')
    print("  wmshare-mcp doctor")
    print("\nAI 客户端最小配置（不含凭证）：")
    print(json.dumps(CLIENT_CONFIG, ensure_ascii=False, indent=2))
    print("\n工具入口：20 个 task tools；长尾 friendly API 用")
    print("wmshare_call(mode='api')；多标的用 wmshare_batch(params=...)。")


if __name__ == "__main__":
    main()
