#!/usr/bin/env python3
"""对真实网关逐接口拍摄响应样本 → docs/api_pack_samples.json。

消费方：build_api_pack 把样本合并进 api_pack 条目的 ``sample`` 字段，开放平台
接口文档站的「示例响应」优先展示真实拍摄（演示快照降级为离线兜底）——用户在
页面看到的响应与点「在线测试」会得到的响应同源。

- 凭证：``Client.from_env()``（~/.wmshare/credentials.env / WMSHARE_*），
  无凭证回落 ``Client.anonymous()``（匿名试用额度）；维护者联网运行。
- 参数：复用 gen_api_docs 的示例参数表（与页面「示例参数」、test payload 一致）；
  先用完整示例参数，失败回落最小必填参数。
- 断点续拍：已有样本文件里 result 非空的 key 跳过（``--force`` 全量重拍）。
- 成本：每次调用真实计 EC（汇总写 provenance.total_ec）；逐条间隔 0.3s 防 429。

用法：.venv/bin/python tools/generate_api_pack_samples.py [--force] [--only key subs]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from gen_api_docs import (  # noqa: E402
    API_PACK_OUT, API_PACK_SAMPLES, SAMPLE_ROW_CAP, SAMPLE_TEXT_CAP,
    _attempt_kwargs_list, _json_safe,
)

from wmshare.client import Client  # noqa: E402

CALL_GAP_SEC = 0.3


def build_client(market: str = "cn") -> tuple[Client, str]:
    """from_env 凭据双缺自动回落匿名（anon_open_* 前缀可识别来源）。"""
    cli = Client.from_env(market=market)
    return cli, ("anonymous" if cli.client_id.startswith("anon_open") else "maintainer")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有样本全量重拍")
    ap.add_argument("--only", action="append", default=[],
                    help="只拍 key 含该子串的接口（可多次）")
    args = ap.parse_args()

    pack = json.loads(API_PACK_OUT.read_text(encoding="utf-8"))
    ifaces = [i for n in pack["namespaces"]
              for i in (*n["interfaces"], *n["composites"])]

    prev: dict = {}
    if API_PACK_SAMPLES.is_file() and not args.force:
        prev = json.loads(API_PACK_SAMPLES.read_text(encoding="utf-8"))
    prev_map = {s["key"]: s for s in prev.get("samples") or []}
    # 续拍语义：只保留上次成功的（result 键存在，值可以是 None=标的真实无数据）；
    # 上次 error 的无条件重试
    samples = [s for s in prev_map.values() if "result" in s]
    done = {s["key"] for s in samples}
    total_ec = float(prev.get("provenance", {}).get("total_ec") or 0)

    cli, cred = build_client()
    cli_hk, _ = build_client(market="hk")
    print(f"[samples] client={cred} base={cli.base_url} "
          f"interfaces={len(ifaces)} already={len(done)}")

    for i in ifaces:
        key = i["key"]
        if key in done:
            continue
        if args.only and not any(pat in key for pat in args.only):
            continue
        if not i["docs_visible"] and not i.get("page") and not args.force:
            continue  # 完全隐藏的接口不成页（变体会出现在宿主变体表，要拍）

        ns, method = i["ns"], i["method"]
        # intl 是港美股披露面：cn 客户端必 MARKET_MISMATCH，换 hk 客户端
        use_cli = cli_hk if ns == "intl" else cli
        fn = getattr(getattr(use_cli, ns), method, None)
        if fn is None:
            samples.append({"key": key, "error": "facade absent"})
            continue

        from types import SimpleNamespace
        params = [SimpleNamespace(name=p["name"], required=p["required"])
                  for p in i["params"]]
        got = None
        for kw in _attempt_kwargs_list(ns, method, params):
            # etf 九视图必须场内 ETF 代码；茅台不是 ETF（NOT_ETF 拒）
            if ns == "etf":
                kw = {**kw, "symbol": "510300"}
            try:
                result = fn(**kw)
                ec = float(getattr(use_cli, "last_ec_cost", 0) or 0)
                # result=None 是合法真实响应（标的在该面无数据），照常入样本
                got = {"key": key, "kwargs": kw, "ec": ec,
                       "result": _json_safe(result, row_cap=SAMPLE_ROW_CAP,
                                            text_cap=SAMPLE_TEXT_CAP)}
                total_ec += ec
                break
            except Exception as e:  # 换下一组参数；两组都失败记 error
                last_err = f"{type(e).__name__}: {e}"
        if got is None:
            got = {"key": key, "error": last_err}
        samples.append(got)
        status = "ok" if "result" in got else f"error: {got.get('error', '')[:80]}"
        print(f"[samples] {key:<40} {status}  ec={got.get('ec', '—')}")
        time.sleep(CALL_GAP_SEC)

    # ---- 特殊重试：参数依赖前置结果或客户端构造差异的接口 ----
    # 常规两轮参数都失败的，按接口语义解析出真实参数再试一次；仍失败则如实留 error。
    def _special_retry() -> None:
        nonlocal total_ec
        pending = [s for s in samples if "result" not in s]
        if not pending:
            return
        lazy: dict[str, Client] = {}

        def client_of(kind: str) -> Client:
            if kind not in lazy:
                kw = {"max_limit": None} if kind == "nolimit" \
                    else {"validate": False} if kind == "novalidate" else {}
                lazy[kind] = Client.from_env(**kw)
            return lazy[kind]

        by_key = {s["key"]: s for s in samples}
        for s in pending:
            key = s["key"]
            try:
                if key == "backtest.run":  # 全历史回测超过默认 max_limit=500
                    cli2 = client_of("nolimit")
                    kw = {"symbol": "600519"}
                    r = cli2.backtest.run(**kw)
                elif key == "etf.nav":  # 真实上游值触发量级守护 → 关校验取原始值
                    cli2 = client_of("novalidate")
                    r = cli2.etf.nav(symbol="510300")
                    kw = {"symbol": "510300"}
                elif key == "cbond.article":  # payload = cbond.daily 的完整产出
                    cli2 = client_of("nolimit")
                    payload = cli2.cbond.daily()
                    r = cli2.cbond.article(payload)
                    kw = {"payload": "<cbond.daily() 产出>"}
                elif key == "cbond.figures":
                    import tempfile
                    cli2 = client_of("nolimit")
                    payload = cli2.cbond.daily()
                    out_dir = tempfile.mkdtemp(prefix="wmshare-figures-")
                    r = cli2.cbond.figures(payload, out_dir)
                    kw = {"payload": "<cbond.daily() 产出>", "out_dir": out_dir}
                elif key in ("pdf_doc.find_by_url", "pdf_doc.find_by_key"):
                    # search 输出可能含超巨型 PDF 行（守护会拒 text_chars 超限行），
                    # 搜索本身用关校验客户端；逐行试定位到成功
                    cli2 = client_of("novalidate")
                    rows = cli2.pdf_doc.search(limit=5)
                    records = (rows.to_dict("records") if hasattr(rows, "to_dict")
                               else list(rows))
                    r = None
                    for row in records:
                        try:
                            if key == "pdf_doc.find_by_url":
                                r = cli2.pdf_doc.find_by_url(row["url"])
                            else:
                                r = cli2.pdf_doc.find_by_key(row["file_key"])
                            break
                        except Exception:
                            continue
                    if r is None:
                        raise RuntimeError("search 前 5 行均定位失败")
                    kw = {("url" if key.endswith("url") else "file_key"):
                          "<pdf_doc.search 行字段>"}
                else:
                    continue
                ec = float(getattr(cli2, "last_ec_cost", 0) or 0)
                total_ec += ec
                s.clear()
                s.update({"key": key, "kwargs": kw, "ec": ec,
                          "result": _json_safe(r, row_cap=SAMPLE_ROW_CAP,
                                               text_cap=SAMPLE_TEXT_CAP)})
                print(f"[samples] {key:<40} ok(special)  ec={ec}")
                time.sleep(CALL_GAP_SEC)
            except Exception as e:
                s["error"] = f"{type(e).__name__}: {e}"[:160]
                print(f"[samples] {key:<40} error(special): {s['error'][:70]}")

    _special_retry()

    ok = sum(1 for s in samples if "result" in s)
    doc = {
        "schema_version": 1,
        "generated_by": "tools/generate_api_pack_samples.py",
        "provenance": {
            "captured_at": time.strftime("%Y-%m-%d"),
            "credentials": cred,
            "total_ec": total_ec,
            "ok": ok,
            "total": len(samples),
        },
        "samples": samples,
    }
    API_PACK_SAMPLES.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"[samples] wrote {API_PACK_SAMPLES.relative_to(Path.cwd())}: "
          f"{ok}/{len(samples)} ok, total_ec={total_ec:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
