#!/usr/bin/env python3
"""构建 notebooks/index_daily.ipynb（源码以脚本维护，产物 notebook 提交执行输出）。

拆两半：本脚本只负责把 cells JSON 组装落盘；正文内容在 INDEX_NB_CELLS（本文件内）。
执行：python3 tools/build_index_daily_nb.py  （在 wmshare 仓根目录）
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


_id_n = [0]


def md(text: str) -> dict:
    _id_n[0] += 1
    return {"id": f"cell-{_id_n[0]:02d}", "cell_type": "markdown", "metadata": {},
            "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    _id_n[0] += 1
    return {"id": f"cell-{_id_n[0]:02d}", "cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [], "source": text.splitlines(keepends=True)}


CELLS = [
    md("""# 指数估值榜 + 通道拨测（wmshare notebook）

只用 [wmshare](https://github.com/open-winmale/wmshare) 一个数据源：

- **榜单**：`index.universe_keys()`（已注册成分宇宙的宽基键）× `index.valuation(key)`
  （整体法 PE/PB/股息率当前值）× `index.trend(key)`（周频整体法序列 → PE/PB 历史分位）
  × 盈利收益率 vs 10 年期国债 → 三档参考区间 + 市场温度星级
- **拨测**：`probe(symbol)` 按需能力——任意场内 ETF/指数键的价格通道（μ±2σ、z 值、
  近 3 年分位、可选 μ∓1σ 单轮回看）

> 档位口径：盈利收益率 = 1/PE；> 2×10Y 国债记绿档、1~2× 记黄档、< 1× 记橙档——
> 行业通行规则的**估值参考区间，非官方阈值**；全文只做数据整理与研究参考，
> **不构成任何投资建议**。整体法口径与主流终端实测差 <1%（2026-11-07）。"""),
    code("""import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "PingFang SC",
                                   "Arial Unicode MS", "SimHei", "sans-serif"]

from wmshare import Client, demo_client


def load_credentials() -> None:
    \"\"\"凭证从 ~/.wmshare/credentials.env 读（也可直接 export WMSHARE_CLIENT_ID/SECRET）。\"\"\"
    for p in (Path.home() / ".wmshare/credentials.env",
              Path.home() / ".winmale/credentials.env"):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


DEMO = False  # True = 离线演示数据（零凭证零请求）
if DEMO:
    cli = demo_client()
else:
    load_credentials()
    # 3 年日频 760 根 > 默认单次上限 500，拨测场景放宽
    cli = Client.from_env(max_limit=800)
print("client ready:", "demo" if DEMO else "live")"""),
    md("""## 一、指数估值榜

每键一次 `valuation`（当前值）+ 一次 `trend`（周频序列分位）。`trend` 依赖平台预热缓存
（cron 每收盘刷新），未命中的键分位列显示「缓存未命中」，其余列不受影响。"""),
    code("""# ── 榜单参数：口径 × 窗口 ────────────────────────────────────────────────
WINDOW = "5y"        # 分位窗口：3y / 5y / 10y
MEASURE = "pe"       # 分位口径：pe（整体法）/ pe_med（中位数）
ZONE_CUT = (0.30, 0.70)   # 绿 <30% / 黄 30~70% / 红 >70%

GROUP_LABEL = {"broad": "宽基", "industry": "行业", "dividend": "红利"}
FALLBACK = {
    "broad": ["index.hs300", "index.csi500", "index.sz50", "index.cybz", "index.star50",
              "index.shzs", "index.szcz", "index.zx100", "index.szzzs", "index.gz2000",
              "index.kc200"],
    "dividend": ["index.csidividend", "index.ssedividend", "index.szhl", "index.gzhl",
                 "index.csicentralsoesdividend", "index.csisoesdividend",
                 "index.csipoesdividend", "index.csi300dividend", "index.csi500dividend",
                 "index.sse180dividend", "index.sse380dividend", "index.ssesoesdividend",
                 "index.ssepoesdividend", "index.ssecentralsoesdividend"],
}
CN = {"HS300": "沪深300", "CSI500": "中证500", "SZ50": "上证50", "CYBZ": "创业板指",
      "STAR50": "科创50", "SHZS": "上证指数", "SZCZ": "深证成指", "ZX100": "中小100",
      "SZZZS": "深证300", "GZ2000": "国证2000", "KC200": "科创200",
      "CSIDIVIDEND": "中证红利", "SSEDIVIDEND": "红利指数", "SZHL": "深证红利",
      "GZHL": "国证红利", "CSICENTRALSOESDIVIDEND": "央企红利",
      "CSISOESDIVIDEND": "国企红利", "CSIPOESDIVIDEND": "民企红利",
      "CSI300DIVIDEND": "300红利", "CSI500DIVIDEND": "500红利",
      "SSE180DIVIDEND": "180红利", "SSE380DIVIDEND": "380红利",
      "SSESOESDIVIDEND": "上国红利", "SSEPOESDIVIDEND": "上民红利",
      "SSECENTRALSOESDIVIDEND": "上央红利"}

