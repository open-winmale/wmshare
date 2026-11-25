"""pdf_doc 读面参数预检：空参必须本地 UsageError，不打上游。

2026-11-24 数据质量审计把空 kwargs 的 read_markdown/read_text 记成
「组合面 ok=False」，实为调用方参数不全（上游返回 not_found）。门面补
参数前置校验后，这类误用以 UsageError(code="params") 暴露，不再消耗 EC
也不污染 ok 语义。
"""
from __future__ import annotations

import pytest

from wmshare.api import FRIENDLY_NAMESPACES
from wmshare.errors import UsageError

PdfApi = FRIENDLY_NAMESPACES["pdf_doc"]


class _NoCall:
    """任何上游调用都应先被参数校验拦住。"""

    def call(self, *args, **kwargs):
        raise AssertionError("参数校验应先于取数")


@pytest.mark.parametrize("method", ["read_text", "read_markdown", "status"])
def test_empty_args_raise_usage_error(method):
    api = PdfApi(_NoCall())
    with pytest.raises(UsageError) as ei:
        getattr(api, method)()
    assert ei.value.code == "params"


def test_read_markdown_accepts_stock_code_only():
    """stock_code 单独即可命中经营评述路径，不应被前置校验误拦。"""

    class _Stub:
        def call(self, *args, **kwargs):
            return {"ok": True, "kwargs": kwargs}

    out = PdfApi(_Stub()).read_markdown(stock_code="600519", period="2024")
    assert out["ok"] is True
    assert out["kwargs"]["stock_code"] == "600519"
