"""Price-sanity guards: bad yfinance ticks must not corrupt fills.

Replay of the 2026-04-20 BARC disaster — the agent held BARC.L at an
entry of 444p, yfinance returned 132.10 on a single tick (a 70% "drop"
that the real market never had), and the paper broker filled the
market SELL at 132.10, realising a ~£16 loss on a £100 account. These
tests lock in the three layers of defence introduced to prevent it:

1. ``fetch_live_prices`` rejects anomalous ticks at the yfinance
   boundary by comparing against the previous close.
2. ``PaperBroker`` refuses to fill a SELL if the live price diverges
   from the position's entry by more than the configured threshold.
3. ``get_live_price`` surfaces the divergence between the broker's
   cached price and a fresh yfinance fetch so the agent can see the
   anomaly before deciding to trade.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core import data_loader
from core.paper_broker import PaperBroker


# ── helpers ───────────────────────────────────────────────────────────


def _yf_frame(closes: list[float]) -> pd.DataFrame:
    """Build a minimal yfinance-style OHLCV frame with the given closes."""
    idx = pd.date_range(end="2026-04-20", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


# ── Layer 1 — data_loader anomaly rejection ───────────────────────────


def test_fetch_live_prices_rejects_anomalous_tick() -> None:
    """yfinance returning a >20% gap vs prior close must be rejected.

    Replays the BARC scenario: prior close 442p, surprise tick 132.1p.
    """
    frame = _yf_frame([440.0, 441.0, 442.0, 132.1])

    with patch("core.data_loader.yf.download", return_value=frame):
        result = data_loader.fetch_live_prices(["BARC.L"])

    entry = result["BARC.L"]
    assert entry["price"] == 0.0, "anomalous price must be zeroed out"
    assert entry.get("anomaly") is True
    assert entry.get("rejected_price") == 132.1
    assert entry.get("reference") == 442.0


def test_fetch_live_prices_passes_normal_tick() -> None:
    """A small intraday move (1-2%) must pass through untouched."""
    frame = _yf_frame([440.0, 441.0, 442.0, 448.0])

    with patch("core.data_loader.yf.download", return_value=frame):
        result = data_loader.fetch_live_prices(["BARC.L"])

    entry = result["BARC.L"]
    assert entry["price"] == 448.0
    assert not entry.get("anomaly", False)


def test_fetch_live_prices_skips_sanity_when_only_one_close() -> None:
    """No prior close → no reference → accept whatever yfinance gives.

    Can't compute a divergence without two points; don't falsely reject.
    """
    frame = _yf_frame([132.1])

    with patch("core.data_loader.yf.download", return_value=frame):
        result = data_loader.fetch_live_prices(["NEW.L"])

    entry = result["NEW.L"]
    assert entry["price"] == 132.1
    assert not entry.get("anomaly", False)


# ── Layer 2 — broker SELL sanity guard ────────────────────────────────


def _build_broker(tmp_path: Path) -> PaperBroker:
    """A fresh broker with £100 GBP, no positions, default thresholds."""
    return PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "paper_orders.jsonl",
        starting_cash=100.0,
        currency="GBP",
    )


def _seed_position(
    broker: PaperBroker, ticker: str, qty: float, avg_price: float
) -> None:
    """Inject a position directly into broker state, bypassing the buy path.

    Buying via ``submit_order`` requires a live price (which we'd have
    to mock per-test). Seeding state directly is the simplest way to
    isolate the SELL sanity guard under test.
    """
    from core.paper_broker import _Position  # type: ignore

    broker._state.positions[ticker] = _Position(
        quantity=qty,
        avg_price=avg_price,
        currency="USD",  # broker always fx-converts; native ccy is USD-like
        cost_basis_acct=qty * avg_price * 0.75,
    )
    broker._save_state()


def test_sell_rejected_when_price_deviates_above_threshold(
    tmp_path: Path,
) -> None:
    """Live price 70% below entry → reject with a price-sanity reason."""
    broker = _build_broker(tmp_path)
    _seed_position(broker, "BARCl_EQ", qty=0.07, avg_price=444.0)

    with patch.object(broker, "_ticker_is_tradeable", return_value=True), \
         patch.object(broker._prices, "get_many", return_value={"BARCl_EQ": 132.1}):
        result = broker.submit_order("BARCl_EQ", "SELL", 0.07, "market")

    assert result["status"] == "REJECTED"
    assert "price-sanity" in result["reason"].lower()
    assert "BARCl_EQ" in broker._state.positions, (
        "position must be untouched after rejected sell"
    )


def test_sell_allowed_when_price_within_threshold(tmp_path: Path) -> None:
    """A 5% adverse move is within tolerance → fill proceeds."""
    broker = _build_broker(tmp_path)
    _seed_position(broker, "BARCl_EQ", qty=0.07, avg_price=444.0)

    # 5% below entry — well within default 15% threshold.
    with patch.object(broker, "_ticker_is_tradeable", return_value=True), \
         patch.object(broker._prices, "get_many", return_value={"BARCl_EQ": 421.8}):
        result = broker.submit_order("BARCl_EQ", "SELL", 0.07, "market")

    assert result["status"] == "FILLED"
    assert result["fill_price"] == 421.8
    assert "BARCl_EQ" not in broker._state.positions


def test_sell_sanity_threshold_is_configurable(tmp_path: Path) -> None:
    """Tightening the threshold to 3% must catch a 5% move the default allows."""
    broker = PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "paper_orders.jsonl",
        starting_cash=100.0,
        currency="GBP",
        fill_sanity_threshold=0.03,
    )
    _seed_position(broker, "BARCl_EQ", qty=0.07, avg_price=444.0)

    with patch.object(broker, "_ticker_is_tradeable", return_value=True), \
         patch.object(broker._prices, "get_many", return_value={"BARCl_EQ": 421.8}):
        result = broker.submit_order("BARCl_EQ", "SELL", 0.07, "market")

    assert result["status"] == "REJECTED"
    assert "price-sanity" in result["reason"].lower()


# ── Layer 3 — get_live_price divergence reporting ─────────────────────


def _call_tool(tool_obj, args: dict) -> dict:
    """Run an SDK-decorated tool's handler synchronously and parse the result."""
    import asyncio
    import json

    raw = asyncio.run(tool_obj.handler(args))
    return json.loads(raw["content"][0]["text"])