try:  # 行业名录是运行时数据，不硬编码；demo / 旧服务端无此接口则空
    IND_ROWS = cli.stocks.industry_list(1) or []
except Exception as _e:
    print("[industry] 名录不可用：", str(_e)[:60])
    IND_ROWS = []
IND_NAME = {r["symbol"]: r["name"] for r in IND_ROWS if isinstance(r, dict)}


def group_keys(group):
    # 取一组键；服务端未部署分组能力时回落到本地清单 / 行业名录
    if group == "industry":
        return ["industry." + r["symbol"] for r in IND_ROWS if isinstance(r, dict)]
    try:
        got = cli.index.universe_keys(group)
        if got:
            return list(got)
    except Exception as e:
        print("[%s] universe_keys 不可用：%s" % (group, str(e)[:60]))
    return FALLBACK.get(group, [])


def zone_of_pct(p):
    # 自身历史分位三档（估值参考区间，非官方阈值）
    if p is None:
        return "—"
    lo, hi = ZONE_CUT
    return "绿档" if p < lo else ("黄档" if p <= hi else "红档")


def label_of(key):
    # 键 → 展示名
    if key.startswith("industry."):
        code = key.split(".", 1)[1]
        return IND_NAME.get(code, code)
    short = key.replace("index.", "").upper()
    return CN.get(short, short)


def pct_recompute(points, col, years, asof):
    # 独立复算：不复用 SDK 分位，按 rank0/(n-1) 重算最新点位置
    if not asof or len(asof) < 10:
        return None
    cut = "%d%s" % (int(asof[:4]) - years, asof[4:10])
    pts = [p for p in points if isinstance(p.get(col), (int, float)) and p[col] > 0]
    if not pts or pts[-1]["date"] > cut:   # 序列起点晚于窗口下界 → 窗口不足
        return None
    vals = sorted(p[col] for p in pts if p["date"] >= cut)
    cur = pts[0][col]                      # points 是新→旧，[0] 即最新点
    if len(vals) < 2:
        return None
    rank0 = (sum(1 for v in vals if v < cur) + sum(1 for v in vals if v <= cur) - 1) / 2
    return rank0 / (len(vals) - 1)


def med_points(med):
    # 月频中位数序列 → 与 base 同结构（date/pe/pe_med），供中位数口径复用同一套分位算法
    return [{"date": str(m[0])[:10], "pe": m[1], "pe_med": m[1]}
            for m in (med or []) if isinstance(m, (list, tuple)) and len(m) >= 2]


def med_window_n(points, years, asof):
    # 窗口内有效样本数（与 pct_recompute 同一切窗规则），用于「样本」列如实展示
    if not asof or len(asof) < 10:
        return 0
    cut = "%d%s" % (int(asof[:4]) - years, asof[4:10])
    return sum(1 for p in points
               if p["date"] >= cut and isinstance(p.get("pe_med"), (int, float)) and p["pe_med"] > 0)


def measure_pct(t, measure):
    # 取分位：优先服务端 pct[measure].p；服务端未部署该口径时用本地序列自算（并标注来源）
    # 返回 (分位, 来源, 该口径序列, 该口径窗口样本数)
    yrs = int(WINDOW[:-1]) if WINDOW[:-1].isdigit() else 5
    node = ((t.get("pct") or {}).get(measure) or {}) if t.get("pct") else {}
    p = node.get("p") if isinstance(node.get("p"), (int, float)) else None
    n = node.get("n%d" % yrs) if isinstance(node.get("n%d" % yrs), (int, float)) else 0
    if p is not None:
        return p, "server", (t.get("points") or []), n
    if measure == "pe":
        if isinstance(t.get("pe_pct"), (int, float)):
            return t["pe_pct"], t.get("pct_source") or "server", (t.get("points") or []), t.get("win_n") or 0
        return None, "", (t.get("points") or []), 0
    # pe_med：服务端只给 base/med 时，本地按月频中位数序列算（样本数是月频点数，不是周频点数）
    mp = med_points(t.get("med"))
    p = pct_recompute(mp, "pe_med", yrs, t.get("as_of") or "")
    return p, ("client" if p is not None else ""), mp, med_window_n(mp, yrs, t.get("as_of") or "")


