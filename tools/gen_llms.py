"""生成 llms.txt / llms-full.txt：AI 友好文档索引与全文拼接（llmstxt.org 规范）。

落地 ROADMAP M4.1：H1 + 摘要块引 + Docs/Key Concepts + 按域索引（单行语义锚点，
随目录自动更新）+「何时不要用」负向节。链接用 GitHub raw URL，AI 可直接抓
markdown 原文；llms-full.txt 按 教程→skill→指南→AI→参考 顺序全文拼接。

用法：
    python3 tools/gen_llms.py            # 重新生成
    python3 tools/gen_llms.py --check    # 漂移检查（CI / pytest 拦截手改）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

RAW = "https://raw.githubusercontent.com/open-winmale/wmshare/main"

FULL_PARTS = [
    "README.md",
    "src/wmshare/skills/wmshare/SKILL.md",
    "docs/GUIDE.md",
    "docs/AI.md",
    "docs/API.md",
]


def _domain_line(domain: dict, facade: list[str]) -> str:
    desc = (domain.get("description") or "").strip()
    head = desc.split("。")[0].strip() if desc else ""
    if len(head) > 72:
        head = head[:71].rstrip("，、：: ") + "…"
    via = f"（cli.{' / cli.'.join(facade)}）" if facade else ""
    return f"- `{domain['id']}`（{domain['cn']}）{via}：{head or '见 API.md'}"


def build_llms_txt() -> str:
    import wmshare
    from wmshare.api import FRIENDLY_INDEX, _FRIENDLY_NS_TO_CATALOG

    cat = wmshare.load()
    stats = cat.stats()
    n_examples = len(list((REPO / "examples").glob("[0-9][0-9]_*.py")))
    facade_by_domain: dict[str, list[str]] = {}
    for ns, cat_ns in _FRIENDLY_NS_TO_CATALOG.items():
        for d in cat.domains.values():
            if d["id"] == cat_ns or d["id"].endswith("." + cat_ns):
                facade_by_domain.setdefault(d["id"], []).append(ns)
                break
    by_domain = cat.functions_by_domain()

    out = [
        "# wmshare",
        "",
        f"> 覆盖 A 股、港股、美股的 Python 财经数据 SDK：{stats['domains']} 个数据域、"
        f"{stats['functions']} 个底层函数、{stats['metric_catalog_total']} 个指标码、"
        f"{len(FRIENDLY_INDEX)} 个核心接口。BSD-3-Clause 开源；取数需开放平台凭证"
        "（环境变量 WMSHARE_CLIENT_ID / WMSHARE_CLIENT_SECRET，见 README）。",
        "",
        "## Docs",
        "",
        f"- [README]({RAW}/README.md)：安装、凭证配置、选股实战（10 行全市场筛选）、能力与市场覆盖矩阵",
        f"- [使用指南 GUIDE]({RAW}/docs/GUIDE.md)：单票菜谱、批量取数、多市场、pandas、故障排查",
        f"- [指标库 INDICATORS]({RAW}/docs/INDICATORS.md)：全量指标码按族导航——命名语法、"
        "11 组精选口径、死码清单与场景速查（先查码，禁止自算已有指标）",
        f"- [AI 用法]({RAW}/docs/AI.md)：MCP server、skill、文档上下文与报错驱动的 Agent 接入路径",
        f"- [API 参考]({RAW}/docs/API.md)：{len(FRIENDLY_INDEX)} 个核心接口的参数 / 返回 / 单位口径",
        f"- [Agent Skill]({RAW}/src/wmshare/skills/wmshare/SKILL.md)：随包分发的 agent 用法合同"
        "（目录先行、单位铁律、决策树、坑位）",
        f"- [可运行示例]({RAW}/examples/README.md)：{n_examples} 个编号示例"
        "（全部支持演示客户端离线试跑），CI 端到端覆盖",
        f"- [CHANGELOG]({RAW}/CHANGELOG.md)：版本历史",
        "",
        "## Key Concepts",
        "",
        "- **单位铁律**：比率/涨跌幅/分位一律小数（0.0396 = 3.96%、0.42 = 42% 分位），"
        "金额=元、量=股；唯一例外是 cli.screener 宽度接口的 `*_pct`（百分数数值）",
        "- **目录先行**：`wmshare.load()` 后 `cat.search(\"中文\")` 检索函数与指标码、"
        '`cat.function(name)["params"]` 查合同；禁止编造指标码（未知名在发请求前即报错）',
        "- **指标码命名**：`$主题+[窗口 3Y/5Y/10Y]+[统计量 TTM/YOY/AVG/MIN/TREND]+[_LAST]`；"
        "族前缀 `$PCT_*` 历史分位、`$ID_*` 行业均值、`$CUR_IND_*` 行业内分位、"
        "`$INDEX_*` 指数层、`$FUT_*` 期货主力——先查 `cat.search`，"
        "禁止自算已有指标（eval 按标的数逐票计费 EC，预置码便宜得多）",
        "- **MCP 优先**：`pip install \"wmshare[mcp]\"` 后先用 `wmshare_search` / "
        "`wmshare_contract`，再用 quote/history/metrics/company/screen/disclosures/batch/call",
        "- **批量绕 429**：服务端按请求次数限流（免费档 500 次/小时、5,000 次/日）；"
        "`cli.batch_all(name, codes)` 把 A 股 5,691 家压成 12 次请求；"
        "容错用批级 `on_batch_error=\"skip\"`，勿用票级逐票放大；一个批次只能同一个市场",
        "- **多市场**：`Client(market=\"cn\"/\"hk\"/\"us\")` 缺省 cn；"
        "港美专项（CCASS/沽空/评级）挂在对应市场客户端的 cli.intl 上",
        "- **数据守护**：每次返回做量级与不变量校验，违例抛 DataError（数据在报警，勿吞）",
        "",
        "## Data Domains",
        "",
    ]
    for d in cat.domains.values():
        out.append(_domain_line(d, facade_by_domain.get(d["id"], [])))
    out += [
        "",
        "## When NOT to use",
        "",
        "- 不是回测框架（没有撮合/仓位管理），不是数据库（数据经云端 API 运行时获取）",
        "- 基金净值 / 期货 / 期权 / 债券（可转债除外）未覆盖",
        "- 美股日 K 已日更（周/月 K 由日线派生）；最新价量用 `cli.kline.live / snapshot`",
        "- 港股十大流通股东与回购上游有管线、SDK 接口待路由（见 CHANGELOG/ROADMAP）",
        "",
        "## Optional",
        "",
        f"- [openapi.json]({RAW}/docs/openapi.json)：OpenAPI 3.1 机器可读合同",
        f"- [llms-full.txt]({RAW}/llms-full.txt)：本页所列文档的全文拼接（大上下文 agent 直读）",
        f"- [CONTRIBUTING]({RAW}/CONTRIBUTING.md)：贡献门禁与内容规范",
        "",
    ]
    return "\n".join(out)


def build_llms_full_txt() -> str:
    parts = ["# wmshare — Full Documentation\n\n"
             "> 由 tools/gen_llms.py 生成（README + skill + 指南 + AI 用法 + API 参考全文）。"]
    for rel in FULL_PARTS:
        body = (REPO / rel).read_text(encoding="utf-8")
        parts.append(f"\n\n---\n\n<!-- 来源：{rel} -->\n\n{body.strip()}")
    return parts[0] + "".join(parts[1:]) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="漂移检查：不一致则退出码 1")
    args = ap.parse_args()

    targets = {"llms.txt": build_llms_txt(), "llms-full.txt": build_llms_full_txt()}
    failed = False
    for name, content in targets.items():
        path = REPO / name
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != content:
                print(f"llms drift: {name}（重跑 python3 tools/gen_llms.py 更新）")
                failed = True
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {name}（{len(content)} bytes）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
