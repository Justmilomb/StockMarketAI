"""SwarmCoordinator — manages the 20-agent research worker pool.

Runs as a daemon thread alongside ScraperRunner. On every tick:
1. Collect finished workers
2. Generate tasks for due roles
3. Assign tasks to idle workers
4. Periodic housekeeping (purge old data)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.agent.research_queue import ResearchQueue
from core.agent.research_roles import ALL_ROLES, get_role

logger = logging.getLogger(__name__)

TICK_SECONDS: float = 5.0
DEFAULT_MAX_WORKERS: int = 4
RETENTION_DAYS: int = 30

# Purge old data once per hour (every N ticks).
_PURGE_INTERVAL_TICKS: int = int(3600 / TICK_SECONDS)


class SwarmCoordinator(threading.Thread):
    """Daemon thread that schedules and manages the 20-role research worker pool.

    On every tick the coordinator:
    - Reaps any QThread workers that have finished.
    - Generates new DB tasks for roles whose cadence has elapsed.
    - Claims pending tasks from the DB and spawns fresh workers for idle slots.
    - Periodically purges old research data beyond the retention window.
    """

    def __init__(
        self,
        config_path: Path | str,
        broker_service: Any,
        db_path: str,
        paper_mode: bool,
        watchlist_provider: Optional[Callable[[], List[str]]] = None,
    ) -> None:
        super().__init__(daemon=True, name="swarm-coordinator")
        self._config_path = Path(config_path)
        self._broker_service = broker_service
        self._db_path = db_path
        self._paper_mode = paper_mode
        self._watchlist_provider = watchlist_provider

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._queue = ResearchQueue()
        self._workers: Dict[str, Any] = {}
        self._max_workers: int = self._read_max_workers()
        self._total_tasks_run: int = 0
        self._tick_count: int = 0

    # ── configuration ────────────────────────────────────────────────

    def _read_max_workers(self) -> int:
        """Read swarm.max_concurrent_workers from config.json, defaulting to 4."""
        try:
            with self._config_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            return int(cfg.get("swarm", {}).get("max_concurrent_workers", DEFAULT_MAX_WORKERS))
        except Exception:
            logger.debug("Could not read max_concurrent_workers from config; using default")
            return DEFAULT_MAX_WORKERS

    # ── thread entry point ────────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — threading.Thread API
        logger.info("[swarm] coordinator started (max_workers=%d)", self._max_workers)
        from database import HistoryManager  # lazy import — keeps boot path light

        db = HistoryManager(self._db_path)

        while not self._stop_event.is_set():
            try:
                self._tick(db)
            except Exception:
                logger.exception("[swarm] tick error")
            self._stop_event.wait(timeout=TICK_SECONDS)

        self._shutdown_workers()
        logger.info("[swarm] coordinator stopped")

    def stop(self) -> None:
        """Signal the coordinator to stop after the current tick."""
        self._stop_event.set()

    # ── tick ──────────────────────────────────────────────────────────

    def _tick(self, db: Any) -> None:
        """One coordinator tick: reap, generate, assign, housekeep."""
        self._tick_count += 1
        self._collect_finished()
        self._generate_tasks(db)
        self._assign_tasks(db)

        # Purge old data once per hour.
        if self._tick_count % _PURGE_INTERVAL_TICKS == 0:
            try:
                db.purge_old_research_data(keep_days=RETENTION_DAYS)
                logger.debug("[swarm] purged research data older than %d days", RETENTION_DAYS)
            except Exception:
                logger.exception("[swarm] purge failed")

    # ── task generation ───────────────────────────────────────────────

    def _generate_tasks(self, db: Any) -> None:
        """Insert DB tasks for every role whose cadence has elapsed.

        Skips generation entirely when the pending queue is already large
        (> 40 rows) to avoid runaway growth between worker ticks.
        """
        # Guard: skip if the queue already has plenty of work waiting.
        try:
            stats = db.get_research_task_stats()
            pending = stats.get("pending", 0)
            if pending > 40:
                logger.debug("[swarm] queue depth %d > 40, skipping generation", pending)
                return
        except Exception:
            logger.exception("[swarm] could not read task stats before generation")
            return

        due_roles = self._queue.get_due_roles()
        watchlist = self._watchlist_provider() if self._watchlist_provider else []

        for role in due_roles:
            try:
                # Priority: quick roles = 3, deep roles = 7.
                priority = 3 if role.tier == "quick" else 7

                # Pass watchlist tickers as a comma-separated string when the
                # role operates on the user's watchlist; leave ticker None
                # otherwise so the worker searches the broad market.
                ticker: Optional[str] = None
                if role.default_tickers and watchlist:
                    ticker = ",".join(watchlist)

                db.insert_research_task(
                    role=role.role_id,
                    priority=priority,
                    ticker=ticker,
                )
                self._queue.mark_fired(role.role_id)
                logger.debug("[swarm] inserted task for role=%s", role.role_id)
            except Exception:
                logger.exception("[swarm] failed to insert task for role=%s", role.role_id)

    # ── task assignment ───────────────────────────────────────────────

    def _assign_tasks(self, db: Any) -> None:
        """Claim pending tasks and spawn workers for each idle slot."""
        with self._lock:
            active_count = len(self._workers)

        idle_slots = self._max_workers - active_count
        if idle_slots <= 0:
            return

        for _ in range(idle_slots):
            try:
                task = db.claim_research_task(worker_id=f"swarm-{uuid.uuid4().hex[:8]}")
                if task is None:
                    break  # Queue is empty — no more work to assign.

                role = get_role(task["role"])
                if role is None:
                    logger.warning("[swarm] unknown role '%s' in task %s", task["role"], task["id"])
                    continue

                self._spawn_worker(task, role)
            except Exception:
                logger.exception("[swarm] failed to assign task")

    # ── worker lifecycle ──────────────────────────────────────────────

    def _spawn_worker(self, task: Dict[str, Any], role: Any) -> None:
        """Create and start a ResearchWorker for *task*."""
        from core.agent.research_worker import ResearchWorker  # lazy import

        worker_id = f"rw-{uuid.uuid4().hex[:6]}"
        watchlist = self._watchlist_provider() if self._watchlist_provider else None

        worker = ResearchWorker(
            worker_id=worker_id,
            task=task,
            role=role,
            config_path=self._config_path,
            broker_service=self._broker_service,
            db_path=self._db_path,
            paper_mode=self._paper_mode,
            watchlist=watchlist,
        )

        with self._lock:
            self._workers[worker_id] = worker
            self._total_tasks_run += 1

        worker.start()
        logger.debug(
            "[swarm] spawned worker %s for role=%s task=%s",
            worker_id, role.role_id, task["id"],
        )

    def _collect_finished(self) -> None:
        """Remove workers that have completed their QThread run."""
        finished: List[str] = []
        with self._lock:
            for wid, w in self._workers.items():
                if not w.isRunning():
                    finished.append(wid)

        for wid in finished:
            with self._lock:
                worker = self._workers.pop(wid, None)
            if worker is not None:
                try:
                    worker.wait(50)
                    worker.deleteLater()
                except Exception:
                    logger.debug("[swarm] cleanup failed for worker %s", wid)
                logger.debug("[swarm] reaped finished worker %s", wid)

    def _shutdown_workers(self) -> None:
        """Request stop on all active workers and wait up to 30 s total."""
        with self._lock:
            workers = dict(self._workers)

        for worker in workers.values():
            try:
                worker.request_stop()
            except Exception:
                pass

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            with self._lock:
                still_running = [w for w in self._workers.values() if w.isRunning()]
            if not still_running:
                break
            time.sleep(0.2)

        # Final reap — anything still running is left to the OS.
        self._collect_finished()
        logger.info("[swarm] all workers stopped (or timed out)")

    # ── status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a lightweight status snapshot safe to call from any thread."""
        with self._lock:
            workers_snapshot = dict(self._workers)

        active_roles: List[str] = []
        for worker in workers_snapshot.values():
            try:
                role_id = worker._role.role_id  # noqa: SLF001 — internal access
                active_roles.append(role_id)
            except Exception:
                pass

        return {
            "running": self.is_alive(),
            "active_workers": len(workers_snapshot),
            "active_roles": active_roles,
            "max_workers": self._max_workers,
            "total_tasks_run": self._total_tasks_run,
        }
