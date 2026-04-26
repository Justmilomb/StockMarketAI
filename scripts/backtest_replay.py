"""Replay 30 days (configurable) of historical data and log the trades a
deterministic rule-based stand-in for the agent would have made.

This is **not** a full agent replay — that would cost real Claude
quota on every iteration and isn't reproducible. Instead we run a
simple RSI-cross strategy over the watchlist, the same indicator the
live agent reaches for first when hunting setups, and book trades
through an in-memory paper broker.

Output: ``data/backtest_results.json`` (override with ``--output``)
containing per-ticker stats, the full trade log, and the worst trades
ranked by realised loss.

Usage::

    python -m scripts.backtest_replay --days 30
    python -m scripts.backtest_replay --days 60 --ticker AAPL --ticker MSFT
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make the project root importable when the script is launched via
# ``python -m scripts.backtest_replay`` or directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(_ROOT / "core"))

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float
    reason: str


def _load_default_watchlist(config_path: Path) -> List[str]:
    """Read watchlists from ``config.json``; fall back to a small default."""
    fallback = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]
    if not config_path.exists():
        return fallback
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    active = str(cfg.get("active_watchlist", "Default") or "Default")
    watchlists = cfg.get("watchlists", {}) or {}
    tickers = watchlists.get(active) or watchlists.get("Default") or []
    tickers = [t for t in tickers if isinstance(t, str) and t.strip()]
    return tickers or fallback


def _fetch_history(ticker: str, days: int) -> pd.DataFrame:
    """Pull daily OHLCV for the lookback window."""
    from data_loader import fetch_ticker_data
    end = datetime.utcnow().date()
    start = end - timedelta(days=days + 30)  # extra buffer for indicator warmup
    try:
        df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    except Exception as exc:
        logger.warning("[backtest] history fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.tail(days + 30)


def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    up = delta.clip(lower=0).rolling(window=period).mean()
    down = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = up / down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _simulate_ticker(
    ticker: str,
    df: pd.DataFrame,
    starting_cash: float,
    days: int,
) -> Tuple[List[Trade], Dict[str, Any]]:
    """Run an RSI cross strategy over ``df`` and return the trade log + stats."""
    if df.empty or len(df) < 20:
        return [], {"ticker": ticker, "trades": 0, "pnl": 0.0, "win_rate": 0.0}

    closes = df["Close"].astype(float)
    rsi = _compute_rsi(closes)

    cash = float(starting_cash)
    qty = 0.0
    entry_price = 0.0
    entry_date = ""
    trades: List[Trade] = []

    eval_window = df.tail(days)
    for ts, row in eval_window.iterrows():
        price = float(row["Close"])
        r = float(rsi.loc[ts]) if ts in rsi.index else 50.0
        date_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        # Buy when oversold and we're flat.
        if qty == 0 and r < 30 and price > 0:
            buy_qty = (cash * 0.5) / price
            if buy_qty <= 0:
                continue
            qty = buy_qty
            entry_price = price
            entry_date = date_str
            cash -= qty * price
            continue

        # Sell when overbought or stopped out (-5%).
        if qty > 0:
            ret = (price - entry_price) / entry_price if entry_price > 0 else 0.0
            if r > 70 or ret <= -0.05:
                exit_value = qty * price
                pnl = exit_value - (qty * entry_price)
                trades.append(Trade(
                    ticker=ticker,
                    entry_date=entry_date,
                    entry_price=round(entry_price, 4),
                    exit_date=date_str,
                    exit_price=round(price, 4),
                    quantity=round(qty, 4),
                    pnl=round(pnl, 4),
                    return_pct=round(ret * 100.0, 4),
                    reason="rsi_overbought" if r > 70 else "stop_loss",
                ))
                cash += exit_value
                qty = 0.0
                entry_price = 0.0
                entry_date = ""

    # Close any open position at the final close so the P&L is realised.
    if qty > 0 and not eval_window.empty:
        last_price = float(eval_window["Close"].iloc[-1])
        last_date = eval_window.index[-1]
        date_str = last_date.isoformat() if hasattr(last_date, "isoformat") else str(last_date)
        ret = (last_price - entry_price) / entry_price if entry_price > 0 else 0.0
        pnl = qty * (last_price - entry_price)
        trades.append(Trade(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=round(entry_price, 4),
            exit_date=date_str,
            exit_price=round(last_price, 4),
            quantity=round(qty, 4),
            pnl=round(pnl, 4),
            return_pct=round(ret * 100.0, 4),
            reason="end_of_window",
        ))
        cash += qty * last_price
        qty = 0.0

    wins = sum(1 for t in trades if t.pnl > 0)
    pnl_total = sum(t.pnl for t in trades)
    stats = {
        "ticker": ticker,
        "trades": len(trades),
        "pnl": round(pnl_total, 4),
        "win_rate": round(wins / len(trades), 4) if trades else 0.0,
        "ending_cash": round(cash, 4),
        "starting_cash": float(starting_cash),
    }
    return trades, stats


def run(
    days: int,
    tickers: Optional[List[str]],
    output_path: Path,
    config_path: Path,
    starting_cash: float = 1000.0,
) -> Dict[str, Any]:
    """Run the full replay and write results to ``output_path``."""
    if tickers:
        watchlist = [t.strip().upper() for t in tickers if t.strip()]
    else:
        watchlist = _load_default_watchlist(config_path)

    all_trades: List[Trade] = []
    per_ticker: List[Dict[str, Any]] = []

    for ticker in watchlist:
        df = _fetch_history(ticker, days)
        if df.empty:
            per_ticker.append({"ticker": ticker, "error": "no historical data"})
            continue
        trades, stats = _simulate_ticker(ticker, df, starting_cash, days)
        all_trades.extend(trades)
        per_ticker.append(stats)

    total_pnl = sum(t.pnl for t in all_trades)
    wins = sum(1 for t in all_trades if t.pnl > 0)
    win_rate = (wins / len(all_trades)) if all_trades else 0.0
    worst = sorted(all_trades, key=lambda t: t.pnl)[:5]

    result: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": int(days),
        "tickers": watchlist,
        "starting_cash_per_ticker": float(starting_cash),
        "total_trades": len(all_trades),
        "total_pnl": round(total_pnl, 4),
        "win_rate": round(win_rate, 4),
        "per_ticker": per_ticker,
        "trades": [asdict(t) for t in all_trades],
        "worst_trades": [asdict(t) for t in worst],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--days", type=int, default=30,
                        help="lookback window in calendar days (default 30)")
    parser.add_argument("--ticker", action="append", default=None,
                        help="repeatable: restrict to specific tickers")
    parser.add_argument("--output", type=str, default="data/backtest_results.json",
                        help="JSON output path (default data/backtest_results.json)")
    parser.add_argument("--config", type=str, default="config.json",
                        help="config.json path (read for the active watchlist)")
    parser.add_argument("--starting-cash", type=float, default=1000.0,
                        help="paper cash per ticker (default 1000)")
    parser.add_argument("--verbose", action="store_true",
                        help="enable info-level logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    result = run(
        days=int(args.days),
        tickers=args.ticker,
        output_path=Path(args.output),
        config_path=Path(args.config),
        starting_cash=float(args.starting_cash),
    )
    print(json.dumps({
        "tickers": len(result["tickers"]),
        "trades": result["total_trades"],
        "win_rate": result["win_rate"],
        "total_pnl": result["total_pnl"],
        "output": args.output,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
