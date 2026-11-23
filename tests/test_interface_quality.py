"""接口质量契约：规范性 / 易用性 / 可理解性（静态审计 + ratchet）。

评估口径（2026-11-18 基线，评分 ≈71/100，缺口随测试收紧逐步清零）：
- 规范性：命名契约、返回说明非空、字段级返回表、错误码文档双向一致；
- 易用性：示例可绑定、文档链接不悬空、示例数各入口一致、MCP 示例质量；
- 可理解性：summary 非空、参数说明无 `—`、字段表数量不下滑、`:param` 债务 ratchet。

原则：**测试渲染结果（docs/API.md），不重复生成器内部逻辑**；允许存量债务，
但新增缺口必须失败（ratchet）。
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from _introspect import FALLBACK_RETURNS, RETURNS_OVERRIDES, method_params  # noqa: E402
from wmshare.api import COMPOSITE_METHODS, FRIENDLY_INDEX, FRIENDLY_NAMESPACES  # noqa: E402
from wmshare.errors import QUOTA_CODES  # noqa: E402

API_MD = REPO / "docs" / "API.md"
PARAM_EMPTY_RE = re.compile(
    r"^\| `[a-z_]+` \| [a-zA-Z?]+ \| (?:是|否) \| .* \| — \|$")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)")

# 方法级 `:param` 债务基线（2026-11-18：50 个方法零方法级 :param，靠类级/目录兜底）。
# 只许减少：新方法必须带方法级 :param；名单里的方法补一条就从基线删一条。
PARAM_DOC_DEBT = frozenset({
    ("kline", "last"), ("kline", "live"), ("kline", "min1"), ("kline", "is_etf"),
    ("moneyflow", "last"), ("moneyflow", "live"),
    ("screener", "screen_limit_up"), ("screener", "screen_limit_down"),
    ("screener", "screen_above_ma20"), ("screener", "screen_ma60_up"),
    ("screener", "screen_breakout_ma20"),
    ("margin", "latest"), ("statements", "audit"),
    ("segments", "products"), ("segments", "business"), ("segments", "region"),
    ("segments", "income"), ("segments", "snapshot"), ("segments", "coverage"),
    ("segments", "periods"),
    ("notice", "has_buyback"), ("notice", "has_reduction"),
    ("forecast", "yjyg"), ("forecast", "yjyg_latest"), ("forecast", "yjkb"),
    ("forecast", "yjkb_latest"), ("forecast", "disclosure_history"),
    ("forecast", "next_disclosure"),
    ("workout", "query"),
    ("dividend", "last"), ("dividend", "dps"), ("dividend", "yield_ttm"),
    ("dividend", "payout_ttm"),
    ("info", "profile"),
    ("equity", "query_holder10"), ("equity", "query_holdernum"),
    ("equity", "query_buyback_detail"), ("equity", "query_executives"),
    ("equity", "query_exec_change"), ("equity", "query_capital_change"),
    ("intl", "issue_info"),
    ("macro", "asof"), ("macro", "spots"), ("macro", "sampling_of"),
    ("macro", "nev_monthly"), ("macro", "nev_weekly"), ("macro", "avc_monthly"),
    ("macro", "chinaiol_monthly"), ("macro", "cpca_top"), ("macro", "phone_share"),
})
# 字段级返回表基线：2026-11-18 为 74 个块；只许增长（缺失 shape 的接口补声明/兜底）。
FIELD_TABLE_MIN = 74


def _core_blocks() -> list[tuple[str, str, str]]:
    """解析 API.md 的核心接口小节（#### `cli.ns.method`）。"""
    text = API_MD.read_text(encoding="utf-8")
    blocks = []
    for part in re.split(r"\n#### ", "\n" + text)[1:]:
        head = part.splitlines()[0]
        m = re.match(r"`cli\.([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)`", head)  # ns 允许下划线（pdf_doc）
        if m:
            blocks.append((m.group(1), m.group(2), part))
    return blocks


def _example_code(block: str) -> str:
    m = re.search(r"\*\*示例\*\*\s*\n+```python\n(.*?)```", block, re.S)
    return m.group(1).strip() if m else ""


