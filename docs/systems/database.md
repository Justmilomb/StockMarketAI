# Database (HistoryManager)

SQLite persistence layer for the trading terminal. Stores all stateful data that must survive session restarts.

## Purpose

Provides durable storage for the terminal's operational history: periodic state snapshots, AI self-tuning audit trail, watchlist changes, interactive chat, AI memory facts, prediction accuracy tracking, and backtest run records.

## Tables

| Table | Purpose |
|-------|---------|
| `snapshots` | Periodic state captures: signals, positions, PnL, account, news JSON per refresh cycle |
| `config_changes` | Audit log for AI-driven config edits (field, old value, new value, reason) |
| `watchlist_log` | Tracks AI additions/removals from watchlists (action, ticker, watchlist, reason) |
| `chat_history` | Persists chat messages across sessions (role, text) |
| `ai_memory` | Persistent facts extracted from chat (category, fact, confidence, source) |
| `prediction_log` | Tracks predictions vs actual outcomes for accuracy measurement (ticker, source, predicted_probability, actual_direction, actual_return) |
| `backtest_runs` | Full backtest metadata (dates, tickers, metrics, equity curve JSON) |
| `backtest_trades` | Individual trade records linked to a backtest run |

## Public API

```python
class HistoryManager:
    def __init__(db_path: str = "data/terminal_history.db")

    # Snapshots
    def save_snapshot(date, mode, equity, pnl, signals, positions, news, account, asset_class) -> None
    def get_recent_snapshots(limit=50) -> List[Dict]

    # Config changes
    def log_config_change(changed_by, field, old_value, new_value, reason) -> None
    def get_config_changes(limit=50) -> List[Dict]

    # Watchlist
    def log_watchlist_change(action, ticker, watchlist, reason) -> None

    # Chat
    def save_chat_message(role, text) -> None
    def get_chat_history(limit=100) -> List[Dict]

    # AI memory
    def save_memory_fact(category, fact, confidence, source) -> None
    def get_memory_facts(category=None) -> List[Dict]

    # Predictions
    def log_prediction(ticker, source, predicted_probability, predicted_signal, asset_class) -> None
    def resolve_predictions(ticker, actual_direction, actual_return) -> None

    # Backtests
    def save_backtest_run(config, metrics, equity_curve, trades) -> int
    def get_backtest_runs(limit=20) -> List[Dict]
```

## Notes

- Database file is created at `data/terminal_history.db` (relative to project root)
- Schema is initialised on first `__init__` call; `_apply_migrations()` handles schema evolution without dropping tables
- All tables use `INTEGER PRIMARY KEY AUTOINCREMENT` for safe concurrent writes (though the terminal is single-process)
- Indexes on `date`, `ticker`, and `source` columns for fast lookups

## Dependencies

- `sqlite3` (stdlib)
- No ORM — raw SQL via `sqlite3.connect()`
