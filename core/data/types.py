"""Shared dataclasses for the data-provider layer.

Every provider returns these same shapes so call sites don't care
whether the data came from yfinance, FMP, or anything we plug in
later. Prices are always in the *account* sense (pounds, not pence —
provider implementations normalise GBX→GBP at ingress).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Quote:
    """A single live price snapshot."""

    ticker: str
    price: float
    change_pct: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    currency: str = "USD"
    timestamp: Optional[str] = None  # ISO-8601 if known
    source: str = "unknown"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "change_pct": self.change_pct,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "currency": self.currency,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass
class Bar:
    """One OHLCV bar."""

    ts: str  # ISO-8601
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class StreamSubscription:
    """Handle returned by :meth:`BaseDataProvider.start_websocket`.

    Callers don't introspect the fields — they just pass the handle
    back to ``stop_websocket``. Keeps the provider free to stash
    whatever bookkeeping it needs (thread, websocket client, etc).
    """

    sub_id: str
    tickers: List[str] = field(default_factory=list)
    handle: Any = None  # opaque — provider-specific
