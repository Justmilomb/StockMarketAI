"""Unit tests for core.alt_data.sec_edgar (13F institutional holder search)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, sec_edgar


def setup_function() -> None:
    _cache._store.clear()


def test_institutional_holders_parses_hits_and_dedupes() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "hits": {
            "total": {"value": 42},
            "hits": [
                {"_source": {"entity_name": "Vanguard Group", "file_date": "2026-02-15", "period_of_report": "2025-12-31"}},
                {"_source": {"entity_name": "Vanguard Group", "file_date": "2026-02-15", "period_of_report": "2025-12-31"}},
                {"_source": {"entity_name": "BlackRock Inc", "file_date": "2026-02-14", "period_of_report": "2025-12-31"}},
                {"_source": {"entity_name": "", "file_date": "", "period_of_report": ""}},
            ],
        },
    }
    mock_resp.raise_for_status.return_value = None
    with patch("core.alt_data.sec_edgar.requests.get", return_value=mock_resp):
        result = sec_edgar.institutional_holders("AAPL", lookback_days=90)
    assert result["ticker"] == "AAPL"
    assert result["total_13f_filings"] == 42
    names = [i["institution"] for i in result["institutions"]]
    assert names == ["Vanguard Group", "BlackRock Inc"]


def test_institutional_holders_handles_http_failure() -> None:
    with patch("core.alt_data.sec_edgar.requests.get", side_effect=RuntimeError("network down")):
        result = sec_edgar.institutional_holders("AAPL")
    assert "error" in result
    assert "network down" in result["error"]


def test_institutional_holders_cached_across_calls() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
    mock_resp.raise_for_status.return_value = None
    with patch("core.alt_data.sec_edgar.requests.get", return_value=mock_resp) as g:
        sec_edgar.institutional_holders("AAPL")
        sec_edgar.institutional_holders("AAPL")
    assert g.call_count == 1
