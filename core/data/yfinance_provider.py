"""yfinance-backed data provider — the default, free, no-key backend.

Delegates to the existing ``data_loader`` module so behaviour is
identical to the pre-provider code path. yfinance has no streaming
API, so :meth:`start_websocket` returns ``None`` and the paper
broker falls back to its 1 s reconciliation poll.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from core.data.base_provider import BaseDataProvider
from core.data.types import Bar, Quote, StreamSubscription

logger = logging.getLogger(__name__)


class YFinanceProvider(BaseDataProvider):
    """Free yfinance backend — historical bars, snapshot prices, no stream."""

    name = "yfinance"
    supports_streaming = False
    supports_fundamentals = False  # only the bare-minimum profile via fast_info

    # ── live prices ───────────────────────────────────────────────────

    def fetch_live_prices(self, tickers: List[str]) -> Dict[str, Dict[str, float]]:
        from data_loader import fetch_live_prices as _fetch
        return _fetch(tickers)

    def get_quote(self, ticker: str) -> Optional[Quote]:
        live = self.fetch_live_prices([ticker]).get(ticker, {})
        price = float(live.get("price", 0.0) or 0.0)
        if price <= 0:
            return None
        from fx import ticker_currency
        return Quote(
            ticker=ticker,
            price=price,
            change_pct=float(live.get("change_pct", 0.0) or 0.0),
            currency=ticker_currency(ticker, default="USD"),
            source=self.name,
        )

    # ── historical bars ───────────────────────────────────────────────

    def fetch_intraday_bars(
        self,
        ticker: str,
        interval: str = "5m",
        lookback_minutes: int = 240,
    ) -> List[Bar]:
        from fx import is_pence_quoted
        try:
            import yfinance as yf
        except Exception as e:
            logger.debug("yfinance import failed: %s", e)
            return []

        period = self._period_for_lookback(interval, lookback_minutes)
        try:
            df = yf.download(
                ticker, period=period, interval=interval,
                progress=False, auto_adjust=False, multi_level_index=False,
            )
        except Exception as e:
            logger.debug("yfinance intraday fetch failed for %s: %s", ticker, e)
            return []
        if df is None or df.empty:
            return []

        px_div = 100.0 if is_pence_quoted(ticker) else 1.0
        bars: List[Bar] = []
        for ts, row in df.tail(400).iterrows():
            bars.append(Bar(
                ts=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                open=float(row.get("Open", 0.0) or 0.0) / px_div,
                high=float(row.get("High", 0.0) or 0.0) / px_div,
                low=float(row.get("Low", 0.0) or 0.0) / px_div,
                close=float(row.get("Close", 0.0) or 0.0) / px_div,
                volume=float(row.get("Volume", 0.0) or 0.0),
            ))
        return bars

    def fetch_daily_bars(
        self,
        ticker: str,
        lookback_days: int = 90,
    ) -> List[Bar]:
        from data_loader import fetch_ticker_data
        from fx import is_pence_quoted

        end = datetime.utcnow().date()
        start = end - timedelta(days=max(7, lookback_days + 5))
        try:
            df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
        except Exception as e:
            logger.debug("yfinance daily fetch failed for %s: %s", ticker, e)
            return []
        if df is None or df.empty:
            return []

        px_div = 100.0 if is_pence_quoted(ticker) else 1.0
        bars: List[Bar] = []
        for ts, row in df.tail(lookback_days).iterrows():
            bars.append(Bar(
                ts=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                open=float(row.get("Open", 0.0) or 0.0) / px_div,
                high=float(row.get("High", 0.0) or 0.0) / px_div,
                low=float(row.get("Low", 0.0) or 0.0) / px_div,
                close=float(row.get("Close", 0.0) or 0.0) / px_div,
                volume=float(row.get("Volume", 0.0) or 0.0),
            ))
        return bars

    # ── streaming (not supported) ─────────────────────────────────────

    def start_websocket(
        self,
        tickers: List[str],
        on_tick: Callable[[Quote], None],
    ) -> Optional[StreamSubscription]:
        return None  # yfinance has no real-time push

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _period_for_lookback(interval: str, lookback_minutes: int) -> str:
        """Pick a yfinance ``period`` that comfortably covers the request.

        yfinance hard-caps 1m to the last 7 trading days; longer
        intervals can pull more. We round up to a generous bucket
        because ``period`` is a string and yfinance rejects exotic
        durations like "143m".
        """
        days = max(1, (lookback_minutes // (60 * 8)) + 1)
        if interval == "1m":
            return "5d" if days <= 5 else "7d"
        if days <= 5:
            return "5d"
        if days <= 30:
            return "1mo"
        if days <= 90:
            return "3mo"
        return "6mo"
