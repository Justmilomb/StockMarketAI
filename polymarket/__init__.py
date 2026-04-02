"""Polymarket prediction-market asset class.

Registers "polymarket" with the AssetRegistry so the pipeline can
route event-based data through specialised feature engineering,
edge detection, and strategy modules.
"""
from __future__ import annotations

from asset_registry import AssetClassConfig, AssetRegistry


def _make_data_loader_factory() -> object:
    """Factory: return the polymarket data_loader module."""
    from polymarket import data_loader
    return data_loader


def _make_feature_builder_factory() -> object:
    """Factory: return the polymarket features module."""
    from polymarket import features
    return features


def _make_ensemble_factory() -> object:
    """Factory: return EdgeDetector (polymarket's 'ensemble' equivalent)."""
    from polymarket.model import EdgeDetector
    return EdgeDetector


def _make_regime_factory() -> object:
    """Factory: return PolymarketRegimeDetector."""
    from polymarket.regime import PolymarketRegimeDetector
    return PolymarketRegimeDetector


def _make_broker_factory() -> object:
    """Factory: return LogPolymarketBroker (paper trading by default)."""
    from polymarket.broker import LogPolymarketBroker
    return LogPolymarketBroker


def _make_strategy_factory() -> object:
    """Factory: return the polymarket strategy module."""
    from polymarket import strategy
    return strategy


def _register() -> None:
    """Register the polymarket asset class with the global registry."""
    registry = AssetRegistry()

    if registry.is_registered("polymarket"):
        return

    registry.register(AssetClassConfig(
        name="polymarket",
        display_name="Polymarket",
        config_section="polymarket",
        data_loader_factory=_make_data_loader_factory,
        feature_builder_factory=_make_feature_builder_factory,
        ensemble_factory=_make_ensemble_factory,
        regime_factory=_make_regime_factory,
        broker_factory=_make_broker_factory,
        strategy_factory=_make_strategy_factory,
        uses_ohlcv=False,
    ))


# Auto-register on import
_register()
