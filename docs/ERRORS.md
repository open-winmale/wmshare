# 错误码与异常处理

本页由 `tools/gen_errors.py` 从源码扫描生成（禁止手改）：客户端 `code="..."` 字面量 + 服务端配额码。异常层级见 [`src/wmshare/errors.py`](../src/wmshare/errors.py)。

## 1. 异常层级

| 异常 | 父类 | 典型触发 | 可重试 |
|---|---|---|---|
| `WmshareError` | `RuntimeError` | 全部 SDK 异常的基类（带 `code`/`status`） | — |
| `AuthError` | `WmshareError` | 凭证缺失/无效/被拒（400/401/403） | 否 |
| `UsageError` | `WmshareError` | 调用方式/参数错误 | 否 |
| `LimitError` | `WmshareError` | 体积/窗口超限；服务端限流 429 | 视 `code`（`rate_limited` 可重试） |
| `QuotaError` | `LimitError` | 配额耗尽（周钱包/当日额度/洞察点数） | **否**（重试无效） |
| `TransportError` | `WmshareError` | 连接/超时（重试耗尽） | 是 |
| `ServerError` | `WmshareError` | 服务端 5xx | 是 |
| `ApiError` | `WmshareError` | 业务错误（success=false / 其他 4xx） | 视 `status` |
| `DataError` | `WmshareError` | 单位量级/关系不变量校验失败 | 否 |
| `StreamResetError` | `WmshareError` | 订阅进度超出保留期 | 否（需重置进度） |
| `CatalogError` | `WmshareError`, `KeyError` | 目录中不存在该函数/指标 | 否 |

## 2. 错误码字典

### 参数与调用

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `check` | 目录 `checks` 声明非法（未注册的检查器） | 否 | 登记检查器后再声明 |
| `dataframe` | 结果形态无法转 DataFrame | 否 | 改用 `_raw=True` 取原始行 |
| `domain` | 数据域不存在 | 否 | 用 `cat.domains` 核对 |
| `eval` | XS 求值表达式构造失败 | 否 | 检查参数名/字面量转义 |
| `freq` | 频率参数不被该数据面支持（如指数周/月 K） | 否 | 改用日频后自行重采样 |
| `function` | 目录函数不存在或签名不匹配 | 否 | 用 `cat.function` 核对 |
| `group` | 参数分组不合法 | 否 | 按函数签名传参 |
| `limit` | 客户端 `max_limit` 或单次请求体积超限 | 否 | 用 `batch_all()` 分批，或 `Client(max_limit=None)` 显式放开 |
| `market` | 市场参数不合法（只支持 cn/hk/us） | 否 | 按市场分别建 Client |
| `metric` | 指标码不存在或不可用 | 否 | `cat.search` / `cat.function` 先查目录 |
| `params` | 参数名/类型/取值不合法（含 `_fields` 未知字段） | 否 | 按消息修正参数；`_fields` 可用字段见报错列表 |
| `range` | 日期/条数超出允许区间（如区间上限 5 年） | 否 | 缩小窗口或分批；起止日期需成对提供 |
| `schema` | 目录 schema 校验失败 | 否 | 按 `validate_catalog` 报错修正 |
| `shape` | 返回形状声明与 inventory 不一致 | 否 | 重跑 extractor 生成 inventory |
| `symbol` | 标的代码不合法或无法归一 | 否 | 检查代码格式与市场 |
| `symbols` | 批量标的集合不合法（空集/重复/跨市场混批） | 否 | 同市场分批调用 |
| `taxonomy` | 指标分类 sidecar 与 metrics.json 不一致 | 否 | 重跑 `extract_metric_taxonomy.py` |
| `unit` | 单位声明与台账不一致 | 否 | 按 `units.yaml` 修正声明 |
| `units` | 单位选项不合法（只支持 base/native） | 否 | 改用默认 base 或 native |
| `window` | 窗口参数不合法（如 `window`/`n` 越界） | 否 | 按文档取值域修正 |

### 目录与契约

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `catalog_dir` | 随包目录缺失或不可读 | 否 | 重装 wheel / 检查安装完整性 |

### 数据与守护

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `invariant` | 关系不变量校验失败（量价/单位量级疑似漂移） | 否 | 核对换算声明；逃生口 `_raw=True` / `_units="native"` |
| `response` | 上游响应形态异常（非预期 JSON/结构） | 是 | 重试一次；持续失败贴原始响应反馈 |

