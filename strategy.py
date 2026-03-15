from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

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
) -> pd.DataFrame:
    """
    Given:
      - prob_up: array of probabilities that tomorrow's close > today's
      - meta_latest: DataFrame with columns [ticker, date] aligned with prob_up
      - held_tickers: list of tickers currently held (enables sell signals)

    Return a DataFrame with columns:
      - ticker, date, prob_up, signal: {"buy", "sell", "hold"}
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

    # SELL: prob below sell threshold AND currently holding
    sell_mask = (df["prob_up"] <= config.threshold_sell) & (df["ticker"].isin(held_set))
    df.loc[sell_mask, "signal"] = "sell"

    # BUY: prob above buy threshold, NOT already holding, up to max_positions
    buy_mask = (df["prob_up"] >= config.threshold_buy) & (~df["ticker"].isin(held_set))
    buy_candidates = df[buy_mask].head(config.max_positions).index
    df.loc[buy_candidates, "signal"] = "buy"

    return df.reset_index(drop=True)
