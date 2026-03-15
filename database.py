import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

class HistoryManager:
    """
    Manages historical persistence for the trading terminal using SQLite.
    Stores daily snapshots of account state, signals, and news.
    """
    def __init__(self, db_path: str = "data/terminal_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
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
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON snapshots(date)")

    def save_snapshot(self, state: Any):
        """Save a snapshot of the current AppState."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        
        # Serialize complex data
        signals_json = ""
        if state.signals is not None:
            signals_json = state.signals.to_json()
            
        positions_json = json.dumps(state.positions)
        news_json = json.dumps(state.news_sentiment)
        account_json = json.dumps(state.account_info)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO snapshots (date, mode, equity, pnl, signals_json, positions_json, news_json, account_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str,
                state.mode,
                state.account_info.get("total", 0.0),
                state.unrealised_pnl,
                signals_json,
                positions_json,
                news_json,
                account_json
            ))

    def get_snapshot(self, date_str: str) -> Optional[Dict]:
        """Retrieve a snapshot for a specific date."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM snapshots WHERE date = ? ORDER BY timestamp DESC LIMIT 1",
                (date_str,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def get_recent_dates(self, limit: int = 10) -> List[str]:
        """List dates with available history."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT DISTINCT date FROM snapshots ORDER BY date DESC LIMIT ?",
                (limit,)
            )
            return [r[0] for r in cursor.fetchall()]
