"""数据目录装载/查询测试（不联网）。"""
import wmshare
from wmshare.catalog import load


def test_load_and_stats():
    cat = load()
    s = cat.stats()
    assert s["domains"] == 18, s
    assert s["functions"] == 266, s
    assert s["raw"] == 184 and s["computed"] == 82, s
    assert s["metric_catalog_total"] == 2752, s
    assert s["upstream_rev"], "inventory 应锚定 upstream rev"


def test_macro_domain_contract():
    """v1.11.0 宏观域：11 函数全 L0、params 精修齐、预加载。"""
    cat = load()
    dom = cat.domain("market.macro")
    assert dom["kind"] == "raw" and dom["category"] == "reference"
    assert len(dom["functions"]) == 11
    fn = cat.function("macro.query")
    assert [p["name"] for p in fn["params"]] == ["code", "n"]
    assert fn["params"][1]["default"] == 4
    assert "macro" in cat.inventory["preloaded_libs"]


def test_fut_metric_market_scope():
    """$FUT_* 共享路径指标码必须带 markets=["cn"]（用错市场客户端必 500）。"""
    cat = load()
    row = cat.metric("$FUT_CLOSE")
    assert row is not None and row.get("markets") == ["cn"], row
    fut = [m for m in cat.metrics["metrics"] if m["code"].startswith("$FUT")]
    assert len(fut) == 27
    assert all(m.get("markets") == ["cn"] for m in fut)


def test_function_contract():
    fn = load().function("kline.query_bars")
    assert fn["domain"] == "market.kline"
    assert [p["name"] for p in fn["params"]] == ["sym", "limit"]
    limit = fn["params"][1]
    assert limit["type"] == "int" and limit["default"] == 120
    assert fn["returns_shape"], "query_bars 应有字段级 returns_shape"
    fields = {f["name"] for f in fn["returns_shape"]["items"]["fields"]}
    assert {"date", "open", "close", "volume", "percent"} <= fields
    assert fn["inventory_example"].startswith("kline.query_bars(")


def test_raw_vs_computed_distinction():
    cat = load()
    # 原始：披露/直采
    assert cat.function("kline.query_bars")["kind"] == "raw"
    assert cat.function("bonus.query_list")["kind"] == "raw"
    assert cat.function("forecast.yjyg_rows")["kind"] == "raw"
    # 自产：计算派生
    assert cat.function("bonus.snapshot_yield_ttm")["kind"] == "computed"
    assert cat.function("kline.index_breadth_summary")["kind"] == "computed"
    # 域缺省：指标域=computed，报表域=raw
    assert cat.domain("fund.indicators")["kind"] == "computed"
    assert cat.domain("fund.statements")["kind"] == "raw"


def test_normalized_function_shapes_follow_fmt_maps():
    """公告/分红规范化后，目录里的 returns_shape 也必须是扁平字段。"""
    cat = load()
    notice = cat.function("notice.query_by_symbol")
    assert notice["normalize_with"] == "notice.fmt_maps"
    notice_fields = {f["name"] for f in notice["returns_shape"]["items"]["fields"]}
    assert {"date", "announce_date", "code", "title", "url"} <= notice_fields

    bonus = cat.function("bonus.query_list")
    assert bonus["normalize_with"] == "bonus.fmt_maps"
    bonus_fields = {f["name"] for f in bonus["returns_shape"]["items"]["fields"]}
    assert {"sas", "announce", "ex_date", "ex_div", "pay", "dps", "total"} <= bonus_fields


def test_namespaces_and_metrics():
    cat = load()
    assert {"kline", "moneyflow", "notice", "filings", "forecast",
            "bonus", "rptdom", "segments", "equity", "margin", "estimates",
            "cbond", "workout", "indices", "intl", "stocks", "macro"} == cat.namespaces()
    m = cat.metric("$PE_TTM_LAST")
    assert m and m["cn"]
    assert cat.metric("$NOT_EXIST") is None


def test_scope_and_categories():
    cat = load()
    cats = {d["category"] for d in cat.domains.values()}
    assert cats == {"market", "fundamentals", "disclosure", "reference"}
    # 财报提取类域不发布
    assert "fin.report" not in cat.domains
    # 股本股东（v1.5 起具备函数面；requires 指向 sys/equity 预载链）
    assert cat.domain("corp.equity")["stores"] == ["biz.equity", "ref.info"]
    assert cat.domain("corp.equity")["requires"]["path"] == "sys/equity/init.xs"
    assert len(cat.domain("corp.equity")["functions"]) == 49


def test_curated_metric_groups_exist():
    cat = load()
    dom = cat.domain("fund.indicators")
    groups = {g["id"] for g in dom["metric_groups"]}
    assert {"valuation", "profitability", "growth", "dividend", "revenue_mix"} <= groups
    for g in dom["metric_groups"]:
        assert g["caliber"], f"指标组 {g['id']} 缺公式口径"
        assert g["depends_on"], f"指标组 {g['id']} 缺依赖域"


def test_package_version():
    assert wmshare.__version__


def test_version_single_source_of_truth():
    """__version__ 必须与 pyproject.toml 一致——双源漂移曾导致 1.9.0 的 wheel
    里 import 出来是 1.8.1（bump pyproject 时漏改 __init__，发布前才发现）。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "pyproject.toml 缺 version"
    assert wmshare.__version__ == m.group(1), (
        f"版本双源漂移：__init__={wmshare.__version__} vs pyproject={m.group(1)}")


def test_catalog_shipped_inside_package():
    """独立性合同：目录数据必须随包分发（pip 安装后离线可用，不依赖仓库/内部工程）。"""
    import wmshare.catalog as catmod
    from pathlib import Path
    pkg_root = Path(catmod.__file__).resolve().parent
    cdir = catmod.catalog_dir()
    assert cdir == pkg_root / "_catalog"
    assert (cdir / "schema" / "domain.schema.json").is_file()
    assert len(list((cdir / "domains").glob("*.yaml"))) == 18
    for g in ("inventory.json", "metrics.json"):
        assert (cdir / "generated" / g).is_file()
