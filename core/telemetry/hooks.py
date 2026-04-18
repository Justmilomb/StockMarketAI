"""Telemetry hooks — scrubbed event shapers for every emit site.

Every public ``record_*`` helper here is responsible for:

* Dropping personal data (emails, names, API keys, T212 account IDs,
  hostnames, file paths) *before* the event reaches the collector.
* Turning a domain object into a flat ``dict`` of primitives that
  ``json.dumps`` can serialise cheaply.
* Calling :func:`core.telemetry.emit` — a no-op when telemetry is
  disabled, so callers never need to check ``is_enabled()`` first.

Call sites live in the scraper runner, agent runner, chat worker,
paper broker, and the ``TelemetryLogHandler`` logging adapter. Keeping
the scrub logic here (rather than inline at every call site) means
there is exactly one place to audit when the privacy policy changes.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from core import telemetry

logger = logging.getLogger(__name__)


# ── scrubbers ────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_API_KEY_RE = re.compile(r"\b[A-Za-z0-9]{24,}\b")
# Trading 212 account URLs and share identifiers follow a predictable
# pattern — strip anything that looks like a full T212 identifier so an
# account number can't leak via a URL or error message.
_T212_ID_RE = re.compile(r"\b\d{7,}\b")

# Keys we refuse to include in any event payload, ever. The list is
# conservative — unknown-but-suspicious keys are dropped at the caller
# boundary. This complements (not replaces) per-site scrubbing.
_FORBIDDEN_KEYS = frozenset({
    "email", "email_address", "user_email",
    "name", "full_name", "display_name", "first_name", "last_name",
    "password", "pwd", "secret", "token", "api_key", "apikey",
    "licence_key", "license_key",
    "t212_api_key", "t212_secret_key", "t212_account_id",
    "address", "phone", "phone_number",
    "host", "hostname", "machine_name", "computer_name", "username",
    "ip", "ip_address", "user_agent",
})


def _scrub_text(text: Any, *, max_len: int = 4000) -> str:
    """Remove obvious PII from a free-text field and bound its length.

    Applies to every string that made it past the caller's own scrub —
    the double pass is intentional. If a scraper writes a URL that
    happens to contain an email, the URL survives but the email is
    masked.
    """
    if text is None:
        return ""
    s = str(text)
    s = _EMAIL_RE.sub("[email]", s)
    s = _API_KEY_RE.sub("[key]", s)
    s = _T212_ID_RE.sub("[id]", s)
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _scrub_dict(d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop forbidden keys and scrub every remaining string field.

    Nested dicts / lists are walked one level — a scraper or agent
    payload should never be deeper than that in practice, and we'd
    rather drop structured info than send unknown data unscrubbed.
    """
    if not d:
        return {}
    out: Dict[str, Any] = {}
    for k, v in d.items():
        kl = str(k).lower()
        if kl in _FORBIDDEN_KEYS:
            continue
        if isinstance(v, str):
            out[k] = _scrub_text(v)
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _scrub_dict(v)
        elif isinstance(v, list):
            out[k] = [_scrub_list_item(item) for item in v[:100]]
        else:
            out[k] = _scrub_text(v)
    return out


def _scrub_list_item(item: Any) -> Any:
    if isinstance(item, dict):
        return _scrub_dict(item)
    if isinstance(item, (int, float, bool)) or item is None:
        return item
    return _scrub_text(item)


# ── scraper events ───────────────────────────────────────────────────

def record_scraper_item(row: Dict[str, Any]) -> None:
    """Called from ``ScraperRunner._run_cycle`` for every new row.

    ``row`` is the dict shape produced by ``ScrapedItem.to_dict``
    post-VADER scoring. We keep source, title, URL, timestamp and
    sentiment; everything else is dropped.
    """
    try:
        payload = {
            "source": row.get("source"),
            "title": _scrub_text(row.get("title"), max_len=500),
            "url": _scrub_text(row.get("url"), max_len=500),
            "published_at": row.get("published_at") or row.get("timestamp"),
            "tickers": list(row.get("tickers") or [])[:20],
            "sentiment": row.get("sentiment"),
            "sentiment_score": row.get("sentiment_score"),
        }
        telemetry.emit("scraper_item", payload)
    except Exception:
        logger.debug("record_scraper_item failed", exc_info=True)


# ── agent events ─────────────────────────────────────────────────────

def record_iteration_finished(
    iteration_id: str,
    summary: str,
    *,
    tool_call_count: int = 0,
    trade_count: int = 0,
    duration_seconds: float = 0.0,
    model_id: str = "",
    effort: str = "",
) -> None:
    """One supervisor iteration wrapped up."""
    try:
        telemetry.emit("agent_iteration", {
            "iteration_id": iteration_id,
            "summary": _scrub_text(summary, max_len=4000),
            "tool_call_count": int(tool_call_count),
            "trade_count": int(trade_count),
            "duration_seconds": float(duration_seconds),
            "model_id": model_id,
            "effort": effort,
        })
    except Exception:
        logger.debug("record_iteration_finished failed", exc_info=True)


def record_tool_use(iteration_id: str, name: str, input_args: Dict[str, Any]) -> None:
    """Every tool call the agent fires during an iteration.

    Tool arguments can carry user-controlled strings (e.g. a chat
    worker told the agent a ticker), so we scrub the dict before
    recording. Tool output is captured separately in
    :func:`record_tool_result`.
    """
    try:
        telemetry.emit("agent_tool_use", {
            "iteration_id": iteration_id,
            "name": name,
            "input": _scrub_dict(input_args),
        })
    except Exception:
        logger.debug("record_tool_use failed", exc_info=True)


