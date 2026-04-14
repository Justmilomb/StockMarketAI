"""One-shot agent REPL — Phase 2 verification harness.

Usage:
    python scripts/agent_repl.py              # default prompt
    python scripts/agent_repl.py "sell TSLA"  # custom prompt

What it does:
    1. Load config.json.
    2. Force paper mode ON (agent safety) — LogBroker regardless of
       the real `broker.type`.
    3. Initialise BrokerService, HistoryManager, RiskManager.
    4. Initialise the process-wide AgentContext used by every
       @tool function in core/agent/tools/*.py.
    5. Build the in-process MCP server from `core.agent.mcp_server`.
    6. Fire one `query()` against Claude Code CLI with the autonomous
       PM system prompt and the MCP server registered.
    7. Stream every AssistantMessage, ToolUseBlock, ToolResultBlock,
       ResultMessage to the terminal.

Exit criteria for Phase 2:
    The agent should be able to call `get_portfolio`, look at a price,
    and cleanly call `end_iteration` without crashing.

This harness is *never* invoked from the desktop app — it's strictly
a developer tool for watching an iteration unfold in real time.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# ── sys.path setup so core/ modules import flat ────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))
os.chdir(PROJECT_ROOT)

from claude_agent_sdk import (  # noqa: E402
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

from broker_service import BrokerService  # noqa: E402
from database import HistoryManager  # noqa: E402
from risk_manager import RiskManager  # noqa: E402

from core.agent.context import clear_agent_context, init_agent_context  # noqa: E402
from core.agent.mcp_server import SERVER_NAME, allowed_tool_names, build_mcp_server  # noqa: E402
from core.agent.prompts import render_system_prompt  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────

def _load_config() -> dict[str, Any]:
    cfg_path = PROJECT_ROOT / "config.json"
    with cfg_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    data["__config_path__"] = str(cfg_path)
    return data


def _force_paper_mode(config: dict[str, Any]) -> dict[str, Any]:
    """Override broker.type → 'log' and agent.paper_mode → True.

    This is the REPL's belt-and-braces guard: regardless of what the
    real config says, the harness *never* talks to a live broker.
    """
    cfg = dict(config)
    cfg["broker"] = {**cfg.get("broker", {}), "type": "log"}
    agent = dict(cfg.get("agent", {}))
    agent["paper_mode"] = True
    cfg["agent"] = agent
    return cfg


def _print_divider(title: str) -> None:
    print()
    print("─" * 72)
    print(title)
    print("─" * 72)


def _print_assistant_message(msg: AssistantMessage) -> None:
    for block in msg.content:
        if isinstance(block, TextBlock):
            print(f"[claude] {block.text}")
        elif isinstance(block, ToolUseBlock):
            args_preview = json.dumps(block.input, default=str)
            if len(args_preview) > 200:
                args_preview = args_preview[:197] + "..."
            print(f"[tool_use] {block.name}({args_preview})")
        elif isinstance(block, ToolResultBlock):
            content = block.content
            preview: str
            if isinstance(content, str):
                preview = content
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict) and "text" in c:
                        parts.append(str(c["text"]))
                    else:
                        parts.append(str(c))
                preview = " ".join(parts)
            else:
                preview = str(content)
            if len(preview) > 400:
                preview = preview[:397] + "..."
            tag = " ERROR" if block.is_error else ""
            print(f"[tool_result{tag}] {preview}")


def _print_user_message(msg: UserMessage) -> None:
    content = msg.content
    if isinstance(content, str):
        # Initial user prompt echoes back as a UserMessage — skip noise.
        return
    for block in content:
        if isinstance(block, ToolResultBlock):
            preview: str
            raw = block.content
            if isinstance(raw, str):
                preview = raw
            elif isinstance(raw, list):
                parts = []
                for c in raw:
                    if isinstance(c, dict) and "text" in c:
                        parts.append(str(c["text"]))
                    else:
                        parts.append(str(c))
                preview = " ".join(parts)
            else:
                preview = str(raw)
            if len(preview) > 400:
                preview = preview[:397] + "..."
            tag = " ERROR" if block.is_error else ""
            print(f"[tool_result{tag}] {preview}")


def _print_result_message(msg: ResultMessage) -> None:
    _print_divider("iteration complete")
    print(f"  duration_ms   : {msg.duration_ms}")
    print(f"  duration_api  : {msg.duration_api_ms}")
    print(f"  num_turns     : {msg.num_turns}")
    print(f"  stop_reason   : {msg.stop_reason}")
    print(f"  is_error      : {msg.is_error}")
    if msg.total_cost_usd is not None:
        print(f"  total_cost_usd: {msg.total_cost_usd:.4f}")
    if msg.errors:
        print(f"  errors        : {msg.errors}")


# ── main ───────────────────────────────────────────────────────────────

async def run_one_iteration(prompt_text: str) -> None:
    config = _force_paper_mode(_load_config())

    # Build the dependencies the tool bus needs.
    db = HistoryManager(config.get("database", {}).get("path", "data/terminal_history.db"))
    broker = BrokerService(config=config)
    risk = RiskManager(config=config)

    iteration_id = f"repl-{uuid.uuid4().hex[:8]}"

    ctx = init_agent_context(
        config=config,
        broker_service=broker,
        db=db,
        risk_manager=risk,
        iteration_id=iteration_id,
        paper_mode=True,
    )
    _print_divider(f"iteration {iteration_id} — paper mode")
    print(f"  broker is_live = {broker.is_live}")
    print(f"  prompt         = {prompt_text}")

    mcp_server = build_mcp_server()
    tool_allowlist = allowed_tool_names()
    print(f"  tools exposed  = {len(tool_allowlist)}")

    options = ClaudeAgentOptions(
        system_prompt=render_system_prompt(config),
        mcp_servers={SERVER_NAME: mcp_server},
        allowed_tools=tool_allowlist,
        permission_mode="bypassPermissions",
        cwd=str(PROJECT_ROOT),
    )

    _print_divider("streaming")
    try:
        async for message in query(prompt=prompt_text, options=options):
            if isinstance(message, AssistantMessage):
                _print_assistant_message(message)
            elif isinstance(message, UserMessage):
                _print_user_message(message)
            elif isinstance(message, SystemMessage):
                # Too noisy to show every system message; keep it quiet.
                pass
            elif isinstance(message, ResultMessage):
                _print_result_message(message)
    finally:
        _print_divider("post-iteration state")
        print(f"  end_requested     = {ctx.end_requested}")
        print(f"  next_wait_minutes = {ctx.next_wait_minutes}")
        print(f"  end_summary       = {ctx.end_summary!r}")
        clear_agent_context()


def main() -> None:
    prompt_text = (
        " ".join(sys.argv[1:])
        or "Wake up. Check the portfolio, look at one live price "
           "(pick any ticker we already hold, or TSLA if we hold none), "
           "write a short journal note about what you see, and end the "
           "iteration with next_check_in_minutes=5."
    )
    asyncio.run(run_one_iteration(prompt_text))


if __name__ == "__main__":
    main()
