"""OpenAPI spec 结构校验：可被标准工具消费的最低保证 + 与核心接口一一对应。

不只是「生成结果可复现」（那是 test_drift 的职责），这里校验 spec 自身合法性：
版本、路径、operationId 唯一、请求/响应 schema 自洽、鉴权定义、核心接口全覆盖。
"""
import json
import re
from pathlib import Path

from wmshare.api import FRIENDLY_INDEX
from wmshare.catalog import load

SPEC = json.loads((Path(__file__).resolve().parents[1] / "docs" / "openapi.json")
                  .read_text(encoding="utf-8"))
CORE_OPS = {f"{ns}_{m}" for _, ns, m, _, _ in FRIENDLY_INDEX}
CAT = load()


def _operations():
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            yield path, method, op


def test_top_level_shape():
    assert SPEC["openapi"].startswith("3.1")
    assert SPEC["info"]["title"] and SPEC["info"]["version"]
    assert SPEC["servers"] and SPEC["servers"][0]["url"].startswith("https://")
    assert SPEC["paths"]


def test_every_path_is_post_with_operation_id():
    for path, method, op in _operations():
        assert path.startswith("/")
        assert method == "post", f"{path} 非 POST"
        assert op.get("operationId"), f"{path} 缺 operationId"
        assert op.get("summary")
        assert op.get("tags")
        assert "200" in op["responses"]


def test_operation_ids_unique():
    ids = [op["operationId"] for _, _, op in _operations()]
    assert len(ids) == len(set(ids)), "operationId 必须全局唯一"


def test_all_core_interfaces_present():
    ids = {op["operationId"] for _, _, op in _operations()}
    assert CORE_OPS <= ids, f"缺少核心接口操作：{sorted(CORE_OPS - ids)}"


def test_gateway_path_present():
    assert "post" in SPEC["paths"]["/v1/analysis/xs/eval"]
    assert SPEC["paths"]["/v1/analysis/xs/eval"]["post"]["operationId"] == "xs_eval"


def test_request_schemas_self_consistent():
    """每个请求体是 object；required 字段必须都在 properties 中。

    例外以目录合同为准：底层目录函数零参数的核心接口（如 cbond.latest_quotes /
    workout.board / indices.keys）请求体允许空 properties；有参接口不得为空。
    """
    underlying_by_op = {f"{ns}_{m}": u for _, ns, m, _, u in FRIENDLY_INDEX}
    for path, _, op in _operations():
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert schema["type"] == "object", f"{path} 请求体非 object"
        props = schema.get("properties") or {}
        if not props:
            fn_key = underlying_by_op.get(op["operationId"], "").split("[")[0]
            assert re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", fn_key or ""), \
                f"{path} 请求体无参数且底层不可回溯目录函数"
            fn = CAT.function(fn_key)
            params = fn.get("params") or CAT.inventory_params(fn_key)
            assert not params, \
                f"{path} 请求体无参数，但目录函数 {fn_key} 声明了 {len(params)} 个参数"
        for name in schema.get("required") or []:
            assert name in props, f"{path} required {name} 不在 properties 中"


def test_response_schemas_are_objects_or_arrays():
    for path, _, op in _operations():
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema.get("type", "object") in {"object", "array"}, f"{path} 响应 schema 异常"


def test_security_scheme_defined():
    schemes = SPEC["components"]["securitySchemes"]
    assert schemes["bearerAuth"]["type"] == "http"
    assert schemes["bearerAuth"]["scheme"] == "bearer"


def test_spec_is_plain_json_no_external_refs():
    """spec 不依赖外部 $ref（可离线导入 Apifox/Postman）。"""
    text = json.dumps(SPEC)
    assert '"$ref"' not in text
    assert "externalValue" not in text
