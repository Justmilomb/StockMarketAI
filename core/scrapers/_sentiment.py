"""Lightweight sentiment scoring for scraped items.

Runs on every scraper cycle BEFORE the items hit the database, so the
information panel can colour-code headlines without a second pass. We
use VADER — it's a pure-Python library with a built-in finance-tilted
lexicon, scores in microseconds, and needs zero API calls. That matters
because a single scrape cycle can yield 100+ new items across 10 sources
and we don't want to burn Claude subscription tokens on headline mood.

VADER returns a ``compound`` score in [-1.0, +1.0]. We map to a string
label so the UI doesn't have to re-derive it each render:

* ``> +0.1`` → ``"bullish"``
* ``< -0.1`` → ``"bearish"``
* otherwise → ``"neutral"``

The 0.1 threshold is the value VADER's own README recommends for
general-purpose classification; anything tighter produces a lot of
false positives on financial boilerplate like "beat expectations" that
VADER scores mildly positive by default.

If ``vaderSentiment`` isn't installed, ``score_item`` is a no-op (returns
``None`` fields) so the scraper pipeline keeps working — the information
panel simply shows no colour-badge.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _ANALYZER: Optional[SentimentIntensityAnalyzer] = SentimentIntensityAnalyzer()
except Exception:
    _ANALYZER = None


#: Threshold that separates neutral from bullish/bearish. Values from
#: the VADER project README.
_POS_THRESHOLD: float = 0.1
_NEG_THRESHOLD: float = -0.1


def is_available() -> bool:
    return _ANALYZER is not None


def score_text(text: str) -> tuple[Optional[float], Optional[str]]:
    """Return ``(compound_score, label)`` for *text* or ``(None, None)``.

    Never raises — a broken analyser should not kill the scraper cycle.
    """
    if _ANALYZER is None or not text:
        return None, None
    try:
        scores = _ANALYZER.polarity_scores(text)
        compound = float(scores.get("compound", 0.0))
    except Exception:
        return None, None
    if compound > _POS_THRESHOLD:
        return compound, "bullish"
    if compound < _NEG_THRESHOLD:
        return compound, "bearish"
    return compound, "neutral"


def score_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Add ``sentiment_score`` + ``sentiment_label`` to *item* and return it.

    Scores the ``title`` plus ``summary`` concatenated, which mirrors how
    the information panel displays them.
    """
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    body = (title + " " + summary).strip()
    score, label = score_text(body)
    if score is not None:
        item["sentiment_score"] = score
        item["sentiment_label"] = label
    return item
