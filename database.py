"""
SQLite persistence for the trading terminal.

Tables:
  - snapshots: periodic state captures (signals, positions, PnL)
  - config_changes: audit log for AI-driven config edits
  - watchlist_log: tracks AI additions/removals from watchlists
  - chat_history: persists chat messages across sessions
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
                                "p_up_gemini", "p_up_final", "reason"]
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

    def close(self) -> None:
        pass  # connections are per-call via context manager
