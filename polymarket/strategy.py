"""Edge-based strategy for prediction markets.

Unlike stock strategies (which convert P(up) into buy/sell signals),
Polymarket strategy converts probability *edges* into BUY_YES or
BUY_NO signals with Kelly-optimal sizing.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from polymarket.types import PolymarketEdge

logger = logging.getLogger(__name__)


def generate_polymarket_signals(
    edges: List[PolymarketEdge],
    config: Dict[str, float | int | str] | None = None,
) -> pd.DataFrame:
    """Convert detected edges into actionable trading signals.

    Applies filters from config and sizes positions using Kelly criterion,
    capped by risk limits.

    Args:
        edges: List of detected probability edges from EdgeDetector.
        config: Strategy config from config.json["polymarket"]["strategy"].
            Keys: min_edge_pct, max_position_usd, min_volume_24h,
            max_resolution_days, min_liquidity, kelly_cap.

    Returns:
        DataFrame with columns:
            condition_id, question, signal, edge_pct, ai_prob,
            market_prob, position_size, confidence
    """
    cfg = config or {}
    min_edge_pct = float(cfg.get("min_edge_pct", 5.0))
    max_position_usd = float(cfg.get("max_position_usd", 50.0))
    kelly_cap = float(cfg.get("kelly_fraction_cap", 0.15))
    max_open_positions = int(cfg.get("max_open_positions", 15))

    records: List[Dict[str, str | float]] = []

    for edge in edges:
        # ── Filter: minimum edge threshold ───────────────────────
        edge_pct = abs(edge.edge) * 100.0
        if edge_pct < min_edge_pct:
            continue

        # ── Signal direction ─────────────────────────────────────
        signal = f"BUY_{edge.recommended_side}"

        # ── Position sizing ──────────────────────────────────────
        # Kelly fraction capped by risk config
        capped_kelly = min(edge.kelly_size, kelly_cap)
        position_size = min(capped_kelly * max_position_usd, max_position_usd)

        # Don't signal tiny positions
        if position_size < 1.0:
            continue

        records.append({
            "condition_id": edge.condition_id,
            "question": edge.question,
            "signal": signal,
            "edge_pct": round(edge_pct, 2),
            "ai_prob": round(edge.ai_probability * 100, 2),
            "market_prob": round(edge.market_probability * 100, 2),
            "position_size": round(position_size, 2),
            "confidence": round(edge.confidence, 4),
        })

        # Cap total open positions
        if len(records) >= max_open_positions:
            break

    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=[
            "condition_id", "question", "signal", "edge_pct",
            "ai_prob", "market_prob", "position_size", "confidence",
        ])

    # Sort by edge descending — highest-conviction signals first
    if not df.empty:
        df = df.sort_values("edge_pct", ascending=False).reset_index(drop=True)

    logger.info(
        "Generated %d Polymarket signals from %d edges (min_edge=%.1f%%)",
        len(df), len(edges), min_edge_pct,
    )
    return df


def filter_events_by_config(
    events: List[Dict[str, float | str]],
    config: Dict[str, float | int | str] | None = None,
) -> List[Dict[str, float | str]]:
    """Pre-filter events before edge detection based on strategy config.

    Useful for removing markets that don't meet minimum requirements
    before running the more expensive edge detection pipeline.

    Args:
        events: List of event dicts with volume_24h, liquidity, and
            time_to_resolution fields.
        config: Strategy config section.

    Returns:
        Filtered list of event dicts.
    """
    cfg = config or {}
    min_volume_24h = float(cfg.get("min_volume_24h", 1000))
    min_liquidity = float(cfg.get("min_liquidity", 500))
    max_resolution_days = float(cfg.get("max_resolution_days", 90))

    filtered: List[Dict[str, float | str]] = []
    for event in events:
        volume = float(event.get("volume_24h", 0))
        liquidity = float(event.get("liquidity", 0))
        time_to_res = float(event.get("time_to_resolution", 999))

        if volume < min_volume_24h:
            continue
        if liquidity < min_liquidity:
            continue
        if time_to_res > max_resolution_days:
            continue
        if time_to_res < 0.5:
            # Skip markets about to resolve (too little time for edge)
            continue

        filtered.append(event)

    logger.debug(
        "Pre-filtered events: %d -> %d (min_vol=%.0f, min_liq=%.0f, max_days=%.0f)",
        len(events), len(filtered), min_volume_24h, min_liquidity, max_resolution_days,
    )
    return filtered
