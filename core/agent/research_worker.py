"""ResearchWorker — QThread that runs one research task.

Like ChatWorker but for autonomous research. Each worker:
1. Claims a task from the queue
2. Sets up AgentContext with research role metadata
3. Runs a claude-agent-sdk query with the role's system prompt
4. Streams until end_iteration
5. Marks the task complete and exits
"""
from __future__ import annotations

from . import subprocess_patch  # noqa: F401

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ResearchWorker(QThread):
    """Runs one research task through a single SDK client session.

    One instance per claimed task. Lives in the SwarmCoordinator's
    worker pool for the duration of its ``run()`` then signals
    completion via ``worker_done`` or ``worker_error``.
    """

    # ── UI signals ───────────────────────────────────────────────────
    log_line = Signal(str)              # pre-formatted journal line
    finding_submitted = Signal(dict)   # {role, ticker, headline, confidence}
    worker_done = Signal(str, str)     # worker_id, summary
    worker_error = Signal(str, str)    # worker_id, error message

    def __init__(
        self,
        worker_id: str,
        task: Dict[str, Any],
        role: Any,
        config_path: Path | str,
        broker_service: Any,
        db_path: str,
        paper_mode: bool,
        watchlist: Optional[List[str]] = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._worker_id = worker_id
        self._task = task
        self._role = role
        self._config_path = Path(config_path)
        self._broker_service = broker_service
        self._db_path = db_path
        self._paper_mode = paper_mode
        self._watchlist = watchlist
        self._stop_requested: bool = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def request_stop(self) -> None:
        """Request the worker to stop at the next message boundary."""
        self._stop_requested = True

    # ── QThread entry point ──────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — QThread API
        self.log_line.emit(f"[research:{self._worker_id}] worker started")
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_research())
        except Exception as e:  # pragma: no cover — defensive
            logger.exception("Research worker %s crashed", self._worker_id)
            self.worker_error.emit(self._worker_id, f"research worker crashed: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
            self.log_line.emit(f"[research:{self._worker_id}] worker stopped")

    # ── config loader ────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        with self._config_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # ── main research coroutine ──────────────────────────────────────

    async def _run_research(self) -> None:
        # Lazy-import: keeps the SDK out of the boot path so a missing
        # SDK fails the worker, not the whole app.
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolUseBlock,
        )
        from database import HistoryManager
        from risk_manager import RiskManager

        from core.agent.context import clear_agent_context, init_agent_context
        from core.agent.mcp_server import (
            SERVER_NAME,
            allowed_tool_names,
            build_mcp_server,
        )
        from core.agent.model_router import research_worker_model
        from core.agent.paths import (
            cli_path_for_sdk,
            prepare_env_for_bundled_engine,
        )
        from core.agent.prompts_research import render_research_prompt

        task_id: int = self._task["id"]
        role_id: str = self._role.role_id

        config = self._load_config()
        agent_cfg = config.get("agent", {}) or {}

        effective_config = dict(config)
        effective_config["agent"] = {
            **agent_cfg,
            "paper_mode": self._paper_mode,
        }

        db = HistoryManager(self._db_path)
        risk = RiskManager(config=effective_config)

        iteration_id = f"swarm-{role_id}-{uuid.uuid4().hex[:6]}"
        ctx = init_agent_context(
            config=effective_config,
            broker_service=self._broker_service,
            db=db,
            risk_manager=risk,
            iteration_id=iteration_id,
            paper_mode=self._paper_mode,
        )
        ctx.stats["research_role"] = role_id
        ctx.stats["research_task_id"] = task_id

        model_id = research_worker_model(effective_config, self._role)

        self.log_line.emit(
            f"[research:{self._worker_id}] iteration {iteration_id} "
            f"(role={role_id}, task={task_id}, "
            f"paper={self._paper_mode}, model={model_id})",
        )

        mcp_server = build_mcp_server()
        prepare_env_for_bundled_engine()

        system_prompt_text = render_research_prompt(
            effective_config,
            self._role,
            watchlist=self._watchlist,
        )

        # Build the wake prompt: role identity + task context + instruction
        wake_prompt_parts: List[str] = [
            f"You are research role '{role_id}'. Wake up and start researching.",
        ]

        ticker = self._task.get("ticker")
        if ticker:
            wake_prompt_parts.append(f"Your assigned ticker for this task: {ticker}.")

        parameters_raw = self._task.get("parameters")
        if parameters_raw:
            # Parameters may already be a dict (if claimed task was deserialized)
            # or a JSON string (straight from the DB row).
            if isinstance(parameters_raw, str):
                try:
                    params = json.loads(parameters_raw)
                except Exception:
                    params = parameters_raw
            else:
                params = parameters_raw
            wake_prompt_parts.append(
                f"Additional task parameters: {json.dumps(params, default=str)}",
            )

        wake_prompt_parts.append(
            "Find what's interesting, submit findings, then end your turn.",
        )

        wake_prompt = " ".join(wake_prompt_parts)

        # Write the system prompt to a temp file — Windows caps CLI args
        # at ~32k chars.
        prompt_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="blank_research_prompt_",
            delete=False, encoding="utf-8",
        )
        try:
            prompt_file.write(system_prompt_text)
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
            cwd=str(self._config_path.parent),
            cli_path=cli_path_for_sdk(),
        )

        start = time.monotonic()
        summary = ""

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(wake_prompt)

                async for message in client.receive_response():
                    if self._stop_requested:
                        self.log_line.emit(
                            f"[research:{self._worker_id}] stop requested",
                        )
                        try:
                            await client.interrupt()
                        except Exception:
                            logger.debug(
                                "interrupt failed on stop request", exc_info=True,
                            )
                        break

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                self.log_line.emit(
                                    f"[research:{self._worker_id}:ai] {block.text}",
                                )
                            elif isinstance(block, ToolUseBlock):
                                args_preview = _truncate(
                                    json.dumps(block.input, default=str), 160,
                                )
                                self.log_line.emit(
                                    f"[research:{self._worker_id}:tool] "
                                    f"{block.name}({args_preview})",
                                )
                                # Surface submit_finding calls to the coordinator
                                # so it can update the live findings panel without
                                # waiting for the DB polling cycle.
                                if block.name == "submit_finding":
                                    inp = block.input or {}
                                    self.finding_submitted.emit({
                                        "role": role_id,
                                        "ticker": inp.get("ticker", ""),
                                        "headline": inp.get("headline", ""),
                                        "confidence": inp.get("confidence_pct", 0),
                                    })
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            self.log_line.emit(
                                f"[research:{self._worker_id}] result=error "
                                f"reason={message.stop_reason}",
                            )
                        else:
                            self.log_line.emit(
                                f"[research:{self._worker_id}] result=ok "
                                f"turns={message.num_turns} "
                                f"duration={message.duration_ms}ms",
                            )
                    elif isinstance(message, SystemMessage):
                        pass

            # Grab the end_summary the agent wrote via end_iteration, if any.
            try:
                from core.agent.context import get_agent_context
                summary = get_agent_context().end_summary or ""
            except Exception:
                summary = ""

            db.complete_research_task(task_id)
            self.log_line.emit(
                f"[research:{self._worker_id}] task {task_id} completed "
                f"({time.monotonic() - start:.1f}s)",
            )
            self.worker_done.emit(self._worker_id, summary)

        except Exception as e:
            logger.exception("Research worker %s query failed", self._worker_id)
            db.complete_research_task(task_id, error=str(e))
            self.log_line.emit(
                f"[research:{self._worker_id}] task {task_id} failed: {e}",
            )
            self.worker_error.emit(self._worker_id, str(e))
        finally:
            clear_agent_context()
            try:
                os.unlink(prompt_file.name)
            except Exception:
                pass


# ── module-level helpers ─────────────────────────────────────────────────────

def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
