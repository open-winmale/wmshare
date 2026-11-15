"""指标发现/分组的可选适配层。

设计边界（与现有 SDK 完全解耦）:
- 不修改 ``metrics.json``、``Catalog``、``IndicatorApi``、``Client`` 或 MCP。
- 只读取新增的 ``generated/metric_taxonomy.json`` sidecar，并调用现有
  ``cli.indicator.metrics`` 取数。
- 只有 ``unit_kind/period/window/caliber`` 完全一致、且没有 unknown/dead 的码
  才允许组合成一次 eval；其余码保持扁平，一行一个返回。
- ``group_id`` 只表示可以同批取数，不代表数值可直接相加/相除；跨码比较仍按
  ``topic/period/window/caliber`` 判断。

典型用法::

    from wmshare import demo_client
    from wmshare.indicator_adapter import IndicatorAdapter

    ad = IndicatorAdapter(demo_client())
    g = ad.combinable_groups(scope="stock", topic="valuation")
    rows = ad.table("600519", g["groups"][0]["codes"])

老接口 ``cli.indicator.get`` / ``cli.indicator.metrics`` 不受影响。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wmshare.catalog import Catalog, load
from wmshare.errors import CatalogError, UsageError

_MAX_CODES_PER_EVAL = 100
_UNKNOWN_FIELDS = ("period", "window", "unit_kind")
_COLUMNS = [
    "code", "value", "scope", "topic", "period", "window", "caliber",
    "stat", "unit_kind", "native_unit", "min_history", "status", "group_id",
    "combinable", "reason", "error",
]


@dataclass
class AdapterBatchResult:
    """``IndicatorAdapter.many`` 的返回值（仅适配层类型）。"""

    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    requests: int = 0
    requested: int = 0
    metric_meta: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_df(self) -> Any:
        """转 pandas.DataFrame：每标的一行，指标码为列。"""
        try:
            import pandas as pd  # optional dependency
        except ImportError as exc:  # pragma: no cover - 环境无 pandas
            raise UsageError(
                "to_df() 需要安装 pandas：pip install pandas", code="pandas") from exc
        rows = [{"symbol": sym, **values} for sym, values in self.results.items()]
        return pd.DataFrame(rows)


class IndicatorAdapter:
    """在现有 ``indicator.metrics`` 之上做发现、分组和扁平化取数。"""

    def __init__(self, cli: Any, catalog: Catalog | None = None) -> None:
        self.cli = cli
        self.catalog = catalog or getattr(cli, "catalog", None) or load()
        self._taxonomy = _load_taxonomy(self.catalog)
        self._by_code = {row["code"]: row for row in self._taxonomy["metrics"]}
        self._labels = _load_labels(self.catalog)
        self._units = _load_units(self.catalog)

    # ------------------------------------------------------------ 发现
    def scopes(self) -> list[dict[str, Any]]:
        """返回 scope 摘要（按 taxonomy.yaml 顺序）。"""
        counts: dict[str, int] = {}
        for row in self._by_code.values():
            counts[row["scope"]] = counts.get(row["scope"], 0) + 1
        return [{"id": key, "cn": self._labels["scopes"].get(key, key),
                 "count": counts.get(key, 0)}
                for key in self._labels["scopes"] if counts.get(key)]

    def topics(self, scope: str | None = None) -> list[dict[str, Any]]:
        """返回 topic 摘要；可按 scope 过滤。"""
        counts: dict[str, int] = {}
        for row in self._by_code.values():
            if scope is not None and row["scope"] != scope:
                continue
            counts[row["topic"]] = counts.get(row["topic"], 0) + 1
        return [{"id": key, "cn": self._labels["topics"].get(key, key),
                 "count": counts.get(key, 0)}
                for key in self._labels["topics"] if counts.get(key)]

    def metrics_by(self, scope: str | None = None, topic: str | None = None,
                   period: str | None = None, window: str | None = None,
                   unit_kind: str | None = None, market: str | None = None,
                   status: str = "active") -> list[dict[str, Any]]:
        """按分类字段筛选指标码；返回带 ``cn/markets/group_id`` 的条目。"""
        out: list[dict[str, Any]] = []
        for code, row in self._by_code.items():
            if scope is not None and row["scope"] != scope:
                continue
            if topic is not None and row["topic"] != topic:
                continue
            if period is not None and row["period"] != period:
                continue
            if window is not None and row["window"] != window:
                continue
            if unit_kind is not None and row["unit_kind"] != unit_kind:
                continue
            if status != "all" and row["status"] != status:
                continue
            base = self.catalog.metric(code) or {}
            markets = list(base.get("markets") or [])
            if market is not None and markets and market not in markets:
                continue
            item = self._entry_row(code, row, base)
            item.update({"cn": base.get("cn", ""), "markets": markets})
            native = (self._units.get(code) or {}).get("native_unit")
            if native and native != row["unit_kind"]:
                item["unit_note"] = (self._units.get(code) or {}).get("note", "")
            out.append(item)
        return sorted(out, key=lambda item: item["code"])

    def combinable_groups(self, scope: str | None = None, topic: str | None = None,
                          market: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """返回 ``{"groups": [...], "flat": [...]}``。

        只把同一 ``group_id`` 且无 unknown/dead 的码放进 groups；其余码进
        flat，并给出原因。任何 unknown 都不会被自动组合。
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        flat: list[dict[str, Any]] = []
        for code, row in self._by_code.items():
            if scope is not None and row["scope"] != scope:
                continue
            if topic is not None and row["topic"] != topic:
                continue
            base = self.catalog.metric(code) or {}
            markets = list(base.get("markets") or [])
            if market is not None and markets and market not in markets:
                continue
            if row["status"] != "active":
                flat.append({"code": code, "reason": "dead",
                             "cn": base.get("cn", ""), "scope": row["scope"],
                             "topic": row["topic"]})
                continue
            reason = _flat_reason(row)
            if reason is not None:
                flat.append({"code": code, "reason": reason,
                             "cn": base.get("cn", ""), "scope": row["scope"],
                             "topic": row["topic"]})
                continue
            gid = _group_id(row, markets)
            groups.setdefault(gid, []).append({
                "code": code, "cn": base.get("cn", ""),
                "scope": row["scope"], "topic": row["topic"],
            })
        group_rows = []
        for gid, members in groups.items():
            first = self._by_code[members[0]["code"]]
            base = self.catalog.metric(first["code"]) or {}
            group_rows.append({
                "group_id": gid,
                "unit_kind": first["unit_kind"],
                "period": first["period"],
                "window": first["window"],
                "caliber": list(first["caliber"]),
                "market": _market_of(list(base.get("markets") or [])),
                "codes": sorted(member["code"] for member in members),
                "count": len(members),
            })
        group_rows.sort(key=lambda item: (-item["count"], item["group_id"]))
        flat.sort(key=lambda item: item["code"])
        return {"groups": group_rows, "flat": flat}

    # ------------------------------------------------------------ 取数
    def table(self, symbol: str, codes: list[str], *, _df: bool = False,
              on_error: str = "raise") -> Any:
        """按显式 codes 取数；同组码合并，flat 码逐个取，返回长表。"""
        rows, _ = self._table_rows(symbol, codes, on_error=on_error)
        return _to_df(rows) if _df else rows

    def many(self, symbols: list[str], codes: list[str], *,
             batch_size: int | None = None, on_error: str = "raise") -> AdapterBatchResult:
        """多标的小列表取数；逐标的调用现有 ``indicator.metrics``。"""
        if not symbols:
            raise UsageError("symbols 不能为空", code="params")
        if any(not isinstance(symbol, str) or not symbol for symbol in symbols):
            raise UsageError("symbols 只能包含非空字符串", code="params")
        if batch_size is not None and (isinstance(batch_size, bool)
                                       or not isinstance(batch_size, int)
                                       or batch_size <= 0):
            raise UsageError("batch_size 必须是正整数", code="params")
        result = AdapterBatchResult(requested=len(symbols))
        for code in codes:
            row = self._by_code.get(code)
            if row is None:
                continue
            result.metric_meta[code] = {
                "scope": row["scope"], "topic": row["topic"],
                "period": row["period"], "window": row["window"],
                "caliber": list(row["caliber"]), "unit_kind": row["unit_kind"],
                "stat": _stat_of(code, (self.catalog.metric(code) or {}).get("cn", "")),
                "group_id": None if _flat_reason(row) else _group_id(
                    row, list((self.catalog.metric(code) or {}).get("markets") or [])),
            }
        size = batch_size or len(symbols)
        for batch in _chunked(symbols, size):
            for symbol in batch:
                rows, requests = self._table_rows(symbol, codes, on_error=on_error)
                result.requests += requests
                values: dict[str, Any] = {}
                for row in rows:
                    if row["status"] == "excluded" or row["error"]:
                        if row["error"]:
                            result.errors.append({
                                "symbol": symbol, "code": row["code"],
                                "error": row["error"],
                            })
                        continue
                    values[row["code"]] = row["value"]
                result.results[symbol] = values
        return result

    # ------------------------------------------------------------ 内部
    def _table_rows(self, symbol: str, codes: list[str],
                    *, on_error: str = "raise") -> tuple[list[dict[str, Any]], int]:
        if not isinstance(codes, list) or not codes:
            raise UsageError("codes 必须是非空 list", code="params")
        if on_error not in ("raise", "skip"):
            raise UsageError("on_error 只支持 'raise'/'skip'", code="params")
        ordered: list[str] = []
        for code in codes:
            if not isinstance(code, str):
                raise UsageError("codes 只能包含字符串", code="params")
            if code not in ordered:
                ordered.append(code)
        for code in ordered:
            if code not in self._by_code:
                raise CatalogError(f"未知指标 {code!r}（不在指标分类 sidecar 内）",
                                   code="metric")

        client_market = str(getattr(self.cli, "market", "cn") or "cn").lower()
        rows: dict[str, dict[str, Any]] = {}
        groups: dict[str, list[str]] = {}
        flat: list[str] = []
        requests = 0
        for code in ordered:
            row = self._by_code[code]
            base = self.catalog.metric(code) or {}
            markets = list(base.get("markets") or [])
            item = self._entry_row(code, row, base)
            if row["status"] == "dead":
                item.update(value=None, status="excluded", reason="dead")
                rows[code] = item
                continue
            if markets and client_market not in markets:
                item.update(value=None, status="excluded",
                            reason=f"market={client_market} 不适用（仅 {'/'.join(markets)}）")
                rows[code] = item
                continue
            reason = _flat_reason(row)
            item.update(value=None, status="active", reason=reason)
            rows[code] = item
            if reason is not None:
                flat.append(code)
            else:
                gid = _group_id(row, markets)
                groups.setdefault(gid, []).append(code)
                item["group_id"] = gid

        for gid, members in groups.items():
            for code in members:
                rows[code]["group_id"] = gid
                rows[code]["combinable"] = len(members) > 1
            for chunk in _chunked(members, _MAX_CODES_PER_EVAL):
                requests += 1
                try:
                    values = self.cli.indicator.metrics(symbol, chunk)
                except Exception as exc:  # noqa: BLE001 - on_error 需要保留原始错误
                    if on_error == "raise":
                        raise
                    for code in chunk:
                        rows[code]["error"] = str(exc)
                    continue
                if not isinstance(values, dict):
                    for code in chunk:
                        rows[code]["error"] = f"返回非 dict：{type(values).__name__}"
                    continue
                for code in chunk:
                    rows[code]["value"] = values.get(code)
        for code in flat:
            requests += 1
            try:
                values = self.cli.indicator.metrics(symbol, [code])
            except Exception as exc:  # noqa: BLE001
                if on_error == "raise":
                    raise
                rows[code]["error"] = str(exc)
                continue
            rows[code]["value"] = values.get(code) if isinstance(values, dict) else None
            if not isinstance(values, dict):
                rows[code]["error"] = f"返回非 dict：{type(values).__name__}"
            rows[code]["combinable"] = False
        return [rows[code] for code in ordered], requests

    def _entry_row(self, code: str, row: dict[str, Any],
                   base: dict[str, Any]) -> dict[str, Any]:
        native = (self._units.get(code) or {}).get("native_unit")
        return {
            "code": code,
            "value": None,
            "scope": row["scope"],
            "topic": row["topic"],
            "period": row["period"],
            "window": row["window"],
            "caliber": list(row["caliber"]),
            "stat": _stat_of(code, base.get("cn", "")),
            "unit_kind": row["unit_kind"],
            "native_unit": native or row["unit_kind"],
            "min_history": _min_history(row["window"]),
            "status": row["status"],
            "group_id": None,
            "combinable": False,
            "reason": None,
            "error": None,
        }


