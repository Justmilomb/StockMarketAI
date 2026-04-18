"""Research swarm role definitions.

Each role describes a specialised research agent: what it focuses on,
how often it fires, and which model tier it uses. The SwarmCoordinator
rotates all 20 roles through a bounded worker pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ResearchRole:
    """One research agent specialisation."""

    role_id: str
    tier: str          # "quick" or "deep"
    model_tier: str    # "simple" (Haiku), "medium" (Sonnet), "complex" (Opus)
    cadence_seconds: int  # how often this role should fire
    focus: str         # one-line description for the system prompt
    default_tickers: bool  # True = uses watchlist tickers; False = broad market


# ── Tier 1 — Quick-Reaction Squad ─────────────────────────────────────────────

_QUICK_ROLES: List[ResearchRole] = [
    ResearchRole(
        role_id="tech_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Tech sector breaking news and price spikes. Monitor FAANG, semis, AI plays.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="healthcare_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Healthcare and biotech: FDA decisions, trial results, drug approvals.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="energy_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Energy sector, oil prices, renewables, geopolitical supply disruptions.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="finance_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Banks, interest rate signals, Fed commentary, financial sector moves.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="consumer_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Consumer and retail: earnings surprises, sentiment shifts, spending data.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="reddit_scanner",
        tier="quick",
        model_tier="simple",
        cadence_seconds=150,
        focus="Reddit WSB, r/stocks, r/investing: hot threads, unusual volume of mentions.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="stocktwits_scanner",
        tier="quick",
        model_tier="simple",
        cadence_seconds=150,
        focus="StockTwits trending tickers, sentiment ratio, message velocity spikes.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="grok_miner",
        tier="quick",
        model_tier="simple",
        cadence_seconds=180,
        focus="X/Twitter intelligence via Grok AI: social buzz, rumours, retail sentiment.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="news_scanner",
        tier="quick",
        model_tier="simple",
        cadence_seconds=120,
        focus="Breaking news from Google News, BBC, MarketWatch: earnings, M&A, guidance.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="earnings_watcher",
        tier="quick",
        model_tier="simple",
        cadence_seconds=180,
        focus="Earnings calendar: pre-market and after-hours movers, beats vs misses.",
        default_tickers=False,
    ),
]

# ── Tier 2 — Deep Research Squad ──────────────────────────────────────────────

_DEEP_ROLES: List[ResearchRole] = [
    ResearchRole(
        role_id="sector_analyst_tech",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Deep tech sector analysis: competitive dynamics, product cycles, capex trends.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="sector_analyst_health",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Biotech pipeline analysis, regulatory landscape, patent cliffs.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="sector_analyst_industrial",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Industrials, commodities, supply chain disruptions, infrastructure spending.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="macro_researcher",
        tier="deep",
        model_tier="medium",
        cadence_seconds=900,
        focus="Macro research: interest rates, inflation, GDP, central bank policy shifts.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="geopolitical_researcher",
        tier="deep",
        model_tier="medium",
        cadence_seconds=900,
        focus="Geopolitical risk: trade wars, sanctions, political instability, tariffs.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="sentiment_aggregator_social",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Cross-platform sentiment synthesis: aggregate Reddit + StockTwits + X signals.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="sentiment_aggregator_news",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="News sentiment trends: detect shifts across BBC, MarketWatch, Google News.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="contrarian_hunter",
        tier="deep",
        model_tier="medium",
        cadence_seconds=900,
        focus="Find where crowd consensus is wrong: overcrowded shorts, contrarian setups.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="catalyst_scanner",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Upcoming catalysts: earnings dates, FDA dates, stock splits, buyback programmes.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="technical_researcher",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus="Chart patterns, support/resistance, volume analysis, breakout candidates.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="market_scanner",
        tier="deep",
        model_tier="medium",
        cadence_seconds=600,
        focus=(
            "Broad-market discovery. Find tickers with fresh catalysts that are NOT "
            "already on the watchlist: breakouts, catalyst-driven small-caps, sector "
            "rotations, unusual volume spikes. Use get_market_buzz, get_news with "
            "empty tickers, and social-buzz tools. Submit findings with the "
            "discovered ticker and a concise catalyst in headline. For pure "
            "market-wide signals with no single ticker, submit with ticker=null. "
            "Cap confidence at 60 percent — the supervisor corroborates before "
            "adding to the watchlist."
        ),
        default_tickers=False,
    ),
]

# ── Module-level exports ───────────────────────────────────────────────────────

ALL_ROLES: List[ResearchRole] = _QUICK_ROLES + _DEEP_ROLES

_ROLES_BY_ID: Dict[str, ResearchRole] = {role.role_id: role for role in ALL_ROLES}


def get_role(role_id: str) -> Optional[ResearchRole]:
    """Return the ResearchRole with the given role_id, or None if not found.

    Args:
        role_id: The unique identifier for the role (e.g. "grok_miner").

    Returns:
        The matching ResearchRole, or None if role_id is unknown.
    """
    return _ROLES_BY_ID.get(role_id)
