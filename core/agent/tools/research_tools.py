"""Research swarm tools — submit findings, read findings, set goals, get status.

Four tools that allow research worker agents to collaborate via the shared DB:

    submit_finding      write a structured research finding to the DB
    get_findings        read recent findings with optional filters
    set_research_goal   create a goal for the swarm to pursue
    get_swarm_status    snapshot of queue stats, active goals, top findings
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context

_VALID_FINDING_TYPES = {"alert", "sentiment", "catalyst", "thesis", "pattern"}


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "submit_finding",
    "Submit a research finding to the shared swarm database so other agents "
    "can act on it. Supply a headline, a finding_type (one of: alert, "
    "sentiment, catalyst, thesis, pattern), and a confidence percentage. "
    "Returns the saved finding id.",
    {
        "ticker": str,
        "finding_type": str,
        "headline": str,
        "confidence_pct": int,
        "source": str,
        "detail": str,
        "methodology": str,
        "evidence": str,
    },
)
async def submit_finding(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    headline = str(args.get("headline") or "").strip()
    if not headline:
        return _text_result({"status": "rejected", "reason": "headline is required"})

    finding_type = str(args.get("finding_type") or "").strip().lower()
    if finding_type not in _VALID_FINDING_TYPES:
        return _text_result({
            "status": "rejected",
            "reason": f"finding_type must be one of {sorted(_VALID_FINDING_TYPES)}",
        })

    try:
        confidence = int(args.get("confidence_pct") or 50)
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    role = str(ctx.stats.get("research_role") or "unknown")
    task_id = ctx.stats.get("research_task_id")

    evidence_raw = args.get("evidence") or ""
    # Store evidence as a JSON string so the column stays serialisable.
    evidence_json = json.dumps(str(evidence_raw)) if evidence_raw else None

    finding_id = ctx.db.save_research_finding({
        "task_id": task_id,
        "role": role,
        "ticker": args.get("ticker") or None,
        "finding_type": finding_type,
        "headline": headline,
        "detail": args.get("detail") or None,
        "confidence_pct": confidence,
        "source": args.get("source") or None,
        "methodology": args.get("methodology") or None,
        "evidence_json": evidence_json,
    })

    return _text_result({
        "status": "saved",
        "finding_id": finding_id,
        "role": role,
        "ticker": args.get("ticker"),
        "finding_type": finding_type,
        "headline": headline,
        "confidence_pct": confidence,
    })


@tool(
    "get_findings",
    "Retrieve recent research findings from the shared swarm database. "
    "Filter by age, minimum confidence, ticker, or finding type. "
    "Returns a list of findings ordered by confidence then recency.",
    {
        "since_minutes": int,
        "min_confidence": int,
        "ticker": str,
        "finding_type": str,
        "limit": int,
    },
)
async def get_findings(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    try:
        since_minutes = int(args.get("since_minutes") or 360)
    except (TypeError, ValueError):
        since_minutes = 360

    try:
        min_confidence = int(args.get("min_confidence") or 0)
    except (TypeError, ValueError):
        min_confidence = 0

    try:
        limit = int(args.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30

    ticker = args.get("ticker") or None
    if ticker:
        ticker = str(ticker).strip() or None

    finding_type = args.get("finding_type") or None
    if finding_type:
        finding_type = str(finding_type).strip() or None

    findings = ctx.db.get_research_findings(
        since_minutes=since_minutes,
        min_confidence=min_confidence,
        ticker=ticker,
        finding_type=finding_type,
        limit=limit,
    )

    return _text_result({"count": len(findings), "findings": findings})


@tool(
    "set_research_goal",
    "Create a new research goal that directs the swarm. "
    "Specify the goal text, a priority (1=highest, 10=lowest), which roles "
    "should tackle it (comma-separated), and an optional deadline in minutes "
    "from now. Returns the new goal id.",
    {
        "goal": str,
        "priority": int,
        "target_roles": str,
        "deadline_minutes": int,
    },
)
async def set_research_goal(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    goal_text = str(args.get("goal") or "").strip()
    if not goal_text:
        return _text_result({"status": "rejected", "reason": "goal text is required"})

    try:
        priority = int(args.get("priority") or 5)
    except (TypeError, ValueError):
        priority = 5
    priority = max(1, min(10, priority))

    target_roles = args.get("target_roles") or None
    if target_roles:
        target_roles = str(target_roles).strip() or None

    deadline_at: str | None = None
    raw_deadline = args.get("deadline_minutes")
    if raw_deadline is not None:
        try:
            deadline_minutes = int(raw_deadline)
            # Express deadline as an ISO-style offset SQLite can handle.
            # We store the string; HistoryManager accepts any ISO-8601 value.
            import datetime
            deadline_dt = (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(minutes=deadline_minutes)
            )
            deadline_at = deadline_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            pass

    role = str(ctx.stats.get("research_role") or "supervisor")

    goal_id = ctx.db.insert_research_goal(
        goal=goal_text,
        priority=priority,
        created_by=role,
        target_roles=target_roles,
        deadline_at=deadline_at,
    )

    return _text_result({
        "status": "created",
        "goal_id": goal_id,
        "goal": goal_text,
        "priority": priority,
        "target_roles": target_roles,
        "deadline_at": deadline_at,
    })


@tool(
    "get_swarm_status",
    "Return a snapshot of the entire research swarm: task queue stats, "
    "active goals, and the highest-confidence findings from the last 2 hours. "
    "Use this to decide what to investigate next.",
    {},
)
async def get_swarm_status(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    task_queue = ctx.db.get_research_task_stats()
    active_goals = ctx.db.get_active_research_goals()
    top_findings = ctx.db.get_research_findings(
        since_minutes=120,
        min_confidence=60,
        limit=10,
    )

    return _text_result({
        "task_queue": task_queue,
        "active_goals": active_goals,
        "top_findings_last_2h": top_findings,
    })


RESEARCH_TOOLS = [submit_finding, get_findings, set_research_goal, get_swarm_status]
