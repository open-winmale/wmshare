"""文档-代码一致性门禁：README / API.md / quickstart 与目录、签名必须逐项对得上。

覆盖三类漂移：
  1. 计数与清单：文档里的域数/函数数/接口数/指标数、核心接口表、指标组表、附录函数表
  2. 参数与示例：表格参数 == 方法签名；每个示例真实可执行；README 代码块可运行
  3. 表述与口径：docstring 参数名存在、单位口径（小数/百分数）与目录一致

这些测试独立于生成器实现（直接解析文档文本 + inspect 签名），能抓住生成器本身的 bug。
"""
from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

from wmshare.api import (COMPOSITE_METHODS, FRIENDLY_INDEX, FRIENDLY_NAMESPACES,
                         GENERATED_NAMESPACES, _FRIENDLY_NS_TO_CATALOG)
from wmshare.catalog import load

REPO = Path(__file__).resolve().parents[1]
API_MD = (REPO / "docs" / "API.md").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")
GUIDE_MD = (REPO / "docs" / "GUIDE.md").read_text(encoding="utf-8")
AI_MD = (REPO / "docs" / "AI.md").read_text(encoding="utf-8")
CAT = load()

# 每接口小节（gen_api_docs.interface_block 的输出合同）：
#   #### `cli.ns.method` — 中文名 → 输入参数表 →（输出字段表 | 输出说明行）→ 示例代码块
IFACE_HEAD = re.compile(r"^#### `cli\.(\w+)\.(\w+)` — (.+)$")
PARAM_ROW = re.compile(r"^\| `(\w+)` \| ([\w?]+) \| (是|否) \| (.*?) \| (.*?) \|$")
GROUP_HEAD = re.compile(r"^#### 指标组 (.+?)（([\w.]+)）$")
GROUP_ROW = re.compile(r"^\| `(\$[\w.]+)` \| (.*?) \| (.*?) \|$")
FN_ROW = re.compile(r"^\| `([a-z][\w]*\.[a-z][\w]*)` \| (.*?) \| (?:原始数据|指标) \|")

# 签名注解 → 文档 json 类型（与 gen_api_docs/_introspect 的映射语义一致，独立复刻防同错）
_ANN2JSON = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
             "list": "array", "list[str]": "array", "dict": "object",
             "dict[str, Any]": "object", "Any": "object"}


def interface_blocks() -> list[dict]:
    """解析 API.md 的每接口小节为结构化块（ns/method/cn/params/ret/example）。"""
    blocks: list[dict] = []
    cur: dict | None = None
    in_example = False
    for line in API_MD.splitlines():
        if line.startswith("#"):  # 任何标题终止当前块（含新接口/指标组/附录域）
            in_example = False
            m = IFACE_HEAD.match(line)
            if m:
                cur = {"ns": m.group(1), "method": m.group(2), "cn": m.group(3),
                       "params": [], "ret": "", "example": None}
                blocks.append(cur)
            else:
                cur = None
            continue
        if cur is None:
            continue
        if in_example:
            if line.strip() == "```":
                in_example = False
            elif cur["example"] is None and line.strip():
                cur["example"] = line
            continue
        if line.strip() == "```python":
            in_example = True
            continue
        if (pm := PARAM_ROW.match(line)):
            cur["params"].append(pm.groups())
        elif line.startswith("**输出**："):
            cur["ret"] = line[len("**输出**："):].strip()
    return blocks


def core_rows() -> list[tuple[str, str, str, str, str]]:
    """兼容旧形态：[(ns, method, params_cell, ret, example)]（params_cell 已弃用为空）。"""
    return [(b["ns"], b["method"],
             "|".join(p[0] for p in b["params"]), b["ret"], b["example"])
            for b in interface_blocks()]


def _expected_params(ns: str, method: str) -> list[tuple[str, str, str, str]]:
    """签名 → (参数, json类型, 必填, 默认) 期望行（默认渲染规则与生成器一致）。"""
    sig = inspect.signature(getattr(FRIENDLY_NAMESPACES[ns], method))
    out = []
    for name, p in sig.parameters.items():
        if name == "self" or name.startswith("_"):
            continue
        ann = p.annotation if isinstance(p.annotation, str) else str(p.annotation)
        base = ann.split("|", 1)[0].strip()
        jt = _ANN2JSON.get(ann.strip()) or _ANN2JSON.get(base, "object")
        has_default = p.default is not inspect.Parameter.empty
        out.append((name, jt, "否" if has_default else "是",
                    repr(p.default) if has_default else "—"))
    return out


