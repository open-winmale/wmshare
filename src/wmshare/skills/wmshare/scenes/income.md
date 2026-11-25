# 场景：收息流投研闭环（发现 → 研判 → 跟踪 → 验证）

> 按需加载：只有用户问「收息 / 高股息排行 / 分红日历 / 拿息收益」时才读本文件。
> 口径真值在服务端 `sys/income`（与 web 收息佬、wm-income 技能共享同一 SoT）——
> **禁止用其他接口的字段自算评分或重排榜单**。

## 边界（先判是不是这个场景）

- 「收息佬功能在哪 / 页面怎么看」→ 产品路由问题，不在本 SDK 范围（赢麻了助手用
  wm-product 技能答页面同一条取数）；本 SDK 是编程取数面。
- 单票分红质量快照（不经评分，只要股息率/派息率判定）→ `cli.dividend.screen_quality(sym)`。
- 红利**指数**估值/定投回测 → `cli.index.trend` / `cli.backtest.run`（非本场景）。

## 四步闭环（每步一次调用，批量优先）

1. **发现**（全市场一次取数）：
   `cli.dividend.rating(top_n=20, grade="strong", industry="银行", min_yield=0.04)`
   - 排序 = 股息分（0.6×TTM + 0.4×近3年最低）降序，过资格门块在前
   - `meta.facets_industries` 是全行业计数全集，改选行业用
   - `ok=false + meta.cache="miss"` = 榜单 cron 未就绪（16:50/19:40 物化）——
     如实告知稍后重试，**勿现场重算全市场评分**（fuel 限会炸）
   - 成本 ≈15k~70k EC（行业过滤早停更便宜）
2. **研判**（原生批量，勿逐票循环）：
   `cli.dividend.diagnose(["600900", "600519"])` —— 批量档 ≈10k EC/票
   - `score.parts` 四维逐项解释（收益30/持续25/稳定25/成长20）
   - `flags` 硬修正必须透传：payout_danger / decaying_high_yield / verify_data / floor_blind
   - `floor_explain.residual` |值|>0.002 = 复原走了通用档，`gate_uncertain=true`
   - deep 档（单票才开）：`include_history=True` 带分红史+方案（+18k EC/票）
3. **跟踪**（分红日历）：
   `cli.dividend.calendar("2026-11-01", "2026-11-30", codes=[自选])`
   - 一个事件含公告/登记/除息/到账四日期，窗口内任一命中即返回
   - `data.stocks` 带名称/股息率/市值 enrich
4. **验证**（拿息收益拆解，≤10 票）：
   `cli.dividend.decomp(["600900"], years=10)`
   - 总收益 − 价格收益 = 股息贡献（hfq−nr 差值口径，含再投效应，非精确现金分红率）
   - `yearly` 逐年表 + `attribution` EPS×PE 归因
   - **首次查某票有冷物化尖刺（~20 万 EC），复查即热 ≈10k EC**；次新股 `ok=false`

## 单位红线（与榜单口径逐字一致）

- 全部率值小数：`yield_ttm` 0.068=6.8%；`payout` 0.7=70%；`bond_yield_10y` 同口径
- `mv` 亿元、`amount` 元、分红方案金额元
- 档位：≥75 强收息(strong) / 60~75 可收息(good) / 45~60 观察(watch) / <45 回避(avoid)
- `dividend_score` 是复合排序分，**不得表述为股息率**
- 评级只给证据与口径，不构成买卖建议；带「先懂公司」前提

## 成本速查（2026-11-20 实测，estimate_cost 同步此口径）

| 调用 | EC |
|---|---|
| rating（top20 全量 / 行业过滤早停） | ≈54k / ≈17k |
| diagnose 批量（每票） | ≈10k（deep +18k/票） |
| calendar（当月） | ≈20k |
| decomp（每票，热态） | ≈10k（冷首查尖刺 ~200k） |
