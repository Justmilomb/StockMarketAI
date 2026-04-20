"""Unit tests for core.alt_data.alpha_vantage — mocks HTTP boundary only."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, alpha_vantage


def setup_function() -> None:
    _cache._store.clear()


def test_company_overview_missing_key_returns_error() -> None:
    with patch.dict("os.environ", {"ALPHA_VANTAGE_KEY": ""}, clear=False):
        result = alpha_vantage.company_overview("AAPL")
    assert "error" in result
    assert "ALPHA_VANTAGE_KEY" in result["error"]


def test_company_overview_happy_path() -> None:
    sample = {
        "Symbol": "AAPL",
        "Name": "Apple Inc",
        "Sector": "Technology",
        "MarketCapitalization": "3000000000000",
        "PERatio": "28.5",
        "EPS": "6.10",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = sample
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"ALPHA_VANTAGE_KEY": "test"}, clear=False), \
         patch("core.alt_data.alpha_vantage.requests.get", return_value=mock_resp):
        result = alpha_vantage.company_overview("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["name"] == "Apple Inc"
    assert result["sector"] == "Technology"
    assert result["pe_ratio"] == "28.5"


def test_company_overview_returns_error_when_payload_empty() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"ALPHA_VANTAGE_KEY": "test"}, clear=False), \
         patch("core.alt_data.alpha_vantage.requests.get", return_value=mock_resp):
        result = alpha_vantage.company_overview("ZZZZ")
    assert "error" in result


def test_earnings_history_parses_quarterly_rows() -> None:
    sample = {
        "symbol": "AAPL",
        "quarterlyEarnings": [
            {
                "fiscalDateEnding": "2026-03-31",
                "reportedDate": "2026-04-25",
                "reportedEPS": "1.53",
                "estimatedEPS": "1.50",
                "surprise": "0.03",
                "surprisePercentage": "2.00",
            },
        ],
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = sample
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"ALPHA_VANTAGE_KEY": "test"}, clear=False), \
         patch("core.alt_data.alpha_vantage.requests.get", return_value=mock_resp):
        result = alpha_vantage.earnings_history("AAPL")
    assert result["ticker"] == "AAPL"
    assert len(result["quarterly"]) == 1
    row = result["quarterly"][0]
    assert row["reported_eps"] == "1.53"
    assert row["surprise_pct"] == "2.00"


def test_rate_limit_note_surfaces_as_error() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Note": "API rate limit reached"}
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"ALPHA_VANTAGE_KEY": "test"}, clear=False), \
         patch("core.alt_data.alpha_vantage.requests.get", return_value=mock_resp):
        result = alpha_vantage.company_overview("AAPL")
    assert "error" in result
    assert "rate limit" in result["error"].lower()
