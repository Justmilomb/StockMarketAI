"""Vision summariser — ask Claude what's on screen in sampled video frames.

Used by :mod:`core.scrapers.youtube_live_vision` to turn sampled frames
from the 24/7 finance-TV live stream into a one-line summary of any
markets content that's on screen (chyrons, ticker ribbons, charts).

Defensive by design: the SDK, the vision model, and the image-block
message format are all best-effort. Any failure returns an empty summary
and the scraper simply skips the cycle.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


_PROMPT: str = (
    "Describe the on-screen markets content in these frames from a "
    "finance-TV live stream. One line per signal you can read — "
    "ticker symbols, chyron headlines, chart direction, numbers. "
    "Skip presenter faces, studio scenery, filler. If no markets "
    "content is visible, reply with exactly the word NONE."
)


def _encode_frame(path: Path) -> Optional[dict]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


async def summarise_frames(
    frame_paths: List[Path],
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    """Return a one-paragraph summary, or empty string on failure / no content.

    ``frame_paths`` should be a small list (3 is typical) of JPEG files on
    disk. Order-agnostic; the model sees them as a set.
    """
    if not frame_paths:
        return ""

    try:
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )
    except Exception as e:
        logger.debug("vision: SDK unavailable (%s)", e)
        return ""

    image_blocks = [_encode_frame(p) for p in frame_paths]
    image_blocks = [b for b in image_blocks if b is not None]
    if not image_blocks:
        return ""

    # The SDK's query() accepts either a plain string or a list of content
    # blocks with images. We attempt the structured form; if that signature
    # isn't supported by the installed SDK version, we fall back cleanly.
    options = ClaudeAgentOptions(
        model=model,
        effort="low",  # type: ignore[arg-type]
        permission_mode="bypassPermissions",
    )

    reply_parts: list[str] = []
    try:
        async for message in query(
            prompt=[*image_blocks, {"type": "text", "text": _PROMPT}],  # type: ignore[arg-type]
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
    except Exception as e:
        logger.debug("vision: query failed (%s)", e)
        return ""

    text = "".join(reply_parts).strip()
    if not text or text.upper().strip() == "NONE":
        return ""
    return text
