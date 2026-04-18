"""Reflector: parse audit log, update stats + cursor."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _write_audit(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_find_new_closed_trades_filters_non_sells(tmp_path: Path) -> None:
    from core.trade_reflector import find_new_closed_trades

    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"timestamp": "2026-04-18T10:00:00+00:00", "status": "FILLED",
         "side": "BUY", "ticker": "AAPL", "quantity": 1, "fill_price": 170.0,
         "realised_pnl_acct": 0.0, "account_currency": "GBP"},
        {"timestamp": "2026-04-18T11:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "AAPL", "quantity": 1, "fill_price": 172.0,
         "realised_pnl_acct": 2.0, "account_currency": "GBP"},
        {"timestamp": "2026-04-18T12:00:00+00:00", "status": "PENDING",
         "side": "SELL", "ticker": "AAPL", "quantity": 1, "fill_price": 0.0,
         "realised_pnl_acct": 0.0, "account_currency": "GBP"},
    ])
    trades, cursor = find_new_closed_trades(audit, None)
    assert len(trades) == 1
    assert trades[0].ticker == "AAPL"
    assert trades[0].realised_pnl == 2.0
    assert cursor == "2026-04-18T11:00:00+00:00"


def test_find_new_closed_trades_respects_cursor(tmp_path: Path) -> None:
    from core.trade_reflector import find_new_closed_trades

    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"timestamp": "2026-04-18T11:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "AAPL", "quantity": 1, "fill_price": 172.0,
         "realised_pnl_acct": 2.0, "account_currency": "GBP"},
        {"timestamp": "2026-04-18T13:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "MSFT", "quantity": 2, "fill_price": 300.0,
         "realised_pnl_acct": -5.0, "account_currency": "GBP"},
    ])
    trades, cursor = find_new_closed_trades(audit, "2026-04-18T12:00:00+00:00")
    assert len(trades) == 1
    assert trades[0].ticker == "MSFT"
    assert cursor == "2026-04-18T13:00:00+00:00"


def test_find_returns_empty_when_audit_missing(tmp_path: Path) -> None:
    from core.trade_reflector import find_new_closed_trades
    trades, cursor = find_new_closed_trades(tmp_path / "nope.jsonl", None)
    assert trades == []
    assert cursor is None


def test_reflect_updates_stats_and_cursor_without_lessons(tmp_path: Path) -> None:
    from core.trade_reflector import reflect_on_closed_trades
    from core.trader_personality import TraderPersonality

    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"timestamp": "2026-04-18T11:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "AAPL", "quantity": 1, "fill_price": 172.0,
         "realised_pnl_acct": 2.0, "account_currency": "GBP"},
        {"timestamp": "2026-04-18T13:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "MSFT", "quantity": 2, "fill_price": 300.0,
         "realised_pnl_acct": -5.0, "account_currency": "GBP"},
    ])
    p = TraderPersonality(tmp_path / "p.json")
    p.load()

    # Force the LLM path to be skipped by pretending no model id is set.
    with patch("core.agent.model_router.assessor_model", return_value=""):
        written = asyncio.run(reflect_on_closed_trades(audit, p, {"ai": {}}))

    assert written == 0
    assert p.stats["total_trades_reflected_on"] == 2
    assert p.stats["wins"] == 1
    assert p.stats["losses"] == 1
    assert p.reflection_cursor == "2026-04-18T13:00:00+00:00"


def test_reflect_writes_parsed_lessons(tmp_path: Path) -> None:
    from core.trade_reflector import reflect_on_closed_trades
    from core.trader_personality import TraderPersonality

    audit = tmp_path / "audit.jsonl"
    _write_audit(audit, [
        {"timestamp": "2026-04-18T11:00:00+00:00", "status": "FILLED",
         "side": "SELL", "ticker": "JBLU", "quantity": 10, "fill_price": 5.2,
         "realised_pnl_acct": -2.4, "account_currency": "GBP"},
    ])
    p = TraderPersonality(tmp_path / "p.json")
    p.load()

    fake_reply = json.dumps({"lessons": [
        {"ticker": "JBLU", "lesson": "Wait on airline dips", "tags": ["JBLU", "patience"]},
    ]})

    async def fake_query(prompt, options):
        from core.agent._sdk import AssistantMessage, TextBlock
        yield AssistantMessage(content=[TextBlock(text=fake_reply)], model="claude-sonnet-4-6")

    with patch("core.agent.model_router.assessor_model", return_value="claude-sonnet-4-6"), \
         patch("core.agent.model_router.assessor_effort", return_value="medium"), \
         patch("core.agent.paths.cli_path_for_sdk", return_value="claude"), \
         patch("core.agent.paths.prepare_env_for_bundled_engine"), \
         patch("core.agent._sdk.query", fake_query):
        written = asyncio.run(reflect_on_closed_trades(audit, p, {"ai": {}}))

    assert written == 1
    assert p.lessons[0]["lesson"] == "Wait on airline dips"
    assert "JBLU" in p.lessons[0]["tags"]
    assert p.reflection_cursor == "2026-04-18T11:00:00+00:00"
