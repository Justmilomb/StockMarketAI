"""Order-history filtering: RESET rows hidden, QUEUED collapsed into terminal status."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.paper_broker import PaperBroker


def _write_audit(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_history_hides_reset_entries(tmp_path: Path) -> None:
    audit = tmp_path / "paper_orders.jsonl"
    now = datetime.now(tz=timezone.utc).isoformat()
    _write_audit(audit, [
        {"timestamp": now, "status": "RESET", "cash_free": 100.0, "currency": "GBP"},
        {"timestamp": now, "order_id": "a1", "ticker": "AAPL", "side": "BUY",
         "quantity": 1.0, "fill_price": 100.0, "status": "FILLED"},
    ])
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=audit,
        starting_cash=100.0,
        currency="GBP",
    )
    items = broker.get_order_history(limit=50)["items"]
    assert [i["status"] for i in items] == ["FILLED"]


def test_history_collapses_queued_then_filled(tmp_path: Path) -> None:
    audit = tmp_path / "paper_orders.jsonl"
    t = datetime.now(tz=timezone.utc).isoformat()
    _write_audit(audit, [
        {"timestamp": t, "order_id": "a1", "ticker": "AAPL", "side": "BUY",
         "quantity": 1.0, "order_type": "market", "status": "QUEUED"},
        {"timestamp": t, "order_id": "a1", "ticker": "AAPL", "side": "BUY",
         "quantity": 1.0, "fill_price": 100.0, "status": "FILLED"},
    ])
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=audit,
        starting_cash=100.0,
        currency="GBP",
    )
    items = broker.get_order_history(limit=50)["items"]
    assert len(items) == 1
    assert items[0]["status"] == "FILLED"


def test_history_keeps_rejected_rows(tmp_path: Path) -> None:
    audit = tmp_path / "paper_orders.jsonl"
    t = datetime.now(tz=timezone.utc).isoformat()
    _write_audit(audit, [
        {"timestamp": t, "order_id": "a1", "ticker": "BAD", "side": "BUY",
         "quantity": 1.0, "status": "REJECTED", "reason": "no price"},
    ])
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=audit,
        starting_cash=100.0,
        currency="GBP",
    )
    items = broker.get_order_history(limit=50)["items"]
    assert [i["status"] for i in items] == ["REJECTED"]
