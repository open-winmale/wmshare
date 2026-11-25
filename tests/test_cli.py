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


# ---- 客户端构造与 screen 动词：免注册访问 ----

def _clean_env(monkeypatch, tmp_path):
    """隔离本机凭证：清空环境变量与凭证文件，让 from_env 落到免注册访问。"""
    monkeypatch.setenv("WMSHARE_CREDENTIALS", str(tmp_path / "absent.env"))
    monkeypatch.delenv("WMSHARE_DISABLE_ANON", raising=False)
    for key in ("WMSHARE_CLIENT_ID", "WMSHARE_CLIENT_SECRET",
                "OPEN_PLATFORM_CLIENT_ID", "OPEN_PLATFORM_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)


def _call_args(*flags):
    return cli.parser().parse_args([*flags, "call", "kline.query_bars", "sym=600519"])


def test_build_client_without_credentials_is_public_pool(monkeypatch, tmp_path, capsys):
    """无凭证：from_env 落到免注册访问，来源提示如实说明（不提「匿名」「一次性额度」）。"""
    _clean_env(monkeypatch, tmp_path)
    client, source = cli._build_client(_call_args())
    try:
        assert client.auth_mode == "public_pool" and source.startswith("public_pool")
    finally:
        client.close()
    err = capsys.readouterr().err
    assert "免注册免费试用" in err and "匿名" not in err


def test_build_client_with_credentials_prefers_them(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WMSHARE_CLIENT_ID", "wm_open_test")
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "sec")
    client, source = cli._build_client(_call_args())
    try:
        assert client.auth_mode == "credentials" and source.startswith("credentials")
    finally:
        client.close()


def test_build_client_anonymous_flag_forces_public_pool(monkeypatch, tmp_path):
    """--anonymous：已配置凭证仍强制免注册（旧语义保留，3.3.0 起不再申领凭据）。"""
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WMSHARE_CLIENT_ID", "wm_open_test")
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "sec")
    # 旗标放在子命令前后必须等价（store_true 继承，见上方旗标继承用例）
    for args in (_call_args("--anonymous"), cli.parser().parse_args(
            ["call", "--anonymous", "kline.query_bars", "sym=600519"])):
        client, source = cli._build_client(args)
        try:
            assert client.auth_mode == "public_pool" and source.startswith("public_pool")
        finally:
            client.close()


def test_build_client_disable_anon_raises_missing_credentials(monkeypatch, tmp_path):
    """WMSHARE_DISABLE_ANON=1：恢复「缺少凭证」报错（迁移逃生口，语义不变）。"""
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WMSHARE_DISABLE_ANON", "1")
    with pytest.raises(cli.wmshare.AuthError, match="缺少凭证"):
        cli._build_client(_call_args())


def test_screen_fields_on_public_client_warns_but_proceeds(capsys, monkeypatch):
    """免注册访问下 fields 重列打成本警告但不阻断（能力对标，只做透明提示）。

    警告不写具体额度数字：免注册额度由服务端按来源网络统一核算，客户端不知道、
    也不该编一个数（旧文案写死的「50 万 EC」是匿名凭据时代的口径）。"""
    import types as _t
    from wmshare import WmshareError

    calls = {}

    def _fake_query(where, **kw):
        calls["fields"] = kw.get("fields")
        raise WmshareError("停止于桩", code="params")

    fake = _t.SimpleNamespace(
        auth_mode="public_pool",
        screener=_t.SimpleNamespace(query=_fake_query))
    monkeypatch.setattr(cli, "_build_client", lambda args: (fake, "stub"))
    code, _, err = _run(["screen", "--where", "$X > 0.1", "--fields", "$X",
                         "--out", "/tmp/wm_public_pool.md"], capsys)
    assert calls["fields"] == ["$X"]
    warning = err.split("警告", 1)[1]
    assert "免注册" in warning and "50 万 EC" not in warning


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
