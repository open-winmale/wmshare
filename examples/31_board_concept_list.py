"""概念板块目录：cli.board.concept_list（3.5 新面）。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/31_board_concept_list.py
学到：概念目录来自日更物化档（读当日 memo，不做索引扫描）；行形
      name/count/members，成员数降序；与 concept_members/concepts_of
      同源（上游概念标签口径，含指数/风格标签不分流）；当前截面无 PIT
      历史，不能回测历史成份；概念名是上游原文（个别含尾随空格）
文档：docs/API.md「板块」章 · estimate_cost('board.concept_list')
"""

from __future__ import annotations

from typing import Any

import wmshare
from wmshare.errors import WmshareError


def main(cli: Any = None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    print("== 1. 先估成本（日更物化档点查；未实测档如实返回 None） ==")
    est = cli.cost_estimate("board.concept_list")
    if est["ec_lo"] is None:
        print(f"  无成本模型（如实返回 None）：{est['note']}")
    else:
        print(f"  {est['ec_lo']}~{est['ec_hi']} EC（{est['model']}）")

    print("== 2. 成员数最多的 10 个概念 ==")
    df = cli.board.concept_list(10)
    rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df)
    for r in rows:
        sample = "、".join(r["members"][:3])
        print(f"  {r['name']}: {r['count']} 只（如 {sample}…）")

    print("== 3. 定向取一个概念：目录行 vs concept_members 互为镜像 ==")
    full = cli.board.concept_list()
    frows = full.to_dict("records") if hasattr(full, "to_dict") else list(full)
    hits = [r for r in frows if r["name"].strip() == "白酒"]
    if hits:
        row = hits[0]
        print(f"  目录行：白酒 = {row['count']} 只，前 5：{row['members'][:5]}")
        members = cli.board.concept_members("白酒", 200)
        mrows = members.to_dict("records") if hasattr(members, "to_dict") else list(members)
        m_syms = [str(r["symbol"]) for r in mrows if str(r["symbol"]) in set(row["members"])]
        print(f"  成份读面落在目录内的：{len(m_syms)} 只（口径一致）")
    else:
        print("  目录中未找到 白酒（物化档可能未就绪）")

    print("== 4. 自检：members 升序、count 与成员数一致 ==")
    r0 = frows[0]
    assert r0["members"] == sorted(r0["members"]), "members 应代码升序"
    assert r0["count"] == len(r0["members"]), "count 应等于成员数"
    counts = [r["count"] for r in frows]
    assert counts == sorted(counts, reverse=True), "应按成员数降序"
    print(f"  全量 {len(frows)} 个概念，排序/自检通过")


if __name__ == "__main__":
    try:
        main()
    except WmshareError as exc:  # 消息自带修复步骤，原样打印
        print(exc)
        raise SystemExit(1) from exc
