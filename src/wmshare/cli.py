"""``wmshare`` 主命令：一次调用 → 一份带口径的成品文件，不用写 Python。

安装即得（与 ``wmshare-mcp`` 并列的 console script）。四个任务动词把
「结论级接口」压成一条 shell，``call`` 透传其余目录函数；
``setup``/``doctor`` 复用 MCP CLI 同款实现（同一份凭证文件）。

::

    wmshare screen --where "$ROE_TTM_LAST > 0.15" --out roe.xlsx
    wmshare income --top-n 20 --out ./income/
    wmshare index trend --keys index.hs300,index.csi500 --out trend.md
    wmshare cbond daily --out ./cb/
    wmshare call kline.query_bars sym=600519 limit=30 --json

客户端构造顺序（首个成功者生效）：``--demo`` 离线快照 → ``--anonymous``
免注册匿名试用 → 环境变量/凭证文件 → 无凭证时自动回退匿名（服务端未开放
则给注册指引）。匿名额度是一次性 50 万 EC，本命令**不砍量**——只对
``screen --fields`` 这类首跑物化可达 ~60 万 EC 的用法打成本警告。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import wmshare
from wmshare import export as _export

__all__ = ["main", "parser"]

_ANON_HINT = "[wmshare] 到 https://open.winmale.com 注册免费账号获取稳定额度"
_DEMO_HINT = "[wmshare] 换真实数据：wmshare --anonymous <命令> 或配置凭证后重跑"


def _common_flags(target: argparse.ArgumentParser, *, top: bool) -> argparse.ArgumentParser:
    """任务动词共享的全局旗标（顶层与子命令层各挂一份）。

    子命令层一律 ``default=argparse.SUPPRESS``：argparse 的子 parser 复用顶层
    namespace 并先填充全部 defaults——非 SUPPRESS 的 store_true 隐含 False，
    会把顶层解析出的 ``--demo=True`` 覆盖回 False（实测踩过：旗标放在子命令
    前却走了付费凭据客户端）。SUPPRESS 让「子位置未给出」时不写该属性。
    """
    demo: dict[str, Any] = dict(action="store_true", help="离线演示快照（零凭证、非实时）")
    anon: dict[str, Any] = dict(action="store_true", help="免注册匿名试用（一次性小配额）")
    market: dict[str, Any] = dict(help="市场 cn/hk/us（默认 cn）")
    js: dict[str, Any] = dict(action="store_true",
                              help="打印原始返回（JSON）；与 --out 组合时落盘照常")
    if not top:
        for kw in (demo, anon, js):
            kw["default"] = argparse.SUPPRESS
        market["default"] = argparse.SUPPRESS
    target.add_argument("--demo", **demo)
    target.add_argument("--anonymous", **anon)
    target.add_argument("--market", **market)
    target.add_argument("--json", **js)
    return target


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wmshare",
        description="wmshare 财经数据 CLI：一次调用出成品文件（md/csv/xlsx/png）")
    _common_flags(p, top=True)          # 顶层（子命令前）
    sub = p.add_subparsers(dest="command")

    def task(name: str, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, parents=[_common_flags(
            argparse.ArgumentParser(add_help=False), top=False)])
        return sp

    sp = task("screen", "全市场条件选股（screener.query）")
    sp.add_argument("--where", required=True,
                    help="XS 布尔表达式，$码须在目录内（cat.search 查）")
    sp.add_argument("--order", default=None, help="排序指标码")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--fields", default=None, help="额外列（逗号分隔 $码）")
    sp.add_argument("--asc", action="store_true", help="升序（默认降序）")
    sp.add_argument("--out", default=None, help="落盘路径（.md/.csv/.xlsx）")

    ip = task("income", "收息排行/诊断/日历/拆解（dividend.*）")
    ip.add_argument("--top-n", type=int, default=20, help="排行条数")
    ip.add_argument("--grade", default=None, help="评级过滤（strong/mid/weak）")
    ip.add_argument("--industry", default=None, help="行业过滤")
    ip.add_argument("--min-yield", type=float, default=None, help="最低股息率（小数）")
    ip.add_argument("--diagnose", default=None, help="诊断标的（逗号分隔）")
    ip.add_argument("--calendar", nargs=2, metavar=("FROM", "TO"), default=None,
                    help="分红日历区间 YYYY-MM-DD YYYY-MM-DD")
    ip.add_argument("--decomp", default=None, help="持有收益拆解标的（逗号分隔，≤10）")
    ip.add_argument("--years", type=int, default=5, choices=(3, 5, 10), help="拆解年限")
    ip.add_argument("--out", default=None, help="落盘目录（write_bundle + manifest.json）")

    xp = task("index", "指数估值")
    xsub = xp.add_subparsers(dest="index_command", required=True)
    xt = xsub.add_parser("trend", help="PE/PB 历史分位（index.trend）",
                         parents=[_common_flags(
                             argparse.ArgumentParser(add_help=False), top=False)])
    xt.add_argument("--keys", default=None, help="指数键（逗号分隔；缺省按 --group 全组）")
    xt.add_argument("--group", default="broad",
                    choices=("broad", "industry", "dividend", "all"),
                    help="缺省键组")
    xt.add_argument("--window", default="5y", choices=("3y", "5y", "10y"))
    xt.add_argument("--out", default=None, help="落盘路径（.md/.csv/.xlsx）")

    cp = task("cbond", "可转债日更成品链")
    csub = cp.add_subparsers(dest="cbond_command", required=True)
    cd = csub.add_parser("daily", help="daily → article → figures 一条链",
                         parents=[_common_flags(
                             argparse.ArgumentParser(add_help=False), top=False)])
    cd.add_argument("--top-n", type=int, default=20)
    cd.add_argument("--no-article", action="store_true", help="只出事实包摘要，不成稿")
    cd.add_argument("--no-figures", action="store_true", help="跳过出图")
    cd.add_argument("--out", required=True, help="落盘目录")

    tp = task("call", "透传目录函数：wmshare call kline.query_bars sym=600519")
    tp.add_argument("target", help="目录函数名（cat.function 可查）")
    tp.add_argument("params", nargs="*", help="参数 k=v（类型按目录声明归一）")
    tp.add_argument("--out", default=None, help="落盘路径（.md/.csv/.xlsx）")

    setup_p = sub.add_parser("setup", help="写入凭证（同 wmshare-mcp setup 的文件与权限）")
    setup_p.add_argument("--client-id", required=True)
    setup_p.add_argument("--client-secret", help="不推荐：会进入 shell history")
    setup_p.add_argument("--client-secret-stdin", action="store_true",
                         help="从 stdin 读取 API Key（推荐）")
    setup_p.add_argument("--market", default="cn")
    setup_p.add_argument("--credentials-path", default=None)

    sub.add_parser("doctor", help="自检凭证/目录/客户端")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            return _setup(args)
        if args.command == "doctor":
            from wmshare.mcp.cli import _doctor
            return _doctor(args)  # type: ignore[arg-type]
        if args.command is None:
            parser().print_help()
            return 0
        cli, source = _build_client(args)
        print(f"[wmshare] 客户端：{source}", file=sys.stderr)
        handlers = {
            "screen": _cmd_screen, "income": _cmd_income,
            "index": _cmd_index, "cbond": _cmd_cbond, "call": _cmd_call,
        }
        return handlers[args.command](cli, args)
    except wmshare.WmshareError as e:
        print(f"[wmshare] {type(e).__name__} ({e.code}): {e}", file=sys.stderr)
        if e.code == "demo_unsupported":
            print(_DEMO_HINT, file=sys.stderr)
        elif e.code.startswith("anon_"):
            print(_ANON_HINT, file=sys.stderr)
        return 2
    except (ValueError, OSError) as e:
        print(f"[wmshare] {e}", file=sys.stderr)
        return 2


# ---- 客户端构造：demo → anonymous → from_env，首个成功者生效 ----

def _build_client(args: argparse.Namespace) -> tuple[Any, str]:
    if args.demo:
        return wmshare.demo_client(), "demo（离线快照，非实时）"
    if args.anonymous:
        cli = wmshare.Client.anonymous(market=args.market)
        return cli, "anonymous（匿名试用，一次性小配额）"
    try:
        return wmshare.Client.from_env(market=args.market), "credentials（付费凭据）"
    except wmshare.AuthError as e:
        if e.code != "config":
            raise
        # 无凭证自动回退匿名：让首次真实数据发生在注册之前
        try:
            cli = wmshare.Client.anonymous(market=args.market)
            print("[wmshare] 未配置凭证，已自动回退匿名试用（一次性 50 万 EC）",
                  file=sys.stderr)
            return cli, "anonymous（自动回退；注册免费账号可获长期额度）"
        except wmshare.AuthError as anon_err:
            raise wmshare.AuthError(
                f"凭证缺失且匿名试用不可用：{anon_err}\n{e}", code="config") from None


def _is_anon(cli: Any) -> bool:
    return getattr(cli, "anon_credentials_path", None) is not None


# ---- 动词实现 ----

def _cmd_screen(cli: Any, args: argparse.Namespace) -> int:
    from wmshare.api import _rows

    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    if fields and _is_anon(cli):
        print("[wmshare] 警告：匿名额度一次性 50 万 EC；fields 重列首跑物化实测可达"
              "~60 万 EC，可能直接耗尽配额（介意请注册免费账号后重跑）", file=sys.stderr)
    res = cli.screener.query(args.where, order=args.order, desc=not args.asc,
                             limit=args.limit, offset=args.offset, fields=fields)
    data = _unwrap(res) or {}
    rows = _rows(data.get("rows")) if isinstance(data, dict) else _rows(res)
    count = data.get("count") if isinstance(data, dict) else None
    if count is not None:
        print(f"全市场命中 {count} 只（展示前 {len(rows)} 行）")
    return _emit(cli, res, args, title="全市场条件选股")


def _cmd_income(cli: Any, args: argparse.Namespace) -> int:
    res = cli.dividend.rating(top_n=args.top_n, grade=args.grade,
                              industry=args.industry, min_yield=args.min_yield)
    if isinstance(res, dict) and res.get("ok") is False:
        print(f"[wmshare] 榜单未就绪（cron 物化 16:50/19:40，稍后重试勿现场重算）："
              f"{json.dumps(res.get('meta') or {}, ensure_ascii=False)}", file=sys.stderr)
    reports: dict[str, Any] = {"rating.md": res}
    if args.diagnose:
        syms = [s.strip() for s in args.diagnose.split(",") if s.strip()]
        reports["diagnose.md"] = cli.dividend.diagnose(syms)
    if args.calendar:
        reports["calendar.md"] = cli.dividend.calendar(args.calendar[0], args.calendar[1])
    if args.decomp:
        syms = [s.strip() for s in args.decomp.split(",") if s.strip()]
        reports["decomp.md"] = cli.dividend.decomp(syms, years=args.years)
    if not args.out:
        _print_table(res, "收息排行（dividend.rating）")
        return 0
    written = _export.write_bundle(reports, args.out)
    print(f"已写入 {len(written)} 个文件 → {args.out}（含 manifest.json）")
    return 0


def _cmd_index(cli: Any, args: argparse.Namespace) -> int:
    from wmshare.api import _rows

    keys = ([k.strip() for k in args.keys.split(",") if k.strip()]
            if args.keys else list(cli.index.universe_keys(args.group)))
    rows_out: list[dict] = []
    for key in keys:
        t = cli.index.trend(key, args.window)
        if isinstance(t, dict) and t.get("ok") is False:
            print(f"[wmshare] {key}: 缓存未命中，稍后重试（不伪造数值）", file=sys.stderr)
            continue
        data = _unwrap(t)
        if not isinstance(data, dict):
            continue
        points = _rows(data.get("points"))
        last = points[-1] if isinstance(points, list) and points else {}
        row: dict[str, Any] = {"key": key, "as_of": data.get("as_of")}
        row.update({k: data.get(k) for k in ("pe", "pb", "pe_pct", "pb_pct",
                                             "pe_pct_window", "pe_missing")})
        if isinstance(last, dict) and last.get("date"):
            row["last_date"] = last.get("date")
        rows_out.append(row)
    if not rows_out:
        print("[wmshare] 无可用键（全部缓存未命中或演示快照不含）", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows_out, ensure_ascii=False))
    return _emit(cli, rows_out, args,
                 title=f"指数估值分位（window={args.window}）")


def _cmd_cbond(cli: Any, args: argparse.Namespace) -> int:
    payload = cli.cbond.daily(top_n=args.top_n)
    cov = payload.get("coverage") or {}
    print(f"快照日 {payload.get('data_date')} · 请求 {cov.get('requests_made')}/"
          f"{cov.get('budget')} 次 · 过闸 {len(payload.get('top') or [])} 只")
    items: dict[str, Any] = {"facts.md": _facts_summary(payload)}
    if not args.no_article:
        art = cli.cbond.article(payload)
        items[f"day{payload.get('data_date')}_cb_article.md"] = art["source"]
        print(f"成稿 {len(art['source'])} 字符")
    if not args.no_figures:
        figs = cli.cbond.figures(payload, args.out)
        print(f"出图 {len(figs)} 张：{', '.join(sorted(figs))}")
    written = _export.write_bundle(items, args.out)
    print(f"落盘 {len(written)} 个文件 → {args.out}（含 manifest.json）")
    return 0


def _cmd_call(cli: Any, args: argparse.Namespace) -> int:
    from wmshare.errors import UsageError

    kv: dict[str, str] = {}
    for item in args.params:
        if "=" not in item:
            raise UsageError(f"参数须为 k=v 形式，收到 {item!r}", code="params")
        key, _, v = item.partition("=")
        kv[key.strip()] = v
    meta = wmshare.load().function(args.target)
    kwargs = _cast_params(meta.get("params") or [], kv)
    res = cli.call(args.target, **kwargs)
    if args.json:
        print(json.dumps(_j(res), ensure_ascii=False))
    return _emit(cli, res, args, title=args.target)


# ---- setup：复用 mcp.cli._setup（同一凭证文件、同一 0600 原子写） ----

def _setup(args: argparse.Namespace) -> int:
    from wmshare.mcp.cli import _setup as mcp_setup
    from wmshare.mcp.constants import MARKETS

    if args.client_secret_stdin and args.client_secret:
        raise ValueError("--client-secret-stdin 与 --client-secret 只能二选一")
    market = args.market or "cn"
    if market not in MARKETS:
        raise ValueError(f"market 只支持 {'/'.join(MARKETS)}")
    args.market = market
    return mcp_setup(args)  # type: ignore[arg-type]  # 字段与 mcp.cli 同名同义


# ---- 参数归一与输出 ----

def _cast_params(decl: list[dict], kv: dict[str, str]) -> dict[str, Any]:
    from wmshare.errors import UsageError

    types_by_name = {p["name"]: str(p.get("type") or "string").lower() for p in decl}
    unknown = sorted(set(kv) - set(types_by_name))
    if unknown:
        raise UsageError(f"未知参数 {unknown}；该函数的合法参数 {sorted(types_by_name)}",
                         code="params")
    out: dict[str, Any] = {}
    for name, raw in kv.items():
        t = types_by_name[name]
        try:
            if t in ("int", "integer", "long"):
                out[name] = int(raw)
            elif t in ("float", "number", "double", "decimal"):
                out[name] = float(raw)
            elif t in ("bool", "boolean"):
                out[name] = raw.strip().lower() in ("1", "true", "yes", "on")
            else:
                out[name] = raw
        except ValueError:
            raise UsageError(f"参数 {name} 类型应为 {t}，收到 {raw!r}",
                             code="params") from None
    return out


def _unwrap(res: Any) -> Any:
    if isinstance(res, dict) and {"ok", "data"} <= set(res):
        return res.get("data")
    return res


def _facts_summary(payload: dict[str, Any]) -> str:
    import pandas as pd

    pool = (payload.get("facts") or []) + (payload.get("derived") or [])
    rows = [{"id": f.get("id"), "metric": f.get("metric"),
             "value": f.get("value_text"), "unit": f.get("unit"),
             "as_of": f.get("as_of")} for f in pool]
    return _export.to_markdown(
        pd.DataFrame(rows),
        title=f"可转债事实包（{payload.get('data_date')}）",
        notes=["事实分两桶合并展示：facts=头条、derived=派生；每个值可按 sources 复算"])


def _print_table(res: Any, title: str) -> None:
    print(_export.to_markdown(res, title=title, max_rows=20))


def _emit(cli: Any, res: Any, args: argparse.Namespace, *, title: str) -> int:
    """统一出口：--out 落盘；否则（未 --json 时）打印带口径的 Markdown 表。"""
    if args.out:
        path = _export.write(res, args.out, title=title)
        print(f"已写入 {path}")
        return 0
    if not args.json:
        _print_table(res, title)
    return 0


def _j(value: Any) -> Any:
    """DataFrame/行数组/信封 → 可 JSON 序列化。"""
    from wmshare.client import BatchResult

    if isinstance(value, BatchResult):
        return {k: _j(v) for k, v in value.results.items()}
    to_records = getattr(value, "to_dict", None)
    if callable(to_records):
        try:
            return value.to_dict("records")
        except TypeError:
            pass
    return value


if __name__ == "__main__":
    raise SystemExit(main())
