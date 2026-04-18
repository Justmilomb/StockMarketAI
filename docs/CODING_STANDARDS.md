# Coding Standards

## Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Classes/Types | PascalCase | `AiService`, `TickerNews` |
| Functions | snake_case | `generate_signals`, `fetch_live_prices` |
| Variables | snake_case | `prob_up`, `universe_data` |
| Constants | UPPER_SNAKE | `FEATURE_COLUMNS`, `DEFAULT_DATA_DIR` |
| Booleans | `is_`/`has_`/`_loaded` | `_model_loaded`, `is_active` |
| Private members | `_leading_underscore` | `_config_cache`, `_broker` |
| Dataclass configs | `{System}Config` | `ModelConfig`, `StrategyConfig`, `AIConfig` |

## File Organisation

- Leaf modules should stay under ~400 lines. Hub files (`app.py`, `ai_service.py`) and files that are the single logical owner of a complex concern may exceed this when splitting would hurt readability or create artificial seams.
- One class/module per file (except small value types like configs).
- Imports: stdlib → third-party → local (isort compatible).
- `from __future__ import annotations` at top of every file that uses `X | None` syntax.
- No circular imports. Use local imports inside methods if needed.

## Error Handling

- Validate at system boundaries (user input, external APIs). Trust internal code.
- External API calls (yfinance, Claude CLI, Trading 212) wrapped in try/except with fallback defaults.
- `ValueError` for bad input data. `FileNotFoundError` for missing models.
- `RuntimeError` for missing required configuration (e.g. API keys).
- Log unexpected states at Warning level. Log failures at Error level.
- Never silently swallow exceptions — at minimum print to stderr.

## Type Hints

- Type hints on every function signature. No exceptions.
- `Any` only at serialisation boundaries (JSON parsing, config dicts).
- Use `X | None` over `Optional[X]` (with `from __future__ import annotations`).
- Dataclasses for all config/state bundles. No naked dicts for structured data.
- `Dict[str, Any]` aliased as `ConfigDict` where used.

## Comments

- Class-level docstring required on every public type.
- Function-level docstring only if behaviour is non-obvious.
- Inline comments explain *why*, never *what*.
- No commented-out code. Delete it; git has the history.
- No TODO/FIXME in code — use `docs/CURRENT_TASKS.md`.

## Formatting

- 4-space indentation (Python standard).
- Max line length: 100 characters (soft limit).
- Trailing commas in multiline function calls and data structures.
- String quotes: double quotes for user-facing strings, single for internal identifiers.
- f-strings preferred over `.format()` or `%`.
