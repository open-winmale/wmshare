"""v1.5 新增 7 个数据域的合同级离线测试（不联网、不臆造业务数值）。

四类合同，逐域参数化：
  1. 目录合同：域注册（category/kind）与函数面完整（cn / inventory 示例 /
     参数可解析 / 规范化后 shape 扁平化）
  2. 规范化引用：normalize_with 目标函数必须存在于同命名空间目录（防悬空）
  3. 单位契约：units percent 声明经 wmshare.units.apply_units 换算为小数
     （合成行仅验证 ×0.01 换算因子，不含任何预期业务数值）
  4. 门面委托：cli.<ns>.<method> 显式核心方法与目录动态委托（fmt_* 等）
     离线可解析并生成合法 XS 脚本（FakeSession 离线传输，零网络请求）
"""
from __future__ import annotations

from typing import Any

import pytest

from wmshare.api import FRIENDLY_INDEX, FRIENDLY_NAMESPACES, _FRIENDLY_NS_TO_CATALOG
from wmshare.catalog import load
from wmshare.units import CONVERSIONS, apply_units

CAT = load()

# 7 个新域的目录合同（id → 命名空间 / 分类 / 性质）
NEW_DOMAINS: dict[str, dict[str, str]] = {
    "corp.equity": {"ns": "equity", "category": "reference", "kind": "raw"},
    "market.margin": {"ns": "margin", "category": "market", "kind": "raw"},
    "market.cbond": {"ns": "cbond", "category": "market", "kind": "raw"},
    "disc.workout": {"ns": "workout", "category": "disclosure", "kind": "raw"},
    "fund.estimates": {"ns": "estimates", "category": "fundamentals", "kind": "raw"},
    "market.index": {"ns": "indices", "dir": "index", "category": "market", "kind": "computed"},
    "market.intl": {"ns": "intl", "category": "reference", "kind": "raw"},
    "market.macro": {"ns": "macro", "category": "reference", "kind": "raw"},
}
DOMAIN_IDS = sorted(NEW_DOMAINS)
# 单位契约：这些域的数据已是基础单位，函数级不应声明换算
# （cbond 1.1.0 起有审计核验的 percent 声明：premiumRatio/couponIr）
# macro v1.11.0：宏观数值为上游原生口径（价格指数点/元），函数级不声明换算
NO_UNITS_DOMAINS = {"market.margin", "fund.estimates", "disc.workout", "market.macro"}
# 仅 ranges 守护（换算声明经审计移除）
RANGES_ONLY_DOMAINS = {"market.index"}
# 规范化行域（normalize_with→fmt_*）：其余三域（cbond/workout/index）无规范化行
NORMALIZE_DOMAINS = {"corp.equity", "market.margin", "fund.estimates", "market.intl"}

# percent 字段换算用例（合成行：只验证 percent→小数的 ×0.01 因子，非业务数值）。
# 口径以 2026-10-28 全量单位审计为准（.internal/UNIT_AUDIT.md）：上游 fmt 部分接口
# 已预换算小数——同接口内混排（如 institution_summary 只有 all_shares_ratio 仍百分数）。
PCT_CONVERSION_CASES: list[tuple[str, dict[str, float]]] = [
    ("equity.query_pledge_detail", {"accum_pledge_tsr": 30.0, "pf_hold_ratio": 12.34}),
    ("equity.query_institution_detail", {"total_shares_ratio": 4.4, "free_shares_ratio": 8.8}),
    ("equity.query_institution_summary", {"all_shares_ratio": 46.0}),
    ("equity.query_hgt", {"add_shares_pct": 0.5}),
    ("equity.query_national_team", {"shares_ratio": 1.2, "shares_ratio_change": 0.1}),
    ("equity.query_release", {"total_shares_ratio": 10.0, "unlimited_ratio": 55.0}),
    ("equity.query_reorg", {"transfer_ratio": 21.0}),
    ("equity.query_concert", {"hold_ratio": 33.3}),
    ("intl.query_ccass", {"pct_of_issued": 5.01}),
]

# 审计实锤「原生已是小数」的字段：不得声明 percent（声明会再除 100，曾在 v1.5.0
# 全量错标）——断言未声明且取数直出不换算。
NO_CONVERSION_CASES: list[tuple[str, dict[str, float]]] = [
    ("equity.query_holder10", {"hold_num_ratio": 0.545}),
    ("equity.query_pledge_summary", {"pledge_ratio": 0.0006}),
    ("equity.query_pledge_industry", {"avg_pledge_ratio": 0.1744}),
    ("equity.query_institution_summary",
     {"total_shares_ratio": 0.7422, "change_ratio": -0.01535}),
    ("equity.query_hgt", {"free_shares_ratio": 3.2e-05, "total_shares_ratio": 3.2e-05}),
    ("indices.weights", {"weight": 0.02127}),
    ("intl.query_shareholders", {"total_shares_ratio": 1e-05}),
]

