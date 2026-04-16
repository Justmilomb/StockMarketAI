"""Research queue — priority scheduling for the swarm.

Tracks when each role last fired and decides which roles are due. Quick-
reaction roles get priority over deep-research roles. The
SwarmCoordinator reads from this queue on every tick.
"""
from __future__ import annotations

import time
from typing import Dict, List

from core.agent.research_roles import ALL_ROLES, ResearchRole


class ResearchQueue:
    """Cadence-based scheduler for 20 research roles."""

    def __init__(self) -> None:
        self._last_fired: Dict[str, float] = {}

    def mark_fired(self, role_id: str) -> None:
        """Record that a role just started running."""
        self._last_fired[role_id] = time.monotonic()

    def get_due_roles(self) -> List[ResearchRole]:
        """Return roles whose cadence has elapsed, quick-first."""
        now = time.monotonic()
        due: List[ResearchRole] = []
        for role in ALL_ROLES:
            last = self._last_fired.get(role.role_id)
            if last is None or (now - last) >= role.cadence_seconds:
                due.append(role)
        # Sort: quick roles first (priority), then by cadence (shorter = more urgent).
        due.sort(key=lambda r: (0 if r.tier == "quick" else 1, r.cadence_seconds))
        return due

    def reset(self) -> None:
        """Clear all fire times (used on restart)."""
        self._last_fired.clear()
