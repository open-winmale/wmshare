"""数据目录装载与查询。

目录随包分发（wheel 内置，离线可用；运行时不依赖任何外部仓库，
唯一外部依赖是 OpenAPI 凭证 appid/client_secret）：
  _catalog/domains/*.yaml     域目录（合同见 _catalog/schema/domain.schema.json）
  _catalog/generated/*.json   机器清单（inventory=函数合同, metrics=$CODE 指标）

本模块只读目录，不做网络请求。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from wmshare.errors import CatalogError
from wmshare.units import _metric_meta_valid, validate_meta

_PACKAGE_CATALOG = Path(__file__).resolve().parent / "_catalog"
SUPPORTED_SCHEMA_VERSION = 2

#: 随包分发的全市场代码目录（companies.<market>.json，来自上游同步冻结）
SYMBOLS_DIR = "symbols"
SUPPORTED_SYMBOL_MARKETS = ("cn", "hk", "us")


def _check_schema(doc: dict, filename: str) -> None:
    version = doc.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise CatalogError(
            f"{filename}: schema_version={version} 与当前 SDK 支持的 "
            f"{SUPPORTED_SCHEMA_VERSION} 不兼容；请升级 wmshare 或重新安装",
            code="schema")


ALLOW_CUSTOM_CATALOG_ENV = "WMSHARE_ALLOW_CUSTOM_CATALOG"


def catalog_dir() -> Path:
    """定位随包分发的目录；自定义目录需显式开启双开关（见 SECURITY.md）。

    域 YAML 里的 ``normalize_with`` / ``xs.require`` 会被拼进服务端 XS 脚本，
    所以「换一个目录」不是加载配置，而是**替换待执行脚本**。默认拒绝，避免
    LLM 或环境变量被诱导指向任意目录造成 XS 注入。
    """
    env = os.environ.get("WMSHARE_CATALOG_DIR")
    if env:
        if os.environ.get(ALLOW_CUSTOM_CATALOG_ENV, "").strip().lower() \
                not in {"1", "true", "yes", "on"}:
            raise CatalogError(
                f"WMSHARE_CATALOG_DIR 需配合 {ALLOW_CUSTOM_CATALOG_ENV}=1 显式开启；"
                "自定义目录会改变服务端 XS 脚本内容，默认拒绝以防注入",
                code="catalog_dir")
        p = Path(env).expanduser().resolve()
        if not (p / "domains").is_dir():
            raise FileNotFoundError(f"WMSHARE_CATALOG_DIR={env} 下没有 domains/")
        for name in ("inventory.json", "metrics.json"):
            if not (p / "generated" / name).is_file():
                raise FileNotFoundError(
                    f"WMSHARE_CATALOG_DIR={env} 缺少 generated/{name}；"
                    "自定义目录必须包含与 domains 匹配的冻结目录")
        return p
    if (_PACKAGE_CATALOG / "domains").is_dir():
        return _PACKAGE_CATALOG
    raise FileNotFoundError(
        "包内 _catalog/ 缺失（安装损坏？）；或设置 WMSHARE_CATALOG_DIR 指向有效目录"
        f"并同时设置 {ALLOW_CUSTOM_CATALOG_ENV}=1")


class Catalog:
    def __init__(self, root: Path):
        self.root = root
        self.domains: dict[str, dict] = {}
        self._functions: dict[str, dict] = {}      # qualified name -> merged entry
        self._fn_domain: dict[str, dict] = {}      # qualified name -> domain doc
        self.inventory: dict = json.loads(
            (root / "generated" / "inventory.json").read_text(encoding="utf-8"))
        self.metrics: dict = json.loads(
            (root / "generated" / "metrics.json").read_text(encoding="utf-8"))
        _check_schema(self.inventory, "generated/inventory.json")
        _check_schema(self.metrics, "generated/metrics.json")
        self._inv_functions = {f["name"]: f for f in self.inventory["functions"]}
        self._metric_by_code = {m["code"]: m for m in self.metrics["metrics"]}
        self._load_domains()

    # ---- 装载 ----
    def _load_domains(self) -> None:
        docs = []
        self._yaml_functions: dict[str, dict] = {}
        for path in sorted((self.root / "domains").glob("*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.domains[doc["id"]] = doc
            docs.append(doc)
            for fn in doc.get("functions") or []:
                self._yaml_functions[fn["name"]] = fn
        # 两阶段：先收集全部 YAML 函数，再合并；这样 normalize_with 可以
        # 读取到同域内尚未合并的格式化函数 shape。
        self._metric_meta: dict[str, dict] = {}
        for doc in docs:
            for g in doc.get("metric_groups") or []:
                for m in g.get("metrics") or []:
                    if m.get("unit") or m.get("range"):
                        meta = {"unit": m.get("unit"), "range": m.get("range"),
                                "group": g["id"], "cn": m.get("cn", "")}
                        _metric_meta_valid(meta, m["code"])
                        self._metric_meta[m["code"]] = meta
        for doc in docs:
            for fn in doc.get("functions") or []:
                meta = {"units": fn.get("units"), "ranges": fn.get("ranges"),
                        "checks": fn.get("checks")}
                if any(meta.values()):
                    validate_meta(meta, fn["name"])
                merged = self._merge_with_inventory(fn, doc["id"])
                self._functions[fn["name"]] = merged
                self._fn_domain[fn["name"]] = doc

    def _normalizer_shape(self, name: str | None) -> dict | None:
        if not name:
            return None
        yaml_fn = self._yaml_functions.get(name) or {}
        ret = yaml_fn.get("returns") or {}
        if isinstance(ret.get("shape"), dict):
            return ret["shape"]
        inv = self._inv_functions.get(name) or {}
        return inv.get("returns_shape")

    def _merge_with_inventory(self, fn: dict, domain_id: str) -> dict:
        """精修条目 + inventory 原始合同（示例/returns_shape/min_args）合并视图。

        returns_shape 优先级：YAML returns.shape → normalize_with 目标函数的 shape
        → 当前函数 inventory shape。这样规范化后的公告/分红行在目录里也是扁平字段。
        """
        inv = self._inv_functions.get(fn["name"], {})
        ret = fn.get("returns") or {}
        shape = ret.get("shape") if isinstance(ret.get("shape"), dict) else None
        if shape is None:
            shape = self._normalizer_shape(fn.get("normalize_with"))
        return {
            **fn,
            "domain": domain_id,
            "inventory_example": inv.get("example", ""),
            "returns_shape": shape or inv.get("returns_shape"),
            "min_args": inv.get("min_args"),
            "sources": inv.get("sources", []),
        }

    def domain(self, domain_id: str) -> dict:
        try:
            return self.domains[domain_id]
        except KeyError:
            raise CatalogError(
                f"未知域 {domain_id!r}；已有：{sorted(self.domains)}", code="domain") from None

    def function(self, name: str) -> dict:
        try:
            return self._functions[name]
        except KeyError:
            raise CatalogError(
                f"未知函数 {name!r}；目录共 {len(self._functions)} 条", code="function") from None

    def metric(self, code: str) -> dict | None:
        """按代码取指标（O(1) 索引，不逐项扫描）。精选组条目带 unit/range 声明。"""
        base = self._metric_by_code.get(code)
        meta = self._metric_meta.get(code)
        if meta and base:
            return {**base, **meta, "cn": base.get("cn") or meta["cn"]}
        return meta or base

    def metric_meta(self, code: str) -> dict | None:
        """精选指标的单位/范围声明（unit/range/group），非精选代码返回 None。"""
        return self._metric_meta.get(code)

    def metrics_in_group(self, group_id: str) -> list[dict]:
        """某指标组的全部指标（code/cn），如 metrics_in_group("valuation")。"""
        for d in self.domains.values():
            for g in d.get("metric_groups") or []:
                if g["id"] == group_id:
                    return list(g.get("metrics") or [])
        raise CatalogError(f"未知指标组 {group_id!r}", code="group")

    def metric_groups(self) -> list[dict]:
        """全部指标组摘要（id/cn/domain/count）。"""
        out = []
        for d in self.domains.values():
            for g in d.get("metric_groups") or []:
                out.append({"id": g["id"], "cn": g["cn"], "domain": d["id"],
                            "count": len(g.get("metrics") or [])})
        return out

    def search(self, query: str, *, kind: str = "all", limit: int = 20) -> list[dict]:
        """按关键字（英文名/中文名，大小写不敏感）搜索函数与指标代码。

        kind: "all" | "function" | "metric"；返回 [{kind,name/code,cn,domain?}]。
        """
        q = query.strip().lower()
        if not q:
            return []
        out: list[dict] = []
        if kind in ("all", "function"):
            for name, fn in self._functions.items():
                if q in f"{name} {fn.get('cn', '')}".lower():
                    out.append({"kind": "function", "name": name,
                                "cn": fn.get("cn", ""), "domain": fn["domain"]})
        if kind in ("all", "metric"):
            for m in self.metrics["metrics"]:
                if q in f"{m['code']} {m.get('cn', '')}".lower():
                    out.append({"kind": "metric", "code": m["code"], "cn": m.get("cn", "")})
        return out[:limit]

    def functions_by_domain(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name, fn in self._functions.items():
            out.setdefault(fn["domain"], []).append(name)
        return {k: sorted(v) for k, v in out.items()}

    def namespaces(self) -> set[str]:
        """目录覆盖的 XS 命名空间（如 kline / notice / rptdom）。"""
        return {name.split(".", 1)[0] for name in self._functions}

    def inventory_params(self, name: str) -> list[dict]:
        """inventory 签名参数（L1 精简条目回退用）。

        xs:catalog 带 min_args 时前 min_args 个必填、其余可选；签名兜底条目全部必填。
        """
        inv = self._inv_functions.get(name) or {}
        params = inv.get("params") or []
        min_args = inv.get("min_args")
        out = []
        for i, p in enumerate(params):
            required = True if min_args is None else i < int(min_args)
            out.append({"name": p["name"], "type": p.get("type", "any"), "required": required})
        return out

    def stats(self) -> dict[str, Any]:
        kinds = {"raw": 0, "computed": 0}
        for fn in self._functions.values():
            k = fn.get("kind") or self.domains[fn["domain"]]["kind"]
            if k in kinds:
                kinds[k] += 1
        metric_total = sum(
            len(g.get("metrics") or []) for d in self.domains.values()
            for g in d.get("metric_groups") or [])
        return {
            "domains": len(self.domains),
            "functions": len(self._functions),
            "raw": kinds["raw"],
            "computed": kinds["computed"],
            "curated_metrics": metric_total,
            "metric_catalog_total": self.metrics.get("count", 0),
            "upstream_rev": self.inventory.get("upstream_rev"),
            "symbols": {m: self.symbols_count(m) for m in SUPPORTED_SYMBOL_MARKETS},
        }

    # ---- 装载辅助：_load_domains 时设置当前域 id ----
    def _set_loading(self, domain_id: str) -> None:
        self._loading_domain = domain_id

    # ---- 全市场代码目录（离线，随包分发）----
    def symbols_freshness(self, market: str | None = None) -> dict:
        """代码目录的数据新鲜度。

        返回 {"as_of": "2026-06-10", "markets": {"cn": "2026-06-10", ...}}；
        market 指定时只返回该市场的日期字符串（无 manifest 时 as_of 为 None）。
        名单为冻结快照，新股/更名可能滞后，精确性以运行时取数为准。
        """
        path = self.root / SYMBOLS_DIR / "manifest.json"
        markets: dict[str, str] = {}
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                for mk, info in (doc.get("markets") or {}).items():
                    if isinstance(info, dict) and info.get("as_of"):
                        markets[mk] = str(info["as_of"])
            except (json.JSONDecodeError, OSError):
                pass
        if market is not None:
            market = market.strip().lower()
            if market not in SUPPORTED_SYMBOL_MARKETS:
                raise CatalogError(
                    f"未知市场 {market!r}；支持：{list(SUPPORTED_SYMBOL_MARKETS)}",
                    code="market")
            return {"as_of": markets.get(market)}
        latest = sorted(markets.values())[-1] if markets else None
        return {"as_of": latest, "markets": markets}

    def _symbols_market(self, market: str) -> list[list[str]]:
        """读取某市场代码表并做轻量规范化缓存。行格式 [code, name, pinyin, abbr]。"""
        market = market.strip().lower()
        if market not in SUPPORTED_SYMBOL_MARKETS:
            raise CatalogError(
                f"未知市场 {market!r}；支持：{list(SUPPORTED_SYMBOL_MARKETS)}",
                code="market")
        cache: dict[str, list[list[str]]] = getattr(
            self, "_symbols_cache", None) or {}
        self._symbols_cache = cache
        if market not in cache:
            path = self.root / SYMBOLS_DIR / f"companies.{market}.json"
            if not path.exists():
                raise CatalogError(
                    f"代码目录缺失：{path}（安装损坏？本包版本可能不含 symbols/）",
                    code="symbols")
            rows = json.loads(path.read_text(encoding="utf-8"))
            if market == "us":
                # us 行为 [code, cn_name, pinyin, abbr]，中文名可能为空 → 回退代码本身
                cache[market] = [
                    [str(r[0]), (str(r[1]).strip() or str(r[0])),
                     str(r[2] or ""), str(r[3] or "")]
                    for r in rows if r and str(r[0]).strip()
                ]
            else:
                cache[market] = [
                    [str(r[0]), str(r[1]).strip(), str(r[2] or ""), str(r[3] or "")]
                    for r in rows if r and str(r[0]).strip() and str(r[1]).strip()
                ]
        return cache[market]

    def symbols_set(self, market: str) -> set[str]:
        """某市场代码集合（用于批量前的跨市场校验；带缓存）。"""
        cache: dict[str, set[str]] = getattr(self, "_symbols_set_cache", None) or {}
        self._symbols_set_cache = cache
        key = market.strip().lower()
        if key not in cache:
            cache[key] = {row[0] for row in self._symbols_market(key)}
        return cache[key]

    def symbols_count(self, market: str = "cn") -> int:
        """某市场代码表条数（cn/hk/us）。"""
        return len(self._symbols_market(market))

    def symbol(self, market: str, code: str) -> dict | None:
        """按代码精确查一条（A股6位/港股5位/美股字母代码）。未命中返回 None。"""
        code = code.strip()
        for row in self._symbols_market(market):
            if row[0] == code:
                return {"market": market, "code": row[0], "name": row[1],
                        "pinyin": row[2], "abbr": row[3]}
        return None

    def symbols_search(self, query: str, market: str = "cn", limit: int = 20) -> list[dict]:
        """按 代码/名称/全拼/拼音首字母 搜索标的（大小写不敏感，按匹配质量排序）。

        匹配优先级：精确代码 > 代码前缀 > 名称前缀 > 名称包含 > 缩写包含
        > 全拼包含。全拼允许任意子串（如 "maotai" 命中 guizhoumaotai）——
        用户很少记得全拼开头，按词中段搜才是常态。
        离线可用、零网络零额度；名单为随包冻结快照，新股可能有滞后。
        """
        query = (query or "").strip()
        if not query:
            return []
        q = query.casefold()
        scored: list[tuple[int, dict]] = []
        for code, name, pinyin, abbr in self._symbols_market(market):
            name_cf = name.casefold()
            if code == q:
                rank = 0
            elif code.startswith(q):
                rank = 1
            elif name_cf.startswith(q):
                rank = 2
            elif q in name_cf:
                rank = 3
            elif abbr and q in abbr:
                rank = 4
            elif pinyin and q in pinyin:
                rank = 5
            else:
                continue
            scored.append((rank, {"market": market, "code": code, "name": name,
                                  "pinyin": pinyin, "abbr": abbr}))
        scored.sort(key=lambda t: (t[0], t[1]["code"]))
        return [item for _, item in scored[:limit]]


_loaded_cache: dict[str, Catalog] = {}


def load(path: str | os.PathLike | None = None) -> Catalog:
    """装载目录。默认自动定位；可传 catalog 目录或仓根。

    同一路径进程内缓存单例（目录随包只读，重复解析 1MB JSON/YAML 纯浪费）；
    需要独立实例时直接构造 `Catalog(dir)`。
    """
    p = Path(path).expanduser().resolve() if path else catalog_dir()
    if (p / "domains").is_dir():
        target = p
    elif (p / "catalog" / "domains").is_dir():
        target = p / "catalog"
    else:
        raise FileNotFoundError(f"{p} 下未找到 domains/")
    cat = _loaded_cache.get(str(target))
    if cat is None:
        cat = _loaded_cache[str(target)] = Catalog(target)
    return cat