# 库名 → 门面属性名（indices 库的门面仍叫 cli.index，内建 index 常量占名历史见 market.index.yaml notes）
FRIENDLY_OF = {"indices": "index"}

# 显式核心方法的离线调用用例（每域一条；只断言脚本形态，不断言返回值）
EXPLICIT_CALL_CASES: dict[str, tuple[str, dict[str, Any]]] = {
    "corp.equity": ("query_holdernum", {"symbol": "600519"}),
    "market.margin": ("latest", {"symbol": "600519"}),
    "market.cbond": ("universe_codes", {}),
    "disc.workout": ("board", {}),
    "fund.estimates": ("query_rating", {"symbol": "600519", "limit": 1}),
    "market.index": ("keys", {}),
    "market.intl": ("issue_info", {"symbol": "600519"}),
    "market.macro": ("asof", {"code": "$CPI"}),
}

# 上游预载链差异：cbond/workout 不在 preloaded_libs，取数脚本需自动补 xs.require
PRELOADED_NS = set(CAT.inventory.get("preloaded_libs") or [])


class FakeSession:
    """离线传输：token + eval 固定成功（与 test_contract 同构），零真实网络。"""

    def __init__(self):
        self.calls: list[dict] = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})

        class R:
            status_code = 200
            text = "{}"
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                if url.endswith("/v1/oauth/token"):
                    return {"data": {"access_token": "tok", "expires_in": 3600}}
                return {"success": True, "data": {"result": [{"ok": True}]}}
        return R()


@pytest.fixture()
def cli():
    from wmshare.client import Client
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=CAT, session=FakeSession())