class FakeSession:
    """离线传输：token + eval 固定成功，返回列表（覆盖 last() 取首行的形态）。"""

    def post(self, url, json=None, data=None, headers=None, timeout=None):
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
                # window_stats 的脚本显式返回 MAP（rows/dps/total）
                if any("bonus.query_list" in ln for ln in lines) and \
                        any('"rows"' in ln for ln in lines):
                    return {"success": True,
                            "data": {"result": {"rows": [], "dps": 0.0, "total": 0.0}}}
                return {"success": True, "data": {"result": [{"ok": True}]}}
        return R()


@pytest.fixture(scope="module")
def cli():
    from wmshare.client import Client
    return Client(base_url="https://t", client_id="i", client_secret="s",
                  catalog=CAT, session=FakeSession())


def test_block_parser_finds_all_interfaces():
    """块解析器必须恰好解析出 FRIENDLY_INDEX 数量的小节（防解析器自身漏块）。"""
    blocks = interface_blocks()
    assert len(blocks) == len(FRIENDLY_INDEX), \
        f"解析出 {len(blocks)} 个接口小节，FRIENDLY_INDEX 有 {len(FRIENDLY_INDEX)} 个"


# ---------------------------------------------------------------- 计数与清单
def test_api_md_counts_match_catalog():
    groups = sum(len(d.get("metric_groups") or []) for d in CAT.domains.values())
    metrics = CAT.metrics["count"]
    assert f"共 **{len(CAT.domains)}** 个数据域" in API_MD
    assert f"**{len(FRIENDLY_INDEX)}** 个核心接口" in API_MD
    assert f"**{groups}** 个指标组" in API_MD
    assert f"{metrics} 个指标代码" in API_MD
    assert f"全量 {CAT.stats()['functions']} 个底层函数" in API_MD


def test_readme_counts_match_catalog():
    stats = CAT.stats()
    groups = sum(len(d.get("metric_groups") or []) for d in CAT.domains.values())
    curated = sum(len(g.get("metrics") or []) for d in CAT.domains.values()
                  for g in d.get("metric_groups") or [])
    assert f"{stats['functions']} 个底层函数" in README
    assert f"{len(FRIENDLY_INDEX)} 个核心接口" in README
    assert f"{stats['metric_catalog_total']} 个指标代码" in README
    assert f"{len(CAT.domains)} 个数据域" in README
    assert f"{groups} 个指标组" in README
    assert f"{curated} 个精选常用指标代码" in README


def test_docs_no_stale_counts():
    """防回归：过时计数口径不得重现（127 曾滞后两个版本、2,639 滞后一个目录代际）。"""
    stale = ("2,639", "2639", "2197", "263 个", "116 个核心接口",
             "127 个 friendly", "12 个编号示例", "130 个核心接口")
    docs = {
        "README.md": README,
        "docs/GUIDE.md": GUIDE_MD,
        "docs/AI.md": AI_MD,
        "docs/README.md": (REPO / "docs" / "README.md").read_text(encoding="utf-8"),
    }
    for name, text in docs.items():
        hit = [s for s in stale if s in text]
        assert not hit, f"{name} 残留过时计数：{hit}"


def test_api_module_docstring_counts_match_catalog():
    """门面模块 docstring 的底层函数计数必须与目录一致（曾停留 155 而目录已 164）。"""
    src = (REPO / "src" / "wmshare" / "api" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"(\d+) 个底层函数零遮蔽", src)
    assert m, "模块 docstring 缺少底层函数计数"
    assert int(m.group(1)) == CAT.stats()["functions"], \
        "api/__init__.py 模块 docstring 的函数计数与目录漂移"


def test_api_md_core_interfaces_exact():
    blocks = interface_blocks()
    got = [(b["ns"], b["method"]) for b in blocks]
    want = [(ns, m) for _, ns, m, _, _ in FRIENDLY_INDEX]
    assert sorted(got) == sorted(want), "核心接口小节与 FRIENDLY_INDEX 不一致"
    assert len(got) == len(set(got)), "核心接口小节存在重复"


def test_api_md_params_match_signatures():
    for b in interface_blocks():
        expected = _expected_params(b["ns"], b["method"])
        got = [(p[0], p[1], p[2], p[3].strip("`")) for p in b["params"]]
        assert got == expected, \
            f"{b['ns']}.{b['method']} 文档参数表 {got} != 签名 {expected}"


def test_api_md_last_rows_are_map():
    """last() 包装返回单行/None，输出必须是字段表（MAP 形态），不得沿用底层数组。"""
    wanted = {("kline", "last"), ("moneyflow", "last"), ("dividend", "last")}
    seen = set()
    for b in interface_blocks():
        key = (b["ns"], b["method"])
        if key in wanted:
            seen.add(key)
            block = _block_text(b)
            assert "**输出字段**" in block, f"{key}: 期望字段表形态"
            assert "**输出**：ARR" not in block, f"{key}: 不得是数组说明"
    assert seen == wanted


