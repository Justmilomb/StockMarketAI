# Orders panel, exit logic & Kronos integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Fix the orders panel showing blank red "SELL" rows on reload, (2) stop the agent panic-selling into temporary dips (JetBlue incident), and (3) integrate the Kronos foundation model as a pre-sell price-forecast gate.

**Architecture:**
- **Orders bug** is two-sided: the paper broker's audit log leaks `RESET` rows (no ticker/side → render as red blanks) and Trading 212 cancelled-order rows have `filledQuantity=0` which the side-derivation maps to "SELL". Fix both sources and add a defensive filter in the panel.
- **Exit logic** lives in the LLM supervisor prompt. Add a minimum-hold-period heuristic, distinguish a dip from a downtrend using MACD / short-EMA slope, and surface each position's hold age (minutes since entry) via `get_portfolio` so the model sees it on every turn.
- **Kronos** is vendored as `core/kronos/` (MIT-licensed, ~3 files from upstream). A thin `core/kronos_forecaster.py` wraps lazy load + caching. Agent gets a new MCP tool `forecast_candles(ticker, pred_minutes)` returning predicted close / high / low over the next N minutes; the prompt is updated to require calling it before every sell.

**Tech Stack:** Python 3.12, PySide6, pandas/numpy, torch>=2.0, einops, huggingface_hub, transformers, pytest.

---

## File Structure

### Task 1 — Orders panel fix
- Modify: `core/paper_broker.py` (`get_order_history`)
- Modify: `core/trading212.py` (`get_order_history`)
- Modify: `desktop/panels/orders.py` (`refresh_view`)
- Create: `tests/test_paper_broker_order_history.py`

### Task 2 — Exit logic (hold period + dip/downtrend)
- Modify: `config.json` (add `agent.min_hold_minutes`, `agent.soft_stop_loss_pct`)
- Modify: `core/config_schema.py` (validate new fields)
- Modify: `core/agent/tools/broker_tools.py` (enrich `get_portfolio` positions with `hold_minutes`)
- Modify: `core/paper_broker.py` (expose `position_entry_time(ticker)` from state)
- Modify: `core/agent/prompts.py` (exit-discipline section)
- Create: `tests/test_position_hold_time.py`

### Task 3 — Kronos integration
- Create: `core/kronos/__init__.py`, `core/kronos/kronos.py`, `core/kronos/module.py` (vendored MIT source)
- Create: `core/kronos/LICENSE` (MIT text)
- Create: `core/kronos_forecaster.py` (lazy loader + forecast wrapper)
- Create: `core/agent/tools/forecast_tools.py` (MCP tool)
- Modify: `core/agent/mcp_server.py` (register FORECAST_TOOLS)
- Modify: `core/agent/prompts.py` (reference `forecast_candles` in sell checklist)
- Modify: `requirements.txt` (add `einops>=0.8.0`)
- Create: `tests/test_forecast_tools.py`

---

## Task 1: Fix blank sell orders

### Task 1.1: Filter RESET + dedupe QUEUED in paper broker history

**Files:**
- Modify: `core/paper_broker.py:936-960` (replace `get_order_history`)
- Test: `tests/test_paper_broker_order_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paper_broker_order_history.py
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    # Only one row per order_id, and it must be the terminal FILLED one.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper_broker_order_history.py -v`
Expected: `test_history_hides_reset_entries` FAILS (RESET row leaks through); `test_history_collapses_queued_then_filled` FAILS (two rows returned).

- [ ] **Step 3: Rewrite `get_order_history`**

Replace the body of `PaperBroker.get_order_history` with:

