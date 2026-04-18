"""Per-install trader personality — the terminal's evolving character.

Each blank install gets its own ``trader_personality.json`` file with:

* ``seed`` — a randomly-picked archetype / risk profile / name generated
  at first run. Fixed for the install's lifetime. Gives the agent a
  unique starting voice so no two terminals feel identical.
* ``lessons`` — an append-only log of lessons the agent writes after
  reflecting on a closed round-trip trade.
* ``rules`` — editable trading rules the agent has promoted from its
  lessons. The agent can ``add_rule`` / ``remove_rule`` as it learns
  and unlearns.
* ``stats`` — cumulative reflection counts.

The file is never synced across installs.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PersonalitySeed:
    name: str
    archetype: str
    risk_tolerance: str
    initial_traits: List[str]
    created_at: str


class TraderPersonality:
    """Load / mutate / save the trader personality JSON file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self.seed: PersonalitySeed = PersonalitySeed(
            name="", archetype="", risk_tolerance="", initial_traits=[], created_at="",
        )
        self.lessons: List[Dict[str, Any]] = []
        self.rules: List[Dict[str, Any]] = []
        self.stats: Dict[str, int] = {"total_trades_reflected_on": 0, "wins": 0, "losses": 0}
        self.reflection_cursor: Optional[str] = None

    # ── persistence ──────────────────────────────────────────────────

    def load(self) -> None:
        if not self._path.exists():
            self._seed_new()
            self.save()
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("trader_personality: corrupt file at %s (%s); reseeding", self._path, e)
            self._seed_new()
            self.save()
            return
        seed = raw.get("seed") or {}
        self.seed = PersonalitySeed(
            name=str(seed.get("name", "") or ""),
            archetype=str(seed.get("archetype", "") or ""),
            risk_tolerance=str(seed.get("risk_tolerance", "") or ""),
            initial_traits=list(seed.get("initial_traits") or []),
            created_at=str(seed.get("created_at", "") or ""),
        )
        if not self.seed.name or not self.seed.archetype:
            self._seed_new()
        self.lessons = list(raw.get("lessons") or [])
        self.rules = list(raw.get("rules") or [])
        self.stats = dict(raw.get("stats") or {"total_trades_reflected_on": 0, "wins": 0, "losses": 0})
        self.reflection_cursor = raw.get("reflection_cursor")

    def save(self) -> None:
        payload = {
            "seed": asdict(self.seed),
            "lessons": self.lessons,
            "rules": self.rules,
            "stats": self.stats,
            "reflection_cursor": self.reflection_cursor,
        }
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._path)

    # ── mutators ─────────────────────────────────────────────────────

    def add_lesson(self, lesson: str, tags: Optional[List[str]] = None,
                   trade: Optional[Dict[str, Any]] = None) -> int:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lesson": str(lesson).strip(),
            "tags": list(tags or []),
        }
        if trade:
            entry["trade"] = trade
        self.lessons.append(entry)
        self.save()
        return len(self.lessons) - 1

    def add_rule(self, rule: str, confidence: str = "experimental",
                 source_lesson_idx: Optional[int] = None) -> int:
        entry: Dict[str, Any] = {
            "added_at": datetime.now(timezone.utc).isoformat(),
            "rule": str(rule).strip(),
            "confidence": str(confidence or "experimental"),
        }
        if source_lesson_idx is not None:
            entry["source_lesson_idx"] = int(source_lesson_idx)
        self.rules.append(entry)
        self.save()
        return len(self.rules) - 1

    def remove_rule(self, index: int) -> bool:
        if 0 <= index < len(self.rules):
            self.rules.pop(index)
            self.save()
            return True
        return False

    def update_stats(self, win: bool) -> None:
        self.stats["total_trades_reflected_on"] = self.stats.get("total_trades_reflected_on", 0) + 1
        key = "wins" if win else "losses"
        self.stats[key] = self.stats.get(key, 0) + 1
        self.save()

    def set_reflection_cursor(self, cursor: str) -> None:
        self.reflection_cursor = cursor
        self.save()

    # ── views ────────────────────────────────────────────────────────

    def recent_lessons(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self.lessons[-n:])

    def active_rules(self) -> List[Dict[str, Any]]:
        return list(self.rules)

    def summary(self) -> Dict[str, Any]:
        return {
            "seed": asdict(self.seed),
            "rules": self.active_rules(),
            "recent_lessons": self.recent_lessons(10),
            "stats": dict(self.stats),
        }

    # ── internal ─────────────────────────────────────────────────────

    def _seed_new(self) -> None:
        from core.personality_seeder import generate_seed
        self.seed = generate_seed()
