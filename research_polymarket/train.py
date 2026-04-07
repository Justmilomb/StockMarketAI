"""Agent-modifiable research file for Polymarket crypto price predictions.

This is the ONLY file you should modify (along with profile_configs.py).
It defines the edge detection configuration that evaluate.py reads.

The bot predicts Polymarket crypto markets (Bitcoin up/down, ETH above X,
etc.) using real BTC/ETH price data (RSI, MACD, Bollinger) combined with
Polymarket market features (momentum, volume, orderbook).

The score is a composite of: Brier score (calibration), bankroll return,
edge accuracy, win rate, and bet volume. Higher is better.
"""

# ── Multi-profile mode flags ───────────────────────────────────────
PROFILE_MODE = True
ACTIVE_PROFILE = "balanced_edge"
EVALUATE_COMBINED = True

# ── Legacy single-config mode ─────────────────────────────────────

CONFIG = {
    # Starting bankroll for simulation
    "bankroll": 1000,

    # Edge detection parameters
    "min_edge_pct": 3.0,           # minimum edge to trigger a bet (percentage points)
    "kelly_fraction_cap": 0.10,    # cap on Kelly bet sizing
    "max_bet_fraction": 0.05,      # max fraction of bankroll per bet

    # Market filters
    "min_volume": 1000,
    "min_liquidity": 500,

    # Edge detection method: "heuristic" (fast, no API calls)
    "calibration_method": "heuristic",
    "confidence_threshold": 0.3,

    # Evaluate edge N days before market resolution
    "eval_point_days_before": 2,

    # How much weight to give crypto price indicators vs Polymarket features
    # 0.0 = pure Polymarket heuristic, 1.0 = pure crypto indicators
    "crypto_indicator_weight": 0.9,

    # Individual indicator weights (must sum to ~1.0)
    "rsi_weight": 0.20,
    "macd_weight": 0.30,
    "trend_weight": 0.25,
    "bb_weight": 0.10,
    "momentum_weight": 0.15,
}
