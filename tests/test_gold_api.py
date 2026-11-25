"""金交所现货门面契约（不联网）。

2026-11-25 部署后实测抓到的两个坑，各留一条回归：

1. **symbol 归一不得大写**：`client._canon_symbol` 会把标的名拼后缀并转大写
   （`Au99.99` → `AU99.99.SGE`），而 V2 存储键大小写敏感、实存
   `cn.Au99.99.SGE` → 恒返 0 行。`Client.RAW_SYMBOL_NAMESPACES` 把 gold 域
   排除在裸码归一之外，本测试锁住「下发的字面量保持原大小写」。
2. **过滤必须作用在规范化行上**：脚本侧 `CONFT(CONOF(...), mr.v.date != "")`
   的谓词若读原始行（无 date 字段）会恒假、整表清空。该缺陷在 script 仓
   （`sys/gold/query.xs`），离线无法覆盖，由 `tests/test_live.py::test_gold_bars`
   的「非空」断言守护。
"""

from __future__ import annotations

import copy

import pytest

from wmshare.catalog import load
from wmshare.client import Client


class _Resp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.headers = {}
        self.text = "{}"

    def json(self):
        return self._body


class _CannedSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        if url.endswith("/v1/oauth/token"):
            return _Resp({"data": {"access_token": "tok", "expires_in": 3600}})
        return _Resp({"success": True, "data": {"result": copy.deepcopy(self.result)}})


def make(result):
    s = _CannedSession(result)
    c = Client(base_url="https://t", client_id="i", client_secret="s",
               catalog=load(), session=s)
    return c, s


ROW = {
    "date": "2026-11-24", "symbol": "cn.Au99.99.SGE", "open": 778.0,
    "high": 794.5, "low": 775.4, "close": 777.72, "volume": 10590.78,
    "amount": 8281693385.2, "percent": -0.0047,
}


# ---- 大小写：gold 域的 code 不做裸码归一 ----

@pytest.mark.parametrize("code", ["Au99.99", "Au(T+D)", "Ag(T+D)", "Pt99.95",
                                  "mAu(T+D)", "iAu99.99"])
def test_gold_symbol_case_is_preserved(code):
    c, s = make([ROW])
    c.gold.bars(code, n=1)
    line = s.calls[-1]["json"]["xs_lines"][-1]
    assert f'gold.bars("{code}"' in line, line
    assert code.upper() not in line.replace(code, ""), (
        f"品种码被大写下发：{line}")


def test_gold_query_bars_preserves_case():
    c, s = make([ROW])
    c.gold.query_bars("Au99.99", "2026-11-01", "2026-11-24", 50)
    line = s.calls[-1]["json"]["xs_lines"][-1]
    assert 'gold.query_bars("Au99.99"' in line, line


def test_other_namespaces_still_normalize():
    """排除只针对 gold：其他域仍走裸码归一（600519.SH → 600519）。

    只断言 `_build_call_line` 生成的字面量（不触网、不校验返回）——
    现货桩在个股 volume_amount 不变量下会违例，跨域复用桩会引入假失败。
    """
    c, _ = make([ROW])
    line = c._build_call_line(
        "kline.query_bars",
        [{"name": "sym", "type": "string"},
         {"name": "limit", "type": "int", "default": 120}],
        {"sym": "600519.SH", "limit": 1})
    assert '"600519"' in line, line
    assert "600519.SH" not in line, line
    # 对照：gold 域同名参数保持原样
    gline = c._build_call_line(
        "gold.bars",
        [{"name": "code", "type": "string"},
         {"name": "limit", "type": "int", "default": 60}],
        {"code": "Au99.99", "limit": 1})
    assert "Au99.99" in gline and "AU99.99" not in gline, gline


# ---- 门面返回形态 ----

def test_gold_bars_returns_dataframe_with_expected_columns():
    c, _ = make([ROW])
    df = c.gold.bars("Au99.99", n=1)
    assert list(df.columns) == ["date", "symbol", "open", "high", "low",
                               "close", "volume", "amount", "percent"]
    assert len(df) == 1
    assert df.iloc[0]["close"] == pytest.approx(777.72)


def test_gold_symbols_passthrough():
    c, _ = make([{"code": "Au99.99", "symbol": "cn.Au99.99.SGE",
                  "date": "2026-11-24", "close": 777.72}])
    df = c.gold.symbols()
    assert list(df.columns) == ["code", "symbol", "date", "close"]


def test_raw_symbol_namespaces_only_gold():
    assert Client.RAW_SYMBOL_NAMESPACES == frozenset({"gold"})