def collect(keys, group):
    out = []
    for k in keys:
        row = {"组": GROUP_LABEL.get(group, group), "key": k, "名称": label_of(k)}
        try:
            cur = (cli.index.valuation(k) or {}).get("current") or {}
            pe, pb, dv = cur.get("pe"), cur.get("pb"), cur.get("dv")
            row["PE"] = round(pe, 2) if isinstance(pe, (int, float)) else None
            row["PB"] = round(pb, 2) if isinstance(pb, (int, float)) else None
            row["股息率%"] = round(dv * 100, 2) if isinstance(dv, (int, float)) else None
        except Exception as e:
            row.update({"PE": None, "PB": None, "股息率%": None,
                        "备注": "valuation 不可用：%s" % str(e)[:30]})
        try:
            t = cli.index.trend(k, WINDOW)
            p, src, series, n_used = measure_pct(t, MEASURE)
            row["分位%"] = round(p * 100, 1) if p is not None else None
            row["档位"] = zone_of_pct(p)
            row["数据日期"] = t.get("as_of") or ""
            row["窗口"] = t.get("window") or WINDOW
            row["样本"] = n_used or t.get("win_n") or t.get("n") or 0
            row["窗口不足"] = bool(t.get("win_trunc"))
            row["分位来源"] = src
            row["_series"] = series
            row["_asof"] = t.get("as_of") or ""
        except Exception as e:
            row.update({"分位%": None, "档位": "—", "数据日期": "", "窗口": WINDOW,
                        "样本": 0, "窗口不足": True, "分位来源": "",
                        "_series": [], "_asof": "",
                        "备注": "trend 不可用：%s" % str(e)[:30]})
        out.append(row)
    return out


all_rows = []
for g in ("broad", "industry", "dividend"):
    ks = group_keys(g)
    if not ks:
        print("[%s] 无可用键（服务端分组未部署或名录为空），跳过" % GROUP_LABEL[g])
        continue
    rs = collect(ks, g)
    all_rows.extend(rs)
    rated_g = [r for r in rs if r["档位"] in ("绿档", "黄档", "红档")]
    print("%s: %d 键，有效分位 %d，绿 %d" % (
        GROUP_LABEL[g], len(rs), len(rated_g),
        sum(1 for r in rated_g if r["档位"] == "绿档")))

# ── 独立复算对账：SDK 分位 vs 按序列重算，必须逐位一致 ──────────────────
years = int(WINDOW[:-1]) if WINDOW[:-1].isdigit() else 5
col = "pe_med" if MEASURE == "pe_med" else "pe"
mismatch, checked, skipped = [], 0, 0
for r in all_rows:
    if r["分位%"] is None:
        continue
    if MEASURE == "pe_med" and r["分位来源"] != "server":
        # pe_med 走本地兜底时，「SDK 值」本身就是笔记本按同一中位数序列算的，
        # 再拿同一套算法对账等于自己比自己 → 跳过并如实计数
        skipped += 1
        continue
    got = pct_recompute(r["_series"], col, years, r["_asof"])
    if got is None:
        skipped += 1
        continue
    checked += 1
    if abs(got * 100 - r["分位%"]) > 0.05:
        mismatch.append((r["名称"], r["分位%"], round(got * 100, 1)))
print("独立复算：比对 %d 行，不一致 %d 行 %s（跳过 %d 行）"
      % (checked, len(mismatch), mismatch[:5], skipped))

# ── 市场温度：全池分位中位数（分位越低越便宜 → 星级越高）────────────────
rated = [r for r in all_rows if r["分位%"] is not None]
vals = sorted(r["分位%"] for r in rated)
if vals:
    n = len(vals)
    mid = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    stars = 5 if mid < 20 else 4 if mid < 40 else 3 if mid < 60 else 2 if mid < 80 else 1
    green_n = sum(1 for r in rated if r["档位"] == "绿档")
    red_n = sum(1 for r in rated if r["档位"] == "红档")
    print("市场温度 %s%s　全池分位中位数 %.1f%%　绿 %d/%d　红 %d/%d　(%d 个有效标的 · %s · %s)" % (
        "★" * stars, "☆" * (5 - stars), mid, green_n, len(rated), red_n, len(rated),
        len(rated), MEASURE, WINDOW))
else:
    print("市场温度：无有效分位（预热缓存未命中或窗口不足）")

cols = ["组", "名称", "PE", "PB", "股息率%", "分位%", "档位", "数据日期", "窗口", "样本"]
order = {"绿档": 0, "黄档": 1, "红档": 2, "—": 3}
shown = sorted(all_rows, key=lambda r: (order.get(r["档位"], 3),
                                        r["分位%"] if r["分位%"] is not None else 999))
