"""AgentRunner — QThread that drives the AI agent loop.

Phase 4 of the agent-native rebuild. One fresh AI subprocess per
iteration, streamed through the agent SDK ``query()`` helper.
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

# Must import the subprocess patch before the agent SDK so it binds to
# the Windows-no-console launchers. Importing this package normally
# also runs the patch via __init__.py, but the explicit import
# documents the dependency and survives __init__.py refactors.
from . import subprocess_patch  # noqa: F401

import asyncio
import json
import logging
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

DEFAULT_WAKE_PROMPT: str = (
    "Wake up. Check the current portfolio and market state, decide "
    "whether anything needs action, and close your turn cleanly with "
    "end_iteration plus a one-paragraph summary for the human log."
)

#: Hard floor on cadence — the agent cannot run more than this often,
#: regardless of config, to protect the AI subscription quota.
CADENCE_FLOOR_SECONDS: int = 30

#: Default cadence when all major markets are closed and no agent
#: preference has been learned yet. 2 minutes — keeps the supervisor
#: responsive enough for fast day-trading decisions without burning
#: subscription quota when nothing's moving.
CADENCE_MARKET_CLOSED_DEFAULT: int = 120

#: Upper bound on how many journal-tail lines we keep in memory so the
#: panel doesn't grow unbounded over a long session.
JOURNAL_TAIL_MAX: int = 500

#: Fallback sleep when Claude's subscription quota is exhausted and the
#: error text doesn't carry a parseable reset clock. Five minutes is
#: long enough that we don't thrash the CLI, short enough that a quota
#: restoration gets picked up quickly.
USAGE_LIMIT_BACKOFF_SECONDS: int = 300

#: Substrings (case-insensitive) that mean the Claude CLI refused the
#: request because the account is out of quota, not because of a
#: programming error. When any of these appear in the combined
#: assistant text + stderr tail we enter the paused state instead of
#: raising an error to the UI.
USAGE_LIMIT_PATTERNS: Tuple[str, ...] = (
    "out of extra usage",
    "out of usage",
    "usage limit",
    "rate limit",
    "quota exceeded",
    "quota reached",
)


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
    cadence_changed = Signal(int)               # next sleep duration in seconds
    usage_limit_paused = Signal(str, int)       # user-facing message, seconds

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
        # Set by ``force_fast_iteration`` when a chat message signals
        # day-trading urgency. Clamps the *next* cadence to the 30s
        # floor so the supervisor doesn't fall back to a learned 5-min
        # wait the moment after a panicked "trade now" prompt.
        self._force_fast_next_cadence: bool = False

        # Per-iteration counters, reset on each run.
        self._tool_call_count: int = 0
        self._trade_count: int = 0
        self._watchlist_add_count: int = 0
        self._last_action_desc: str = ""
        self._agent_requested_wait_minutes: int = 0

        # Lifetime iteration counter (increments each iteration).
        self._iter_count: int = 0

        # Cached personality reference so market-aware cadence can read
        # learned timing preferences between iterations. Set at the start
        # of each iteration; None before the first iteration completes.
        self._cached_personality: Optional[Any] = None

        # Usage-limit backoff window: when Claude's subscription quota is
        # exhausted, the main loop skips iterations until this monotonic
        # deadline and shows ``_usage_pause_msg`` in the status bar.
        self._usage_pause_until: float = 0.0
        self._usage_pause_msg: str = ""

    # ── public API ───────────────────────────────────────────────────

    def request_stop(self) -> None:
        """Soft-stop: finish current iteration, then exit the loop."""
        self._stop_requested = True
        self._interrupt_sleep = True
        self.log_line.emit("[runner] stop requested")

    def notify_chat_activity(self) -> None:
        """Break the sleep early so the next iteration runs ASAP.

        Called by :class:`AgentPool` whenever a new chat worker is
        spawned. The supervisor sleeps in 250ms ticks polling this
        flag, so a chat message that mutates state (place_order, add
        to watchlist, update memory) means the supervisor can re-read
        the world on its very next wake and react — instead of sitting
        idle for the full cadence interval.

        Safe to call from any thread: only sets a single bool, no
        locking needed. Not an error to call when the loop is already
        in the middle of an iteration — the flag will be picked up the
        next time the runner enters ``_sleep_with_interrupt``.
        """
        self._interrupt_sleep = True

    def force_fast_iteration(self) -> None:
        """Force an immediate iteration with the minimum-cadence next wait.

        Called by :class:`AgentPool` when a chat message contains a
        day-trading urgency keyword (``trade now``, ``wake up``,
        ``hurry`` …). Wakes the supervisor out of any current sleep
        *and* clamps the next computed cadence to the 30s floor so the
        agent actually day-trades instead of sliding back to a learned
        5-minute wait the moment after the user asked for urgency.
        """
        self._interrupt_sleep = True
        self._force_fast_next_cadence = True

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
            # Honour the usage-limit pause window before spawning a
            # subprocess. The window was set by ``_enter_usage_pause``
            # when a prior iteration detected exhausted quota, and is
            # sized to land exactly 1 minute after Claude's reported
            # reset time (or USAGE_LIMIT_BACKOFF_SECONDS if we couldn't
            # parse a clock out of the error text).
            if self._usage_pause_until > time.monotonic():
                remaining = self._usage_pause_until - time.monotonic()
                if self._usage_pause_msg:
                    self.log_line.emit(f"[runner] {self._usage_pause_msg}")
                self.cadence_changed.emit(int(remaining))
                await self._sleep_with_interrupt(remaining)
                if self._stop_requested:
                    break
                # Pause expired — clear state and fall through to a
                # fresh iteration immediately.
                self._usage_pause_until = 0.0
                self._usage_pause_msg = ""
                continue

            self._agent_requested_wait_minutes = 0
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
            # If the iteration just tripped a usage-limit pause, skip
            # the normal cadence — the top-of-loop check will sleep
            # through the pause window on the next pass.
            if self._usage_pause_until > time.monotonic():
                continue
            wait_secs = self._compute_wait_seconds(self._agent_requested_wait_minutes)
            market_open = self._any_market_open()
            label = "market open" if market_open else "market closed"
            self.log_line.emit(
                f"[runner] next check-in in {wait_secs:.0f}s ({label})",
            )
            self.cadence_changed.emit(int(wait_secs))
            await self._sleep_with_interrupt(wait_secs)

    # ── iteration plumbing ───────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        # Delegate to the pool so the force_paper override is applied —
        # live pools always see paper_mode=False, paper pools always
        # see paper_mode=True, regardless of what's on disk.
        return self._pool._load_config()

    def _announce_next_cadence(self, minutes: int) -> None:
        """Emit cadence_changed the moment the agent picks its next wait.

        Called by the end_iteration tool via ``AgentContext.cadence_hook``
        — fires inside the tool callback, which runs on the agent loop's
        asyncio task. Qt auto-marshals the signal to the GUI thread via
        ``QueuedConnection``, so it's safe to call from here. The goal
        is a sub-second UI countdown flip instead of the ~5-20s lag from
        waiting until the assessor + reflector stages finish.

        Runs ``_compute_wait_seconds`` with a copy of the requested
        minutes so the settings panel sees the exact same duration the
        main loop will actually sleep for, including the 30s floor and
        any force-fast-next-cadence override.
        """
        try:
            mins = max(0, int(minutes))
        except (TypeError, ValueError):
            return
        # Intentionally does not consume _force_fast_next_cadence here —
        # _compute_wait_seconds does that when the main loop picks the
        # real wait. This is just an early UI preview, and using the
        # non-clamped path keeps it idempotent.
        if self._force_fast_next_cadence:
            secs = float(CADENCE_FLOOR_SECONDS)
        elif mins > 0:
            secs = float(max(CADENCE_FLOOR_SECONDS, mins * 60))
        else:
            market_open = self._any_market_open()
            if market_open:
                try:
                    cfg = self._load_config()
                    cadence = int(cfg.get("agent", {}).get("cadence_seconds", 90))
                except Exception:
                    cadence = 90
                secs = float(max(CADENCE_FLOOR_SECONDS, cadence))
            else:
                secs = float(max(CADENCE_FLOOR_SECONDS, self._closed_market_cadence()))
        self.cadence_changed.emit(int(secs))

    def _compute_wait_seconds(self, agent_requested_minutes: int = 0) -> float:
        """Compute sleep duration with market-aware fallback.

        Priority order:
        1. Agent's explicit next_check_in_minutes (highest trust — AI knows its state).
        2. Market-aware default: short cadence when open, longer when closed.
           The closed cadence uses learned personality preferences once enough
           samples have been collected, else CADENCE_MARKET_CLOSED_DEFAULT.

        The config cadence_seconds is used as the open-market default.
        """
        market_open = self._any_market_open()
        if self._force_fast_next_cadence:
            # Urgent chat override — one-shot clamp to the 30s floor so
            # a "trade now" prompt actually produces sub-minute follow-up,
            # even if the agent last asked for a 5-minute wait.
            self._force_fast_next_cadence = False
            return float(CADENCE_FLOOR_SECONDS)
        if agent_requested_minutes > 0:
            secs = float(max(CADENCE_FLOOR_SECONDS, agent_requested_minutes * 60))
            self._learn_cadence(secs, market_open)
            return secs
        if market_open:
            try:
                cfg = self._load_config()
                cadence = int(cfg.get("agent", {}).get("cadence_seconds", 90))
            except Exception:
                cadence = 90
            return float(max(CADENCE_FLOOR_SECONDS, cadence))
        # Market closed: use learned preference or default 10 min
        return float(max(CADENCE_FLOOR_SECONDS, self._closed_market_cadence()))

    def _any_market_open(self) -> bool:
        """Return True if LSE or NYSE/Nasdaq is currently in regular session."""
        try:
            from datetime import datetime, timezone
            from core.market_hours import get_exchange, status as mh_status
            now = datetime.now(tz=timezone.utc)
            for code in ("LSE", "US"):
                ex = get_exchange(code)
                if ex and mh_status(ex, now)["is_open"]:
                    return True
        except Exception:
            pass
        return False

    def _closed_market_cadence(self) -> float:
        """Return cadence seconds to use when all major markets are closed."""
        try:
            p = self._cached_personality
            if p is not None:
                prefs = getattr(p, "cadence_prefs", {})
                learned = float(prefs.get("closed_seconds", 0.0))
                samples = int(prefs.get("sample_count", 0))
                if learned > 0 and samples >= 3:
                    return min(learned, 300.0)  # cap at 5 min
        except Exception:
            pass
        return float(CADENCE_MARKET_CLOSED_DEFAULT)

    def _learn_cadence(self, seconds: float, market_open: bool) -> None:
        """Record the agent's chosen wait to the personality cadence prefs."""
        try:
            p = self._cached_personality
            if p is not None:
                p.record_cadence(seconds, market_open)
        except Exception:
            pass

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
        from core.agent._sdk import (
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
        from core.agent.model_router import supervisor_effort, supervisor_model
        from core.agent.paths import (
            cli_path_for_sdk,
            prepare_env_for_bundled_engine,
        )
        from core.agent.prompts import render_system_prompt

        config = self._load_config()
        agent_cfg = config.get("agent", {}) or {}
        paper_mode = bool(agent_cfg.get("paper_mode", True))

        effective_config = self._with_paper_flag(config, paper_mode)
        broker_service = self._pool.get_broker_for_mode(paper_mode)

        db = HistoryManager(self._db_path)
        risk = RiskManager(config=effective_config)

        from core.trader_personality import TraderPersonality
        personality_path = str(
            agent_cfg.get("trader_personality_path")
            or "data/trader_personality.json"
        )
        trader_personality = TraderPersonality(personality_path)
        trader_personality.load()
        self._cached_personality = trader_personality

        iteration_id = f"iter-{uuid.uuid4().hex[:8]}"
        ctx = init_agent_context(
            config=effective_config,
            broker_service=broker_service,
            db=db,
            risk_manager=risk,
            iteration_id=iteration_id,
            paper_mode=paper_mode,
            trader_personality=trader_personality,
            protective_store=self._pool.get_protective_store(),
        )
        # Install the cadence hook so end_iteration can announce the
        # next wake-up to the UI immediately, without waiting for the
        # iteration-teardown phase (assessor + reflector + cleanup) to
        # finish. _compute_wait_seconds applies the same clamping the
        # main loop would, so the settings-panel countdown matches the
        # real sleep duration the loop is about to enter.
        ctx.cadence_hook = self._announce_next_cadence

        self._tool_call_count = 0
        self._trade_count = 0
        self._watchlist_add_count = 0
        self._last_action_desc = ""
        self._iter_count += 1
        transcript_lines: list[str] = []
        prompt_text = self._build_iteration_prompt()

        # The supervisor is the autonomous trade decider — always the
        # heaviest tier. Chat workers get the lighter tier for
        # info-retrieval questions via model_router.chat_worker_model.
        model_id = supervisor_model(effective_config)
        effort = supervisor_effort(effective_config)

        self.iteration_started.emit(iteration_id)
        self.log_line.emit(
            f"[runner] iteration {iteration_id} "
            f"(paper={paper_mode}, model={model_id}, effort={effort}, no caps)",
        )

        mcp_server = build_mcp_server()
        # Bundled engine: on a frozen install the AI engine ships
        # next to blank.exe; we point the SDK straight at it so
        # system PATH never decides which engine gets spawned. In dev
        # cli_path_for_sdk resolves the system claude so the SDK
        # doesn't fall back to a stale bundled copy.
        prepare_env_for_bundled_engine()
        resolved_cli = cli_path_for_sdk()
        self.log_line.emit(f"[runner] cli={resolved_cli or '(sdk default)'}")

        stderr_lines: list[str] = []

        def _on_stderr(line: str) -> None:
            logger.warning("claude stderr: %s", line)
            stderr_lines.append(line)

        # Write the system prompt to a temp file so the CLI arg stays
        # short — Windows caps the command line at ~32k chars, and the
        # full prompt + MCP config + allowed-tools list easily exceeds
        # that when passed inline via --system-prompt.
        prompt_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="blank_prompt_",
            delete=False, encoding="utf-8",
        )
        try:
            prompt_file.write(render_system_prompt(effective_config, personality=trader_personality))
            prompt_file.close()
            system_prompt_ref: Dict[str, str] = {
                "type": "file",
                "path": prompt_file.name,
            }
        except Exception:
            prompt_file.close()
            os.unlink(prompt_file.name)
            raise

        options = ClaudeAgentOptions(
            system_prompt=system_prompt_ref,  # type: ignore[arg-type]
            mcp_servers={SERVER_NAME: mcp_server},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",
            model=model_id,
            effort=effort,  # type: ignore[arg-type]
            cwd=str(self._config_path.parent),
            cli_path=resolved_cli,
            stderr=_on_stderr,
        )

        start = time.monotonic()
        summary: str = ""
        last_assistant_text: str = ""

        try:
            async for message in query(prompt=prompt_text, options=options):
                # Only hard gate left is the user-initiated stop flag.
                if self._stop_requested:
                    self.log_line.emit("[runner] stop requested — breaking iteration")
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            last_assistant_text = block.text
                            self.text_chunk.emit(block.text)
                            self.log_line.emit(f"[ai] {block.text}")
                            transcript_lines.append(f"[thought] {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            self._tool_call_count += 1
                            tool_name = block.name or ""
                            # Tool names are namespaced as
                            # "mcp__<server>__<tool>" by the SDK; match
                            # on the trailing segment so we count both
                            # raw and namespaced variants.
                            short_name = tool_name.rsplit("__", 1)[-1]
                            if short_name == "place_order":
                                self._trade_count += 1
                            elif short_name == "add_to_watchlist":
                                self._watchlist_add_count += 1
                            self._last_action_desc = short_name or tool_name
                            self.tool_use.emit({
                                "name": block.name,
                                "input": block.input,
                                "iteration_id": iteration_id,
                            })
                            args_preview = self._truncate(
                                json.dumps(block.input, default=str), 160,
                            )
                            self.log_line.emit(f"[tool] {block.name}({args_preview})")
                            transcript_lines.append(
                                f"[tool] {short_name}({args_preview})"
                            )
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
                                transcript_lines.append(
                                    f"[result:{tag}] {self._truncate(preview, 400)}"
                                )
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        self.log_line.emit(
                            f"[runner] result=error reason={message.stop_reason}",
                        )
                        combined = (
                            last_assistant_text
                            + "\n"
                            + "\n".join(stderr_lines[-10:])
                        )
                        if self._looks_like_usage_limit(combined):
                            self._enter_usage_pause(combined)
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
            detail = str(e)
            if stderr_lines:
                detail += " | stderr: " + " ".join(stderr_lines[-5:])
            combined = last_assistant_text + "\n" + detail
            if self._looks_like_usage_limit(combined):
                self._enter_usage_pause(combined)
            else:
                self.error_occurred.emit(f"query failed: {detail}")
        finally:
            # Pull the summary + requested sleep the agent wrote via
            # end_iteration, if any — must happen before clear_agent_context.
            try:
                from core.agent.context import get_agent_context
                ctx = get_agent_context()
                summary = ctx.end_summary or ""
                self._agent_requested_wait_minutes = ctx.next_wait_minutes
            except Exception:
                summary = ""
            self._write_last_iteration_summary(
                iteration_id=iteration_id,
                summary=summary,
            )
            self.iteration_finished.emit(iteration_id, summary)
            self.log_line.emit(
                f"[runner] iteration {iteration_id} done "
                f"({self._tool_call_count} tool calls, "
                f"{time.monotonic() - start:.1f}s)",
            )
            try:
                await self._run_assessor(
                    iteration_id=iteration_id,
                    transcript_lines=transcript_lines,
                    summary=summary,
                    config=effective_config,
                )
            except Exception as e:
                logger.warning("assessor stage failed: %s", e)
            try:
                await self._run_reflector(
                    personality=trader_personality,
                    config=effective_config,
                )
            except Exception as e:
                logger.warning("reflector stage failed: %s", e)
            clear_agent_context()
            try:
                os.unlink(prompt_file.name)
            except Exception:
                pass

    async def _run_assessor(
        self,
        iteration_id: str,
        transcript_lines: List[str],
        summary: str,
        config: Dict[str, Any],
    ) -> None:
        """Grade the just-finished iteration and write the review to the journal.

        Purely advisory — never blocks the next iteration. A disabled
        assessor (empty ``ai.model_assessor``) short-circuits in
        :func:`core.agent.assessor.run_assessor`.
        """
        if not transcript_lines and not summary:
            return

        from core.agent.assessor import run_assessor

        transcript = "\n".join(transcript_lines)
        if summary:
            transcript += f"\n\n[end_iteration summary]\n{summary}"

        review = await run_assessor(transcript, config)
        if review is None:
            return

        colour = {"good": "ok", "mediocre": "warn", "bad": "err"}.get(review.grade, "warn")
        self.log_line.emit(
            f"[rev:{colour}] {review.grade.upper()} — {review.one_line}",
        )
        for c in review.concerns:
            self.log_line.emit(f"[rev] concern: {c}")
        for f in review.follow_ups:
            self.log_line.emit(f"[rev] follow-up: {f}")

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO agent_journal (iteration_id, kind, payload, tags) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        iteration_id,
                        "assessor_review",
                        review.to_json(),
                        review.grade,
                    ),
                )
        except Exception as e:
            logger.warning("failed to persist assessor review: %s", e)

    async def _run_reflector(
        self,
        personality: Any,
        config: Dict[str, Any],
    ) -> None:
        """Turn newly-closed trades into personality lessons.

        Reads the paper-broker audit log, updates win/loss stats, and
        (when the assessor model is configured) asks Claude for one
        lesson per closed trade. Purely advisory — never blocks.
        """
        if personality is None:
            return
        paper_cfg = config.get("paper_broker", {}) or {}
        audit_path = str(paper_cfg.get("audit_path") or "logs/paper_orders.jsonl")

        from core.trade_reflector import reflect_on_closed_trades
        written = await reflect_on_closed_trades(audit_path, personality, config)
        if written:
            self.log_line.emit(
                f"[reflector] wrote {written} lesson(s) from closed trades",
            )

    def _write_last_iteration_summary(
        self,
        iteration_id: str,
        summary: str,
    ) -> None:
        """Persist a one-line snapshot of the iteration to agent_memory.

        The chat worker reads ``last_iteration_summary`` on every user
        turn so it can answer "what just happened" without making a
        round-trip tool call. Best-effort — failure to write must never
        crash the iteration loop.
        """
        try:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            last_action = self._last_action_desc or "no tool calls"
            tail = ""
            if summary:
                # Squash newlines so the snapshot stays single-line.
                tail = " " + " ".join(summary.split())
                if len(tail) > 240:
                    tail = tail[:237] + "..."
            line = (
                f"iter {self._iter_count} ({iteration_id}) @ {now_iso}: "
                f"{self._tool_call_count} tools, "
                f"{self._trade_count} trades, "
                f"{self._watchlist_add_count} new tickers. "
                f"last action: {last_action}.{tail}"
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO agent_memory (key, value, updated_at) "
                    "VALUES (?, ?, datetime('now')) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value, "
                    "updated_at = datetime('now')",
                    ("last_iteration_summary", line),
                )
        except Exception:
            logger.exception("failed to persist last_iteration_summary")

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

    # ── usage-limit handling ─────────────────────────────────────────

    @staticmethod
    def _looks_like_usage_limit(text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        return any(p in lower for p in USAGE_LIMIT_PATTERNS)

    @staticmethod
    def _parse_reset_target(text: str) -> Optional[Tuple[datetime, datetime]]:
        """Parse Claude's "resets 10am" clock hint from an error message.

        Returns ``(reset_at, resume_at)`` where ``resume_at`` is one
        minute after the parsed reset time — that's when the loop fires
        its next iteration. Both are naive local ``datetime`` objects.
        Returns ``None`` if no clock is found so the caller can fall
        back to ``USAGE_LIMIT_BACKOFF_SECONDS``.
        """
        match = re.search(
            r"resets?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        try:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            meridiem = (match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            now = datetime.now()
            reset_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if reset_at <= now:
                reset_at = reset_at + timedelta(days=1)
            resume_at = reset_at + timedelta(minutes=1)
            return reset_at, resume_at
        except Exception:
            return None

    def _enter_usage_pause(self, detail: str) -> None:
        """Arm the pause window and tell the UI what's happening.

        Called when an iteration's error output matches a usage-limit
        pattern. Parses the reset clock if present and sleeps until
        exactly 1 minute after reset, otherwise falls back to a 5-minute
        blind retry. Either way, the user sees a plain-English message
        in the status bar that tells them when the advisor will resume.
        """
        snippet = self._truncate(detail.strip().replace("\n", " "), 160)
        parsed = self._parse_reset_target(detail)
        if parsed is not None:
            reset_at, resume_at = parsed
            seconds = max(1, int((resume_at - datetime.now()).total_seconds()))
            fmt = "%H:%M"
            self._usage_pause_msg = (
                f"blank advisor paused — usage resets at "
                f"{reset_at.strftime(fmt)}, will resume at "
                f"{resume_at.strftime(fmt)}"
            )
        else:
            seconds = USAGE_LIMIT_BACKOFF_SECONDS
            resume_at = datetime.now() + timedelta(seconds=seconds)
            hint = snippet or "no reset time given"
            self._usage_pause_msg = (
                f"blank advisor paused — usage limit reached "
                f"({hint}). Will retry at {resume_at.strftime('%H:%M')}."
            )
        self._usage_pause_until = time.monotonic() + seconds
        self.log_line.emit(f"[runner] {self._usage_pause_msg}")
        self.usage_limit_paused.emit(self._usage_pause_msg, seconds)
        self.cadence_changed.emit(seconds)