```python
def get_order_history(
    self,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Read recent audit rows, newest-first, collapsed per order_id.

    Skips RESET housekeeping rows (they have no ticker/side) and
    keeps only the latest status per order_id — a BUY that was
    QUEUED and then FILLED must not show up twice.
    """
    if not self._audit_path.exists():
        return {"items": [], "next_cursor": None}
    try:
        with self._audit_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {"items": [], "next_cursor": None}

    seen_ids: set[str] = set()
    items: List[Dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("status", "")).upper() == "RESET":
            continue
        if not row.get("ticker") or not row.get("side"):
            continue
        oid = str(row.get("order_id") or "")
        if oid and oid in seen_ids:
            continue
        if oid:
            seen_ids.add(oid)
        items.append(row)
        if len(items) >= limit:
            break
    return {"items": items, "next_cursor": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper_broker_order_history.py -v`
Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add core/paper_broker.py tests/test_paper_broker_order_history.py
git commit -m "fix(broker): hide RESET rows and dedupe QUEUED+FILLED in paper order history"
```

### Task 1.2: Defend the orders panel against malformed rows

**Files:**
- Modify: `desktop/panels/orders.py:37-65`

- [ ] **Step 1: Make the panel skip rows with no ticker/side**

Rewrite `OrdersPanel.refresh_view` to pre-filter:

```python
def refresh_view(self, state: Any) -> None:
    raw = state.recent_orders or []
    # Defence in depth: the broker should already have hidden RESET
    # rows, but if an unexpected audit shape leaks in, render nothing
    # rather than a blank red "SELL".
    orders = [
        o for o in raw
        if isinstance(o, dict)
        and str(o.get("ticker", "")).strip()
        and str(o.get("side", "")).strip().upper() in ("BUY", "SELL")
    ][:_MAX_ROWS]
    self.table.setRowCount(len(orders))
    for row, order in enumerate(orders):
        side = order.get("side", "")
        side_color = "#00ff00" if side.upper() == "BUY" else "#ff0000"
        status = order.get("status", "")
        status_upper = status.upper()
        if status_upper == "FILLED":
            status_color = "#00ff00"
        elif status_upper in ("CANCELLED", "REJECTED", "FAILED"):
            status_color = "#ff0000"
        elif status_upper in ("PENDING", "NEW", "WORKING", "ACCEPTED", "QUEUED"):
            status_color = "#ffd700"
        else:
            status_color = "#aaaaaa"
        order_type = order.get("order_type", order.get("type", ""))
        time_str = _format_time(order)
        items = [
            _item(time_str, "#aaaaaa"),
            _item(order.get("ticker", ""), "#00bfff"),
            _item(side, side_color),
            _item(str(order.get("quantity", "")), "#ffd700"),
            _item(order_type, "#ffd700"),
            _item(status, status_color),
        ]
        for col, item in enumerate(items):
            self.table.setItem(row, col, item)
