"""Forecasting package — Chronos / TimesFM / TFT + meta-learner.

Every wrapper exposes the same tiny surface: a module-level ``forecast``
function that takes ``(hist_df, interval_minutes, pred_len)`` and returns
``{"close": [...], "high": [...], "low": [...], "timestamps": [...]}`` on
success or ``{"error": "..."}`` on failure. Keeps the ensemble
``run_ensemble`` shim dumb — it just calls every enabled backend.
"""