### 环境与凭证

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `anon_bad_response` | 匿名凭据响应缺少 client_id/client_secret | 是 | 重试；持续失败反馈网关版本 |
| `anon_failed` | 匿名凭据申领失败（其他 HTTP 错误） | 是 | 稍后重试；持续失败贴消息反馈 |
| `anon_quota` | 匿名试用今日名额已满或本网络领取次数超限 | 是 | 次日再试；需要稳定额度请注册免费账号 |
| `anon_unavailable` | 服务端未开放匿名试用（端点 404） | 否 | 到 open.winmale.com 注册免费账号获取凭据 |
| `config` | 客户端构造参数或凭证配置错误 | 否 | 按消息修正配置 |
| `credential_mode` | 凭证文件权限过宽且开启严格模式 | 否 | `chmod 600` 后重试 |
| `endpoint_unavailable` | 端点不可达或非官方主机未放行 | 否 | 用官方端点；自定义主机需 `allow_custom_host=True` |
| `network` | 网络层失败（重试耗尽） | 是 | 检查网络/代理后重试 |
| `oauth` | OAuth 取 token 失败 | 是 | 检查 client_id/secret；瞬时失败可重试 |
| `oauth_response` | OAuth 响应结构异常 | 是 | 重试；持续失败检查网关版本 |
| `pandas` | 缺少 pandas（DataFrame 默认路径依赖） | 否 | `pip install pandas`（>=1.5） |

### 配额与限流

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `ec_budget` | 本地 EC 预算保护触发（未发请求） | 否 | 调大预算或缩小请求；先 `cli.cost_estimate` 估算 |
| `rate_limited` | 服务端限流（HTTP 429，按请求次数） | 是 | 按 `retry_after`/`Retry-After` 退避；减少请求次数（batch_all/批量原生） |

### 批量

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `batch` | 批量返回不是 MAP 或结构异常 | 否 | 降级为逐票调用定位问题 |
| `batch_missing` | 批量返回缺少部分标的（服务端无对应行） | 否 | 核对代码有效性/停牌；准全市场捷径用 `truncated` 判断 |

### 演示模式

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `demo_limit` | 演示快照条数不足 | 否 | 减小 `limit` 或换真实客户端 |
| `demo_market` | 演示快照仅覆盖单一市场 | 否 | 用该市场客户端或真实客户端 |
| `demo_symbol` | 演示快照未覆盖该标的 | 否 | 用快照内标的或真实客户端 |
| `demo_unsupported` | 该数据面未纳入离线演示快照 | 否 | 换真实客户端（需凭证） |

### 订阅

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `stream_event` | 订阅事件结构异常 | 是 | 跳过并记录；持续失败反馈 |
| `stream_reset` | 订阅进度超出服务端保留期 | 否 | `seek_oldest(market)` 后继续消费 |

## 3. 服务端配额码（`QuotaError.code`）

| `code` | 含义 | 可重试 | 处理建议 |
|---|---|---|---|
| `DAILY_EC_CAP_EXCEEDED` | 当日 EC 消耗到顶 | 否 | 换平台默认应用凭证 / 等周补 / 升级或充值 |
| `DAILY_INSIGHT_CREDIT_CAP_EXCEEDED` | 当日洞察点数到顶 | 否 | 换平台默认应用凭证 / 等周补 / 升级或充值 |
| `EC_BALANCE_EXHAUSTED` | EC 钱包余额耗尽（周额度已空） | 否 | 换平台默认应用凭证 / 等周补 / 升级或充值 |
| `INSIGHT_CREDIT_EXHAUSTED` | 洞察点数额度耗尽 | 否 | 换平台默认应用凭证 / 等周补 / 升级或充值 |

## 4. 处理范式

```python
import time

from wmshare import DataError, LimitError, QuotaError
from wmshare.errors import ServerError, TransportError

try:
    rows = cli.kline.bars("600519", n=120)
except QuotaError:            # 配额耗尽：重试无意义
    ...
except LimitError as e:       # 429 限流：按 retry_after 退避
    time.sleep(getattr(e, "retry_after", 1.0) or 1.0)
except (TransportError, ServerError):  # 瞬时故障：可重试
    ...
except DataError:             # 数据守护：先核对口径，勿盲目重试
    ...
```

程序化分类优先看 `err.code`；`err.status` 仅作辅助（429/5xx 与重试策略相关）。
