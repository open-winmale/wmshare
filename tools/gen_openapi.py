#!/usr/bin/env python3
"""Generate docs/openapi.json (OpenAPI 3.1) + docs/swagger.html from the friendly API layer.

核心接口（友好层 44 个方法）映射为语义化路径 POST /{ns}/{method}：参数 schema 来自方法
签名，说明来自 docstring，返回 schema 来自目录 returns_shape；另含一条真实网关路径
POST /v1/analysis/xs/eval。确定性输出；`--check` 校验磁盘文件一致（漂移门禁，进
tests/test_drift.py）。docs/swagger.html 为单文件 Swagger UI（CDN），亦可导入
Apifox / Postman 等工具。

Usage:
  python3 tools/gen_openapi.py          # write docs/openapi.json + docs/swagger.html
  python3 tools/gen_openapi.py --check  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wmshare  # noqa: E402
from _introspect import (  # noqa: E402
    FALLBACK_RETURNS, method_doc, method_params, return_shape_for, shape_to_schema,
    underlying_fn,
)
from wmshare.api import FRIENDLY_INDEX, FRIENDLY_NAMESPACES  # noqa: E402
from wmshare.catalog import load  # noqa: E402

SPEC_PATH = REPO / "docs" / "openapi.json"
HTML_PATH = REPO / "docs" / "swagger.html"

CATEGORY_CN = {"market": "市场行情", "fundamentals": "财务基本面",
               "disclosure": "信息披露", "reference": "参考数据"}
# 独立 tag 覆盖：宏观是独立数据域（market.macro），不宜挂在「市场行情」大 tag 下被能力列表误读
NS_TAG_OVERRIDE = {"macro": "宏观数据"}

SWAGGER_HTML = """<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>wmshare 数据 API · Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.SwaggerUIBundle({
      spec: __SPEC__,
      dom_id: "#swagger-ui",
      persistAuthorization: true,
    });
  </script>
</body>
</html>
"""


def render_swagger(spec: dict) -> str:
    """把 spec 内联进 HTML，避免 file:// 下 fetch 相对 JSON 被 CORS 拦截。"""
    data = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    return SWAGGER_HTML.replace("__SPEC__", data)


def _core_paths(catalog) -> dict:
    paths: dict = {}
    for category, ns, method, cn, underlying in FRIENDLY_INDEX:
        cls = FRIENDLY_NAMESPACES[ns]
        params = method_params(cls, method)
        summary, body = method_doc(cls, method)
        props = {}
        for p in params:
            prop: dict = {"type": p.json_type}
            if p.desc:
                prop["description"] = p.desc
            props[p.name] = prop
        fn_key = underlying_fn(underlying)
        if fn_key:
            resp = shape_to_schema(return_shape_for(catalog, ns, method, underlying))
            call_note = f"底层目录函数 `{underlying}`"
        else:
            resp = {}
            call_note = underlying
        desc = "、".join(x for x in [body, call_note] if x)
        desc += f"。SDK 调用：`cli.{ns}.{method}(...)`；实际经网关 POST /v1/analysis/xs/eval 执行。"
        paths[f"/{ns}/{method}"] = {"post": {
            "operationId": f"{ns}_{method}",
            "summary": summary or cn,
            "description": desc,
            "tags": [NS_TAG_OVERRIDE.get(ns, CATEGORY_CN[category])],
            "requestBody": {
                "required": any(p.required for p in params),
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": props,
                    "required": [p.name for p in params if p.required],
                }}},
            },
            "responses": {"200": {
                "description": FALLBACK_RETURNS.get((ns, method), "调用成功"),
                "content": {"application/json": {"schema": resp or {"type": "object"}}},
            }},
        }}
    return paths


