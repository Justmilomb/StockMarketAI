"""generate_seed picks a unique-looking personality."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.personality_seeder import ARCHETYPES, RISK_PROFILES, generate_seed


def test_generated_seed_has_all_fields() -> None:
    s = generate_seed()
    assert s.name
    assert s.archetype in ARCHETYPES
    assert s.risk_tolerance in RISK_PROFILES
    assert len(s.initial_traits) >= 2
    assert s.created_at


def test_seeds_are_probabilistically_distinct() -> None:
    seeds = [generate_seed() for _ in range(50)]
    names = {s.name for s in seeds}
    assert len(names) > 40  # ~16^4 space so collisions rare
    archetypes = {s.archetype for s in seeds}
    assert len(archetypes) > 1
