"""Per-terminal fine-tune pipeline scaffold.

Full fine-tuning is out of scope for this session — we ship the pipeline
seam so a follow-up plan can slot training into place without touching
downstream code.

What lives here today:

* ``build_training_manifest()`` — scan the paper-broker audit log and
  emit a JSON manifest of closed SELL fills (features, label) suitable
  for fine-tuning the meta-learner.

* ``should_retrain(now)`` — decides whether enough new trades have
  accumulated to justify a retrain (default: 20 new trades or 7 days).

The actual retrain step calls ``MetaLearner.fit()`` which is already
implemented — the fine-tune loop just invokes it periodically.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_RETRAIN_TRADE_THRESHOLD: int = 20
DEFAULT_RETRAIN_DAYS: int = 7


def build_training_manifest(
    audit_path: Path | str,
    manifest_path: Path | str,
) -> int:
    """Emit a lightweight manifest of closed trades. Returns count written."""
    audit = Path(audit_path)
    manifest = Path(manifest_path)
    if not audit.exists():
        return 0
    rows: List[Dict[str, Any]] = []
    for line in audit.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("status", "")).upper() != "FILLED":
            continue
        if str(row.get("side", "")).upper() != "SELL":
            continue
        rows.append({
            "timestamp": row.get("timestamp"),
            "ticker": row.get("ticker"),
            "realised_pnl": row.get("realised_pnl_acct"),
            "quantity": row.get("quantity"),
            "fill_price": row.get("fill_price"),
        })
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"trades": rows}, indent=2, default=str), encoding="utf-8",
    )
    return len(rows)


def should_retrain(
    last_trained_at: Optional[str],
    trades_since_last: int,
    now: Optional[datetime] = None,
    trade_threshold: int = DEFAULT_RETRAIN_TRADE_THRESHOLD,
    day_threshold: int = DEFAULT_RETRAIN_DAYS,
) -> bool:
    if trades_since_last >= trade_threshold:
        return True
    if not last_trained_at:
        return trades_since_last > 0
    try:
        last = datetime.fromisoformat(last_trained_at)
    except Exception:
        return True
    now = now or datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(days=day_threshold)
