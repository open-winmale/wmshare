"""把事实包写成可发布的图文：源稿（Markdown）与公众号适配稿。

设计原则：

- **数字只拷贝，不重算**。正文里任何一个数字都必须来自事实包的 ``value_text``；
  缺条目就抛错退出，不补猜测值。这条纪律比排版重要得多——一处现造的数字
  会让整篇文章的"可复算"承诺失效。
- **图表分开生成**。成稿只管文字与图片链接，图片由 :mod:`wmshare.cb.figures`
  产出；这样换渠道（公众号/日报/邮件）时可以只换图不换文。
- **合规措辞内建**。只写"参考区间""观察名单"，不写目标价、不写买卖建议。
"""
from __future__ import annotations

from typing import Any

from .valuation import double_low, premium_pct  # noqa: F401  (供调用方复用口径)

__all__ = ["Facts", "build_source", "build_wechat", "TYPE_CN", "UTM"]

UTM = ("https://gitee.com/open-winmale/wmshare?utm_source=wechat"
       "&utm_medium=article&utm_campaign={campaign}")

TYPE_CN = {"reset_proposal": "董事会下修提案", "reset": "下修实施", "no_reset": "承诺不下修",
           "price_adj": "除权除息调价", "redeem": "强赎", "no_redeem": "不行使强赎",
           "put": "回售相关", "convert_start": "进入转股期", "convert_result": "转股结果公告",
           "shareholder_meeting": "股东会表决", "put_start": "回售期开始",
           "put_end": "回售期结束", "expiry": "到期"}

GATE_ORDER = ["g1_expired", "g1_no_price", "g1_no_size", "g2_st", "g3_redeem",
              "g3_met15", "g3_near_expiry"]

BYLINE = "本文全部数据与图表用开源库 wmshare 生成（安装：pip install wmshare）。"


