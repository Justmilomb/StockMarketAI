"""Financial Modeling Prep provider — Enterprise REST + WebSocket.

Disabled by default. Activate by:

1. Setting ``FMP_KEY`` (or whichever env var ``data_provider.fmp_key_env``
   points at) to your Enterprise key.
2. Flipping ``data_provider.fmp_enabled`` and ``data_provider.primary``
   to ``"fmp"`` in ``config.json``.

The class can be imported and instantiated regardless of those flags
— it only validates the key when it actually makes an outbound call,
so unit tests and dry runs don't need credentials.

Coverage
--------
* Real-time quotes              (``/quote/{tickers}``)
* Intraday bars                  (``/historical-chart/{interval}/{ticker}``)
* Daily OHLCV                    (``/historical-price-full/{ticker}``)
* WebSocket live ticks            (``wss://websockets.financialmodelingprep.com``)
* Company profile                (``/profile/{ticker}``)
* Financial ratios (TTM)         (``/ratios-ttm/{ticker}``)
* DCF valuation                  (``/discounted-cash-flow/{ticker}``)
* Analyst estimates              (``/analyst-estimates/{ticker}``)
* Price target consensus         (``/price-target-consensus/{ticker}``)
* Earnings calendar              (``/earning_calendar``)
* News                           (``/stock_news``)
* ETF holdings                   (``/etf-holder/{ticker}``)

GBX → GBP normalisation happens at every price boundary using
:func:`fx.is_pence_quoted` — same rule we apply to yfinance — so
the UI and broker never see pence figures.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from core.data.base_provider import BaseDataProvider
from core.data.types import Bar, Quote, StreamSubscription

logger = logging.getLogger(__name__)


_DEFAULT_REST_BASE = "https://financialmodelingprep.com/api/v3"
_DEFAULT_REST_BASE_V4 = "https://financialmodelingprep.com/api/v4"
_DEFAULT_WS_URL = "wss://websockets.financialmodelingprep.com"

# Reasonable timeouts: short for hot-path price fetches, longer for
# fundamentals which can be heavy on FMP's side.
_QUOTE_TIMEOUT_SECONDS = 6.0
_HISTORY_TIMEOUT_SECONDS = 20.0
_FUNDAMENTALS_TIMEOUT_SECONDS = 25.0


class FMPProvider(BaseDataProvider):
    """Financial Modeling Prep Enterprise provider."""

    name = "fmp"
    supports_streaming = True
    supports_fundamentals = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "FMP_KEY",
        base_url: str = _DEFAULT_REST_BASE,
        base_url_v4: str = _DEFAULT_REST_BASE_V4,
        websocket_url: str = _DEFAULT_WS_URL,
    ) -> None:
        self._explicit_key = api_key
        self._key_env = api_key_env
        self._base_url = base_url.rstrip("/")
        self._base_url_v4 = base_url_v4.rstrip("/")
        self._ws_url = websocket_url
        # Active stream registrations keyed by sub_id so update/stop
        # don't have to walk the threads.
        self._streams: Dict[str, "_FMPStream"] = {}
        self._streams_lock = threading.Lock()

    # ── auth ──────────────────────────────────────────────────────────

    def _api_key(self) -> str:
        if self._explicit_key:
            return self._explicit_key
        key = os.environ.get(self._key_env, "").strip()
        if not key:
            raise RuntimeError(
                f"FMP API key not set: env var {self._key_env} is empty. "
                "Either export it or pass api_key= when constructing the provider.",
            )
        return key

    def _has_key(self) -> bool:
        if self._explicit_key:
            return True
        return bool(os.environ.get(self._key_env, "").strip())

    # ── shared HTTP plumbing ──────────────────────────────────────────

    def _get(
        self,
        path: str,
        *,
        v4: bool = False,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = _QUOTE_TIMEOUT_SECONDS,
    ) -> Any:
        # Missing-key path: never raise from a data fetch — log and
        # return None so callers fall through to their empty-shape
        # defaults. The factory in provider.py already prevents a
        # keyless FMP from being installed as the active provider, so
        # this only fires when an FMPProvider is built directly (e.g.
        # from a test or a manual fundamentals call).
        try:
            api_key = self._api_key()
        except RuntimeError as e:
            logger.warning("fmp GET %s skipped: %s", path, e)
            return None

        import requests
        base = self._base_url_v4 if v4 else self._base_url
        url = f"{base}/{path.lstrip('/')}"
        merged = dict(params or {})
        merged["apikey"] = api_key
        try:
            resp = requests.get(url, params=merged, timeout=timeout)
        except Exception as e:
            logger.debug("fmp GET %s failed: %s", path, e)
            return None
        if resp.status_code != 200:
            logger.debug("fmp GET %s → %d %s", path, resp.status_code, resp.text[:200])
            return None
        try:
            return resp.json()
        except Exception:
            return None

    # ── live prices ───────────────────────────────────────────────────

    def fetch_live_prices(self, tickers: List[str]) -> Dict[str, Dict[str, float]]:
        from fx import is_pence_quoted
        out: Dict[str, Dict[str, float]] = {t: {"price": 0.0, "change_pct": 0.0} for t in tickers}
        if not tickers:
            return out
        # FMP's batch quote endpoint takes a comma-separated symbol
        # list. Cap at 200 per call to be safe under Enterprise limits.
        for chunk_start in range(0, len(tickers), 200):
            chunk = tickers[chunk_start:chunk_start + 200]
            symbols = ",".join(quote(t, safe=":-_/.") for t in chunk)
            data = self._get(f"quote/{symbols}")
            if not isinstance(data, list):
                continue
            for row in data:
                ticker = str(row.get("symbol", "")).strip()
                if not ticker:
                    continue
                price = float(row.get("price", 0.0) or 0.0)
                change_pct = float(row.get("changesPercentage", 0.0) or 0.0)
                if is_pence_quoted(ticker):
                    price = price / 100.0
                # Map back onto the user-supplied ticker — FMP echoes
                # the input, but case may differ on dual-listings.
                key = ticker if ticker in out else _match_ticker(ticker, chunk)
                if key:
                    out[key] = {"price": price, "change_pct": change_pct}
        return out

    def get_quote(self, ticker: str) -> Optional[Quote]:
        from fx import is_pence_quoted, ticker_currency
        data = self._get(f"quote/{quote(ticker, safe=':-_/.')}")
        row: Optional[Dict[str, Any]] = None
        if isinstance(data, list) and data:
            row = data[0]
        elif isinstance(data, dict):
            row = data
        if not row:
            return None
        price = float(row.get("price", 0.0) or 0.0)
        if price <= 0:
            return None
        if is_pence_quoted(ticker):
            price = price / 100.0
        return Quote(
            ticker=ticker,
            price=price,
            change_pct=float(row.get("changesPercentage", 0.0) or 0.0),
            volume=float(row.get("volume", 0.0) or 0.0),
            currency=ticker_currency(ticker, default="USD"),
            timestamp=str(row.get("timestamp") or ""),
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
        # FMP exposes intervals as "1min" / "5min" / "15min" / "30min"
        # / "1hour" / "4hour"; we accept the yfinance-style spelling
        # we already pass through the codebase and translate here.
        fmp_interval = _normalise_interval(interval)
        if fmp_interval is None:
            return []
        data = self._get(
            f"historical-chart/{fmp_interval}/{quote(ticker, safe=':-_/.')}",
            timeout=_HISTORY_TIMEOUT_SECONDS,
        )
        if not isinstance(data, list):
            return []
        # FMP returns newest-first; flip so callers see oldest→newest
        # (the same shape yfinance produces).
        data = list(reversed(data))
        px_div = 100.0 if is_pence_quoted(ticker) else 1.0
        bars: List[Bar] = []
        # Approximate lookback filter: drop anything older than
        # lookback_minutes before the latest bar so a 240-minute
        # request doesn't return a full week.
        if lookback_minutes > 0 and data:
            from datetime import datetime, timedelta
            try:
                latest = datetime.fromisoformat(str(data[-1].get("date")).replace(" ", "T"))
                cutoff = latest - timedelta(minutes=lookback_minutes)
                data = [
                    row for row in data
                    if datetime.fromisoformat(str(row.get("date")).replace(" ", "T")) >= cutoff
                ]
            except Exception:
                pass
        for row in data:
            bars.append(Bar(
                ts=str(row.get("date", "")),
                open=float(row.get("open", 0.0) or 0.0) / px_div,
                high=float(row.get("high", 0.0) or 0.0) / px_div,
                low=float(row.get("low", 0.0) or 0.0) / px_div,
                close=float(row.get("close", 0.0) or 0.0) / px_div,
                volume=float(row.get("volume", 0.0) or 0.0),
            ))
        return bars

    def fetch_daily_bars(
        self,
        ticker: str,
        lookback_days: int = 90,
    ) -> List[Bar]:
        from fx import is_pence_quoted
        data = self._get(
            f"historical-price-full/{quote(ticker, safe=':-_/.')}",
            params={"timeseries": max(1, lookback_days)},
            timeout=_HISTORY_TIMEOUT_SECONDS,
        )
        if not isinstance(data, dict):
            return []
        rows = data.get("historical")
        if not isinstance(rows, list):
            return []
        rows = list(reversed(rows))  # FMP returns newest-first
        px_div = 100.0 if is_pence_quoted(ticker) else 1.0
        bars: List[Bar] = []
        for row in rows[-lookback_days:]:
            bars.append(Bar(
                ts=str(row.get("date", "")),
                open=float(row.get("open", 0.0) or 0.0) / px_div,
                high=float(row.get("high", 0.0) or 0.0) / px_div,
                low=float(row.get("low", 0.0) or 0.0) / px_div,
                close=float(row.get("close", 0.0) or 0.0) / px_div,
                volume=float(row.get("volume", 0.0) or 0.0),
            ))
        return bars

    # ── WebSocket streaming ───────────────────────────────────────────

    def start_websocket(
        self,
        tickers: List[str],
        on_tick: Callable[[Quote], None],
    ) -> Optional[StreamSubscription]:
        if not self._has_key():
            logger.warning("fmp websocket: no API key, skipping")
            return None
        sub_id = f"fmp-{uuid.uuid4().hex[:8]}"
        try:
            stream = _FMPStream(
                ws_url=self._ws_url,
                api_key=self._api_key(),
                tickers=list(tickers),
                on_tick=on_tick,
            )
        except Exception as e:
            logger.warning("fmp websocket init failed: %s", e)
            return None
        stream.start()
        with self._streams_lock:
            self._streams[sub_id] = stream
        return StreamSubscription(sub_id=sub_id, tickers=list(tickers), handle=stream)

    def stop_websocket(self, subscription: StreamSubscription) -> None:
        with self._streams_lock:
            stream = self._streams.pop(subscription.sub_id, None)
        if stream is not None:
            stream.stop()

    def update_websocket_tickers(
        self,
        subscription: StreamSubscription,
        tickers: List[str],
    ) -> None:
        with self._streams_lock:
            stream = self._streams.get(subscription.sub_id)
        if stream is None:
            return
        stream.update_tickers(list(tickers))
        subscription.tickers = list(tickers)

    # ── fundamentals ──────────────────────────────────────────────────

    def get_company_profile(self, ticker: str) -> Dict[str, Any]:
        data = self._get(
            f"profile/{quote(ticker, safe=':-_/.')}",
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict):
            return data
        return {}

    def get_financial_ratios(self, ticker: str) -> Dict[str, Any]:
        data = self._get(
            f"ratios-ttm/{quote(ticker, safe=':-_/.')}",
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        return {}

    def get_dcf(self, ticker: str) -> Dict[str, Any]:
        data = self._get(
            f"discounted-cash-flow/{quote(ticker, safe=':-_/.')}",
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict):
            return data
        return {}

    def get_analyst_estimates(self, ticker: str) -> Dict[str, Any]:
        data = self._get(
            f"analyst-estimates/{quote(ticker, safe=':-_/.')}",
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        if isinstance(data, list):
            return {"estimates": data}
        return {}

    def get_price_target(self, ticker: str) -> Dict[str, Any]:
        data = self._get(
            f"price-target-consensus",
            v4=True,
            params={"symbol": ticker},
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        if isinstance(data, list) and data:
            return dict(data[0])
        if isinstance(data, dict):
            return data
        return {}

    def get_earnings_calendar(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if ticker:
            data = self._get(
                f"historical/earning_calendar/{quote(ticker, safe=':-_/.')}",
                timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
            )
        else:
            params: Dict[str, Any] = {}
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date
            data = self._get(
                "earning_calendar",
                params=params or None,
                timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
            )
        return data if isinstance(data, list) else []

    def get_news(
        self,
        tickers: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if tickers:
            params["tickers"] = ",".join(tickers)
        data = self._get(
            "stock_news",
            params=params,
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        return data if isinstance(data, list) else []

    def get_etf_holdings(self, ticker: str) -> List[Dict[str, Any]]:
        data = self._get(
            f"etf-holder/{quote(ticker, safe=':-_/.')}",
            timeout=_FUNDAMENTALS_TIMEOUT_SECONDS,
        )
        return data if isinstance(data, list) else []

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        with self._streams_lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.stop()


# ─────────────────────────────────────────────────────────────────────
# WebSocket stream implementation
# ─────────────────────────────────────────────────────────────────────

class _FMPStream:
    """Background WebSocket worker.

    Runs on its own daemon thread. The thread:
    1. Opens the socket
    2. Sends the login payload
    3. Subscribes to every requested ticker
    4. Reads frames, decodes, fires ``on_tick``
    5. Auto-reconnects on disconnect with backoff

    GBX → GBP conversion is applied per tick. Callbacks are wrapped
    in try/except so a buggy listener can't poison the loop.
    """

    def __init__(
        self,
        ws_url: str,
        api_key: str,
        tickers: List[str],
        on_tick: Callable[[Quote], None],
    ) -> None:
        self._ws_url = ws_url
        self._api_key = api_key
        self._tickers = [t.lower() for t in tickers]
        self._on_tick = on_tick
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._ws: Any = None  # websocket-client connection

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        t = threading.Thread(target=self._run, name="fmp-ws", daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)

    def update_tickers(self, tickers: List[str]) -> None:
        new = [t.lower() for t in tickers]
        with self._lock:
            old = set(self._tickers)
            new_set = set(new)
            self._tickers = new
        ws = self._ws
        if ws is None:
            return
        # Subscribe newcomers, unsubscribe drops. Idempotent on the FMP side.
        for t in new_set - old:
            self._send(ws, {"event": "subscribe", "data": {"ticker": t}})
        for t in old - new_set:
            self._send(ws, {"event": "unsubscribe", "data": {"ticker": t}})

    # ── internals ─────────────────────────────────────────────────────

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._connect_and_loop()
                backoff = 1.0  # reset after a clean session
            except Exception as e:
                logger.warning("fmp websocket session ended: %s", e)
            if self._stop.is_set():
                break
            # Exponential backoff capped at 30 s — long enough that a
            # broken Enterprise endpoint doesn't burn the rate limit.
            self._stop.wait(timeout=backoff)
            backoff = min(backoff * 2.0, 30.0)

    def _connect_and_loop(self) -> None:
        try:
            from websocket import create_connection  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "websocket-client not installed; pip install websocket-client"
            ) from e

        ws = create_connection(self._ws_url, timeout=10)
        self._ws = ws
        # Login
        self._send(ws, {"event": "login", "data": {"apiKey": self._api_key}})
        # Subscribe to every ticker we know about. Take a snapshot so
        # update_tickers can edit the list mid-session safely.
        with self._lock:
            initial = list(self._tickers)
        for t in initial:
            self._send(ws, {"event": "subscribe", "data": {"ticker": t}})

        from fx import is_pence_quoted, ticker_currency
        while not self._stop.is_set():
            try:
                raw = ws.recv()
            except Exception as e:
                logger.debug("fmp websocket recv error: %s", e)
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            # FMP frames carry a "lp" (last price) field on price ticks.
            ticker = str(msg.get("s", "")).upper()
            price = msg.get("lp")
            if not ticker or price is None:
                continue
            try:
                price_f = float(price)
            except (TypeError, ValueError):
                continue
            if is_pence_quoted(ticker):
                price_f = price_f / 100.0
            quote_ = Quote(
                ticker=ticker,
                price=price_f,
                change_pct=0.0,  # FMP ticks don't carry day-change
                bid=_safe_float(msg.get("bp")),
                ask=_safe_float(msg.get("ap")),
                volume=_safe_float(msg.get("v")),
                currency=ticker_currency(ticker, default="USD"),
                timestamp=str(msg.get("t", "")),
                source="fmp",
            )
            try:
                self._on_tick(quote_)
            except Exception:
                logger.exception("fmp on_tick callback raised")

    @staticmethod
    def _send(ws: Any, payload: Dict[str, Any]) -> None:
        try:
            ws.send(json.dumps(payload))
        except Exception as e:
            logger.debug("fmp websocket send failed: %s", e)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _normalise_interval(interval: str) -> Optional[str]:
    """Map yfinance-style interval strings to FMP's spelling."""
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "1hour",
        "1h": "1hour",
        "4h": "4hour",
        "1d": "1day",
    }
    return mapping.get(interval.lower())


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _match_ticker(returned: str, requested: List[str]) -> Optional[str]:
    """Find the user-supplied ticker that maps to FMP's echoed symbol.

    FMP often canonicalises case; users may have submitted ``rr.l``
    while FMP echoes ``RR.L``. Match case-insensitively and prefer
    exact length to avoid a stray prefix collision.
    """
    target = returned.upper()
    for t in requested:
        if t.upper() == target:
            return t
    return None