def _block_text(block: dict) -> str:
    """块起止之间的原文（用于形态断言）：从接口标题到下一个标题。"""
    lines = API_MD.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"#### `cli.{block['ns']}.{block['method']}`"):
            start = i
            break
    assert start is not None
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        out.append(ln)
    return "\n".join(out)


def test_indicator_units_documented_as_decimal():
    assert "0.332 = 33.2%" in README
    assert "0.332 = 33.2%" in API_MD
    assert "15.0 = 15%" not in README
    assert "15.0 = 15%" not in API_MD
    assert "指标层比率统一为小数" in API_MD


def test_api_md_metric_groups_match_catalog():
    doc_groups: dict[str, list[tuple[str, str, str]]] = {}
    current = None
    for line in API_MD.splitlines():
        m = GROUP_HEAD.match(line)
        if m:
            current = m.group(2)
            doc_groups[current] = []
            continue
        if line.startswith("#"):
            current = None
            continue
        if current and (g := GROUP_ROW.match(line)):
            doc_groups[current].append((g.group(1), g.group(2), g.group(3).strip()))

    catalog_groups = {}
    for d in CAT.domains.values():
        for g in d.get("metric_groups") or []:
            catalog_groups[g["id"]] = [(m["code"], m["cn"]) for m in g["metrics"]]

    assert set(doc_groups) == set(catalog_groups), "指标组集合不一致"
    for gid, pairs in catalog_groups.items():
        got = [(c, cn) for c, cn, _ in doc_groups[gid]]
        assert got == pairs, f"指标组 {gid} 的指标代码/中文名与目录不一致"
        # 守护列：目录声明了 range/unit 的指标，文档必须带守护标注（反之不得空穴来风）
        by_code = {m["code"]: m for d in CAT.domains.values()
                   for g in d.get("metric_groups") or [] for m in g.get("metrics") or []}
        for code, _, guard in doc_groups[gid]:
            m = by_code[code]
            if m.get("range") or m.get("unit"):
                assert guard, f"{code} 目录声明了守护，文档守护列为空"
            else:
                assert not guard, f"{code} 目录无守护声明，文档却写了：{guard}"


def visible_catalog_functions(cat) -> list[str]:
    """与 gen_api_docs.doc_hidden 同规则：排除内部/索引积木类函数。"""
    out = []
    for names in cat.functions_by_domain().values():
        for name in names:
            short = name.split(".", 1)[1]
            if cat.function(name).get("status") == "internal":
                continue
            if short.startswith(("index_where_", "index_field")) or short.endswith("_bin_expr"):
                continue
            out.append(name)
    return out


def test_api_md_appendix_functions_match_catalog():
    appendix = API_MD.split("附录：全量底层函数目录", 1)[1]
    doc_fns = [m.group(1) for m in map(FN_ROW.match, appendix.splitlines()) if m]
    assert sorted(doc_fns) == sorted(visible_catalog_functions(CAT)), \
        "附录函数表与目录（可见函数）不一致"


# ---------------------------------------------------------------- 示例可执行
def test_api_md_examples_execute(cli):
    for ns, method, _, _, example in core_rows():
        assert example.startswith(f"cli.{ns}.{method}("), f"{ns}.{method} 示例串不匹配"
        eval(example, {"cli": cli})  # noqa: S307 - 文档内生成的示例，受仓库控制


class _FakeBatch:
    """pandas-free 批结果替身：CI 不装可选依赖，README 块只需验证调用形态不回退。

    真 BatchResult.to_df() 需要 pandas（wmshare[dataframe]）；CI 环境故意不装，
    曾把 test_readme_python_blocks_execute 打红（1.9.2 起 main 常红）。
    """

    def __init__(self, results: dict, requests: int):
        self.results, self.errors, self.requests = results, {}, requests

    def to_df(self):
        return [{"symbol": k, **(v if isinstance(v, dict) else {"value": v})}
                for k, v in self.results.items()]


