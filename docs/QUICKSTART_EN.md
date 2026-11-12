# wmshare — Quick Start (English)

A Python SDK for market data from mainland China (A-shares), Hong Kong, and the
United States. It requires Python 3.11 or later and uses the BSD-3-Clause license.

## Why it exists

Calculating the 10-year percentile rank of a stock's price-to-earnings ratio
requires historical data, a percentile method, and consistent handling of
corporate actions and trading dates.

The server provides **2,752 precomputed indicators**, including percentile ranks,
averages over different periods, industry-relative ranks, and trailing 12-month
yields. Each code has a documented definition. The SDK checks units and value
ranges and raises `DataError` when a value violates those checks.

## Install

```bash
pip install wmshare
```

## Try it offline

The demo uses a snapshot captured on October 30, 2026. You can run this example
offline without credentials. Tests check both outputs.

```python
import wmshare

cli = wmshare.demo_client()
print(f"{cli.dividend.yield_ttm('600519'):.2%}")        # 3.73%
print(cli.screener.index_breadth_summary()["total"])    # 5686
```

The demo raises an error for symbols outside the snapshot.

## First live call

Use your AppId and API key from the [data service](https://open.winmale.com) to set
these environment variables:

```bash
export WMSHARE_CLIENT_ID=<AppId> WMSHARE_CLIENT_SECRET=<API Key>
```

```python
import wmshare

cli = wmshare.Client.from_env()
p = cli.indicator.get("600519", "$PCT_PE_TTM_10Y_LAST")
print(p)   # 0.2115 is about the 21st percentile of the 10-year P/E history.
```

The free tier allows 500 requests per hour and 5,000 per day. A batch counts as one
request regardless of how many rows it returns.

## Whole market in 12 requests

In the documented example, `batch_all` fetches snapshots for 5,691 A-share symbols
in about **12 requests**. See the [batch example](../examples/07_stocks_industry_batch.py)
and the [README](../README.md) for the three batch methods.

## Find an indicator code

- Set `cat = cli.catalog` to use the offline catalog. Search for a term with
  `cat.search("股息")` (dividends), or look up a specific code with `cat.metric(code)`.
- The [indicator catalog](INDICATORS.md) groups all 2,752 codes by data type and
  explains their naming conventions and how to spot unsupported codes.

## Unit contract

Normalized results use **decimals for ratios and returns** (0.01 = 1%) and **shares
for volume**. Monetary values are in yuan where specified. Financial statements
use their original reporting currency.

Use `_raw=True` for original rows, or `_units="native"` to retain source units with
normalized field names. `Client(validate=False)` keeps unit conversion and
disables validation.

## Daily price history

Daily bars go back to the first listing day for individual stocks and ETFs, with
the earliest listings dating to 1991. A range query spans up to five years and
returns up to 500 bars by default. Set `Client(max_limit=...)` to adjust the bar limit.

## Use it from AI agents

- Install `wmshare[mcp]` to run the `wmshare-mcp` server over stdio.
- See the [AI integration guide](AI.md) for the bundled skill and documentation
  files for language models.

## Where to go next

The detailed [guide](GUIDE.md), [indicator catalog](INDICATORS.md), and
[API reference](API.md) are in Chinese. The [examples index](../examples/README.md)
lists the 15 numbered examples and identifies which ones can run offline.
See [AGENTS.md](../AGENTS.md) and the [bundled skill](../src/wmshare/skills/wmshare/SKILL.md)
for agent integration.

## Disclaimer & license

Data is provided for research reference only and does **not** constitute
investment advice. Code is [BSD-3-Clause](../LICENSE); the cloud data service
requires an open.winmale.com account.
