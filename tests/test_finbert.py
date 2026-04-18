from __future__ import annotations

import pytest


def test_finbert_score_empty_returns_empty():
    from core.nlp import finbert
    assert finbert.score_texts([]) == []


def test_finbert_aggregate_compound_empty():
    from core.nlp import finbert
    assert finbert.aggregate_compound([]) == 0.0


def test_finbert_aggregate_compound_clamped():
    from core.nlp import finbert
    scores = [{"compound": 0.8}, {"compound": 0.6}]
    assert finbert.aggregate_compound(scores) == pytest.approx(0.7)


def test_finbert_returns_labels_on_sample_text():
    pytest.importorskip("transformers")
    from core.nlp import finbert

    scores = finbert.score_texts([
        "Shares rallied after record earnings beat expectations",
        "Company warns on revenue, stock plunges",
    ])
    if not scores:
        pytest.skip("finbert model not available")
    assert scores[0]["label"] in {"positive", "negative", "neutral"}
    assert 0.0 <= scores[0]["score"] <= 1.0
