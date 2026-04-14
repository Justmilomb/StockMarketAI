"""ChatWorker — a one-shot Claude sub-agent for a single chat message.

Part of the multi-agent pool. The supervisor (``AgentRunner``) keeps
its long-running loop; every user chat message spawns a ``ChatWorker``
in its own ``QThread`` / asyncio task. The worker shares the
supervisor's tools, journal, and memory via the same SQLite handles,
but holds its own ``AgentContext`` bound to its own asyncio task
(``contextvars.ContextVar`` keeps them from racing).

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

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ChatWorker(QThread):
    """Runs a single chat message through one claude-agent-sdk ``query()``.

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

    async def _run_one_shot(self) -> None:
        # Lazy-import for the same reason AgentRunner does: keep the SDK
        # out of the boot path so a missing SDK fails the worker, not
        # the whole app.
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
        from core.agent.model_router import chat_worker_model
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

        # Judgment vs info routing: keyword classifier picks Opus for
        # trade/decision requests and Sonnet for pure info retrieval.
        # Defaults fall back to Sonnet — cheap is the safe default for
        # chat because the supervisor handles autonomous decisions.
        model_id, tier = chat_worker_model(effective_config, self._message)

        self.log_line.emit(
            f"[chat:{self._worker_id}] iteration {iteration_id} "
            f"(paper={self._paper_mode}, tier={tier}, model={model_id}, no caps)",
        )

        mcp_server = build_mcp_server()
        options = ClaudeAgentOptions(
            system_prompt=render_chat_system_prompt(effective_config),
            mcp_servers={SERVER_NAME: mcp_server},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",
            model=model_id,
            cwd=str(self._config_path.parent),
        )

        start = time.monotonic()
        final_text_parts: List[str] = []

        try:
            async for message in query(prompt=self._message, options=options):
                if self._cancel_requested:
                    self.log_line.emit(
                        f"[chat:{self._worker_id}] cancel requested",
                    )
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            final_text_parts.append(block.text)
                            self.chat_text.emit(self._worker_id, block.text)
                            self.log_line.emit(
                                f"[chat:{self._worker_id}:claude] {block.text}",
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
            self.chat_error.emit(
                self._worker_id, f"chat query failed: {e}",
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
