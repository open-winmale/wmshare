"""P0-B：MCP 网关策略、schema 可达性、数据溯源信封回归测试。"""
from __future__ import annotations

import ast
import asyncio
import re
from itertools import chain
from pathlib import Path
from typing import get_args

import pytest

pytest.importorskip("mcp")

from wmshare.api import COMPOSITE_METHODS, FRIENDLY_INDEX  # noqa: E402
from wmshare.errors import LimitError  # noqa: E402
from wmshare.mcp import apis, core, tools  # noqa: E402
from wmshare.mcp.constants import MARKET_ACTIONS, TOOL_NAMES  # noqa: E402
from wmshare.mcp.core import MCPRuntime  # noqa: E402
from wmshare.mcp.server import MarketAction, build_server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
_ALL_MARKET_ACTIONS = set(chain.from_iterable(MARKET_ACTIONS.values()))


# ---- B1：枚举可达性 ----

def test_market_action_literal_covers_every_registry_action():
    assert set(get_args(MarketAction)) == _ALL_MARKET_ACTIONS, (
        "MarketAction 与 MARKET_ACTIONS 漂移；补 Literal 只是修法之一，"
        "必须靠这条等量断言锁死")


@pytest.mark.parametrize("action", sorted(_ALL_MARKET_ACTIONS))
def test_every_registry_action_is_schema_reachable(action):
    from pydantic import TypeAdapter

    assert TypeAdapter(MarketAction).validate_python(action) == action


def test_tool_schema_enum_matches_registry():
    server = build_server(MCPRuntime(demo=True))

    async def schemas():
        listed = await server.list_tools()
        return {t.name: t.inputSchema for t in listed}

    facts = asyncio.run(schemas())
    assert set(facts["wmshare_market"]["properties"]["action"]["enum"]) == \
        _ALL_MARKET_ACTIONS


# ---- B2：LLM 直接读到的计数 ----

def test_no_stale_friendly_api_count_in_ai_surface():
    """正则锚定 route_count()，替代已失效的 stale 黑名单。"""
    total = apis.route_count()
    scanned = [
        REPO / "README.md", REPO / "docs/AI.md", REPO / "llms.txt",
        REPO / "llms-full.txt",
        REPO / "src/wmshare/skills/wmshare/SKILL.md",
        REPO / "src/wmshare/mcp/server.py",
    ]
    seen = 0
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(\d+) 个 (?:SDK )?friendly API", text):
            seen += 1
            assert int(m.group(1)) == total, (
                f"{path.relative_to(REPO)} 写了 {m.group(1)} 个 friendly API，"
                f"实际 {total}")
    assert seen >= 2, "扫描面失效：至少 README/AI.md 应出现该口径"


def test_search_kind_description_uses_runtime_count():
    server = build_server(MCPRuntime(demo=True))

    async def schemas():
        listed = await server.list_tools()
        return {t.name: t.inputSchema for t in listed}

    desc = asyncio.run(schemas())["wmshare_search"]["properties"]["kind"]["description"]
    assert f"{apis.route_count()} 个 SDK friendly API" in desc
    assert "127 个" not in desc


# ---- B3：副作用路由与 EC 预算 ----

@pytest.mark.parametrize("target", ["cbond.figures", "cbond.article"])
def test_filesystem_routes_rejected_by_gateway(target, tmp_path):
    out = tmp_path / "should_not_exist"
    with pytest.raises(apis.GatewayPolicyError, match="MCP 网关不开放"):
        apis.invoke_api(object(), target, {"out_dir": str(out)},
                        market="cn", raw=False, units="base")
    assert not out.exists(), "被拒的路由不允许产生任何文件"


def test_gateway_policy_error_has_prescriptive_fix():
    envelope = core.error(
        apis.GatewayPolicyError("cbond.figures 会向任意路径写文件"),
        MCPRuntime(demo=True),
    )
    assert envelope["error"]["code"] == "gateway_policy"
    assert any("本地 Python SDK" in line for line in envelope["error"]["fix"])


def test_denied_routes_do_not_shrink_registry():
    """只拒调用、不缩清单：SDK 层公开 API 与 OpenAPI paths 不变。"""
    composite_count = sum(len(methods) for methods in COMPOSITE_METHODS.values())
    assert apis.route_count() == len(FRIENDLY_INDEX) + composite_count
    assert {r.target for r in apis.api_routes()} >= {"cbond.figures", "cbond.article"}


@pytest.mark.parametrize("method", sorted(apis.DENIED_CLIENT_METHODS))
def test_low_level_client_methods_not_routable(method):
    with pytest.raises(ValueError, match="低层 Client 方法"):
        apis.find_route(method)


class _Bars:
    @staticmethod
    def bars(**kw):
        return [{"close": 1.0}]


class _FakeCli:
    kline = _Bars()

    def __init__(self, ec):
        self.last_ec_cost = ec


def test_ec_budget_blocks_overspend(monkeypatch):
    rt = MCPRuntime(demo=False, max_ec_per_call=5)
    monkeypatch.setattr(MCPRuntime, "client", lambda self, market=None: _FakeCli(999))
    with pytest.raises(LimitError, match="ec_budget|超过 MCP 单次上限"):
        tools.call(rt, "kline.bars", mode="api")


def test_ec_cost_is_exposed_in_envelope(monkeypatch):
    rt = MCPRuntime(demo=False)
    monkeypatch.setattr(MCPRuntime, "client", lambda self, market=None: _FakeCli(10))
    result = tools.call(rt, "kline.bars", mode="api")
    assert result["ok"] is True
    assert result["meta"]["ec_cost"] == 10


