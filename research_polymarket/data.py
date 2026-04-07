"""Resolved market data for Polymarket research evaluation.

Fetches closed/resolved markets from the Gamma API and determines
actual outcomes for backtesting edge detection strategies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/polymarket")
RESOLVED_CACHE = CACHE_DIR / "resolved_cache.json"

# Gamma API base (read-only, no auth)
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
_REQUEST_TIMEOUT = 15


@dataclass
class ResolvedMarket:
    """A prediction market that has resolved with a known outcome."""

    condition_id: str
    question: str
    category: str
    outcome: Literal["Yes", "No"]
    final_yes_price: float
    pre_resolution_yes_price: float
    volume_24h: float
    liquidity: float
    end_date: datetime
    history: pd.DataFrame    # columns: timestamp, price
    tokens: Dict[str, str]   # outcome -> token_id


def fetch_resolved_markets(
    max_markets: int = 100,
    crypto_only: bool = True,
) -> List[ResolvedMarket]:
    """Fetch resolved crypto price markets from Gamma API and cache results.

    Uses the /events endpoint with tag_slug=crypto. Only returns binary
    (Yes/No) markets with determinable outcomes. Filters to BTC/ETH/SOL
    price-related questions by default.
    """
    cached = _load_cache()
    if cached:
        if crypto_only:
            cached = [m for m in cached if _is_crypto_price_market(m.question)]
        logger.info("Loaded %d resolved markets from cache", len(cached))
        return cached[:max_markets]

    markets = _fetch_from_api(max_markets * 3)
    if markets:
        _save_cache(markets)

    if crypto_only:
        markets = [m for m in markets if _is_crypto_price_market(m.question)]

    return markets[:max_markets]


def _is_crypto_price_market(question: str) -> bool:
    """Check if a market question is about crypto price predictions."""
    q = question.lower()
    crypto_terms = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]
    price_terms = [
        "price", "above", "below", "up or down", "up/down", "hit",
        "dip", "reach", "all-time high", "ath",
    ]
    has_crypto = any(t in q for t in crypto_terms)
    has_price = any(t in q for t in price_terms)
    return has_crypto and has_price


def _fetch_from_api(limit: int) -> List[ResolvedMarket]:
    """Fetch resolved crypto markets from Gamma API.

    Uses the /events endpoint with tag_slug=crypto to get crypto-specific
    markets. Paginates via offset to collect enough data. Volume/liquidity
    filters are NOT applied here because resolved markets report 0 volume.
    """
    import requests

    resolved: List[ResolvedMarket] = []
    page_size = 100
    offset = 0
    max_pages = 10

    for page in range(max_pages):
        params: Dict[str, str | int] = {
            "tag_slug": "crypto",
            "closed": "true",
            "limit": page_size,
            "offset": offset,
        }

        try:
            resp = requests.get(
                f"{GAMMA_API_BASE}/events",
                params=params,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            raw_events = resp.json()
        except Exception as exc:
            logger.error("Failed to fetch resolved markets (page %d): %s", page, exc)
            break

        if not isinstance(raw_events, list) or not raw_events:
            break

        for raw_event in raw_events:
            for raw in raw_event.get("markets", []):
                if not raw.get("closed", False):
                    continue

                try:
                    market = _parse_resolved(raw)
                except (KeyError, ValueError, TypeError) as exc:
                    logger.debug("Skipping malformed resolved market: %s", exc)
                    continue

                if market is None:
                    continue

                # Fetch price history for this market
                token_id = market.tokens.get("Yes", "")
                if token_id:
                    market.history = _fetch_history(token_id, market.condition_id)

                resolved.append(market)

        offset += page_size
        if len(raw_events) < page_size:
            break

        if len(resolved) >= limit:
            break

    logger.info("Fetched %d resolved crypto markets from Gamma API", len(resolved))
    return resolved


def _parse_resolved(raw: dict) -> Optional[ResolvedMarket]:
    """Parse a raw Gamma API market into a ResolvedMarket.

    Returns None if the market isn't binary or outcome can't be determined.
    """
    outcomes_raw = raw.get("outcomes", ["Yes", "No"])
    if isinstance(outcomes_raw, str):
        try:
            outcomes_raw = json.loads(outcomes_raw)
        except json.JSONDecodeError:
            outcomes_raw = ["Yes", "No"]

    if set(outcomes_raw) != {"Yes", "No"}:
        return None

    # Determine outcome from final prices
    prices_raw = raw.get("outcomePrices", [])
    if isinstance(prices_raw, str):
        try:
            prices_raw = json.loads(prices_raw)
        except json.JSONDecodeError:
            return None

    outcome_prices: Dict[str, float] = {}
    for i, outcome in enumerate(outcomes_raw):
        if i < len(prices_raw):
            try:
                outcome_prices[outcome] = float(prices_raw[i])
            except (ValueError, TypeError):
                return None

    if "Yes" not in outcome_prices or "No" not in outcome_prices:
        return None

    yes_price = outcome_prices["Yes"]
    no_price = outcome_prices["No"]

    # Resolved markets have prices near 0 or 1
    if yes_price > 0.95:
        outcome: Literal["Yes", "No"] = "Yes"
    elif no_price > 0.95:
        outcome = "No"
    else:
        # Market resolved but prices aren't decisive — skip
        return None

    # Extract token IDs
    clob_ids_raw = raw.get("clobTokenIds", [])
    if isinstance(clob_ids_raw, str):
        try:
            clob_ids_raw = json.loads(clob_ids_raw)
        except json.JSONDecodeError:
            clob_ids_raw = []

    tokens: Dict[str, str] = {}
    for i, o in enumerate(outcomes_raw):
        if i < len(clob_ids_raw):
            tokens[o] = str(clob_ids_raw[i])

    # Parse end date
    end_date_str = raw.get("endDate", raw.get("end_date_iso", ""))
    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        end_date = datetime(2099, 12, 31, tzinfo=timezone.utc)

    return ResolvedMarket(
        condition_id=str(raw.get("conditionId", raw.get("condition_id", ""))),
        question=str(raw.get("question", "")),
        category=str(raw.get("groupSlug", raw.get("category", "other"))),
        outcome=outcome,
        final_yes_price=yes_price,
        pre_resolution_yes_price=yes_price,  # Updated from history if available
        volume_24h=float(raw.get("volume24hr", raw.get("volume_24h", 0))),
        liquidity=float(raw.get("liquidity", 0)),
        end_date=end_date,
        history=pd.DataFrame(columns=["timestamp", "price"]),
        tokens=tokens,
    )


def _fetch_history(token_id: str, condition_id: str) -> pd.DataFrame:
    """Fetch price history for a market's YES token."""
    import requests

    url = "https://clob.polymarket.com/prices-history"
    params = {"market": token_id, "interval": "max", "fidelity": 60}

    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return pd.DataFrame(columns=["timestamp", "price"])

    if isinstance(raw, dict):
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

    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
    return df


