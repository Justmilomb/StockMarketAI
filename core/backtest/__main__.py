"""``python -m core.backtest`` thin wrapper around scripts/backtest_replay.py."""
from __future__ import annotations

from scripts.backtest_replay import main


if __name__ == "__main__":
    raise SystemExit(main())
