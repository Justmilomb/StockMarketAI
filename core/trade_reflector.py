"""Post-iteration reflector — turn closed trades into lessons.

After every supervisor iteration the runner calls
:func:`reflect_on_closed_trades`. It reads any new FILLED SELL lines in
the paper-broker audit log since the last reflection cursor, updates
the personality's win/loss stats, and asks Claude (on the cheap tier)
to write a one-line lesson per closed trade. Lessons are appended to
the personality via ``add_lesson``; the cursor is advanced so the same
trade is never reflected twice.

Never raises. If the LLM is unavailable or the reply is unusable we
still update stats and advance the cursor so the reflector doesn't get
stuck on the same trade.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ClosedTrade:
    """One round-trip close extracted from the paper audit log."""

    cursor: str           # audit timestamp — used as the new cursor
    ticker: str
    quantity: float
    fill_price: float
    realised_pnl: float   # in account currency
    currency: str


def find_new_closed_trades(
    audit_path: Path | str,
    cursor: Optional[str],
) -> Tuple[List[ClosedTrade], Optional[str]]:
    """Return FILLED SELL trades whose audit timestamp is > ``cursor``.

    Returns ``(trades, new_cursor)``. The new cursor is the timestamp of
    the last trade returned, or the previous cursor if nothing new was
    found. Safe to call on a missing / empty audit file — returns ``([], cursor)``.
    """
    path = Path(audit_path)
    if not path.exists():
        return [], cursor

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("reflector: could not read %s: %s", path, e)
        return [], cursor

    trades: List[ClosedTrade] = []
    latest_cursor = cursor
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("status", "")).upper() != "FILLED":
            continue
        if str(row.get("side", "")).upper() != "SELL":
            continue
        ts = str(row.get("timestamp", "") or "")
        if cursor and ts <= cursor:
            continue
        try:
            qty = float(row.get("quantity", 0) or 0)
            fill_price = float(row.get("fill_price", 0) or 0)
            realised = float(row.get("realised_pnl_acct", 0) or 0)
        except (TypeError, ValueError):
            continue
        trades.append(ClosedTrade(
            cursor=ts,
            ticker=str(row.get("ticker", "") or ""),
            quantity=qty,
            fill_price=fill_price,
            realised_pnl=realised,
            currency=str(row.get("account_currency", "GBP") or "GBP"),
        ))
        latest_cursor = ts

    return trades, latest_cursor


REFLECTOR_SYSTEM_PROMPT: str = """\
You help a trading AI reflect on its own closed trades. The user will
describe one or more closed round-trip trades. For each, write one
short, first-person lesson that captures what could be learnt.
Lessons should be durable observations the trader would want to
remember the *next* time a similar setup appears — not a generic
platitude.

Reply with STRICT JSON (no prose, no fences):
  {"lessons": [
     {"ticker": "...", "lesson": "...", "tags": ["tag1", "tag2"]},
     ...
  ]}

If a trade is too small or uninformative to yield a lesson, omit it
from the list. Empty "lessons" array is fine.
"""


def _build_trade_block(trades: List[ClosedTrade]) -> str:
    lines = []
    for t in trades:
        verdict = "WIN" if t.realised_pnl > 0 else ("LOSS" if t.realised_pnl < 0 else "FLAT")
        lines.append(
            f"- {t.ticker}: SOLD {t.quantity:g} @ {t.fill_price:g} "
            f"({t.currency}); realised P&L {t.realised_pnl:+.2f} [{verdict}]",
        )
    return "\n".join(lines)


def _parse_lessons(raw: str) -> List[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text
    try:
        data = json.loads(candidate)
    except Exception:
        return []
    items = data.get("lessons") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        lesson = str(it.get("lesson", "")).strip()
        if not lesson:
            continue
        tags_raw = it.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()][:6]
        cleaned.append({
            "ticker": str(it.get("ticker", "") or "").strip(),
            "lesson": lesson[:400],
            "tags": tags,
        })
    return cleaned


async def reflect_on_closed_trades(
    audit_path: Path | str,
    personality: Any,
    config: Dict[str, Any],
) -> int:
    """Reflect on any new closed trades and write lessons to personality.

    Returns the number of lessons written. Never raises.
    """
    if personality is None:
        return 0

    cursor = getattr(personality, "reflection_cursor", None)
    trades, new_cursor = find_new_closed_trades(audit_path, cursor)
    if not trades:
        return 0

    # Stats update first — happens even if the LLM call fails.
    for t in trades:
        try:
            personality.update_stats(win=t.realised_pnl > 0)
        except Exception:
            pass

    lessons_written = 0
    transcript = _build_trade_block(trades)
    try:
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
        from core.agent.model_router import assessor_effort, assessor_model
        from core.agent.paths import cli_path_for_sdk, prepare_env_for_bundled_engine
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("reflector: SDK import failed: %s", e)
        _advance_cursor(personality, new_cursor)
        return 0

    model_id = assessor_model(config)
    effort = assessor_effort(config)
    if not model_id:
        _advance_cursor(personality, new_cursor)
        return 0

    prepare_env_for_bundled_engine()
    cli = cli_path_for_sdk()
    options = ClaudeAgentOptions(
        system_prompt=REFLECTOR_SYSTEM_PROMPT,
        model=model_id,
        effort=effort,  # type: ignore[arg-type]
        cli_path=cli,
        permission_mode="bypassPermissions",
    )

    reply_parts: List[str] = []
    try:
        async for message in query(prompt=transcript, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
    except Exception as e:
        logger.warning("reflector: query failed: %s", e)
        _advance_cursor(personality, new_cursor)
        return 0

    lessons = _parse_lessons("".join(reply_parts))
    for lesson in lessons:
        try:
            personality.add_lesson(
                lesson["lesson"],
                tags=lesson.get("tags") or [],
                trade={"ticker": lesson.get("ticker", "")},
            )
            lessons_written += 1
        except Exception:
            continue

    _advance_cursor(personality, new_cursor)
    return lessons_written


def _advance_cursor(personality: Any, new_cursor: Optional[str]) -> None:
    if new_cursor is None:
        return
    try:
        personality.set_reflection_cursor(new_cursor)
    except Exception:
        pass