def _load_taxonomy(catalog: Catalog) -> dict[str, Any]:
    path = Path(catalog.root) / "generated" / "metric_taxonomy.json"
    if not path.is_file():
        raise CatalogError(
            f"指标适配层缺少 {path}；请升级/重新安装 wmshare，"
            "或运行 python tools/extract_metric_taxonomy.py 生成",
            code="taxonomy",
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"指标分类 sidecar 无法读取：{path}：{exc}",
                           code="taxonomy") from exc
    if doc.get("schema_version") != 1 or not isinstance(doc.get("metrics"), list):
        raise CatalogError(f"指标分类 sidecar 结构不兼容：{path}", code="taxonomy")
    return doc


def _load_labels(catalog: Catalog) -> dict[str, dict[str, str]]:
    path = Path(catalog.root) / "taxonomy.yaml"
    if not path.is_file():
        return {"scopes": {}, "topics": {}}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {"scopes": {}, "topics": {}}
    return {
        "scopes": {str(k): str(v) for k, v in (doc.get("scopes") or {}).items()},
        "topics": {str(k): str(v) for k, v in (doc.get("topics") or {}).items()},
    }


def _load_units(catalog: Catalog) -> dict[str, dict[str, Any]]:
    """单位台账：只覆盖与基础单位不一致的码；缺文件时表为空（不报错）。"""
    path = Path(catalog.root) / "units.yaml"
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {str(k): dict(v or {}) for k, v in (doc.get("overrides") or {}).items()}


