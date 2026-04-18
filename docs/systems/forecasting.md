# Forecasting Ensemble

Four independent forecasters run in parallel, each producing close / high
/ low predictions over a user-chosen horizon. An XGBoost meta-learner
blends their outputs into a single `prob_up + direction +
expected_move_pct` signal that the agent can consume as one MCP tool call.

## Forecasters

| Name    | Source                          | Module                                   |
|---------|---------------------------------|------------------------------------------|
| Kronos  | `NeoQuasar/Kronos-small`        | `core/kronos_forecaster.py`              |
| Chronos | `amazon/chronos-t5-small`       | `core/forecasting/chronos_forecaster.py` |
| TimesFM | `google/timesfm-2.0-500m-pytorch` | `core/forecasting/timesfm_forecaster.py` |
| TFT     | `pytorch-forecasting` TFT (train-on-demand) | `core/forecasting/tft_forecaster.py` |

Each wrapper exposes `forecast(hist_df, interval_minutes, pred_len,
**kwargs) -> dict` with the same shape — timestamps, close, high, low,
model_id, pred_len. Any wrapper that can't load its dependency returns
`{"error": "..."}` rather than raising, so the ensemble keeps working
as long as one forecaster succeeds.

All forecasters are **lazy singletons** — the model is only loaded on
first call, guarded by a thread lock. This keeps the desktop app cold
start fast and never triggers a model download unless the tool is
actually used.

## Meta-learner (`core/forecasting/meta_learner.py`)

Builds a 4-col feature row per forecaster (`_pct_final`, `_pct_max`,
`_pct_min`, `_present`). XGBoost `binary:logistic` predicts `prob_up`
from those features once at least 50 labelled rows have been recorded.

Until the training set is large enough the meta-learner falls back to a
simple vote — the mean of each forecaster's predicted close-move
compared to the current price.

Labels are added via `MetaLearner.record(forecaster_outputs, last_close,
realised_close)`. The fine-tune pipeline (see `core/finetune/`) is what
calls `record` whenever a SELL fill closes a position.

## Ensemble orchestrator (`core/forecasting/ensemble.py`)

```python
out = run_ensemble(
    hist_df=last_400_bars,
    interval_minutes=5,
    pred_len=12,          # = horizon / interval
    ticker="TSLA",
    enabled={"kronos": True, "chronos": True, "timesfm": True, "tft": False},
    meta_model_path="models/meta_learner.json",
)
```

Returns `{ticker, pred_len, interval_minutes, last_close, forecasters,
meta}`. `forecasters` contains each model's raw output (or error
payload); `meta` is the blended signal.

## `forecast_ensemble` MCP tool

The agent's one-call entry point — `core/agent/tools/ensemble_tools.py`.
Fetches recent bars via yfinance, runs the ensemble, and returns a
trimmed payload (no full close/high/low arrays) so the MCP channel
stays cheap.

Input args: `{ticker, horizon_minutes, interval}`.

Output payload shape:

```json
{
  "ticker": "TSLA",
  "pred_len": 12,
  "interval_minutes": 5,
  "last_close": 245.3,
  "meta": {
    "prob_up": 0.63,
    "direction": "up",
    "expected_move_pct": 0.82,
    "confidence": 0.26,
    "n_forecasters": 3,
    "source": "xgboost"
  },
  "forecasters": {
    "kronos":  {"available": true,  "final_close": 247.1, "model_id": "kronos"},
    "chronos": {"available": true,  "final_close": 246.4, "model_id": "chronos-t5-small"},
    "timesfm": {"available": false, "error": "torch unavailable"},
    "tft":     {"available": true,  "final_close": 248.0, "model_id": "tft"}
  }
}
```

## When to prefer it over `forecast_candles`

`forecast_candles` exposes a single forecaster (Kronos only). Use it
when inspecting one model's output. For actual trading decisions prefer
`forecast_ensemble` — it aggregates four independent models so no
single bad prediction dominates, and the meta-learner weights them by
historical accuracy on this terminal's trade history.
