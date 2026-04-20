"""Unit tests for core.alt_data.earnings_whispers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, earnings_whispers


def setup_function() -> None:
    _cache._store.clear()


def test_scrape_falls_back_to_yfinance_when_patterns_miss() -> None:
    mock_resp = MagicMock()
    mock_resp.text = "<html>no earnings info</html>"
    mock_resp.raise_for_status.return_value = None
    fallback = {"earnings_date": "2026-04-25", "eps_estimate": 1.5}
    with patch("core.alt_data.earnings_whispers.requests.get", return_value=mock_resp), \
         patch("core.alt_data.earnings_whispers._yf_fallback", return_value=fallback):
        result = earnings_whispers.earnings_estimate("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["earnings_date"] == "2026-04-25"
    assert result["eps_estimate"] == 1.5


def test_scrape_extracts_fields_when_patterns_match() -> None:
    html = (
        '<html>'
        '<div class="earnings-date">April 25, 2026</div>'
        '<div class="epswhisper">$1.55</div>'
        '<div class="consensus">$1.50</div>'
        '</html>'
    )
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status.return_value = None
    with patch("core.alt_data.earnings_whispers.requests.get", return_value=mock_resp):
        result = earnings_whispers.earnings_estimate("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["source"] == "earningswhispers"
    assert "earnings_date" in result or "whisper_eps" in result


def test_fetch_failure_returns_error_when_no_fallback() -> None:
    with patch("core.alt_data.earnings_whispers.requests.get", side_effect=RuntimeError("boom")), \
         patch("core.alt_data.earnings_whispers._yf_fallback", return_value={}):
        result = earnings_whispers.earnings_estimate("ZZZZ")
    assert result["error"] == "no earnings data available"