try:
    import pandas as pd
    from IPython.display import display

    def _hl(s):
        color = {"绿档": "#1a7f37", "黄档": "#9a6700", "红档": "#bc4c00"}
        return ["color:%s;font-weight:bold" % color.get(v, "inherit") if c == "档位" else ""
                for c, v in zip(s.index, s)]

    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in shown])
    display(df.style.apply(_hl).hide(axis="index"))
    for g in ("宽基", "行业", "红利"):
        sub = [r for r in shown if r["组"] == g]
        if sub:
            print("—— %s ——" % g)
            display(pd.DataFrame([{c: r.get(c) for c in cols} for r in sub])
                    .style.apply(_hl).hide(axis="index"))
except ImportError:
    for r in shown:
        print("  ".join(str(r.get(c)) for c in cols))
print("档位=该键自身历史分位（<30% 绿 / 30~70% 黄 / >70% 红），估值参考区间非官方阈值；"
      "分位=周频整体法序列；股息率无历史不出分位；不构成投资建议。")"""),
    md("""## 二、通道拨测（按需能力）

`probe(symbol)` 对任意场内 ETF/指数键出价格通道：前复权日 K → 份额折算跳变清理 →
μ±2σ 通道、z 值、近 3 年分位；`backtest=True` 附 μ∓1σ 单轮机械回看（限价成交、T+1、
收盘口径；**算法演示，非预测**）。"""),
    code("""def clean_series(closes, dates, jump=0.25):
    \"\"\"qfq 不处理份额折算：单日 |涨跌|>jump 的断点之后才是统计纯净子窗口。\"\"\"
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev and abs(closes[i] / prev - 1) > jump:
            return closes[i:], dates[i:], f"自{dates[i]}（剔除份额折算跳变）"
    return closes, dates, ""


def channel(closes: list[float]) -> dict:
    \"\"\"均值 ± 1σ/2σ 通道 + z 值 + 分位（σ=总体标准差 ÷N）。\"\"\"
    n = len(closes)
    mu = sum(closes) / n
    sd = math.sqrt(sum((c - mu) ** 2 for c in closes) / n) or 1e-9
    last = closes[-1]
    z = (last - mu) / sd
    pct = sum(1 for c in closes if c <= last) / n
    if z > 2:
        zone = "上轨上方"
    elif z > 1:
        zone = "上轨附近"
    elif z >= -1:
        zone = "通道内"
    elif z >= -2:
        zone = "下轨附近"
    else:
        zone = "下轨下方"
    return {"mu": mu, "sd": sd, "lower1": mu - sd, "upper1": mu + sd,
            "lower2": max(0.0, mu - 2 * sd), "upper2": mu + 2 * sd,
            "z": z, "pct": pct, "zone": zone, "n": n}


def backtest_band(bars: list[dict], buy: float, sell: float) -> dict:
    \"\"\"μ∓1σ 单轮回看：限价成交（跳空按更优价）、T+1 当日不卖、收盘口径持仓。\"\"\"
    n = len(bars)
    i = 0
    while i < n and not (bars[i]["low"] <= buy):
        i += 1
    if i >= n:
        return {"traded": False, "distance_to_buy": buy / bars[-1]["close"] - 1}
    fill = min(bars[i]["open"], buy)
    holding = [bars[i]["close"]]
    j = i + 1
    sell_fill = None
    while j < n:
        holding.append(bars[j]["close"])
        if bars[j]["high"] >= sell:
            sell_fill = max(bars[j]["open"], sell)
            break
        j += 1
    mdd, peak = 0.0, fill
    for c in holding:
        peak = max(peak, c)
        mdd = max(mdd, 1 - c / peak)
    if sell_fill is None:
        return {"traded": True, "ret": holding[-1] / fill - 1, "days": len(holding),
                "mdd": mdd, "still_holding": True}
    return {"traded": True, "ret": sell_fill / fill - 1, "days": len(holding),
            "mdd": mdd, "still_holding": False}


