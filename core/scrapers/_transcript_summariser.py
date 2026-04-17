"""Transcript summariser — Haiku CLI with regex fallback.

Used by the YouTube-transcripts scraper to turn a 5-20 minute video
caption dump into a sub-400-character market-commentary summary. The
Haiku call goes through the same bundled engine CLI as the rest of
the app; if the CLI isn't available (fresh install, engine missing)
or the call fails, the fallback extractive summariser keeps the
scraper working.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from typing import List

logger = logging.getLogger(__name__)

_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
_MAX_CHARS: int = 400
_CALL_TIMEOUT: int = 45

_TICKER_RE = re.compile(r"\$?\b[A-Z]{1,5}\b")

_PROMPT_TEMPLATE: str = (
    "Summarise this market commentary transcript in under 400 characters. "
    "Focus on tickers mentioned, macro themes, and any specific calls or "
    "forecasts. British English. Output plain text, no preamble.\n\n"
    "TRANSCRIPT:\n{transcript}"
)


def _engine_cmd() -> str:
    """Resolve the bundled engine CLI, falling back to plain 'claude'."""
    try:
        from core.agent.paths import bundled_engine_cmd, engine_available
        if engine_available():
            return str(bundled_engine_cmd())
    except Exception:
        pass
    return "claude"


def _call_haiku(prompt: str) -> str:
    """Run one Haiku CLI invocation. Returns '' on any failure."""
    try:
        result = subprocess.run(
            [_engine_cmd(), "-p", prompt, "--model", _HAIKU_MODEL, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=_CALL_TIMEOUT,
            encoding="utf-8",
            **_SUBPROCESS_FLAGS,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return ""
    except Exception as exc:
        logger.debug("Haiku summariser error: %s", exc)
        return ""


def _extract_tickers(text: str) -> List[str]:
    """Grep-style ticker extraction for the fallback path.

    Matches $TICKER and bare TICKER tokens of 1-5 uppercase letters. A
    small blocklist filters out the most common all-caps English words
    to cut noise — it's not exhaustive, but good enough for a fallback.
    """
    noise = {
        "THE", "AND", "FOR", "BUT", "NOT", "YOU", "ARE", "WAS", "HAS", "OUR",
        "WILL", "THIS", "THAT", "WITH", "FROM", "HAVE", "BEEN", "WERE", "THEY",
        "WHAT", "WHEN", "WHERE", "THEIR", "THERE", "ABOUT",
        "CEO", "CFO", "EPS", "IPO", "USD", "GBP", "EUR",
    }
    found: List[str] = []
    for match in _TICKER_RE.findall(text.upper()):
        sym = match.lstrip("$")
        if len(sym) < 1 or len(sym) > 5:
            continue
        if sym in noise:
            continue
        if sym not in found:
            found.append(sym)
        if len(found) >= 8:
            break
    return found


def _fallback_summary(transcript: str) -> str:
    """Deterministic summariser used when the LLM CLI is unavailable."""
    cleaned = " ".join(transcript.split()).strip()
    if not cleaned:
        return ""
    preview = cleaned[:180]
    tickers = _extract_tickers(cleaned)
    if tickers:
        preview = f"{preview.rstrip('.')} | tickers: {', '.join(tickers)}"
    return preview[:_MAX_CHARS]


def summarise_transcript(transcript: str) -> str:
    """Return a sub-400-char summary of a video transcript.

    Tries Haiku first; on any failure returns a regex-extractive
    fallback so the scraper still produces a usable item.
    """
    cleaned = " ".join((transcript or "").split()).strip()
    if not cleaned:
        return ""
    # Cap input length to keep the CLI call cheap (Haiku is fast but
    # we'd rather not ship 30 min of captions at a time).
    truncated = cleaned[:6000]

    response = _call_haiku(_PROMPT_TEMPLATE.format(transcript=truncated))
    if response:
        return response[:_MAX_CHARS]
    return _fallback_summary(cleaned)
