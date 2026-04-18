from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.finetune.terminal_finetune import (
    build_training_manifest,
    should_retrain,
)


def test_build_training_manifest(tmp_path: Path):
    audit = tmp_path / "paper_orders.jsonl"
    audit.write_text("\n".join([
        json.dumps({
            "status": "FILLED", "side": "SELL", "timestamp": "2026-04-10",
            "ticker": "TSLA", "realised_pnl_acct": 12.3, "quantity": 1,
            "fill_price": 300,
        }),
        json.dumps({
            "status": "FILLED", "side": "BUY", "timestamp": "2026-04-10",
            "ticker": "TSLA", "quantity": 1, "fill_price": 290,
        }),
        json.dumps({"status": "REJECTED", "side": "SELL", "timestamp": "2026-04-10"}),
    ]), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    n = build_training_manifest(audit, manifest)
    assert n == 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["trades"][0]["ticker"] == "TSLA"
    assert data["trades"][0]["realised_pnl"] == 12.3


def test_build_training_manifest_missing_file(tmp_path: Path):
    n = build_training_manifest(tmp_path / "nope.jsonl", tmp_path / "m.json")
    assert n == 0


def test_should_retrain_hits_trade_threshold():
    assert should_retrain(None, trades_since_last=25) is True


def test_should_retrain_waits_until_day_threshold():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert should_retrain(yesterday, trades_since_last=1) is False
    week_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert should_retrain(week_ago, trades_since_last=1) is True


def test_should_retrain_first_time_with_trades():
    assert should_retrain(None, trades_since_last=3) is True


def test_should_retrain_first_time_no_trades():
    assert should_retrain(None, trades_since_last=0) is False
