"""单位契约层：目录声明（units/ranges/checks）→ 全库单点换算 + 返回前校验。

上游脚本永远输出其原有单位（如 statement_compare.diffp 百分数、kline.volume 手——
仅 cn/ETF，港美上游即股），本模块是唯一的换算点：call() 取回脚本原值后，按域目录的
声明把非基础单位换成基础单位，并对声明过 range 的字段做量级守护、对 checks 里的
关系不变量做精确校验。

基础单位约定（全库一致）：
  比率/涨跌幅/占比 = 小数（0.332 = 33.2%）
  金额/价格/市值   = 元（报表原币）
  股数/成交量      = 股
  时间 = 天；倍数 = 倍

声明位置（域 YAML，schema 见 _catalog/schema/domain.schema.json）：
  function 级 units:   {字段: percent|yi_yuan|lot}  仅声明"需换算"的非基础单位
  function 级 ranges:  {字段: [lo, hi]}             宽松量级界，只拦 ×100 类量级错
  function 级 checks:  [不变量 id]                   引用 CHECKS 注册表（Python 函数）
  metric 级 unit/range: 精选指标同语义（IndicatorApi 消费）
"""
from __future__ import annotations

from typing import Any

from wmshare.errors import CatalogError, DataError

# unit token → 换算因子（脚本原值 × 因子 = 基础单位值）
CONVERSIONS: dict[str, float] = {
    "percent": 0.01,   # 百分数 → 小数（14.67 → 0.1467）
    "yi_yuan": 1e8,    # 亿元 → 元
    "lot": 100.0,      # 手 → 股（A 股 1 手 = 100 股）
}

ESCAPE_HINT = ('如需原始口径：_raw=True（上游原始行）或 _units="native"（保留上游原单位）；'
               '或 Client(validate=False) 关闭校验。')


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: Any) -> float | None:
    """数值则返回（bool 除外），否则 None——供 mypy 收窄的运行时守卫。"""
    return v if _is_num(v) else None


def _scaled(x: Any, factor: float) -> Any:
    n = _num(x)
    return x * factor if n is not None else x


