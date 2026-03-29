"""Crypto asset class package.

Importing this package registers ``"crypto"`` with the ``AssetRegistry``,
wiring up crypto-specific factories for data loading, feature engineering,
ML ensemble, regime detection, broker connectivity, and strategy logic.
"""

from __future__ import annotations

from asset_registry import AssetClassConfig, AssetRegistry
from crypto.types import CryptoConfig


def _make_data_loader_factory() -> object:
    """Factory: return the crypto data_loader module."""
    from crypto import data_loader
    return data_loader


def _make_feature_builder_factory() -> object:
    """Factory: return the crypto features module."""
    from crypto import features
    return features


def _make_ensemble_factory() -> object:
    """Factory: return a crypto-configured EnsembleModel."""
    from crypto.ensemble import create_crypto_ensemble
    return create_crypto_ensemble


def _make_regime_factory() -> object:
    """Factory: return a CryptoRegimeDetector instance."""
    from crypto.regime import CryptoRegimeDetector
    return CryptoRegimeDetector


def _make_broker_factory() -> object:
    """Factory: return the crypto broker module."""
    from crypto import broker
    return broker


def _make_strategy_factory() -> object:
    """Factory: return the crypto strategy module."""
    from crypto import strategy
    return strategy


def _register() -> None:
    """Register the crypto asset class with the global registry."""
    registry = AssetRegistry()

    if registry.is_registered("crypto"):
        return

    registry.register(AssetClassConfig(
        name="crypto",
        display_name="Crypto",
        config_section="crypto",
        data_loader_factory=_make_data_loader_factory,
        feature_builder_factory=_make_feature_builder_factory,
        ensemble_factory=_make_ensemble_factory,
        regime_factory=_make_regime_factory,
        broker_factory=_make_broker_factory,
        strategy_factory=_make_strategy_factory,
        uses_ohlcv=True,
        default_watchlist=[
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
        ],
    ))


# Auto-register on import
_register()
