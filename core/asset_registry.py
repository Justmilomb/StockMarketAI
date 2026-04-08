"""Asset class registry for multi-asset pipeline routing.

Maps each AssetClass to the factories and modules that implement its
data loading, feature engineering, ML ensemble, regime detection,
broker connectivity, and strategy logic.

Stocks are registered by default. Crypto and Polymarket register
themselves when their packages are imported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from types_shared import AssetClass


@dataclass
class AssetClassConfig:
    """Everything the pipeline needs to run one asset class."""

    name: AssetClass
    display_name: str
    config_section: str  # key in config.json for asset-specific config

    # Factory callables — each returns the relevant module/object
    data_loader_factory: Callable[..., Any] = lambda: None
    feature_builder_factory: Callable[..., Any] = lambda: None
    ensemble_factory: Callable[..., Any] = lambda: None
    regime_factory: Callable[..., Any] = lambda: None
    broker_factory: Callable[..., Any] = lambda: None
    strategy_factory: Callable[..., Any] = lambda: None

    # Whether this asset class uses OHLCV data (crypto, stocks)
    # vs event-based data (polymarket)
    uses_ohlcv: bool = True

    # Default watchlist for this asset class
    default_watchlist: List[str] = field(default_factory=list)


class AssetRegistry:
    """Singleton registry of available asset classes.

    Usage:
        registry = AssetRegistry()
        registry.register(AssetClassConfig(name="crypto", ...))
        config = registry.get("crypto")
    """

    _instance: Optional[AssetRegistry] = None
    _registry: Dict[AssetClass, AssetClassConfig]

    def __new__(cls) -> AssetRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry = {}
            cls._instance._register_stocks()
        return cls._instance

    def _register_stocks(self) -> None:
        """Register the built-in stocks asset class."""
        self._registry["stocks"] = AssetClassConfig(
            name="stocks",
            display_name="Stocks",
            config_section="stocks",
            uses_ohlcv=True,
        )

    def register(self, config: AssetClassConfig) -> None:
        """Register an asset class configuration."""
        self._registry[config.name] = config

    def get(self, asset_class: AssetClass) -> AssetClassConfig:
        """Get the config for an asset class. Raises KeyError if not registered."""
        return self._registry[asset_class]

    def is_registered(self, asset_class: AssetClass) -> bool:
        """Check if an asset class has been registered."""
        return asset_class in self._registry

    def enabled(self, app_config: Dict[str, Any] | None = None) -> List[AssetClass]:
        """Return list of enabled asset classes.

        If app_config is provided, checks the 'enabled_asset_classes' key.
        Otherwise returns all registered asset classes.
        """
        if app_config is not None:
            enabled_list = app_config.get("enabled_asset_classes", ["stocks"])
            return [ac for ac in enabled_list if ac in self._registry]
        return list(self._registry.keys())

    def all_registered(self) -> List[AssetClass]:
        """Return all registered asset class names."""
        return list(self._registry.keys())
