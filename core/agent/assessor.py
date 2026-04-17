"""Post-iteration assessor — grades the supervisor's last iteration.

Runs once per supervisor iteration, right after ``end_iteration`` and
before ``clear_agent_context``. Purely advisory: if the call times out
or errors, the loop keeps going without it.

The assessor runs on the cheaper Sonnet tier by default (configurable
via ``ai.model_assessor`` + ``ai.effort_assessor``). The prompt lives in
:mod:`core.agent.prompts`; the JSON contract is documented there.

Failure policy
--------------

- SDK missing / CLI unresolved → log once, return ``None``.
- Empty transcript → skip entirely, return ``None``.
- Model reply unparsable → return a ``bad``-grade review with the raw
  reply stashed in ``concerns[0]`` so the human still sees something.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_GRADES: tuple[str, ...] = ("good", "mediocre", "bad")


@dataclass
class AssessorReview:
    grade: str                # one of _GRADES
    one_line: str
    concerns: List[str]
    follow_ups: List[str]

    def to_json(self) -> str:
        return json.dumps({
            "grade": self.grade,
            "one_line": self.one_line,
            "concerns": self.concerns,
            "follow_ups": self.follow_ups,
        })


def _parse_reply(raw: str) -> AssessorReview:
    """Coerce a model reply into a structured review.

    The prompt asks for strict JSON, but models sometimes wrap it in a
    ``` fence or prepend a sentence. We strip that and try again before
    giving up.
    """
    text = (raw or "").strip()
    if not text:
        return AssessorReview("bad", "empty reply", ["assessor returned no text"], [])

    # Extract the first {...} block if the model added prose or fences.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text

    try:
        data = json.loads(candidate)
    except Exception:
        return AssessorReview(
            "bad",
            "unparsable JSON",
            [text[:500]],
            [],
        )

    grade = str(data.get("grade", "")).strip().lower()
    if grade not in _GRADES:
        grade = "mediocre"

    one_line = str(data.get("one_line", "")).strip()[:200]

    concerns_raw = data.get("concerns") or []
    follow_ups_raw = data.get("follow_ups") or []
    concerns = [str(c).strip() for c in concerns_raw if str(c).strip()][:3]
    follow_ups = [str(f).strip() for f in follow_ups_raw if str(f).strip()][:3]

    return AssessorReview(grade, one_line, concerns, follow_ups)


async def run_assessor(
    transcript: str,
    config: Dict[str, Any],
) -> Optional[AssessorReview]:
    """Grade a supervisor transcript. Returns ``None`` if disabled / failed.

    Setting ``ai.model_assessor`` to an empty string in config disables
    the assessor cleanly — useful as a kill switch.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return None

    try:
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
        from core.agent.model_router import assessor_effort, assessor_model
        from core.agent.paths import cli_path_for_sdk, prepare_env_for_bundled_engine
        from core.agent.prompts import render_assessor_system_prompt
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("assessor: SDK import failed: %s", e)
        return None

    model_id = assessor_model(config)
    if not model_id:
        return None
    effort = assessor_effort(config)

    prepare_env_for_bundled_engine()
    cli = cli_path_for_sdk()

    options = ClaudeAgentOptions(
        system_prompt=render_assessor_system_prompt(config),
        model=model_id,
        effort=effort,  # type: ignore[arg-type]
        cli_path=cli,
        permission_mode="bypassPermissions",
    )

    reply_parts: list[str] = []
    try:
        async for message in query(prompt=transcript, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
    except Exception as e:
        logger.warning("assessor: query failed: %s", e)
        return None

    return _parse_reply("".join(reply_parts))
