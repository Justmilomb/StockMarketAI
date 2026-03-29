"""Crypto strategy — signal generation with crypto-appropriate defaults.

Reuses the core ``strategy.generate_signals()`` logic but with:
- Higher buy threshold (0.62 vs 0.60 for stocks) — more conviction needed
- Lower sell threshold (0.38 vs 0.40) — quicker exits in volatile markets
- No market hours gating (crypto trades 24/7)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from strategy import StrategyConfig, generate_signals


# Crypto-tuned defaults: wider spread between buy/sell thresholds
# to filter noise in the higher-volatility crypto environment
CRYPTO_STRATEGY_DEFAULTS = StrategyConfig(
    threshold_buy=0.62,
    threshold_sell=0.38,
    max_positions=5,
    position_size_fraction=0.08,
)


def generate_crypto_signals(
    prob_up: np.ndarray,
    meta_latest: pd.DataFrame,
    config: StrategyConfig | None = None,
    held_tickers: Optional[List[str]] = None,
    protected_tickers: set[str] | None = None,
    per_ticker_configs: Dict[str, StrategyConfig] | None = None,
) -> pd.DataFrame:
    """Generate buy/sell/hold signals for crypto pairs.

    Delegates to ``strategy.generate_signals()`` with crypto defaults.
    No market-hours gating is applied since crypto trades 24/7.

    Args:
        prob_up: Array of P(up) values aligned with *meta_latest* rows.
        meta_latest: DataFrame with columns ``[ticker, date]``.
        config: Strategy config overrides. Falls back to ``CRYPTO_STRATEGY_DEFAULTS``.
        held_tickers: Pairs currently in the portfolio.
        protected_tickers: Pairs that must never be traded.
        per_ticker_configs: Optional per-pair config overrides.

    Returns:
        DataFrame with columns ``[ticker, date, prob_up, signal]``.
    """
    effective_config = config or CRYPTO_STRATEGY_DEFAULTS

    return generate_signals(
        prob_up=prob_up,
        meta_latest=meta_latest,
        config=effective_config,
        held_tickers=held_tickers,
        protected_tickers=protected_tickers,
        per_ticker_configs=per_ticker_configs,
    )


def build_crypto_strategy_config(
    raw_config: Dict[str, object] | None = None,
) -> StrategyConfig:
    """Build a StrategyConfig from the crypto section of config.json.

    Reads from ``config["crypto"]["strategy"]``.
    """
    if raw_config is None:
        return StrategyConfig(**{
            "threshold_buy": CRYPTO_STRATEGY_DEFAULTS.threshold_buy,
            "threshold_sell": CRYPTO_STRATEGY_DEFAULTS.threshold_sell,
            "max_positions": CRYPTO_STRATEGY_DEFAULTS.max_positions,
            "position_size_fraction": CRYPTO_STRATEGY_DEFAULTS.position_size_fraction,
        })

    return StrategyConfig(
        threshold_buy=float(raw_config.get("threshold_buy", 0.62)),
        threshold_sell=float(raw_config.get("threshold_sell", 0.38)),
        max_positions=int(raw_config.get("max_positions", 5)),
        position_size_fraction=float(raw_config.get("position_size_fraction", 0.08)),
    )
