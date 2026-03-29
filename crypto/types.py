"""Crypto-specific configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ExchangeConfig:
    """Connection details for a single crypto exchange."""

    name: str = "binance"
    api_key_env: str = "CRYPTO_API_KEY"
    secret_key_env: str = "CRYPTO_SECRET_KEY"
    testnet: bool = True
    rate_limit: bool = True
    timeout_ms: int = 30_000


@dataclass
class CryptoConfig:
    """Top-level configuration for the crypto asset class.

    Populated from the ``crypto`` section of ``config.json``.
    """

    enabled: bool = False
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    watchlists: Dict[str, List[str]] = field(default_factory=lambda: {
        "Major": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"],
    })
    active_watchlist: str = "Major"
    data_dir: str = "data"

    # Strategy thresholds (24/7 market, slightly wider than stocks)
    threshold_buy: float = 0.62
    threshold_sell: float = 0.38
    max_positions: int = 5
    position_size_fraction: float = 0.08

    # Risk parameters
    kelly_fraction_cap: float = 0.20
    max_position_pct: float = 0.15
    atr_stop_multiplier: float = 2.5
    atr_profit_multiplier: float = 3.5
    min_position_dollars: float = 5.0

    # Ensemble
    model_dir: str = "models/crypto/ensemble"
    n_models: int = 8
    horizons: List[int] = field(default_factory=lambda: [1, 3, 7])

    # Regime
    regime_lookback_days: int = 60
    benchmark_pair: str = "BTC/USDT"

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> CryptoConfig:
        """Build a CryptoConfig from the ``crypto`` section of config.json."""
        exchange_raw = raw.get("exchange", raw.get("exchange_name", "binance"))
        if isinstance(exchange_raw, dict):
            exchange = ExchangeConfig(**exchange_raw)
        else:
            exchange = ExchangeConfig(
                name=str(raw.get("exchange", "binance")),
                api_key_env=str(raw.get("api_key_env", "CRYPTO_API_KEY")),
                secret_key_env=str(raw.get("secret_key_env", "CRYPTO_SECRET_KEY")),
                testnet=bool(raw.get("testnet", True)),
            )

        watchlists_raw = raw.get("watchlists", {})
        watchlists = {
            str(k): list(v)
            for k, v in watchlists_raw.items()  # type: ignore[union-attr]
        } if isinstance(watchlists_raw, dict) else {}

        strategy_raw = raw.get("strategy", {})
        if not isinstance(strategy_raw, dict):
            strategy_raw = {}
        risk_raw = raw.get("risk", {})
        if not isinstance(risk_raw, dict):
            risk_raw = {}
        ensemble_raw = raw.get("ensemble", {})
        if not isinstance(ensemble_raw, dict):
            ensemble_raw = {}
        regime_raw = raw.get("regime", {})
        if not isinstance(regime_raw, dict):
            regime_raw = {}

        return cls(
            enabled=bool(raw.get("enabled", False)),
            exchange=exchange,
            watchlists=watchlists,
            active_watchlist=str(raw.get("active_watchlist", "Major")),
            data_dir=str(raw.get("data_dir", "data")),
            threshold_buy=float(strategy_raw.get("threshold_buy", 0.62)),
            threshold_sell=float(strategy_raw.get("threshold_sell", 0.38)),
            max_positions=int(strategy_raw.get("max_positions", 5)),
            position_size_fraction=float(strategy_raw.get("position_size_fraction", 0.08)),
            kelly_fraction_cap=float(risk_raw.get("kelly_fraction_cap", 0.20)),
            max_position_pct=float(risk_raw.get("max_position_pct", 0.15)),
            atr_stop_multiplier=float(risk_raw.get("atr_stop_multiplier", 2.5)),
            atr_profit_multiplier=float(risk_raw.get("atr_profit_multiplier", 3.5)),
            min_position_dollars=float(risk_raw.get("min_position_dollars", 5.0)),
            model_dir=str(raw.get("model_dir", "models/crypto/ensemble")),
            n_models=int(ensemble_raw.get("n_models", 8)),
            horizons=list(ensemble_raw.get("horizons", [1, 3, 7])),
            regime_lookback_days=int(regime_raw.get("lookback_days", 60)),
            benchmark_pair=str(regime_raw.get("benchmark_ticker", "BTC/USDT")),
        )