def _fake_ctx(divergence_threshold: float = 0.05):
    """Build a minimal AgentContext stand-in exposing config only."""
    from types import SimpleNamespace

    return SimpleNamespace(
        config={
            "paper_broker": {
                "divergence_warn_threshold": divergence_threshold,
            },
        },
    )


def test_get_live_price_flags_divergence() -> None:
    """Broker says 443.8, fresh fetch says 132.1 → warn the agent loudly.

    This is the smoking-gun shape from the BARC post-mortem: the agent's
    portfolio panel showed ``current_price: 443.8`` at the exact moment
    yfinance was serving 132.1 on its live endpoint. The tool must make
    that disagreement impossible to miss.
    """
    from core.agent.tools import market_tools

    fresh = {"BARCl_EQ": {"price": 132.1, "change_pct": 0.0}}

    with patch.object(market_tools, "_held_current_price", return_value=443.8), \
         patch.object(market_tools, "get_agent_context", return_value=_fake_ctx()), \
         patch("data_loader.fetch_live_prices", return_value=fresh):
        payload = _call_tool(market_tools.get_live_price, {"ticker": "BARCl_EQ"})

    assert payload["price"] == 443.8
    assert payload["source"] == "broker_live"
    assert payload["fresh_price"] == 132.1
    assert payload["fresh_source"] == "yfinance"
    assert payload["divergence_pct"] < -50.0, (
        "a ~70% drop must be reported as a large negative divergence"
    )
    assert "warning" in payload, "divergence beyond threshold must set warning"
    assert "divergence" in payload["warning"].lower()


def test_get_live_price_quiet_when_prices_agree() -> None:
    """Fresh fetch within threshold → no warning, clean payload."""
    from core.agent.tools import market_tools

    fresh = {"BARCl_EQ": {"price": 445.2, "change_pct": 0.3}}

    with patch.object(market_tools, "_held_current_price", return_value=443.8), \
         patch.object(market_tools, "get_agent_context", return_value=_fake_ctx()), \
         patch("data_loader.fetch_live_prices", return_value=fresh):
        payload = _call_tool(market_tools.get_live_price, {"ticker": "BARCl_EQ"})

    assert payload["price"] == 443.8
    assert payload["fresh_price"] == 445.2
    assert "warning" not in payload
    assert abs(payload["divergence_pct"]) < 1.0


def test_get_live_price_surfaces_layer1_anomaly() -> None:
    """If fetch_live_prices already rejected the tick, propagate that flag.

    Layer 1 zeroes ``price`` and sets ``anomaly=True``; the tool must still
    report the *rejected* price so the agent can see what yfinance tried
    to serve, plus a warning about the disagreement.
    """
    from core.agent.tools import market_tools

    fresh = {
        "BARCl_EQ": {
            "price": 0.0,
            "change_pct": 0.0,
            "anomaly": True,
            "rejected_price": 132.1,
            "reference": 442.0,
        },
    }

    with patch.object(market_tools, "_held_current_price", return_value=443.8), \
         patch.object(market_tools, "get_agent_context", return_value=_fake_ctx()), \
         patch("data_loader.fetch_live_prices", return_value=fresh):
        payload = _call_tool(market_tools.get_live_price, {"ticker": "BARCl_EQ"})

    assert payload["fresh_price"] == 132.1
    assert payload.get("fresh_anomaly") is True
    assert "warning" in payload
