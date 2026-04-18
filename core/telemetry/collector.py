"""Local SQLite event store + module-level singleton.

The collector owns one ``telemetry.db`` under ``user_data_dir/data/``.
Every emitted event becomes one row:

    (id, event_type, session_id, machine_id, created_at,
     payload_json, uploaded_at)

``created_at`` is the event timestamp (epoch seconds). ``uploaded_at``
stays NULL until the uploader successfully POSTs the row to the blank
server; the same row is never shipped twice.

Singleton access is via module-level ``init`` / ``emit`` / ``close``.
The collector runs its own background uploader (see :mod:`uploader`)
and flushes pending events when the app shuts down.

Personal data is stripped at the caller's boundary — every hook in
``core/telemetry/hooks.py`` scrubs emails, API keys, names, and T212
account identifiers before calling :func:`emit`. This module treats
every payload as already-anonymous and refuses to introspect contents.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    payload_json TEXT NOT NULL,
    uploaded_at REAL
);
CREATE INDEX IF NOT EXISTS idx_events_uploaded ON events(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
"""


class TelemetryCollector:
    """Thread-safe local event store + uploader controller.

    Construction is cheap: the SQLite file is created on first write.
    Call :meth:`emit` from any thread — writes are serialised with a
    short ``threading.Lock`` and each write is its own tiny
    transaction, so the caller never blocks meaningfully.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        machine_id: str,
        licence_key: str,
        endpoint: str,
        enabled: bool = True,
        max_queue_size: int = 100_000,
    ) -> None:
        self._db_path: Path = Path(db_path)
        self._machine_id: str = machine_id
        self._licence_key: str = licence_key
        self._endpoint: str = endpoint
        self._enabled: bool = bool(enabled)
        self._max_queue_size: int = int(max_queue_size)

        self._session_id: str = uuid.uuid4().hex
        self._lock: threading.Lock = threading.Lock()
        self._uploader: Optional[Any] = None

        if self._enabled:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    # ── public API ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def licence_key(self) -> str:
        return self._licence_key

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Record one event. Never raises."""
        if not self._enabled:
            return
        if not isinstance(event_type, str) or not event_type:
            return
        try:
            row = (
                event_type,
                self._session_id,
                self._machine_id,
                time.time(),
                json.dumps(payload or {}, default=str, ensure_ascii=False),
                None,
            )
        except (TypeError, ValueError) as exc:
            logger.debug("telemetry emit serialise failed for %s: %s", event_type, exc)
            return

        try:
            with self._lock, self._connect() as conn:
                self._enforce_cap(conn)
                conn.execute(
                    "INSERT INTO events(event_type, session_id, machine_id,"
                    " created_at, payload_json, uploaded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    row,
                )
        except sqlite3.Error as exc:
            logger.debug("telemetry emit insert failed: %s", exc)

    def pending(self, limit: int = 500) -> List[Tuple[int, str, str, float, str]]:
        """Return up to ``limit`` un-uploaded events ordered by id."""
        if not self._enabled:
            return []
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "SELECT id, event_type, session_id, created_at, payload_json"
                    " FROM events WHERE uploaded_at IS NULL ORDER BY id ASC LIMIT ?",
                    (int(limit),),
                )
                return list(cur.fetchall())
        except sqlite3.Error as exc:
            logger.debug("telemetry pending read failed: %s", exc)
            return []

    def mark_uploaded(self, ids: List[int]) -> None:
        """Mark a batch of rows as successfully shipped to the server."""
        if not self._enabled or not ids:
            return
        try:
            now = time.time()
            with self._lock, self._connect() as conn:
                conn.executemany(
                    "UPDATE events SET uploaded_at = ? WHERE id = ?",
                    [(now, int(i)) for i in ids],
                )
        except sqlite3.Error as exc:
            logger.debug("telemetry mark_uploaded failed: %s", exc)

    def purge_uploaded(self, older_than_days: int = 30) -> int:
        """Drop already-shipped rows older than ``older_than_days``.

        Keeps the local SQLite file bounded. Rows that are still
        pending (``uploaded_at IS NULL``) are preserved forever.
        """
        if not self._enabled:
            return 0
        cutoff = time.time() - (older_than_days * 86_400)
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM events WHERE uploaded_at IS NOT NULL"
                    " AND uploaded_at < ?",
                    (cutoff,),
                )
                return int(cur.rowcount or 0)
        except sqlite3.Error as exc:
            logger.debug("telemetry purge failed: %s", exc)
            return 0

    def attach_uploader(self, uploader: Any) -> None:
        """Store a reference to the background uploader so ``close`` can join it."""
        self._uploader = uploader

    def flush(self) -> None:
        """Trigger an immediate upload cycle, if an uploader is attached."""
        if self._uploader is not None:
            try:
                self._uploader.request_upload()
            except Exception as exc:
                logger.debug("telemetry flush failed: %s", exc)

    def close(self) -> None:
        """Graceful shutdown: stop the uploader and wait briefly."""
        if self._uploader is not None:
            try:
                self._uploader.stop()
                self._uploader.join(timeout=5.0)
            except Exception as exc:
                logger.debug("telemetry close uploader stop failed: %s", exc)
            self._uploader = None

    # ── internals ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _enforce_cap(self, conn: sqlite3.Connection) -> None:
        """Keep the local queue under ``max_queue_size`` rows.

        When the cap is hit, oldest already-uploaded rows are deleted
        first. If every row is still pending (upload has been failing
        for a long time), we drop the oldest pending rows — the cap is
        a hard ceiling, not a soft hint.
        """
        row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        if not row or row[0] < self._max_queue_size:
            return
        overflow = int(row[0]) - self._max_queue_size + 1
        conn.execute(
            "DELETE FROM events WHERE id IN ("
            " SELECT id FROM events WHERE uploaded_at IS NOT NULL"
            " ORDER BY id ASC LIMIT ?)",
            (overflow,),
        )
        row2 = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        if row2 and row2[0] >= self._max_queue_size:
            conn.execute(
                "DELETE FROM events WHERE id IN ("
                " SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                (overflow,),
            )


# ── Module-level singleton ────────────────────────────────────────────

_INSTANCE: Optional[TelemetryCollector] = None
_INSTANCE_LOCK: threading.Lock = threading.Lock()


def init(
    *,
    db_path: Path,
    machine_id: str,
    licence_key: str,
    endpoint: str,
    enabled: bool = True,
    max_queue_size: int = 100_000,
) -> TelemetryCollector:
    """Initialise the singleton. Safe to call once per process."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is not None:
            return _INSTANCE
        _INSTANCE = TelemetryCollector(
            db_path=db_path,
            machine_id=machine_id,
            licence_key=licence_key,
            endpoint=endpoint,
            enabled=enabled,
            max_queue_size=max_queue_size,
        )
        return _INSTANCE


def get() -> Optional[TelemetryCollector]:
    """Return the singleton, or ``None`` if telemetry was never initialised."""
    return _INSTANCE


def is_enabled() -> bool:
    return _INSTANCE is not None and _INSTANCE.enabled


def session_id() -> str:
    return _INSTANCE.session_id if _INSTANCE is not None else ""


def emit(event_type: str, payload: Dict[str, Any]) -> None:
    """No-op if telemetry isn't initialised or is disabled in config."""
    inst = _INSTANCE
    if inst is None or not inst.enabled:
        return
    inst.emit(event_type, payload)


def flush() -> None:
    inst = _INSTANCE
    if inst is not None:
        inst.flush()


def close() -> None:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            return
        try:
            _INSTANCE.close()
        finally:
            _INSTANCE = None
