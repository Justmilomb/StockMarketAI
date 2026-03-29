"""Polymarket prediction-market asset class.

Registers "polymarket" with the AssetRegistry so the pipeline can
route event-based data through specialised feature engineering,
edge detection, and strategy modules.
"""
from __future__ import annotations

from asset_registry import AssetClassConfig, AssetRegistry

registry = AssetRegistry()
registry.register(
    AssetClassConfig(
        name="polymarket",
        display_name="Polymarket",
        config_section="polymarket",
        uses_ohlcv=False,
    )
)