def _flat_reason(row: dict[str, Any]) -> str | None:
    for field in _UNKNOWN_FIELDS:
        if row.get(field) == "unknown":
            return f"{field}=unknown"
    if "unknown" in (row.get("caliber") or []):
        return "caliber=unknown"
    return None


def _group_id(row: dict[str, Any], markets: list[str]) -> str:
    calibers = "+".join(sorted(row.get("caliber") or [])) or "-"
    return (f"{row['unit_kind']}|{row['period']}|{row['window']}|"
            f"{calibers}|{_market_of(markets)}")


def _market_of(markets: list[str]) -> str:
    return "+".join(sorted(markets)) if markets else "shared"


def _stat_of(code: str, cn: str) -> str:
    if "PCT" in code or "分位" in cn:
        return "percentile"
    if "_YOY" in code:
        return "yoy"
    if "_AVG" in code:
        return "avg"
    if "_MIN" in code:
        return "min"
    if "_TREND" in code:
        return "trend"
    if "_LAST" in code:
        return "last"
    return "plain"


def _min_history(window: str) -> str:
    return window if window in ("1y", "3y", "5y", "10y", "3q") else "none"


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _to_df(rows: list[dict[str, Any]]) -> Any:
    try:
        import pandas as pd  # optional dependency
    except ImportError as exc:  # pragma: no cover - 环境无 pandas
        raise UsageError(
            "_df=True 需要安装 pandas：pip install pandas", code="pandas") from exc
    return pd.DataFrame(rows, columns=_COLUMNS)
