"""Edge evaluation engine for Polymarket crypto price predictions.

Simulates betting on resolved Polymarket crypto markets (Bitcoin up/down,
ETH price on date X, etc.) using edge detection enhanced with actual
BTC/ETH OHLCV price data and technical indicators.

The key advantage: the heuristic edge detector uses Polymarket market
features (momentum, volume, time decay). We add real crypto price signals
(RSI, MACD, Bollinger bands, trend) to form a better probability estimate.
"""

from __future__ import annotations

import logging
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

from polymarket.features import build_event_features
from polymarket.model import EdgeDetector
from polymarket.types import PolymarketEvent
from research_polymarket.data import ResolvedMarket

logger = logging.getLogger(__name__)


@dataclass
class BetRecord:
    """A single simulated bet on a resolved market."""

    condition_id: str
    question: str
    category: str
    side: Literal["YES", "NO"]
    ai_probability: float
    market_probability: float
    edge: float
    bet_size: float
    won: bool
    pnl: float
    bankroll_after: float
    actual_outcome: Literal["Yes", "No"]


@dataclass
class PolymarketMetrics:
    """Aggregate metrics from a Polymarket edge evaluation."""

    # Calibration
    brier_score: float = 1.0
    log_loss: float = 10.0

    # Profitability
    total_return_pct: float = 0.0
    final_bankroll: float = 0.0

    # Edge quality
    edge_accuracy: float = 0.0
    win_rate: float = 0.0
    n_bets: int = 0
    n_markets_evaluated: int = 0

    # Risk
    max_drawdown_pct: float = 0.0
    avg_bet_size: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0

    # Per-category breakdown
    category_win_rates: Dict[str, float] = field(default_factory=dict)

    # Raw bet records
    bets: List[BetRecord] = field(default_factory=list)


# ── Crypto price data loading ──────────────────────────────────────────

def _load_crypto_price_data() -> Dict[str, pd.DataFrame]:
    """Fetch BTC and ETH daily OHLCV from yfinance (cached).

    Returns dict mapping ticker -> DataFrame with standard OHLCV columns.
    """
    import yfinance as yf

    cache_dir = Path("data/polymarket")
    cache_dir.mkdir(parents=True, exist_ok=True)

    tickers = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
    result: Dict[str, pd.DataFrame] = {}

    for name, yf_ticker in tickers.items():
        cache_file = cache_dir / f"{name}_ohlcv.csv"

        # Use cache if fresh (less than 1 day old)
        if cache_file.exists():
            try:
                mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
                if (datetime.now(timezone.utc) - mtime).days < 1:
                    df = pd.read_csv(cache_file, parse_dates=["Date"], index_col="Date")
                    if len(df) > 100:
                        result[name] = df
                        continue
            except Exception:
                pass

        try:
            df = yf.download(
                yf_ticker, period="2y", auto_adjust=False,
                progress=False, multi_level_index=False, timeout=15,
            )
            if df.empty:
                continue
            df.to_csv(cache_file)
            result[name] = df
            logger.info("Fetched %d days of %s price data", len(df), name)
        except Exception as exc:
            logger.warning("Failed to fetch %s price data: %s", name, exc)

    return result


