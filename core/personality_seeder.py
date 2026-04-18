"""First-run personality seeder.

Randomly draws an archetype + risk profile + name from a fixed pool so
every terminal install starts with a different voice. The lesson /
rule accumulator on top of this seed is what makes each terminal
genuinely unique over time.
"""
from __future__ import annotations

import random
import secrets
from datetime import datetime, timezone
from typing import List

from core.trader_personality import PersonalitySeed


ARCHETYPES: List[str] = [
    "contrarian",
    "momentum",
    "mean-reversion",
    "breakout",
    "value-hunter",
    "news-scalper",
    "trend-follower",
    "sector-rotator",
    "macro-tactical",
    "event-driven",
]

RISK_PROFILES: List[str] = ["cautious", "balanced", "aggressive"]

TRAIT_POOL: List[str] = [
    "patient", "decisive", "skeptical", "curious", "disciplined",
    "imaginative", "cautious", "opportunistic", "data-obsessed",
    "intuitive", "methodical", "restless", "stoic", "witty",
    "pragmatic", "quietly confident",
]


def _random_name() -> str:
    return "Trader-" + secrets.token_hex(2).upper()


def generate_seed() -> PersonalitySeed:
    archetype = random.choice(ARCHETYPES)
    risk = random.choice(RISK_PROFILES)
    traits = random.sample(TRAIT_POOL, k=random.randint(2, 4))
    return PersonalitySeed(
        name=_random_name(),
        archetype=archetype,
        risk_tolerance=risk,
        initial_traits=traits,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
