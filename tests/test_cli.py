"""`wmshare` 主命令测试：四动词、call 透传、参数归一、旗标继承、离线夹具驱动。

离线路径统一注入回放夹具客户端（tests/replay_client），真实数据路径不在此测
（与 live 测试同一门槛）；旗标继承是实测踩过的坑——子 parser 的非 SUPPRESS
default 会覆盖顶层解析值，这里前后双位置各测一遍防回退。
"""
from __future__ import annotations

import json

import pytest

from wmshare import cli


def _run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def replay_cli(monkeypatch):
    """把 _build_client 打桩为回放夹具客户端（离线、零网络）。"""
    from fake_client import fake_client

    monkeypatch.setattr(cli, "_build_client",
                        lambda args: (fake_client(), "replay（离线快照，非实时）"))


# ---- 帮助与旗标继承 ----

def test_help_and_no_command_prints_usage(capsys):
    code, out, _ = _run([], capsys)
    assert code == 0
    assert "screen" in out and "cbond" in out


def test_store_true_flag_before_and_after_subcommand(replay_cli, capsys):
    """store_true 旗标放子命令前后必须等价：子 parser 的非 SUPPRESS default 曾把
    顶层解析值覆盖回 False，静默改写客户端选择（实测踩过）。--demo 已随 3.0.0
    移除，同一机制由 --json / --anonymous 继续守。"""
    for argv in (["--json", "index", "trend", "--keys", "index.hs300"],
                 ["index", "--json", "trend", "--keys", "index.hs300"]):
        code, out, err = _run(argv, capsys)
        assert code == 0, err
        assert "replay（离线快照" in err
        rows = json.loads(out.strip().splitlines()[-1])
        assert rows[0]["key"] == "index.hs300"


# ---- index 动词 ----

def test_index_trend_replay_writes_md(replay_cli, capsys):
    code, out, err = _run(
        ["index", "trend", "--keys", "index.hs300,index.csi500", "--out",
         "/tmp/wm_test_trend.md"], capsys)
    assert code == 0, err
    text = open("/tmp/wm_test_trend.md", encoding="utf-8").read()
    assert "指数估值分位" in text and "index.hs300" in text
    assert "pe_pct" in text


def test_index_trend_json_and_stdout_table(replay_cli, capsys):
    code, out, err = _run(["--json", "index", "trend",
                           "--keys", "index.hs300"], capsys)
    assert code == 0, err
    rows = json.loads(out.strip().splitlines()[-1])
    assert rows[0]["key"] == "index.hs300"


def test_index_trend_all_keys_missing_exits_2(capsys, monkeypatch):
    """全部键缓存未命中：逐键提示并退出 2（回放罐头对未知键也返数据，须打桩）。"""
    import types as _t

    monkeypatch.setattr(cli, "_build_client",
                        lambda args: (_t.SimpleNamespace(
                            index=_t.SimpleNamespace(
                                universe_keys=lambda group="broad": ["index.a", "index.b"],
                                trend=lambda key, window: {
                                    "ok": False, "as_of": None, "data": None,
                                    "meta": {"cache": "miss"}}),
                        ), "stub"))
    code, _, err = _run(["index", "trend"], capsys)
    assert code == 2
    assert "无可用键" in err and "index.a" in err


# ---- call 动词 ----

def test_call_passes_through_with_type_casting(replay_cli, capsys):
    code, out, err = _run(["--json", "call", "kline.query_bars",
                           "sym=600519", "limit=3"], capsys)
    assert code == 0, err
    rows = json.loads(out.strip().splitlines()[-1])
    assert isinstance(rows, list) and len(rows) == 3


def test_call_unknown_param_lists_legal_set(replay_cli, capsys):
    code, _, err = _run(["call", "kline.query_bars", "sym=600519",
                         "bogus=1"], capsys)
    assert code == 2
    assert "bogus" in err and "limit" in err and "sym" in err


def test_call_bad_int_reports_target_type(replay_cli, capsys):
    code, _, err = _run(["call", "kline.query_bars", "sym=600519",
                         "limit=abc"], capsys)
    assert code == 2
    assert "int" in err


def test_call_unknown_function_is_catalog_error(replay_cli, capsys):
    code, _, err = _run(["call", "no_such.function"], capsys)
    assert code == 2
    assert "未知函数" in err


# ---- screen 动词：匿名态成本警告 ----

def test_screen_fields_on_anon_client_warns_but_proceeds(capsys, monkeypatch):
    """匿名态 fields 重列打成本警告但不阻断（能力对标，只做透明提示）。"""
    import types as _t
    from wmshare import WmshareError

    calls = {}

    def _fake_query(where, **kw):
        calls["fields"] = kw.get("fields")
        raise WmshareError("停止于桩", code="params")

    fake = _t.SimpleNamespace(
        anon_credentials_path="/tmp/anon.env",
        screener=_t.SimpleNamespace(query=_fake_query))
    monkeypatch.setattr(cli, "_build_client", lambda args: (fake, "stub"))
    code, _, err = _run(["screen", "--where", "$X > 0.1", "--fields", "$X",
                         "--out", "/tmp/wm_anon.md"], capsys)
    assert calls["fields"] == ["$X"]
    assert "50 万 EC" in err


# ---- income / cbond：回放夹具未拍摄面显式降级 ----

def test_income_unbacked_face_degrades(replay_cli, capsys):
    code, _, err = _run(["income"], capsys)
    assert code == 2
    assert "replay_unsupported" in err


def test_cbond_unbacked_face_degrades(replay_cli, capsys):
    code, _, err = _run(["cbond", "daily", "--out", "/tmp/wm_cb"], capsys)
    assert code == 2
    assert "replay_unsupported" in err


# ---- 参数归一单元 ----

def test_cast_params_types():
    decl = [{"name": "a", "type": "int"}, {"name": "b", "type": "float"},
            {"name": "c", "type": "bool"}, {"name": "d", "type": "string"}]
    out = cli._cast_params(decl, {"a": "5", "b": "0.5", "c": "true", "d": "D"})
    assert out == {"a": 5, "b": 0.5, "c": True, "d": "D"}


def test_setup_conflicting_secret_flags(capsys):
    code = cli.main(["setup", "--client-id", "i", "--client-secret", "s",
                     "--client-secret-stdin"])
    assert code == 2
