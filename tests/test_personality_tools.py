"""Agent-facing MCP tools for reading and mutating the personality."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _load_personality(tmp_path: Path):
    from core.trader_personality import TraderPersonality
    p = TraderPersonality(tmp_path / "p.json")
    p.load()
    return p


def test_get_personality_returns_summary(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)
    p.add_rule("cut losers fast", confidence="experimental")

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.get_personality.handler({})
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert out["seed"]["archetype"]
    assert any(rule["rule"] == "cut losers fast" for rule in out["rules"])


def test_get_personality_when_missing_returns_error() -> None:
    from core.agent.tools import personality_tools

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=None):
            r = await personality_tools.get_personality.handler({})
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out


def test_add_lesson_persists(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.add_lesson.handler({
                "lesson": "Patience on airline dips",
                "tags": ["airlines", "patience"],
            })
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert out["added_index"] == 0
    assert p.lessons[0]["lesson"] == "Patience on airline dips"


def test_add_lesson_rejects_blank(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.add_lesson.handler({"lesson": "   "})
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out


def test_add_and_remove_rule(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)

    async def add() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.add_rule.handler({
                "rule": "Give airline trades at least 4h",
                "confidence": "learned",
            })
            return json.loads(r["content"][0]["text"])

    async def remove() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.remove_rule.handler({"index": 0})
            return json.loads(r["content"][0]["text"])

    asyncio.run(add())
    assert len(p.rules) == 1
    out = asyncio.run(remove())
    assert out["removed"] is True
    assert p.rules == []


def test_remove_rule_rejects_out_of_range(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.remove_rule.handler({"index": 99})
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert out["removed"] is False


def test_list_rules(tmp_path: Path) -> None:
    from core.agent.tools import personality_tools

    p = _load_personality(tmp_path)
    p.add_rule("rule A")
    p.add_rule("rule B")

    async def run() -> dict:
        with patch.object(personality_tools, "_get_personality", return_value=p):
            r = await personality_tools.list_rules.handler({})
            return json.loads(r["content"][0]["text"])

    out = asyncio.run(run())
    assert len(out["rules"]) == 2
    assert out["rules"][0]["index"] == 0
    assert out["rules"][1]["rule"] == "rule B"
