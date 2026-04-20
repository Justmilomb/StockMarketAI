"""Unit tests for core.alt_data._cache — shared TTL store."""
from __future__ import annotations

import time

from core.alt_data import _cache


def setup_function() -> None:
    _cache._store.clear()


def test_get_returns_none_for_missing_key() -> None:
    assert _cache.get("does-not-exist") is None


def test_put_then_get_returns_value() -> None:
    _cache.put("k", {"v": 1}, ttl=60)
    assert _cache.get("k") == {"v": 1}


def test_get_returns_none_after_ttl_expires(monkeypatch) -> None:
    real_time = time.time
    now = [real_time()]
    monkeypatch.setattr(_cache.time, "time", lambda: now[0])
    _cache.put("k", "v", ttl=10)
    now[0] += 5
    assert _cache.get("k") == "v"
    now[0] += 10
    assert _cache.get("k") is None


def test_isolated_keys_do_not_collide() -> None:
    _cache.put("a", 1, ttl=60)
    _cache.put("b", 2, ttl=60)
    assert _cache.get("a") == 1
    assert _cache.get("b") == 2
