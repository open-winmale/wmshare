"""把 wmshare 的 AI skill 装进你的 agent：一条命令，AI 即可正确使用 SDK。

前提：离线可跑（不联网、零凭证）
运行：python examples/09_ai_skill_setup.py
学到：skill_dir() 定位随包用法说明；agent 发现路径；AI 正确行为的验证标准
文档：docs/AI.md（MCP/skill/文档/报错接入路径、提示词模板、常见错误对照表）
"""
from pathlib import Path

import wmshare

AGENT_SKILL_DIRS = {
    "个人级（多数 agent 通用）": "~/.agents/skills/wmshare",
    "ZCode 项目级": ".zcode/skills/wmshare",
    "Claude Code 项目级": ".claude/skills/wmshare",
}


def main() -> None:
    skill_dir = Path(wmshare.skill_dir())
    skill_md = skill_dir / "SKILL.md"
    print(f"skill 位置：{skill_dir}")
    assert skill_md.is_file(), f"安装不完整：缺 {skill_md}"
    text = skill_md.read_text(encoding="utf-8")
    for marker in ("目录先行", "单位铁律", "WmshareError"):
        assert marker in text, f"skill 内容异常：缺「{marker}」"
    print("skill 自检：目录先行 / 单位铁律 / 错误速查 均在 ✓")

    print("\n装进 agent（任选其一，复制整段执行）：")
    for label, target in AGENT_SKILL_DIRS.items():
        print(f"  # {label}")
        print(f'  cp -r "{skill_dir}" {target}')

    print("\n装好后这样验证（把这句话发给 AI）：")
    print('  「用 wmshare 帮我取 600519 近 30 根日 K，并给出 TTM 股息率与 PE 分位。」')
    print("  正确行为：先查目录（cat.search），再写 cli.kline.bars / cli.indicator.get；")
    print("  涨跌幅 / 股息率 / 分位一律读小数（0.0396 = 3.96%），不要自己 ×100。")


if __name__ == "__main__":
    main()