def _gateway_path() -> dict:
    return {"post": {
        "operationId": "xs_eval",
        "summary": "取数网关（SDK 实际 HTTP 入口）",
        "description": (
            "wmshare SDK 全部取数的统一网关：携带 OAuth Bearer 令牌，提交 XS 脚本行，"
            "mode=call 时顶层 return 值位于 data.result。一般不直接使用，"
            "经 SDK 核心接口调用。"),
        "tags": ["网关"],
        "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object",
            "required": ["symbol", "xs_lines"],
            "properties": {
                "symbol": {"type": "string", "description": "标的代码（6 位裸码）", "example": "600519"},
                "xs_lines": {"type": "array", "items": {"type": "string"},
                              "description": "XS 脚本行，最后一行 return 结果"},
                "args": {"type": "object", "description": "执行参数（默认含 print.plain=true）"},
                "script_files": {"type": "object"},
                "market": {"type": "string", "description": "市场，缺省 cn"},
                "mode": {"type": "string", "enum": ["call"], "description": "固定 call"},
            },
        }}}},
        "responses": {"200": {
            "description": "success=true；data.result 为脚本顶层 return 值",
            "content": {"application/json": {"schema": {"type": "object", "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "object", "properties": {"result": {}}},
                "error": {"type": "object"},
            }}}},
        }},
    }}


def build() -> dict:
    catalog = load()
    paths: dict = _core_paths(catalog)
    paths["/v1/analysis/xs/eval"] = _gateway_path()
    metric_total = catalog.stats()["metric_catalog_total"]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "wmshare 数据 API",
            "version": wmshare.__version__,
            "description": (
                "覆盖 A 股、港股、美股的财经数据核心接口（Python SDK，`pip install wmshare`；`import wmshare`）。"
                "凭证必填：在开放平台（open.winmale.com）获取 client_id/api-key；"
                "遇到 401/403/429 错误消息即完整的申请与配置指引。"
                "覆盖行情 K 线（不复权/前复权/后复权、盘中、分时、ETF、指数）、三大报表"
                "（多期、合并 vs 母公司、树视图、新旧会计准则归一）、分红（历史/DPS/窗口/TTM 率）、"
                "公告与业绩披露、资金流与指标层。"
                f"平台指标经 /indicator/get、/indicator/metrics 按指标代码寻址，"
                f"全量 {metric_total} 个指标代码随包内置目录分发（分组清单见 docs/API.md）。"),
            "license": {"name": "BSD-3-Clause",
                         "url": "https://github.com/open-winmale/wmshare/blob/main/LICENSE"},
        },
        "servers": [{"url": "https://api.winmale.com", "description": "生产网关"}],
        "tags": [{"name": cn} for cn in CATEGORY_CN.values()]
                 + [{"name": "宏观数据"}, {"name": "网关"}],
        "security": [{"bearerAuth": []}],
        "components": {"securitySchemes": {"bearerAuth": {
            "type": "http", "scheme": "bearer",
            "description": "OAuth2 client_credentials：POST /v1/oauth/token "
                           "（grant_type=client_credentials, client_id, client_secret）换取访问令牌",
        }}},
        "paths": paths,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    spec_doc = build()
    spec = json.dumps(spec_doc, ensure_ascii=False, indent=2) + "\n"
    html = render_swagger(spec_doc)
    drift: list[str] = []
    if args.check:
        if not SPEC_PATH.is_file() or SPEC_PATH.read_text(encoding="utf-8") != spec:
            drift.append(str(SPEC_PATH.relative_to(REPO)))
        if not HTML_PATH.is_file() or HTML_PATH.read_text(encoding="utf-8") != html:
            drift.append(str(HTML_PATH.relative_to(REPO)))
        if drift:
            print("gen_openapi drift:", ", ".join(drift), file=sys.stderr)
            return 1
        print("gen_openapi ok")
        return 0
    SPEC_PATH.write_text(spec, encoding="utf-8")
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"wrote {SPEC_PATH.relative_to(REPO)} ({len(spec)} bytes) + swagger.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
