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

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Tear down any sockets / thread pools the provider holds."""
        return None
