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
    """隐藏内部名字不得以牺牲 cli.statements.* 为代价（组合门面：三加一 +
    audit + 4.4 附注/会计政策三面）。"""
    docs = (REPO / "docs" / "API.md").read_text(encoding="utf-8")
    spec = (REPO / "docs" / "openapi.json").read_text(encoding="utf-8")
    composite = COMPOSITE_METHODS.get("statements", set())
    assert composite == {"balance", "income", "cashflow", "indicators",
                         "notes", "notes_index", "policies"}
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


def test_internal_ns_absent_from_runtime_surfaces():
    """运行时面同样不得泄露内部命名空间（2026-11-25 补齐：此前只扫文档）。

    事故背景：Agent 用 ``cat.search("报表")`` 检索时首条命中 ``rptdom.statement``，
    照着调却撞上它要求 ``fin.*`` 全名 domain —— 因为文档侧隐藏、运行时没隐藏。
    """
    from wmshare.client import Client

    ext = _introspect()
    cat = wmshare.load()
    cli = Client(base_url="https://t", client_id="cid", client_secret="sec",
                 catalog=cat, allow_custom_host=True)

    leaked: list[str] = []
    # 1) IDE 补全 / 交互探索面
    for ns in ext.INTERNAL_CATALOG_NS:
        if ns in dir(cli):
            leaked.append(f"dir(cli) 含 {ns}")

    # 2) 属性直达（须在生成门面与 _Namespace 兜底之前拦住）
    for ns in ext.INTERNAL_CATALOG_NS:
        try:
            getattr(cli, ns)
        except AttributeError:
            pass
        else:
            leaked.append(f"cli.{ns} 属性可达")

    # 3) 目录检索（MCP wmshare_search 直接透传此函数）
    for query in ("报表", "statement", "审计"):
        for hit in cat.search(query, limit=50):
            name = str(hit.get("name") or "")
            if name and ext.is_internal_catalog_name(name):
                leaked.append(f"cat.search({query!r}) 命中 {name}")

    # 4) 类型化门面不得生成内部命名空间类
    from wmshare.api import GENERATED_NAMESPACES
    for ns in ext.INTERNAL_CATALOG_NS:
        if ns in GENERATED_NAMESPACES:
            leaked.append(f"GENERATED_NAMESPACES 含 {ns}")

    # 5) 友好命名空间的动态透传：cli.statements.statement 等会经 _Api.__getattr__
    #    拼出 rptdom.* 再委托，Client 层拦截管不到（2026-11-25 审计实证）。
    #    对外只该有组合面四表 + audit 这五个显式方法。
    allowed = {"balance", "income", "cashflow", "indicators", "audit"}
    for name in ("statement", "statement_years", "statement_compare", "statement_tree"):
        if name in allowed:
            continue
        try:
            getattr(cli.statements, name)
        except AttributeError:
            pass
        else:
            leaked.append(f"cli.statements.{name} 动态透传可达")

    assert not leaked, f"运行时泄露内部命名空间：{leaked}"


def test_internal_ns_still_reachable_via_call():
    """收归内部 ≠ 删掉能力：友好门面的底层依赖必须仍可经 cli.call 调。"""
    cat = wmshare.load()
    for underlying in ("rptdom.statement_audit", "rptdom.statement"):
        assert cat.function(underlying), f"{underlying} 必须留在随包目录（门面委托依赖）"
