"""Unit tests for core.alt_data.news_api_client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.alt_data import _cache, news_api_client


def setup_function() -> None:
    _cache._store.clear()


def test_missing_key_surfaces() -> None:
    with patch.dict("os.environ", {"NEWS_API_KEY": ""}, clear=False):
        result = news_api_client.search_headlines("AAPL")
    assert "error" in result
    assert "NEWS_API_KEY" in result["error"]


def test_search_headlines_happy_path() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "ok",
        "totalResults": 2,
        "articles": [
            {
                "title": "Apple reports record quarter",
                "source": {"name": "Reuters"},
                "publishedAt": "2026-04-20T12:00:00Z",
                "description": "...",
                "url": "https://example.com/a",
            },
            {
                "title": "iPhone 17 launch soon",
                "source": {"name": "WSJ"},
                "publishedAt": "2026-04-19T09:00:00Z",
                "description": "...",
                "url": "https://example.com/b",
            },
        ],
    }
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"NEWS_API_KEY": "test"}, clear=False), \
         patch("core.alt_data.news_api_client.requests.get", return_value=mock_resp):
        result = news_api_client.search_headlines("AAPL")
    assert result["query"] == "AAPL"
    assert result["total_results"] == 2
    assert len(result["articles"]) == 2
    assert result["articles"][0]["source"] == "Reuters"


def test_non_ok_status_surfaces_message() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "error", "message": "apiKeyInvalid"}
    mock_resp.raise_for_status.return_value = None
    with patch.dict("os.environ", {"NEWS_API_KEY": "test"}, clear=False), \
         patch("core.alt_data.news_api_client.requests.get", return_value=mock_resp):
        result = news_api_client.search_headlines("AAPL")
    assert result == {"error": "apiKeyInvalid"}
