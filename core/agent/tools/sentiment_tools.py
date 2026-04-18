"""FinBERT + StockTwits sentiment tools.

Two tools:

* ``score_sentiment(texts)`` — batch-score arbitrary text with FinBERT.
  Useful when the agent already has news headlines or research notes
  and wants a numeric mood score.

* ``finbert_ticker_sentiment(ticker)`` — pulls recent cached social
  items for *ticker* from the scraper buffer and scores them with
  FinBERT. Also returns the existing StockTwits bullish/bearish tag
  so the agent can compare explicit tags vs model inferences.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.nlp.finbert import aggregate_compound, score_texts


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "score_sentiment",
    "Score a batch of text snippets with FinBERT (financial BERT) and "
    "return per-text {label, score, compound} + an aggregate compound. "
    "Use on news headlines, research notes, or any free text you want a "
    "mood signal from.",
    {"texts": list},
)
async def score_sentiment(args: Dict[str, Any]) -> Dict[str, Any]:
    raw_texts = args.get("texts") or []
    texts: List[str] = [str(t) for t in raw_texts if str(t).strip()]
    scores = score_texts(texts)
    return _text_result({
        "n_scored": len(scores),
        "scores": scores,
        "aggregate_compound": aggregate_compound(scores),
    })


@tool(
    "finbert_ticker_sentiment",
    "Pull recent cached social posts for *ticker* from the scraper buffer "
    "and score them with FinBERT. Compares the aggregate FinBERT compound "
    "to the StockTwits bullish/bearish tag ratio so you can spot "
    "disagreement between explicit user tags and what the model reads.",
    {"ticker": str, "since_minutes": int},
)
async def finbert_ticker_sentiment(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    since = int(args.get("since_minutes", 360) or 360)
    if not ticker:
        return _text_result({"error": "ticker is required"})

    ctx = get_agent_context()
    items = ctx.db.get_scraper_items(tickers=[ticker], since_minutes=since) \
        if hasattr(ctx.db, "get_scraper_items") else []

    texts: List[str] = []
    bulls = 0
    bears = 0
    for it in items:
        title = str((it.get("title") or it.get("summary") or "")).strip()
        if title:
            texts.append(title)
        meta = it.get("meta") or {}
        sentiment = meta.get("sentiment")
        if sentiment == "Bullish":
            bulls += 1
        elif sentiment == "Bearish":
            bears += 1

    scores = score_texts(texts)
    stocktwits_ratio = 0.0
    if bulls + bears > 0:
        stocktwits_ratio = (bulls - bears) / (bulls + bears)

    finbert_agg = aggregate_compound(scores)
    return _text_result({
        "ticker": ticker,
        "since_minutes": since,
        "posts_found": len(items),
        "posts_scored": len(scores),
        "finbert_aggregate": finbert_agg,
        "stocktwits_ratio": stocktwits_ratio,
        "stocktwits_bulls": bulls,
        "stocktwits_bears": bears,
        "disagreement": abs(finbert_agg - stocktwits_ratio),
    })


SENTIMENT_TOOLS = [score_sentiment, finbert_ticker_sentiment]
