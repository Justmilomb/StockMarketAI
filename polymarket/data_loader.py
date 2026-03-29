"""Data loading for Polymarket prediction markets.

Fetches market data from the Polymarket Gamma API (read-only, no auth)
and the CLOB API for orderbook depth.  Results are cached as JSON in
``data/polymarket/`` to reduce API calls during development.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from polymarket.types import PolymarketEvent

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
CACHE_DIR = Path("data/polymarket")

# Gamma API sometimes returns paginated results
_DEFAULT_LIMIT = 100
_REQUEST_TIMEOUT = 15


# ── Public API ────────────────────────────────────────────────────────


def fetch_markets(
    active_only: bool = True,
    min_volume: float = 0,
    limit: int = _DEFAULT_LIMIT,
    category: Optional[str] = None,
) -> List[PolymarketEvent]:
    """Fetch prediction markets from the Gamma API.

    Args:
        active_only: Only return markets that are still open.
        min_volume: Minimum 24h volume in USD.
        limit: Maximum number of markets to return.
        category: Optional category filter (e.g. "politics", "crypto").

    Returns:
        List of PolymarketEvent dataclasses sorted by 24h volume desc.
    """
    params: Dict[str, str | int | bool] = {
        "limit": limit,
        "order": "volume24hr",
        "ascending": "false",
    }
    if active_only:
        params["active"] = "true"
        params["closed"] = "false"
    if category:
        params["tag"] = category

    raw_markets = _gamma_get("/markets", params)
    if raw_markets is None:
        return []

    events: List[PolymarketEvent] = []
    for m in raw_markets:
        try:
            event = _parse_market(m)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Skipping malformed market: %s", exc)
            continue

        if event.volume_24h >= min_volume:
            events.append(event)

    _cache_write("markets_latest.json", raw_markets)
    logger.info("Fetched %d Polymarket events (active=%s)", len(events), active_only)
    return events


def fetch_market_history(condition_id: str) -> pd.DataFrame:
    """Fetch YES-token price timeseries for a single market.

    Returns a DataFrame with columns: timestamp, price (YES probability).
    Falls back to cached data if the API call fails.
    """
    cache_key = f"history_{condition_id}.json"
    params: Dict[str, str | int] = {
        "market": condition_id,
        "interval": "max",
        "fidelity": 60,  # 1-hour candles
    }

    raw = _gamma_get("/prices-history", params)
    if raw is None:
        cached = _cache_read(cache_key)
        if cached is not None:
            return _history_to_dataframe(cached)
        return pd.DataFrame(columns=["timestamp", "price"])

    _cache_write(cache_key, raw)
    return _history_to_dataframe(raw)


def fetch_orderbook(token_id: str) -> Dict[str, List[Dict[str, float]]]:
    """Fetch current orderbook for a token from the CLOB API.

    Returns dict with 'bids' and 'asks', each a list of
    {price, size} dicts.  Returns empty orderbook on failure.
    """
    empty: Dict[str, List[Dict[str, float]]] = {"bids": [], "asks": []}
    url = f"{CLOB_API_BASE}/book"
    params = {"token_id": token_id}

    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        logger.warning("Orderbook fetch failed for token %s: %s", token_id, exc)
        return empty

    bids = [
        {"price": float(b.get("price", 0)), "size": float(b.get("size", 0))}
        for b in data.get("bids", [])
    ]
    asks = [
        {"price": float(a.get("price", 0)), "size": float(a.get("size", 0))}
        for a in data.get("asks", [])
    ]
    return {"bids": bids, "asks": asks}


# ── Internal helpers ──────────────────────────────────────────────────


def _gamma_get(
    endpoint: str,
    params: Dict[str, str | int | bool] | None = None,
) -> Optional[list | dict]:
    """Make a GET request to the Gamma API with error handling."""
    url = f"{GAMMA_API_BASE}{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        logger.error("Gamma API timeout on %s", endpoint)
    except requests.HTTPError as exc:
        logger.error("Gamma API HTTP error on %s: %s", endpoint, exc)
    except requests.ConnectionError:
        logger.error("Gamma API connection failed on %s", endpoint)
    except json.JSONDecodeError:
        logger.error("Gamma API returned invalid JSON on %s", endpoint)
    return None


def _parse_market(raw: dict) -> PolymarketEvent:
    """Parse a raw Gamma API market object into a PolymarketEvent."""
    # Gamma API provides outcome prices in a nested structure
    outcomes = raw.get("outcomes", ["Yes", "No"])
    outcome_prices_raw = raw.get("outcomePrices", [])

    outcome_prices: Dict[str, float] = {}
    tokens: Dict[str, str] = {}

    if isinstance(outcome_prices_raw, str):
        # Sometimes returned as JSON string
        try:
            outcome_prices_raw = json.loads(outcome_prices_raw)
        except json.JSONDecodeError:
            outcome_prices_raw = []

    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = ["Yes", "No"]

    for i, outcome in enumerate(outcomes):
        if i < len(outcome_prices_raw):
            try:
                outcome_prices[outcome] = float(outcome_prices_raw[i])
            except (ValueError, TypeError):
                outcome_prices[outcome] = 0.5

    # Extract token IDs from clobTokenIds
    clob_ids_raw = raw.get("clobTokenIds", [])
    if isinstance(clob_ids_raw, str):
        try:
            clob_ids_raw = json.loads(clob_ids_raw)
        except json.JSONDecodeError:
            clob_ids_raw = []
    for i, outcome in enumerate(outcomes):
        if i < len(clob_ids_raw):
            tokens[outcome] = str(clob_ids_raw[i])

    # Parse end date — Gamma uses ISO 8601
    end_date_str = raw.get("endDate", raw.get("end_date_iso", ""))
    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        end_date = datetime(2099, 12, 31, tzinfo=timezone.utc)

    return PolymarketEvent(
        condition_id=str(raw.get("conditionId", raw.get("condition_id", ""))),
        question=str(raw.get("question", "")),
        description=str(raw.get("description", "")),
        category=str(raw.get("groupSlug", raw.get("category", "other"))),
        end_date=end_date,
        outcome_prices=outcome_prices,
        volume_24h=float(raw.get("volume24hr", raw.get("volume_24h", 0))),
        liquidity=float(raw.get("liquidity", 0)),
        num_traders=int(raw.get("uniqueTraders", raw.get("num_traders", 0))),
        slug=str(raw.get("slug", "")),
        active=bool(raw.get("active", True)),
        closed=bool(raw.get("closed", False)),
        tokens=tokens,
    )


def _history_to_dataframe(raw: list | dict) -> pd.DataFrame:
    """Convert raw price-history response to a clean DataFrame."""
    if isinstance(raw, dict):
        # Some endpoints wrap the array in {"history": [...]}
        raw = raw.get("history", [])

    if not raw:
        return pd.DataFrame(columns=["timestamp", "price"])

    records = []
    for point in raw:
        try:
            ts = point.get("t", point.get("timestamp", 0))
            price = float(point.get("p", point.get("price", 0.5)))
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            records.append({"timestamp": dt, "price": price})
        except (ValueError, TypeError, OSError):
            continue

    if not records:
        return pd.DataFrame(columns=["timestamp", "price"])

    df = pd.DataFrame(records)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _cache_write(filename: str, data: list | dict) -> None:
    """Write API response to JSON cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / filename
    try:
        path.write_text(json.dumps(data, default=str), encoding="utf-8")
    except OSError as exc:
        logger.debug("Cache write failed for %s: %s", filename, exc)


def _cache_read(filename: str) -> Optional[list | dict]:
    """Read cached JSON data. Returns None if missing or corrupt."""
    path = CACHE_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