def probe(symbol: str, n: int = 760, backtest: bool = True, plot: bool = True) -> dict:
    \"\"\"按需拨测：symbol = 场内 ETF 代码（如 510310）或指数键（如 index.hs300）。

    极值与回看全部基于**日线 OHLC**：窗口最高/最低取日 K 的 high/low（含日期），
    回看买卖触发用日内 low/high（限价成交语义），通道统计仍用收盘序列。
    \"\"\"
    bars_raw = cli.kline.bars(symbol, n=n, adj="qfq")
    rows = bars_raw.get("bars", bars_raw) if isinstance(bars_raw, dict) else bars_raw
    rows = sorted(rows or [], key=lambda r: str(r.get("date") or r.get("samplingTs") or ""))
    bars = [{"date": str(r.get("date") or "")[:10],
             "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])}
            for r in rows if r.get("close")]
    # 折算跳变清理：整行截断（保持 OHLC 对齐），qfq 已消除大部分折算，>25% 残留再兜底
    note = ""
    for i in range(1, len(bars)):
        prev = bars[i - 1]["close"]
        if prev and abs(bars[i]["close"] / prev - 1) > 0.25:
            bars, note = bars[i:], f"自{bars[i]['date']}（剔除份额折算跳变）"
            break
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    ch = channel(closes)
    out = {"symbol": symbol, "n": ch["n"], "note": note, **ch}
    # 日线极值（high/low 口径，含日期）
    hi = max(bars, key=lambda b: b["high"])
    lo = min(bars, key=lambda b: b["low"])
    out["window_high"] = {"price": hi["high"], "date": hi["date"]}
    out["window_low"] = {"price": lo["low"], "date": lo["date"]}
    if backtest and ch["n"] >= 120:
        bt = backtest_band(bars, ch["lower1"], ch["upper1"])
        out["backtest"] = bt
    if plot:
        fig, ax = plt.subplots(figsize=(8.6, 4.4), dpi=110)
        ax.axhspan(ch["lower1"], ch["upper1"], facecolor="#dbeafe", alpha=0.55, zorder=0)
        ax.axhspan(ch["lower2"], ch["lower1"], facecolor="#eff6ff", alpha=0.45, zorder=0)
        ax.axhspan(ch["upper1"], ch["upper2"], facecolor="#eff6ff", alpha=0.45, zorder=0)
        for v, lab, ls in ((ch["lower2"], "-2σ", ":"), (ch["lower1"], "-1σ", "--"),
                           (ch["mu"], "μ", "-"), (ch["upper1"], "+1σ", "--"),
                           (ch["upper2"], "+2σ", ":")):
            ax.axhline(v, color="#8b949e", lw=0.9, ls=ls, alpha=0.85, zorder=1)
        x = list(range(len(closes)))
        ax.plot(x, closes, color="#1f2328", lw=1.2, zorder=2)
        ax.scatter([x[-1]], [closes[-1]], color="#c2410c", s=26, zorder=3)
        ax.set_title(f"{symbol} 价格通道拨测（μ±2σ{('·' + note) if note else ''}）　"
                     f"z={ch['z']:+.2f}  近3年分位 {ch['pct'] * 100:.1f}%  {ch['zone']}",
                     fontsize=11)
        step = max(1, len(x) // 8)
        ax.set_xticks(x[::step])
        ax.set_xticklabels(dates[::step], fontsize=8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        plt.tight_layout()
        plt.show()
    print(f"[极值·日线·前复权口径] 窗口最高 {out['window_high']['price']:.3f} @{out['window_high']['date']}  "
          f"最低 {out['window_low']['price']:.3f} @{out['window_low']['date']}")
    bt = out.get("backtest")
    if bt and bt.get("traded"):
        sign = "+" if bt["ret"] >= 0 else ""
        tail = "仍在持仓" if bt.get("still_holding") else "已出场"
        print(f"[回看·算法演示非预测] μ∓1σ 单轮：收益 {sign}{bt['ret'] * 100:.2f}%  "
              f"持仓 {bt['days']} 日  最大回撤 {bt['mdd'] * 100:.2f}%  {tail}")
    elif bt:
        print(f"[回看] 从未触发买轨，距买轨 {bt['distance_to_buy'] * 100:+.1f}%")
    return out


# 按需调用示例（改成任何你关注的标的）：
_ = probe("510310", backtest=True)   # 沪深300ETF
"""),
    md("""## 三、口径与免责

- 估值=整体法（Σ市值/Σ盈利），平台指数域预热计算，与主流终端实测差 <1%（2026-11-07）；
- 分位=最新值在周频整体法序列中的位置（0=最低，1=最高），样本 <60 点不给出；
- 档位=盈利收益率法三档参考区间，行业通行规则，**非官方阈值**；
- 回看为日线 OHLC 限价单模拟（触发用日内 low/high），**算法演示，非预测**；
- 全部内容为数据整理与研究参考，**不构成任何投资建议**。"""),
]


def main() -> None:
    nb = {"cells": CELLS, "metadata": {"kernelspec": {"display_name": "Python 3",
                                                      "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = REPO / "docs" / "notebooks" / "index_daily.ipynb"
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
