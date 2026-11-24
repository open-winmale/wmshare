# wmshare — Quick Start (English)

A Python SDK for market data from mainland China (A-shares), Hong Kong, and the
United States. It requires Python 3.11 or later and uses the BSD-3-Clause license.

## Why it exists

Calculating the 10-year percentile rank of a stock's price-to-earnings ratio
requires historical data, a percentile method, and consistent handling of
corporate actions and trading dates.

The server provides **2,983 precomputed indicator codes**, including percentile
ranks, averages over different periods, industry-relative ranks, and trailing
12-month yields. Each code has a documented definition. Where validation rules
apply, the SDK raises `DataError` for values that fail those checks.

The SDK also provides an MCP server, `llms.txt`, and `SKILL.md` for querying
market data from an AI agent.

## Install

```bash
pip install wmshare
```

## First live call

`wmshare.Client.from_env()` uses free guest access when no credentials are
configured. Guest access requires a network connection and its quota is shared
by network. The following example fetches live values, so your output may vary.

```python
import wmshare

cli = wmshare.Client.from_env()
print(f"{cli.dividend.yield_ttm('600519'):.2%}")       # e.g. 3.96%
print(cli.screener.index_breadth_summary()["total"])   # e.g. 5685
```

Requests for unknown symbols raise an error.

## Standing quota

For an account quota, get an AppId and API key from the
[data service](https://open.winmale.com) and set them as environment variables.

```bash
export WMSHARE_CLIENT_ID="YOUR_APP_ID"
export WMSHARE_CLIENT_SECRET="YOUR_API_KEY"
```

```python
import wmshare

cli = wmshare.Client.from_env()
p = cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")
print(p)   # 0.2115 is about the 21st percentile of the 10-year P/E history.
```

The free tier allows 500 requests per hour and 5,000 per day. The server
separately measures billing in EC for each row it materializes. Batching
uses fewer requests and can reduce latency, but it does not cut EC. Use
`cli.cost_estimate(name, **params)` to estimate the charge offline. Read the
actual charge from `cli.last_ec_cost` or `BatchResult.ec_cost`.

## Whole market in 11 requests

The batch helpers split the whole A-share market (5,375 symbols) into pages.
It takes about **11 requests** to cover the full market in the
[batch example](../examples/07_stocks_industry_batch.py). See the
[README](../README.md) for the available batch methods.

## Find an indicator code

- Set `cat = cli.catalog` to use the offline catalog. Search for a term with
  `cat.search("股息")` (dividends), or look up a specific code with
  `cat.metric(code)`. An unknown code returns `None` from `cat.metric`. The
  screener raises an error with a catalog search hint.
- The [indicator catalog](INDICATORS.md) groups all 2,983 codes by data type and
  explains their naming conventions and how to spot unsupported codes.

## Unit contract

Normalized results use **decimals for ratios and returns** (0.01 = 1%),
**shares for volume**, and **yuan for monetary values** by default. Financial
statements use their original reporting currency.

Use `_raw=True` to get the original rows or `_units="native"` to retain source
units with normalized field names. `Client(validate=False)` disables validation
and keeps unit conversion enabled.

## Daily price history

Daily bars go back to the first listing day for individual stocks and ETFs, with
the earliest listings dating to 1991. A range query spans up to five years and
returns up to 500 bars by default. Set `Client(max_limit=...)` to adjust the bar limit.

## Use it from AI agents

- Install `wmshare[mcp]` to run the `wmshare-mcp` server over stdio. The server
  is listed in the official MCP registry.
- The project generates `llms.txt` and `llms-full.txt` from the docs and bundles
  a skill. See the [AI integration guide](AI.md).

## Where to go next

The detailed [guide](GUIDE.md), [indicator catalog](INDICATORS.md), and
[API reference](API.md) (185 core endpoints) are in Chinese. The
[examples index](../examples/README.md) lists 30 numbered examples, including
four that run fully offline. The others use guest access by default.
See [AGENTS.md](../AGENTS.md) and the [bundled skill](../src/wmshare/skills/wmshare/SKILL.md)
for agent integration.

## Use the command line

The CLI uses guest access when no credentials are set and supports
Markdown, CSV, and Excel output through `--out`.

```bash
wmshare screen --where '$ROE_TTM_LAST > 0.15' --out roe.xlsx
wmshare income --top-n 20 --out ./income/
wmshare index trend --keys index.hs300,index.csi500 --out trend.md
wmshare cbond daily --out ./cb/
wmshare call kline.query_bars sym=600519 limit=30 --json   # pass-through for all catalog functions
```

## Disclaimer & license

Data is provided for research and does **not** constitute investment advice.
The code uses the [BSD-3-Clause license](../LICENSE). The cloud data service
offers guest access and account-based access.
