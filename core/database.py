"""
SQLite persistence for the trading terminal.

Tables:
  - snapshots: periodic state captures (signals, positions, PnL)
  - config_changes: audit log for AI-driven config edits
  - watchlist_log: tracks AI additions/removals from watchlists
  - chat_history: persists chat messages across sessions
  - ai_memory: persistent facts about user preferences and trading behaviour
  - prediction_log: tracks predictions vs actual outcomes for accuracy measurement
  - agent_memory: key-value store the AI agent uses as its scratchpad
  - agent_journal: append-only log of agent iterations, tool calls, and decisions
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
        self._apply_migrations()

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
                    account_json TEXT,
                    asset_class TEXT DEFAULT 'stocks'
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
                    resolved_at TEXT,
                    asset_class TEXT DEFAULT 'stocks'
                );
                CREATE INDEX IF NOT EXISTS idx_pred_ticker ON prediction_log(ticker);
                CREATE INDEX IF NOT EXISTS idx_pred_source ON prediction_log(source);
                CREATE INDEX IF NOT EXISTS idx_pred_resolved ON prediction_log(resolved_at);

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    tickers TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    n_folds INTEGER,
                    duration_seconds REAL,
                    config_json TEXT,
                    total_return_pct REAL,
                    annualised_return_pct REAL,
                    sharpe_ratio REAL,
                    sortino_ratio REAL,
                    calmar_ratio REAL,
                    max_drawdown_pct REAL,
                    total_trades INTEGER,
                    win_rate REAL,
                    profit_factor REAL,
                    signal_accuracy REAL,
                    signal_precision REAL,
                    signal_recall REAL,
                    avg_win_pct REAL,
                    avg_loss_pct REAL,
                    best_trade_pct REAL,
                    worst_trade_pct REAL,
                    avg_hold_days REAL,
                    use_mirofish INTEGER DEFAULT 0,
                    equity_curve_json TEXT,
                    per_source_json TEXT
                );

                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES backtest_runs(id),
                    ticker TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    exit_date TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    quantity REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    hold_days INTEGER,
                    exit_reason TEXT,
                    signal_prob REAL
                );
                CREATE INDEX IF NOT EXISTS idx_bt_trades_run ON backtest_trades(run_id);
                CREATE INDEX IF NOT EXISTS idx_bt_trades_ticker ON backtest_trades(ticker);

                CREATE TABLE IF NOT EXISTS backtest_folds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES backtest_runs(id),
                    fold_id INTEGER NOT NULL,
                    train_start TEXT,
                    train_end TEXT,
                    test_start TEXT,
                    test_end TEXT,
                    accuracy REAL,
                    precision_val REAL,
                    recall_val REAL,
                    n_predictions INTEGER,
                    n_trades INTEGER,
                    total_pnl REAL
                );
                CREATE INDEX IF NOT EXISTS idx_bt_folds_run ON backtest_folds(run_id);

                CREATE TABLE IF NOT EXISTS position_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    opened_at TEXT DEFAULT (datetime('now')),
                    entry_reason TEXT,
                    strategy_profile TEXT,
                    regime_at_entry TEXT,
                    intended_hold TEXT,
                    entry_signal_prob REAL,
                    entry_consensus_pct REAL,
                    special_instructions TEXT,
                    exit_reason TEXT,
                    closed_at TEXT,
                    pnl_realized REAL,
                    is_open INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_pn_ticker ON position_notes(ticker);
                CREATE INDEX IF NOT EXISTS idx_pn_open ON position_notes(is_open);

                CREATE TABLE IF NOT EXISTS agent_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS agent_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    iteration_id TEXT,
                    kind TEXT NOT NULL,
                    tool TEXT,
                    payload TEXT,
                    tags TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_aj_ts ON agent_journal(timestamp);
                CREATE INDEX IF NOT EXISTS idx_aj_kind ON agent_journal(kind);
                CREATE INDEX IF NOT EXISTS idx_aj_iter ON agent_journal(iteration_id);

                -- Scraped items: news headlines + social posts from the
                -- background scraper runner. Tools read from this table
                -- rather than hitting sources live on every agent call.
                CREATE TABLE IF NOT EXISTS scraper_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at TEXT DEFAULT (datetime('now')),
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ticker TEXT,
                    title TEXT NOT NULL,
                    url TEXT,
                    ts TEXT,
                    summary TEXT,
                    meta_json TEXT,
                    sentiment_score REAL,
                    sentiment_label TEXT,
                    UNIQUE(source, url, title)
                );
                CREATE INDEX IF NOT EXISTS idx_sc_fetched ON scraper_items(fetched_at);
                CREATE INDEX IF NOT EXISTS idx_sc_ticker ON scraper_items(ticker);
                CREATE INDEX IF NOT EXISTS idx_sc_source ON scraper_items(source);
                CREATE INDEX IF NOT EXISTS idx_sc_kind ON scraper_items(kind);

                -- Research swarm: task queue, structured findings, goals
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    ticker TEXT,
                    parameters TEXT,
                    goal_id INTEGER,
                    priority INTEGER NOT NULL DEFAULT 5,
                    assigned_worker TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_rt_status ON research_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_rt_role ON research_tasks(role);
                CREATE INDEX IF NOT EXISTS idx_rt_priority ON research_tasks(priority);

                CREATE TABLE IF NOT EXISTS research_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    role TEXT NOT NULL,
                    ticker TEXT,
                    finding_type TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    detail TEXT,
                    confidence_pct INTEGER NOT NULL DEFAULT 50,
                    source TEXT,
                    methodology TEXT,
                    evidence_json TEXT,
                    acted_on INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_rf_ticker ON research_findings(ticker);
                CREATE INDEX IF NOT EXISTS idx_rf_confidence ON research_findings(confidence_pct);
                CREATE INDEX IF NOT EXISTS idx_rf_created ON research_findings(created_at);
                CREATE INDEX IF NOT EXISTS idx_rf_type ON research_findings(finding_type);

                CREATE TABLE IF NOT EXISTS research_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER NOT NULL DEFAULT 5,
                    created_by TEXT,
                    target_roles TEXT,
                    deadline_at TEXT,
                    findings_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT
                );
            """)

    # ── Migrations ─────────────────────────────────────────────────────

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        """Check whether *column* already exists on *table*."""
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cursor.fetchall())

    def _apply_migrations(self) -> None:
        """Add columns that may be missing from databases created before
        the multi-asset-class update."""
        with sqlite3.connect(self.db_path) as conn:
            if not self._column_exists(conn, "snapshots", "asset_class"):
                conn.execute(
                    "ALTER TABLE snapshots ADD COLUMN asset_class TEXT DEFAULT 'stocks'"
                )
            if not self._column_exists(conn, "prediction_log", "asset_class"):
                conn.execute(
                    "ALTER TABLE prediction_log ADD COLUMN asset_class TEXT DEFAULT 'stocks'"
                )
            # Per-item sentiment scoring on scraped news/social items — added
            # alongside the VADER-based scoring step in the scraper runner.
            if not self._column_exists(conn, "scraper_items", "sentiment_score"):
                conn.execute(
                    "ALTER TABLE scraper_items ADD COLUMN sentiment_score REAL"
                )
            if not self._column_exists(conn, "scraper_items", "sentiment_label"):
                conn.execute(
                    "ALTER TABLE scraper_items ADD COLUMN sentiment_label TEXT"
                )

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

    def save_snapshot(self, state: Any, asset_class: str = "stocks") -> None:
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
                "positions_json, news_json, account_json, asset_class) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (date_str, state.mode,
                 state.account_info.get("total", 0.0) if state.account_info else 0.0,
                 state.unrealised_pnl, signals_json, positions_json, news_json,
                 account_json, asset_class),
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

    def log_prediction(
        self, ticker: str, source: str, probability: float, signal: str,
        asset_class: str = "stocks",
    ) -> None:
        """Insert an unresolved prediction."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO prediction_log "
                "(ticker, source, predicted_probability, predicted_signal, asset_class) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticker, source, probability, signal, asset_class),
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

    # ── Backtest persistence ──────────────────────────────────────────

    def save_backtest(self, result: Any) -> int:
        """Persist a BacktestResult to the database.

        Returns the run_id for the saved backtest.
        """
        from dataclasses import asdict

        config = result.config
        metrics = result.metrics

        config_json = json.dumps(asdict(config), default=str)
        tickers_str = ",".join(config.tickers)

        equity_json = ""
        per_source_json = ""
        if metrics:
            equity_json = json.dumps({
                "equity": metrics.equity_curve,
                "dates": metrics.equity_dates,
                "drawdown": metrics.drawdown_curve,
            })
            per_source_json = json.dumps(metrics.per_source_accuracy)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO backtest_runs (
                    start_date, end_date, tickers, mode, n_folds,
                    duration_seconds, config_json,
                    total_return_pct, annualised_return_pct,
                    sharpe_ratio, sortino_ratio, calmar_ratio,
                    max_drawdown_pct, total_trades, win_rate,
                    profit_factor, signal_accuracy, signal_precision,
                    signal_recall, avg_win_pct, avg_loss_pct,
                    best_trade_pct, worst_trade_pct, avg_hold_days,
                    use_mirofish, equity_curve_json, per_source_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )""",
                (
                    config.start_date, config.end_date, tickers_str,
                    config.mode, len(result.folds),
                    result.total_duration_seconds, config_json,
                    metrics.total_return_pct if metrics else None,
                    metrics.annualised_return_pct if metrics else None,
                    metrics.sharpe_ratio if metrics else None,
                    metrics.sortino_ratio if metrics else None,
                    metrics.calmar_ratio if metrics else None,
                    metrics.max_drawdown_pct if metrics else None,
                    metrics.total_trades if metrics else 0,
                    metrics.win_rate if metrics else None,
                    metrics.profit_factor if metrics else None,
                    metrics.signal_accuracy if metrics else None,
                    metrics.signal_precision if metrics else None,
                    metrics.signal_recall if metrics else None,
                    metrics.avg_win_pct if metrics else None,
                    metrics.avg_loss_pct if metrics else None,
                    metrics.best_trade_pct if metrics else None,
                    metrics.worst_trade_pct if metrics else None,
                    metrics.avg_hold_days if metrics else None,
                    1 if config.use_mirofish else 0,
                    equity_json, per_source_json,
                ),
            )
            run_id = cursor.lastrowid

            # Save individual trades
            for fold in result.folds:
                for trade in fold.trades:
                    conn.execute(
                        """INSERT INTO backtest_trades (
                            run_id, ticker, entry_date, exit_date,
                            entry_price, exit_price, quantity,
                            pnl, pnl_pct, hold_days, exit_reason, signal_prob
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id, trade.ticker,
                            str(trade.entry_date), str(trade.exit_date),
                            trade.entry_price, trade.exit_price,
                            trade.quantity, trade.pnl, trade.pnl_pct,
                            trade.hold_days, trade.exit_reason,
                            trade.signal_prob,
                        ),
                    )

            # Save fold summaries
            for fold in result.folds:
                s = fold.split
                conn.execute(
                    """INSERT INTO backtest_folds (
                        run_id, fold_id, train_start, train_end,
                        test_start, test_end, accuracy, precision_val,
                        recall_val, n_predictions, n_trades, total_pnl
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, fold.fold_id,
                        str(s.train_start), str(s.train_end),
                        str(s.test_start), str(s.test_end),
                        fold.accuracy, fold.precision, fold.recall,
                        fold.n_predictions, len(fold.trades),
                        sum(t.pnl for t in fold.trades),
                    ),
                )

        return run_id

    def get_backtest_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent backtest runs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, timestamp, tickers, mode, n_folds,
                    duration_seconds, sharpe_ratio, win_rate,
                    total_return_pct, max_drawdown_pct, total_trades,
                    signal_accuracy, use_mirofish
                FROM backtest_runs ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Position notes ("patient chart") ─────────────────────────────

    def save_position_note(
        self,
        ticker: str,
        entry_reason: str = "",
        strategy_profile: str = "",
        regime_at_entry: str = "",
        intended_hold: str = "",
        entry_signal_prob: float = 0.0,
        entry_consensus_pct: float = 0.0,
        special_instructions: str = "",
    ) -> int:
        """Record context for a newly opened position."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO position_notes
                   (ticker, entry_reason, strategy_profile, regime_at_entry,
                    intended_hold, entry_signal_prob, entry_consensus_pct,
                    special_instructions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker, entry_reason, strategy_profile, regime_at_entry,
                 intended_hold, entry_signal_prob, entry_consensus_pct,
                 special_instructions),
            )
            return cursor.lastrowid or 0

    def close_position_note(
        self,
        ticker: str,
        exit_reason: str = "",
        pnl_realized: float = 0.0,
    ) -> None:
        """Mark the most recent open note for *ticker* as closed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE position_notes
                   SET is_open = 0, closed_at = datetime('now'),
                       exit_reason = ?, pnl_realized = ?
                   WHERE ticker = ? AND is_open = 1""",
                (exit_reason, pnl_realized, ticker),
            )

    def get_open_position_notes(self) -> Dict[str, Dict[str, Any]]:
        """Return open position notes keyed by ticker."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM position_notes WHERE is_open = 1
                   ORDER BY opened_at DESC""",
            ).fetchall()
        notes: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            notes[r["ticker"]] = dict(r)
        return notes

    # ── Scraped items (Phase 5) ────────────────────────────────────────

    def save_scraper_items(self, items: List[Dict[str, Any]]) -> int:
        """Bulk-insert scraped items. Duplicates (source+url+title) are
        silently skipped via ``INSERT OR IGNORE``. Returns the number of
        *new* rows actually inserted.
        """
        if not items:
            return 0

        rows = []
        for it in items:
            meta_json = it.get("meta_json")
            if meta_json is None and it.get("meta") is not None:
                meta_json = json.dumps(it["meta"], default=str)
            rows.append((
                it.get("source"),
                it.get("kind"),
                it.get("ticker"),
                it.get("title"),
                it.get("url"),
                it.get("ts"),
                it.get("summary", ""),
                meta_json,
                it.get("sentiment_score"),
                it.get("sentiment_label"),
            ))

        with sqlite3.connect(self.db_path) as conn:
            before = conn.execute("SELECT COUNT(*) FROM scraper_items").fetchone()[0]
            conn.executemany(
                "INSERT OR IGNORE INTO scraper_items "
                "(source, kind, ticker, title, url, ts, summary, meta_json, "
                "sentiment_score, sentiment_label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            after = conn.execute("SELECT COUNT(*) FROM scraper_items").fetchone()[0]
        return after - before

    def get_scraper_items(
        self,
        *,
        kinds: Optional[List[str]] = None,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 1440,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return scraped items newer than *since_minutes*, filtered by
        kind and ticker. Most-recent first.
        """
        where: List[str] = ["fetched_at >= datetime('now', ?)"]
        params: List[Any] = [f"-{int(since_minutes)} minutes"]

        if kinds:
            placeholders = ",".join("?" * len(kinds))
            where.append(f"kind IN ({placeholders})")
            params.extend(kinds)

        if tickers:
            # Match either items tagged with the ticker or items whose
            # title contains the ticker as a token — so market-wide
            # feeds (BBC, financial news feeds, YouTube) still surface relevant
            # hits for the agent's watchlist.
            ticker_clauses: List[str] = []
            for t in tickers:
                clean = (t or "").split("_")[0].upper()
                if not clean:
                    continue
                ticker_clauses.append("ticker = ?")
                params.append(clean)
                ticker_clauses.append("UPPER(title) LIKE ?")
                params.append(f"%{clean}%")
            if ticker_clauses:
                where.append("(" + " OR ".join(ticker_clauses) + ")")

        sql = (
            "SELECT id, fetched_at, source, kind, ticker, title, url, ts, "
            "summary, meta_json, sentiment_score, sentiment_label "
            "FROM scraper_items "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY COALESCE(ts, fetched_at) DESC LIMIT ?"
        )
        params.append(int(limit))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()

        items: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            meta_json = d.pop("meta_json", None)
            try:
                d["meta"] = json.loads(meta_json) if meta_json else {}
            except (ValueError, TypeError):
                d["meta"] = {}
            items.append(d)
        return items

    def get_ticker_sentiment(
        self,
        tickers: List[str],
        since_minutes: int = 240,
    ) -> Dict[str, Dict[str, Any]]:
        """Return average VADER sentiment per ticker from recent scraper items.

        The watchlist passes T212 symbols (``SHELl_EQ``, ``RRl_EQ``) while
        scrapers store whatever form they query with — usually the plain
        ``split("_")[0].upper()`` form, but sometimes the yfinance form
        (``RR.L``). So we match every plausible variant against both the
        ``ticker`` column and the article title.
        """
        if not tickers:
            return {}

        try:
            from core.data_loader import _clean_ticker as _yf_clean
        except Exception:
            _yf_clean = None

        result: Dict[str, Dict[str, Any]] = {}
        with sqlite3.connect(self.db_path) as conn:
            for raw_ticker in tickers:
                variants: set[str] = set()
                simple = (raw_ticker or "").split("_")[0].upper()
                if simple:
                    variants.add(simple)
                if _yf_clean is not None:
                    try:
                        yf = _yf_clean(raw_ticker)
                    except Exception:
                        yf = ""
                    if yf:
                        variants.add(yf.upper())
                        variants.add(yf.split(".")[0].upper())
                variants.discard("")
                if not variants:
                    continue

                # Ticker column match is precise — scrapers store the symbol
                # they queried with. Title match is a word-boundary fallback
                # for market-wide items (BBC, Reddit) that don't tag tickers.
                # We use several LIKE variants to catch start-of-title,
                # end-of-title, and parens-wrapped mentions (e.g.
                # "Nvidia (NVDA) soars") without the heavy false-positive
                # rate of an unanchored ``%TICKER%``.
                clauses: List[str] = []
                params: List[Any] = [f"-{int(since_minutes)} minutes"]
                for v in variants:
                    clauses.append("ticker = ?")
                    params.append(v)
                for v in variants:
                    if len(v) < 2:
                        continue
                    for pat in (f"% {v} %", f"{v} %", f"% {v}", f"%({v})%", f"%:{v})%", f"%:{v} %"):
                        clauses.append("UPPER(title) LIKE ?")
                        params.append(pat)

                sql = (
                    "SELECT sentiment_score FROM scraper_items "
                    "WHERE fetched_at >= datetime('now', ?) "
                    "AND sentiment_score IS NOT NULL "
                    "AND (" + " OR ".join(clauses) + ")"
                )
                rows = conn.execute(sql, params).fetchall()
                scores = [r[0] for r in rows if r[0] is not None]
                if scores:
                    result[raw_ticker] = {
                        "sentiment_score": sum(scores) / len(scores),
                        "article_count": len(scores),
                    }
        return result

    def purge_old_scraper_items(self, keep_days: int = 7) -> int:
        """Delete scraper items older than *keep_days*. Returns deleted count."""
        with sqlite3.connect(self.db_path) as conn:
            before = conn.execute("SELECT COUNT(*) FROM scraper_items").fetchone()[0]
            conn.execute(
                "DELETE FROM scraper_items WHERE fetched_at < datetime('now', ?)",
                (f"-{int(keep_days)} days",),
            )
            after = conn.execute("SELECT COUNT(*) FROM scraper_items").fetchone()[0]
        return before - after

    # ── Research swarm ────────────────────────────────────────────────

    def insert_research_task(
        self,
        role: str,
        priority: int = 5,
        ticker: Optional[str] = None,
        parameters: Optional[str] = None,
        goal_id: Optional[int] = None,
    ) -> int:
        """Insert a new research task into the queue and return its id.

        Args:
            role: The analyst role responsible for this task.
            priority: Scheduling priority — lower numbers run first.
            ticker: Optional equity ticker this task relates to.
            parameters: Optional JSON-encoded task parameters.
            goal_id: Optional foreign key to a research_goals row.

        Returns:
            The auto-assigned task id.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO research_tasks (role, priority, ticker, parameters, goal_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (role, priority, ticker, parameters, goal_id),
            )
            return cursor.lastrowid or 0

    def claim_research_task(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim the highest-priority pending task for *worker_id*.

        Uses ``BEGIN IMMEDIATE`` to prevent two workers racing for the same row.
        Tasks are ordered by priority ASC (lower = higher priority), then
        created_at ASC so older tasks of equal priority run first.

        Args:
            worker_id: Unique identifier for the claiming worker process.

        Returns:
            The claimed task row as a dict, or ``None`` if the queue is empty.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM research_tasks "
                "WHERE status = 'pending' "
                "ORDER BY priority ASC, created_at ASC "
                "LIMIT 1",
            ).fetchone()
            if row is None:
                return None
            task_id = row["id"]
            conn.execute(
                "UPDATE research_tasks "
                "SET status = 'running', assigned_worker = ?, started_at = datetime('now') "
                "WHERE id = ?",
                (worker_id, task_id),
            )
            return dict(row)

    def complete_research_task(
        self,
        task_id: int,
        *,
        error: Optional[str] = None,
    ) -> None:
        """Mark a running task as completed or failed.

        Args:
            task_id: The id of the task to finalise.
            error: If provided, the task is marked ``failed`` with this message;
                otherwise it is marked ``completed``.
        """
        status = "failed" if error else "completed"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks "
                "SET status = ?, completed_at = datetime('now'), error = ? "
                "WHERE id = ?",
                (status, error, task_id),
            )

    def save_research_finding(self, finding: Dict[str, Any]) -> int:
        """Persist a structured research finding and return its id.

        Args:
            finding: Dict with keys matching the research_findings columns.
                Required: ``role``, ``finding_type``, ``headline``.
                Optional: ``task_id``, ``ticker``, ``detail``,
                ``confidence_pct``, ``source``, ``methodology``,
                ``evidence_json``, ``acted_on``.

        Returns:
            The auto-assigned finding id.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO research_findings "
                "(task_id, role, ticker, finding_type, headline, detail, "
                " confidence_pct, source, methodology, evidence_json, acted_on) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    finding.get("task_id"),
                    finding["role"],
                    finding.get("ticker"),
                    finding["finding_type"],
                    finding["headline"],
                    finding.get("detail"),
                    finding.get("confidence_pct", 50),
                    finding.get("source"),
                    finding.get("methodology"),
                    finding.get("evidence_json"),
                    finding.get("acted_on", 0),
                ),
            )
            return cursor.lastrowid or 0

    def get_research_findings(
        self,
        *,
        since_minutes: int = 360,
        min_confidence: int = 0,
        ticker: Optional[str] = None,
        finding_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent findings, newest and most confident first.

        Args:
            since_minutes: Only return findings created within this window.
            min_confidence: Exclude findings below this confidence threshold.
            ticker: Optional filter by ticker symbol.
            finding_type: Optional filter by finding category.
            limit: Maximum number of rows to return.

        Returns:
            List of finding dicts ordered by confidence_pct DESC, created_at DESC.
        """
        where: List[str] = [
            "created_at >= datetime('now', ?)",
            "confidence_pct >= ?",
        ]
        params: List[Any] = [f"-{int(since_minutes)} minutes", min_confidence]

        if ticker is not None:
            where.append("ticker = ?")
            params.append(ticker)

        if finding_type is not None:
            where.append("finding_type = ?")
            params.append(finding_type)

        sql = (
            "SELECT * FROM research_findings "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY confidence_pct DESC, created_at DESC "
            "LIMIT ?"
        )
        params.append(int(limit))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_research_task_stats(self) -> Dict[str, int]:
        """Return a count of research tasks grouped by status.

        Returns:
            Dict mapping status strings to their row counts, e.g.
            ``{"pending": 3, "running": 1, "completed": 12, "failed": 0}``.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM research_tasks GROUP BY status",
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def clear_agent_history(self) -> Dict[str, int]:
        """Wipe every table the agent reads as memory.

        Used by the "Clear all chats & history" action in live mode and
        by the paper-mode teardown path. Leaves scraper_items alone —
        those are market data, not agent state.

        Returns a dict of ``{table: rows_deleted}`` for logging.
        """
        tables = (
            "chat_history",
            "agent_memory",
            "agent_journal",
            "research_findings",
            "research_tasks",
            "research_goals",
            "ai_memory",
        )
        deleted: Dict[str, int] = {}
        with sqlite3.connect(self.db_path) as conn:
            for name in tables:
                try:
                    cur = conn.execute(f"DELETE FROM {name}")
                    deleted[name] = cur.rowcount or 0
                except sqlite3.OperationalError:
                    # Table doesn't exist on this DB — skip quietly.
                    deleted[name] = 0
        return deleted

    def purge_old_research_data(self, keep_days: int = 30) -> None:
        """Delete old findings and terminal tasks beyond the retention window.

        Removes findings older than *keep_days* and completed/failed tasks
        older than *keep_days*.

        Args:
            keep_days: Retention window in calendar days.
        """
        cutoff = f"-{int(keep_days)} days"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM research_findings WHERE created_at < datetime('now', ?)",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM research_tasks "
                "WHERE status IN ('completed', 'failed') "
                "AND completed_at < datetime('now', ?)",
                (cutoff,),
            )

    def insert_research_goal(
        self,
        goal: str,
        priority: int = 5,
        created_by: str = "supervisor",
        target_roles: Optional[str] = None,
        deadline_at: Optional[str] = None,
    ) -> int:
        """Insert a new research goal and return its id.

        Args:
            goal: Plain-text description of what the swarm should investigate.
            priority: Scheduling priority for tasks spawned under this goal.
            created_by: Identifier of the entity that created the goal.
            target_roles: Optional comma-separated list of roles to assign.
            deadline_at: Optional ISO-8601 deadline string.

        Returns:
            The auto-assigned goal id.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO research_goals "
                "(goal, priority, created_by, target_roles, deadline_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (goal, priority, created_by, target_roles, deadline_at),
            )
            return cursor.lastrowid or 0

    def get_active_research_goals(self) -> List[Dict[str, Any]]:
        """Return all goals whose status is ``'active'``, ordered by priority.

        Returns:
            List of goal dicts ordered by priority ASC, created_at ASC.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM research_goals "
                "WHERE status = 'active' "
                "ORDER BY priority ASC, created_at ASC",
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        pass  # connections are per-call via context manager
