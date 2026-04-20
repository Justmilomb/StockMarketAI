# Alt-Data

`core/alt_data/` — external data sources the agent calls on demand:
fundamentals, macro indicators, structured news, institutional
holders, earnings dates, insider cluster activity. Seven clients,
eleven MCP tools, one shared in-process TTL cache.

## Purpose

The agent needs evidence beyond price and social chatter: financial
ratios, macro regime, analyst price targets, institutional 13F
filings, upcoming earnings, insider clusters. Rather than bake those
into the supervisor prompt, each source is a typed MCP tool the agent
picks as it needs.

Every client degrades gracefully: missing env keys, HTTP errors,
rate-limit notes, and non-ok status codes all return
`{"error": "..."}` instead of raising — the agent sees the failure as
data, never as a crash. Every tool also checks
`alt_data.<source>.enabled` in `config.json` and short-circuits with a
`{error, fix}` pair when disabled, so the operator can kill a source
at runtime without a restart.

## Sources

| Source              | Env key             | Data                                                   | Default TTL |
|---------------------|---------------------|--------------------------------------------------------|-------------|
| Alpha Vantage       | `ALPHA_VANTAGE_KEY` | Company overview (fundamentals), earnings history      | 1 h         |
| Financial Modeling Prep | `FMP_KEY`       | Ratios, DCF, analyst price targets                     | 1 h         |
| FRED                | `FRED_KEY`          | Macro snapshot + arbitrary series observations         | 1 h         |
| News API            | `NEWS_API_KEY`      | Keyword headline search (newsapi.org /everything)      | 15 min      |
| SEC EDGAR           | *(no key)*          | 13F-HR institutional holder search                     | 1 h         |
| Earnings Whispers   | *(scrape, no key)*  | Next earnings date, whisper EPS, consensus             | 30 min      |
| OpenInsider         | *(scrape, no key)*  | Clustered open-market insider buy/sell activity        | 30 min      |

## MCP Tools

Registered in `core/agent/mcp_server.py`. Every tool returns the
payload as `{"content": [{"type": "text", "text": json.dumps(...)}]}`.

**Fundamentals** (`fundamentals_tools.py`)
- `get_company_overview(ticker)` — Alpha Vantage OVERVIEW
- `get_earnings_history(ticker)` — Alpha Vantage EARNINGS (8 quarters)
- `get_financial_ratios(ticker)` — FMP ratios-TTM
- `get_dcf_value(ticker)` — FMP DCF + `upside_pct`
- `get_analyst_price_targets(ticker)` — FMP price-target-consensus

**Macro** (`macro_tools.py`)
- `get_macro_snapshot()` — curated FRED bundle (Fed Funds, 10Y/2Y, CPI YoY,
  core PCE, unemployment, derived `yield_curve` flag)
- `get_fred_series(series_id, limit?)` — raw FRED observations

**News** (`news_api_tools.py`)
- `get_structured_news(query, days_back?)` — NewsAPI /everything

**Institutional / insider** (`alt_data_extended_tools.py`)
- `get_institutional_holders(ticker, lookback_days?)` — EDGAR 13F search
- `get_earnings_whisper(ticker)` — EarningsWhispers + yfinance fallback
- `get_insider_cluster_summary(ticker)` — OpenInsider buy/sell summary

## Shared infrastructure

`core/alt_data/_cache.py` — process-wide `{key: (expires_at, value)}`
dict behind a lock. Every client namespaces its own keys
(`av_overview_AAPL`, `fred_DGS10_10`, `oi_AAPL`, …) and passes a
source-specific TTL on `put`.

## Graceful-degradation contract

- Every client returns either the real payload or a dict shaped
  `{"error": "...", ...}`. No raises cross the tool layer.
- Tools check `alt_data.<source>.enabled` before calling the client and
  return `{"error": "alt_data.<source> is disabled", "fix": "..."}`
  when the flag is off.
- Missing env key → client returns `{"error": "<KEY> not configured"}`
  *without* hitting the network.
- HTTP failure, rate-limit note (AV), or non-ok status (NewsAPI) →
  client logs at INFO and returns `{"error": "<message>"}`.

## Config

`config.json → alt_data` toggles per source; defaults in
`config.default.json` enable all seven so the feature ships working:

```jsonc
{
  "alt_data": {
    "alpha_vantage":     {"enabled": true, "cache_ttl_seconds": 3600},
    "fmp":               {"enabled": true, "cache_ttl_seconds": 3600},
    "fred":              {"enabled": true, "cache_ttl_seconds": 3600},
    "news_api":          {"enabled": true, "cache_ttl_seconds": 900},
    "sec_edgar":         {"enabled": true, "cache_ttl_seconds": 3600},
    "earnings_whispers": {"enabled": true, "cache_ttl_seconds": 1800},
    "open_insider":      {"enabled": true, "cache_ttl_seconds": 1800}
  }
}
```

## Testing

Each client has a focused test file under `tests/` (one per module)
mocking `requests.get` at the HTTP boundary. The
`test_alt_data_tools_registered.py` integration test locks the set of
tool names exposed through `mcp_server.allowed_tool_names()`, so
forgetting to register a new tool is caught at CI time.

Run only the alt-data coverage:

```
pytest tests/test_alt_data_cache.py tests/test_alpha_vantage.py \
  tests/test_fmp.py tests/test_fred.py tests/test_news_api_client.py \
  tests/test_sec_edgar.py tests/test_earnings_whispers.py \
  tests/test_open_insider.py tests/test_alt_data_tools_registered.py -v
```

## Adding a new source

1. Drop a client module in `core/alt_data/<source>.py`. Use `_cache.get`
   / `_cache.put` for caching — don't roll your own.
2. Every failure path returns `{"error": "..."}`. Missing env key
   returns before the HTTP call.
3. Add a thin tool wrapper in `core/agent/tools/<name>_tools.py`,
   check `alt_data.<source>.enabled`, return
   `{"content": [{"type": "text", "text": json.dumps(...)}]}`.
4. Append the `*_TOOLS` list to `ALL_TOOLS` in `core/agent/mcp_server.py`.
5. Add the `alt_data.<source>` entry to `config.default.json`.
6. Tests: at minimum a missing-key path, a happy-path parse, and an
   HTTP-failure path. Add the new tool name to
   `tests/test_alt_data_tools_registered.py::EXPECTED_ALT_DATA_TOOLS`.
