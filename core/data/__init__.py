"""Pluggable data-provider layer.

Existing call sites that fetch market data (prices, bars, fundamentals,
news) should depend on :func:`core.data.provider.get_provider` rather
than reaching into yfinance directly. The provider is selected at
runtime from ``config.json`` under ``data_provider``.

Default: yfinance (free, slow, rate-limited). Optional: FMP Enterprise
(real-time REST + WebSocket streaming, fundamentals, analyst data).
"""
from core.data.provider import get_provider, reset_provider
from core.data.types import Bar, Quote

__all__ = ["get_provider", "reset_provider", "Bar", "Quote"]
