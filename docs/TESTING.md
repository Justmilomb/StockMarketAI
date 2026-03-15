# Testing

## Build Verification

- `python -c "import ai_service; import broker_service; import terminal.app"` — must complete with no import errors.
- `mypy --ignore-missing-imports *.py terminal/*.py` — should pass (when configured).

## Test Suite

- `pytest` — run from project root.
- All existing tests must pass. No skipping without documented reason.
- New code requires new tests unless it's pure wiring/glue.
- Test files go in `tests/` directory, mirroring source structure.

### Test Categories

| Category | Directory | What to test |
|----------|-----------|-------------|
| Unit | `tests/test_features.py` | Feature engineering, RSI calc, NaN handling |
| Unit | `tests/test_model.py` | Train/load/predict cycle, time-based split |
| Unit | `tests/test_strategy.py` | Signal generation logic, edge cases |
| Unit | `tests/test_broker.py` | LogBroker logging, Trading212 request building |
| Integration | `tests/test_ai_service.py` | Full pipeline with mock Gemini |
| Integration | `tests/test_auto_engine.py` | Signal → order flow with mock broker |

## Smoke Test Checklist

Manual verification steps for changes to core systems.

1. [ ] `python daily_agent.py` runs without errors and prints signals
2. [ ] `python terminal/app.py` launches TUI without crash
3. [ ] Watchlist displays tickers with live prices
4. [ ] Press 'g' — chart loads for selected ticker
5. [ ] Press 'c' — chat input focuses and responds
6. [ ] Press 'w' — watchlist cycles between groups
7. [ ] Press 'r' — data refreshes without error
8. [ ] No error-level output in terminal stderr

## Regression Rule

Full smoke test required for changes to:
- `ai_service.py` (signal pipeline)
- `terminal/app.py` (TUI lifecycle)
- `broker.py` or `broker_service.py` (order execution)
- `features.py` (model input format)
- `config.json` (schema changes)

## Log Patterns

- **Error (must fix):** `RuntimeError`, `ValueError`, `FileNotFoundError`, `HTTPError`
- **Warning (investigate):** `[broker_service] Missing Trading 212 api_key`, `Could not parse AI response`
- **Benign (ignore):** `chcp 65001`, yfinance download progress bars, `Skipped validation: not enough data`
