"""Friendly API gateway, coverage, schema, and MCP full-path contracts."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from itertools import chain
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from wmshare.api import FRIENDLY_NAMESPACES
from wmshare.client import BatchResult
from wmshare.mcp.apis import (
    GatewayPolicyError,
    MCP_DENIED_ROUTES,
    api_routes,
    batchable_catalog_functions,
    find_route,
    invoke_api,
    route_contract,
    route_count,
)
from wmshare.mcp.constants import (
    CORPORATE_ACTIONS,
    DIVIDEND_ACTIONS,
    ESTIMATE_ACTIONS,
    INTL_ACTIONS,
    MARKET_ACTIONS,
    MARKET_DOMAINS,
    NOTICE_ACTIONS,
    SEGMENT_ACTIONS,
    STATEMENT_ACTIONS,
    TOOL_NAMES,
)
from wmshare.mcp.core import MCPRuntime
from wmshare.mcp.server import build_server
from wmshare.mcp import tools


class DomainSpy:
    def __init__(self, name: str, calls: list[tuple[str, str, dict[str, Any]]]) -> None:
        self.name = name
        self.calls = calls

    def __getattr__(self, method: str):
        def call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((self.name, method, kwargs))
            return {"target": f"{self.name}.{method}", "args": kwargs}
        return call


class GatewayFakeClient:
    market = "cn"

    def __init__(self) -> None:
        self.calls = list[tuple[str, str, dict[str, Any]]]()

    def __getattr__(self, domain: str) -> DomainSpy:
        if domain.startswith("_"):
            raise AttributeError(domain)
        return DomainSpy(domain, self.calls)


class CatalogFakeClient:
    market = "cn"

    def call(self, function: str, **kwargs: Any) -> dict[str, Any]:
        return {"function": function, "args": kwargs}


@pytest.fixture(scope="module")
def routes() -> tuple[Any, ...]:
    return api_routes()


@pytest.fixture()
def runtime() -> MCPRuntime:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": GatewayFakeClient()}
    return rt


def test_registry_covers_every_friendly_api(routes: tuple[Any, ...]) -> None:
    expected = {
        f"{domain}.{method}"
        for domain, cls in FRIENDLY_NAMESPACES.items()
        for method, fn in inspect.getmembers(cls, inspect.isfunction)
        if not method.startswith("_")
        and inspect.getattr_static(cls, method) is not None
    }
    actual = {route.target for route in routes}
    # 与注册表逐条对齐即可；不要写死数字——每加一个公开方法就要改测试，
    # 数字一致本身不产生信息（expected 已由反射算出）。
    assert route_count() == len(expected)
    assert actual == expected
    assert len(actual) == len(expected)
    assert len(expected) >= 130
    for route in routes:
        assert route.description
        assert route.signature
        assert route.example
        assert route.recommended_tool.startswith("wmshare_")
        assert route.recommended_tool in TOOL_NAMES


def test_search_and_contract_friendly_api(runtime: Any) -> None:
    found = tools.search(runtime, "segments", kind="api", limit=20)
    assert found["ok"] is True
    assert any(row["target"] == "segments.snapshot" for row in found["data"])
    contract = tools.contract(runtime, "segments.snapshot", kind="api")
    assert contract["ok"] is True
    assert contract["data"]["target"] == "segments.snapshot"
    assert "symbol" in contract["data"]["allowed_arguments"]
    assert contract["data"]["recommended_tool"] == "wmshare_segments"


def test_status_reports_capability_coverage(runtime: Any) -> None:
    status = tools.status(runtime)
    caps = status["data"]["capabilities"]
    assert caps["friendly_apis"] == route_count()
    assert caps["first_class_tools"] == 20
    assert caps["batchable_catalog_functions"] > 100
    assert "pandas/_df" in caps["excluded_from_mcp"][0]


def test_catalog_contract_surface_is_complete() -> None:
    import wmshare

    cat = wmshare.load()
    names = {
        function["name"]
        for domain in cat.domains.values()
        for function in domain.get("functions", [])
    }
    assert len(names) == cat.stats()["functions"] == 269
    for name in names:
        assert cat.function(name)
    assert len(batchable_catalog_functions()) >= 100


def test_generic_api_gateway_invokes_and_guards(runtime: Any) -> None:
    result = tools.call(
        runtime, "dividend.screen_quality", {"symbol": "600519", "min_yield": 0.03},
        mode="api",
    )
    assert result["ok"] is True
    assert result["data"]["target"] == "dividend.screen_quality"
    assert result["meta"]["mode"] == "api"
    assert result["meta"]["units"] == "base"

    with pytest.raises(ValueError, match="未知参数"):
        tools.call(runtime, "dividend.screen_quality", {"bad": 1}, mode="api")
    with pytest.raises(ValueError, match="私有选项"):
        tools.call(runtime, "dividend.screen_quality", {"_df": True}, mode="api")
    with pytest.raises(ValueError, match="不支持 raw"):
        tools.call(runtime, "info.profile", {"symbol": "600519"}, mode="api", raw=True)


def test_generic_catalog_gateway_supports_raw_units() -> None:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": CatalogFakeClient()}
    result = tools.call(rt, "segments.snapshot", {"sym": "600519"}, raw=True, units="native")
    assert result["ok"] is True
    assert result["data"]["args"]["_raw"] is True
    assert result["data"]["args"]["_units"] == "native"


class BatchFakeClient:
    market = "cn"

    def batch_iter(self, function: str, symbols: list[str], **kwargs: Any):
        return iter([BatchResult(
            results={symbol: {"function": function} for symbol in symbols},
            requests=1, requested=len(symbols),
        )])


def test_batch_params_are_forwarded() -> None:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": BatchFakeClient()}
    runtime = rt
    result = tools.batch(
        runtime, "kline.snapshot", ["600519"], params={"adj": "qfq"},
        raw=False, units="base",
    )
    assert result["ok"] is True
    with pytest.raises(ValueError, match="私有选项"):
        tools.batch(runtime, "kline.snapshot", ["600519"], params={"_df": True})


def test_every_friendly_route_is_invokable() -> None:
    rt = MCPRuntime(market="cn", demo=False)
    client = GatewayFakeClient()
    for route in api_routes():
        # 有文件系统副作用的路由仍在 registry（SDK 层可用），但 MCP 网关
        # 必须拒绝；此处验证「拒绝」本身，其余路由继续验证可调用性。
        if (route.domain, route.method) in MCP_DENIED_ROUTES:
            with pytest.raises(GatewayPolicyError, match="MCP 网关不开放"):
                invoke_api(client, route.target, {}, market="cn",
                           raw=False, units="base")
            continue
        kwargs: dict[str, Any] = {}
        params = route.parameters
        # route.parameters includes optional params; only supply required values.
        fn = getattr(FRIENDLY_NAMESPACES[route.domain], route.method)
        for name, param in inspect.signature(fn).parameters.items():
            if name == "self" or name.startswith("_") or param.default is not inspect.Parameter.empty:
                continue
            if name in {"symbol", "sym", "stk", "code", "category", "industry", "key", "sampling", "date", "sort_by"}:
                kwargs[name] = "600519" if name in {"symbol", "sym", "stk", "code"} else "test"
            elif name in {"symbols", "codes"}:
                kwargs[name] = ["600519"]
            elif param.annotation in {int, "int"}:
                kwargs[name] = 1
            elif param.annotation in {float, "float"}:
                kwargs[name] = 1.0
            elif param.annotation in {bool, "bool"}:
                kwargs[name] = True
            else:
                kwargs[name] = "600519"
        market = "hk" if route.domain == "intl" else "cn"
        value = invoke_api(client, route.target, kwargs, market=market, raw=False, units="base")
        assert value["target"] == route.target


def test_intl_requires_non_cn_market() -> None:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": GatewayFakeClient(), "hk": GatewayFakeClient()}
    with pytest.raises(ValueError, match="hk/us"):
        tools.intl(rt, "query_ccass", "00700")
    result = tools.intl(rt, "query_ccass", "00700", market="hk", limit=1)
    assert result["data"]["args"]["symbol"] == "00700"


def test_mcp_registry_schema_and_resources() -> None:
    server = build_server(MCPRuntime(market="cn", demo=True))
    async def inspect_server() -> tuple[list[str], dict[str, Any]]:
        listed = await server.list_tools()
        schema = {tool.name: tool.inputSchema for tool in listed}
        coverage = await server._resource_manager._resources["wmshare://coverage"].read()
        setup = await server._resource_manager._resources["wmshare://setup"].read()
        limits = await server._resource_manager._resources["wmshare://limits"].read()
        return [tool.name for tool in listed], {
            "schema": schema,
            "coverage": json.loads(coverage),
            "setup": setup,
            "limits": limits,
        }
    names, facts = asyncio.run(inspect_server())
    assert set(names) == set(TOOL_NAMES) and len(names) == 20
    coverage = facts["coverage"]
    assert coverage["friendly_apis"] == route_count()
    assert coverage["first_class_tools"] == 20
    assert coverage["batchable_catalog_functions"] >= 100
    assert "pandas DataFrame / _df=True" in coverage["excluded_from_mcp"]
    assert "--client-secret-stdin" in facts["setup"]
    assert "--client-secret " not in facts["setup"]
    for phrase in ("partial=true", "resume_start", "resume_symbols", "retry_after_seconds"):
        assert phrase in facts["limits"]
    for tool_name, schema in facts["schema"].items():
        assert tool_name.startswith("wmshare_")
        assert schema.get("type") == "object"
        assert schema.get("properties")
    output = facts["schema"]["wmshare_status"]["properties"]["output"]
    assert "enum" in output or "allOf" in output
    batch = facts["schema"]["wmshare_batch"]["properties"]
    assert "params" in batch
    assert "raw" in batch
    assert "units" in batch
    call = facts["schema"]["wmshare_call"]["properties"]
    assert "target" in call
    assert "mode" in call


def test_function_and_api_resources_emit_json() -> None:
    server = build_server(MCPRuntime(market="cn", demo=True))
    async def read_resources() -> tuple[dict[str, Any], dict[str, Any]]:
        fn_template = server._resource_manager._templates["wmshare://catalog/function/{name}"]
        resource = await fn_template.create_resource(
            "wmshare://catalog/function/segments.snapshot", {"name": "segments.snapshot"}
        )
        api_template = server._resource_manager._templates["wmshare://api/{target}"]
        api_resource = await api_template.create_resource(
            "wmshare://api/segments.snapshot", {"target": "segments.snapshot"}
        )
        return json.loads(await resource.read()), json.loads(await api_resource.read())
    fn_data, api_data = asyncio.run(read_resources())
    assert fn_data["name"] == "segments.snapshot"
    assert api_data["target"] == "segments.snapshot"


def _domain_runtime() -> MCPRuntime:
    rt = MCPRuntime(market="cn", demo=False)
    rt._clients = {"cn": GatewayFakeClient(), "hk": GatewayFakeClient()}
    return rt


@pytest.mark.parametrize("tool_name,args", [
    ("statement", {"action": "income", "symbol": "600519"}),
    ("segments", {"action": "snapshot", "symbol": "600519"}),
    ("dividend", {"action": "window_stats", "symbol": "600519"}),
    ("estimates", {"action": "forecast", "symbol": "600519"}),
    ("corporate", {"action": "query_holder10", "symbol": "600519"}),
    ("market", {"domain": "moneyflow", "action": "last", "symbol": "600519"}),
    ("intl", {"action": "query_ccass", "symbol": "00700", "market": "hk"}),
    ("notice", {"action": "list", "symbol": "600519"}),
])
def test_eight_domain_tools_success_envelope(tool_name: str, args: dict[str, Any]) -> None:
    fn = getattr(tools, tool_name)
    result = fn(_domain_runtime(), **args)
    assert result["ok"] is True
    assert result["data"]["target"]
    for key in ("market", "units", "row_count", "rows_total", "truncated", "next_action"):
        assert key in result["meta"]


@pytest.mark.parametrize("tool_name,args", [
    ("statement", {"action": "bad", "symbol": "600519"}),
    ("segments", {"action": "snapshot"}),
    ("dividend", {"action": "history", "symbol": "600519", "begin": "2026-01-01"}),
    ("estimates", {"action": "bad", "symbol": "600519"}),
    ("corporate", {"action": "query_exec_change_at", "symbol": "600519"}),
    ("market", {"domain": "moneyflow", "action": "bad", "symbol": "600519"}),
    ("intl", {"action": "query_ccass", "symbol": "00700", "market": "cn"}),
    ("notice", {"action": "by_category"}),
])
def test_eight_domain_tools_condition_errors(tool_name: str, args: dict[str, Any]) -> None:
    fn = getattr(tools, tool_name)
    with pytest.raises(ValueError):
        fn(_domain_runtime(), **args)


def test_pypi_registry_metadata_contract() -> None:
    # tomllib 是 3.11+ 标准库；项目声明 requires-python>=3.10 且 CI 跑 3.10，
    # 必须有 tomli 回退（见 pyproject.toml dev extra），否则 3.10 job 必红。
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
        import tomli as tomllib  # type: ignore[no-redef]

    repo = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repo / "pyproject.toml").read_text())
    server = json.loads((repo / "server.json").read_text())
    # 2026-11 起 pyproject 用 dynamic version（源 = wmshare.__version__），
    # 此时以包内 __version__ 为基准；两种形态都要能取到版本。
    version = project["project"].get("version")
    if version is None:
        assert "version" in project["project"].get("dynamic", []), \
            "pyproject 既无 version 也未声明 dynamic version"
        import wmshare
        version = wmshare.__version__
    readme = (repo / "README.md").read_text()
    # 四处版本互校：pyproject / server.json×2 / 包的 __version__。
    # 曾只校验前三处，__init__.py 漂移无人发现。
    package_init = (repo / "src/wmshare/__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', package_init, re.M)
    assert m, "src/wmshare/__init__.py 缺少 __version__ 字面量"
    assert m.group(1) == version, "包 __version__ 与 pyproject 版本漂移"
    assert server["name"] == "io.github.open-winmale/wmshare"
    assert server["version"] == version
    package = server["packages"][0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "wmshare"
    assert package["version"] == version
    assert package["transport"]["type"] == "stdio"
    assert package["runtimeHint"] == "wmshare-mcp"
    assert "mcp-name: io.github.open-winmale/wmshare" in readme


def test_docs_mcp_numbers_match_routes() -> None:
    """README/AI.md 的 MCP 数字必须锚定代码：127 曾是 1.12.0 旧总数（116+11），
    漂移两个版本才被发现——兜底面以 route_count() 为唯一事实源。"""
    repo = Path(__file__).resolve().parents[1]
    total = route_count()
    readme = (repo / "README.md").read_text(encoding="utf-8")
    ai = (repo / "docs/AI.md").read_text(encoding="utf-8")
    phrase = f"全部 {total} 个 friendly API"
    assert phrase in readme, "README 的 MCP 兜底面数字与 route_count() 漂移"
    assert phrase in ai, "docs/AI.md 的 MCP 兜底面数字与 route_count() 漂移"
    assert f"{len(TOOL_NAMES)} 个 task tools" in readme
    for stale in ("127 个 friendly", "其余 127 个", "116 个核心接口"):
        assert stale not in readme and stale not in ai, f"过时口径残留：{stale}"


def test_tool_schemas_have_enums_and_descriptions() -> None:
    server = build_server(MCPRuntime(market="cn", demo=True))
    async def schemas() -> dict[str, dict[str, Any]]:
        listed = await server.list_tools()
        return {tool.name: tool.inputSchema for tool in listed}
    facts = asyncio.run(schemas())
    assert set(facts) == set(TOOL_NAMES)
    for name, schema in facts.items():
        for param, definition in schema["properties"].items():
            if definition.get("type") in {"string", "integer", "number", "boolean"}:
                assert definition.get("description"), (name, param)
    search = facts["wmshare_search"]["properties"]["kind"]
    assert {"all", "function", "metric", "symbol", "api"} <= set(search["enum"])
    call = facts["wmshare_call"]["properties"]
    assert set(call["mode"]["enum"]) == {"catalog", "api"}
    assert set(call["units"]["enum"]) == {"base", "native"}
    assert set(facts["wmshare_history"]["properties"]["adj"]["anyOf"][0]["enum"]) == {"qfq", "hfq"}


def test_domain_action_enums_are_machine_readable() -> None:
    server = build_server(MCPRuntime(market="cn", demo=True))
    async def schemas() -> dict[str, dict[str, Any]]:
        listed = await server.list_tools()
        return {tool.name: tool.inputSchema for tool in listed}
    facts = asyncio.run(schemas())
    expected = {
        "wmshare_statement": set(STATEMENT_ACTIONS),
        "wmshare_segments": set(SEGMENT_ACTIONS),
        "wmshare_dividend": set(DIVIDEND_ACTIONS),
        "wmshare_estimates": set(ESTIMATE_ACTIONS),
        "wmshare_corporate": set(CORPORATE_ACTIONS),
        "wmshare_intl": set(INTL_ACTIONS),
        "wmshare_notice": set(NOTICE_ACTIONS),
    }
    for name, values in expected.items():
        assert set(facts[name]["properties"]["action"]["enum"]) == values
    market_domain = facts["wmshare_market"]["properties"]["domain"]
    market_action = facts["wmshare_market"]["properties"]["action"]
    assert set(market_domain["enum"]) == set(MARKET_DOMAINS)
    # 等量而非「包含」断言：曾漏 trend / universe_keys 两条已实现路由，
    # 弱断言让 schema 层静默拒绝，代码成了死路径。
    assert set(market_action["enum"]) == set(
        chain.from_iterable(MARKET_ACTIONS.values()))
    for name, schema in facts.items():
        for definition in schema["properties"].values():
            assert definition.get("description"), (name, definition)
