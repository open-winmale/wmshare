"""全接口合同测试：44 个核心接口 + 155 个底层函数都必须能按目录构造出合法调用。

这是覆盖面最广的一层——不校验业务数值（那由 live 测试负责），而是保证：
参数名/必填性/类型/默认值/规范化/命名空间 require 在全部接口上自洽。
"""
import inspect

import pytest

from wmshare.api import FRIENDLY_INDEX, FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
from wmshare.catalog import load

CAT = load()
CORE_IDS = [f"{ns}.{m}" for _, ns, m, _, _ in FRIENDLY_INDEX]
ALL_FNS = sorted(n for names in CAT.functions_by_domain().values() for n in names)

# 语义敏感参数的合法样例值（其余按类型生成）
SAMPLES = {
    "symbol": "600519", "sym": "600519", "stk": "600519", "syms": ["600519"],
    "code": "$PE_TTM_LAST", "codes": ["$PE_TTM_LAST", "$ROE_TTM_LAST"],
    "begin": "2026-01-01", "end": "2026-03-31",
    "from_date": "2026-01-01", "to_date": "2026-03-31",
    "domain": "fin.income_statement", "type_key": "annual", "kind": "annual",
    "idx": None, "key": "index.hs300", "keys": ["index.hs300"],
    "rows": [], "props": ["close"], "sas": "2024-Q4", "asof": "2026-06-30",
    "category": "回购", "window": "3y", "adj": "qfq", "scope": "合并",
    "metric": "pe", "where": "$ROE_TTM_LAST > 0.15",
    "opts": {"scope": "合并", "n": 2}, "fields": ["percent"],
}
_BY_TYPE = {"string": "x", "int": 1, "float": 1.0, "bool": True, "array": [], "object": {}}


def sample(name: str, typ: str):
    if name in SAMPLES:
        return SAMPLES[name]
    return _BY_TYPE.get(typ, "x")


class FakeSession:
    def __init__(self):
        self.calls = []
        self.eval_result = {"ok": True}

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
                lines = (json or {}).get("xs_lines") or []
                if any("bonus.query_list" in ln for ln in lines) and \
                        any('"rows"' in ln for ln in lines):
                    return {"success": True,
                            "data": {"result": {"rows": [], "dps": 0.0, "total": 0.0}}}
                # 列表形态：友好层 last() 会对规范化序列取首行
                return {"success": True, "data": {"result": [{"ok": True}]}}
        return R()


@pytest.fixture()
def cli():
    from wmshare.client import Client
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=CAT, session=FakeSession())


def last_xs(cli) -> list[str]:
    return [x for x in cli.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


@pytest.mark.parametrize("core_id", CORE_IDS)
def test_core_interface_dispatches(cli, core_id):
    """44 个核心接口：按签名必填参数调用，必须生成合法取数脚本。"""
    ns, method = core_id.split(".", 1)
    cls = FRIENDLY_NAMESPACES[ns]
    sig = inspect.signature(getattr(cls, method))
    kwargs = {}
    for name, p in sig.parameters.items():
        if name == "self" or name.startswith("_") or p.default is not inspect.Parameter.empty:
            continue
        ann = p.annotation if isinstance(p.annotation, str) else "any"
        kwargs[name] = sample(name, {"str": "string", "int": "int", "float": "float",
                                     "bool": "bool", "list[str]": "array",
                                     "list": "array", "dict": "object"}.get(ann, "any"))
    getattr(getattr(cli, ns), method)(**kwargs)
    xs = last_xs(cli)
    assert xs and xs[-1].startswith("return"), f"{core_id} 未生成 return 行：{xs}"


@pytest.mark.parametrize("full_name", ALL_FNS)
def test_low_level_function_accepts_all_catalog_params(cli, full_name):
    """155 个底层函数：把目录声明的每个参数都显式传入，必须全部被接受。"""
    fn = CAT.function(full_name)
    params = fn.get("params") or CAT.inventory_params(full_name)
    kwargs = {p["name"]: sample(p["name"], p.get("type", "any")) for p in params}
    if "limit" in kwargs and isinstance(kwargs["limit"], int):
        kwargs["limit"] = min(kwargs["limit"], 100)
    cli.call(full_name, **kwargs)
    xs = last_xs(cli)
    assert xs and xs[-1].startswith("return")


@pytest.mark.parametrize("full_name", ALL_FNS)
def test_low_level_function_required_only(cli, full_name):
    """只传必填参数也必须可调用（可选参数走目录默认值/省略）。"""
    fn = CAT.function(full_name)
    params = fn.get("params") or CAT.inventory_params(full_name)
    kwargs = {p["name"]: sample(p["name"], p.get("type", "any"))
              for p in params if p.get("required") and "default" not in p}
    cli.call(full_name, **kwargs)
    assert last_xs(cli)[-1].startswith("return")


def test_generated_facade_signatures_match_catalog():
    """类型化门面的每个方法签名 == 目录参数合同（防生成层与目录漂移）。"""
    checked = 0
    for full_name in ALL_FNS:
        ns, short = full_name.split(".", 1)
        cls = GENERATED_NAMESPACES[ns]
        assert hasattr(cls, short), f"生成层缺方法 {full_name}"
        sig_params = [p for p in inspect.signature(getattr(cls, short)).parameters
                      if p not in ("self", "_raw", "_df")]
        fn = CAT.function(full_name)
        catalog_params = [p["name"] for p in (fn.get("params") or CAT.inventory_params(full_name))]
        assert sig_params == catalog_params, f"{full_name} 签名 {sig_params} != 目录 {catalog_params}"
        checked += 1
    assert checked == len(ALL_FNS)


def test_every_core_interface_has_openapi_operation():
    """44 个核心接口在 OpenAPI spec 中都必须有对应操作（文档-代码一致性）。"""
    import json
    from pathlib import Path
    spec = json.loads((Path(__file__).resolve().parents[1] / "docs" / "openapi.json")
                      .read_text(encoding="utf-8"))
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    for _, ns, method, _, _ in FRIENDLY_INDEX:
        assert f"{ns}_{method}" in ops, f"OpenAPI 缺 {ns}_{method}"
