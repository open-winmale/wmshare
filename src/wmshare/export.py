"""成品出口层：把信封/DataFrame/行数组一次写成可直接交付的文件。

wmshare 的门面返回的是数据（DataFrame/信封），不是产物。本模块补最后一公里：
同一份数据按扩展名落成 ``.md``（带口径表头的 Markdown）/ ``.csv`` / ``.xlsx`` /
``.png``，或一次写一整套（``write_bundle`` 附 ``manifest.json``）。

不进目录（``_catalog``）、不进 ``FRIENDLY_INDEX``/``COMPOSITE_METHODS``——这是
客户端落盘工具，不是数据接口，不参与取数合同与计数门禁。

单位口径随文件走：Markdown 表头固定输出 ``as_of`` 与「比率=小数、金额=元、
股数=股」约定。这是 wmshare 的差异点——交付物自带口径，收稿人不需要问
「0.03 是 3% 还是 0.03%」。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["to_markdown", "write", "write_bundle"]

#: Markdown 表格单文件展示上限；超出行提示换 csv/xlsx 取全量（防把终端当数据库）。
DEFAULT_MAX_ROWS = 50

#: 口径约定文案（与 wmshare/__init__ 模块文档同源：比率小数 / 金额元 / 股数股）。
_UNIT_NOTE = "单位口径：比率/涨跌幅/占比=小数（0.03=3%）、金额/价格=元、股数/成交量=股"


def _unwrap(data: Any) -> tuple[Any, str | None]:
    """归一输入：统一信封拆包，返回 ``(行数组/DataFrame/dict, as_of)``。

    识别 2.0 信封 ``{ok, as_of, data, meta}`` 与 ``{rows: [...]}`` 包装；
    其余形态原样透传（DataFrame/dict/标量由各写入器自行处理）。
    """
    as_of: str | None = None
    if isinstance(data, dict) and {"ok", "data"} <= set(data):
        as_of = str(data.get("as_of") or "") or None
        data = data.get("data")
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    return data, as_of


def _to_frame(data: Any) -> tuple[Any, str | None]:
    """行数组/DataFrame/扁平 dict → DataFrame（供 csv/xlsx/png/md 表格）。"""
    import pandas as pd

    rows, as_of = _unwrap(data)
    if isinstance(rows, list):
        return pd.DataFrame(rows), as_of
    if isinstance(rows, dict):
        # 扁平 MAP → 单行表；嵌套值 JSON 序列化进单元格，不丢字段
        flat = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                    else v) for k, v in rows.items()}
        return pd.DataFrame([flat]), as_of
    return rows, as_of          # DataFrame 原样；其它类型由调用方报错


def _cell(value: Any) -> str:
    """单元格转 Markdown：None 留空、竖线转义、换行压平。"""
    if value is None:
        return ""
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text


def _md_table(df: Any, max_rows: int) -> str:
    """DataFrame → Markdown 表（手写渲染，不依赖可选的 tabulate）。"""
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.head(max_rows).iterrows():
        out.append("| " + " | ".join(_cell(row[c]) for c in df.columns) + " |")
    total = len(df)
    if total > max_rows:
        out.append(f"\n（另 {total - max_rows} 行略；全量请落 .csv/.xlsx）")
    return "\n".join(out)


def to_markdown(data: Any, *, title: str = "wmshare 数据", as_of: str | None = None,
                notes: list[str] | None = None,
                max_rows: int = DEFAULT_MAX_ROWS) -> str:
    """信封/DataFrame/行数组 → 带「数据截至 + 单位口径」表头的 Markdown。

    :param data: 统一信封 / DataFrame / 行数组 / 扁平 dict（MAP）
    :param title: 一级标题
    :param as_of: 显式覆盖数据截至日（缺省取信封 ``as_of``）
    :param notes: 附加口径说明行（逐行追加在表头区）
    :param max_rows: 表格最多展示的行数
    """
    import wmshare

    frame, env_as_of = _to_frame(data)
    as_of = as_of or env_as_of or ""
    lines = [f"# {title}", ""]
    if as_of:
        lines.append(f"- 数据截至（as_of）：{as_of}")
    lines.append(f"- {_UNIT_NOTE}")
    lines.append(f"- 生成：wmshare {wmshare.__version__} · "
                 f"{datetime.now().isoformat(timespec='seconds')}")
    for note in notes or []:
        lines.append(f"- {note}")
    lines.append("")
    if frame is None or len(frame) == 0:
        lines.append("（无数据行）")
        return "\n".join(lines) + "\n"
    lines.append(_md_table(frame, max_rows))
    return "\n".join(lines) + "\n"


def write(data: Any, path: str | Path, *, title: str | None = None) -> Path:
    """按扩展名落盘：``.md`` / ``.csv`` / ``.xlsx`` / ``.png``，返回写入路径。

    - ``.md``：``to_markdown`` 成品（含 as_of 与单位口径表头）
    - ``.csv`` / ``.xlsx``：表格全量；xlsx 需 ``pip install "wmshare[excel]"``
    - ``.png``：matplotlib Figure 原样 savefig；DataFrame 渲染成表格图，
      需 ``pip install "wmshare[figures]"``

    缺可选依赖抛 ``UsageError(code="extra")`` 并给安装命令，不静默降级。
    """
    target = Path(path)
    suffix = target.suffix.lower()
    target.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".md":
        # str 直通：cbond.article 等产出的成品稿已是 Markdown 文本，原样落盘
        target.write_text(data if isinstance(data, str)
                          else to_markdown(data, title=title or target.stem),
                          encoding="utf-8")
        return target

    frame, _ = _to_frame(data)

    if suffix == ".csv":
        _require_frame(frame, suffix)
        frame.to_csv(target, index=False, encoding="utf-8-sig")
        return target

    if suffix == ".xlsx":
        _require_frame(frame, suffix)
        try:
            import openpyxl  # noqa: F401
        except ImportError as e:
            raise _extra_error("xlsx", "excel") from e
        frame.to_excel(target, index=False)
        return target

    if suffix == ".png":
        try:
            import matplotlib
        except ImportError as e:
            raise _extra_error("png", "figures") from e
        fig = data if hasattr(data, "savefig") else None
        if fig is not None:
            fig.savefig(target, dpi=150, facecolor="white", bbox_inches="tight")
            return target
        _require_frame(frame, suffix)
        _render_table_png(frame, target)
        return target

    raise _extra_error(suffix, "", unknown=True)


def _render_table_png(frame: Any, target: Path) -> None:
    """DataFrame → 简洁表格图（白底、居中，供直接贴进文档/聊天）。

    CJK 字体复用 ``cb.figures._font()`` 的五平台探测（macOS/Windows/Linux），
    不另造一套——否则 matplotlib 默认 DejaVu Sans 渲染中文全是方框。
    """
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    from wmshare.cb.figures import _font as _cjk_font

    n_rows = min(len(frame), DEFAULT_MAX_ROWS)
    cols = [str(c) for c in frame.columns]
    cell_text = [[_cell(frame.iloc[i][c]) for c in frame.columns]
                 for i in range(n_rows)]
    fig_w = min(2.0 + 1.1 * len(cols), 16.0)
    fig_h = max(1.0, 0.4 * (n_rows + 1) + 0.4)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    table = ax.table(cellText=cell_text, colLabels=cols, loc="center",
                     cellLoc="center")
    table.auto_set_font_size(False)
    font = _cjk_font()
    for cell in table.get_celld().values():
        cell.get_text().set_fontproperties(font)
        cell.get_text().set_fontsize(9)
    table.scale(1, 1.4)
    fig.savefig(target, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _require_frame(frame: Any, suffix: str) -> None:
    from wmshare.errors import UsageError

    if frame is None or not hasattr(frame, "columns"):
        raise UsageError(
            f".{suffix} 需要表格数据（DataFrame/行数组/信封）；"
            "标量或图形对象请改用 .md 或 .png", code="params")


def _extra_error(kind: str, extra: str, *, unknown: bool = False) -> Any:
    from wmshare.errors import UsageError

    if unknown:
        return UsageError(
            f"不支持的导出格式 {kind!r}；可选 .md/.csv/.xlsx/.png", code="params")
    return UsageError(
        f".{kind} 导出需要可选依赖：pip install \"wmshare[{extra}]\"", code="extra")


def write_bundle(items: dict[str, Any], out_dir: str | Path) -> dict[str, Path]:
    """一组成品一次落盘：``{文件名(带扩展名): 数据}`` → 目录 + ``manifest.json``。

    manifest 记录生成时间、wmshare 版本、每个文件的行数与数据截至日，
    收稿方可据此核对口径与新鲜度。返回 ``{文件名: 路径}``（含 manifest）。
    """
    import wmshare

    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    files: list[dict[str, Any]] = []
    as_of: str | None = None
    for name, data in items.items():
        path = write(data, d / name)
        written[name] = path
        frame, env_as_of = _to_frame(data)
        entry: dict[str, Any] = {"file": name,
                                 "rows": int(len(frame)) if frame is not None
                                 and hasattr(frame, "columns") else None}
        if env_as_of:
            entry["as_of"] = env_as_of
            as_of = as_of or env_as_of
        files.append(entry)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "wmshare_version": wmshare.__version__,
        "as_of": as_of,
        "files": files,
    }
    mpath = d / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    written["manifest.json"] = mpath
    return written
