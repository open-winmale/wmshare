"""extract 同步的暴露面与 rev 锚点防回归门禁。

背景：工具 ``tools/extract_from_scripts.py`` 每次从上游重写
``generated/inventory.json`` 与 ``generated/metrics.json``。发布政策要求：
未审批的命名空间/函数一律不进对外清单。这里用抽取器自身的 ``in_scope``
策略做校验，避免把 38 个不暴露 name 写进测试台账（只做聚合校验、不逐条列名）。

同时钉住「三份生成物必须锚定同一个 upstream_rev」：2026-11-14 同步时
``metric_taxonomy.json`` 的 rev 会跟随 inventory/metrics 一起漂移，漏重跑
就会造成目录自相矛盾。
"""
import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "src" / "wmshare" / "_catalog" / "generated"


def _extractor():
    spec = importlib.util.spec_from_file_location(
        "extract_from_scripts", REPO / "tools" / "extract_from_scripts.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _doc(name: str) -> dict:
    return json.loads((GEN / name).read_text(encoding="utf-8"))


def test_all_published_functions_pass_extractor_scope_policy():
    """generated/inventory.json 不得出现任何白名单外的函数。"""
    ext = _extractor()
    names = [f["name"] for f in _doc("inventory.json")["functions"]]
    leaked = sorted({n for n in names if not ext.in_scope(n)})
    assert not leaked, f"暴露面泄漏 {len(leaked)} 个函数（聚合计数，不列名）"
    assert len(names) == len(set(names)), "函数清单出现重复 name"


def test_rptdom_surface_is_limited_to_approved_statements():
    """rptdom 只保留三表透视族，聚合计数校验、不逐条列名。"""
    ext = _extractor()
    names = [f["name"] for f in _doc("inventory.json")["functions"]]
    rptdom = [n for n in names if n.startswith("rptdom.")]
    assert rptdom, "rptdom 域不应为空"
    assert len(rptdom) == len(ext.RPTDOM_KEEP), (
        f"rptdom 暴露数量 {len(rptdom)} != 审批子集 {len(ext.RPTDOM_KEEP)}")
    assert all(n.partition(".")[2] in ext.RPTDOM_KEEP for n in rptdom)


def test_three_generated_docs_share_one_upstream_rev():
    """inventory / metrics / metric_taxonomy 必须锚定同一个上游 rev。"""
    revs = {name: _doc(name).get("upstream_rev")
            for name in ("inventory.json", "metrics.json", "metric_taxonomy.json")}
    assert all(re.fullmatch(r"[0-9a-f]{8}", r or "") for r in revs.values()), revs
    assert len(set(revs.values())) == 1, f"三份生成物 rev 不一致：{revs}"


def test_packaged_catalog_matches_deterministic_render():
    """离线校验：随包目录必须与抽取器的确定性渲染结果一致（不依赖上游树）。"""
    ext = _extractor()
    inv = _doc("inventory.json")
    met = _doc("metrics.json")
    assert ext.render(inv) == (GEN / "inventory.json").read_text(encoding="utf-8")
    assert ext.render(met) == (GEN / "metrics.json").read_text(encoding="utf-8")
    assert inv["function_count"] == len(inv["functions"])
    assert met["count"] == len(met["metrics"])
