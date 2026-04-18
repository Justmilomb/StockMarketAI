"""position_entry_time reads the most recent BUY fill from the audit log."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.paper_broker import PaperBroker


def test_entry_time_from_latest_buy_fill(tmp_path: Path) -> None:
    audit = tmp_path / "paper_orders.jsonl"
    t0 = (datetime.now(tz=timezone.utc) - timedelta(minutes=75)).isoformat()
    t1 = (datetime.now(tz=timezone.utc) - timedelta(minutes=10)).isoformat()
    with audit.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": t0, "order_id": "o1", "ticker": "AAPL",
                            "side": "BUY", "quantity": 1.0, "fill_price": 100.0,
                            "status": "FILLED"}) + "\n")
        f.write(json.dumps({"timestamp": t1, "order_id": "o2", "ticker": "AAPL",
                            "side": "BUY", "quantity": 1.0, "fill_price": 101.0,
                            "status": "FILLED"}) + "\n")
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=audit,
        starting_cash=500.0,
        currency="GBP",
    )
    entry = broker.position_entry_time("AAPL")
    assert entry is not None
    age_min = (datetime.now(tz=timezone.utc) - entry).total_seconds() / 60
    assert 5 <= age_min <= 30


def test_entry_time_none_when_no_history(tmp_path: Path) -> None:
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "nope.jsonl",
        starting_cash=100.0,
        currency="GBP",
    )
    assert broker.position_entry_time("AAPL") is None


def test_entry_time_ignores_sells_and_queued(tmp_path: Path) -> None:
    audit = tmp_path / "paper_orders.jsonl"
    t_buy = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
    t_queued = (datetime.now(tz=timezone.utc) - timedelta(minutes=20)).isoformat()
    t_sell = (datetime.now(tz=timezone.utc) - timedelta(minutes=5)).isoformat()
    with audit.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": t_buy, "order_id": "o1", "ticker": "AAPL",
                            "side": "BUY", "quantity": 1.0, "fill_price": 100.0,
                            "status": "FILLED"}) + "\n")
        f.write(json.dumps({"timestamp": t_queued, "order_id": "o2", "ticker": "AAPL",
                            "side": "BUY", "quantity": 1.0, "status": "QUEUED"}) + "\n")
        f.write(json.dumps({"timestamp": t_sell, "order_id": "o3", "ticker": "AAPL",
                            "side": "SELL", "quantity": 1.0, "fill_price": 101.0,
                            "status": "FILLED"}) + "\n")
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=audit,
        starting_cash=500.0,
        currency="GBP",
    )
    entry = broker.position_entry_time("AAPL")
    assert entry is not None
    age_min = (datetime.now(tz=timezone.utc) - entry).total_seconds() / 60
    # Must be the 2-hour-old FILLED BUY, not the QUEUED or SELL.
    assert 110 <= age_min <= 130