def _bind_example(ns: str, method: str, code: str) -> None:
    """示例必须能对真实签名绑定（AST，不 eval、不联网）。"""
    func = getattr(FRIENDLY_NAMESPACES[ns], method)
    sig = inspect.signature(func)
    tree = ast.parse(code)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls, f"cli.{ns}.{method}: 示例没有函数调用"
    call = calls[0]
    args = []
    for a in call.args:
        try:
            args.append(ast.literal_eval(a))
        except (ValueError, SyntaxError):
            args.append(None)  # 非字面量占位不影响绑定
    kwargs = {}
    for kw in call.keywords:
        try:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            kwargs[kw.arg] = None
    # 函数是未绑定的（self 在签名里）：用占位对象补 self 再绑定用户参数
    sig.bind(object(), *args, **kwargs)


def test_every_core_method_has_summary_and_bindable_example():
    blocks = _core_blocks()
    assert len(blocks) == len(FRIENDLY_INDEX), (
        f"API.md 核心小节数 {len(blocks)} != FRIENDLY_INDEX {len(FRIENDLY_INDEX)}")
    for ns, method, block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        assert len(lines) >= 2 and lines[1], f"cli.{ns}.{method}: 缺一句话说明"
        code = _example_code(block)
        assert code, f"cli.{ns}.{method}: 缺示例"
        assert "…" not in code, f"cli.{ns}.{method}: 示例含省略号占位"
        _bind_example(ns, method, code)


def test_no_empty_param_or_return_cells():
    text = API_MD.read_text(encoding="utf-8")
    empty_params = [ln for ln in text.splitlines() if PARAM_EMPTY_RE.match(ln)]
    assert not empty_params, f"参数说明为空的行：\n" + "\n".join(empty_params[:5])
    assert "**输出**：—" not in text, "存在返回说明为空的接口（补 FALLBACK_RETURNS/目录 returns）"


def test_field_table_ratchet():
    text = API_MD.read_text(encoding="utf-8")
    n = text.count("**输出字段**")
    assert n >= FIELD_TABLE_MIN, (
        f"字段级返回表 {n} < 基线 {FIELD_TABLE_MIN}：返回字段声明不得回退")


def test_fallback_tables_are_live():
    core = {(ns, m) for _, ns, m, _, _ in FRIENDLY_INDEX}
    composite = {(ns, m) for ns, names in COMPOSITE_METHODS.items() for m in names}
    known = core | composite
    for key, desc in FALLBACK_RETURNS.items():
        assert key in known, f"FALLBACK_RETURNS 残留失效条目：{key}"
        assert desc and desc != "—", f"FALLBACK_RETURNS[{key}] 为空"
    for key, desc in RETURNS_OVERRIDES.items():
        assert key in core, f"RETURNS_OVERRIDES 只用于核心接口：{key}"
        assert desc, f"RETURNS_OVERRIDES[{key}] 为空"


def test_symbol_naming_contract():
    """按标的查询的公开方法：参数名必须叫 `symbol` 且排第一；禁止暴露 sym/stk。"""
    code_ns_allowlist = {"indicator", "macro"}  # 指标码 / 宏观码参数名叫 code
    for _, ns, method, _cn, _u in FRIENDLY_INDEX:
        func = getattr(FRIENDLY_NAMESPACES[ns], method)
        names = list(inspect.signature(func).parameters)
        for bad in ("sym", "stk"):
            assert bad not in names, f"cli.{ns}.{method}: 参数名 {bad} 应统一为 symbol"
        if "symbol" in names:
            assert names[0] == "self" and names[1] == "symbol", (
                f"cli.{ns}.{method}: symbol 必须是首个参数")
        for p in names:
            if p == "code" and ns not in code_ns_allowlist:
                raise AssertionError(f"cli.{ns}.{method}: 参数 code 需登记 allowlist")


