"""Structured news headline MCP tool — News API.

Supplements the scraper-based news feed with a keyword-searchable endpoint
that returns structured headline data (title, source, date, description, URL)
from mainstream English-language outlets.

Requires NEWS_API_KEY env var and alt_data.news_api.enabled: true in config.json.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "get_structured_news",
    "Search recent news headlines for *query* (ticker symbol, company name, or topic) "
    "using News API. Returns up to 20 articles with: title, source, publication date, "
    "description, and URL. Sorted newest first. "
    "*days_back* controls the lookback window (1–29, default 7; free-tier max is 30 days). "
    "Use this when you need source-attributed, structured headline data — e.g., to check "
    "whether a recent price move has a news catalyst, or to scan for M&A rumours. "
    "Complements the scraper-based feed (get_news) which is broader but less structured. "
    "Requires NEWS_API_KEY env var and alt_data.news_api.enabled: true.",
    {"query": str, "days_back": int},
)
async def get_structured_news(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return _text_result({"error": "query is required"})
    days_back = max(1, min(29, int(args.get("days_back", 7) or 7)))
    ctx = get_agent_context()
    cfg = ctx.config.get("alt_data", {}).get("news_api", {})
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.news_api is disabled",
            "fix": "set alt_data.news_api.enabled to true in config.json and set NEWS_API_KEY",
        })
    from core.alt_data.news_api_client import search_headlines
    ttl = int(cfg.get("cache_ttl_seconds", 900))
    return _text_result(search_headlines(query, days_back=days_back, ttl=ttl))


NEWS_API_TOOLS = [get_structured_news]