def test_mcp_max_ec_env_override(monkeypatch):
    monkeypatch.setenv("WMSHARE_MCP_MAX_EC", "1234")
    assert MCPRuntime().max_ec_per_call == 1234
    monkeypatch.setenv("WMSHARE_MCP_MAX_EC", "not-a-number")
    assert MCPRuntime().max_ec_per_call == 200_000


# ---- B4：数据溯源信封 ----

_OLD_META_KEYS = ("market", "source", "units", "row_count", "rows_total",
                  "truncated", "next_action")
_NEW_META_KEYS = ("demo", "as_of", "retrieved_at", "data_freshness")


@pytest.mark.parametrize("demo", [True, False])
def test_success_envelope_carries_provenance(demo):
    rt = MCPRuntime(demo=demo)
    meta = core.success(rt, [1, 2])["meta"]
    for key in _OLD_META_KEYS + _NEW_META_KEYS:
        assert key in meta
    assert meta["demo"] is demo
    assert meta["data_freshness"] == ("snapshot" if demo else "live")
    if demo:
        assert meta["as_of"], "demo 信封必须带快照日期"
    else:
        assert meta["as_of"] is None


def test_error_envelope_carries_provenance_and_tolerates_missing_runtime():
    with_runtime = core.error(ValueError("x"), MCPRuntime(demo=True))
    without_runtime = core.error(ValueError("x"))
    for envelope in (with_runtime, without_runtime):
        for key in _NEW_META_KEYS:
            assert key in envelope["meta"]
    assert with_runtime["meta"]["data_freshness"] == "snapshot"
    assert without_runtime["meta"]["data_freshness"] == "unknown"


def test_status_tool_envelope_carries_provenance():
    envelope = tools.status(MCPRuntime(demo=True))
    assert envelope["ok"] is True
    for key in _NEW_META_KEYS:
        assert key in envelope["meta"]


# ---- S8：公开面手写计数锚定运行时 ----

_SURFACE_FILES = (
    "README.md",
    "docs/AI.md",
    "docs/README.md",
    "docs/GUIDE.md",
    "docs/API.md",
    "llms.txt",
    "llms-full.txt",
    "src/wmshare/skills/wmshare/SKILL.md",
    "src/wmshare/mcp/server.py",
)


def _count_facts() -> dict[str, int]:
    """计数真值只从运行时对象取，不在测试里重复写死。"""
    import wmshare

    stats = wmshare.load().stats()
    return {
        "core": len(FRIENDLY_INDEX),
        "composite": sum(len(methods) for methods in COMPOSITE_METHODS.values()),
        "functions": stats["functions"],
        "metrics": stats["metric_catalog_total"],
        "tools": len(TOOL_NAMES),
        "domains": stats["domains"],
        "friendly": apis.route_count(),
    }


# (口径, 正则, 至少命中处数)：命中下限用来防止扫描面被悄悄改没。
# 逐行扫描而非全文扫描，避免跨行的历史口径（如 CONTRIBUTING.md 的「44 个 / 核心接口」）误命中。
_COUNT_PATTERNS = (
    ("core", r"([\d,]+)\s*个\s*(?:SDK\s*)?核心接口", 3),
    ("composite", r"([\d,]+)\s*个\s*组合接口", 2),
    ("functions", r"([\d,]+)\s*个\s*底层函数", 2),
    ("metrics", r"([\d,]+)\s*个\s*指标(?:码|代码)", 3),
    ("tools", r"([\d,]+)\s*个\s*task\s*tools", 2),
    ("domains", r"([\d,]+)\s*个\s*数据域", 2),
    ("friendly", r"([\d,]+)\s*个\s*(?:SDK\s*)?friendly API", 2),
)


@pytest.mark.parametrize("kind,pattern,min_hits", _COUNT_PATTERNS)
def test_handwritten_counts_match_runtime(kind, pattern, min_hits):
    """README / AI 面 / llms / SKILL.md 里的手写计数必须与运行时真值一致。"""
    expected = _count_facts()[kind]
    hits = 0
    for rel in _SURFACE_FILES:
        path = REPO / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(pattern, line):
                value = int(match.group(1).replace(",", ""))
                hits += 1
                assert value == expected, (
                    f"{rel}:{lineno} 写了 {value} 个 {kind}，运行时真值 {expected}；"
                    "改了目录或接口请同步文档或改生成器")
    assert hits >= min_hits, (
        f"{kind} 扫描面失效：只命中 {hits} 处（需 ≥{min_hits}）")


def _attr_chain(node):
    if isinstance(node, ast.Attribute):
        parent = _attr_chain(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def test_skill_frontmatter_and_examples_are_real():
    """SKILL.md 的 frontmatter 约束与 cli.* 示例不能是编造的。"""
    text = (REPO / "src/wmshare/skills/wmshare/SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md 缺 frontmatter"
    front = text.split("---", 2)[1]
    assert re.search(r"^name:\s*\S+", front, re.M)
    description = re.search(r"^description:\s*(.+)$", front, re.M)
    assert description and len(description.group(1)) > 40
    assert "禁止臆造" in description.group(1), "防幻觉约束不能从 description 消失"

    blocks = [block for lang, block in
              re.findall(r"```(\w*)\n(.*?)```", text, re.S) if lang == "python"]
    assert len(blocks) >= 2
    calls = []
    for block in blocks:
        for node in ast.walk(ast.parse(block)):
            if not isinstance(node, ast.Call):
                continue
            chain_name = _attr_chain(node.func)
            if chain_name and chain_name.startswith("cli."):
                calls.append(chain_name[4:])
    assert len(calls) >= 5, f"SKILL.md 的 cli.* 示例过少：{len(calls)}"
    routes = {route.target for route in apis.api_routes()}
    unknown = sorted({name for name in calls if name not in routes})
    assert not unknown, f"SKILL.md 示例引用了不存在的接口：{unknown}"
