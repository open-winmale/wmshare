# wmshare — Quick Start (English)

A Python SDK for China A-share / Hong Kong / US market data, BSD-3-Clause licensed.
Requires Python ≥ 3.11.

## Why it exists

Most market-data libraries hand you raw OHLCV rows and leave the analytics to you.
Want the 10-year PE percentile of a stock? You download history, pick a percentile
algorithm, handle corporate actions and calendar alignment — and everyone's number
differs slightly.

wmshare moves that computation **to the server**: 2,983 precomputed indicator codes
(percentile ranks, multi-window averages, industry-relative ranks, TTM yields, …),
each with a documented definition, one call each. A "data guardian" layer validates
plausibility and unit contracts before values reach your code — implausible values
raise `DataError` instead of silently polluting your model.

It also ships an MCP server and `llms.txt` / `SKILL.md`, so AI agents (Cursor,
Claude, …) can query the market without a human writing glue code.

## Install

```bash
pip install wmshare
```

## First call — no sign-up, 3 lines

No registration needed: `Client.from_env()` automatically falls back to an
anonymous trial (one-shot quota aligned with the free tier) when no credentials
are configured — real data, network required:

```python
import wmshare

cli = wmshare.Client.from_env()                        # anonymous fallback, no sign-up
print(f"{cli.dividend.yield_ttm('600519'):.2%}")       # 3.96%
print(cli.screener.index_breadth_summary()["total"])   # 5685
```

Unknown symbols raise an explicit error instead of returning made-up values.

## Standing quota

For a standing quota, get an AppId / API Key from
[open.winmale.com](https://open.winmale.com), then:

```bash
export WMSHARE_CLIENT_ID=<AppId> WMSHARE_CLIENT_SECRET=<API Key>
```

```python
import wmshare

cli = wmshare.Client.from_env()
p = cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")
print(p)   # 10-year PE percentile, e.g. 0.2115 = 21st percentile; moves daily
```

Two separate meters apply. **Rate limiting** counts requests (free tier: 500/hour,
5,000/day) — that is what batching fixes. **Billing** is measured in EC by the server
per materialized row, **not per request**: batching cuts request count and latency,
but it does not cut EC. Estimate before you pull with
`cli.cost_estimate(name, **params)` (offline, no request), and read the actual charge
back from `cli.last_ec_cost` / `BatchResult.ec_cost`.

## Whole market in 11 requests

Looping over stocks one by one is the fastest way to hit rate limits. The batch
helpers split the whole A-share market (5,375 symbols) into page requests —
about **11 requests** for full coverage. See `examples/07_stocks_industry_batch.py`
and the README section on batch fetching.

## Find an indicator code

- Browse the offline catalog: `cat.search("股息")` / `cat.metric(code)` after
  `cat = cli.catalog` — codes are verified before use (`cat.metric` returns
  `None` for unknown codes; the screener raises with a `cat.search` hint).
- Full navigation: [docs/INDICATORS.md](INDICATORS.md) (Chinese) — all 2,983 codes
  grouped by data type, with naming grammar and a dead-code warning chapter.

## Unit contract

One rule set across every endpoint: **ratios/returns are decimals** (0.01 = 1%),
**money/prices/market cap are yuan** (statement original currency), **volume is
shares**. Upstream quirks (手, percent-as-number) are normalized; `_raw=True` /
`_units="native"` / `Client(validate=False)` opt out when you need source fidelity.

## Daily K-line depth

Individual stocks and ETFs have daily bars since their first listing day
(earliest 1991); a single range query is capped at 5 years, 500 bars per call
by default (`Client(max_limit=...)` to adjust).

## Use it from AI agents

- MCP server: `pip install wmshare` provides the `wmshare-mcp` command
  (stdio transport; published on the official MCP registry).
- Skill + `llms.txt` / `llms-full.txt` are generated from the docs for
  LLM-friendly context. See [docs/AI.md](AI.md).

## Where to go next

The in-depth documentation is in Chinese:
[GUIDE.md](GUIDE.md) (task recipes, batching, troubleshooting) ·
[INDICATORS.md](INDICATORS.md) (indicator catalog) ·
[API.md](API.md) (175 core endpoints) ·
[examples/](../examples/README.md) (22 runnable numbered examples: anonymous
trial by default, 4 fully offline) ·
[AGENTS.md](../AGENTS.md) and
[SKILL.md](../src/wmshare/skills/wmshare/SKILL.md) for agent integration.

## Shell first: the `wmshare` CLI

No Python needed for the four job verbs — each writes a finished file (`--out`,
`.md`/`.csv`/`.xlsx`); falls back to anonymous trial when no credentials are set:

```bash
wmshare screen --where "$ROE_TTM_LAST > 0.15" --out roe.xlsx
wmshare income --top-n 20 --out ./income/
wmshare index trend --keys index.hs300,index.csi500 --out trend.md
wmshare cbond daily --out ./cb/
wmshare call kline.query_bars sym=600519 limit=30 --json   # pass-through for all catalog functions
```

## Disclaimer & license

Data is provided for research reference only and does **not** constitute
investment advice. Code is [BSD-3-Clause](../LICENSE); the cloud data service
requires an open.winmale.com account.
