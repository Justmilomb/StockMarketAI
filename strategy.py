from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd


@dataclass
class StrategyConfig:
    threshold_buy: float = 0.6
    threshold_sell: float = 0.4
    max_positions: int = 5
    position_size_fraction: float = 0.2


def generate_signals(
    prob_up: np.ndarray,
    meta_latest: pd.DataFrame,
    config: StrategyConfig | None = None,
    held_tickers: Optional[List[str]] = None,
    protected_tickers: set[str] | None = None,
    per_ticker_configs: Dict[str, StrategyConfig] | None = None,
) -> pd.DataFrame:
    """Generate buy/sell/hold signals from predicted probabilities.

    Args:
        prob_up: Array of P(up) values aligned with *meta_latest* rows.
        meta_latest: DataFrame with columns ``[ticker, date]``.
        config: Global strategy thresholds (used as fallback when
            *per_ticker_configs* does not cover a ticker).
        held_tickers: Tickers currently in the portfolio (enables sell
            signals).
        protected_tickers: Tickers that must never be traded — any
            generated signal is overridden to ``hold``.
        per_ticker_configs: Optional mapping of ticker -> individual
            ``StrategyConfig``.  When provided, each ticker's buy/sell
            thresholds are looked up here first, falling back to
            *config* for any ticker not listed.  The global
            ``config.max_positions`` acts as a hard cap across all
            groups.

    Returns:
        DataFrame with columns ``[ticker, date, prob_up, signal]``.
    """
    if config is None:
        config = StrategyConfig()
    if held_tickers is None:
        held_tickers = []

    held_set = set(held_tickers)

    df = meta_latest.copy()
    df["prob_up"] = prob_up

    # Rank by probability descending
    df = df.sort_values("prob_up", ascending=False)

    # Default to hold
    df["signal"] = "hold"

    if per_ticker_configs:
        # ── Per-ticker sell logic ─────────────────────────────────
        for idx, row in df.iterrows():
            ticker = row["ticker"]
            tc = per_ticker_configs.get(ticker, config)
            if row["prob_up"] <= tc.threshold_sell and ticker in held_set:
                df.loc[idx, "signal"] = "sell"

        # ── Per-ticker buy logic ──────────────────────────────────
        # Group candidates by their config so each group's threshold
        # applies correctly, but a global hard cap still limits total
        # buy signals.
        total_buys = 0
        global_max = config.max_positions
        already_bought: Set[str] = set()

        # Iterate the probability-sorted df so highest-prob tickers
        # are considered first regardless of which config group they
        # belong to.
        for idx, row in df.iterrows():
            if total_buys >= global_max:
                break
            ticker = row["ticker"]
            if ticker in held_set or ticker in already_bought:
                continue
            tc = per_ticker_configs.get(ticker, config)
            if row["prob_up"] >= tc.threshold_buy:
                df.loc[idx, "signal"] = "buy"
                already_bought.add(ticker)
                total_buys += 1
    else:
        # ── Original single-config path (unchanged) ──────────────
        sell_mask = (df["prob_up"] <= config.threshold_sell) & (
            df["ticker"].isin(held_set)
        )
        df.loc[sell_mask, "signal"] = "sell"

        buy_mask = (df["prob_up"] >= config.threshold_buy) & (
            ~df["ticker"].isin(held_set)
        )
        buy_candidates = df[buy_mask].head(config.max_positions).index
        df.loc[buy_candidates, "signal"] = "buy"

    # Protected tickers: override any signal to hold — never trade these
    # Case-insensitive match — config may store VUKGl_EQ while pipeline has VUKGL_EQ
    if protected_tickers:
        protected_upper = {t.upper() for t in protected_tickers}
        protected_mask = df["ticker"].str.upper().isin(protected_upper)
        df.loc[protected_mask, "signal"] = "hold"

    return df.reset_index(drop=True)
