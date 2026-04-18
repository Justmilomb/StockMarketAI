"""render_system_prompt injects the trader personality."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _base_config() -> dict:
    return {
        "agent": {"paper_mode": True, "cadence_seconds": 90},
        "paper_broker": {"currency": "GBP"},
    }


def test_render_without_personality_has_placeholders_filled() -> None:
    from core.agent.prompts import render_system_prompt

    s = render_system_prompt(_base_config(), personality=None)
    assert "Your trader personality" in s
    assert "{personality_name}" not in s
    assert "{personality_rules_block}" not in s
    assert "Exit discipline" not in s


def test_render_with_personality_shows_seed_rules_and_lessons(tmp_path: Path) -> None:
    from core.agent.prompts import render_system_prompt
    from core.trader_personality import TraderPersonality

    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    p.add_rule("hold airline dips 30m", confidence="learned")
    p.add_lesson("panicked on JBLU, missed recovery", tags=["JBLU", "patience"])

    s = render_system_prompt(_base_config(), personality=p)
    assert p.seed.name in s
    assert p.seed.archetype in s
    assert "hold airline dips 30m" in s
    assert "learned" in s
    assert "panicked on JBLU" in s
    assert "JBLU" in s


def test_render_with_empty_personality_uses_none_placeholders(tmp_path: Path) -> None:
    from core.agent.prompts import render_system_prompt
    from core.trader_personality import TraderPersonality

    p = TraderPersonality(tmp_path / "p.json")
    p.load()

    s = render_system_prompt(_base_config(), personality=p)
    assert "none yet" in s  # both rules and lessons default copy
