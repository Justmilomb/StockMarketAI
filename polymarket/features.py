"""Feature engineering for prediction markets.

Unlike OHLCV-based features for stocks/crypto, prediction-market
features centre on probability dynamics, time decay, and volume
patterns.  The "price" of a YES share IS the probability, so
momentum here means "the market is becoming more/less convinced".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from polymarket.types import PolymarketEvent

logger = logging.getLogger(__name__)


def build_event_features(
    event: PolymarketEvent,
    price_history: Optional[pd.DataFrame] = None,
    orderbook: Optional[Dict[str, List[Dict[str, float]]]] = None,
) -> Dict[str, float]:
    """Build feature vector for a single prediction-market event.

    Args:
        event: The market event with current prices and metadata.
        price_history: Optional DataFrame with 'timestamp' and 'price'
            columns (YES token price over time).
        orderbook: Optional orderbook with 'bids' and 'asks' lists,
            each containing {price, size} dicts.

    Returns:
        Dict mapping feature names to float values.  Missing features
        default to 0.0 rather than NaN so downstream models never
        see missing data.
    """
    features: Dict[str, float] = {}

    # ── Current state ────────────────────────────────────────────────
    features["market_probability"] = event.market_probability
    features["volume_24h"] = event.volume_24h
    features["liquidity"] = event.liquidity
    features["num_traders"] = float(event.num_traders)

    # ── Time-to-resolution (the single most important feature) ───────
    time_features = _compute_time_features(event.end_date)
    features.update(time_features)

    # ── Price momentum (requires history) ────────────────────────────
    if price_history is not None and len(price_history) >= 2:
        momentum = _compute_momentum_features(price_history)
        features.update(momentum)
    else:
        features["price_momentum_1d"] = 0.0
        features["price_momentum_7d"] = 0.0
        features["price_volatility_7d"] = 0.0
        features["price_trend_slope"] = 0.0

    # ── Volume dynamics ──────────────────────────────────────────────
    features["volume_spike"] = _compute_volume_spike(event)

    # ── Orderbook features ───────────────────────────────────────────
    if orderbook:
        ob_features = _compute_orderbook_features(orderbook)
        features.update(ob_features)
    else:
        features["bid_ask_spread"] = 0.0
        features["bid_depth"] = 0.0
        features["ask_depth"] = 0.0
        features["orderbook_imbalance"] = 0.0

    return features


def build_batch_features(
    events: List[PolymarketEvent],
    histories: Optional[Dict[str, pd.DataFrame]] = None,
    orderbooks: Optional[Dict[str, Dict[str, List[Dict[str, float]]]]] = None,
) -> List[Dict[str, float]]:
    """Build features for a batch of events.

    Args:
        events: List of market events.
        histories: Optional mapping of condition_id -> price DataFrame.
        orderbooks: Optional mapping of token_id -> orderbook dict.

    Returns:
        List of feature dicts, one per event, same order as input.
    """
    histories = histories or {}
    orderbooks = orderbooks or {}

    results: List[Dict[str, float]] = []
    for event in events:
        history = histories.get(event.condition_id)

        # Look up orderbook by YES token ID
        ob = None
        yes_token_id = event.tokens.get("Yes", "")
        if yes_token_id and yes_token_id in orderbooks:
            ob = orderbooks[yes_token_id]

        features = build_event_features(event, history, ob)
        results.append(features)

    return results


# ── Internal feature computation ──────────────────────────────────────


def _compute_time_features(end_date: datetime) -> Dict[str, float]:
    """Time-to-resolution features.

    Markets approaching resolution behave differently: prices converge
    toward 0 or 1, and the remaining edge opportunity shrinks.
    """
    now = datetime.now(timezone.utc)
    delta = end_date - now
    days_remaining = max(delta.total_seconds() / 86400.0, 0.0)

    features: Dict[str, float] = {
        "time_to_resolution": days_remaining,
    }

    # Time decay rate: how quickly the market should converge
    # Faster decay = less opportunity for edge, but more price movement
    if days_remaining > 0:
        features["time_decay_rate"] = 1.0 / days_remaining
    else:
        features["time_decay_rate"] = 100.0  # already resolved

    # Bucketed time urgency (useful for tree-based models)
    if days_remaining < 1:
        features["time_bucket"] = 5.0      # imminent
    elif days_remaining < 7:
        features["time_bucket"] = 4.0      # this week
    elif days_remaining < 30:
        features["time_bucket"] = 3.0      # this month
    elif days_remaining < 90:
        features["time_bucket"] = 2.0      # this quarter
    else:
        features["time_bucket"] = 1.0      # distant

    return features


def _compute_momentum_features(price_history: pd.DataFrame) -> Dict[str, float]:
    """Price momentum and volatility from YES-token price timeseries.

    In prediction markets, "momentum" = the market is becoming
    more or less convinced.  A momentum of +0.10 means the YES
    probability rose by 10 percentage points.
    """
    prices = price_history["price"].values
    n = len(prices)

    features: Dict[str, float] = {}

    # 1-day momentum (last ~24 data points for hourly data, or last point)
    lookback_1d = min(24, n - 1)
    if lookback_1d > 0:
        features["price_momentum_1d"] = float(prices[-1] - prices[-1 - lookback_1d])
    else:
        features["price_momentum_1d"] = 0.0

    # 7-day momentum
    lookback_7d = min(168, n - 1)  # 7 * 24
    if lookback_7d > 0:
        features["price_momentum_7d"] = float(prices[-1] - prices[-1 - lookback_7d])
    else:
        features["price_momentum_7d"] = 0.0

    # 7-day realised volatility
    if n >= 2:
        changes = np.diff(prices[-min(168, n):])
        features["price_volatility_7d"] = float(np.std(changes)) if len(changes) > 1 else 0.0
    else:
        features["price_volatility_7d"] = 0.0

    # Linear trend slope (OLS on last 7 days of data)
    trend_window = min(168, n)
    if trend_window >= 3:
        y = prices[-trend_window:]
        x = np.arange(len(y), dtype=float)
        # Simple OLS slope: cov(x,y) / var(x)
        x_mean = x.mean()
        y_mean = y.mean()
        slope = float(np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2))
        features["price_trend_slope"] = slope
    else:
        features["price_trend_slope"] = 0.0

    return features


def _compute_volume_spike(event: PolymarketEvent) -> float:
    """Detect abnormal volume relative to liquidity.

    A volume spike often precedes large probability moves as informed
    traders enter the market.
    """
    if event.liquidity <= 0:
        return 0.0

    # Volume-to-liquidity ratio: >2x is unusual, >5x is extreme
    ratio = event.volume_24h / event.liquidity
    return float(min(ratio, 10.0))  # cap at 10x to avoid outlier effects


def _compute_orderbook_features(
    orderbook: Dict[str, List[Dict[str, float]]],
) -> Dict[str, float]:
    """Features derived from the live orderbook."""
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    features: Dict[str, float] = {}

    # Best bid-ask spread
    best_bid = max((b["price"] for b in bids), default=0.0)
    best_ask = min((a["price"] for a in asks), default=1.0)
    features["bid_ask_spread"] = max(best_ask - best_bid, 0.0)

    # Depth (total size on each side)
    bid_depth = sum(b.get("size", 0.0) for b in bids)
    ask_depth = sum(a.get("size", 0.0) for a in asks)
    features["bid_depth"] = bid_depth
    features["ask_depth"] = ask_depth

    # Orderbook imbalance: (bid_depth - ask_depth) / total
    total_depth = bid_depth + ask_depth
    if total_depth > 0:
        features["orderbook_imbalance"] = (bid_depth - ask_depth) / total_depth
    else:
        features["orderbook_imbalance"] = 0.0

    return features