class Facts:
    """事实包取数门面：缺条目即 refusal。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.p = payload
        self._by_id = {f["id"]: f for f in payload.get("facts", []) + payload.get("derived", [])}

    def text(self, fid: str) -> str:
        f = self._by_id.get(fid)
        if f is None or f.get("value_text") in (None, ""):
            raise LookupError(f"facts 缺条目 {fid}，拒绝成稿（禁现造数字）")
        return str(f["value_text"])

    def opt(self, fid: str) -> str | None:
        f = self._by_id.get(fid)
        v = f.get("value_text") if f else None
        return str(v) if v not in (None, "") else None

    def num(self, fid: str) -> float | None:
        f = self._by_id.get(fid)
        v = f.get("value_num") if f else None
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _yi(v: Any) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def _yrs(v: Any) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def build_source(fa: Facts, date: str, asof: str, campaign: str,
                 fig_dir: str = "figs") -> str:
    """生成源稿 Markdown。

    :param date: 文件名用的日期（``YYYYMMDD``）
    :param asof: 数据快照日（``YYYY-MM-DD``）——正文里"数据截至"用这个，不是运行日
    :param fig_dir: 图片链接前缀（相对仓库根或绝对路径）
    """
    p = fa.p
    top = p.get("top") or []
    gates = p.get("gates") or {}
    cal = p.get("calendar") or {}
    if not top:
        raise ValueError("事实包无榜单（top 为空），拒绝成稿")
    top0 = top[0]

    quote_base = fa.text("traded_n")
    passed_n = fa.text("gate_passed_n")
    mean_dl, median_dl = fa.text("mean_dl"), fa.text("median_dl")
    ytm_pos = fa.text("ytm_pos_n")
    excluded = fa.text("excluded_total")

    parts: list[str] = []
    # ---------- 标题（数据型，前 15 字内含「转债」）----------
    parts.append(f"# {quote_base} 只在市转债：双低均值 {mean_dl}")
    parts.append("")

    # ---------- 导语（首屏点出锚点个券）----------
    parts.append(
        f"双低最低的一只是 {top0['bondName']} {top0['bondCode']}"
        f"（双低 {fa.text('dl_' + top0['bondCode'])}），但它排在榜首的原因不是便宜，"
        f"而是转股溢价率只有 {fa.text('prem_' + top0['bondCode'])}。"
        "下面这张表先排雷、再排序，所以前 20 名和你在别处看到的双低榜不会一样。")
    parts.append("")

    # ---------- 数据卡 ----------
    gap = int(fa.num("gate_base_n") or 0) - int(fa.num("traded_n") or 0)
    parts.extend([
        f"**数据卡**｜数据截至 {asof}（快照日，非发布日）",
        f"- 样本：全表 {fa.text('total_n')} 行（含退出档案行）→ 行情基座 {quote_base} 只"
        f"（价与溢价率均非空，横截面统计口径）→ 闸门基座 {fa.text('gate_base_n')} 只"
        + (f"（另 {gap} 只在档但当日无报价，一并送进闸门逐只判定，不留盲区）" if gap > 0 else "")
        + f"→ 过闸 {passed_n} 只",
        f"- 温度：双低均值 {mean_dl}、中位 {median_dl}、溢价率均值 {fa.text('mean_prem')}",
        f"- 结构：破面（<100 元）{fa.text('bin_lt100')} 只，130 元以上 {fa.text('bin_gt130')} 只",
        f"- 排雷：剔除 {excluded} 只，其中已满足强赎 {fa.text('gate_g3_met15')} 只、"
        f"剩余不足半年 {fa.text('gate_g3_near_expiry')} 只、正股 ST {fa.text('gate_g2_st')} 只",
        f"- 事件：今日新增条款公告 {fa.text('cal_new_n')} 起，未来 30 日 {fa.text('cal_next_n')} 个节点",
        "",
        BYLINE,
        "",
    ])

    # ---------- 01 今日温度 ----------
    parts.append("## 01 今日温度")
    parts.append("")
    parts.append(f"行情基座 {quote_base} 只（价与转股溢价率均非空）。双低均值 {mean_dl}、"
                 f"中位 {median_dl}——两个数要对照着看：均值看整体水位，"
                 "中位看「典型一只债」的水位；中位明显低于均值，说明少数高双低个券把均值抬高了。")
    parts.append("")
    delta = fa.opt("mean_delta")
    if delta:
        if p.get("hist_series_n"):
            parts.append(f"与上一期相比，双低均值变化 {delta}。")
        else:
            parts.append(f"与上一期相比，双低均值变化 {delta}（历史序列自本期起积累，"
                         "满 10 期后开放分位与星级）。")
        parts.append("")
    parts.append(f"价格分布：低于 100 元 {fa.text('bin_lt100')} 只、"
                 f"100–110 元 {fa.text('bin_100_110')} 只、"
                 f"110–130 元 {fa.text('bin_110_130')} 只、"
                 f"130 元以上 {fa.text('bin_gt130')} 只。"
                 "130 元以上意味着已进入强赎触发价的常见区间（多数条款以 130% 转股价为线）。")
    parts.append("")
    parts.append(f"税后到期收益率为正的 {ytm_pos} 只，其中正股带 ST 的 {fa.text('obs_ytm_pos_st_n')} 只、"
                 f"通过三道闸进入候选池的 {fa.text('obs_ytm_pos_passed_n')} 只。"
                 "YTM 为正的多数恰恰是低价区、也是信用折价最深的地方——"
                 "2023–2024 年搜特、蓝盾、鸿达、岭南四只违约债，当时都曾交易在百元附近。")
    parts.append("")
    hist = fa.opt("dl_pct_hist")
    if hist and hist != "序列积累中":
        stars = fa.opt("stars")
        parts.append(f"双低均值在历史序列中的分位 {hist}"
                     + (f"，转债温度 {stars}" if stars else "")
                     + f"（序列 {p.get('hist_series_n')} 期）。")
    else:
        parts.append("历史分位与温度星级从本期起逐日积累，满 10 期后开放——"
                     "不拿首期数据冒充历史分位。")
    parts.append("")
    parts.append(f"![双低榜与温度计]({fig_dir}/day{date}_cb_table.png)")
    parts.append("")
    parts.append("**读法**：表按双低升序；绿底=偏债（税后到期收益率为正），橙底=正股 ST，"
                 "灰底=剩余 0.5–1 年（灰标区，双低会天然偏低）。")
    parts.append("")

    # ---------- 02 双低榜 ----------
    parts.append(f"## 02 双低榜前 {len(top)}（已过三道闸）")
    parts.append("")
    parts.append("双低 = 价格 + 转股溢价率×100（社区通行公式，本项目独立计算）。"
                 f"下表 {len(top)} 只是通过 G1 可交易 → G2 信用 → G3 条款三道闸后双低最低的标的，"
                 f"剔除的 {excluded} 只见 03 节。")
    parts.append("")
    parts.append("| 转债 | 代码 | 价格(元) | 溢价率 | 双低 | 税后YTM | 规模(亿) | 剩余年限 | "
                 "强赎状态 | 下修状态 | 正股 | 警示 |")
    parts.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in top:
        code = r["bondCode"]
        dist = r.get("redeem_dist_pct")
        if r.get("call_state_key") == "idle" and isinstance(dist, (int, float)):
            call_cell = f"距触发 {dist:+.0f}%"
        else:
            call_cell = r.get("call_state") or "—"
        reset_cell = r.get("reset_state") or "—"
        floor = r.get("reset_floor")
        if reset_cell in ("无", "") and isinstance(floor, (int, float)):
            reset_cell = f"地板 {floor:.2f}"
        tl = r.get("stock_tl_rate_pct")
        if r.get("is_st"):
            warn = "ST"
        elif isinstance(tl, (int, float)) and tl >= 85:
            warn = f"负债率 {tl:.0f}%"
        elif r.get("near_expiry"):
            warn = "临近到期"
        else:
            warn = "—"
        ytm = fa.opt(f"ytm_{code}") or "—"
        parts.append(f"| {r['bondName']} | {code} | {fa.text(f'price_{code}')} | "
                     f"{fa.text(f'prem_{code}')} | {fa.text(f'dl_{code}')} | {ytm} | "
                     f"{_yi(r.get('remain_size_yi'))} | {_yrs(r.get('years_to_expire'))} | "
                     f"{call_cell} | {reset_cell} | {r.get('stockName') or '—'} | {warn} |")
    parts.append("")
    c0 = top0["bondCode"]
    parts.append(f"**读法**：第一名 {top0['bondName']}（{c0}）双低 {fa.text('dl_' + c0)}，"
                 f"价格 {fa.text('price_' + c0)} 元、溢价率 {fa.text('prem_' + c0)}。"
                 "「强赎状态」列在未触发时给的是**正股还要上涨多少才够到强赎触发价**——"
                 "这个数越大，离强制赎回越远；越小，越要盯计数公告。"
                 "「下修状态」列给公告口径的状态，或服务端测算的下修地板价（转股价的下限参考）。")
    parts.append("")
    parts.append(f"![全市场双低价差图]({fig_dir}/day{date}_cb_scatter.png)")
    parts.append("")
    parts.append("**读法**：越靠左下双低越小；斜虚线是双低等值线。实心圆=通过闸门，"
                 "灰叉=被剔除，空心圆=剩余 0.5–1 年的灰标区。右下角（高价+低溢价）是偏股区，"
                 "左上角（低价+高溢价）是最需要信用筛子的区域。")
    parts.append("")

    # ---------- 03 三道闸 ----------
    parts.append("## 03 三道闸：今天被剔除了什么")
    parts.append("")
    parts.append("排序之前先排雷。三道闸按序判定、命中即剔除、理由唯一（只记首个命中理由，"
                 "其余命中留档可查）：G1 可交易（到期未摘牌、无有效报价、剩余规模为 0）→ "
                 "G2 信用（正股 ST / 退市整理）→ G3 条款（已公告强赎、已满足强赎条件、"
                 "剩余不足 0.5 年）。")
    parts.append("")
    by_reason = gates.get("byReason") or {}
    labels = gates.get("ruleLabel") or {}
    parts.append("| 闸门 | 剔除数 | 本期名单（部分） |")
    parts.append("|---|---|---|")
    for key in GATE_ORDER:
        items = by_reason.get(key) or []
        if not items:
            continue
        names = "、".join(str(x["bondName"]) for x in items[:8])
        more = f" 等 {len(items)} 只" if len(items) > 8 else ""
        parts.append(f"| {labels.get(key, key)} | {fa.text('gate_' + key)} | {names}{more} |")
    parts.append("")
    parts.append(f"合计剔除 {excluded} 只，与各闸门计数之和一致（{passed_n} 只过闸 → 进榜候选）。"
                 "**G3 剩余不足半年**这一条最容易被忽略：这类债双低天然偏低会挤占榜单前列，"
                 "但它们剩余时间短、期权价值接近归零，价格再低也换不来时间。")
    parts.append("")

    # ---------- 04 条款日历 ----------
    parts.append("## 04 条款日历")
    parts.append("")
    new_today = cal.get("newToday") or []
    if new_today:
        parts.append(f"**今日新增 {fa.text('cal_new_n')} 起**（{asof} 公告）：")
        parts.append("")
        for c in new_today:
            title = str(c.get("title") or "")[:40]
            parts.append(f"- {c['bondName']}（{c['bondCode']}）· "
                         f"{TYPE_CN.get(c['type'], c['type'])}：{title}")
        parts.append("")
    else:
        parts.append("**今日无新增条款公告。**")
        parts.append("")
    nxt = cal.get("next30d") or []
    if nxt:
        parts.append(f"**未来 30 日 {fa.text('cal_next_n')} 个节点**（按日期升序；到期与股东会表决是"
                     "最硬的两个时点）：")
        parts.append("")
        parts.append("| 日期 | 类型 | 转债 |")
        parts.append("|---|---|---|")
        for c in nxt:
            parts.append(f"| {c['date']} | {TYPE_CN.get(c['type'], c['type'])} | "
                         f"{c['bondName']}（{c['bondCode']}） |")
        parts.append("")
        prop = [c for c in new_today if c["type"] == "reset_proposal"]
        if prop:
            names = "、".join(f"{c['bondName']}（{c['bondCode']}）" for c in prop)
            parts.append(f"本次新增下修提案：{names}——提案只是提请股东会，"
                         "最终是否下调、下调到多少以表决结果与后续公告为准。")
            parts.append("")
        parts.append("下修提案的表决日是最值得记的时点：提案通过则转股价下调、转股价值抬升，"
                     "不通过则承诺期重算。这里只列时点与机制，不预判表决结果。")
        parts.append("")
    band = p.get("featured_band") or {}
    if band:
        parts.append("**价格通道**（榜前几只，上市以来全部交易日；读法在图后统一说明）：")
        parts.append("")
        for code, b in band.items():
            ch = b["channel"]
            parts.append(f"**{b['name']}** 上市以来 {b['n_bars']} 个交易日的价格通道："
                         f"z 值 {ch['z']:+.2f}、价格分位 {ch['pct'] * 100:.1f}%、"
                         f"分区「{ch['zone_cn']}」，μ±1σ 区间 {ch['lower1']:.2f}–{ch['upper1']:.2f} 元。")
            parts.append("")
            parts.append(f"![{b['name']} 价格通道]({fig_dir}/day{date}_cbband_{code}.png)")
            parts.append("")
        parts.append("**读法**：通道是位置描述（现价在自身历史分布中的哪一格），不是买卖信号；"
                     "z 值越负越处在历史低位区。几只债的 μ、σ 各自独立计算，"
                     "不可横向比较谁「更便宜」。")
        parts.append("")

    # ---------- 05 异动观察 ----------
    parts.append("## 05 异动观察（只陈述事实）")
    parts.append("")
    obs: list[str] = []
    lt100 = fa.opt("obs_lt100_names")
    if lt100 and lt100 != "无":
        obs.append(f"**破面区名单**：{lt100}——其中正股带 ST 标记的有 "
                   f"{fa.text('obs_lt100_st_n')} 只。价格低于面值不等于便宜，"
                   "这类标的的低价来源是信用折价与到期时间不足，不是估值错杀。")
    met15 = fa.opt("obs_call_met15")
    if met15 and met15 != "0":
        obs.append(f"**已满足强赎条件 {met15} 只**，全部已被 G3 剔除、不进榜单。"
                   "已满足不等于一定赎回：是否行使由公司决定，计数达标只代表条款门槛已过。")
    waived = fa.opt("obs_call_met15_with_waiver")
    if waived and waived != "0":
        recent = fa.text("obs_call_met15_waiver_recent")
        obs.append(f"**计数达标、同时有不赎回公告的 {waived} 只**：{met15} 只达标个券里，"
                   f"{waived} 只此前发过「不提前赎回」公告，最新几只是 {recent}。"
                   "这里并列两个事实、不下合并结论——不赎回公告通常只承诺未来若干个月，"
                   "而事件流不给有效期字段。**判定豁免是否仍在有效期内，请查公告原文**；"
                   "能确定的是：计数已经攒满，公告一到期，只要股价还站在触发价上，"
                   "随时可以重新启动赎回流程。")
    near_n = fa.opt("obs_call_near_n")
    if near_n and near_n != "0":
        obs.append(f"**距强赎触发不足 10% 的过闸个券 {near_n} 只**：{fa.text('obs_call_near_names')}。"
                   "正股再涨这一小段，就会进入「15 个交易日中有 15 日收盘不低于触发价」的计数区；"
                   "计数达标后是否赎回仍由公司决定，但价格上限会被条款压住。"
                   "这一列用快照价与触发价直接相除得到，不依赖服务端计数字段。")
    nored = fa.opt("obs_call_no_redeem")
    if nored and nored != "0":
        obs.append(f"**公告不强赎 {nored} 只**：公司在有效期内承诺不行使赎回权，"
                   "这段时间的强赎风险按公告口径视作解除，但承诺到期后重新起算。")
    stale = fa.opt("obs_call_stale_n")
    if stale and stale != "0":
        obs.append(f"**计数口径待核 {stale} 只**：{fa.text('obs_call_stale_names')} 的正股快照价已不低于"
                   "强赎触发价，但服务端计数未达标。本期按「未满足」处理并保留在榜内，"
                   "同时在这里点明——若后续公告确认计数，会被 G3 剔除并退出榜单。"
                   "口径上宁可少剔，也不替发行人提前下结论。")
    gray = fa.opt("obs_gray_n")
    if gray and gray != "0":
        obs.append(f"**灰标区 {gray} 只**：剩余 0.5–1 年，仍入榜但在表里灰底标注。"
                   "它们的双低会因时间价值衰减而天然偏低，看排名时要把这一列权重调低。")
    for i, s in enumerate(obs, 1):
        parts.append(f"{i}. {s}")
        parts.append("")

    # ---------- 06 口径与复现 ----------
    parts.extend([
        "## 06 口径与复现",
        "",
        "**口径脚注（每期固定）**",
        "",
        "- 双低 = 价格 + 转股溢价率×100；溢价率字段为百分比数值（4.87 表示 +4.87%）；",
        "- 在市 = 快照行 bondPrice 与 premiumRatio 均非空，再叠剩余规模 > 0、到期日 ≥ 快照日；"
        "全表含已退出合约的档案行；",
        "- 税后到期收益率为可达口径：有分年票息表就用表、并以到期赎回价求 IRR；"
        "缺票息表时退回当期票息恒定；赎回价缺失时按面值 100（真值 ≥ 此下限）；利息税 20%；"
        "剩余不足 0.5 年不年化；",
        "- 债性分类与三色是估值参考区间，非官方阈值；强赎/下修状态由公告事件与服务端计数推导，"
        "非交易所口径；",
        f"- 数据截至 {asof}（快照日），非文章发布日。",
        "",
        "**想自己算一遍**",
        "",
        "```python",
        "from wmshare import Client",
        "from wmshare.cb import run_daily",
        "",
        "cli = Client.from_env()",
        "payload = run_daily(cli)          # 一次面板 + 全量条款事件 + 少量日 K",
        "for r in payload['top'][:5]:",
        "    print(r['bondName'], r['double_low'], r['ytm'])",
        "```",
        "",
        "```text",
        "参数：cbond.board() 转债面板（一次请求返回全市场，按日 asOf）",
        "返回：bondCode/bondName/bondPrice/premiumRatio/transferValue/redeemValue/"
        "redeemTrig/remainSize/outstanding/callHits/resetFloor/event",
        "单位：价格与双低为元（面值 100 口径），premiumRatio 为百分比数值",
        "注意：面板不含 rating（评级）与行业字段，也不含下修触发比例与下修计数，"
        "这两类缺口在口径段如实标注，不用推测值填充",
        "```",
        "",
        "装法一行：`pip install wmshare`。不装环境也行——在微信「搜一搜」或任意平台"
        "搜索 wmshare，即可找到开源仓库、口径文档与全部示例脚本。",
        "",
        "## 带走三条",
        "",
        f"1. **排序之前先排雷**：双低是排序器，不是筛子。今天被剔除的 {excluded} 只里，"
        f"{fa.text('gate_g3_met15')} 只已满足强赎条件、"
        f"{fa.text('gate_g3_near_expiry')} 只剩余不足半年——它们双低都很低，但低的原因各不相同；",
        "2. **低价不等于便宜**：破面区里正股 ST 的占多数，违约史已经给过教训；"
        "看到百元以下的债，第一个问题应当是「为什么不涨」，而不是「是不是便宜」；",
        "3. **先问口径再看表**：溢价率是小数还是百分数、在市怎么过滤、"
        "YTM 是下限还是可达——同一张双低表，口径不同结论可以完全相反。",
        "",
        "**留一个问题**：下一期你更想先看到哪一段的加强——"
        "强赎倒计时的逐日计数，还是下修提案的触发进度？"
        "这两项目前上游字段都不全，读者的优先级会决定我们先补哪个数据缺口。",
        "",
        "---",
        "",
        "本文由 AI 辅助生成，全部数字可用 wmshare 逐项复算（口径见 06 节）。"
        "数据会随行情更新，请以交易软件实时数据为准。本文只讲数据口径与计算方法，"
        "不构成投资建议。",
    ])
    return "\n".join(parts) + "\n"


def build_wechat(src: str, campaign: str, summary: str) -> str:
    """在源稿上加摘要与阅读原文链接，供公众号排版直接粘贴。"""
    utm = UTM.format(campaign=campaign)
    link_line = ("本文全部数据与图表用开源库 wmshare 生成："
                 f"[开源仓库]({utm})")
    out = src.replace(BYLINE, f"> 摘要：**{summary}**\n\n{link_line}", 1)
    return out.rstrip("\n") + f"\n\n阅读原文：[wmshare 开源仓库]({utm})\n"


def build_summary(fa: Facts) -> str:
    """公众号摘要行（一句数据，控制在两行内）。"""
    return (f"在市转债 {fa.text('traded_n')} 只，过三道闸后 {fa.text('gate_passed_n')} 只："
            f"双低均值 {fa.text('mean_dl')}、中位 {fa.text('median_dl')}，"
            f"税后 YTM 为正 {fa.text('ytm_pos_n')} 只；剔除的 {fa.text('excluded_total')} 只"
            "各有各的原因。")
