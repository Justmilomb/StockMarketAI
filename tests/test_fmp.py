"""Unit tests for core.alt_data.fmp."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, fmp


def setup_function() -> None:
    _cache._store.clear()


def test_financial_ratios_missing_key() -> None:
    with patch.dict("os.environ", {"FMP_KEY": ""}, clear=False):
        result = fmp.financial_ratios("AAPL")
    assert "error" in result


def test_financial_ratios_happy_path() -> None:
    sample = [{
        "peRatioTTM": 28.5,
        "returnOnEquityTTM": 1.5,
        "debtEquityRatioTTM": 1.8,
        "currentRatioTTM": 0.95,
    }]
    mock_resp = MagicMock()
    mock_resp.json.return_value = sample
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FMP_KEY": "test"}, clear=False), \
         patch("core.alt_data.fmp.requests.get", return_value=mock_resp):
        result = fmp.financial_ratios("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["pe_ratio"] == 28.5
    assert result["roe"] == 1.5


def test_dcf_value_computes_upside() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{
        "date": "2026-04-20",
        "stockPrice": 200.0,
        "dcf": 250.0,
    }]
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FMP_KEY": "test"}, clear=False), \
         patch("core.alt_data.fmp.requests.get", return_value=mock_resp):
        result = fmp.dcf_value("AAPL")
    assert result["stock_price"] == 200.0
    assert result["dcf_value"] == 250.0
    assert result["upside_pct"] == 25.0


def test_dcf_value_handles_missing_data() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FMP_KEY": "test"}, clear=False), \
         patch("core.alt_data.fmp.requests.get", return_value=mock_resp):
        result = fmp.dcf_value("ZZZZ")
    assert "error" in result


def test_analyst_targets_returns_consensus() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{
        "targetConsensus": 210.0,
        "targetHigh": 260.0,
        "targetLow": 170.0,
        "targetMedian": 215.0,
    }]
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"FMP_KEY": "test"}, clear=False), \
         patch("core.alt_data.fmp.requests.get", return_value=mock_resp):
        result = fmp.analyst_targets("AAPL")
    assert result["target_consensus"] == 210.0
    assert result["target_high"] == 260.0
    assert result["target_low"] == 170.0