# ── Cache ──────────────────────────────────────────────────────────────

def _save_cache(markets: List[ResolvedMarket]) -> None:
    """Cache resolved markets to JSON."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = []
    for m in markets:
        data.append({
            "condition_id": m.condition_id,
            "question": m.question,
            "category": m.category,
            "outcome": m.outcome,
            "final_yes_price": m.final_yes_price,
            "pre_resolution_yes_price": m.pre_resolution_yes_price,
            "volume_24h": m.volume_24h,
            "liquidity": m.liquidity,
            "end_date": m.end_date.isoformat(),
            "tokens": m.tokens,
            "history": m.history.to_dict(orient="records") if not m.history.empty else [],
        })

    try:
        RESOLVED_CACHE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("Cached %d resolved markets", len(data))
    except OSError as exc:
        logger.warning("Cache write failed: %s", exc)


def _load_cache() -> List[ResolvedMarket]:
    """Load resolved markets from cache."""
    if not RESOLVED_CACHE.exists():
        return []

    try:
        data = json.loads(RESOLVED_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    markets: List[ResolvedMarket] = []
    for entry in data:
        try:
            end_date_str = entry.get("end_date", "")
            try:
                end_date = datetime.fromisoformat(end_date_str)
            except (ValueError, TypeError):
                end_date = datetime(2099, 12, 31, tzinfo=timezone.utc)

            history_records = entry.get("history", [])
            if history_records:
                history = pd.DataFrame(history_records)
                if "timestamp" in history.columns:
                    history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True)
            else:
                history = pd.DataFrame(columns=["timestamp", "price"])

            markets.append(ResolvedMarket(
                condition_id=entry["condition_id"],
                question=entry["question"],
                category=entry.get("category", "other"),
                outcome=entry["outcome"],
                final_yes_price=float(entry["final_yes_price"]),
                pre_resolution_yes_price=float(entry.get("pre_resolution_yes_price", 0.5)),
                volume_24h=float(entry.get("volume_24h", 0)),
                liquidity=float(entry.get("liquidity", 0)),
                end_date=end_date,
                history=history,
                tokens=entry.get("tokens", {}),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("Skipping cached market: %s", exc)
            continue

    return markets
