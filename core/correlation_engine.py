"""Hard-coded sector correlation engine.

When a scraped news item mentions a known catalyst (oil price up,
defense spending up, gold rally, big-tech selloff), this engine emits
trade *suggestions* on the related tickers. Suggestions land in the
``correlation_signals`` table with status ``pending`` so the agent can
acknowledge or dismiss each one on the next iteration.

Correlations are intentionally curated (not learned) — the user has
high conviction about the linkages and wants the system to act on
them without latency for retraining or backtesting.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorrelationRule:
    """One sector trigger with the tickers it influences."""
    trigger_key: str
    keywords: Tuple[str, ...]
    targets: Tuple[Tuple[str, str, str], ...]  # (ticker, direction, action)


@dataclass(frozen=True)
class CorrelationMatch:
    """One matched rule applied to one target."""
    trigger_key: str
    ticker: str
    direction: str
    suggested_action: str
    matched_keyword: str


# ── rule library ─────────────────────────────────────────────────────────
#
# Format: trigger_key → (keywords[], (ticker, direction, action)[])
#
# direction = "up" | "down" — the *sector* signal. The suggested_action
# already accounts for whether the linked ticker moves with or against
# the signal (e.g. higher oil → buy oil majors; tech selloff → consider
# trimming megacaps but possibly buy bond ETFs).

CORRELATION_RULES: Tuple[CorrelationRule, ...] = (
    CorrelationRule(
        trigger_key="oil_up",
        keywords=("oil price rises", "oil rally", "crude up", "opec cut",
                  "oil prices surge", "brent up", "wti up"),
        targets=(
            ("XOM", "up", "buy"),
            ("CVX", "up", "buy"),
            ("BP.L", "up", "buy"),
            ("SHEL.L", "up", "buy"),
        ),
    ),
    CorrelationRule(
        trigger_key="oil_down",
        keywords=("oil price falls", "crude down", "oil rout", "oil slump",
                  "brent down", "wti down"),
        targets=(
            ("XOM", "down", "sell"),
            ("CVX", "down", "sell"),
            ("BP.L", "down", "sell"),
            ("SHEL.L", "down", "sell"),
        ),
    ),
    CorrelationRule(
        trigger_key="tech_up",
        keywords=("tech rally", "ai boom", "semiconductor surge",
                  "nvda earnings beat", "tech leads gains"),
        targets=(
            ("NVDA", "up", "buy"),
            ("AAPL", "up", "buy"),
            ("MSFT", "up", "buy"),
            ("GOOGL", "up", "buy"),
        ),
    ),
    CorrelationRule(
        trigger_key="tech_down",
        keywords=("tech selloff", "ai bubble", "semiconductor slump",
                  "tech rout", "nvda earnings miss"),
        targets=(
            ("NVDA", "down", "sell"),
            ("AAPL", "down", "sell"),
            ("MSFT", "down", "sell"),
            ("GOOGL", "down", "sell"),
        ),
    ),
    CorrelationRule(
        trigger_key="gold_up",
        keywords=("gold rally", "gold price surges", "gold up", "safe haven"),
        targets=(
            ("GLD", "up", "buy"),
            ("NEM", "up", "buy"),
            ("GOLD", "up", "buy"),
        ),
    ),
    CorrelationRule(
        trigger_key="gold_down",
        keywords=("gold falls", "gold rout", "gold down"),
        targets=(
            ("GLD", "down", "sell"),
            ("NEM", "down", "sell"),
            ("GOLD", "down", "sell"),
        ),
    ),
    CorrelationRule(
        trigger_key="defense_up",
        keywords=("defense spending", "military aid", "ukraine aid", "nato",
                  "defense contract", "missile order", "weapons package"),
        targets=(
            ("LMT", "up", "buy"),
            ("RTX", "up", "buy"),
            ("BA.L", "up", "buy"),
            ("RR.L", "up", "buy"),
        ),
    ),
    CorrelationRule(
        trigger_key="rate_up",
        keywords=("rate hike", "fed hikes", "interest rate increase",
                  "boe hikes", "ecb hikes"),
        targets=(
            ("XLF", "up", "buy"),
            ("JPM", "up", "buy"),
            ("BAC", "up", "buy"),
        ),
    ),
    CorrelationRule(
        trigger_key="rate_down",
        keywords=("rate cut", "fed cuts", "interest rate cut",
                  "boe cuts", "ecb cuts"),
        targets=(
            ("XLF", "down", "sell"),
            ("QQQ", "up", "buy"),
            ("XLK", "up", "buy"),
        ),
    ),
)


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for substring matching."""
    return re.sub(r"\s+", " ", (text or "").lower())


def match_correlations(
    text: str,
    watchlist: Optional[List[str]] = None,
) -> List[CorrelationMatch]:
    """Scan ``text`` for correlation keywords and return matches.

    When ``watchlist`` is supplied, only matches whose target ticker is
    on the watchlist are returned — keeps the suggestion stream
    relevant. Pass ``None`` to get every match (used by tests).
    """
    if not text:
        return []
    haystack = _normalise(text)

    watchlist_set: Optional[set] = None
    if watchlist:
        watchlist_set = {t.upper() for t in watchlist}

    matches: List[CorrelationMatch] = []
    seen: set = set()
    for rule in CORRELATION_RULES:
        for kw in rule.keywords:
            if kw in haystack:
                for ticker, direction, action in rule.targets:
                    if watchlist_set is not None and ticker.upper() not in watchlist_set:
                        continue
                    key = (rule.trigger_key, ticker)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append(CorrelationMatch(
                        trigger_key=rule.trigger_key,
                        ticker=ticker,
                        direction=direction,
                        suggested_action=action,
                        matched_keyword=kw,
                    ))
                break  # one keyword hit per rule is enough
    return matches


def queue_correlation_action(
    db_path: Path | str,
    match: CorrelationMatch,
    *,
    source_text: str = "",
    source_url: str = "",
) -> int:
    """Insert a pending correlation signal. Returns the row id."""
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            """
            INSERT INTO correlation_signals
                (trigger_key, ticker, direction, suggested_action,
                 source_text, source_url, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                match.trigger_key, match.ticker, match.direction,
                match.suggested_action, source_text[:500], source_url[:500],
            ),
        )
        row_id = cursor.lastrowid
    logger.info(
        "[correlation] queued %s on %s (%s) from %r",
        match.suggested_action, match.ticker, match.trigger_key,
        match.matched_keyword,
    )
    return int(row_id or 0)


def get_pending_signals(
    db_path: Path | str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return every pending correlation signal, newest first."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, trigger_key, ticker, direction, suggested_action,
                   source_text, source_url, status, created_at
            FROM correlation_signals
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_signal(
    db_path: Path | str,
    signal_id: int,
    new_status: str = "acknowledged",
) -> bool:
    """Mark a signal as acknowledged (or dismissed). Returns True on success."""
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE correlation_signals
            SET status = ?, acknowledged_at = datetime('now')
            WHERE id = ? AND status = 'pending'
            """,
            (new_status, int(signal_id)),
        )
        return cursor.rowcount > 0