def is_index_symbol(symbol: str | None) -> bool:
    """是否指数键（与上游 ``index_quote_bridge.xs::kline.is_index_sym`` 对齐）。

    识别（大小写不敏感）：``index.*`` 前缀、``*.INDEX`` 后缀，以及 6 位
    ``399xxx`` 深证指数裸码（可带 .SH/.SZ/.BJ 交易所后缀）。刻意不把
    ``000001`` 一类歧义裸码当指数，避免误伤个股与 ETF。

    指数点位行的 volume 是成分股聚合量、amount 是聚合成交额，既不以「手」
    披露，也不满足个股 ``volume×close≈amount`` 关系；调用方据此收窄守护。
    """
    if not symbol:
        return False
    s = str(symbol).strip()
    if not s:
        return False
    u = s.upper()
    if u.startswith("INDEX."):
        return True
    if u.endswith(".INDEX"):
        # 只认「6 位数字 .INDEX」：任意 foo.INDEX 若被当成指数会跳过守护，
        # 比漏判更危险（上游桥接的合法形态是 index.* 与 399xxx / 000300.INDEX）。
        head = u[: -len(".INDEX")]
        return len(head) == 6 and head.isdigit()
    bare = u
    for prefix in ("CN.", "SH.", "SZ.", "BJ."):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    for suffix in (".SH", ".SZ", ".BJ"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    # 收紧为纯数字：误判成指数会跳过守护，比漏判更危险
    return len(bare) == 6 and bare.startswith("399") and bare.isdigit()


def convert_field(token: str, v: Any) -> Any:
    """按声明把一个字段值换成基础单位；dict（期间→值）逐项、list 逐项；
    None/非数值原样返回。"""
    factor = CONVERSIONS[token]
    if isinstance(v, dict):
        return {k: _scaled(x, factor) for k, x in v.items()}
    if isinstance(v, list):
        return [_scaled(x, factor) for x in v]
    return _scaled(v, factor)


def _fmt_range(bounds: list[Any]) -> str:
    lo, hi = bounds
    return f"[{lo}, {hi}]"


def _check_bounds(v: Any, bounds: list[Any], *, fname: str, where: str) -> None:
    """量级守护：宽松界，只拦 ×100 类量级错（换算声明写错会在这里自动暴露）。"""
    lo, hi = float(bounds[0]), float(bounds[1])
    values = v.values() if isinstance(v, dict) else [v]
    for x in values:
        if _is_num(x) and not (lo <= x <= hi):
            raise DataError(
                f"{fname}: 字段 {where}={x!r} 超出声明范围 {_fmt_range(bounds)}"
                f"（量级守护，疑似单位口径不符）。{ESCAPE_HINT}",
                code="range")


# ---- 命名不变量（行内自洽，无需跨请求状态） ----
def _check_diffp_ratio(row: dict, fname: str, path: str) -> None:
    """statement_compare 行：diffp（已换算为小数）≈ diff / c（合并值），相对误差 1%。"""
    c, d, p = row.get("c"), row.get("diff"), row.get("diffp")
    if not (isinstance(c, dict) and isinstance(d, dict) and isinstance(p, dict)):
        return
    for k, pv in p.items():
        f_pv, f_cv, f_dv = _num(pv), _num(c.get(k)), _num(d.get(k))
        if f_pv is None or f_cv is None or f_dv is None or abs(f_cv) < 1e-9:
            continue
        expected = f_dv / f_cv
        if abs(f_pv - expected) > max(1e-6, abs(expected) * 0.01):
            raise DataError(
                f"{fname}: 不变量 diffp_ratio 违例（{path or '行'} {k}）："
                f"diffp={pv!r} 与 diff/c={expected:.6g} 不一致，疑似口径变化。{ESCAPE_HINT}",
                code="invariant")


def _check_volume_amount(row: dict, fname: str, path: str) -> None:
    """K 线行：volume（已换算为股）× close ≈ amount（元），容 close≠VWAP 的偏离。"""
    f_v, f_close, f_amt = (_num(row.get("volume")), _num(row.get("close")),
                           _num(row.get("amount")))
    if f_v is None or f_close is None or f_amt is None or f_amt == 0 or f_close <= 0:
        return
    ratio = f_v * f_close / f_amt
    if not 0.4 <= ratio <= 2.5:
        raise DataError(
            f"{fname}: 不变量 volume_amount 违例（{path or '行'}）："
            f"volume×close/amount={ratio:.4g}，不在 [0.4, 2.5]（疑似 volume 单位变化）。{ESCAPE_HINT}",
            code="invariant")


CHECKS: dict[str, Any] = {
    "diffp_ratio": _check_diffp_ratio,
    "volume_amount": _check_volume_amount,
}


def validate_meta(meta: dict, fname: str) -> None:
    """装载/调用前校验声明本身的合法性（未知 token/不变量 id 立即暴露，防 YAML 笔误）。"""
    for f, tok in (meta.get("units") or {}).items():
        if tok not in CONVERSIONS:
            raise CatalogError(
                f"{fname}: 字段 {f} 的单位声明 {tok!r} 不合法（可用：{sorted(CONVERSIONS)}）",
                code="unit")
    for cid in meta.get("checks") or []:
        if cid not in CHECKS:
            raise CatalogError(
                f"{fname}: 不变量 {cid!r} 不在注册表（可用：{sorted(CHECKS)}）", code="check")
    for f, bounds in (meta.get("ranges") or {}).items():
        if (not isinstance(bounds, list) or len(bounds) != 2
                or not all(_is_num(x) for x in bounds) or not bounds[0] <= bounds[1]):
            raise CatalogError(
                f"{fname}: 字段 {f} 的 range 声明 {bounds!r} 不合法（应为 [lo, hi] 数字对）",
                code="range")


def _metric_meta_valid(meta: dict, code: str) -> None:
    unit = meta.get("unit")
    if unit is not None and unit not in CONVERSIONS:
        raise CatalogError(
            f"指标 {code}: 单位声明 {unit!r} 不合法（可用：{sorted(CONVERSIONS)}）", code="unit")
    rng = meta.get("range")
    if rng is not None and (not isinstance(rng, list) or len(rng) != 2
                            or not all(_is_num(x) for x in rng) or not rng[0] <= rng[1]):
        raise CatalogError(f"指标 {code}: range 声明 {rng!r} 不合法（应为 [lo, hi] 数字对）",
                           code="range")


def finish_metric(value: Any, meta: dict | None, *, code: str,
                  validate: bool = True) -> Any:
    """精选指标单值：按声明换算单位并做范围守护；None 原样返回。"""
    if value is None:
        return value
    meta = meta or {}
    unit = meta.get("unit")
    if unit:
        value = convert_field(unit, value)
    if validate and meta.get("range"):
        _check_bounds(value, meta["range"], fname="indicator", where=code)
    return value


def apply_units(result: Any, meta: dict, *, fname: str, validate: bool = True,
                market: str = "cn", symbol: str | None = None) -> Any:
    """对一次目录调用的结果做单位换算（就地修改并返回）+ 量级/不变量校验。

    结果形态支持：行数组、单行 MAP、以及一层容器 MAP（如 forecast.snapshot 的
    yjkb/yjyg 子行）；未声明字段的嵌套结构继续下探，声明过的字段按数据处理。

    ``lot``（手→股）是 cn 专属换算：上游仅 A 股/ETF 以手披露成交量，港股/美股
    上游即股，再乘 100 会膨胀两个数量级（volume_amount 不变量会拦下）。因此
    market != "cn" 时跳过 lot 换算、其余声明（percent/yi_yuan）照常生效。

    ``symbol`` 为本次调用的标的（已归一）。指数点位行由上游 index_quote 桥接
    生成，volume 是成分股聚合量、amount 是聚合成交额，既不以「手」披露，
    也不满足个股 volume×close≈amount。故指数键下**只**剔除 lot 换算与
    volume_amount 不变量，percent/ranges/diffp_ratio 等其余守护一律保留；
    目录声明本身不改写（声明仍描述个股语义），避免污染 catalog 缓存。
    """
    validate_meta(meta, fname)
    units = meta.get("units") or {}
    ranges = meta.get("ranges") or {}
    checks = [(c, CHECKS[c]) for c in meta.get("checks") or []]
    declared = set(units) | set(ranges)
    if not declared and not checks:
        return result

    def apply_fields(row: dict, path: str, index_like: bool) -> None:
        for f, tok in units.items():
            if f not in row:
                continue
            if tok == "lot" and (market != "cn" or index_like):
                # 指数 volume 不是「手」，不能按个股口径 ×100
                continue
            row[f] = convert_field(tok, row[f])
        if validate:
            where = f"{path}." if path else ""
            for f, bounds in ranges.items():
                if f in row:
                    _check_bounds(row[f], bounds, fname=fname, where=f"{where}{f}")
            for cid, c in checks:
                if index_like and cid == "volume_amount":
                    # 指数 close 是点数、amount 是聚合成交额，不变量不适用
                    continue
                c(row, fname, path)

    def walk(node: Any, path: str, index_like: bool) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, path, index_like)
        elif isinstance(node, dict):
            apply_fields(node, path, index_like)
            for k, v in node.items():
                if k not in declared and isinstance(v, (dict, list)):
                    # 批量返回 {symbol: bar} 容器：按 key 逐子树判定，混合批里
                    # 指数与个股各走自己的口径。顶层 symbol 为指数时整体按指数
                    # 处理（单标的路径）；批量路径的 symbol 是中性锚点，故由 key
                    # 决定。不把 index_like 在这里重置，避免 {"bars": [...]} 这类
                    # 普通数据字段被误当成个股容器而重新 ×100。
                    child_index = index_like or (isinstance(k, str)
                                                 and is_index_symbol(k))
                    walk(v, f"{path}.{k}" if path else k, child_index)

    walk(result, "", is_index_symbol(symbol))
    return result
