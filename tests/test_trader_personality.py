"""TraderPersonality owns the per-install personality JSON."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.trader_personality import TraderPersonality


def test_load_creates_blank_file(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "personality.json")
    p.load()
    assert p.seed.name
    assert p.seed.archetype
    assert p.lessons == []
    assert p.rules == []
    assert (tmp_path / "personality.json").exists()


def test_add_lesson_persists(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    p.add_lesson("Sold JBLU too early on a dip", tags=["premature exit", "airlines"])
    p2 = TraderPersonality(tmp_path / "p.json")
    p2.load()
    assert len(p2.lessons) == 1
    assert p2.lessons[0]["lesson"] == "Sold JBLU too early on a dip"
    assert "airlines" in p2.lessons[0]["tags"]


def test_add_and_remove_rule(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    idx = p.add_rule("Give airline trades at least 4h before exiting on dips <3%",
                     confidence="learned")
    assert idx == 0
    assert p.rules[0]["confidence"] == "learned"
    assert p.remove_rule(0) is True
    assert p.rules == []


def test_remove_rule_rejects_out_of_range(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    assert p.remove_rule(99) is False
    assert p.remove_rule(-1) is False


def test_update_stats(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    p.update_stats(win=True)
    p.update_stats(win=False)
    p.update_stats(win=True)
    assert p.stats["wins"] == 2
    assert p.stats["losses"] == 1
    assert p.stats["total_trades_reflected_on"] == 3


def test_corrupt_file_reseeds(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not valid json", encoding="utf-8")
    p = TraderPersonality(path)
    p.load()
    assert p.seed.name
    assert p.lessons == []


def test_reflection_cursor_persists(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    p.set_reflection_cursor("order-42")
    p2 = TraderPersonality(tmp_path / "p.json")
    p2.load()
    assert p2.reflection_cursor == "order-42"


def test_summary_shape(tmp_path: Path) -> None:
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    p.add_rule("cut losers fast")
    p.add_lesson("learned something")
    s = p.summary()
    assert "seed" in s and "rules" in s and "recent_lessons" in s and "stats" in s
    assert s["seed"]["name"]
