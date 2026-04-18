from __future__ import annotations

from datetime import datetime, timezone

from core.execution.vwap import plan_execution


def test_twap_equal_slices():
    plan = plan_execution(
        ticker="TSLA", side="BUY", total_shares=100.0,
        duration_minutes=60, strategy="twap", slices=6,
    )
    assert len(plan["slices"]) == 6
    assert all(abs(s["shares"] - 100.0 / 6) < 1e-2 for s in plan["slices"][:-1])
    assert abs(sum(s["shares"] for s in plan["slices"]) - 100.0) < 1e-6


def test_vwap_back_loaded_when_close_approaching():
    plan = plan_execution(
        ticker="TSLA", side="SELL", total_shares=100.0,
        duration_minutes=60, strategy="vwap", slices=4,
        now=datetime(2026, 4, 18, 19, 30, tzinfo=timezone.utc),
    )
    sizes = [s["shares"] for s in plan["slices"]]
    assert sizes[-1] >= sizes[0]


def test_invalid_total_returns_error():
    plan = plan_execution("TSLA", "BUY", 0.0, 60, "twap", 4)
    assert "error" in plan


def test_invalid_strategy_returns_error():
    plan = plan_execution("TSLA", "BUY", 100.0, 60, "iceberg", 4)
    assert "error" in plan


def test_slices_include_fire_at_and_weight():
    plan = plan_execution(
        ticker="AAPL", side="BUY", total_shares=50.0,
        duration_minutes=30, strategy="twap", slices=3,
    )
    for s in plan["slices"]:
        assert "fire_at" in s
        assert "weight" in s
        assert 0 <= s["weight"] <= 1
