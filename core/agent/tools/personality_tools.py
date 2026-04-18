"""Personality MCP tools — let the agent read and evolve itself.

Five tools:

* ``get_personality`` — returns the seed, active rules, recent lessons,
  and stats.
* ``list_rules`` — numbered rules for quick reference before pruning.
* ``add_lesson(lesson, tags, trade?)`` — append an immutable lesson.
* ``add_rule(rule, confidence?, source_lesson_idx?)`` — add a new rule.
* ``remove_rule(index)`` — drop a rule that no longer applies.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _get_personality() -> Any:
    try:
        from core.agent.context import get_agent_context
        ctx = get_agent_context()
    except Exception:
        return None
    return getattr(ctx, "trader_personality", None)


@tool(
    "get_personality",
    "Read your own trader personality. Returns your seed (name, "
    "archetype, risk profile, initial traits), the rules you have "
    "written for yourself, your most recent lessons, and your win/"
    "loss stats. Call this when deciding how to weigh a trade or "
    "before adding / removing a rule so you know what's already there.",
    {},
)
async def get_personality(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_personality()
    if p is None:
        return _text_result({"error": "personality not initialised"})
    return _text_result(p.summary())


@tool(
    "list_rules",
    "List your active trading rules with their indexes. Useful right "
    "before calling remove_rule so you pass the correct index.",
    {},
)
async def list_rules(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_personality()
    if p is None:
        return _text_result({"error": "personality not initialised"})
    return _text_result({
        "rules": [
            {"index": i, **r} for i, r in enumerate(p.active_rules())
        ],
    })


@tool(
    "add_lesson",
    "Record a lesson after reflecting on a trade. Lessons are "
    "append-only and immortal — phrase them as things you want "
    "future-you to remember. Include tags (tickers, sectors, "
    "patterns) so similar situations retrieve them. Pass the trade "
    "dict for context if relevant.\n\n"
    "Args:\n"
    "    lesson: the lesson text\n"
    "    tags: list of string tags\n"
    "    trade: optional trade metadata dict\n",
    {"lesson": str, "tags": list, "trade": dict},
)
async def add_lesson(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_personality()
    if p is None:
        return _text_result({"error": "personality not initialised"})
    lesson = str(args.get("lesson", "")).strip()
    if not lesson:
        return _text_result({"error": "lesson text is required"})
    tags = args.get("tags") or []
    trade = args.get("trade") or None
    idx = p.add_lesson(lesson, tags=list(tags), trade=trade)
    return _text_result({"added_index": idx})


@tool(
    "add_rule",
    "Promote a lesson into an active rule that will be injected into "
    "your system prompt every iteration. Rules shape future "
    "decisions — use them for durable preferences, not one-off "
    "observations. Confidence is one of: 'experimental', 'learned', "
    "'strong'.\n\n"
    "Args:\n"
    "    rule: the rule text\n"
    "    confidence: 'experimental' | 'learned' | 'strong'\n"
    "    source_lesson_idx: optional index into your lessons list\n",
    {"rule": str, "confidence": str, "source_lesson_idx": int},
)
async def add_rule(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_personality()
    if p is None:
        return _text_result({"error": "personality not initialised"})
    rule = str(args.get("rule", "")).strip()
    if not rule:
        return _text_result({"error": "rule text is required"})
    conf = str(args.get("confidence", "experimental") or "experimental")
    src = args.get("source_lesson_idx")
    try:
        src_idx: Optional[int] = int(src) if src is not None else None
    except Exception:
        src_idx = None
    idx = p.add_rule(rule, confidence=conf, source_lesson_idx=src_idx)
    return _text_result({"added_index": idx})


@tool(
    "remove_rule",
    "Delete a rule that no longer fits you. Pass the rule's index as "
    "shown by list_rules. Returns {\"removed\": true} on success.",
    {"index": int},
)
async def remove_rule(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_personality()
    if p is None:
        return _text_result({"error": "personality not initialised"})
    try:
        idx = int(args.get("index", -1))
    except Exception:
        idx = -1
    removed = p.remove_rule(idx)
    return _text_result({"removed": removed, "index": idx})


PERSONALITY_TOOLS: List[Any] = [
    get_personality,
    list_rules,
    add_lesson,
    add_rule,
    remove_rule,
]
