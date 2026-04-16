"""ChatWorker — a single-turn AI sub-agent wrapped around a
persistent SDK client session.

Part of the multi-agent pool. The supervisor (``AgentRunner``) keeps
its long-running loop; every user chat message spawns a ``ChatWorker``
in its own ``QThread`` / asyncio task. The worker shares the
supervisor's tools, journal, and memory via the same SQLite handles,
but holds its own ``AgentContext`` bound to its own asyncio task
(``contextvars.ContextVar`` keeps them from racing).

Uses the SDK's streaming client mode rather than the one-shot
``query()`` helper. Streaming mode is the SDK-recommended pattern for
chat-style UIs: it gives us a proper conversation session (so
``interrupt`` works for cancels, the MCP server stays attached for the
whole turn, and the SDK tracks context correctly) instead of
re-spawning a fresh AI subprocess per call. The client lives for one
user message and is torn down by ``__aexit__`` when the turn ends.

No tool-call or wall-clock budget is enforced: the worker runs until
the model decides it's done (``end_iteration`` / natural stop) or the
user cancels via ``cancel()``. Historically there were ``max_turns``
and ``max_seconds`` caps, but they were removed because chat needed
the freedom to work through multi-step requests without hitting an
invisible ceiling mid-thought.

Paper / live broker selection is delegated to ``AgentPool``: the
worker is handed a broker reference on construction and uses it
verbatim. It never rebuilds a LogBroker for itself, so one chat worker
can see the paper positions the supervisor created (and vice versa).
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
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ChatWorker(QThread):
    """Runs a single chat message through one SDK client session.

    One instance per user message. Lives in ``AgentPool._chat_workers``
    for the duration of its ``run()`` then cleans itself up via the
    ``chat_done`` signal.
    """

    # ── UI signals ───────────────────────────────────────────────────
    chat_text = Signal(str, str)        # worker_id, text block
    chat_done = Signal(str, str)        # worker_id, summary
    chat_error = Signal(str, str)       # worker_id, error message
    tool_use = Signal(dict)             # {name, input, iteration_id}
    tool_result = Signal(dict)          # {content, is_error, iteration_id}
    log_line = Signal(str)              # pre-formatted journal line

    def __init__(
        self,
        worker_id: str,
        message: str,
        config_path: Path | str,
        broker_service: Any,
        db_path: str,
        paper_mode: bool,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._worker_id = worker_id
        self._message = (message or "").strip()
        self._config_path = Path(config_path)
        self._broker_service = broker_service
        self._db_path = db_path
        self._paper_mode = paper_mode
        self._tool_call_count: int = 0
        self._cancel_requested: bool = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def cancel(self) -> None:
        """Request the worker to stop at the next message boundary."""
        self._cancel_requested = True

    # ── QThread entry point ──────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — QThread API
        self.log_line.emit(f"[chat:{self._worker_id}] worker started")
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_one_shot())
        except Exception as e:  # pragma: no cover — defensive
            logger.exception("Chat worker %s crashed", self._worker_id)
            self.chat_error.emit(self._worker_id, f"chat worker crashed: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
            self.log_line.emit(f"[chat:{self._worker_id}] worker stopped")

    # ── one-shot plumbing ────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        with self._config_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # ── supervisor state snapshot ────────────────────────────────────

    def _build_supervisor_state_block(self, config: Dict[str, Any]) -> str:
        """Assemble a compact 'what the supervisor is doing' snapshot.

        Read from already-warm sources only (sqlite tables, the cached
        broker dicts) — no fresh tool round-trips. The model reads this
        on every turn so it can answer 'what's going on' without hitting
        a tool call. Best-effort: any failed source becomes a "—" line
        instead of crashing the worker.
        """
        lines: List[str] = ["## Current supervisor state"]

        # 1) Last iteration summary (written by AgentRunner Task F).
        lines.append("")
        lines.append(self._snapshot_last_iter_summary())

        # 2) Portfolio (cash + equity + open positions).
        lines.append("")
        lines.append(self._snapshot_portfolio())

        # 3) Active watchlist.
        lines.append("")
        lines.append(self._snapshot_watchlist(config))

        # 4) Last 5 journal entries.
        lines.append("")
        lines.append(self._snapshot_journal_tail(limit=5))

        # 5) Agent memory (capped to ~2KB so we don't blow the prompt).
        lines.append("")
        lines.append(self._snapshot_memory(byte_cap=2048))

        return "\n".join(lines)

    def _snapshot_last_iter_summary(self) -> str:
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM agent_memory WHERE key = ?",
                    ("last_iteration_summary",),
                ).fetchone()
            if row and row[0]:
                return f"Last supervisor iteration: {row[0]}"
        except Exception:
            logger.debug("snapshot last_iter_summary failed", exc_info=True)
        return "Last supervisor iteration: (none yet)"

    def _snapshot_portfolio(self) -> str:
        try:
            account = self._broker_service.get_account_info() or {}
            positions = self._broker_service.get_positions() or []
        except Exception:
            logger.debug("snapshot portfolio failed", exc_info=True)
            return "Portfolio: (unavailable)"

        cash = account.get("cash")
        equity = account.get("total") or account.get("equity") or account.get("free")
        currency = account.get("currency") or ""

        head = f"Portfolio: cash={cash} equity={equity}"
        if currency:
            head += f" ({currency})"

        if not positions:
            return head + "; positions=none"

        # Compact one-line position list.
        pos_bits: List[str] = []
        for p in positions[:20]:
            ticker = p.get("ticker") or p.get("symbol") or "?"
            qty = p.get("quantity") or p.get("qty") or 0
            avg = p.get("average_price") or p.get("avg_price") or p.get("avg_cost")
            pos_bits.append(f"{ticker} x{qty}@{avg}")
        return head + "; positions=" + ", ".join(pos_bits)

    def _snapshot_watchlist(self, config: Dict[str, Any]) -> str:
        try:
            active = config.get("active_watchlist") or "Default"
            lists = config.get("watchlists") or {}
            tickers = list(lists.get(active) or [])
        except Exception:
            logger.debug("snapshot watchlist failed", exc_info=True)
            return "Watchlist: (unavailable)"
        if not tickers:
            return f"Watchlist '{active}': empty"
        if len(tickers) > 30:
            preview = tickers[:30]
            return (
                f"Watchlist '{active}' ({len(tickers)} total): "
                + ", ".join(preview)
                + ", ..."
            )
        return f"Watchlist '{active}': " + ", ".join(tickers)

    def _snapshot_journal_tail(self, limit: int = 5) -> str:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT timestamp, kind, tool, payload FROM agent_journal "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except Exception:
            logger.debug("snapshot journal failed", exc_info=True)
            return "Recent journal: (unavailable)"
        if not rows:
            return "Recent journal: (empty)"
        out: List[str] = ["Recent journal (newest first):"]
        for r in rows:
            ts, kind, tool, payload = r
            payload_short = (payload or "").replace("\n", " ")
            if len(payload_short) > 160:
                payload_short = payload_short[:157] + "..."
            tag = tool or kind or "note"
            out.append(f"  - {ts} [{tag}] {payload_short}")
        return "\n".join(out)

    def _snapshot_memory(self, byte_cap: int = 2048) -> str:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT key, value, updated_at FROM agent_memory "
                    "ORDER BY updated_at DESC",
                ).fetchall()
        except Exception:
            logger.debug("snapshot memory failed", exc_info=True)
            return "Memory: (unavailable)"
        if not rows:
            return "Memory: (empty)"
        out: List[str] = ["Memory:"]
        used = 0
        for key, value, _ts in rows:
            entry = f"  - {key}: {value}"
            if used + len(entry) > byte_cap:
                out.append("  - (truncated — use read_memory for the rest)")
                break
            out.append(entry)
            used += len(entry)
        return "\n".join(out)

    def _compose_prompt(self, config: Dict[str, Any]) -> str:
        """Prepend a supervisor-state block to the user's literal message."""
        try:
            block = self._build_supervisor_state_block(config)
        except Exception:
            logger.exception("supervisor state block assembly crashed")
            block = "## Current supervisor state\n(unavailable this turn)"
        return f"{block}\n\n---\n\n{self._message}"

    async def _run_one_shot(self) -> None:
        # Lazy-import for the same reason AgentRunner does: keep the SDK
        # out of the boot path so a missing SDK fails the worker, not
        # the whole app.
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )
        from database import HistoryManager
        from risk_manager import RiskManager

        from core.agent.context import clear_agent_context, init_agent_context
        from core.agent.mcp_server import (
            SERVER_NAME,
            allowed_tool_names,
            build_mcp_server,
        )
        from core.agent.model_router import chat_worker_model
        from core.agent.paths import (
            cli_path_for_sdk,
            prepare_env_for_bundled_engine,
        )
        from core.agent.prompts import render_chat_system_prompt

        config = self._load_config()
        agent_cfg = config.get("agent", {}) or {}

        # Every agent runs against the same config dict so `paper_mode`
        # and other flags remain consistent. We *don't* rebuild the
        # broker here: the pool handed us the right one.
        effective_config = dict(config)
        effective_config["agent"] = {
            **agent_cfg,
            "paper_mode": self._paper_mode,
        }

        db = HistoryManager(self._db_path)
        risk = RiskManager(config=effective_config)

        iteration_id = f"chat-{self._worker_id}"
        init_agent_context(
            config=effective_config,
            broker_service=self._broker_service,
            db=db,
            risk_manager=risk,
            iteration_id=iteration_id,
            paper_mode=self._paper_mode,
        )

        # Judgment vs info routing: keyword classifier picks the heavy
        # tier for trade/decision requests and the medium tier for pure
        # info retrieval. Defaults fall back to medium — cheap is the
        # safe default for chat because the supervisor handles
        # autonomous decisions.
        model_id, tier = chat_worker_model(effective_config, self._message)

        self.log_line.emit(
            f"[chat:{self._worker_id}] iteration {iteration_id} "
            f"(paper={self._paper_mode}, tier={tier}, model={model_id}, no caps)",
        )

        mcp_server = build_mcp_server()
        # Bundled engine: prefer our shipped engine + Node over anything
        # on system PATH. In dev mode cli_path_for_sdk resolves the
        # system claude so the SDK skips its stale bundled copy.
        prepare_env_for_bundled_engine()
        resolved_cli = cli_path_for_sdk()
        self.log_line.emit(
            f"[chat:{self._worker_id}] cli={resolved_cli or '(sdk default)'}",
        )

        stderr_lines: list[str] = []

        def _on_stderr(line: str) -> None:
            logger.warning("claude stderr: %s", line)
            stderr_lines.append(line)

        options = ClaudeAgentOptions(
            system_prompt=render_chat_system_prompt(effective_config),
            mcp_servers={SERVER_NAME: mcp_server},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",
            model=model_id,
            cwd=str(self._config_path.parent),
            cli_path=resolved_cli,
            stderr=_on_stderr,
        )

        start = time.monotonic()
        final_text_parts: List[str] = []

        # The supervisor-state block is prepended here so the model has
        # "what just happened" context before it even starts the turn —
        # zero fresh tool calls needed for the common "what's going on"
        # question. See Task B in the v1.0.0 plan.
        composed_prompt = self._compose_prompt(effective_config)

        try:
            # Streaming-mode session: the SDK client owns the AI
            # subprocess + MCP server for the whole turn. We send the
            # composed prompt once and drain receive_response() which
            # terminates on the first ResultMessage (end of turn).
            async with ClaudeSDKClient(options=options) as client:
                await client.query(composed_prompt)

                async for message in client.receive_response():
                    if self._cancel_requested:
                        self.log_line.emit(
                            f"[chat:{self._worker_id}] cancel requested",
                        )
                        # Tell the SDK to stop the current turn. Any
                        # stray messages after this are ignored — we
                        # break out of the loop immediately below.
                        try:
                            await client.interrupt()
                        except Exception:
                            logger.debug(
                                "interrupt failed on cancel", exc_info=True,
                            )
                        break

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                final_text_parts.append(block.text)
                                self.chat_text.emit(self._worker_id, block.text)
                                self.log_line.emit(
                                    f"[chat:{self._worker_id}:ai] {block.text}",
                                )
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
                                self.log_line.emit(
                                    f"[chat:{self._worker_id}:tool] "
                                    f"{block.name}({args_preview})",
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
                                        f"[chat:{self._worker_id}:result:{tag}] "
                                        f"{self._truncate(preview, 200)}",
                                    )
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            self.log_line.emit(
                                f"[chat:{self._worker_id}] result=error "
                                f"reason={message.stop_reason}",
                            )
                        else:
                            self.log_line.emit(
                                f"[chat:{self._worker_id}] result=ok "
                                f"turns={message.num_turns} "
                                f"duration={message.duration_ms}ms",
                            )
                    elif isinstance(message, SystemMessage):
                        pass
        except Exception as e:
            logger.exception("Chat query stream failed")
            detail = str(e)
            if stderr_lines:
                detail += " | stderr: " + " ".join(stderr_lines[-5:])
            self.chat_error.emit(
                self._worker_id, f"chat query failed: {detail}",
            )
        finally:
            # Prefer the end_iteration summary if the model called it;
            # otherwise fall back to the concatenated text we collected.
            summary = ""
            try:
                from core.agent.context import get_agent_context
                summary = get_agent_context().end_summary or ""
            except Exception:
                summary = ""
            if not summary:
                summary = "\n".join(p for p in final_text_parts if p).strip()
            self.chat_done.emit(self._worker_id, summary)
            self.log_line.emit(
                f"[chat:{self._worker_id}] done "
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
