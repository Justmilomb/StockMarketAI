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


#: Substrings that, when present in a chat message (case-insensitive),
#: escalate the usual supervisor wake into a full ``force_fast_iteration``
#: call. Kept deliberately narrow — "now" on its own is too common and
#: would fire on benign questions like "what's the price now?".
_URGENT_CHAT_PATTERNS: tuple[str, ...] = (
    "trade now",
    "day trade",
    "day-trade",
    "wake up",
    "hurry",
    "immediately",
    "urgent",
    "asap",
    "right now",
    "do it now",
)


def _is_urgent_chat(message: str) -> bool:
    """Return True if ``message`` looks like a day-trading urgency cue."""
    if not message:
        return False
    lower = message.lower()
    return any(pat in lower for pat in _URGENT_CHAT_PATTERNS)


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

        # Research swarm coordinator (daemon thread, built lazily).
        self._swarm: Optional[Any] = None
        self._watchlist_provider: Any = lambda: []

        # Native protective-orders engine. The store persists across
        # restarts; the monitor is a daemon thread that polls live
        # prices every ~1s and fires stops independently of the
        # supervisor's iteration cadence.
        self._protective_store: Optional[Any] = None
        self._protective_monitor: Optional[Any] = None

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

        Routing rules:

        * **Live mode** — hand back the main ``BrokerService`` the
          desktop app already built at boot.
        * **Paper mode, window-locked** (``force_paper=True``) — the
          MainWindow already built a paper ``BrokerService`` and
          handed it to us as ``live_broker_service``. Reuse it. This
          is critical: if we built our own here the UI and the agent
          pool would see two different paper portfolios, which is
          exactly the v2.1.3 "UI says £100, agent says $100k" bug.
        * **Paper mode, live window** — the live ``BrokerService`` is
          real money; we build a session-wide paper broker lazily on
          first request so the agent can still trade paper while the
          user watches live prices in the UI. Kept for the
          config-toggles-paper-in-a-live-window edge case.
        """
        if not paper_mode:
            return self._live_broker

        # Window-locked paper mode: reuse the MainWindow's paper broker.
        if self._force_paper:
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
            # Defaults deliberately small: paper mode in blank is a
            # £100 sandbox, never a $100k toy. A missing config key
            # should degrade safely, not silently hand the agent 1000x
            # its intended buying power.
            starting_cash = float(paper_cfg.get("starting_cash", 100.0))
            currency = str(paper_cfg.get("currency", "GBP") or "GBP")
            service.register_broker(
                "stocks",
                PaperBroker(
                    state_path=state_path,
                    audit_path=audit_path,
                    starting_cash=starting_cash,
                    currency=currency,
                ),
            )
            self._paper_broker = service
            logger.info(
                "AgentPool built session-wide paper broker (state=%s, currency=%s)",
                state_path, currency,
            )
        return self._paper_broker

    # ── protective orders (native stop-loss / take-profit) ──────────

    def get_protective_store(self) -> Any:
        """Lazily build the session-wide ProtectiveStore.

        Paper-locked windows get their own store file so paper stops
        never hit a live position and vice versa.
        """
        if self._protective_store is None:
            from pathlib import Path as _Path

            from core.protective_orders import ProtectiveStore

            cfg = self._load_config()
            po_cfg = cfg.get("protective_orders") or {}
            default_path = (
                "data/protective_orders_paper.json" if self._force_paper
                else "data/protective_orders.json"
            )
            state_path = _Path(po_cfg.get("state_path", default_path))
            self._protective_store = ProtectiveStore(state_path=state_path)
        return self._protective_store

    def start_protective_monitor(self) -> None:
        """Start the price-monitor daemon if enabled in config (default on)."""
        cfg = self._load_config()
        po_cfg = cfg.get("protective_orders") or {}
        if not po_cfg.get("enabled", True):
            logger.info("AgentPool: protective monitor disabled in config")
            return
        if (self._protective_monitor is not None
                and self._protective_monitor.is_alive()):
            return

        from core.protective_monitor import ProtectiveMonitor

        # Stops only make sense for the same broker the agent trades
        # through. We follow the pool's paper / live routing, same
        # as get_broker_for_mode does for the supervisor.
        config = self._load_config()
        paper_mode = bool(
            config.get("agent", {}).get("paper_mode", self._force_paper),
        )
        broker = self.get_broker_for_mode(paper_mode)
        store = self.get_protective_store()
        poll = float(po_cfg.get("poll_seconds", 1.0))
        self._protective_monitor = ProtectiveMonitor(
            store=store, broker_service=broker, poll_seconds=poll,
        )
        self._protective_monitor.start()
        logger.info(
            "AgentPool: protective monitor started (poll=%.2fs)", poll,
        )

    def stop_protective_monitor(self) -> None:
        if (self._protective_monitor is not None
                and self._protective_monitor.is_alive()):
            self._protective_monitor.stop()
            self._protective_monitor.join(timeout=5)
        self._protective_monitor = None

    def protective_monitor_running(self) -> bool:
        return (
            self._protective_monitor is not None
            and self._protective_monitor.is_alive()
        )

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
            protective_store=self.get_protective_store(),
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

        # Wake the supervisor early so it re-reads state right after
        # the chat worker touches the journal / broker / memory. Without
        # this, a user could ask blank to open a position in the chat
        # panel and the supervisor would keep sleeping for another
        # minute-and-a-half before noticing a new position exists.
        #
        # Urgency keywords escalate this to ``force_fast_iteration``,
        # which additionally clamps the NEXT cadence to the 30s floor
        # so the supervisor doesn't immediately slide back into a
        # learned multi-minute wait after the user asked for action.
        sup = self._supervisor
        if sup is not None and sup.isRunning():
            try:
                if _is_urgent_chat(message) and hasattr(sup, "force_fast_iteration"):
                    sup.force_fast_iteration()
                else:
                    sup.notify_chat_activity()
            except Exception:
                logger.debug("failed to wake supervisor on chat spawn", exc_info=True)

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
        self.stop_swarm()
        self.stop_protective_monitor()
        self.kill_supervisor()

    # ── swarm lifecycle ─────────────────────────────────────────────

    def start_swarm(self) -> None:
        """Start the research swarm coordinator if enabled in config."""
        try:
            config = self._load_config()
            swarm_cfg = config.get("swarm", {})
            if not swarm_cfg.get("enabled", False):
                logger.info("AgentPool: swarm disabled in config")
                return
        except Exception:
            return

        if self._swarm is not None and self._swarm.is_alive():
            return

        from core.agent.swarm import SwarmCoordinator

        paper_mode = self._force_paper
        broker = self.get_broker_for_mode(paper_mode)

        self._swarm = SwarmCoordinator(
            config_path=self._config_path,
            broker_service=broker,
            db_path=self._db_path,
            paper_mode=paper_mode,
            watchlist_provider=self._watchlist_provider,
        )
        self._swarm.start()
        logger.info("AgentPool: swarm coordinator started")

    def stop_swarm(self) -> None:
        """Stop the swarm coordinator."""
        if self._swarm is not None and self._swarm.is_alive():
            self._swarm.stop()
            self._swarm.join(timeout=10)
            self._swarm = None

    @property
    def swarm(self) -> Optional[Any]:
        return self._swarm

    def swarm_running(self) -> bool:
        return self._swarm is not None and self._swarm.is_alive()

    def set_watchlist_provider(self, provider: Any) -> None:
        """Set the watchlist provider callable for the swarm."""
        self._watchlist_provider = provider