def _compute_crypto_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicators from crypto OHLCV data.

    Returns DataFrame indexed by date with indicator columns.
    """
    data = df.copy()

    close = data["Close"]
    high = data["High"]
    low = data["Low"]

    # Momentum
    data["rsi_14"] = _compute_rsi(close, 14)
    data["ret_1d"] = close.pct_change(1)
    data["ret_5d"] = close.pct_change(5)
    data["ret_10d"] = close.pct_change(10)

    # Trend
    data["sma_20"] = close.rolling(20).mean()
    data["sma_50"] = close.rolling(50).mean()
    data["above_sma20"] = (close > data["sma_20"]).astype(float)
    data["above_sma50"] = (close > data["sma_50"]).astype(float)

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    data["macd"] = ema12 - ema26
    data["macd_signal"] = data["macd"].ewm(span=9).mean()
    data["macd_hist"] = data["macd"] - data["macd_signal"]

    # Bollinger Bands
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    data["bb_upper"] = sma + 2 * std
    data["bb_lower"] = sma - 2 * std
    data["bb_pct"] = (close - data["bb_lower"]) / (data["bb_upper"] - data["bb_lower"])

    # Volatility
    data["atr_14"] = _compute_atr(high, low, close, 14)
    data["volatility_10d"] = close.pct_change().rolling(10).std()

    return data.dropna()


def _compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()


# ── Market question parsing ────────────────────────────────────────────

def _detect_crypto_asset(question: str) -> Optional[str]:
    """Detect which crypto asset a Polymarket question is about.

    Returns 'BTC', 'ETH', 'SOL', or None.
    """
    q = question.lower()
    if any(w in q for w in ["bitcoin", "btc"]):
        return "BTC"
    if any(w in q for w in ["ethereum", "eth"]):
        return "ETH"
    if any(w in q for w in ["solana", "sol"]):
        return "SOL"
    return None


def _parse_price_target(question: str) -> Optional[float]:
    """Try to extract a price target from the question.

    'Bitcoin above 68,000 on April 7?' -> 68000.0
    'Ethereum price on April 7?' -> None (no specific target)
    """
    # Match patterns like "above 68,000" or "above 2,200"
    m = re.search(r"above\s+[\$]?([\d,]+)", question, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # Match "hit 65,000" or "hit 75,000"
    m = re.search(r"hit\s+[\$]?([\d,]+)", question, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))

    # Match price ranges like "68,000-70,000"
    m = re.search(r"([\d,]+)\s*[-–]\s*([\d,]+)", question)
    if m:
        low = float(m.group(1).replace(",", ""))
        high = float(m.group(2).replace(",", ""))
        return (low + high) / 2.0

    return None


def _is_direction_market(question: str) -> bool:
    """Check if this is a simple up/down direction market."""
    q = question.lower()
    return "up or down" in q or "up/down" in q


# ── Price-enhanced probability estimation ──────────────────────────────

def _estimate_crypto_probability(
    market: ResolvedMarket,
    eval_date: datetime,
    crypto_data: Dict[str, pd.DataFrame],
    config: Dict[str, Any],
) -> Optional[float]:
    """Use actual crypto price data to estimate probability for a market.

    For 'Bitcoin above X?' questions: uses current price, RSI, MACD,
    Bollinger bands to estimate P(price > target).

    For 'Bitcoin Up or Down?' questions: uses momentum indicators
    to estimate P(up).
    """
    asset = _detect_crypto_asset(market.question)
    if not asset or asset not in crypto_data:
        return None

    df = crypto_data[asset]
    indicators = _compute_crypto_indicators(df)

    # Find the closest date to our evaluation point
    if eval_date.tzinfo is None:
        eval_date = eval_date.replace(tzinfo=timezone.utc)

    eval_date_naive = eval_date.date() if hasattr(eval_date, 'date') else eval_date

    if hasattr(indicators.index, 'date'):
        date_index = indicators.index.date
    else:
        date_index = indicators.index

    mask = date_index <= eval_date_naive
    if not mask.any():
        return None

    row = indicators.loc[mask].iloc[-1]
    current_price = float(row["Close"])

    # Base signal weights from config
    rsi_weight = float(config.get("rsi_weight", 0.25))
    macd_weight = float(config.get("macd_weight", 0.20))
    trend_weight = float(config.get("trend_weight", 0.25))
    bb_weight = float(config.get("bb_weight", 0.15))
    momentum_weight = float(config.get("momentum_weight", 0.15))

    price_target = _parse_price_target(market.question)
    is_direction = _is_direction_market(market.question)

    if price_target is not None:
        # "Bitcoin above X?" market — estimate P(price >= target)
        distance_pct = (price_target - current_price) / current_price

        # How many days until resolution?
        days_to_resolve = (market.end_date - eval_date).days
        days_to_resolve = max(days_to_resolve, 1)

        # Base probability from distance (closer = more likely to stay)
        if distance_pct <= 0:
            # Already above target
            base_prob = 0.7 + 0.2 * min(abs(distance_pct) / 0.10, 1.0)
        else:
            # Need to rise to target
            daily_vol = float(row.get("volatility_10d", 0.03))
            expected_move = daily_vol * math.sqrt(days_to_resolve)
            z_score = distance_pct / max(expected_move, 0.001)
            base_prob = max(0.05, 0.5 - z_score * 0.2)

        # Adjust with indicators
        rsi = float(row.get("rsi_14", 50)) / 100.0
        rsi_signal = 0.5 - (rsi - 0.5)  # RSI < 50 = bullish (oversold)

        macd_hist = float(row.get("macd_hist", 0))
        macd_signal = 0.5 + min(max(macd_hist / max(current_price * 0.01, 1), -0.3), 0.3)

        above_sma = float(row.get("above_sma20", 0.5))
        trend_signal = 0.3 + above_sma * 0.4

        bb_pct = float(row.get("bb_pct", 0.5))
        bb_signal = bb_pct  # Higher = price near upper band = bullish

        ret_5d = float(row.get("ret_5d", 0))
        momentum_signal = 0.5 + min(max(ret_5d * 5, -0.3), 0.3)

        indicator_adj = (
            rsi_signal * rsi_weight
            + macd_signal * macd_weight
            + trend_signal * trend_weight
            + bb_signal * bb_weight
            + momentum_signal * momentum_weight
        )
        # indicator_adj is ~0.0-1.0, center around 0
        indicator_adj = (indicator_adj - 0.5) * 0.3

        prob = base_prob + indicator_adj

    elif is_direction:
        # "Up or Down?" market — pure direction call
        rsi = float(row.get("rsi_14", 50)) / 100.0
        rsi_signal = 0.5 - (rsi - 0.5)

        macd_hist = float(row.get("macd_hist", 0))
        macd_signal = 0.5 + min(max(macd_hist / max(current_price * 0.01, 1), -0.3), 0.3)

        above_sma = float(row.get("above_sma20", 0.5))
        trend_signal = 0.3 + above_sma * 0.4

        ret_1d = float(row.get("ret_1d", 0))
        ret_5d = float(row.get("ret_5d", 0))
        momentum_signal = 0.5 + min(max(ret_1d * 8 + ret_5d * 3, -0.4), 0.4)

        bb_pct = float(row.get("bb_pct", 0.5))
        bb_signal = bb_pct

        prob = (
            rsi_signal * rsi_weight
            + macd_signal * macd_weight
            + trend_signal * trend_weight
            + bb_signal * bb_weight
            + momentum_signal * momentum_weight
        )
    else:
        return None

    return max(0.02, min(0.98, prob))


# ── Main evaluation ────────────────────────────────────────────────────

def evaluate_edge_strategy(
    resolved_markets: List[ResolvedMarket],
    config: Dict[str, Any],
) -> PolymarketMetrics:
    """Simulate betting on historical resolved crypto price markets.

    Enhanced flow:
    1. Load BTC/ETH/SOL price data from yfinance
    2. For each resolved market: use both Polymarket features AND
       real crypto indicators to estimate probability
    3. If edge detected, place a Kelly-sized bet
    4. Track bankroll and calibration metrics
    """
    initial_bankroll = float(config.get("bankroll", 1000))
    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_dd = 0.0

    min_edge_pct = float(config.get("min_edge_pct", 5.0))
    kelly_cap = float(config.get("kelly_fraction_cap", 0.10))
    max_bet_frac = float(config.get("max_bet_fraction", 0.05))
    confidence_threshold = float(config.get("confidence_threshold", 0.3))
    eval_days_before = int(config.get("eval_point_days_before", 7))
    crypto_weight = float(config.get("crypto_indicator_weight", 0.6))
    market_weight = 1.0 - crypto_weight

    # Load real crypto price data
    logger.info("Loading crypto price data for enhanced edge detection...")
    crypto_data = _load_crypto_price_data()
    logger.info("Loaded price data for: %s", list(crypto_data.keys()))

    edge_detector = EdgeDetector({
        "min_edge_pct": min_edge_pct,
        "calibration_method": config.get("calibration_method", "heuristic"),
    })

    bets: List[BetRecord] = []
    ai_probs: List[float] = []
    actual_outcomes: List[float] = []
    n_evaluated = 0

    for market in resolved_markets:
        if bankroll <= 0:
            break

        # Only evaluate crypto price markets
        asset = _detect_crypto_asset(market.question)
        if asset is None:
            continue

        # Get market probability at evaluation point
        eval_prob = _get_pre_resolution_probability(market, eval_days_before)
        if eval_prob is None:
            continue

        n_evaluated += 1

        # Evaluation timestamp
        eval_time = market.end_date - timedelta(days=eval_days_before)

        # Get crypto-price-based probability estimate
        crypto_prob = _estimate_crypto_probability(
            market, eval_time, crypto_data, config,
        )

        # Get Polymarket feature-based estimate
        event = PolymarketEvent(
            condition_id=market.condition_id,
            question=market.question,
            description="",
            category=market.category,
            end_date=market.end_date,
            outcome_prices={"Yes": eval_prob, "No": 1.0 - eval_prob},
            volume_24h=market.volume_24h,
            liquidity=market.liquidity,
            tokens=market.tokens,
        )
        features = build_event_features(event, market.history)

        # Combine: crypto indicators + Polymarket heuristic
        if crypto_prob is not None:
            heuristic_prob = edge_detector._estimate_probability(event, features)
            ai_prob = crypto_prob * crypto_weight + heuristic_prob * market_weight
        else:
            ai_prob = edge_detector._estimate_probability(event, features)

        ai_prob = max(0.02, min(0.98, ai_prob))

        actual = 1.0 if market.outcome == "Yes" else 0.0
        ai_probs.append(ai_prob)
        actual_outcomes.append(actual)

        # Check for edge
        edge_val = ai_prob - eval_prob
        threshold = min_edge_pct / 100.0

        if abs(edge_val) < threshold:
            continue

        # Compute confidence (no free boost — model must earn it)
        confidence = edge_detector._estimate_confidence(features, edge_val)

        if confidence < confidence_threshold:
            continue

        recommended_side: Literal["YES", "NO"] = "YES" if edge_val > 0 else "NO"
        kelly_raw = edge_detector._compute_kelly(ai_prob, eval_prob, recommended_side)
        kelly = min(abs(kelly_raw), kelly_cap)
        bet_size = min(kelly * bankroll, bankroll * max_bet_frac)
        bet_size = max(bet_size, 0.01)

        if bet_size > bankroll:
            continue

        # Did we win?
        won = (
            (recommended_side == "YES" and market.outcome == "Yes")
            or (recommended_side == "NO" and market.outcome == "No")
        )

        # Binary bet payout (with 2% spread — realistic Polymarket cost)
        spread = 0.02
        if won:
            buy_price = eval_prob if recommended_side == "YES" else (1.0 - eval_prob)
            buy_price = min(buy_price + spread, 0.99)  # worse fill due to spread
            if buy_price > 0:
                pnl = bet_size * (1.0 / buy_price - 1.0)
            else:
                pnl = bet_size
        else:
            pnl = -bet_size

        bankroll += pnl

        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
        dd = (peak_bankroll - bankroll) / peak_bankroll if peak_bankroll > 0 else 0.0
        max_dd = max(max_dd, dd)

        bets.append(BetRecord(
            condition_id=market.condition_id,
            question=market.question[:80],
            category=market.category,
            side=recommended_side,
            ai_probability=ai_prob,
            market_probability=eval_prob,
            edge=edge_val,
            bet_size=bet_size,
            won=won,
            pnl=pnl,
            bankroll_after=bankroll,
            actual_outcome=market.outcome,
        ))

    # Aggregate metrics
    n_bets = len(bets)
    wins = sum(1 for b in bets if b.won)

    if ai_probs:
        brier = float(np.mean([(p - a) ** 2 for p, a in zip(ai_probs, actual_outcomes)]))
    else:
        brier = 1.0

    if ai_probs:
        eps = 1e-10
        ll = -float(np.mean([
            a * math.log(max(p, eps)) + (1 - a) * math.log(max(1 - p, eps))
            for p, a in zip(ai_probs, actual_outcomes)
        ]))
    else:
        ll = 10.0

    edge_correct = sum(1 for b in bets if (
        (b.side == "YES" and b.actual_outcome == "Yes")
        or (b.side == "NO" and b.actual_outcome == "No")
    ))
    edge_accuracy = edge_correct / n_bets if n_bets > 0 else 0.0

    cat_bets: Dict[str, List[bool]] = {}
    for b in bets:
        cat_bets.setdefault(b.category, []).append(b.won)
    cat_win_rates = {
        cat: sum(ws) / len(ws)
        for cat, ws in cat_bets.items()
        if ws
    }

    # Profit factor: gross wins / gross losses
    gross_wins = sum(b.pnl for b in bets if b.pnl > 0)
    gross_losses = abs(sum(b.pnl for b in bets if b.pnl < 0))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0.0

    # Sharpe ratio: mean(pnl) / std(pnl) * sqrt(n_bets)
    if n_bets >= 2:
        pnls = [b.pnl for b in bets]
        mean_pnl = float(np.mean(pnls))
        std_pnl = float(np.std(pnls, ddof=1))
        sharpe = (mean_pnl / std_pnl) * math.sqrt(n_bets) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    return PolymarketMetrics(
        brier_score=brier,
        log_loss=ll,
        total_return_pct=((bankroll / initial_bankroll) - 1.0) * 100.0 if initial_bankroll > 0 else 0.0,
        final_bankroll=bankroll,
        edge_accuracy=edge_accuracy,
        win_rate=wins / n_bets if n_bets > 0 else 0.0,
        n_bets=n_bets,
        n_markets_evaluated=n_evaluated,
        max_drawdown_pct=max_dd * 100.0,
        avg_bet_size=float(np.mean([b.bet_size for b in bets])) if bets else 0.0,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        category_win_rates=cat_win_rates,
        bets=bets,
    )


def _get_pre_resolution_probability(
    market: ResolvedMarket,
    days_before: int,
) -> Optional[float]:
    """Get the YES price at a point before resolution."""
    if market.history.empty or "timestamp" not in market.history.columns:
        return 0.5

    history = market.history.copy()
    if not pd.api.types.is_datetime64_any_dtype(history["timestamp"]):
        history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True)

    target_time = market.end_date - timedelta(days=days_before)
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)

    before_mask = history["timestamp"] <= target_time
    if before_mask.any():
        closest = history.loc[before_mask].iloc[-1]
        return float(closest["price"])

    if len(history) > 0:
        return float(history.iloc[0]["price"])

    return 0.5
