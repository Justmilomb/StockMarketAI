"""AgentRunner — QThread that drives the Claude agent loop.

Phase 4 of the Claude-native rebuild. One fresh Claude Code subprocess
per iteration, streamed through the claude-agent-sdk ``query()`` helper.
No tool-call or wall-clock budget is enforced here any more — the
agent runs each iteration until the model calls ``end_iteration`` (or
the user hits stop). The earlier caps kept being hit mid-thought and
were removed so the supervisor can do its best work without an
invisible ceiling.

Design notes
------------

* One iteration = one subprocess. No shared state between iterations
  other than the sqlite agent_journal / agent_memory tables, which are
  the agent's *persistent* memory across runs.
* The QThread owns the asyncio event loop. Every SDK message is routed
  through Qt signals, which Qt auto-marshals onto the GUI thread via
  ``Qt.QueuedConnection``, so panel updates are safe.
* Chat is no longer routed through the supervisor. The ``AgentPool``
  spawns an independent ``ChatWorker`` per user message; this runner
  only handles the long-lived autonomous loop. That way chat stays
  responsive even while the supervisor is mid-iteration.
* Broker selection goes through ``AgentPool.get_broker_for_mode`` so
  the supervisor and every chat worker share one session-wide paper
  broker (instead of each agent rebuilding an empty LogBroker).
* ``request_stop`` raises a soft stop flag; the loop exits at the next
  safe checkpoint (end of iteration, sleep tick, or message boundary).
  The subprocess is killed by the SDK when the async iterator is broken
  out of.

Config
------

Reads ``agent`` section from ``config.json`` every iteration so the user
can retune cadence / caps live without restarting the app.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

DEFAULT_WAKE_PROMPT: str = (
    "Wake up. Check the current portfolio and market state, decide "
    "whether anything needs action, and close your turn cleanly with "
    "end_iteration plus a one-paragraph summary for the human log."
)

#: Hard floor on cadence — the agent cannot run more than this often,
#: regardless of config, to protect the Claude subscription quota.
CADENCE_FLOOR_SECONDS: int = 30

#: Upper bound on how many journal-tail lines we keep in memory so the
#: panel doesn't grow unbounded over a long session.
JOURNAL_TAIL_MAX: int = 500


class AgentRunner(QThread):
    """Continuous agent loop: spawn → stream → sleep → repeat."""

    # ── UI signals ───────────────────────────────────────────────────
    status_changed = Signal(bool)               # True when loop is alive
    iteration_started = Signal(str)             # iteration_id
    iteration_finished = Signal(str, str)       # iteration_id, summary
    tool_use = Signal(dict)                     # {name, input, iteration_id}
    tool_result = Signal(dict)                  # {content, is_error, iteration_id}
    text_chunk = Signal(str)                    # assistant text block
    log_line = Signal(str)                      # pre-formatted journal line
    error_occurred = Signal(str)                # fatal runner error

    def __init__(
        self,
        config_path: Path | str,
        pool: Any,
        db_path: str = "data/terminal_history.db",
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._config_path: Path = Path(config_path)
        self._pool = pool
        self._db_path = db_path

        self._stop_requested: bool = False
        self._interrupt_sleep: bool = False

        # Per-iteration counters, reset on each run.
        self._tool_call_count: int = 0

    # ── public API ───────────────────────────────────────────────────

    def request_stop(self) -> None:
        """Soft-stop: finish current iteration, then exit the loop."""
        self._stop_requested = True
        self._interrupt_sleep = True
        self.log_line.emit("[runner] stop requested")

    # ── QThread entry point ──────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — QThread API
        self._stop_requested = False
        self.status_changed.emit(True)
        self.log_line.emit("[runner] agent loop started")
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._main_loop())
        except Exception as e:  # pragma: no cover — defensive
            logger.exception("Agent runner crashed")
            self.error_occurred.emit(f"agent loop crashed: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
            self.status_changed.emit(False)
            self.log_line.emit("[runner] agent loop stopped")

    async def _main_loop(self) -> None:
        while not self._stop_requested:
            try:
                await self._run_one_iteration()
            except asyncio.CancelledError:
                self.log_line.emit("[runner] iteration cancelled")
                break
            except Exception as e:
                logger.exception("Iteration failed")
                self.error_occurred.emit(f"iteration error: {e}")

            if self._stop_requested:
                break
            await self._sleep_with_interrupt(self._compute_wait_seconds())

    # ── iteration plumbing ───────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        # Delegate to the pool so the force_paper override is applied —
        # live pools always see paper_mode=False, paper pools always
        # see paper_mode=True, regardless of what's on disk.
        return self._pool._load_config()

    def _compute_wait_seconds(self) -> float:
        try:
            cfg = self._load_config()
            cadence = int(cfg.get("agent", {}).get("cadence_seconds", 90))
        except Exception:
            cadence = 90
        return float(max(CADENCE_FLOOR_SECONDS, cadence))

    async def _sleep_with_interrupt(self, seconds: float) -> None:
        """Sleep in short ticks so stop / chat can interrupt quickly."""
        self._interrupt_sleep = False
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop_requested or self._interrupt_sleep:
                return
            await asyncio.sleep(0.25)

    def _build_iteration_prompt(self) -> str:
        """The supervisor only ever gets the standard wake prompt.

        Chat messages no longer flow through here — the pool spawns a
        dedicated ``ChatWorker`` per user message so chat turnaround
        doesn't wait on a full iteration.
        """
        return DEFAULT_WAKE_PROMPT

    @staticmethod
    def _with_paper_flag(config: Dict[str, Any], paper_mode: bool) -> Dict[str, Any]:
        """Propagate the effective paper flag into the config dict the
        tools read from. Broker selection is delegated to the pool —
        we don't override ``broker.type`` here any more.
        """
        cfg = dict(config)
        agent = dict(cfg.get("agent", {}))
        agent["paper_mode"] = paper_mode
        cfg["agent"] = agent
        return cfg

    async def _run_one_iteration(self) -> None:
        # Lazy-import so that importing this module does not force the
        # SDK + tool bus to resolve at app startup (cheaper boot, and a
        # missing SDK fails the agent loop rather than the whole app).
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
            query,
        )
        from database import HistoryManager
        from risk_manager import RiskManager

        from core.agent.context import clear_agent_context, init_agent_context
        from core.agent.mcp_server import (
            SERVER_NAME,
            allowed_tool_names,
            build_mcp_server,
        )
        from core.agent.model_router import supervisor_model
        from core.agent.prompts import render_system_prompt

        config = self._load_config()
        agent_cfg = config.get("agent", {}) or {}
        paper_mode = bool(agent_cfg.get("paper_mode", True))

        effective_config = self._with_paper_flag(config, paper_mode)
        broker_service = self._pool.get_broker_for_mode(paper_mode)

        db = HistoryManager(self._db_path)
        risk = RiskManager(config=effective_config)

        iteration_id = f"iter-{uuid.uuid4().hex[:8]}"
        init_agent_context(
            config=effective_config,
            broker_service=broker_service,
            db=db,
            risk_manager=risk,
            iteration_id=iteration_id,
            paper_mode=paper_mode,
        )

        self._tool_call_count = 0
        prompt_text = self._build_iteration_prompt()

        # The supervisor is the autonomous trade decider — always Opus.
        # Chat workers get the lighter Sonnet tier for info-retrieval
        # questions via core.agent.model_router.chat_worker_model.
        model_id = supervisor_model(effective_config)

        self.iteration_started.emit(iteration_id)
        self.log_line.emit(
            f"[runner] iteration {iteration_id} "
            f"(paper={paper_mode}, model={model_id}, no caps)",
        )

        mcp_server = build_mcp_server()
        options = ClaudeAgentOptions(
            system_prompt=render_system_prompt(effective_config),
            mcp_servers={SERVER_NAME: mcp_server},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",
            model=model_id,
            cwd=str(self._config_path.parent),
        )

        start = time.monotonic()
        summary: str = ""

        try:
            async for message in query(prompt=prompt_text, options=options):
                # Only hard gate left is the user-initiated stop flag.
                if self._stop_requested:
                    self.log_line.emit("[runner] stop requested — breaking iteration")
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            self.text_chunk.emit(block.text)
                            self.log_line.emit(f"[claude] {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            self._tool_call_count += 1
                            self.tool_use.emit({
                                "name": block.name,
                                "input": block.input,
                                "iteration_id": iteration_id,
                            })
                            args_preview = self._truncate(
                                json.dumps(block.input, default=str), 160,
                            )
                            self.log_line.emit(f"[tool] {block.name}({args_preview})")
                elif isinstance(message, UserMessage):
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, ToolResultBlock):
                                preview = self._format_tool_result(block.content)
                                self.tool_result.emit({
                                    "content": preview,
                                    "is_error": bool(block.is_error),
                                    "iteration_id": iteration_id,
                                })
                                tag = "err" if block.is_error else "ok"
                                self.log_line.emit(
                                    f"[result:{tag}] {self._truncate(preview, 200)}",
                                )
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        self.log_line.emit(
                            f"[runner] result=error reason={message.stop_reason}",
                        )
                    else:
                        self.log_line.emit(
                            f"[runner] result=ok turns={message.num_turns} "
                            f"duration={message.duration_ms}ms",
                        )
                elif isinstance(message, SystemMessage):
                    # Silent — too noisy to surface in the UI log.
                    pass
        except Exception as e:
            logger.exception("Query stream failed")
            self.error_occurred.emit(f"query failed: {e}")
        finally:
            # Pull the summary the agent wrote via end_iteration, if any.
            try:
                from core.agent.context import get_agent_context
                summary = get_agent_context().end_summary or ""
            except Exception:
                summary = ""
            self.iteration_finished.emit(iteration_id, summary)
            self.log_line.emit(
                f"[runner] iteration {iteration_id} done "
                f"({self._tool_call_count} tool calls, "
                f"{time.monotonic() - start:.1f}s)",
            )
            clear_agent_context()

    # ── formatting helpers ───────────────────────────────────────────

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    @staticmethod
    def _format_tool_result(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for c in content:
                if isinstance(c, dict) and "text" in c:
                    parts.append(str(c["text"]))
                else:
                    parts.append(str(c))
            return " ".join(parts)
        return str(content)
