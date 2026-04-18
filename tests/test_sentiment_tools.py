from __future__ import annotations

import asyncio
import json
from unittest.mock import patch


def test_score_sentiment_empty_texts():
    from core.agent.tools import sentiment_tools

    async def run():
        return await sentiment_tools.score_sentiment.handler({"texts": []})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["n_scored"] == 0
    assert payload["aggregate_compound"] == 0.0


def test_score_sentiment_with_stub():
    from core.agent.tools import sentiment_tools

    async def run():
        with patch(
            "core.agent.tools.sentiment_tools.score_texts",
            return_value=[{"label": "positive", "score": 0.9, "compound": 0.9}],
        ):
            return await sentiment_tools.score_sentiment.handler({"texts": ["great earnings"]})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["n_scored"] == 1
    assert payload["aggregate_compound"] > 0


def test_finbert_ticker_sentiment_rejects_empty():
    from core.agent.tools import sentiment_tools

    async def run():
        return await sentiment_tools.finbert_ticker_sentiment.handler(
            {"ticker": "", "since_minutes": 60},
        )

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert "error" in payload
