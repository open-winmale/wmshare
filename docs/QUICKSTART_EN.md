# wmshare — Quick Start (English)

A Python SDK for China A-share / Hong Kong / US market data, BSD-3-Clause licensed.
Requires Python ≥ 3.11.

## Why it exists

Most market-data libraries hand you raw OHLCV rows and leave the analytics to you.
Want the 10-year PE percentile of a stock? You download history, pick a percentile
algorithm, handle corporate actions and calendar alignment — and everyone's number
differs slightly.

wmshare moves that computation **to the server**: 2,752 precomputed indicator codes
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

## Try it offline — no sign-up, 3 lines

The package ships a frozen snapshot (captured 2026-10-30, not live data). This runs
fully offline and is pinned by tests:

```python
import wmshare

cli = wmshare.demo_client()
print(f"{cli.dividend.yield_ttm('600519'):.2%}")        # 3.73%
print(cli.screener.index_breadth_summary()["total"])    # 5686
```

Codes outside the demo universe raise an explicit error instead of returning
made-up values.

## First live call

Get an AppId / API Key from [open.winmale.com](https://open.winmale.com), then:

```bash
export WMSHARE_CLIENT_ID=<AppId> WMSHARE_CLIENT_SECRET=<API Key>
```

```python
import wmshare

cli = wmshare.Client.from_env()
p = cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")
print(p)   # 10-year PE percentile, e.g. 0.2115 = 21st percentile; moves daily
```

The free tier allows 500 requests/hour and 5,000/day. Requests are billed
**per request**, not per row — which is why batching matters:

## Whole market in 12 requests

Looping over stocks one by one is the fastest way to hit rate limits. The batch
helpers split the whole A-share market (5,691 symbols) into page requests —
about **12 requests** for full coverage. See `examples/07_stocks_industry_batch.py`
and the README section on batch fetching.

## Find an indicator code

- Browse the offline catalog: `cat.search("股息")` / `cat.metric(code)` after
  `cat = cli.catalog` — codes are verified before use (`cat.metric` raises on
  dead codes).
- Full navigation: [docs/INDICATORS.md](INDICATORS.md) (Chinese) — all 2,752 codes
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
[API.md](API.md) (132 core endpoints) ·
[examples/](../examples/README.md) (15 runnable numbered examples, all with an
offline `--demo` mode) · [AGENTS.md](../AGENTS.md) and
[SKILL.md](../src/wmshare/skills/wmshare/SKILL.md) for agent integration.

## Disclaimer & license

Data is provided for research reference only and does **not** constitute
investment advice. Code is [BSD-3-Clause](../LICENSE); the cloud data service
requires an open.winmale.com account.
