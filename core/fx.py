"""Lightweight FX + ticker-currency helpers.

Used by the paper broker at fill time (to convert a USD-denominated
share price into the account's GBP cash ledger) and by the agent's
``size_position`` tool (to quote Kelly sizing in the correct currency).

Two public functions:

* :func:`ticker_currency` — what currency is this instrument priced in?
* :func:`fx_rate` — how many ``to`` per one ``from``?

Both cache results in a small module-level dict keyed by
``(from, to)`` / ``ticker``. Rates move on a scale of minutes, not
milliseconds, so the simple cache is enough for paper fills and
sizing hints. Both functions degrade gracefully: when yfinance is
unreachable or rate-limited, they fall back to **1.0** (no
conversion) and the caller logs a debug line. That keeps the paper
broker functional in airplane-mode testing at the cost of a small
tracking error — acceptable for a £100 sandbox.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ── caches ─────────────────────────────────────────────────────────────

_RATE_CACHE: Dict[tuple[str, str], float] = {}
_TICKER_CCY_CACHE: Dict[str, str] = {}


# Yahoo ticker suffixes → currency. When a ticker ends in one of these
# and yfinance's fast_info can't tell us the currency (rate-limited,
# fresh ticker, etc.), this map is the backstop. Built from the set of
# venues ``get_market_status`` already knows about; keep them in sync.
_SUFFIX_CCY: Dict[str, str] = {
    ".L": "GBP",       # London
    ".DE": "EUR",      # XETRA
    ".F": "EUR",       # Frankfurt
    ".PA": "EUR",      # Euronext Paris
    ".AS": "EUR",      # Euronext Amsterdam
    ".BR": "EUR",      # Euronext Brussels
    ".LS": "EUR",      # Euronext Lisbon
    ".MC": "EUR",      # BME Madrid
    ".MI": "EUR",      # Borsa Italiana
    ".SW": "CHF",      # SIX Swiss
    ".ST": "SEK",      # Nasdaq Stockholm
    ".HE": "EUR",      # Nasdaq Helsinki
    ".CO": "DKK",      # Nasdaq Copenhagen
    ".OL": "NOK",      # Oslo
    ".TA": "ILS",      # Tel Aviv
    ".TO": "CAD",      # Toronto
    ".V": "CAD",       # Venture
    ".AX": "AUD",      # Australia
    ".HK": "HKD",      # Hong Kong
    ".T": "JPY",       # Tokyo
}


def _normalise(ccy: str) -> str:
    return (ccy or "").strip().upper()


# ── ticker currency ────────────────────────────────────────────────────

def ticker_currency(ticker: str, default: str = "USD") -> str:
    """Return the currency code a given ticker is quoted in.

    Tries yfinance's ``fast_info`` first (cheap, cached by yfinance).
    Falls back to the Yahoo suffix map above, then to ``default`` (USD
    for bare symbols, matching NYSE/NASDAQ convention).

    The result is cached per-ticker for the lifetime of the process.
    """
    if not ticker:
        return default
    key = ticker.upper()
    if key in _TICKER_CCY_CACHE:
        return _TICKER_CCY_CACHE[key]

    ccy: Optional[str] = None

    # Step 1 — yfinance fast_info (fast, avoids the heavy .info path)
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        raw = fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None)
        if isinstance(raw, str) and raw:
            ccy = _normalise(raw)
    except Exception as exc:
        logger.debug("fast_info currency lookup failed for %s: %s", ticker, exc)

    # Step 2 — suffix map fallback
    if not ccy:
        for suffix, mapped in _SUFFIX_CCY.items():
            if key.endswith(suffix):
                ccy = mapped
                break

    # Step 3 — final fallback
    if not ccy:
        ccy = _normalise(default)

    _TICKER_CCY_CACHE[key] = ccy
    return ccy


# ── fx rate ────────────────────────────────────────────────────────────

def fx_rate(src: str, dst: str) -> float:
    """Return the multiplier converting ``src`` into ``dst``.

    ``amount_in_dst = amount_in_src * fx_rate(src, dst)``.

    Uses yfinance currency pairs (``{src}{dst}=X``), cached per-pair
    for the process lifetime. Returns 1.0 if the currencies match,
    and also returns 1.0 as a safe fallback when yfinance is
    unavailable — a stale-rate trade is annoying; a crash is worse.
    """
    src_n = _normalise(src)
    dst_n = _normalise(dst)
    if not src_n or not dst_n or src_n == dst_n:
        return 1.0

    key = (src_n, dst_n)
    cached = _RATE_CACHE.get(key)
    if cached is not None:
        return cached

    rate: Optional[float] = None
    try:
        import yfinance as yf
        pair = yf.Ticker(f"{src_n}{dst_n}=X").fast_info
        raw = None
        if hasattr(pair, "last_price"):
            raw = pair.last_price
        if raw is None and hasattr(pair, "get"):
            raw = pair.get("last_price") or pair.get("lastPrice")
        if raw is not None and float(raw) > 0:
            rate = float(raw)
    except Exception as exc:
        logger.debug("fx rate %s→%s failed: %s", src_n, dst_n, exc)

    # Try inverse pair (some crosses only quote one direction)
    if rate is None:
        try:
            import yfinance as yf
            inv = yf.Ticker(f"{dst_n}{src_n}=X").fast_info
            raw = None
            if hasattr(inv, "last_price"):
                raw = inv.last_price
            if raw is None and hasattr(inv, "get"):
                raw = inv.get("last_price") or inv.get("lastPrice")
            if raw is not None and float(raw) > 0:
                rate = 1.0 / float(raw)
        except Exception as exc:
            logger.debug("fx rate inverse %s→%s failed: %s", dst_n, src_n, exc)

    if rate is None or rate <= 0:
        logger.warning(
            "fx_rate %s→%s unavailable — defaulting to 1.0 (no conversion)",
            src_n, dst_n,
        )
        rate = 1.0

    _RATE_CACHE[key] = rate
    return rate


def convert(amount: float, src: str, dst: str) -> float:
    """Convert ``amount`` from ``src`` currency to ``dst`` currency."""
    return float(amount) * fx_rate(src, dst)


def clear_cache() -> None:
    """Drop all cached rates + currencies. Used by tests."""
    _RATE_CACHE.clear()
    _TICKER_CCY_CACHE.clear()
