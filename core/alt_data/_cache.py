"""Shared in-process TTL cache for alt-data API clients.

Key format is opaque — each client namespaces its own keys.
Expired entries are evicted lazily on the next get() for that key.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def get(key: str) -> Optional[Any]:
    """Return cached value for *key*, or None if missing or expired."""
    with _lock:
        entry = _store.get(key)
        if entry is not None and time.time() < entry[0]:
            return entry[1]
        return None


def put(key: str, value: Any, ttl: int = 3600) -> None:
    """Store *value* under *key* for *ttl* seconds."""
    with _lock:
        _store[key] = (time.time() + ttl, value)
