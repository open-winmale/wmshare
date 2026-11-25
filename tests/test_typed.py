"""类型化门面（生成层）测试：注册表完整性、防编造、委托翻译、默认值与上限（mock 传输）。"""
import inspect

import pytest

from wmshare.api import FRIENDLY_NAMESPACES, GENERATED_NAMESPACES
from wmshare.catalog import INTERNAL_CATALOG_NS, load
from wmshare.client import Client, WmshareError


class FakeSession:
    def __init__(self):
        self.calls = []
        self.token_count = 0
        self.eval_result = {"ok": True}

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        class R:
            status_code = 200
            text = "{}"
            def raise_for_status(self):
                pass
            def json(self):
                if url.endswith("/v1/oauth/token"):
                    self._cls.token_count += 1
                    return {"data": {"access_token": "tok-1", "expires_in": 3600}}
                return {"success": True, "data": {"result": self._cls.eval_result}}
        R._cls = self
        return R()


@pytest.fixture()
def cli():
    return Client(base_url="https://t.example", client_id="i", client_secret="s",
                  catalog=load(), session=FakeSession())


def last_xs(c: Client) -> list[str]:
    return [x for x in c.session.calls if x["url"].endswith("/xs/eval")][-1]["json"]["xs_lines"]


def _all_catalog_fns() -> set[str]:
    cat = load()
    return {n for names in cat.functions_by_domain().values() for n in names}


def test_namespaces_cover_catalog():
    cat = load()
    for ns in cat.namespaces():
        if ns in INTERNAL_CATALOG_NS:
            # 内部命名空间整域不进类型化门面（实现细节，只经友好门面暴露）
            assert ns not in GENERATED_NAMESPACES, f"内部命名空间 {ns} 不该有门面"
            continue
        assert ns in GENERATED_NAMESPACES, f"命名空间 {ns} 缺少类型化门面"


def test_methods_match_catalog_both_ways():
    fns = _all_catalog_fns()
    for ns, cls in GENERATED_NAMESPACES.items():
        for name, _m in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            assert f"{ns}.{name}" in fns, f"生成方法 {ns}.{name} 不在目录中（防编造）"
    for full in fns:
        ns, short = full.split(".", 1)
        if ns in FRIENDLY_NAMESPACES:
            continue  # 友好层接管，生成层仍生成但被遮蔽
        if ns in INTERNAL_CATALOG_NS:
            # 内部命名空间整域不进类型化门面（实现细节，经友好门面/cli.call 用）
            assert ns not in GENERATED_NAMESPACES, f"内部命名空间 {ns} 不该生成门面"
            continue
        if load().function(full).get("internal"):
            assert not hasattr(GENERATED_NAMESPACES[ns], short), f"{full} 应退出类型化门面"
            continue
        assert hasattr(GENERATED_NAMESPACES[ns], short), f"目录函数 {full} 缺少生成方法"


def test_typed_dispatch(cli):
    cli.bonus.snapshot_yield_ttm(sym="600519")
    assert last_xs(cli) == ['return bonus.snapshot_yield_ttm("600519")']
    # 内部命名空间（rptdom）不经类型化门面，底层直调仍生成正确的 require + 调用
    cli.call("rptdom.statement", sym="600519", domain="fin.income_statement", opts={"n": 5})
    xs = last_xs(cli)
    assert xs[0] == 'xs.require("sys/rptdom/init.xs")'
    assert xs[-1] == 'return rptdom.statement("600519", "fin.income_statement", {"n": 5})'
    with pytest.raises(AttributeError, match="内部实现"):
        cli.rptdom


def test_typed_optional_param_omitted(cli):
    cli.bonus.query_list(sym="600519")
    assert last_xs(cli) == ['__r := bonus.query_list("600519")',
                            "return bonus.fmt_maps(__r)"]  # 规范化输出扁平行
    cli.bonus.query_list(sym="600519", limit=5)
    assert last_xs(cli) == ['__r := bonus.query_list("600519", 5)',
                            "return bonus.fmt_maps(__r)"]


def test_typed_uses_curated_defaults_and_normalize(cli):
    # kline 被友好层遮蔽，直接实例化生成类验证：目录默认 limit=120 与 normalize_with 均生效
    ns = GENERATED_NAMESPACES["kline"](cli)
    ns.query_bars(sym="600519")
    assert last_xs(cli) == ['__r := kline.query_bars("600519", 120)',
                            "return kline.fmt_maps(__r)"]


def test_typed_raw_passthrough(cli):
    cli.bonus.query_list(sym="600519", limit=5, _raw=True)
    assert last_xs(cli) == ['return bonus.query_list("600519", 5)']


def test_typed_max_limit_guard(cli):
    with pytest.raises(WmshareError, match="超过单次请求上限 500"):
        cli.bonus.query_list(sym="600519", limit=9999)


def test_friendly_still_wins(cli):
    # 友好层优先：kline 命名空间解析到手写类
    assert type(cli.kline).__name__ == "KlineApi"
    # 非友好命名空间解析到生成类
    assert type(cli.bonus).__name__ == "BonusNS"
