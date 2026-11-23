"""成品出口：把一次调用的结果直接写成 md/csv/xlsx 成品文件，不用再手拼。

前提：凭证可选——无凭证自动回落匿名试用（需网络）；xlsx 需 pip install "wmshare[excel]"，
png 需 "wmshare[figures]"
运行：python examples/21_cli_export.py
学到：to_markdown 的口径表头（as_of/单位约定）；write 按扩展名分派；
      write_bundle 一次落一整套文件并附 manifest.json（收稿方按它核对新鲜度）
文档：README「不写 Python：wmshare 命令行出成品」（命令行版同能力）、docs/API.md·组合接口
"""
import tempfile
from pathlib import Path

import wmshare
from wmshare import export
from wmshare import WmshareError


def main(cli=None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()
    out_dir = Path(tempfile.mkdtemp(prefix="wmshare_export_"))

    # ---- 段 1：一次调用 → 信封 → Markdown（口径表头自动带上）----
    print("--- to_markdown：指数估值分位（信封 → 带口径表头的成品）---")
    keys = ["index.hs300", "index.csi500", "index.csidividend"]
    rows = []
    for key in keys:
        t = cli.index.trend(key, "5y")
        if isinstance(t, dict) and t.get("ok") is False:
            print(f"  {key}: 缓存未命中，跳过（不伪造数值）")
            continue
        data = t.get("data") or {}
        rows.append({"key": key, "as_of": data.get("as_of"),
                     "pe_pct": data.get("pe_pct"), "pb_pct": data.get("pb_pct"),
                     "pe_pct_window": data.get("pe_pct_window")})
    if not rows:
        print("  无可用键（当前环境无该数据）；以下用最小示例继续演示出口能力")
        rows = [{"key": "index.hs300", "as_of": "2026-11-19",
                 "pe_pct": 0.1765, "pb_pct": 0.3277, "pe_pct_window": "5y"}]
    md = export.to_markdown(rows, title="指数估值分位（5y）",
                            notes=["pe_missing=True = 行业整体亏损，无 PE"])
    print("\n".join(md.splitlines()[:8]) + "\n  …")

    # ---- 段 2：write 按扩展名分派（同一份数据三种落法）----
    print("--- write：同一信封落 .md / .csv（xlsx 需 wmshare[excel]）---")
    p_md = export.write(rows, out_dir / "trend.md")
    p_csv = export.write(rows, out_dir / "trend.csv")
    print(f"  {p_md.name} {p_md.stat().st_size}B · {p_csv.name} {p_csv.stat().st_size}B")
    try:
        export.write(rows, out_dir / "trend.xlsx")
        print("  trend.xlsx 已写出")
    except WmshareError as e:
        print(f"  xlsx 跳过：{e}")

    # ---- 段 3：write_bundle 一套文件 + manifest.json ----
    print("--- write_bundle：多产物一次落盘，manifest 记录行数与 as_of ---")
    written = export.write_bundle(
        {"trend.md": rows, "trend.csv": rows,
         "summary.md": md},                      # 成品文本直通（str 原样落盘）
        out_dir / "bundle")
    manifest = (out_dir / "bundle" / "manifest.json").read_text(encoding="utf-8")
    print(f"  落盘 {len(written)} 个文件 → {out_dir / 'bundle'}")
    for line in manifest.splitlines():
        if line.strip().startswith(('"as_of"', '"file"', '"generated_at"')):
            print(f"  {line.strip()}")
    print("\n命令行一步到位：wmshare index trend --keys index.hs300,index.csi500 --out trend.md")
    print("全部输出为数据整理与研究参考，不构成任何投资建议。")


if __name__ == "__main__":
    main()
