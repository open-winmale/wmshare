"""内部目录命名空间的可见性门禁。

背景（2026-11-14）：目录命名空间 ``rptdom`` 必须留在随包 inventory 中——
``cli.statements.*`` 友好门面靠 ``catalog.function()`` 的目录感知委托工作；
但它属于内部实现细节，**不得**以 ``rptdom.xxx`` 形式出现在任何对用户或 Agent
可见的清单（API 文档、OpenAPI、llms、示例、技能文档、MCP 注册清单）。

发布政策要求「例外须单独走暴露审批」；本测试同时钉住：
  1. 对外清单零内部命名空间字面量；
  2. 友好门面仍然存在且每个方法都能回溯到目录契约；
  3. 内部命名空间集合与 inventory 实际出现的内部前缀一致，防止偷偷扩散。
"""
from __future__ import annotations

import sys
from pathlib import Path

import wmshare
from wmshare.api import COMPOSITE_METHODS
from wmshare.api import FRIENDLY_INDEX, _FRIENDLY_NS_TO_CATALOG

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))


def _introspect():
    # 必须走正常 import：模块内有 @dataclass，importlib 手工 exec 时
    # sys.modules 缺项会让 dataclasses 解析 cls.__module__ 失败。
    import _introspect
    return _introspect


def _public_files() -> list[Path]:
    files = [
        REPO / "README.md", REPO / "CHANGELOG.md", REPO / "CONTRIBUTING.md",
        REPO / "SECURITY.md", REPO / "llms.txt", REPO / "llms-full.txt",
        REPO / "server.json", REPO / "INDICATORS.md",
    ]
    files += sorted((REPO / "docs").rglob("*.md"))
    files += sorted((REPO / "docs").rglob("*.json"))
    files += sorted((REPO / "docs").rglob("*.html"))
    files += sorted((REPO / "examples").rglob("*.py"))
    files += sorted((REPO / "src" / "wmshare" / "skills").rglob("*.md"))
    return [p for p in files if p.is_file()]


def test_internal_ns_absent_from_every_public_asset():
    ext = _introspect()
    leaked: list[str] = []
    for path in _public_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for ns in ext.INTERNAL_CATALOG_NS:
            if f"{ns}." in text:
                leaked.append(f"{path.relative_to(REPO)}: {ns}")
    assert not leaked, f"对外清单泄露内部命名空间：{leaked}"


def test_friendly_statements_facade_is_intact():
    """隐藏内部名字不得以牺牲 cli.statements.* 为代价（组合门面：三加一 + audit）。"""
    docs = (REPO / "docs" / "API.md").read_text(encoding="utf-8")
    spec = (REPO / "docs" / "openapi.json").read_text(encoding="utf-8")
    composite = COMPOSITE_METHODS.get("statements", set())
    assert composite == {"balance", "income", "cashflow", "indicators"}
    assert _FRIENDLY_NS_TO_CATALOG.get("statements") == "rptdom"
    for method in sorted(composite | {"audit"}):
        assert f"cli.statements.{method}" in docs, f"docs/API.md 缺少 {method}"
    assert "statements_audit" in spec, "openapi 缺少 statements 友好 operation"



def test_catalog_contract_still_backs_every_facade_method():
    """门面委托的每个 underlying 在随包目录里必须可查。"""
    ext = _introspect()
    cat = wmshare.load()
    for _, ns, method, _, underlying in FRIENDLY_INDEX:
        if ns != "statements":
            continue
        fn_key = ext.underlying_fn(underlying)
        assert fn_key, f"{ns}.{method} 缺少底层函数名"
        assert ext.is_internal_catalog_name(fn_key)
        meta = cat.function(fn_key)
        assert meta.get("name") == fn_key


def test_internal_ns_set_covers_inventory_prefixes():
    """inventory 里出现的内部命名空间必须都在管控集合内（聚合校验，不列名）。"""
    ext = _introspect()
    inv = wmshare.load().inventory
    names = [f["name"] for f in inv["functions"]]
    internal = {n for n in names if ext.is_internal_catalog_name(n)}
    assert internal, "内部命名空间函数应仍保留在目录中（门面委托依赖）"
    assert all(n.partition(".")[0] in ext.INTERNAL_CATALOG_NS for n in internal)
    assert len(internal) == 5, f"内部命名空间函数数量变化：{len(internal)}"


def test_doc_hidden_rule_covers_internal_namespace():
    """文档生成器的隐藏规则必须覆盖内部命名空间，且不误伤普通函数。"""
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    from gen_api_docs import doc_hidden  # noqa: E402

    assert doc_hidden({"name": "rptdom.statement"})
    assert doc_hidden({"name": "rptdom.mkt_latest"})
    assert not doc_hidden({"name": "kline.query_bars"})
    assert not doc_hidden({"name": "cbond.card"})