class ReadmeClient:
    """README 示例执行用的罐头客户端：返回值与示例注释里的预期输出同量级。

    与 test_units.py 的罐头数据同源（真实 probe 样本），保证注释值不腐烂。
    """

    INDICATORS = {"$PCT_PE_TTM_10Y_LAST": 0.42, "$CUR_IND_ROE_PCT_LAST": 1.0,
                  "$PE_TTM_LAST": 25.5}

    def __init__(self):
        import types
        self.kline = types.SimpleNamespace(
            bars=lambda *a, **k: [{"date": "2026-10-20", "close": 1331.88,
                                   "volume": 3413500.0, "amount": 4525398959.0,
                                   "percent": 0.005215}],
            screen_above_ma20=lambda *a, **k: True,
            index_breadth_summary=lambda *a, **k: {"up": 3200, "down": 2100},
        )
        self.screener = types.SimpleNamespace(
            screen_limit_up=lambda *a, **k: False,
            screen_above_ma20=lambda *a, **k: True,
            screen_momentum_20d=lambda *a, **k: False,
            screen_volume_spike=lambda *a, **k: True,
            # 数值取自 2026-10-24 真实 probe（A 股全市场截面）
            index_breadth_summary=lambda *a, **k: {"total": 5685, "up": 4567, "down": 934,
                                                   "flat": 184, "up_pct": 80.3,
                                                   "down_pct": 16.4, "flat_pct": 3.2,
                                                   "median_pct": 0.015363},
            index_breadth_bins=lambda *a, **k: [
                {"label": "涨停", "count": 109, "pct_of_total": 1.9},
                {"label": "+5%~10%", "count": 464, "pct_of_total": 8.2},
                {"label": "+3%~5%", "count": 829, "pct_of_total": 14.6},
            ],
            index_top_movers=lambda *a, **k: [
                {"symbol": "600519", "name": "贵州茅台", "percent": 0.0052},
            ],
            # 全市场条件选股：罐头值取 2026-11-10 真实 probe（命中 108，首行伊泰B股）
            query=lambda *a, **k: {"count": 108, "rows": [
                {"symbol": "900948", "name": "伊泰B股",
                 "$BONUS_RATE_3Y_AVG_LAST": 0.2104, "$ROE_TTM_LAST": 0.1631},
            ]},
        )
        self.dividend = types.SimpleNamespace(
            yield_ttm=lambda *a, **k: 0.0396,
            screen_quality=lambda *a, **k: True,
            history=lambda *a, **k: [],
        )
        self.indicator = types.SimpleNamespace(
            get=lambda sym, code: self.INDICATORS.get(code, 0.5),
            metrics=lambda sym, codes: {c: self.INDICATORS.get(c) for c in codes},
        )
        self.notice = types.SimpleNamespace(
            list=lambda *a, **k: [],
            has_buyback=lambda *a, **k: True,
        )
        self.statements = types.SimpleNamespace(
            income=lambda *a, **k: [], compare=lambda *a, **k: [],
        )
        self.info = types.SimpleNamespace(profile=lambda *a, **k: {})
        self.stocks = types.SimpleNamespace(
            list=lambda *a, **k: [{"symbol": "600519", "name": "贵州茅台",
                                   "exchange": "sh", "industry": "industry.S480301",
                                   "industry_name": "股份制银行", "is_st": False,
                                   "listed": "2001-08-27"}],
            industries=lambda *a, **k: [{"symbol": "S48", "name": "银行",
                                         "level": 1, "standard": "sw2021"}],
            industry_members=lambda *a, **k: [
                {"symbol": "600519", "name": "贵州茅台", "listed": "2001-08-27"}],
        )

    def _payload(self, name, symbols):
        # 首屏「选股实战」块：批量股息率返回小数，走筛选分支；其余保持行情行形状
        if name == "bonus.snapshot_yield_ttm":
            return {s: 0.045 for s in symbols}
        return {s: {"close": 1331.88, "percent": 0.0052} for s in symbols}

    def call_batch(self, name, symbols, **kw):
        return _FakeBatch(self._payload(name, symbols), requests=1)

    def batch_all(self, name, symbols, batch_size=None, **kw):
        return _FakeBatch(self._payload(name, symbols),
                          requests=-(-len(symbols) // 500))

    def batch_iter(self, name, symbols, batch_size=None, **kw):
        step = batch_size or 500
        chunks = [symbols[i:i + step] for i in range(0, len(symbols), step)]
        for chunk in chunks:
            yield _FakeBatch({s: {"close": 1331.88, "percent": 0.0052}
                              for s in chunk}, requests=1)

    @classmethod
    def from_env(cls, *a, **k):
        return cls()

    def call(self, name, **kw):
        return []


@pytest.fixture(scope="module")
def readme_cli():
    return ReadmeClient()


def test_readme_python_blocks_execute(readme_cli):
    import textwrap

    import wmshare
    blocks = re.findall(r"```python\n(.*?)```", README, re.S)
    assert blocks, "README 缺少 python 示例"
    original = wmshare.Client
    wmshare.Client = type("PatchedClient", (ReadmeClient,), {})  # from_env/构造都不联网
    try:
        for block in blocks:
            exec(compile(textwrap.dedent(block), "README.md", "exec"),
                 {"__name__": "__readme__"})
    finally:
        wmshare.Client = original


def test_readme_images_exist():
    """README 引用的图片必须真实存在且非空——首屏静态图不进生成物漂移门禁，单独守。"""
    refs = re.findall(r"!\[[^\]]*\]\((docs/img/[^)\s]+)\)", README)
    assert refs, "README 首屏缺少示意图"
    for rel in refs:
        path = REPO / rel
        assert path.is_file(), f"README 引用的图片不存在：{rel}"
        assert path.stat().st_size > 0, f"README 引用的图片为空：{rel}"


def test_readme_example_outputs_documented():
    """示例注释里的预期输出必须与罐头数据同值——注释值从此有测试守护。"""
    pairs = [("yield_ttm", "0.0396"),
             ("$PCT_PE_TTM_10Y_LAST", "0.42"),
             ("$CUR_IND_ROE_PCT_LAST", "1.0")]
    for call, value in pairs:
        line = next((ln for ln in README.splitlines() if call in ln and value in ln), None)
        assert line is not None, f"README 示例缺少 {call} 与预期输出 {value} 的对应注释"


def test_readme_zero_credential_snippet_matches_snapshot():
    """首屏「零凭证先试」块的注释值必须等于真实快照回放值。

    首屏是唯一给未注册用户的钩子：值一旦与 ``_demo_data.json`` 漂移，陌生人照抄就跑出
    不同数字。这里直接打真快照（不 patch），把注释与快照焊死。
    """
    import wmshare

    assert "wmshare.demo_client()" in README, "首屏缺少零凭证试跑入口"
    demo = wmshare.demo_client()
    for label, value in (("yield", f"{demo.dividend.yield_ttm('600519'):.2%}"),
                         ("total", str(demo.screener.index_breadth_summary()["total"]))):
        assert value in README, f"首屏注释的 {label} 值 {value} 与快照回放不符"


def test_readme_units_and_guards_documented():
    """单位与守护的最小行动块必须在 README 成文（2026-10-25 二次瘦身定版）。

    2026-11-10 重构：「能力一览」章更名为「基本功能」（基本功能/特色功能分章）。
    """
    for kw in ("单位与数据守护", "DataError", '_units="native"', "validate=False",
               "服务端算好直出", "11 个质量筛选器", "基本功能"):
        assert kw in README, f"README 缺少关键内容：{kw}"
    assert "量=手" not in README and "volume in lots" not in README, \
        "成交量已统一为股，README 不得再写手"
    # API.md 同步：catalog 章节存在、旧口径文案绝迹
    assert "数据目录（离线）" in API_MD and "cat.search" in API_MD
    assert "差额 / 合并值 × 100" not in API_MD


def test_readme_no_competitor_names():
    """README 零竞品名（2026-10-24 用户定版）：差异化卖点一律自证式表述，防回潮。

    禁词表唯一来源是 tools/check_leak.py 的混淆词表——测试不二次入库字面量。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_leak_gate", REPO / "tools" / "check_leak.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not mod.thirdparty_pattern().search(README), \
        "README 不得出现竞品名（对比历史留在 CHANGELOG）"


def test_readme_is_lean():
    """店面纪律：README 保持精炼（2026-10-25 二次瘦身 206 行），超限先删内容再提限。

    2026-10-28 提至 250：新增均为上手动线必需（凭证两种配置示例、安装验证命令、
    examples 入口），已按「先删后提限」压缩过一轮。
    2026-10-29 提至 275：批量取数是核心上手动线（429 按请求次数限流，批量是正解），
    新增「批量取数」专章（分批执行器 batch_all/batch_iter、限流续跑、批级容错）；
    已先删「更多」区旧批量 bullet、压缩镜像/生态/示例段落腾出空间。
    2026-10-29 再提至 287：补三接口参数对照表（batch_all/batch_iter/call_batch 的
    用途、请求数、关键参数与默认值），参数语义必须成文——同名不同义是认知陷阱。
    2026-10-29 提至 289：把批量放进「三行上手」动线（新手必经路径不能只有单票示例，
    否则学完首页就写 for 循环逐票取数、正好撞 429）。
    2026-10-29 提至 291：批量章节补「市场边界」——跨市场混批会在本市场引擎里取到
    错误数值（实测同一港股标的 close/percent 均不符），必须成文且有 SDK 侧拦截。
    2026-11-11 提至 306：新增「指数与行业估值历史」节——这是全库计算量最重的数据
    （56 键 × 730 期 × 每期全部成分股汇总，单键重算 3.2M fuel/39s），此前店面只有
    表格一行、接口名完全不出现，用户无从发现。新增含可跑示例与口径摘要；已先压缩
    市场覆盖注记（4→1 行）、许可段批量重复句（3→2 行）、「更多」合并（2→1 行）。
    2026-11-12 提至 330：新增「主站、开放平台与 SkillHub」节——同一套数据的三层入口
    此前在店面完全缺失（投研/SkillHub/主站 0 处），读者无从知道有现成工具站与 AI
    技能库；主站按投资者类型列应用（指数定投/可转债/财报专业版/抄作业等）。
    """
    assert len(README.splitlines()) <= 330, \
        f"README 膨胀到 {len(README.splitlines())} 行（上限 330）；长内容下沉 docs/ 或删除"


def test_readme_no_stale_trial_promises():
    """1.7.0 起凭证必填（内置体验 AppID 已下线）：公开店面不得残留旧承诺，防回潮。

    起 因：1.7.0 发布时 pyproject 描述 / README 英文 TL;DR / OpenAPI intro 三处仍写
    「开箱即用，内置体验 appid」，用户照店面走第一步就撞缺凭证报错。
    豁免：行内含「不再内置」「已下线」（描述删除本身合法，如 CHANGELOG/SKILL）。
    """
    banned = ("开箱即用", "共享池", "zero-config", "内置体验 appid")
    exempt = ("不再内置", "已下线")
    targets: list[tuple[str, str]] = [
        ("README.md", README),
        ("docs/API.md", API_MD),
        ("docs/openapi.json",
         (REPO / "docs" / "openapi.json").read_text(encoding="utf-8")),
    ]
    for ex in sorted((REPO / "examples").glob("*.py")):
        targets.append((f"examples/{ex.name}", ex.read_text(encoding="utf-8")))
    for name, text in targets:
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(b in low for b in banned) and not any(e in line for e in exempt):
                raise AssertionError(f"{name}:{i} 残留过期承诺（1.7.0 已凭证必填）：{line.strip()}")


def test_docs_no_ad_diversion_cta():
    """公开文档零导流话术（2026-10-29 Gitee 风控整改）：只讲事实，不写促销 CTA。

    起因：Gitee 镜像仓 README 被判「内容可能含有违规信息」不渲染，风控分类里
    「纯广告导流」是首要嫌疑——「注册…微信扫码，免费、注册即得」这类模板同时命中
    扫码 + 领取 + 免费三连。凭证获取改成中性陈述（去哪里取、取哪两个值）后，
    能力描述与额度事实不变。禁词表按 Gitee 页面分类维护，不含事实性表述
    （如「免费档 500 次/小时」是额度事实，允许）。目标面 = 全部公开文档：
    README、docs/*.md、SKILL、examples/README、AGENTS、llms.txt。
    """
    banned = ("微信扫码", "扫码微信", "扫码登录", "注册即得", "免费领取", "不另收费")
    targets: list[tuple[str, str]] = [
        ("README.md", README),
        ("docs/API.md", API_MD),
        ("docs/GUIDE.md", GUIDE_MD),
        ("docs/AI.md", AI_MD),
        ("docs/INDICATORS.md",
         (REPO / "docs" / "INDICATORS.md").read_text(encoding="utf-8")),
        ("docs/README.md", (REPO / "docs" / "README.md").read_text(encoding="utf-8")),
        ("skills/wmshare/SKILL.md",
         (REPO / "src" / "wmshare" / "skills" / "wmshare" / "SKILL.md").read_text(encoding="utf-8")),
        ("examples/README.md", (REPO / "examples" / "README.md").read_text(encoding="utf-8")),
        ("AGENTS.md", (REPO / "AGENTS.md").read_text(encoding="utf-8")),
        ("llms.txt", (REPO / "llms.txt").read_text(encoding="utf-8")),
    ]
    for name, text in targets:
        for i, line in enumerate(text.splitlines(), 1):
            hit = [b for b in banned if b in line]
            assert not hit, f"{name}:{i} 残留导流话术 {hit}（Gitee 风控判定违规）：{line.strip()}"


def test_readme_catalog_references_valid():
    """行内 `cat.xxx(...)` 引用必须是 Catalog 真实方法（防止文档凭空写方法名）。"""
    from wmshare.catalog import Catalog
    for meth in set(re.findall(r"cat\.(\w+)\(", README)):
        assert meth == "load" or callable(getattr(Catalog, meth, None)), \
            f"README 引用了不存在的目录方法 cat.{meth}()"


def test_example_calls_are_valid():
    """全部 examples/*.py 的 cli.* 调用、$指标码、cat.* 方法必须真实存在（防示例腐烂）。"""
    files = sorted((REPO / "examples").glob("*.py"))
    assert len(files) >= 9, f"示例应不少于 9 个（编号课程），实际 {len(files)}"
    metrics = {m["code"] for m in CAT.metrics["metrics"]}
    total = 0
    for path in files:
        src = path.read_text(encoding="utf-8")
        # 03 故意演示「未知指标在发请求前被拦下」，是唯一允许出现假指标码的示例
        if path.name != "03_error_handling.py":
            codes = set(re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", src))
            assert codes <= metrics, f"{path.name} 引用了不存在的指标代码：{codes - metrics}"
        for meth in set(re.findall(r"cat\.(\w+)\(", src)):
            assert callable(getattr(CAT, meth, None)), \
                f"{path.name} 引用了不存在的目录方法 cat.{meth}()"
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                    and isinstance(f.value.value, ast.Name) and f.value.value.id == "cli"):
                continue
            if f.value.attr == "call":  # cli.call("ns.fn", ...) 走目录级校验
                assert node.args and isinstance(node.args[0], ast.Constant)
                CAT.function(node.args[0].value)
            else:
                cls = FRIENDLY_NAMESPACES.get(f.value.attr) or GENERATED_NAMESPACES.get(f.value.attr)
                assert cls is not None, \
                    f"{path.name} 引用了不存在的命名空间 {f.value.attr}"
                if not hasattr(cls, f.attr):
                    # 与 _Api.__getattr__ 同语义：目录委托函数（如 screener.screen_up_today）
                    catalog_ns = _FRIENDLY_NS_TO_CATALOG.get(f.value.attr, "")
                    assert CAT.function(f"{catalog_ns}.{f.attr}"), \
                        f"{path.name} 引用了不存在的方法 {f.value.attr}.{f.attr}"
                    continue
                sig = inspect.signature(getattr(cls, f.attr))
                kwargs = {kw.arg: None for kw in node.keywords if kw.arg}
                sig.bind(None, *[None] * len(node.args), **kwargs)
            total += 1
    assert total >= 25, f"示例共识别到 {total} 个 cli.* 调用，解析可能失效"


# ---------------------------------------------------------------- 表述与口径
def test_docstring_params_exist_in_signature():
    for _, ns, method, _, _ in FRIENDLY_INDEX:
        fn = getattr(FRIENDLY_NAMESPACES[ns], method)
        doc = inspect.getdoc(fn) or ""
        params = set(re.findall(r"^:param (\w+):", doc, re.M))
        sig = set(inspect.signature(fn).parameters) - {"self", "_raw", "_df"}
        assert params <= sig, f"{ns}.{method} docstring 参数 {params - sig} 不在签名中"


def test_unit_wording_matches_catalog():
    """目录说小数，文档就不能说百分数（反之亦然）——曾出现过分红率口径事故。"""
    problems = []
    for _, ns, method, _, underlying in FRIENDLY_INDEX:
        fn_key = underlying.split("[")[0].strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fn_key):
            continue
        try:
            ret = (CAT.function(fn_key).get("returns") or {}).get("desc") or ""
        except KeyError:
            continue
        cls = FRIENDLY_NAMESPACES[ns]
        doc = (inspect.getdoc(getattr(cls, method)) or "") + (inspect.getdoc(cls) or "")
        if "小数" in ret and "百分数" in doc:
            problems.append(f"{ns}.{method}: 目录=小数，文档出现百分数")
        if "百分数" in ret and "小数" in doc:
            problems.append(f"{ns}.{method}: 目录=百分数，文档出现小数")
    assert not problems, problems


def _assert_doc_references(text: str, label: str, cli) -> None:
    """文档引用三件套校验：$指标码 / cli.ns.method / cat.* / 域 id 全部真实存在。"""
    codes = set(re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", text))
    metrics = {m["code"] for m in CAT.metrics["metrics"]}
    assert codes <= metrics, f"{label} 引用了不存在的指标代码：{codes - metrics}"
    # cli.ns.method 必须运行时可触达：显式方法或目录动态委托（与真实语义一致）
    for ns, method in set(re.findall(r"cli\.(\w+)\.(\w+)\(", text)):
        try:
            getattr(getattr(cli, ns), method)
        except AttributeError:
            raise AssertionError(f"{label} 引用了不存在的接口 {ns}.{method}") from None
    for meth in set(re.findall(r"cat\.(\w+)\(", text)):
        assert meth == "load" or callable(getattr(type(CAT), meth, None)), \
            f"{label} 引用了不存在的目录方法 cat.{meth}()"
    # 反引号里的域 id 必须存在
    for dom in re.findall(r"`([a-z]+\.[a-z_]+)`", text):
        if dom.split(".")[0] in {d.split(".")[0] for d in CAT.domains}:
            assert dom in CAT.domains, f"{label} 引用了不存在的域 {dom}"


def test_readme_references_are_valid(cli):
    _assert_doc_references(README, "README", cli)


def test_guide_references_are_valid(cli):
    """GUIDE 是 how-to 主文档：菜谱里的每个调用与指标码必须真实存在。"""
    _assert_doc_references(GUIDE_MD, "docs/GUIDE.md", cli)


def test_ai_references_are_valid(cli):
    """AI.md 的提示词模板与示例命令同样受引用门禁（AI 照抄即正确）。"""
    _assert_doc_references(AI_MD, "docs/AI.md", cli)


def test_indicators_references_are_valid(cli):
    """INDICATORS.md（生成物）的码/接口/目录方法引用同样受门禁（防目录演进后引用失真）。

    通配标记（`$ID_*` 族标题、`$c_* / $x_*`）不是码：先剥离再校验，
    其余出现的每个 `$码` 仍须全量真实（场景速查与示例零豁免）。
    """
    text = (REPO / "docs" / "INDICATORS.md").read_text(encoding="utf-8")
    text = re.sub(r"`\$[A-Za-z_][A-Za-z0-9_]*\*`", "", text)
    _assert_doc_references(text, "docs/INDICATORS.md", cli)


def test_openapi_matches_signatures_and_returns():
    spec = json.loads((REPO / "docs" / "openapi.json").read_text(encoding="utf-8"))
    ops = {op["operationId"]: op for item in spec["paths"].values() for op in item.values()}
    type_map = {"str": "string", "int": "integer", "float": "number",
                "bool": "boolean", "list[str]": "array", "dict": "object"}
    for _, ns, method, _, underlying in FRIENDLY_INDEX:
        op = ops[f"{ns}_{method}"]
        fn = getattr(FRIENDLY_NAMESPACES[ns], method)
        params = [p for name, p in inspect.signature(fn).parameters.items()
                  if name != "self" and not name.startswith("_")]
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert set(schema["properties"]) == {p.name for p in params}
        assert set(schema.get("required") or []) == {
            p.name for p in params if p.default is inspect.Parameter.empty}
        for p in params:
            ann = p.annotation if isinstance(p.annotation, str) else str(p.annotation)
            expected = type_map.get(ann.split("|")[0].strip(), "object")
            assert schema["properties"][p.name]["type"] == expected, f"{ns}.{method}.{p.name}"

        fn_key = underlying.split("[")[0].strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fn_key):
            continue
        shape = CAT.function(fn_key).get("returns_shape")
        if not shape:
            continue
        fields = (shape.get("items") or shape).get("fields") or []
        if not fields:
            continue
        resp = op["responses"]["200"]["content"]["application/json"]["schema"]
        expected_container = {
            ("kline", "last"): "object",
            ("moneyflow", "last"): "object",
            ("dividend", "last"): "object",
            ("kline", "bars"): "array",
        }
        if (ns, method) in expected_container:
            assert resp.get("type") == expected_container[(ns, method)], \
                f"{ns}.{method} OpenAPI 容器类型错误：{resp.get('type')}"
        if ns == "notice" and method in ("list", "recent", "by_category", "find", "on_date"):
            assert {"date", "title", "url"} <= set(resp.get("items", {}).get("properties") or {}), \
                f"notice.{method} 未记录规范化字段"
        container = resp.get("items", resp) if resp.get("type") == "array" else resp
        assert set(container.get("properties") or {}) == {f["name"] for f in fields}, \
            f"{ns}.{method} 响应字段与目录 returns_shape 不一致"


def test_llms_lists_composite_interfaces():
    """llms.txt 必须列出组合接口：AI 文档挖掘只读这份索引，漏列会被误判为「没有该 cli 接口」。

    组合方法不是 FRIENDLY_INDEX 成员（底层不是单一目录函数），按域索引天然覆盖不到，
    所以在 llms.txt 单独成节；这里锁住「每个组合方法都出现 + 头部计数含组合数」。
    """
    llms = (REPO / "llms.txt").read_text(encoding="utf-8")
    total = len(FRIENDLY_INDEX) + sum(len(v) for v in COMPOSITE_METHODS.values())
    assert f"{len(FRIENDLY_INDEX)} 个核心接口" in llms
    assert f"{sum(len(v) for v in COMPOSITE_METHODS.values())} 个组合接口" in llms
    assert f"{total} 个 friendly API" in llms
    for ns, methods in COMPOSITE_METHODS.items():
        for method in methods:
            assert f"`cli.{ns}.{method}(" in llms, f"llms.txt 漏列组合接口 cli.{ns}.{method}"


def test_api_md_composite_section_states_facade_and_ec():
    """组合小节必须写明「同样是 cli 门面、可取数计 EC」——防被读成纯本地模块。"""
    assert "可直接调用" in API_MD and "EC 照常计" in API_MD
    assert "wmshare.backtest" in API_MD          # backtest 纯内核指路
