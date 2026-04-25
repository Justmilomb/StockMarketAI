"""Abstract data provider — the single interface every backend implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from core.data.types import Bar, Quote, StreamSubscription


class BaseDataProvider(ABC):
    """Single typed interface for every market-data backend.

    Implementations:
    * :class:`core.data.yfinance_provider.YFinanceProvider` — default.
      Free, polite, slow; no streaming.
    * :class:`core.data.fmp_provider.FMPProvider` — Financial Modeling
      Prep Enterprise. Real-time REST + WebSocket; fundamentals,
      ratios, DCF, analyst targets, earnings calendar, news.

    Capability flags
    ----------------
    * :attr:`supports_streaming` — whether ``start_websocket`` actually
      pushes ticks. The paper broker checks this at startup and
      subscribes when True; otherwise it falls back to 1 s polling.
    * :attr:`supports_fundamentals` — whether the fundamentals /
      ratios / DCF / analyst methods return data or NotImplemented.
    """

    name: str = "base"
    supports_streaming: bool = False
    supports_fundamentals: bool = False

    # ── live prices ───────────────────────────────────────────────────

    @abstractmethod
    def fetch_live_prices(self, tickers: List[str]) -> Dict[str, Dict[str, float]]:
        """Snapshot price for every ticker. Shape: ``{ticker: {price, change_pct}}``.

        Missing tickers map to ``{"price": 0.0, "change_pct": 0.0}``
        so callers can treat the response as a complete dict. Always
        returns prices in the ticker's *account* currency convention
        (pence are converted to pounds at the boundary).
        """

    @abstractmethod
    def get_quote(self, ticker: str) -> Optional[Quote]:
        """Single-ticker quote with optional bid/ask/volume."""

    # ── historical bars ───────────────────────────────────────────────

    @abstractmethod
    def fetch_intraday_bars(
        self,
        ticker: str,
        interval: str = "5m",
        lookback_minutes: int = 240,
    ) -> List[Bar]:
        """Recent intraday OHLCV — interval one of 1m/5m/15m/30m/60m."""

    @abstractmethod
    def fetch_daily_bars(
        self,
        ticker: str,
        lookback_days: int = 90,
    ) -> List[Bar]:
        """Daily OHLCV bars over the last ``lookback_days``."""

    # ── streaming ─────────────────────────────────────────────────────

    def start_websocket(
        self,
        tickers: List[str],
        on_tick: Callable[[Quote], None],
    ) -> Optional[StreamSubscription]:
        """Subscribe to real-time tick updates. Returns ``None`` when unsupported.

        ``on_tick`` is called from the provider's worker thread for
        every tick. Implementations MUST swallow callback exceptions
        so a buggy listener can't kill the stream.
        """
        return None

    def stop_websocket(self, subscription: StreamSubscription) -> None:
        """Tear down a stream started by :meth:`start_websocket`. Idempotent."""
        return None

    def update_websocket_tickers(
        self,
        subscription: StreamSubscription,
        tickers: List[str],
    ) -> None:
        """Replace the subscribed tickers on an existing stream. Optional."""
        return None

    # ── fundamentals (optional) ───────────────────────────────────────

    def get_company_profile(self, ticker: str) -> Dict[str, Any]:
        """Name, sector, industry, market cap, description. Empty dict if unsupported."""
        return {}

    def get_financial_ratios(self, ticker: str) -> Dict[str, Any]:
        return {}

    def get_dcf(self, ticker: str) -> Dict[str, Any]:
        return {}

    def get_analyst_estimates(self, ticker: str) -> Dict[str, Any]:
        return {}

    def get_price_target(self, ticker: str) -> Dict[str, Any]:
        return {}

    def get_earnings_calendar(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return []

    def get_news(
        self,
        tickers: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return []

    def get_etf_holdings(self, ticker: str) -> List[Dict[str, Any]]:
        return []

    # ── extended catalogue (FMP-backed) ───────────────────────────────
    # Default implementations return empty so the yfinance backend is
    # still complete. Callers should check ``supports_fundamentals``
    # (or just look for empty results) and handle the unsupported case.

    # Index data
    def list_indices(self) -> List[Dict[str, Any]]: return []
    def get_index_quote(self, symbol: str) -> Dict[str, Any]: return {}
    def get_index_constituents(self, index: str) -> List[Dict[str, Any]]: return []

    # Financial statements
    def get_income_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []
    def get_balance_sheet(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []
    def get_cash_flow_statement(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []
    def get_key_metrics(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []
    def get_financial_growth(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []
    def get_enterprise_value(self, ticker: str, period: str = "annual", limit: int = 5) -> List[Dict[str, Any]]: return []

    # Bulk
    def bulk_profiles(self, part: int = 0) -> List[Dict[str, Any]]: return []
    def bulk_quotes(self, exchange: str = "NASDAQ") -> List[Dict[str, Any]]: return []
    def bulk_eod_prices(self, date: str) -> List[Dict[str, Any]]: return []

    # Earnings transcripts
    def get_earnings_transcript(
        self, ticker: str, year: Optional[int] = None, quarter: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {}
    def list_earnings_transcripts(self, ticker: str) -> List[Dict[str, Any]]: return []

    # Executives
    def get_executives(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_executive_compensation(self, ticker: str) -> List[Dict[str, Any]]: return []

    # Search & directory
    def search_symbol(self, query: str, limit: int = 10, exchange: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def list_tradable_symbols(self) -> List[Dict[str, Any]]: return []
    def list_exchanges(self) -> List[Dict[str, Any]]: return []

    # Calendars
    def get_ipo_calendar(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def get_dividend_calendar(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def get_split_calendar(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]: return []

    # News
    def get_general_news(self, limit: int = 50) -> List[Dict[str, Any]]: return []
    def get_press_releases(self, ticker: str, limit: int = 25) -> List[Dict[str, Any]]: return []

    # ESG
    def get_esg_score(self, ticker: str) -> Dict[str, Any]: return {}
    def get_esg_ratings(self, ticker: str) -> List[Dict[str, Any]]: return []

    # Economics
    def get_economic_indicator(
        self, name: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return []
    def get_treasury_rates(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def get_economic_calendar(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> List[Dict[str, Any]]: return []

    # Advanced metrics
    def get_market_cap(self, ticker: str) -> Dict[str, Any]: return {}
    def get_share_float(self, ticker: str) -> Dict[str, Any]: return {}
    def get_short_interest(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_sector_pe(self, exchange: str = "NYSE", date: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def get_sector_performance(self) -> List[Dict[str, Any]]: return []

    # Analyst extras
    def list_price_targets(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_upgrades_downgrades(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_stock_grade(self, ticker: str) -> List[Dict[str, Any]]: return []

    # Forex
    def get_forex_quote(self, pair: str) -> Dict[str, Any]: return {}
    def list_forex_quotes(self) -> List[Dict[str, Any]]: return []
    def get_forex_history(self, pair: str, interval: str = "1d", lookback: int = 90) -> List[Dict[str, Any]]: return []

    # ETFs / mutual funds
    def get_etf_profile(self, ticker: str) -> Dict[str, Any]: return {}
    def get_etf_sector_weightings(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_etf_country_weightings(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_mutual_fund_holders(self, ticker: str) -> List[Dict[str, Any]]: return []

    # Commodities
    def get_commodity_quote(self, symbol: str) -> Dict[str, Any]: return {}
    def list_commodity_quotes(self) -> List[Dict[str, Any]]: return []
    def get_commodity_history(self, symbol: str, interval: str = "1d", lookback: int = 90) -> List[Dict[str, Any]]: return []

    # Insider / congressional
    def get_insider_trades(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]: return []
    def get_insider_roster(self, ticker: str) -> List[Dict[str, Any]]: return []
    def get_senate_trades(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]: return []
    def get_house_trades(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]: return []

    # 13F
    def get_13f_filings(self, cik: str, limit: int = 25) -> List[Dict[str, Any]]: return []
    def get_institutional_holders(self, ticker: str) -> List[Dict[str, Any]]: return []
    def search_institutional_filer(self, query: str) -> List[Dict[str, Any]]: return []

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Tear down any sockets / thread pools the provider holds."""
        return None
