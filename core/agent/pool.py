"""AgentPool — one-stop orchestrator for the agent fleet.

The user wants a **hierarchy** of agents, not just one:

* **Supervisor** — the long-running ``AgentRunner`` loop (one at a time).
* **Chat workers** — unbounded (soft-capped) short-lived one-shot agents,
  one per chat message, spawned in their own ``QThread`` and running
  concurrently with the supervisor and with each other.

All agents share the **same brain**:

* same SQLite ``HistoryManager`` → same ``agent_journal`` + ``agent_memory``;
* same ``config.json`` dict;
* **same broker** — one session-wide paper broker when in paper mode, or
  the main live ``BrokerService`` when in live mode. This is critical:
  if every worker built its own ``LogBroker`` they would each see an
  empty paper portfolio and immediately overwrite each other's state.

The pool owns the live / paper broker pair and hands out the right
one via :meth:`get_broker_for_mode`. The supervisor and each chat
worker call that method at construction time and use the result for
their whole iteration.

Soft cap: ``config.agent.max_chat_workers`` (default 5). Additional
chat messages queue in a small FIFO and are drained as workers finish.
No hard ceiling — raise the config key if you want more.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Deque, Dict, Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AgentPool(QObject):
    """Owns the supervisor + chat-worker fleet for one desktop session."""

    # ── UI signals (forwarded from workers) ──────────────────────────
    chat_text = Signal(str, str)                # worker_id, text
    chat_done = Signal(str, str)                # worker_id, summary
    chat_error = Signal(str, str)               # worker_id, error
    chat_tool_use = Signal(dict)
    chat_tool_result = Signal(dict)
    chat_log_line = Signal(str)

    # Lifecycle signals for the caller (MainWindow).
    worker_spawned = Signal(str)                # worker_id
    worker_finished = Signal(str)               # worker_id

    def __init__(
        self,
        config_path: Path | str,
        live_broker_service: Any,
        db_path: str = "data/terminal_history.db",
        force_paper: bool = False,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._config_path: Path = Path(config_path)
        self._live_broker: Any = live_broker_service
        self._db_path: str = db_path
        # When True the pool is locked to paper mode regardless of what
        # config.json says — used by the dedicated paper trading window.
        self._force_paper: bool = force_paper

        # Supervisor is built lazily on first start (keeps boot cheap
        # and lets the app render before the SDK loads).
        self._supervisor: Optional[Any] = None

        # Chat worker fleet.
        self._chat_workers: Dict[str, Any] = {}
        self._chat_queue: Deque[str] = deque()
        self._lock: Lock = Lock()

        # Paper broker is built on demand the first time a paper-mode
        # agent asks for one, then reused for the rest of the session.
        self._paper_broker: Optional[Any] = None

    # ── config helpers ───────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        import json
        with self._config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        # The pool's force_paper flag is the single source of truth for
        # which mode its agents run in. We override agent.paper_mode in
        # both directions so a stale config.json value can never bleed
        # across windows — live pools are always live, paper pools are
        # always paper.
        cfg.setdefault("agent", {})["paper_mode"] = self._force_paper
        return cfg

    def _max_chat_workers(self) -> int:
        try:
            cfg = self._load_config()
            return max(1, int(cfg.get("agent", {}).get("max_chat_workers", 5)))
        except Exception:
            return 5

    # ── broker routing (the shared brain, broker half) ───────────────

    def get_broker_for_mode(self, paper_mode: bool) -> Any:
        """Return the BrokerService every agent should use this iteration.

        One session-wide ``BrokerService`` is built lazily on the first
        paper-mode request and cached for the rest of the session, so
        supervisor + chat workers share one paper portfolio. The
        stocks slot is overridden with a stateful ``PaperBroker`` —
        the stateless ``LogBroker`` that comes from a `"type": "log"`
        config would show every agent an empty portfolio, defeating the
        point of paper trading. Live mode hands back the main
        ``BrokerService`` the desktop app already built at boot.
        """
        if not paper_mode:
            return self._live_broker

        if self._paper_broker is None:
            from pathlib import Path as _Path

            from broker_service import BrokerService
            from paper_broker import PaperBroker

            config = self._load_config()
            paper_config = dict(config)
            paper_config["broker"] = {
                **(config.get("broker", {}) or {}),
                "type": "log",
            }
            paper_config.setdefault("agent", {})
            paper_config["agent"] = {
                **paper_config["agent"],
                "paper_mode": True,
            }
            service = BrokerService(config=paper_config)

            paper_cfg = (config.get("paper_broker") or {})
            state_path = _Path(
                paper_cfg.get("state_path", "data/paper_state.json"),
            )
            audit_path = _Path(
                paper_cfg.get("audit_path", "logs/paper_orders.jsonl"),
            )
            starting_cash = float(paper_cfg.get("starting_cash", 100000.0))
            service.register_broker(
                "stocks",
                PaperBroker(
                    state_path=state_path,
                    audit_path=audit_path,
                    starting_cash=starting_cash,
                ),
            )
            self._paper_broker = service
            logger.info(
                "AgentPool built session-wide paper broker (state=%s)",
                state_path,
            )
        return self._paper_broker

    # ── supervisor lifecycle ─────────────────────────────────────────

    def ensure_supervisor(self) -> Any:
        """Build the AgentRunner on first use, reuse it thereafter."""
        if self._supervisor is None:
            from core.agent.runner import AgentRunner
            self._supervisor = AgentRunner(
                config_path=self._config_path,
                pool=self,
                db_path=self._db_path,
            )
        return self._supervisor

    def start_supervisor(self) -> None:
        sup = self.ensure_supervisor()
        if not sup.isRunning():
            sup.start()

    def stop_supervisor(self) -> None:
        if self._supervisor is not None and self._supervisor.isRunning():
            self._supervisor.request_stop()

    def kill_supervisor(self) -> bool:
        """Hard-stop the supervisor. Returns True if it came down clean."""
        if self._supervisor is None:
            return True
        self._supervisor.request_stop()
        if not self._supervisor.wait(2000):
            try:
                self._supervisor.terminate()
                self._supervisor.wait(1000)
            except Exception:
                return False
        return True

    @property
    def supervisor(self) -> Optional[Any]:
        return self._supervisor

    def supervisor_running(self) -> bool:
        return self._supervisor is not None and self._supervisor.isRunning()

    # ── chat worker lifecycle ────────────────────────────────────────

    def active_chat_count(self) -> int:
        with self._lock:
            return len(self._chat_workers)

    def can_spawn_chat_worker(self) -> bool:
        return self.active_chat_count() < self._max_chat_workers()

    def spawn_chat_worker(self, message: str) -> str:
        """Spawn a new chat worker for ``message`` and return its id.

        If the soft cap is hit, the message is queued and drained when
        an earlier worker finishes. The caller still gets a worker id
        immediately so it can correlate signals to the right chat
        turn.
        """
        worker_id = uuid.uuid4().hex[:8]
        with self._lock:
            if len(self._chat_workers) >= self._max_chat_workers():
                self._chat_queue.append(f"{worker_id}::{message}")
                return worker_id
        self._spawn_worker_now(worker_id, message)
        return worker_id

    def _spawn_worker_now(self, worker_id: str, message: str) -> None:
        """Actually construct and start a worker thread."""
        from core.agent.chat_worker import ChatWorker

        config = self._load_config()
        paper_mode = bool(config.get("agent", {}).get("paper_mode", True))
        broker = self.get_broker_for_mode(paper_mode)

        worker = ChatWorker(
            worker_id=worker_id,
            message=message,
            config_path=self._config_path,
            broker_service=broker,
            db_path=self._db_path,
            paper_mode=paper_mode,
            parent=self,
        )

        # Fan worker signals out through pool signals so MainWindow
        # only needs to wire the pool once.
        worker.chat_text.connect(self.chat_text.emit)
        worker.chat_done.connect(self._on_worker_done)
        worker.chat_error.connect(self.chat_error.emit)
        worker.tool_use.connect(self.chat_tool_use.emit)
        worker.tool_result.connect(self.chat_tool_result.emit)
        worker.log_line.connect(self.chat_log_line.emit)

        with self._lock:
            self._chat_workers[worker_id] = worker
        self.worker_spawned.emit(worker_id)
        worker.start()

    def _on_worker_done(self, worker_id: str, summary: str) -> None:
        """Cleanup hook: drop the worker, drain the queue if possible."""
        self.chat_done.emit(worker_id, summary)
        next_task: Optional[str] = None
        with self._lock:
            worker = self._chat_workers.pop(worker_id, None)
            if self._chat_queue:
                next_task = self._chat_queue.popleft()
        if worker is not None:
            try:
                worker.wait(50)
            except Exception:
                pass
            worker.deleteLater()
        self.worker_finished.emit(worker_id)
        if next_task is not None:
            # Format: "<worker_id>::<message>"
            q_id, _, q_message = next_task.partition("::")
            self._spawn_worker_now(q_id, q_message)

    def cancel_all_chat_workers(self) -> None:
        """Signal every live chat worker to stop at the next boundary."""
        with self._lock:
            workers = list(self._chat_workers.values())
            self._chat_queue.clear()
        for w in workers:
            try:
                w.cancel()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Best-effort clean shutdown of everything in the pool."""
        self.cancel_all_chat_workers()
        self.kill_supervisor()
