"""Runtime context for the agent tool bus.

The @tool decorator from claude-agent-sdk requires module-level async
functions whose only parameter is a dict of arguments. Those functions
still need access to stateful resources — broker, database, config,
risk manager — so we park them in a process-wide singleton that the
runner (or the agent_repl harness) initialises once before registering
the MCP server.

This is deliberately a tiny object: one struct, one init/get pair, no
magic. Importing the tool modules does *not* build any of the real
resources — only a call to ``init_agent_context`` does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from broker_service import BrokerService
from database import HistoryManager
from risk_manager import RiskManager


@dataclass
class AgentContext:
    """Process-wide handles every tool module can read from.

    Fields:
        config            loaded config.json dict
        broker_service    BrokerService for get_portfolio / place_order
        db                HistoryManager for agent_memory + agent_journal
        risk_manager      RiskManager for size_position
        iteration_id      tag written into every journal row for this run
        paper_mode        when True, place_order is routed to LogBroker
                          regardless of config.broker.type (agent safety)
        end_requested     set by end_iteration tool; the runner checks this
                          after the query() call returns to schedule the
                          next wake-up and write the summary to the UI.
        next_wait_minutes the agent's requested delay before the next
                          iteration (runner clamps against cadence floor).
        end_summary       free-form summary the agent wrote on its way out.
        stats             ad-hoc counters (tool_calls, errors, …) used by
                          the runner for budget enforcement.
    """

    config: Dict[str, Any]
    broker_service: BrokerService
    db: HistoryManager
    risk_manager: RiskManager
    iteration_id: str = ""
    paper_mode: bool = True
    end_requested: bool = False
    next_wait_minutes: int = 0
    end_summary: str = ""
    stats: Dict[str, int] = field(default_factory=dict)


_context: Optional[AgentContext] = None


def init_agent_context(
    config: Dict[str, Any],
    broker_service: BrokerService,
    db: HistoryManager,
    risk_manager: RiskManager,
    iteration_id: str = "",
    paper_mode: bool = True,
) -> AgentContext:
    """Set the process-wide agent context. Called once per agent iteration."""
    global _context
    _context = AgentContext(
        config=config,
        broker_service=broker_service,
        db=db,
        risk_manager=risk_manager,
        iteration_id=iteration_id,
        paper_mode=paper_mode,
    )
    return _context


def get_agent_context() -> AgentContext:
    """Return the initialised context or raise if init_agent_context was skipped."""
    if _context is None:
        raise RuntimeError(
            "AgentContext not initialised — call init_agent_context() "
            "before spawning the agent iteration.",
        )
    return _context


def clear_agent_context() -> None:
    """Drop the context — used for test isolation."""
    global _context
    _context = None
