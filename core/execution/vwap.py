"""TWAP / VWAP execution planner.

Generates a list of child-order slices over *duration_minutes*. The
actual broker bridge still places one order per slice — this module is
the scheduling layer.

TWAP: equal-sized slices evenly spaced.

VWAP: slice size proportional to a hand-built intraday volume profile
(U-shape: heavier open, lighter mid-day, heaviest close). If the plan
straddles the close the close-weighting dominates; plans that sit
entirely in mid-day default closer to TWAP.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_VOLUME_PROFILE: List[float] = [0.15, 0.10, 0.10, 0.05, 0.05, 0.10, 0.10, 0.15, 0.20]


def _profile_weight(fraction_of_session: float) -> float:
    if fraction_of_session <= 0:
        return _VOLUME_PROFILE[0]
    if fraction_of_session >= 1:
        return _VOLUME_PROFILE[-1]
    idx = fraction_of_session * (len(_VOLUME_PROFILE) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(_VOLUME_PROFILE) - 1)
    frac = idx - lo
    return _VOLUME_PROFILE[lo] * (1 - frac) + _VOLUME_PROFILE[hi] * frac


def plan_execution(
    ticker: str,
    side: str,
    total_shares: float,
    duration_minutes: int,
    strategy: str = "twap",
    slices: int = 6,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if total_shares <= 0:
        return {"error": "total_shares must be > 0"}
    if duration_minutes <= 0:
        return {"error": "duration_minutes must be > 0"}
    if slices <= 0:
        return {"error": "slices must be > 0"}

    strategy = strategy.lower()
    now = now or datetime.now(timezone.utc)

    slice_minutes = duration_minutes / slices
    if strategy == "twap":
        weights = [1.0 / slices] * slices
    elif strategy == "vwap":
        session_start = now.replace(hour=14, minute=30, second=0, microsecond=0)
        session_end = now.replace(hour=21, minute=0, second=0, microsecond=0)
        session_seconds = (session_end - session_start).total_seconds() or 1.0
        raw: List[float] = []
        for i in range(slices):
            centre = now + timedelta(minutes=slice_minutes * (i + 0.5))
            frac = (centre - session_start).total_seconds() / session_seconds
            frac = max(0.0, min(1.0, frac))
            raw.append(_profile_weight(frac))
        total_w = sum(raw) or 1.0
        weights = [w / total_w for w in raw]
    else:
        return {"error": f"unknown strategy {strategy!r}"}

    slices_out: List[Dict[str, Any]] = []
    for i, w in enumerate(weights):
        t_offset = timedelta(minutes=slice_minutes * i)
        slices_out.append({
            "index": i,
            "fire_at": (now + t_offset).isoformat(),
            "shares": round(total_shares * w, 6),
            "weight": round(w, 4),
        })
    drift = total_shares - sum(s["shares"] for s in slices_out)
    slices_out[-1]["shares"] = round(slices_out[-1]["shares"] + drift, 6)

    return {
        "ticker": ticker.upper(),
        "side": side.upper(),
        "strategy": strategy,
        "total_shares": total_shares,
        "duration_minutes": duration_minutes,
        "slices": slices_out,
    }
