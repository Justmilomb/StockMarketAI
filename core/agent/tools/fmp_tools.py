"""FMP Enterprise MCP tools.

Every tool routes through :func:`core.data.get_provider`. When FMP
isn't the active backend (the default), each tool returns a uniform
``{"status": "disabled", "reason": "FMP provider not active"}``
payload — no API call, no network. The user activates FMP by setting
``data_provider.primary = "fmp"``, ``data_provider.fmp_enabled = true``
and exporting ``FMP_KEY``; on the next process start the provider
flips and these tools come alive.

Tool groups (matching the FMP Enterprise catalogue):

* Real-time + historical quotes — ``fmp_real_time_quote``,
  ``fmp_intraday_bars``, ``fmp_daily_bars``
* Index data — ``fmp_index_quote``, ``fmp_index_constituents``
* Fundamentals — ``fmp_financials`` (income / balance / cash flow /
  metrics / growth), ``fmp_company_profile``, ``fmp_executives``
* Bulk — ``fmp_bulk_quotes``, ``fmp_bulk_eod``, ``fmp_bulk_profiles``
* Earnings transcripts — ``fmp_earnings_transcript``,
  ``fmp_list_earnings_transcripts``
* Search & directory — ``fmp_search``, ``fmp_list_exchanges``
* Calendars — ``fmp_market_calendar`` (earnings / IPOs / dividends /
  splits in one tool), ``fmp_economic_calendar``
* News — ``fmp_market_news`` (general + press releases)
* ESG — ``fmp_esg``
* Economics — ``fmp_economic_indicator``, ``fmp_treasury_rates``
* Advanced metrics — ``fmp_advanced_metrics``,
  ``fmp_sector_performance``
* Analyst — ``fmp_analyst`` (estimates, targets, grades, upgrades)
* Forex — ``fmp_forex_quote``, ``fmp_forex_history``
* ETF / mutual fund — ``fmp_etf_profile``, ``fmp_etf_holdings``,
  ``fmp_mutual_fund_holders``
* Commodities — ``fmp_commodity_quote``, ``fmp_commodity_history``
* Insider / congressional — ``fmp_insider_trades``,
  ``fmp_congressional_trades``
* 13F — ``fmp_13f_filings``, ``fmp_institutional_holders``
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.data import get_provider
from core.data.base_provider import BaseDataProvider


# ── helpers ────────────────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(kind: str, payload: Dict[str, Any]) -> None:
    try:
        ctx = get_agent_context()
    except Exception:
        return
    try:
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ctx.iteration_id, kind, payload.get("tool", ""),
                    json.dumps(payload, default=str), "fmp",
                ),
            )
    except Exception:
        # Tool calls must not fail because the journal is unavailable.
        pass


def _provider_or_disabled() -> tuple[Optional[BaseDataProvider], Optional[Dict[str, Any]]]:
    """Return the active provider, or a disabled-status payload.

    The factory in :mod:`core.data.provider` falls back to yfinance
    when FMP isn't fully configured, so we check the resolved
    backend's ``name`` rather than re-reading config — that keeps the
    gate consistent with what's actually serving requests.
    """
    try:
        provider = get_provider()
    except Exception as e:
        return None, _text_result({
            "status": "error", "reason": f"provider unavailable: {e}",
        })
    if getattr(provider, "name", "") != "fmp":
        return None, _text_result({
            "status": "disabled",
            "reason": (
                "FMP provider not active. Set data_provider.primary='fmp', "
                "data_provider.fmp_enabled=true, and export FMP_KEY to enable."
            ),
            "active_provider": provider.name,
        })
    return provider, None


# ── (1) Real-time quotes ──────────────────────────────────────────────

@tool(
    "fmp_real_time_quote",
    "FMP real-time quote(s). Pass one ticker or a comma-separated list. "
    "Returns price, change %, bid/ask/volume in account-currency terms "
    "(LSE pence are converted to pounds). FMP-only.",
    {"tickers": str},
)
async def fmp_real_time_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    raw = str(args.get("tickers", "")).strip()
    if not raw:
        return _text_result({"status": "rejected", "reason": "tickers is required"})
    tickers = [t.strip() for t in raw.split(",") if t.strip()]
    out = provider.fetch_live_prices(tickers)
    _journal("tool_call", {"tool": "fmp_real_time_quote", "n": len(tickers)})
    return _text_result(out)


# ── (2) Historical OHLCV ──────────────────────────────────────────────

@tool(
    "fmp_intraday_bars",
    "Intraday OHLCV via FMP. interval ∈ {1m,5m,15m,30m,60m,4h}. "
    "lookback_minutes filters to the most recent window. FMP-only.",
    {"ticker": str, "interval": str, "lookback_minutes": int},
)
async def fmp_intraday_bars(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    interval = str(args.get("interval", "5m") or "5m")
    lookback = int(args.get("lookback_minutes", 240) or 240)
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    bars = provider.fetch_intraday_bars(ticker, interval=interval, lookback_minutes=lookback)
    _journal("tool_call", {"tool": "fmp_intraday_bars", "ticker": ticker, "n": len(bars)})
    return _text_result({"ticker": ticker, "interval": interval, "bars": [b.as_dict() for b in bars]})


@tool(
    "fmp_daily_bars",
    "Daily OHLCV via FMP. lookback_days ≤ ~5000. FMP-only.",
    {"ticker": str, "lookback_days": int},
)
async def fmp_daily_bars(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    lookback = int(args.get("lookback_days", 90) or 90)
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    bars = provider.fetch_daily_bars(ticker, lookback_days=lookback)
    _journal("tool_call", {"tool": "fmp_daily_bars", "ticker": ticker, "n": len(bars)})
    return _text_result({"ticker": ticker, "bars": [b.as_dict() for b in bars]})


# ── (3) Index market data ─────────────────────────────────────────────

@tool(
    "fmp_index_quote",
    "Live quote for an index. symbol like ^GSPC (S&P), ^FTSE (FTSE 100), "
    "^IXIC (Nasdaq), ^DJI (Dow). FMP-only.",
    {"symbol": str},
)
async def fmp_index_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _text_result({"status": "rejected", "reason": "symbol is required"})
    return _text_result(provider.get_index_quote(symbol))


@tool(
    "fmp_index_constituents",
    "Members of a major index. index ∈ {sp500, nasdaq, dowjones}. FMP-only.",
    {"index": str},
)
async def fmp_index_constituents(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    index = str(args.get("index", "sp500")).strip().lower()
    return _text_result(provider.get_index_constituents(index))


# ── (4) Fundamental financial statements ──────────────────────────────

@tool(
    "fmp_financials",
    "Financial statements via FMP. statement ∈ {income, balance, cashflow, "
    "metrics, growth, enterprise_value}. period ∈ {annual, quarter}. "
    "Returns the most-recent ``limit`` filings (default 5).",
    {"ticker": str, "statement": str, "period": str, "limit": int},
)
async def fmp_financials(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    statement = str(args.get("statement", "income")).strip().lower()
    period = str(args.get("period", "annual")).strip().lower()
    limit = int(args.get("limit", 5) or 5)
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})

    dispatch = {
        "income": provider.get_income_statement,
        "balance": provider.get_balance_sheet,
        "cashflow": provider.get_cash_flow_statement,
        "metrics": provider.get_key_metrics,
        "growth": provider.get_financial_growth,
        "enterprise_value": provider.get_enterprise_value,
        "ev": provider.get_enterprise_value,
    }
    fn = dispatch.get(statement)
    if fn is None:
        return _text_result({
            "status": "rejected",
            "reason": f"unknown statement '{statement}'; expected one of {list(dispatch)}",
        })
    rows = fn(ticker, period=period, limit=limit)
    _journal("tool_call", {"tool": "fmp_financials", "ticker": ticker, "statement": statement, "n": len(rows)})
    return _text_result({"ticker": ticker, "statement": statement, "period": period, "rows": rows})


# ── (5) Bulk financial data ───────────────────────────────────────────

@tool(
    "fmp_bulk_quotes",
    "All live quotes for an exchange in one call. exchange ∈ {NYSE, NASDAQ, "
    "AMEX, EURONEXT, LSE, TSX, ...}. Returns thousands of rows — use sparingly.",
    {"exchange": str},
)
async def fmp_bulk_quotes(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    exchange = str(args.get("exchange", "NASDAQ")).strip().upper()
    rows = provider.bulk_quotes(exchange)
    return _text_result({"exchange": exchange, "count": len(rows), "rows": rows})


@tool(
    "fmp_bulk_eod",
    "End-of-day OHLCV for every covered ticker on an ISO date (YYYY-MM-DD). "
    "Heavy — only call when actually needed for a sweep.",
    {"date": str},
)
async def fmp_bulk_eod(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    date = str(args.get("date", "")).strip()
    if not date:
        return _text_result({"status": "rejected", "reason": "date is required"})
    rows = provider.bulk_eod_prices(date)
    return _text_result({"date": date, "count": len(rows), "rows": rows})


@tool(
    "fmp_bulk_profiles",
    "Bulk dump of every covered company's profile. ``part`` pages through "
    "the dataset (0,1,2,...). Heavy.",
    {"part": int},
)
async def fmp_bulk_profiles(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    part = int(args.get("part", 0) or 0)
    rows = provider.bulk_profiles(part)
    return _text_result({"part": part, "count": len(rows), "rows": rows})


# ── (6) Earnings call transcripts ─────────────────────────────────────

@tool(
    "fmp_earnings_transcript",
    "Full text of a quarterly earnings call. Omit year/quarter for the "
    "most recent. Transcripts can be 50k+ tokens — chunk before passing "
    "to small models.",
    {"ticker": str, "year": int, "quarter": int},
)
async def fmp_earnings_transcript(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    year = args.get("year")
    quarter = args.get("quarter")
    return _text_result(provider.get_earnings_transcript(
        ticker,
        year=int(year) if year else None,
        quarter=int(quarter) if quarter else None,
    ))


@tool(
    "fmp_list_earnings_transcripts",
    "Index of every (year, quarter) earnings transcript available for a ticker.",
    {"ticker": str},
)
async def fmp_list_earnings_transcripts(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result(provider.list_earnings_transcripts(ticker))


# ── (7) Company profile + executives ──────────────────────────────────

@tool(
    "fmp_company_profile",
    "Company profile via FMP — name, sector, industry, market cap, employees, "
    "description, IPO date, website, beta, etc.",
    {"ticker": str},
)
async def fmp_company_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result(provider.get_company_profile(ticker))


@tool(
    "fmp_executives",
    "Key executives at a company plus their roles. Set "
    "include_compensation=true to fetch the comp table as well (slower).",
    {"ticker": str, "include_compensation": bool},
)
async def fmp_executives(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    out: Dict[str, Any] = {"executives": provider.get_executives(ticker)}
    if bool(args.get("include_compensation")):
        out["compensation"] = provider.get_executive_compensation(ticker)
    return _text_result(out)


# ── (8) Search & directory ────────────────────────────────────────────

@tool(
    "fmp_search",
    "Symbol search by name or partial ticker. Returns up to ``limit`` "
    "matches with exchange, currency, and stock type.",
    {"query": str, "limit": int, "exchange": str},
)
async def fmp_search(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    query = str(args.get("query", "")).strip()
    if not query:
        return _text_result({"status": "rejected", "reason": "query is required"})
    limit = int(args.get("limit", 10) or 10)
    exchange = str(args.get("exchange", "") or "") or None
    return _text_result(provider.search_symbol(query, limit=limit, exchange=exchange))


@tool(
    "fmp_list_exchanges",
    "Every exchange FMP tracks plus current open/close status.",
    {},
)
async def fmp_list_exchanges(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    return _text_result(provider.list_exchanges())


# ── (9) Market calendar ───────────────────────────────────────────────

@tool(
    "fmp_market_calendar",
    "Upcoming corporate events. event ∈ {earnings, ipo, dividend, split}. "
    "Date filters use ISO YYYY-MM-DD. Earnings supports ticker filter.",
    {"event": str, "from_date": str, "to_date": str, "ticker": str},
)
async def fmp_market_calendar(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    event = str(args.get("event", "earnings")).strip().lower()
    from_date = str(args.get("from_date", "") or "") or None
    to_date = str(args.get("to_date", "") or "") or None
    ticker = str(args.get("ticker", "") or "") or None
    if event == "earnings":
        return _text_result(provider.get_earnings_calendar(from_date=from_date, to_date=to_date, ticker=ticker))
    if event == "ipo":
        return _text_result(provider.get_ipo_calendar(from_date=from_date, to_date=to_date))
    if event == "dividend":
        return _text_result(provider.get_dividend_calendar(from_date=from_date, to_date=to_date))
    if event == "split":
        return _text_result(provider.get_split_calendar(from_date=from_date, to_date=to_date))
    return _text_result({
        "status": "rejected",
        "reason": f"unknown event '{event}'; expected earnings|ipo|dividend|split",
    })


@tool(
    "fmp_economic_calendar",
    "Macro releases (CPI, NFP, GDP, central-bank decisions, etc) on a date "
    "range. Useful for spotting volatility windows.",
    {"from_date": str, "to_date": str},
)
async def fmp_economic_calendar(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    from_date = str(args.get("from_date", "") or "") or None
    to_date = str(args.get("to_date", "") or "") or None
    return _text_result(provider.get_economic_calendar(from_date=from_date, to_date=to_date))


# ── (10) News ─────────────────────────────────────────────────────────

@tool(
    "fmp_market_news",
    "Market news from FMP. mode='general' for the broad feed, "
    "mode='ticker' for a specific symbol's stock news + press releases.",
    {"mode": str, "ticker": str, "limit": int},
)
async def fmp_market_news(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    mode = str(args.get("mode", "general")).strip().lower()
    limit = int(args.get("limit", 50) or 50)
    if mode == "general":
        return _text_result({"news": provider.get_general_news(limit=limit)})
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker required when mode='ticker'"})
    return _text_result({
        "news": provider.get_news(tickers=[ticker], limit=limit),
        "press_releases": provider.get_press_releases(ticker, limit=limit),
    })


# ── (11) ESG ──────────────────────────────────────────────────────────

@tool(
    "fmp_esg",
    "ESG (Environmental / Social / Governance) data: latest score plus "
    "the historical ratings series.",
    {"ticker": str},
)
async def fmp_esg(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result({
        "score": provider.get_esg_score(ticker),
        "ratings_history": provider.get_esg_ratings(ticker),
    })


# ── (12) Economics ────────────────────────────────────────────────────

@tool(
    "fmp_economic_indicator",
    "Macro time series. name ∈ {GDP, realGDP, CPI, federalFunds, "
    "unemploymentRate, retailSales, consumerSentiment, ...}.",
    {"name": str, "from_date": str, "to_date": str},
)
async def fmp_economic_indicator(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    name = str(args.get("name", "")).strip()
    if not name:
        return _text_result({"status": "rejected", "reason": "name is required"})
    from_date = str(args.get("from_date", "") or "") or None
    to_date = str(args.get("to_date", "") or "") or None
    return _text_result(provider.get_economic_indicator(name, from_date=from_date, to_date=to_date))


@tool(
    "fmp_treasury_rates",
    "US Treasury yield curve series across the date range. Each row carries "
    "1mo / 3mo / 6mo / 1y / 2y / 5y / 7y / 10y / 20y / 30y.",
    {"from_date": str, "to_date": str},
)
async def fmp_treasury_rates(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    from_date = str(args.get("from_date", "") or "") or None
    to_date = str(args.get("to_date", "") or "") or None
    return _text_result(provider.get_treasury_rates(from_date=from_date, to_date=to_date))


# ── (13) Advanced market metrics ──────────────────────────────────────

@tool(
    "fmp_advanced_metrics",
    "Per-ticker advanced metrics: market_cap, share float, short interest "
    "history. Pass include=['market_cap','float','short'] to choose subsets; "
    "default returns all three.",
    {"ticker": str, "include": list},
)
async def fmp_advanced_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    include = args.get("include") or ["market_cap", "float", "short"]
    out: Dict[str, Any] = {"ticker": ticker}
    if "market_cap" in include:
        out["market_cap"] = provider.get_market_cap(ticker)
    if "float" in include:
        out["share_float"] = provider.get_share_float(ticker)
    if "short" in include:
        out["short_interest"] = provider.get_short_interest(ticker)
    return _text_result(out)


@tool(
    "fmp_sector_performance",
    "Today's sector performance ranked +→− across S&P sectors. Optionally "
    "include the per-sector P/E table by passing include_pe=true.",
    {"include_pe": bool, "exchange": str, "date": str},
)
async def fmp_sector_performance(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    out: Dict[str, Any] = {"sectors": provider.get_sector_performance()}
    if bool(args.get("include_pe")):
        exchange = str(args.get("exchange", "NYSE") or "NYSE")
        date = str(args.get("date", "") or "") or None
        out["sector_pe"] = provider.get_sector_pe(exchange=exchange, date=date)
    return _text_result(out)


# ── (14) Analyst ──────────────────────────────────────────────────────

@tool(
    "fmp_analyst",
    "Sell-side analyst data: estimates (EPS / revenue future quarters), "
    "consensus price target, individual price target history, "
    "upgrade/downgrade events, and stock grades. Pass which='all' (default) "
    "or a subset list ['estimates','target','target_history','grades','rating_actions'].",
    {"ticker": str, "which": list},
)
async def fmp_analyst(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    which = args.get("which") or ["estimates", "target", "target_history", "grades", "rating_actions"]
    out: Dict[str, Any] = {"ticker": ticker}
    if "estimates" in which:
        out["estimates"] = provider.get_analyst_estimates(ticker)
    if "target" in which:
        out["price_target_consensus"] = provider.get_price_target(ticker)
    if "target_history" in which:
        out["price_target_history"] = provider.list_price_targets(ticker)
    if "grades" in which:
        out["grades"] = provider.get_stock_grade(ticker)
    if "rating_actions" in which:
        out["upgrades_downgrades"] = provider.get_upgrades_downgrades(ticker)
    return _text_result(out)


# ── (15) Forex ────────────────────────────────────────────────────────

@tool(
    "fmp_forex_quote",
    "Live forex quote. pair like EURUSD, GBPJPY, USDCAD. Empty pair "
    "returns the full FMP forex board.",
    {"pair": str},
)
async def fmp_forex_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    pair = str(args.get("pair", "")).strip()
    if not pair:
        return _text_result({"pairs": provider.list_forex_quotes()})
    return _text_result(provider.get_forex_quote(pair))


@tool(
    "fmp_forex_history",
    "Historical forex bars. interval ∈ {1m,5m,15m,30m,60m,4h,1d}.",
    {"pair": str, "interval": str, "lookback": int},
)
async def fmp_forex_history(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    pair = str(args.get("pair", "")).strip()
    if not pair:
        return _text_result({"status": "rejected", "reason": "pair is required"})
    interval = str(args.get("interval", "1d") or "1d")
    lookback = int(args.get("lookback", 90) or 90)
    return _text_result({
        "pair": pair, "interval": interval,
        "rows": provider.get_forex_history(pair, interval=interval, lookback=lookback),
    })


# ── (16) ETF & mutual fund ────────────────────────────────────────────

@tool(
    "fmp_etf_profile",
    "ETF profile: name, AUM, expense ratio, NAV, inception, holdings count.",
    {"ticker": str},
)
async def fmp_etf_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result(provider.get_etf_profile(ticker))


@tool(
    "fmp_etf_holdings",
    "ETF holdings + sector / country breakdown. Pass which=['holdings',"
    "'sectors','countries'] for subsets; default returns all three.",
    {"ticker": str, "which": list},
)
async def fmp_etf_holdings(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    which = args.get("which") or ["holdings", "sectors", "countries"]
    out: Dict[str, Any] = {"ticker": ticker}
    if "holdings" in which:
        out["holdings"] = provider.get_etf_holdings(ticker)
    if "sectors" in which:
        out["sectors"] = provider.get_etf_sector_weightings(ticker)
    if "countries" in which:
        out["countries"] = provider.get_etf_country_weightings(ticker)
    return _text_result(out)


@tool(
    "fmp_mutual_fund_holders",
    "Mutual funds holding the named ticker, with share counts and weight.",
    {"ticker": str},
)
async def fmp_mutual_fund_holders(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result(provider.get_mutual_fund_holders(ticker))


# ── (17) Commodities ──────────────────────────────────────────────────

@tool(
    "fmp_commodity_quote",
    "Live commodity quote. Common symbols: GCUSD (gold), SIUSD (silver), "
    "CLUSD (WTI crude), BZUSD (Brent), NGUSD (nat gas), HGUSD (copper), "
    "ZWUSD (wheat), ZCUSD (corn). Empty symbol returns the full board.",
    {"symbol": str},
)
async def fmp_commodity_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _text_result({"commodities": provider.list_commodity_quotes()})
    return _text_result(provider.get_commodity_quote(symbol))


@tool(
    "fmp_commodity_history",
    "Historical commodity bars. interval ∈ {1m,5m,15m,30m,60m,4h,1d}.",
    {"symbol": str, "interval": str, "lookback": int},
)
async def fmp_commodity_history(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _text_result({"status": "rejected", "reason": "symbol is required"})
    interval = str(args.get("interval", "1d") or "1d")
    lookback = int(args.get("lookback", 90) or 90)
    return _text_result({
        "symbol": symbol, "interval": interval,
        "rows": provider.get_commodity_history(symbol, interval=interval, lookback=lookback),
    })


# ── (18) Insider + congressional trading ──────────────────────────────

@tool(
    "fmp_insider_trades",
    "Form 4 insider transactions (officer/director buys + sells). "
    "include_roster=true also returns the company's current insider list.",
    {"ticker": str, "limit": int, "include_roster": bool},
)
async def fmp_insider_trades(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    limit = int(args.get("limit", 100) or 100)
    out: Dict[str, Any] = {
        "ticker": ticker,
        "trades": provider.get_insider_trades(ticker, limit=limit),
    }
    if bool(args.get("include_roster")):
        out["roster"] = provider.get_insider_roster(ticker)
    return _text_result(out)


@tool(
    "fmp_congressional_trades",
    "Senate + House disclosed trades. chamber ∈ {senate, house, both}. "
    "Omit ticker to get the full RSS-style feed across all members.",
    {"chamber": str, "ticker": str},
)
async def fmp_congressional_trades(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    chamber = str(args.get("chamber", "both")).strip().lower()
    ticker = str(args.get("ticker", "") or "") or None
    out: Dict[str, Any] = {"ticker": ticker}
    if chamber in ("senate", "both"):
        out["senate"] = provider.get_senate_trades(ticker=ticker)
    if chamber in ("house", "both"):
        out["house"] = provider.get_house_trades(ticker=ticker)
    return _text_result(out)


# ── (19) 13F institutional holdings ───────────────────────────────────

@tool(
    "fmp_13f_filings",
    "13F holdings for an institutional filer (e.g. Berkshire Hathaway, "
    "Bridgewater). cik is the SEC CIK number — use fmp_search_filers "
    "first to look one up.",
    {"cik": str, "limit": int},
)
async def fmp_13f_filings(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    cik = str(args.get("cik", "")).strip()
    if not cik:
        return _text_result({"status": "rejected", "reason": "cik is required"})
    limit = int(args.get("limit", 25) or 25)
    return _text_result(provider.get_13f_filings(cik, limit=limit))


@tool(
    "fmp_institutional_holders",
    "List every institutional fund that holds the named ticker, with "
    "share counts and reporting date.",
    {"ticker": str},
)
async def fmp_institutional_holders(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    return _text_result(provider.get_institutional_holders(ticker))


@tool(
    "fmp_search_filers",
    "Look up an institutional filer's CIK by name (e.g. 'Berkshire'). "
    "Feed the returned CIK into fmp_13f_filings.",
    {"query": str},
)
async def fmp_search_filers(args: Dict[str, Any]) -> Dict[str, Any]:
    provider, disabled = _provider_or_disabled()
    if disabled is not None:
        return disabled
    query = str(args.get("query", "")).strip()
    if not query:
        return _text_result({"status": "rejected", "reason": "query is required"})
    return _text_result(provider.search_institutional_filer(query))


# ── tool list ──────────────────────────────────────────────────────────

FMP_TOOLS = [
    # 1+2 quotes & history
    fmp_real_time_quote, fmp_intraday_bars, fmp_daily_bars,
    # 3 indices
    fmp_index_quote, fmp_index_constituents,
    # 4 fundamentals
    fmp_financials,
    # 5 bulk
    fmp_bulk_quotes, fmp_bulk_eod, fmp_bulk_profiles,
    # 6 transcripts
    fmp_earnings_transcript, fmp_list_earnings_transcripts,
    # 7 profile / executives
    fmp_company_profile, fmp_executives,
    # 8 search & directory
    fmp_search, fmp_list_exchanges,
    # 9 calendars
    fmp_market_calendar, fmp_economic_calendar,
    # 10 news
    fmp_market_news,
    # 11 ESG
    fmp_esg,
    # 12 economics
    fmp_economic_indicator, fmp_treasury_rates,
    # 13 advanced metrics
    fmp_advanced_metrics, fmp_sector_performance,
    # 14 analyst
    fmp_analyst,
    # 15 forex
    fmp_forex_quote, fmp_forex_history,
    # 16 ETF / mutual fund
    fmp_etf_profile, fmp_etf_holdings, fmp_mutual_fund_holders,
    # 17 commodities
    fmp_commodity_quote, fmp_commodity_history,
    # 18 insider / congressional
    fmp_insider_trades, fmp_congressional_trades,
    # 19 13F
    fmp_13f_filings, fmp_institutional_holders, fmp_search_filers,
]
