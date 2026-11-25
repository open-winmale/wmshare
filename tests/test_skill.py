"""AI skill 守护：SKILL.md 的合同真实性（防臆造接口）、格式合法性与分发。

SKILL.md 是随 wheel 分发给 AI agent 的说明书——里面的每个调用都必须真实存在、
签名可绑定（agent 照着做必须能跑通），格式必须满足 Agent Skills 发现机制。
"""
import ast
import inspect
import re
from pathlib import Path

from wmshare import skill_dir
from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
from wmshare.catalog import Catalog, load

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = skill_dir()
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
PYPROJECT = (REPO / "pyproject.toml").read_text(encoding="utf-8")

CAT = load()

_NS_METHOD_RE = re.compile(r"cli\.(\w+)\.(\w+)\(")
_FN_CALL_RE = re.compile(r'cli\.call(?:_batch)?\(\s*"([a-z][\w]*\.[a-z][\w]*)"')
_CAT_METHOD_RE = re.compile(r"cat\.(\w+)\(")


def _frontmatter() -> dict[str, str]:
    """顶层扁平 key: value 解析（Agent Skills 要求 frontmatter 扁平，缩进键无效）。"""
    assert SKILL.startswith("---\n"), "SKILL.md 缺少 frontmatter"
    body = SKILL.split("\n---\n", 1)[0][4:]
    meta: dict[str, str] = {}
    for ln in body.splitlines():
        if not ln.strip() or ln.startswith((" ", "\t", "#")):
            continue
        key, _, value = ln.partition(":")
        assert key.strip() == key, f"frontmatter 键含缩进（无效）：{ln!r}"
        meta[key.strip()] = value.strip()
    return meta


def test_frontmatter_valid():
    meta = _frontmatter()
    assert meta.get("name") == SKILL_DIR.name, "name 必须与目录名一致"
    desc = meta.get("description", "")
    assert desc, "缺 description 的 skill 永远不会被触发"
    assert len(desc) <= 1024, f"description 超长（{len(desc)} > 1024）"
    # 触发词前置：发现机制只看 name + description（约前 250 字符），
    # 高频意图词必须出现在前 250 字符内
    head = desc[:250]
    for kw in ("A 股数据", "K 线", "指标", "选股", "分红", "公告"):
        assert kw in head, f"触发词 {kw!r} 未前置在 description 前 250 字符"
    assert SKILL.count("\n") < 500, "SKILL.md 应保持 <500 行（渐进披露：细节路由到目录）"


def test_skill_no_stale_trial_promises():
    """1.7.0 起凭证必填：SKILL.md 不得残留「开箱即用/共享池」类旧承诺（行内含
    「不再内置/已下线」豁免——描述删除本身合法）。"""
    banned = ("开箱即用", "共享池", "zero-config", "内置体验 appid")
    exempt = ("不再内置", "已下线")
    for i, line in enumerate(SKILL.splitlines(), 1):
        low = line.lower()
        if any(b in low for b in banned) and not any(e in line for e in exempt):
            raise AssertionError(f"SKILL.md:{i} 残留过期承诺：{line.strip()}")


def test_skill_calls_are_real():
    """防臆造（关键守护）：文中每个 cli.* / cat.* 调用都必须真实存在且可绑定。"""
    blocks = re.findall(r"```python\n(.*?)```", SKILL, re.S)
    assert blocks, "SKILL.md 缺少 python 示例"
    for block in blocks:
        for node in ast.walk(ast.parse(block)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)):
                continue
            if f.value.id == "cli" and f.attr in ("call", "call_batch"):
                assert node.args and isinstance(node.args[0], ast.Constant)
                CAT.function(node.args[0].value)   # 目录级校验（防编造）
            elif isinstance(f.value, ast.Attribute) and f.value.attr == "cli":
                continue  # wmshare.Client() 等包级调用
            elif f.value.id == "cli":
                ns, method = f.value.attr, f.attr
                cls = FRIENDLY_NAMESPACES.get(ns) or GENERATED_NAMESPACES.get(ns)
                assert cls is not None, f"SKILL.md 引用了不存在的命名空间 {ns}"
                assert hasattr(cls, method), f"SKILL.md 引用了不存在的方法 {ns}.{method}"
                sig = inspect.signature(getattr(cls, method))
                kwargs = {kw.arg: None for kw in node.keywords if kw.arg}
                sig.bind(None, *[None] * len(node.args), **kwargs)
            elif f.value.id == "cat":
                assert callable(getattr(Catalog, f.attr, None)), \
                    f"SKILL.md 引用了不存在的目录方法 cat.{f.attr}()"


def test_skill_inline_references_are_real():
    """决策树表格等行内代码同样不得臆造（正文非代码块部分用正则校验）。"""
    for ns, method in _NS_METHOD_RE.findall(SKILL):
        cls = FRIENDLY_NAMESPACES.get(ns) or GENERATED_NAMESPACES.get(ns)
        assert cls is not None, f"SKILL.md 行内引用了不存在的命名空间 {ns}"
        assert hasattr(cls, method), f"SKILL.md 行内引用了不存在的方法 {ns}.{method}"
    for full in set(_FN_CALL_RE.findall(SKILL)):
        CAT.function(full)
    for meth in set(_CAT_METHOD_RE.findall(SKILL)):
        assert meth == "load" or callable(getattr(Catalog, meth, None)), \
            f"SKILL.md 行内引用了不存在的目录方法 cat.{meth}()"


def test_skill_scene_files_calls_are_real():
    """scenes/*.md（渐进披露的场景深流程）与 SKILL.md 同待遇：cli 调用必须真实存在。

    场景文件只在 agent 命中对应意图时才读——所以允许更长，但臆造接口的
    伤害一样大，故同规则校验（目录先行纪律同样适用于场景层）。
    """
    scene_re = re.compile(r"cli\.(\w+)\.(\w+)\(")
    for path in sorted(SKILL_DIR.glob("scenes/*.md")):
        text = path.read_text(encoding="utf-8")
        for ns, method in scene_re.findall(text):
            cls = FRIENDLY_NAMESPACES.get(ns) or GENERATED_NAMESPACES.get(ns)
            assert cls is not None, f"{path.name} 引用了不存在的命名空间 {ns}"
            assert hasattr(cls, method), f"{path.name} 引用了不存在的方法 {ns}.{method}"
        for full in set(_FN_CALL_RE.findall(text)):
            CAT.function(full)


def test_skill_ships_in_wheel():
    """skill 随 wheel 分发：package-data 声明 + skill_dir() 指向真实文件。"""
    assert '"skills/wmshare/*.md"' in PYPROJECT, "pyproject 未声明 skills 数据"
    assert (SKILL_DIR / "SKILL.md").is_file()
    import wmshare
    assert "skill_dir" in wmshare.__all__


def test_skill_wording_guards():
    """关键纪律必须在文：单位铁律、目录先行、错误引导、许可证边界。"""
    for kw in ("小数", "cat.search", "禁止编造", "open.winmale.com", "DataError",
               "BSD-3-Clause", "0.0396 = 3.96%"):
        assert kw in SKILL, f"SKILL.md 缺少关键内容：{kw}"
