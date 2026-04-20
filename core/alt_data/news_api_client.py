"""News API client — structured headline search.

Free tier: 100 requests/day, articles up to 30 days old.
Env var: NEWS_API_KEY  (register free at newsapi.org)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_API_KEY_ENV = "NEWS_API_KEY"
_BASE = "https://newsapi.org/v2"


def _key() -> str:
    return os.getenv(_API_KEY_ENV, "")


def search_headlines(
    query: str,
    days_back: int = 7,
    page_size: int = 20,
    ttl: int = 900,
) -> Dict[str, Any]:
    """Search recent news headlines for *query* (ticker or topic).

    Returns up to *page_size* articles (max 20 on free tier) with title,
    source, publication timestamp, description, and URL.
    """
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"newsapi_{query}_{days_back}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from_date = (
            datetime.now(timezone.utc) - timedelta(days=min(days_back, 29))
        ).strftime("%Y-%m-%d")
        resp = requests.get(
            f"{_BASE}/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "publishedAt",
                "pageSize": str(min(page_size, 20)),
                "language": "en",
                "apiKey": _key(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            return {"error": data.get("message", "News API error")}
        articles: List[Dict[str, Any]] = [
            {
                "title": a.get("title"),
                "source": (a.get("source") or {}).get("name"),
                "published_at": a.get("publishedAt"),
                "description": a.get("description"),
                "url": a.get("url"),
            }
            for a in (data.get("articles") or [])
        ]
        result: Dict[str, Any] = {
            "query": query,
            "total_results": data.get("totalResults", 0),
            "articles": articles,
        }
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("news_api: search_headlines(%r) failed: %s", query, exc)
        return {"error": str(exc)}