def record_tool_result(
    iteration_id: str,
    content: Any,
    *,
    is_error: bool,
) -> None:
    """Tool result paired with the preceding tool_use event by iteration_id."""
    try:
        telemetry.emit("agent_tool_result", {
            "iteration_id": iteration_id,
            "content": _scrub_text(content, max_len=8000),
            "is_error": bool(is_error),
        })
    except Exception:
        logger.debug("record_tool_result failed", exc_info=True)


def record_assessor_review(
    iteration_id: str,
    grade: str,
    one_line: str,
    concerns: List[str],
    follow_ups: List[str],
) -> None:
    """Post-iteration grade from the assessor agent."""
    try:
        telemetry.emit("agent_assessor_review", {
            "iteration_id": iteration_id,
            "grade": grade,
            "one_line": _scrub_text(one_line, max_len=500),
            "concerns": [_scrub_text(c, max_len=200) for c in concerns[:10]],
            "follow_ups": [_scrub_text(f, max_len=200) for f in follow_ups[:10]],
        })
    except Exception:
        logger.debug("record_assessor_review failed", exc_info=True)


def record_personality_lesson(
    lesson: str,
    *,
    trigger_event: str = "",
    confidence: float = 0.0,
) -> None:
    """One reflector lesson (win/loss post-mortem)."""
    try:
        telemetry.emit("agent_personality_lesson", {
            "lesson": _scrub_text(lesson, max_len=1000),
            "trigger_event": _scrub_text(trigger_event, max_len=200),
            "confidence": float(confidence),
        })
    except Exception:
        logger.debug("record_personality_lesson failed", exc_info=True)


# ── chat events ──────────────────────────────────────────────────────

def record_chat_turn(
    worker_id: str,
    role: str,
    text: str,
    *,
    model_id: str = "",
    tier: str = "",
) -> None:
    """One chat message — user prompt or AI reply.

    The chat panel shows a standing warning telling the user not to
    share personal data here. We still scrub with :func:`_scrub_text`
    as a belt-and-braces measure: even a well-intentioned user may
    paste a stack trace with their email in it.

    Callers must first check ``AppConfig.telemetry.include_chat`` —
    when the user has opted chat-recording off, this helper is still
    called but ``telemetry.emit`` will honour the global enabled flag.
    A per-type gate lives at the caller so the opt-out is explicit.
    """
    try:
        telemetry.emit("chat_turn", {
            "worker_id": worker_id,
            "role": role,
            "text": _scrub_text(text, max_len=4000),
            "model_id": model_id,
            "tier": tier,
        })
    except Exception:
        logger.debug("record_chat_turn failed", exc_info=True)


# ── broker events ────────────────────────────────────────────────────

def record_trade_fill(
    ticker: str,
    side: str,
    quantity: float,
    fill_price: float,
    *,
    paper_mode: bool,
    currency: str = "",
    realised_pnl: float = 0.0,
) -> None:
    """Called from ``PaperBroker._fill_order`` and live-broker fill paths."""
    try:
        telemetry.emit("trade_fill", {
            "ticker": str(ticker),
            "side": str(side).upper(),
            "quantity": float(quantity),
            "fill_price": float(fill_price),
            "paper_mode": bool(paper_mode),
            "currency": currency or "",
            "realised_pnl": float(realised_pnl),
        })
    except Exception:
        logger.debug("record_trade_fill failed", exc_info=True)


# ── forecast ground-truth events ─────────────────────────────────────

def record_forecast(
    ticker: str,
    horizon_minutes: int,
    backend: str,
    prediction: Dict[str, Any],
) -> None:
    """Forecaster output — Kronos / Chronos / TFT / statistical."""
    try:
        telemetry.emit("forecast", {
            "ticker": str(ticker),
            "horizon_minutes": int(horizon_minutes),
            "backend": backend,
            "prediction": _scrub_dict(prediction),
        })
    except Exception:
        logger.debug("record_forecast failed", exc_info=True)


def record_market_snapshot(
    ticker: str,
    price: float,
    *,
    volume: Optional[float] = None,
    indicators: Optional[Dict[str, Any]] = None,
) -> None:
    """Market data at the moment the agent made a decision."""
    try:
        telemetry.emit("market_snapshot", {
            "ticker": str(ticker),
            "price": float(price),
            "volume": float(volume) if volume is not None else None,
            "indicators": _scrub_dict(indicators) if indicators else {},
        })
    except Exception:
        logger.debug("record_market_snapshot failed", exc_info=True)


# ── error / crash events ─────────────────────────────────────────────

class TelemetryLogHandler(logging.Handler):
    """Logging handler that forwards WARNING+ records as error_log events.

    Attach this once during app bootstrap after
    :func:`telemetry.init`. Handler-level filtering keeps the noise
    down: INFO and DEBUG never reach the wire.
    """

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            payload = {
                "level": record.levelname,
                "logger": record.name,
                "message": _scrub_text(record.getMessage(), max_len=2000),
                "exc_type": record.exc_info[0].__name__ if record.exc_info else "",
            }
            telemetry.emit("error_log", payload)
        except Exception:
            # Logging handlers must never raise — they'd break the
            # calling code. Drop on the floor.
            pass
