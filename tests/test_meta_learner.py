from __future__ import annotations

from core.forecasting.meta_learner import MetaLearner, build_features


def test_build_features_from_single_forecaster():
    forecaster_outputs = {
        "kronos": {"close": [100.0, 101.0, 102.0], "model_id": "k"},
    }
    feats = build_features(forecaster_outputs, last_close=100.0)
    assert "kronos_pct_final" in feats
    assert abs(feats["kronos_pct_final"] - 0.02) < 1e-6
    # Missing forecasters still emit zeroed columns so feature vector has
    # a fixed shape.
    assert feats["chronos_present"] == 0.0
    assert feats["chronos_pct_final"] == 0.0


def test_meta_learner_untrained_falls_back_to_vote(tmp_path):
    ml = MetaLearner(model_path=tmp_path / "meta.json")
    outputs = {
        "kronos": {"close": [100, 101]},
        "chronos": {"close": [100, 102]},
    }
    preds = ml.predict(outputs, last_close=100.0)
    assert 0.0 <= preds["prob_up"] <= 1.0
    assert preds["direction"] in {"up", "down", "flat"}
    assert preds["n_forecasters"] == 2
    assert preds["source"].startswith("vote")


def test_meta_learner_ignores_error_forecasters(tmp_path):
    ml = MetaLearner(model_path=tmp_path / "meta.json")
    outputs = {
        "kronos": {"close": [100, 101]},
        "chronos": {"error": "forecast failed"},
    }
    preds = ml.predict(outputs, last_close=100.0)
    assert preds["n_forecasters"] == 1


def test_meta_learner_record_does_not_raise(tmp_path):
    ml = MetaLearner(model_path=tmp_path / "meta.json")
    ml.record(
        {"kronos": {"close": [100.0, 101.0]}},
        last_close=100.0,
        realised_close=101.5,
    )
    # Not enough data to fit yet.
    assert ml.fit() is False