```

- [ ] **Step 2: Commit**

```bash
git add desktop/panels/orders.py
git commit -m "fix(ui): orders panel skips rows with no ticker/side"
```

### Task 1.3: Fix Trading 212 "SELL from qty=0" bug

**Files:**
- Modify: `core/trading212.py:236-253`

- [ ] **Step 1: Derive side from signed raw quantity, not filledQuantity**

A cancelled T212 order has `filledQuantity=0` but the original `quantity` preserves the sign. Use the signed `quantity` first and only fall back to `filledQuantity` when it's nonzero.

Replace the list-comp in `get_order_history`:

```python
def get_order_history(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
    """Historical completed orders with pagination."""
    result = self._get_paginated("/equity/history/orders", limit, cursor)
    cleaned: List[Dict[str, Any]] = []
    for o in result["items"]:
        raw_qty = o.get("quantity", 0) or 0
        filled_qty = o.get("filledQuantity", 0) or 0
        # Prefer signed raw qty for side (survives cancels); fall back
        # to signed filled qty when raw is missing/zero.
        signed = raw_qty if raw_qty else filled_qty
        if signed == 0:
            # Skip entries we can't even attribute a side to — they
            # used to render as blank red SELL rows.
            continue
        cleaned.append({
            "id": o.get("id", ""),
            "ticker": o.get("ticker", ""),
            "side": "BUY" if signed > 0 else "SELL",
            "quantity": abs(filled_qty or raw_qty),
            "fill_price": o.get("fillPrice", o.get("filledPrice", 0.0)),
            "order_type": o.get("type", ""),
            "status": o.get("status", ""),
            "date": o.get("dateModified", o.get("dateCreated", "")),
            "fill_cost": o.get("fillCost", 0.0),
        })
    result["items"] = cleaned
    return result
```

- [ ] **Step 2: Commit**

```bash
git add core/trading212.py
git commit -m "fix(t212): derive order side from signed raw quantity, not filledQuantity"
```

---

## Task 2: Exit logic — hold period + dip/downtrend discipline

### Task 2.1: Config fields for minimum hold

**Files:**
- Modify: `config.json`
- Modify: `core/config_schema.py`

- [ ] **Step 1: Locate the `agent` config section**

Read `config.json` and `core/config_schema.py` to find the AgentConfig model.

- [ ] **Step 2: Add two fields with sensible defaults**

In `config_schema.py`, on the `AgentConfig` pydantic model (or equivalent):

```python
min_hold_minutes: int = Field(default=30, ge=0, description=(
    "Minimum minutes to hold a position before a discretionary exit "
    "unless a hard stop is hit. Prevents panic-selling into dips."
))
soft_stop_loss_pct: float = Field(default=3.0, ge=0.0, description=(
    "Unrealised loss percentage below which the agent is allowed to "
    "override min_hold_minutes and exit immediately."
))
```

In `config.json`, add to the `agent` block:

```json
"min_hold_minutes": 30,
"soft_stop_loss_pct": 3.0
```

- [ ] **Step 3: Commit**

```bash
git add config.json core/config_schema.py
git commit -m "feat(config): add min_hold_minutes + soft_stop_loss_pct agent fields"
```

### Task 2.2: Surface hold time per position in `get_portfolio`

**Files:**
- Modify: `core/paper_broker.py` (add `position_entry_time` state helper)
- Modify: `core/agent/tools/broker_tools.py` (`get_portfolio`)
- Test: `tests/test_position_hold_time.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_position_hold_time.py
from __future__ import annotations
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    # Most recent BUY fill wins so "hold time" measures the freshest add.
    age_min = (datetime.now(tz=timezone.utc) - entry).total_seconds() / 60
    assert 5 <= age_min <= 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_position_hold_time.py -v`
Expected: `AttributeError: 'PaperBroker' object has no attribute 'position_entry_time'`.

- [ ] **Step 3: Implement `position_entry_time` on PaperBroker**

Add this method (right after `get_order_history`):

```python
def position_entry_time(self, ticker: str) -> Optional[datetime]:
    """Return the timestamp of the most recent BUY fill for *ticker*.

    Reads the audit log newest-first and stops at the first matching
    FILLED BUY. Used by the agent's exit logic to measure how long a
    position has been open so it can honour the min_hold_minutes
    floor.
    """
    if not self._audit_path.exists():
        return None
    try:
        with self._audit_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if (str(row.get("ticker", "")) == ticker
                and str(row.get("side", "")).upper() == "BUY"
                and str(row.get("status", "")).upper() == "FILLED"):
            ts = row.get("timestamp")
            if not ts:
                continue
            try:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_position_hold_time.py -v`
Expected: PASS.

- [ ] **Step 5: Propagate to `get_portfolio` so the agent sees `hold_minutes`**

In `core/agent/tools/broker_tools.py`, augment the `positions` loop inside `get_portfolio` (lines 94-109). For each position, compute `hold_minutes`:

```python
# Compute hold age per position so the prompt's min-hold floor has
# real data to reason against. Only paper broker exposes
# position_entry_time today; trading212 can be added later.
entry_lookup = getattr(svc.broker, "position_entry_time", None)

def _hold_minutes(ticker: str) -> Optional[float]:
    if not callable(entry_lookup):
        return None
    ts = entry_lookup(ticker)
    if ts is None:
        return None
    from datetime import datetime, timezone
    age = datetime.now(tz=timezone.utc) - ts
    return round(age.total_seconds() / 60, 1)
```

Then in the position dict comprehension append:

```python
"hold_minutes": _hold_minutes(str(p.get("ticker", ""))),
```

- [ ] **Step 6: Commit**

```bash
git add core/paper_broker.py core/agent/tools/broker_tools.py tests/test_position_hold_time.py
git commit -m "feat(broker): expose position_entry_time + hold_minutes in get_portfolio"
```

### Task 2.3: Prompt changes — minimum hold + dip vs downtrend

**Files:**
- Modify: `core/agent/prompts.py` (insert a new section before `## Standing rules`)

- [ ] **Step 1: Add the exit-discipline section to `SYSTEM_PROMPT_AUTONOMOUS_PM_TEMPLATE`**

Insert the following block just above the existing `## Standing rules` heading:

```
## Exit discipline — give trades room to breathe

Selling too early is as expensive as not selling at all. The JetBlue
incident (bought, sold an hour later at −24p, price then recovered
30p) is the exact failure mode to avoid. Defaults:

- **Minimum hold: {min_hold_minutes} minutes.** Unless the position
  is down more than **{soft_stop_loss_pct}%** on cost, or genuinely
  broken news has hit the wire, do not sell inside this window. Every
  position you own carries a ``hold_minutes`` field in
  ``get_portfolio`` — check it before even considering a sell.
- **Distinguish a dip from a downtrend.** Before closing a losing
  position, always:
  1. `compute_indicators(ticker, ["macd", "ema", "rsi", "atr"])` —
     if MACD histogram is still rising or RSI is bouncing off <30,
     this is a dip, not a trend break.
  2. `get_intraday_bars(ticker, "5m", 180)` — are the last 2–3 bars
     making a higher low? Then the bleed has stopped.
  3. `forecast_candles(ticker, pred_minutes=60)` — Kronos' short-term
     close forecast. If the predicted close 30–60 minutes from now is
     **above your entry price**, hold. If it's still below both entry
     and current price, the exit is justified.
- **A 24p paper loss is not a reason to sell.** Sizing already
  guarantees the absolute £ loss is small. The cost of panicking out
  of a temporary wobble is missing the recovery.
- **Hard stops still apply.** If the loss exceeds
  {soft_stop_loss_pct}% *and* the three checks above all point down,
  exit — that is the discipline, not stubbornness.
- **Winners follow the same discipline.** Small wins (0.5–2%) are
  still candidates to bank, but not inside the first
  {min_hold_minutes} minutes unless momentum is clearly fading (MACD
  rolled, price rejected from resistance).

Record your decision rationale in the journal on every sell: what the
forecast said, what MACD/RSI said, and which rule you applied. If you
ever override the min-hold floor, write *why* — future-you is
auditing you.
```

- [ ] **Step 2: Update `render_system_prompt` to inject the two new values**

Replace the return in `render_system_prompt`:

```python
def render_system_prompt(config: Dict[str, Any]) -> str:
    agent_cfg = config.get("agent", {}) or {}
    paper_cfg = config.get("paper_broker", {}) or {}
    return SYSTEM_PROMPT_AUTONOMOUS_PM_TEMPLATE.format(
        paper_mode="ON (no real money)" if agent_cfg.get("paper_mode", True) else "OFF (LIVE MONEY)",
        cadence_seconds=int(agent_cfg.get("cadence_seconds", 90)),
        currency=str(paper_cfg.get("currency", "GBP") or "GBP"),
        min_hold_minutes=int(agent_cfg.get("min_hold_minutes", 30)),
        soft_stop_loss_pct=float(agent_cfg.get("soft_stop_loss_pct", 3.0)),
    )
```

- [ ] **Step 3: Commit**

```bash
git add core/agent/prompts.py
git commit -m "feat(agent): exit discipline — min hold, dip vs downtrend, Kronos check"
```

---

## Task 3: Kronos integration

### Task 3.1: Vendor upstream Kronos source under `core/kronos/`

**Files:**
- Create: `core/kronos/__init__.py`
- Create: `core/kronos/kronos.py`
- Create: `core/kronos/module.py`
- Create: `core/kronos/LICENSE`

- [ ] **Step 1: Add einops to requirements.txt**

Append to `requirements.txt`:

```
# Kronos financial-candlestick foundation model (vendored under
# core/kronos/ from github.com/shiyu-coder/Kronos, MIT licensed).
einops>=0.8.0
```

- [ ] **Step 2: Copy the three upstream files into `core/kronos/`**

Fetch and write verbatim:
- `https://raw.githubusercontent.com/shiyu-coder/Kronos/master/model/__init__.py` → `core/kronos/__init__.py`
- `https://raw.githubusercontent.com/shiyu-coder/Kronos/master/model/kronos.py` → `core/kronos/kronos.py`
- `https://raw.githubusercontent.com/shiyu-coder/Kronos/master/model/module.py` → `core/kronos/module.py`
- `https://raw.githubusercontent.com/shiyu-coder/Kronos/master/LICENSE` → `core/kronos/LICENSE`

Verify the `__init__.py` exports `Kronos`, `KronosTokenizer`, `KronosPredictor`.

- [ ] **Step 3: Install einops**

Run: `pip install einops>=0.8.0`
Expected: installs cleanly.

- [ ] **Step 4: Smoke-test imports**

Run:
```bash
python -c "from core.kronos import Kronos, KronosTokenizer, KronosPredictor; print('ok')"
```
Expected: `ok`. If import fails because of `sys.path.append("../")` shims or `from model import ...` inside upstream code, fix the imports to use absolute `core.kronos` paths.

- [ ] **Step 5: Commit**

```bash
git add core/kronos/ requirements.txt
git commit -m "feat(kronos): vendor shiyu-coder/Kronos model/ under core/kronos/ (MIT)"
```

### Task 3.2: Forecaster wrapper with lazy model load

**Files:**
- Create: `core/kronos_forecaster.py`

- [ ] **Step 1: Write the wrapper module**

```python
"""Kronos forecaster — pre-sell price-forecast gate.

Wraps the vendored ``core.kronos`` model with lazy, process-wide
caching so the 100 MB model is loaded at most once. ``forecast``
takes the ticker's recent intraday bars and returns predicted close
/ high / low series for the next N minutes.

Design
------

* Lazy load — import torch only when first forecast is requested.
* Singleton — one (tokenizer, model, predictor) tuple per process.
* CPU-only by default; if a CUDA device is visible it'll use it.
* Forecast failures (missing data, torch OOM, HTTPError from HF) are
  caught and surfaced as ``{"error": "..."}`` dicts rather than
  propagating — the agent should *hold* when forecasting fails, not
  crash the loop.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_PREDICTOR: Optional[Any] = None

#: Default HF identifiers. Kronos-small is 24.7M params — fast and
#: cheap on CPU. Kronos-base (102M) is higher quality but slower.
TOKENIZER_ID: str = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_ID: str = "NeoQuasar/Kronos-small"


def _get_predictor() -> Any:
    global _PREDICTOR
    if _PREDICTOR is not None:
        return _PREDICTOR
    with _MODEL_LOCK:
        if _PREDICTOR is not None:
            return _PREDICTOR
        from core.kronos import Kronos, KronosTokenizer, KronosPredictor
        logger.info("kronos: loading tokenizer %s", TOKENIZER_ID)
        tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
        logger.info("kronos: loading model %s", MODEL_ID)
        model = Kronos.from_pretrained(MODEL_ID)
        _PREDICTOR = KronosPredictor(model, tokenizer, max_context=512)
        logger.info("kronos: predictor ready")
        return _PREDICTOR


def forecast(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
    sample_count: int = 1,
    temperature: float = 1.0,
    top_p: float = 0.9,
) -> Dict[str, Any]:
    """Forecast the next ``pred_len`` candles.

    Args:
        hist_df: DataFrame indexed by timestamp with columns
            ``open``, ``high``, ``low``, ``close``, ``volume``.
            Must have at least 64 rows.
        interval_minutes: bar width in minutes (matches hist_df's
            spacing — 5 for 5-minute bars, etc.).
        pred_len: number of future candles to predict.
        sample_count: ensemble size. 1 is usually enough.
        temperature, top_p: sampling knobs.

    Returns:
        Dict with ``close``, ``high``, ``low`` lists + a ``timestamps``
        list for the predicted bars, or ``{"error": ...}`` on failure.
    """
    if hist_df is None or len(hist_df) < 64:
        return {"error": "need at least 64 historical bars for forecasting"}

    hist = hist_df.copy()
    required = {"open", "high", "low", "close"}
    if not required.issubset({c.lower() for c in hist.columns}):
        return {"error": f"missing required OHLC columns: {required}"}
    hist.columns = [c.lower() for c in hist.columns]
    if "volume" not in hist.columns:
        hist["volume"] = 0.0

    x_timestamp = pd.Series(hist.index, index=hist.index)
    last_ts = pd.to_datetime(hist.index[-1])
    step = timedelta(minutes=interval_minutes)
    y_timestamp = pd.Series(
        [last_ts + step * (i + 1) for i in range(pred_len)]
    )

    try:
        predictor = _get_predictor()
        pred_df = predictor.predict(
            df=hist[["open", "high", "low", "close", "volume"]],
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )
    except Exception as e:
        logger.warning("kronos: forecast failed: %s", e)
        return {"error": f"forecast failed: {e}"}

    return {
        "timestamps": [ts.isoformat() for ts in y_timestamp],
        "close": [float(x) for x in pred_df["close"].tolist()],
        "high": [float(x) for x in pred_df["high"].tolist()],
        "low": [float(x) for x in pred_df["low"].tolist()],
        "interval_minutes": interval_minutes,
        "pred_len": pred_len,
        "model_id": MODEL_ID,
    }
```

- [ ] **Step 2: Commit**

```bash
git add core/kronos_forecaster.py
git commit -m "feat(kronos): lazy forecaster wrapper with singleton predictor"
```

### Task 3.3: MCP tool `forecast_candles`

**Files:**
- Create: `core/agent/tools/forecast_tools.py`
- Modify: `core/agent/mcp_server.py`
- Test: `tests/test_forecast_tools.py`

- [ ] **Step 1: Write the failing test with a mocked forecaster**

```python
# tests/test_forecast_tools.py
from __future__ import annotations
import asyncio, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _fake_bars(n: int = 80, interval_min: int = 5) -> pd.DataFrame:
    now = datetime.now()
    idx = [now - timedelta(minutes=interval_min * (n - i)) for i in range(n)]
    return pd.DataFrame({
        "Open":   [100 + i * 0.1 for i in range(n)],
        "High":   [101 + i * 0.1 for i in range(n)],
        "Low":    [99  + i * 0.1 for i in range(n)],
        "Close":  [100 + i * 0.1 for i in range(n)],
        "Volume": [1000] * n,
    }, index=pd.DatetimeIndex(idx))


def test_forecast_returns_prediction_summary() -> None:
    from core.agent.tools import forecast_tools

    async def run() -> dict:
        with (
            patch.object(forecast_tools, "_fetch_recent_bars", return_value=(_fake_bars(), 5)),
            patch("core.kronos_forecaster.forecast", return_value={
                "timestamps": ["2026-04-18T14:00:00"],
                "close": [110.0], "high": [111.0], "low": [109.0],
                "interval_minutes": 5, "pred_len": 1, "model_id": "test",
            }),
        ):
            result = await forecast_tools.forecast_candles({
                "ticker": "AAPL", "pred_minutes": 60,
            })
            return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert out["ticker"] == "AAPL"
    assert out["predicted_close"] == [110.0]
    assert out["summary"]["final_close"] == 110.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forecast_tools.py -v`
Expected: `ModuleNotFoundError: No module named 'core.agent.tools.forecast_tools'`.

- [ ] **Step 3: Write `forecast_tools.py`**

```python
"""Kronos forecast tool — pre-sell price-forecast gate for the agent.

Exposes a single MCP tool, ``forecast_candles(ticker, pred_minutes,
interval)``. The agent is instructed by the system prompt to call
this before every discretionary sell: if the model forecasts
recovery above entry within the window, it should hold.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple

import pandas as pd

from core.agent._sdk import tool


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _fetch_recent_bars(ticker: str, interval: str, lookback_bars: int = 400) -> Tuple[pd.DataFrame, int]:
    """Pull recent intraday bars via yfinance. Returns (df, interval_minutes)."""
    import yfinance as yf

    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}.get(interval, 5)
    # Choose a period wide enough to contain `lookback_bars` * minutes of trading.
    span_minutes = lookback_bars * minutes
    if minutes <= 5:
        period = "7d"
    elif minutes <= 30:
        period = "30d"
    else:
        period = "60d"
    df = yf.download(
        ticker, period=period, interval=interval,
        progress=False, auto_adjust=False, multi_level_index=False,
    )
    if df is None or df.empty:
        return pd.DataFrame(), minutes
    return df.tail(lookback_bars), minutes


@tool(
    "forecast_candles",
    "Forecast the next N minutes of OHLC candles for a ticker using the "
    "Kronos financial foundation model. Call this BEFORE every "
    "discretionary sell. If the forecast shows close recovering above "
    "your entry price within the window, you should hold instead of "
    "exiting. Also useful for entry timing — buy only if the forecast "
    "trends up.\n\n"
    "Args:\n"
    "    ticker: instrument to forecast\n"
    "    pred_minutes: horizon in minutes (e.g. 60, 120, 240)\n"
    "    interval: bar width — one of '1m','5m','15m','30m','60m' (default '5m')\n\n"
    "Returns predicted close/high/low arrays and a summary with the "
    "final predicted close, the max predicted close, and the min "
    "predicted low over the horizon.",
    {"ticker": str, "pred_minutes": int, "interval": str},
)
async def forecast_candles(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    pred_minutes = int(args.get("pred_minutes", 60) or 60)
    interval = str(args.get("interval", "5m") or "5m")
    if not ticker:
        return _text_result({"error": "ticker is required"})
    if pred_minutes <= 0 or pred_minutes > 1440:
        return _text_result({"error": "pred_minutes must be 1..1440"})

    try:
        hist, interval_minutes = _fetch_recent_bars(ticker, interval)
    except Exception as e:
        return _text_result({"ticker": ticker, "error": f"data fetch failed: {e}"})
    if hist.empty or len(hist) < 64:
        return _text_result({"ticker": ticker, "error": "not enough history to forecast"})

    pred_len = max(1, pred_minutes // interval_minutes)

    from core.kronos_forecaster import forecast as _forecast
    result = _forecast(hist_df=hist, interval_minutes=interval_minutes, pred_len=pred_len)
    if "error" in result:
        return _text_result({"ticker": ticker, **result})

    closes = result["close"]
    highs = result["high"]
    lows = result["low"]
    return _text_result({
        "ticker": ticker,
        "interval": interval,
        "pred_minutes": pred_minutes,
        "pred_len": pred_len,
        "model_id": result["model_id"],
        "timestamps": result["timestamps"],
        "predicted_close": closes,
        "predicted_high": highs,
        "predicted_low": lows,
        "summary": {
            "final_close": closes[-1] if closes else 0.0,
            "max_close": max(closes) if closes else 0.0,
            "min_low": min(lows) if lows else 0.0,
            "pct_move_final_vs_last_hist": round(
                (closes[-1] / float(hist["Close"].iloc[-1]) - 1) * 100, 3
            ) if closes else 0.0,
        },
    })


FORECAST_TOOLS = [forecast_candles]
```

- [ ] **Step 4: Register the tool in `mcp_server.py`**

Add import near the others:

```python
from core.agent.tools.forecast_tools import FORECAST_TOOLS
```

Append to `ALL_TOOLS`:

```python
    *FORECAST_TOOLS,
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_forecast_tools.py -v`
Expected: PASS.

- [ ] **Step 6: Update prompt tool-catalogue section**

In `core/agent/prompts.py`, in the tool catalogue near the `**Indicators**` entry, add:

```
**Forecast** — `forecast_candles(ticker, pred_minutes, interval)` runs the
Kronos foundation model on recent intraday bars and returns predicted
close/high/low for the next N minutes. **Required before every
discretionary sell.** If the predicted close at the end of the horizon
is above your entry price, you must hold unless a hard stop has
already triggered.
```

- [ ] **Step 7: Commit**

```bash
git add core/agent/tools/forecast_tools.py core/agent/mcp_server.py core/agent/prompts.py tests/test_forecast_tools.py
git commit -m "feat(agent): forecast_candles MCP tool backed by Kronos"
```

---

## Final verification

- [ ] **Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: all tests green (or pre-existing failures unchanged).

- [ ] **Merge to main and push**

User explicitly asked: "Commit and push to main when done."

From the worktree:
```bash
git log --oneline claude/brave-bartik-8f5f10 ^main   # review commits
```

Then from the main repo dir (not the worktree — `git worktree` locks the branch):
```bash
cd E:/Coding/StockMarketAI
git checkout main
git merge --ff-only claude/brave-bartik-8f5f10
git push origin main
```

If `--ff-only` fails, fall back to `git merge --no-ff` so history stays clean.

---

## Self-review notes

- **Spec coverage:** (1) blank sell orders → Task 1 (paper + t212 + panel). (2) exit logic → Task 2 (config + hold time + prompt). (3) Kronos → Task 3 (vendor + wrapper + tool + prompt).
- **Placeholders:** every code block is complete. Tests include full fixtures. Kronos vendored file contents are fetched live in step 3.1.2 rather than inlined, but the exact URLs and destinations are specified.
- **Type consistency:** `hold_minutes` is an `Optional[float]` everywhere; `forecast_candles` return shape matches the test's assertions.
