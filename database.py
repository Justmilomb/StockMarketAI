"""
SQLite persistence for the trading terminal.

Tables:
  - snapshots: periodic state captures (signals, positions, PnL)
  - config_changes: audit log for AI-driven config edits
  - watchlist_log: tracks AI additions/removals from watchlists
  - chat_history: persists chat messages across sessions
  - ai_memory: persistent facts about user preferences and trading behaviour
  - prediction_log: tracks predictions vs actual outcomes for accuracy measurement
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class HistoryManager:
    """
    Manages historical persistence for the trading terminal using SQLite.
    Stores snapshots of account state, signals, config changes, and watchlist actions.
    """

    def __init__(self, db_path: str = "data/terminal_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    date TEXT,
                    mode TEXT,
                    equity REAL,
                    pnl REAL,
                    signals_json TEXT,
                    positions_json TEXT,
                    news_json TEXT,
                    account_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_date ON snapshots(date);

                CREATE TABLE IF NOT EXISTS config_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT DEFAULT (datetime('now')),
                    changed_by TEXT,
                    field TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS watchlist_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT DEFAULT (datetime('now')),
                    action TEXT,
                    ticker TEXT,
                    watchlist TEXT,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    role TEXT NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    category TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'chat'
                );

                CREATE TABLE IF NOT EXISTS prediction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    ticker TEXT NOT NULL,
                    source TEXT NOT NULL,
                    predicted_probability REAL,
                    predicted_signal TEXT,
                    actual_direction INTEGER,
                    actual_return REAL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pred_ticker ON prediction_log(ticker);
                CREATE INDEX IF NOT EXISTS idx_pred_source ON prediction_log(source);
                CREATE INDEX IF NOT EXISTS idx_pred_resolved ON prediction_log(resolved_at);
            """)

    # ── Serialisation helpers ──────────────────────────────────────────

    @staticmethod
    def _serialize_news(news_sentiment: Dict[str, Any]) -> str:
        """Convert news data (may contain dataclasses) to JSON string."""
        from dataclasses import is_dataclass, asdict
        serializable = {}
        for ticker, nd in news_sentiment.items():
            if is_dataclass(nd):
                d = asdict(nd)
                if d.get("last_updated"):
                    d["last_updated"] = d["last_updated"].isoformat()
                serializable[ticker] = d
            else:
                serializable[ticker] = nd
        return json.dumps(serializable)

    # ── Snapshots ──────────────────────────────────────────────────────

    def save_snapshot(self, state: Any) -> None:
        """Save a point-in-time snapshot of the terminal state."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # Only store essential signal columns to keep the DB lean
        signals_json = ""
        if state.signals is not None and not state.signals.empty:
            cols = [c for c in ["ticker", "prob_up", "signal", "ai_rec", "p_up_sklearn",
                                "p_up_ai", "p_up_final", "reason"]
                    if c in state.signals.columns]
            signals_json = state.signals[cols].head(30).to_json(orient="records")

        positions_json = json.dumps(state.positions[:30])
        news_json = self._serialize_news(state.news_sentiment)
        account_json = json.dumps(state.account_info or {})

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO snapshots (date, mode, equity, pnl, signals_json, "
                "positions_json, news_json, account_json) VALUES (?,?,?,?,?,?,?,?)",
                (date_str, state.mode,
                 state.account_info.get("total", 0.0) if state.account_info else 0.0,
                 state.unrealised_pnl, signals_json, positions_json, news_json, account_json),
            )

    def get_snapshot(self, date_str: str) -> Optional[Dict]:
        """Retrieve the latest snapshot for a given date."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM snapshots WHERE date = ? ORDER BY timestamp DESC LIMIT 1",
                (date_str,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def get_recent_dates(self, limit: int = 10) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM snapshots ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_all_snapshots(self, limit: int = 100) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, mode, equity, pnl FROM snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"date": r[0], "mode": r[1], "equity": r[2], "pnl": r[3]} for r in rows]

    # ── Config Change Audit Log ────────────────────────────────────────

    def log_config_change(
        self, changed_by: str, field: str, old_value: str, new_value: str, reason: str = ""
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO config_changes (changed_by, field, old_value, new_value, reason) "
                "VALUES (?,?,?,?,?)",
                (changed_by, field, old_value, new_value, reason),
            )

    def get_config_changes(self, limit: int = 20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, changed_by, field, old_value, new_value, reason "
                "FROM config_changes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"date": r[0], "changed_by": r[1], "field": r[2],
                     "old_value": r[3], "new_value": r[4], "reason": r[5]} for r in rows]

    # ── Watchlist Log ──────────────────────────────────────────────────

    def log_watchlist_action(
        self, action: str, ticker: str, watchlist: str, reason: str = ""
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO watchlist_log (action, ticker, watchlist, reason) VALUES (?,?,?,?)",
                (action, ticker, watchlist, reason),
            )

    def get_watchlist_log(self, limit: int = 50) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, action, ticker, watchlist, reason "
                "FROM watchlist_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"date": r[0], "action": r[1], "ticker": r[2],
                     "watchlist": r[3], "reason": r[4]} for r in rows]

    # ── Chat History ─────────────────────────────────────────────────

    def save_chat_message(self, role: str, text: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO chat_history (role, text) VALUES (?, ?)",
                (role, text),
            )

    def load_chat_history(self, limit: int = 50) -> List[Dict[str, str]]:
        """Load recent chat messages (oldest first) for session restore."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT role, text FROM ("
                "  SELECT role, text, id FROM chat_history ORDER BY id DESC LIMIT ?"
                ") sub ORDER BY id ASC",
                (limit,),
            ).fetchall()
            return [{"role": r[0], "text": r[1]} for r in rows]

    def clear_old_chat(self, keep_last: int = 200) -> None:
        """Prune chat to prevent unbounded growth."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM chat_history WHERE id NOT IN "
                "(SELECT id FROM chat_history ORDER BY id DESC LIMIT ?)",
                (keep_last,),
            )

    # ── AI Memory ──────────────────────────────────────────────────

    def save_memory_fact(self, category: str, fact: str, confidence: float = 1.0, source: str = "chat") -> None:
        """Store a persistent fact about the user or their trading behaviour."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO ai_memory (category, fact, confidence, source) VALUES (?, ?, ?, ?)",
                (category, fact, confidence, source),
            )

    def get_memory_summary(self, limit: int = 20) -> str:
        """Build a natural language summary of stored memories for AI context."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT category, fact, timestamp FROM ai_memory ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        if not rows:
            return ""
        lines: list[str] = []
        for category, fact, ts in rows:
            lines.append(f"- [{category}] {fact} (recorded: {ts})")
        return "\n".join(lines)

    def clear_old_memories(self, keep_last: int = 50) -> None:
        """Prune old memories to prevent unbounded growth."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM ai_memory WHERE id NOT IN "
                "(SELECT id FROM ai_memory ORDER BY id DESC LIMIT ?)",
                (keep_last,),
            )

    # ── Prediction Log ──────────────────────────────────────────────

    def log_prediction(self, ticker: str, source: str, probability: float, signal: str) -> None:
        """Insert an unresolved prediction."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO prediction_log (ticker, source, predicted_probability, predicted_signal) VALUES (?, ?, ?, ?)",
                (ticker, source, probability, signal),
            )

    def resolve_predictions(self, ticker: str, actual_direction: int, actual_return: float) -> int:
        """Mark all unresolved predictions for a ticker as resolved. Returns count resolved."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE prediction_log SET actual_direction = ?, actual_return = ?, resolved_at = datetime('now') "
                "WHERE ticker = ? AND resolved_at IS NULL",
                (actual_direction, actual_return, ticker),
            )
            return cursor.rowcount

    def get_accuracy_stats(self, source: str = "all", window_days: int = 30) -> Dict[str, Any]:
        """Get accuracy stats for a source over the last N days."""
        with sqlite3.connect(self.db_path) as conn:
            where_clause = "WHERE resolved_at IS NOT NULL AND resolved_at > datetime('now', ?)"
            params: list = [f"-{window_days} days"]
            if source != "all":
                where_clause += " AND source = ?"
                params.append(source)

            row = conn.execute(
                f"SELECT COUNT(*) as total, "
                f"SUM(CASE WHEN (predicted_probability > 0.5 AND actual_direction = 1) "
                f"OR (predicted_probability <= 0.5 AND actual_direction = 0) THEN 1 ELSE 0 END) as correct "
                f"FROM prediction_log {where_clause}",
                params,
            ).fetchone()

            total = row[0] or 0
            correct = row[1] or 0
            return {
                "total": total,
                "correct": correct,
                "hit_rate": correct / total if total > 0 else 0.0,
            }

    def get_unresolved_predictions(self, ticker: str | None = None) -> List[Dict[str, Any]]:
        """Get pending predictions, optionally filtered by ticker."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM prediction_log WHERE resolved_at IS NULL AND ticker = ?",
                    (ticker,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prediction_log WHERE resolved_at IS NULL",
                ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        pass  # connections are per-call via context manager
