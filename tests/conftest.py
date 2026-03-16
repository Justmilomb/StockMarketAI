"""Shared pytest fixtures for StockMarketAI tests."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """A minimal OHLCV DataFrame indexed by date, suitable for feature engineering."""
    dates = pd.bdate_range(end=datetime.now(), periods=60)
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(60) * 0.5)
    high = close + np.abs(np.random.randn(60) * 0.3)
    low = close - np.abs(np.random.randn(60) * 0.3)
    open_ = close + np.random.randn(60) * 0.2
    volume = np.random.randint(1_000_000, 10_000_000, size=60)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    df.index.name = "Date"
    return df


@pytest.fixture
def sample_config(tmp_path: Path) -> Dict[str, Any]:
    """A valid config dict that mirrors config.json structure."""
    cfg = {
        "watchlists": {"Main": ["AAPL", "MSFT", "GOOGL"]},
        "active_watchlist": "Main",
        "start_date": "2023-01-01",
        "end_date": "2024-01-01",
        "data_dir": str(tmp_path / "data"),
        "model_path": str(tmp_path / "models" / "rf_tomorrow_up.joblib"),
        "strategy": {
            "threshold_buy": 0.6,
            "threshold_sell": 0.4,
            "max_positions": 5,
            "position_size_fraction": 0.2,
        },
        "capital": 100_000,
        "ai": {
            "sklearn_weight": 0.5,
            "gemini_weight": 0.3,
            "news_weight": 0.2,
            "retrain_on_start": False,
            "retrain_interval_hours": 24,
        },
        "gemini": {"api_key_env": "GEMINI_API_KEY", "model": "gemini-2.5-flash"},
        "broker": {"type": "log"},
        "terminal": {
            "mode": "recommendation",
            "refresh_interval_seconds": 30,
            "max_daily_loss": 0.05,
        },
    }
    return cfg


@pytest.fixture
def sample_config_path(sample_config: Dict[str, Any], tmp_path: Path) -> Path:
    """Write sample_config to a temp JSON file and return its path."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(sample_config), encoding="utf-8")
    return path


@pytest.fixture
def sample_universe_data(sample_ohlcv_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Universe data dict mapping ticker -> OHLCV DataFrame."""
    return {
        "AAPL": sample_ohlcv_df.copy(),
        "MSFT": sample_ohlcv_df.copy(),
    }


@pytest.fixture
def mock_gemini_client() -> MagicMock:
    """A mocked GeminiClient that returns sensible defaults."""
    client = MagicMock()
    client.get_signal_for_ticker.return_value = {
        "p_up_gemini": 0.6,
        "reason": "Test reason",
    }
    client.get_recommendation.return_value = {
        "action": "HOLD",
        "confidence": 0.5,
        "reasoning": "Test reasoning",
    }
    client.analyze_news.return_value = {"sentiment": 0.1, "summary": "Neutral news"}
    client.suggest_ticker.return_value = "NVDA"
    client.search_tickers.return_value = [
        {"ticker": "NVDA", "name": "NVIDIA Corp", "sector": "Technology"}
    ]
    client.chat_with_context.return_value = "Test AI response"
    client._call.return_value = '{"changes": {}, "explanation": "No changes needed"}'
    return client


@pytest.fixture
def mock_broker() -> MagicMock:
    """A mocked Broker that returns empty/safe defaults."""
    broker = MagicMock()
    broker.get_positions.return_value = []
    broker.get_account_info.return_value = {
        "free": 100_000.0,
        "invested": 0.0,
        "result": 0.0,
        "total": 100_000.0,
    }
    broker.get_pending_orders.return_value = []
    broker.submit_order.return_value = {
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 1.0,
        "order_type": "market",
        "status": "SUBMITTED",
    }
    broker.cancel_order.return_value = True
    return broker