def test_error_codes_bidirectional_documented():
    """源码 `code="..."` 字面量 ↔ docs/ERRORS.md 双向一致（独立于生成器逻辑）。"""
    text = (REPO / "docs" / "ERRORS.md").read_text(encoding="utf-8")
    # 只取数据行（跳过表头 `| `code` | 含义 |`）：第二列不是「含义」
    documented = set(re.findall(r"^\| `([a-z][a-z0-9_]*)` \| (?!含义)", text, re.M))
    scanned: set[str] = set()
    for p in sorted((REPO / "src" / "wmshare").rglob("*.py")):
        scanned |= set(re.findall(r'code="([a-z][a-z0-9_]*)"',
                                  p.read_text(encoding="utf-8", errors="ignore")))
    missing = scanned - documented
    extra = documented - scanned - set(QUOTA_CODES)
    assert not missing, f"源码新增错误码未写入 docs/ERRORS.md：{sorted(missing)}"
    assert not extra, f"docs/ERRORS.md 登记了源码中不存在的码：{sorted(extra)}"


def test_relative_links_exist_and_example_count_consistent():
    """文档相对链接不悬空；各入口的示例数口径一致（曾漂移 17 vs 18）。"""
    n_examples = len(list((REPO / "examples").glob("*.py")))
    for name in ("README.md", "docs/README.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        m = re.search(r"(\d+) 个编号示例", text)
        assert m and int(m.group(1)) == n_examples, (
            f"{name}: 示例数与仓库不符（实际 {n_examples}）")
    targets = [(REPO / "README.md")] + sorted((REPO / "docs").glob("*.md"))
    # PROMOTION.md 已于 2026-11-19 迁出仓库（→ ../promo/）：推广执行手册属
    # 方案/流程类文档，CONTRIBUTING 明确不入库。此处不再需要 skip 名单。
    skip_names: set[str] = set()
    dead: list[str] = []
    for path in targets:
        if path.name in skip_names:
            continue
        for target in LINK_RE.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                dead.append(f"{path.name} -> {target}")
    assert not dead, f"悬空相对链接：\n" + "\n".join(dead[:10])


def test_mcp_route_examples_quality():
    """MCP 路由：description 不得是 fallback；示例不得含 <REQUIRED> 占位。"""
    pytest.importorskip("mcp")
    from wmshare.mcp.apis import api_routes

    routes = api_routes()
    fallback = [f"{r.domain}.{r.method}" for r in routes
                if r.description == "SDK friendly API"]
    assert not fallback, f"MCP description 退化为兜底文案：{fallback[:5]}"
    placeholder = [f"{r.domain}.{r.method}" for r in routes
                   if "<REQUIRED>" in (r.example or "")]
    # 2026-11-18 基线 30 条：示例里必填参数还是 <REQUIRED> 占位（不可执行）。
    # 只许减少：给对应方法补 example 值后从基线删除。
    baseline = {
        "calendar.days", "calendar.is_open", "calendar.next",
        "cbond.article", "cbond.call_hits", "cbond.figures", "cbond.kline_window",
        "equity.query_capital_change_at", "equity.query_exec_change_at",
        "futures.get", "futures.snapshot", "index.members", "index.trend",
        "index.valuation", "index.weights", "indicator.metrics",
        "kline.batch_live", "macro.avc_monthly", "macro.bond_curve",
        "macro.chinaiol_monthly", "macro.cpca_top", "macro.nev_monthly",
        "macro.nev_weekly", "macro.phone_share", "notice.by_category",
        "notice.find", "notice.on_date", "notice.read_text", "screener.query",
        "stocks.industry_members",
    }
    new = set(placeholder) - baseline
    assert not new, f"MCP 示例出现新的 <REQUIRED> 占位：{sorted(new)[:5]}"
    assert len(placeholder) <= len(baseline), (
        f"MCP 占位示例变多：{len(placeholder)} > 基线 {len(baseline)}")


def test_method_param_doc_debt_ratchet():
    """方法级 `:param` 债务只许减少（存量靠类级/目录兜底，新增方法必须自带）。"""
    current: set[tuple[str, str]] = set()
    for _, ns, method, _cn, _u in FRIENDLY_INDEX:
        cls = FRIENDLY_NAMESPACES[ns]
        params = method_params(cls, method)
        doc = inspect.getdoc(getattr(cls, method)) or ""
        if params and doc.count(":param") == 0:
            current.add((ns, method))
    new = current - set(PARAM_DOC_DEBT)
    assert not new, f"新增方法缺方法级 :param：{sorted(new)[:5]}"
    assert len(current) <= len(PARAM_DOC_DEBT), (
        f":param 债务变多：{len(current)} > 基线 {len(PARAM_DOC_DEBT)}")


def test_replay_signatures_cover_live_facade_params():
    """离线回放夹具与 live 门面签名一致：live 的每个形参夹具都必须能接收。

    缺口会让离线测试拿 TypeError（或更糟：参数被静默吞掉）而不是显式报错。
    未回放的能力可以报错，但不能「假装没有这个参数」——2026-11-18 实测曾漂移
    17 处（kline freq/_fields、screener 形参名 symbol vs sym、margin/indicator
    的 _fields/fut_symbol、volume_spike 的 min_ratio）。

    2026-11-19 收紧：此前「整方法缺失」会被静默跳过，于是整域未拍与单方法
    缺口全部漏检。现在缺失即失败——没有白名单，未拍摄的能力只在运行时以
    ``replay_unsupported`` 显式报错（签名本身必须存在）。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from replay_client import replay_client

    replay = replay_client()
    problems = []
    checked = 0
    for ns, cls in FRIENDLY_NAMESPACES.items():
        replay_ns = getattr(replay, ns, None)
        if replay_ns is None:
            problems.append(f"cli.{ns}: 回放夹具整个命名空间缺失")
            continue
        for method in dir(cls):
            if method.startswith("_"):
                continue
            live_fn = getattr(cls, method, None)
            if not callable(live_fn):
                continue
            replay_fn = getattr(replay_ns, method, None)
            if not callable(replay_fn):
                problems.append(f"cli.{ns}.{method}: 回放夹具侧不可调用")
                continue
            checked += 1
            live_params = list(inspect.signature(live_fn).parameters)[1:]  # 去 self
            replay_params = list(inspect.signature(replay_fn).parameters)
            missing = [p for p in live_params if p not in replay_params]
            if missing:
                problems.append(f"cli.{ns}.{method} 缺 {missing}"
                                f"（live={live_params} replay={replay_params}）")
    assert checked >= 58, f"只比对到 {checked} 对方法，扫描范围可能被改坏"
    assert not problems, "回放夹具与 live 门面签名漂移：\n" + "\n".join(problems)


def test_replay_unbacked_calls_raise_replay_unsupported():
    """回放夹具每个可调用项：要么正常返回，要么 replay_unsupported，绝不 AttributeError。

    「同签名」的可验证含义在这里：属性一定存在且可调用。未回放的能力用
    ``UsageError(code="replay_unsupported")`` 明确表示「快照没拍」，与
    「SDK 没有这个能力」（AttributeError）区分开。

    固定用例取 README 正文推荐过的 ``cli.notice.has_buyback(sym, "6m")``——
    2026-11-19 前它在回放侧直接 AttributeError。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import wmshare
    from replay_client import replay_client
    from wmshare.errors import UsageError

    replay = replay_client()
    # 固定用例：README「我想做 X → 用哪一行」表格里推荐过的调用
    with pytest.raises(UsageError) as exc:
        replay.notice.has_buyback("600519", "6m")
    assert exc.value.code == "replay_unsupported"

    # 全命名空间扫描：每个方法都要么可调用成功、要么显式报错
    checked = 0
    for ns in wmshare.api.FRIENDLY_NAMESPACES:
        replay_ns = getattr(replay, ns, None)
        assert replay_ns is not None, f"cli.{ns}: 回放夹具命名空间缺失"
        for method in dir(wmshare.api.FRIENDLY_NAMESPACES[ns]):
            if method.startswith("_"):
                continue
            target = getattr(replay_ns, method, None)
            assert callable(target), f"cli.{ns}.{method}: 回放夹具不可调用"
            checked += 1
    assert checked > 150, f"只扫描到 {checked} 个回放方法，扫描面可能被改坏"

