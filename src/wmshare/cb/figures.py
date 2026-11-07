"""把事实包画成图：榜单表图、双低价差图、个券价格通道图。

matplotlib 不是本包的默认依赖——只有真要出图时才装::

    pip install "wmshare[figures]"

中文字体按平台候选链自动挑选，找不到时退回 matplotlib 默认字体（会缺字但不崩）。
水印文案可用 ``watermark=`` 覆盖，或传空串关掉。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .article import Facts

__all__ = ["render_all", "render_table", "render_scatter", "render_band", "WATERMARK"]

WATERMARK = "github.com/open-winmale/wmshare ; winmale.com"

INK, MUTED, GATE_GRAY = "#1f2328", "#8b949e", "#b1b6bd"
GREEN_BG, ORANGE_BG, GRAY_BG = "#e9f5ec", "#fcefe4", "#f0f1f3"
WARN_FG, GRAY_FG = "#bc4c00", "#6e7781"

NATURE_COLOR = {"偏债": ("#1a7f37", "偏债（税后到期收益率为正）"),
                "平衡": ("#9a6700", "平衡"),
                "偏股": ("#bc4c00", "偏股（价格≥130 且溢价≤15%）")}

_TABLE_COLS = [
    ("转债", 0.118), ("代码", 0.062), ("价格", 0.058), ("溢价率", 0.062), ("双低", 0.058),
    ("税后YTM", 0.064), ("规模(亿)", 0.062), ("年限", 0.050), ("强赎", 0.126),
    ("下修", 0.106), ("正股", 0.098), ("警示", 0.058),
]
_HDR_H, _CAP_H, _GAP_H = 0.028, 0.030, 0.012
_TITLE_H, _SUB_H, _FOOT_H = 0.062, 0.028, 0.090

_CALL_SHORT = {"met15": "已达标", "no_redeem": "公告不赎", "counting": "计数中",
               "redeem_announced": "强赎公告", "redeemed": "已强赎"}
_RESET_SHORT = {"proposal_pending": "提案待表决", "no_reset": "公告不下修",
                "reset_done": "已下修"}

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


def _plt() -> Any:
    try:
        import matplotlib
    except ImportError as e:  # pragma: no cover - 环境相关
        raise ImportError(
            "出图需要 matplotlib，请先安装：pip install \"wmshare[figures]\"") from e
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _font() -> Any:
    import matplotlib.font_manager as fm
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return fm.FontProperties(fname=path)
    return fm.FontProperties()


def _stamp(fig: Any, text: str) -> None:
    if text:
        fig.text(0.985, 0.006, text, ha="right", va="bottom",
                 fontsize=11, color="#3d434c", alpha=0.8)


def _trim(s: Any, n: int) -> str:
    s = str(s or "—")
    return s if len(s) <= n else s[: n - 1] + "…"


def _short_state(key: str, state: Any, kind: str) -> str:
    if kind == "call":
        if key in _CALL_SHORT:
            return _CALL_SHORT[key]
        return _trim(state, 9)
    if key == "proposed":
        import re
        m = re.search(r"(\d+)月(\d+)日", str(state or ""))
        return f"{m.group(1)}/{m.group(2)} 表决" if m else "提案待表决"
    return _RESET_SHORT.get(key) or _trim(state, 8)


def _row_meta(r: dict, fa: Facts) -> dict:
    """榜单行在图上要用的几个派生值（缺口径字段时给 None，不猜）。"""
    code = r["bondCode"]
    return {
        "price": fa.text(f"price_{code}"), "prem": fa.text(f"prem_{code}"),
        "dl": fa.text(f"dl_{code}"), "ytm": fa.opt(f"ytm_{code}") or "—",
        "nature": fa.opt(f"nat_{code}") or "",
    }


def render_table(fa: Facts, out_path: str | Path, *, title_date: str,
                 watermark: str = WATERMARK) -> Path:
    """12 列双低榜表图（行底色编码债性/ST/灰标，行高按内容铺满）。"""
    plt = _plt()
    from matplotlib.patches import Rectangle

    font = _font()
    plt.rcParams["axes.unicode_minus"] = False
    p = fa.p
    top = p.get("top") or []
    gates = p.get("gates") or {}
    cal = p.get("calendar") or {}
    n = max(1, len(top))

    fixed = _TITLE_H + _SUB_H + _HDR_H + _CAP_H + _FOOT_H + 4 * _GAP_H
    row_h = max(0.018, (1.0 - fixed) / n)
    total = fixed + n * row_h
    fig, ax = plt.subplots(figsize=(10.4, 10.4 * total * 1.02), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    def text(x: float, y: float, s: str, size: float = 8.0, color: str = INK,
             weight: str = "normal", ha: str = "center") -> None:
        ax.text(x, y, s, fontproperties=font, fontsize=size, color=color,
                ha=ha, va="center", weight=weight)

    widths = [w for _, w in _TABLE_COLS]
    xs, acc = [], 0.0
    for w in widths:
        xs.append(acc + w / 2)
        acc += w

    y = 1.0
    text(0.5, y - 0.028,
         f"转债双低榜前 {n} · 过闸后候选 {fa.opt('gate_passed_n') or '—'} 只 "
         f"· 双低均值 {fa.opt('mean_dl') or '—'}", size=14.0, weight="bold")
    text(0.5, y - 0.052,
         f"数据截至 {title_date} · 双低 = 价格 + 转股溢价率×100 · 按双低升序 · "
         f"已剔除 ST / 已满足强赎 / 剩余<0.5 年", size=8.6, color=MUTED)
    y -= _TITLE_H + _SUB_H + _GAP_H

    ax.add_patch(Rectangle((0.004, y - _HDR_H / 2 - 0.005), 0.992, _HDR_H,
                           facecolor="#f2f4f7", edgecolor="none", zorder=0))
    for i, (hdr, _) in enumerate(_TABLE_COLS):
        text(xs[i], y - _HDR_H / 2, hdr, size=8.0)
    y -= _HDR_H

    for r in top:
        code = r["bondCode"]
        meta = _row_meta(r, fa)
        is_st, gray = bool(r.get("is_st")), bool(r.get("near_expiry"))
        tl = r.get("stock_tl_rate_pct")
        warn = ("ST" if is_st else
                (f"{tl:.0f}%" if isinstance(tl, (int, float)) and tl >= 85 else "—"))
        bg = GRAY_BG if gray else (GREEN_BG if meta["nature"] == "偏债"
                                   else (ORANGE_BG if is_st else None))
        if bg:
            ax.add_patch(Rectangle((0.004, y - row_h / 2), 0.992, row_h,
                                   facecolor=bg, edgecolor="none", zorder=0))
        dist = r.get("redeem_dist_pct")
        if r.get("call_state_key") == "idle" and isinstance(dist, (int, float)):
            call_cell = f"距触发 +{dist:.0f}%" if dist >= 0 else f"已越线 {dist:.0f}%"
        else:
            call_cell = _short_state(r.get("call_state_key") or "", r.get("call_state"), "call")
        rs_key, floor = r.get("reset_state_key"), r.get("reset_floor")
        if rs_key and rs_key != "none":
            reset_cell = _short_state(rs_key, r.get("reset_state"), "reset")
        elif isinstance(floor, (int, float)):
            reset_cell = f"地板 {floor:.2f}"
        else:
            reset_cell = "无"
        yi, yrs = r.get("remain_size_yi"), r.get("years_to_expire")
        vals = [
            _trim(r["bondName"], 7), code, meta["price"], meta["prem"], meta["dl"], meta["ytm"],
            f"{yi:.1f}" if isinstance(yi, (int, float)) else "—",
            f"{yrs:.2f}" if isinstance(yrs, (int, float)) else "—",
            call_cell, reset_cell, _trim(r.get("stockName"), 6), warn,
        ]
        for i, v in enumerate(vals):
            color, weight = INK, ("bold" if i in (0, 4) else "normal")
            if i == 8 and not call_cell.startswith("距触发"):
                color = WARN_FG
            if i == 9 and reset_cell not in ("无", "—"):
                color = WARN_FG
            if i == 7 and gray:
                color = GRAY_FG
            if i == 11 and warn != "—":
                color, weight = WARN_FG, "bold"
            text(xs[i], y - row_h / 2, v, size=7.6, color=color, weight=weight)
        y -= row_h

    y -= _GAP_H
    text(0.008, y - _CAP_H / 2,
         "绿底=偏债（税后到期收益率为正）· 橙底=正股 ST · 灰底=剩余 0.5–1 年（灰标区）；"
         f"今日新增条款事件 {len(cal.get('newToday') or [])} 起，"
         f"未来 30 日 {len(cal.get('next30d') or [])} 个节点",
         size=7.8, color=MUTED, ha="left")

    ax.add_patch(Rectangle((0.004, 0.002), 0.992, 0.078, facecolor="#f6f8fa",
                           edgecolor="none", zorder=0))
    for i, line in enumerate((
        "口径：双低 = 价格 + 转股溢价率×100；在市 = 价与溢价率均非空，"
        "再叠剩余规模>0、到期日≥快照日；",
        "YTM 为税后口径：优先分年票息表 + 到期赎回价，缺表退回当期票息恒定，"
        "缺赎回价按面值 100（下限）；",
        "强赎/下修状态由公告事件与服务端计数推导，非交易所口径；"
        "全部内容为数据整理与研究参考，不构成任何投资建议。",
    )):
        text(0.012, 0.062 - i * 0.020, line, size=7.2, color=MUTED, ha="left")

    fig.subplots_adjust(left=0.008, right=0.992, top=0.998, bottom=0.002)
    _stamp(fig, watermark)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)
    return out


def render_scatter(fa: Facts, out_path: str | Path, *, title_date: str,
                   x_range: tuple[float, float] = (88.0, 200.0),
                   y_range: tuple[float, float] = (-10.0, 160.0),
                   watermark: str = WATERMARK) -> Path:
    """全市场双低价差图（分色=债性，灰叉=被剔除，空心=灰标）。"""
    plt = _plt()
    import matplotlib.font_manager as fm

    font = _font()
    sub = fm.FontProperties(fname=font.get_file(), size=7.2) if font.get_file() else font
    plt.rcParams["axes.unicode_minus"] = False
    x_min, x_max = x_range
    y_min, y_max = y_range

    pts = [q for q in (fa.p.get("scatter") or [])
           if q.get("price") is not None and q.get("prem_pct") is not None
           and x_min <= q["price"] <= x_max and y_min <= q["prem_pct"] <= y_max]
    fig, ax = plt.subplots(figsize=(9.2, 6.2), dpi=150)
    fig.patch.set_facecolor("white")
    passed = [q for q in pts if q.get("passed_gate")]
    gated = [q for q in pts if not q.get("passed_gate")]

    for nature, (color, label) in NATURE_COLOR.items():
        sel = [q for q in passed if q.get("nature") == nature and not q.get("near_expiry")]
        if sel:
            ax.scatter([q["price"] for q in sel], [q["prem_pct"] for q in sel], s=17, c=color,
                       alpha=0.62, edgecolors="none", label=f"{label} {len(sel)} 只", zorder=3)
    gray_sel = [q for q in passed if q.get("near_expiry")]
    if gray_sel:
        ax.scatter([q["price"] for q in gray_sel], [q["prem_pct"] for q in gray_sel], s=30,
                   facecolors="none", edgecolors="#6e7781", linewidths=0.9,
                   label=f"剩余 0.5–1 年（灰标）{len(gray_sel)} 只", zorder=4)
    if gated:
        ax.scatter([q["price"] for q in gated], [q["prem_pct"] for q in gated], s=20,
                   marker="x", c=GATE_GRAY, linewidths=0.9, alpha=0.75,
                   label=f"被闸门剔除 {len(gated)} 只（图内可见者）", zorder=2)

    labels: list[tuple[float, float, str]] = []
    for r in (fa.p.get("top") or [])[:5]:
        code = r["bondCode"]
        px, pp = fa.num(f"price_{code}"), fa.num(f"prem_{code}")
        if px is None or pp is None or not (x_min <= px <= x_max and y_min <= pp <= y_max):
            continue
        labels.append((px, pp, f"{r['bondName']}{code}"))
    placed: list[tuple[float, float]] = []
    for px, pp, text in labels:
        dy = 12.0
        for k in range(6):
            cand = (px, pp + dy / 3.2 * 10)
            if all(abs(cand[0] - a) > 4 or abs(cand[1] - b) > 7 for a, b in placed):
                break
            dy = 12.0 if dy < 0 else -30.0 - k * 6
        placed.append((px, pp + dy / 3.2 * 10))
        ax.annotate(text, (px, pp), textcoords="offset points", xytext=(8, dy),
                    fontproperties=font, fontsize=7.8, color=INK,
                    arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.6,
                                "shrinkA": 0, "shrinkB": 3})

    for xv, lab, yv in ((100, "100 元（面值）", y_max - 4), (110, "110 元", y_max - 26),
                        (130, "130 元", y_max - 4)):
        ax.axvline(xv, color="#d0d7de", lw=0.8, ls="--", zorder=0)
        ax.text(xv, yv, lab, fontproperties=font, fontsize=7.5, color=MUTED, ha="left", va="top")
    ax.axhline(0, color="#d0d7de", lw=0.8, ls="--", zorder=0)
    ax.text(x_min + 2, 1.5, "溢价率 0", fontproperties=font, fontsize=7.5, color=MUTED)
    xs = list(range(int(x_min), int(x_max) + 1, 2))
    for level in (150, 200):
        ax.plot(xs, [level - v for v in xs], color="#c8d1da", lw=0.8, ls=":", zorder=0)
        ax.text(x_max - 2, level - x_max + 2, f"双低 {level}", fontproperties=font,
                fontsize=7, color="#9aa4ad", ha="right", va="bottom")

    passed_all = fa.num("gate_passed_n")
    ax.set_title(
        f"全市场转债 双低价差图 · 画点 {len(pts)} 只（过闸 {len(passed)}"
        + (f" / 全市场 {int(passed_all)}" if passed_all else "") + "）· "
        f"双低均值 {fa.opt('mean_dl') or '—'}（数据截至 {title_date}）",
        fontproperties=font, fontsize=12.0, color=INK, pad=12)
    ax.set_xlabel("转债价格（元，面值 100 口径）", fontproperties=font, fontsize=9.5, color=INK)
    ax.set_ylabel("转股溢价率（%）", fontproperties=font, fontsize=9.5, color=INK)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    for t in ax.get_xticklabels() + ax.get_yticklabels():
        t.set_fontproperties(font)
        t.set_fontsize(8.5)
    ax.grid(True, color="#f0f2f5", lw=0.5)
    ax.legend(prop=fm.FontProperties(fname=font.get_file(), size=7.8) if font.get_file() else font,
              loc="upper right", frameon=False, labelspacing=0.4)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.text(0.01, 0.034,
             "越靠左下双低越小；斜虚线是双低等值线。轴范围截断"
             f"（价格 {x_min:.0f}–{x_max:.0f} 元、溢价率 {y_min:.0f}%–{y_max:.0f}%），越界点未画。",
             fontproperties=sub, color=MUTED)
    fig.text(0.01, 0.014, "分色为行业惯例规则，非官方阈值；数据整理与研究参考，不构成任何投资建议。",
             fontproperties=sub, color=MUTED)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.905, bottom=0.145)
    _stamp(fig, watermark)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)
    return out


def render_band(fa: Facts, out_path: str | Path, *, code: str, watermark: str = WATERMARK,
                klines: dict[str, dict] | None = None) -> Path | None:
    """单只债的价格通道图（μ±1σ/±2σ）。日 K 不新鲜时返回 None，不出图。"""
    plt = _plt()
    import matplotlib.font_manager as fm

    font = _font()
    sub = fm.FontProperties(fname=font.get_file(), size=7.2) if font.get_file() else font
    plt.rcParams["axes.unicode_minus"] = False
    band = (fa.p.get("featured_band") or {}).get(code)
    kl = (klines or fa.p.get("featured_klines") or {}).get(code)
    if not band or not kl or kl.get("error") or not kl.get("closes"):
        return None
    if kl.get("last_bar_date") != fa.p.get("date"):
        return None
    ch = band["channel"]
    dates, closes = list(kl["dates"]), list(kl["closes"])
    n = len(closes)
    x = list(range(n))

    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=150)
    fig.patch.set_facecolor("white")
    ax.fill_between(x, ch["lower2"], ch["upper2"], color="#e7f0fa", alpha=0.6, zorder=0,
                    label="μ±2σ")
    ax.fill_between(x, ch["lower1"], ch["upper1"], color="#cfe3f7", alpha=0.8, zorder=1,
                    label="μ±1σ")
    ax.axhline(ch["avg"], color="#8b949e", lw=0.9, ls="--", zorder=2,
               label=f"μ={ch['avg']:.2f}")
    ax.plot(x, closes, color="#0969da", lw=1.4, zorder=3, label="转债收盘价")
    ax.annotate(f"现价 {closes[-1]:.3f}\nz={ch['z']:+.2f} · {ch['zone_cn']}",
                xy=(0.012, 0.035), xycoords="axes fraction", fontproperties=font,
                fontsize=8.5, color=INK, ha="left", va="bottom",
                bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#d0d7de", "alpha": 0.85})
    ax.set_title(f"{band['name']}（{code}）上市以来价格通道 · {n} 个交易日 · "
                 f"数据截至 {fa.p.get('date')}", fontproperties=font, fontsize=12.5,
                 color=INK, pad=12)
    ax.set_ylabel("价格（元，面值 100 口径）", fontproperties=font, fontsize=9.5, color=INK)
    ticks = [i for i in range(0, n, max(1, n // 6))]
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][2:] for i in ticks], fontproperties=font, fontsize=8)
    for t in ax.get_yticklabels():
        t.set_fontproperties(font)
        t.set_fontsize(8.5)
    ax.grid(True, color="#f0f2f5", lw=0.5)
    ax.legend(prop=fm.FontProperties(fname=font.get_file(), size=8.5) if font.get_file() else font,
              loc="upper right", frameon=False, ncol=2)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.text(0.01, 0.045, "通道=均值±σ（总体标准差）；位置描述非买卖信号，"
             "不构成任何投资建议。",
             fontproperties=sub, color=MUTED, va="bottom")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.89, bottom=0.16)
    _stamp(fig, watermark)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor="white")
    plt.close(fig)
    return out


def render_all(fa: Facts, out_dir: str | Path, *, date: str,
               klines: dict[str, dict] | None = None,
               watermark: str = WATERMARK) -> dict[str, Path]:
    """一次出齐当期图：``{table, scatter, band_<code>...}``。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    title_date = str(fa.p.get("date") or "")
    outs: dict[str, Path] = {
        "table": render_table(fa, d / f"day{date}_cb_table.png",
                              title_date=title_date, watermark=watermark),
        "scatter": render_scatter(fa, d / f"day{date}_cb_scatter.png",
                                  title_date=title_date, watermark=watermark),
    }
    for code in (fa.p.get("featured_band") or {}):
        p = render_band(fa, d / f"day{date}_cbband_{code}.png", code=code,
                        klines=klines, watermark=watermark)
        if p is not None:
            outs[f"band_{code}"] = p
    return outs