def last_xs(cli) -> list[str]:
    return [x for x in cli.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


def domain_fns(domain: str) -> list[str]:
    return CAT.functions_by_domain()[domain]


# ---------------------------------------------------------------- 1. 目录合同
@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_domain_registered(domain):
    """域已注册且 category/kind 与设计一致；命名空间进入目录覆盖集合。"""
    spec = NEW_DOMAINS[domain]
    doc = CAT.domain(domain)
    assert doc["category"] == spec["category"], domain
    assert doc["kind"] == spec["kind"], domain
    assert doc["version"], domain
    assert domain in CAT.functions_by_domain()
    assert spec["ns"] in CAT.namespaces()


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_function_contracts_complete(domain):
    """域内每个函数：cn / inventory 示例 / 参数合同齐备；规范化函数 shape 已扁平化。"""
    fns = domain_fns(domain)
    assert fns, domain
    for name in fns:
        fn = CAT.function(name)
        assert fn["cn"], name
        assert fn["domain"] == domain
        assert fn["inventory_example"].startswith(name.split(".", 1)[0]), name
        params = fn.get("params") or CAT.inventory_params(name)
        assert isinstance(params, list) and all(p.get("name") for p in params), name
        if fn.get("normalize_with"):
            assert fn["returns_shape"], f"{name}: normalize_with 后应有扁平 returns_shape"


# ---------------------------------------------------------------- 2. 规范化引用
@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_normalize_targets_exist(domain):
    """normalize_with 目标必须存在于同命名空间目录（防悬空引用）；
    规范化行域必须有引用，无规范化行的域不得凭空声明。"""
    ns = NEW_DOMAINS[domain]["ns"]
    hits = 0
    for name in domain_fns(domain):
        target = CAT.function(name).get("normalize_with")
        if not target:
            continue
        assert target.split(".", 1)[0] == ns, f"{name}: 规范化函数跨命名空间 {target}"
        CAT.function(target)  # 未命中抛 CatalogError
        hits += 1
    if domain in NORMALIZE_DOMAINS:
        assert hits, f"{domain}: 期望存在 normalize_with 引用"
    else:
        assert hits == 0, f"{domain}: 无规范化行设计，不应声明 normalize_with"


# ---------------------------------------------------------------- 3. 单位契约
@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_units_contract(domain):
    """声明换算的域必须有 units 且 token 合法；基础单位域不得声明 units。"""
    declared = {n: CAT.function(n).get("units")
                for n in domain_fns(domain) if CAT.function(n).get("units")}
    if domain in NO_UNITS_DOMAINS:
        assert not declared, f"{domain}: 数据已为基础单位，不应声明换算 {sorted(declared)}"
    elif domain in RANGES_ONLY_DOMAINS:
        # index.weights 1.2.0：审计实锤权重原生已小数，percent 声明移除、改 ranges 守护
        assert not declared, f"{domain}: 审计后不应再有 units 声明 {sorted(declared)}"
        assert CAT.function("indices.weights").get("ranges"), "indices.weights 应有 ranges"
    else:
        assert declared, f"{domain}: 期望至少一处 units 声明"
        for name, units in declared.items():
            assert set(units.values()) <= set(CONVERSIONS), name


@pytest.mark.parametrize("name,row", PCT_CONVERSION_CASES)
def test_units_percent_converted_to_decimal(name, row):
    """percent 字段经 apply_units 换算为小数（仅验证 ×0.01 换算因子）。"""
    fn = CAT.function(name)
    assert fn.get("units"), name
    out = apply_units([dict(row)], fn, fname=name)
    for field, raw in row.items():
        assert field in fn["units"], f"{name}: {field} 未声明 percent"
        assert out[0][field] == pytest.approx(raw * CONVERSIONS["percent"]), \
            f"{name}.{field}: percent 应换算为小数（×0.01）"


@pytest.mark.parametrize("name,row", NO_CONVERSION_CASES)
def test_units_audit_decimal_fields_pass_through(name, row):
    """审计实锤为小数的字段必须未声明 percent 且取数直出（防 ×100 错标回潮）。"""
    fn = CAT.function(name)
    units = fn.get("units") or {}
    out = apply_units([dict(row)], fn, fname=name)
    for field, raw in row.items():
        assert field not in units, \
            f"{name}.{field}: 审计实测原生已小数，不得声明 percent（会再除 100）"
        assert out[0][field] == raw, f"{name}.{field}: 未声明字段应原值直出"


# ---------------------------------------------------------------- 4. 门面委托
@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_facade_registered_and_delegates(cli, domain):
    """cli.<ns> 门面已注册；核心方法可解析；目录内其余函数经 __getattr__ 动态委托。"""
    ns = NEW_DOMAINS[domain]["ns"]
    friendly = FRIENDLY_OF.get(ns, ns)
    assert FRIENDLY_NAMESPACES[friendly].__name__
    assert _FRIENDLY_NS_TO_CATALOG[friendly] == ns
    facade = getattr(cli, friendly)
    assert isinstance(facade, FRIENDLY_NAMESPACES[friendly])
    core = {m for _, n, m, _, _ in FRIENDLY_INDEX if n == friendly}
    assert core, f"{ns}: FRIENDLY_INDEX 应登记核心接口"
    for method in core:
        assert callable(getattr(type(facade), method, None)), f"{ns}.{method} 应为显式方法"
    all_short = {n.split(".", 1)[1] for n in domain_fns(domain)}
    for short in all_short - core:
        delegate = getattr(facade, short)
        assert callable(delegate), f"{ns}.{short} 应可动态委托"
        assert delegate.__name__ == short
    with pytest.raises(AttributeError):
        getattr(facade, "no_such_catalog_function")


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_explicit_method_generates_script(cli, domain):
    """显式核心方法离线调用：生成合法 XS（preloaded 域免 require，规范化域走 fmt）。"""
    ns = NEW_DOMAINS[domain]["ns"]
    method, kwargs = EXPLICIT_CALL_CASES[domain]
    getattr(getattr(cli, FRIENDLY_OF.get(ns, ns)), method)(**kwargs)
    xs = last_xs(cli)
    assert xs and xs[-1].startswith("return"), xs
    assert f"{ns}." in xs[-1], xs
    if ns in PRELOADED_NS:
        assert not any("xs.require" in ln for ln in xs), xs
    else:
        require_dir = NEW_DOMAINS[domain].get("dir", ns)
        assert any(f'xs.require("sys/{require_dir}/init.xs")' in ln for ln in xs), xs


@pytest.mark.parametrize("domain", sorted(NORMALIZE_DOMAINS))
def test_low_level_call_normalizes(cli, domain):
    """底层 call：声明 normalize_with 的函数生成 `return fmt(__r)` 脚本形态。"""
    ns = NEW_DOMAINS[domain]["ns"]
    normalized = [n for n in domain_fns(domain) if CAT.function(n).get("normalize_with")]
    assert normalized, domain
    name = sorted(normalized)[0]
    params = CAT.inventory_params(name)
    kw: dict[str, Any] = {}
    for p in params:
        if p.get("required"):
            kw[p["name"]] = "600519" if p["name"] in ("sym", "stk") else 1
    cli.call(name, **kw)
    xs = last_xs(cli)
    target = CAT.function(name)["normalize_with"]
    assert any(ln.startswith("__r :=") for ln in xs), xs
    assert xs[-1].startswith(f"return {target}("), xs
