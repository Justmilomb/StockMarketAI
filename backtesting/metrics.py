"""Performance metrics — computes Sharpe, drawdown, win rate, attribution, etc.

Takes raw trade records and daily snapshots from the backtest engine and
produces a single PerformanceMetrics summary.
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from backtesting.types import (
    BacktestConfig,
    DailySnapshot,
    FoldResult,
    PerformanceMetrics,
    TradeRecord,
)


def compute_metrics(
    folds: List[FoldResult],
    config: BacktestConfig,
) -> PerformanceMetrics:
    """Aggregate all fold results into a single PerformanceMetrics."""

    # Collect all trades and snapshots across folds
    all_trades: List[TradeRecord] = []
    all_snapshots: List[DailySnapshot] = []
    for fold in folds:
        all_trades.extend(fold.trades)
        all_snapshots.extend(fold.daily_snapshots)

    # Sort snapshots chronologically
    all_snapshots.sort(key=lambda s: s.date)

    # -- Signal quality (from fast-mode data) ---------------------------------
    total_preds = sum(f.n_predictions for f in folds)
    total_correct = sum(f.n_correct for f in folds)
    signal_accuracy = total_correct / total_preds if total_preds > 0 else 0.0

    # Weighted precision/recall across folds
    weighted_precision = _weighted_avg(folds, "precision", "n_predictions")
    weighted_recall = _weighted_avg(folds, "recall", "n_predictions")

    # -- Trade statistics -----------------------------------------------------
    total_trades = len(all_trades)
    if total_trades == 0:
        return PerformanceMetrics(
            signal_accuracy=signal_accuracy,
            signal_precision=weighted_precision,
            signal_recall=weighted_recall,
        )

    winners = [t for t in all_trades if t.pnl > 0]
    losers = [t for t in all_trades if t.pnl <= 0]
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = winning_trades / total_trades

    gross_profit = sum(t.pnl for t in winners) if winners else 0.0
    gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win_pct = float(np.mean([t.pnl_pct for t in winners])) if winners else 0.0
    avg_loss_pct = float(np.mean([t.pnl_pct for t in losers])) if losers else 0.0
    best_trade_pct = max(t.pnl_pct for t in all_trades)
    worst_trade_pct = min(t.pnl_pct for t in all_trades)
    avg_hold_days = float(np.mean([t.hold_days for t in all_trades]))

    # -- Equity curve metrics -------------------------------------------------
    # Each fold starts with fresh capital, so we chain fold equity curves:
    # fold 2 starts from fold 1's ending equity, not from initial_capital.
    initial = config.initial_capital
    equity_curve: List[float] = []
    equity_dates: List[str] = []
    daily_returns: List[float] = []

    running_equity = initial
    peak_equity = initial

    for fold in folds:
        if not fold.daily_snapshots:
            continue

        # How much this fold gained/lost relative to its own starting capital
        fold_start = fold.daily_snapshots[0].equity - fold.daily_snapshots[0].daily_return * fold.daily_snapshots[0].equity
        # Use first snapshot's equity as fold start (before any daily return)
        fold_start_equity = initial  # Each fold starts from initial_capital

        for snap in fold.daily_snapshots:
            # Scale this snapshot's equity relative to the running total
            fold_gain_ratio = snap.equity / fold_start_equity
            chained_equity = running_equity * fold_gain_ratio
            equity_curve.append(chained_equity)
            equity_dates.append(str(snap.date))

            # Daily return from chained curve
            if len(equity_curve) >= 2:
                prev = equity_curve[-2]
                daily_returns.append((chained_equity / prev - 1.0) if prev > 0 else 0.0)
            else:
                daily_returns.append(0.0)

        # Advance running equity by this fold's total gain/loss
        if fold.daily_snapshots:
            fold_final = fold.daily_snapshots[-1].equity
            fold_return = fold_final / fold_start_equity
            running_equity *= fold_return

    # Drawdown from chained equity curve
    drawdown_curve: List[float] = []
    peak = initial
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        drawdown_curve.append(dd)

    # Total return
    final_equity = equity_curve[-1] if equity_curve else initial
    total_return_pct = (final_equity / initial - 1.0) * 100.0

    # Annualised return
    n_days = len(equity_curve)
    years = n_days / 252.0 if n_days > 0 else 1.0
    annualised_return_pct = (
        (final_equity / initial) ** (1.0 / max(years, 0.01)) - 1.0
    ) * 100.0 if final_equity > 0 else 0.0

    # -- Risk metrics ---------------------------------------------------------
    sharpe = _sharpe_ratio(daily_returns)
    sortino = _sortino_ratio(daily_returns)

    # Max drawdown
    max_dd = max(drawdown_curve) * 100.0 if drawdown_curve else 0.0
    avg_dd = float(np.mean([d for d in drawdown_curve if d > 0])) * 100.0 if any(d > 0 for d in drawdown_curve) else 0.0

    # Max drawdown duration (days underwater)
    max_dd_days = _max_drawdown_duration(drawdown_curve)

    # Calmar ratio
    calmar = annualised_return_pct / max_dd if max_dd > 0 else 0.0

    # -- Per-source attribution -----------------------------------------------
    per_source = _compute_attribution(all_trades)

    return PerformanceMetrics(
        total_return_pct=total_return_pct,
        annualised_return_pct=annualised_return_pct,
        buy_and_hold_return_pct=0.0,  # Filled by runner if benchmark available
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown_pct=max_dd,
        avg_drawdown_pct=avg_dd,
        max_drawdown_days=max_dd_days,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        best_trade_pct=best_trade_pct,
        worst_trade_pct=worst_trade_pct,
        avg_hold_days=avg_hold_days,
        signal_accuracy=signal_accuracy,
        signal_precision=weighted_precision,
        signal_recall=weighted_recall,
        per_source_accuracy=per_source,
        equity_curve=equity_curve,
        equity_dates=equity_dates,
        drawdown_curve=[d * 100 for d in drawdown_curve],
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sharpe_ratio(daily_returns: List[float], risk_free_daily: float = 0.0) -> float:
    """Annualised Sharpe ratio from daily returns."""
    if len(daily_returns) < 10:
        return 0.0
    arr = np.array(daily_returns)
    excess = arr - risk_free_daily
    mean_excess = float(np.mean(excess))
    std = float(np.std(excess, ddof=1))
    if std < 1e-10:
        return 0.0
    return mean_excess / std * math.sqrt(252)


def _sortino_ratio(daily_returns: List[float], risk_free_daily: float = 0.0) -> float:
    """Annualised Sortino ratio (only penalises downside volatility)."""
    if len(daily_returns) < 10:
        return 0.0
    arr = np.array(daily_returns)
    excess = arr - risk_free_daily
    mean_excess = float(np.mean(excess))
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf") if mean_excess > 0 else 0.0
    downside_std = float(np.std(downside, ddof=1))
    if downside_std < 1e-10:
        return 0.0
    return mean_excess / downside_std * math.sqrt(252)


def _max_drawdown_duration(drawdown_curve: List[float]) -> int:
    """Longest consecutive period of being in drawdown (days)."""
    max_dur = 0
    current_dur = 0
    for dd in drawdown_curve:
        if dd > 0.001:
            current_dur += 1
            max_dur = max(max_dur, current_dur)
        else:
            current_dur = 0
    return max_dur


def _compute_attribution(trades: List[TradeRecord]) -> Dict[str, float]:
    """Group trades by signal probability bands and compute win rates."""
    bands = {
        "strong_buy (>0.70)": (0.70, 1.01),
        "buy (0.55-0.70)": (0.55, 0.70),
        "weak_buy (0.50-0.55)": (0.50, 0.55),
    }
    result: Dict[str, float] = {}
    for band_name, (lo, hi) in bands.items():
        band_trades = [t for t in trades if lo <= t.signal_prob < hi]
        if band_trades:
            wins = sum(1 for t in band_trades if t.pnl > 0)
            result[band_name] = wins / len(band_trades)
    return result


def _weighted_avg(folds: List[FoldResult], attr: str, weight_attr: str) -> float:
    """Weighted average of a fold attribute."""
    total_weight = sum(getattr(f, weight_attr, 0) for f in folds)
    if total_weight == 0:
        return 0.0
    return sum(getattr(f, attr, 0) * getattr(f, weight_attr, 0) for f in folds) / total_weight


def format_report(result: "BacktestResult") -> str:
    """Generate a human-readable text report from backtest results."""
    from backtesting.types import BacktestResult

    m = result.metrics
    if m is None:
        return "No metrics available — backtest may have produced no trades."

    lines = [
        "=" * 70,
        "  BACKTEST RESULTS",
        "=" * 70,
        "",
        f"  Period:        {result.config.start_date} -> {result.config.end_date}",
        f"  Tickers:       {len(result.config.tickers)}",
        f"  Folds:         {len(result.folds)}",
        f"  Mode:          {result.config.mode}",
        f"  Duration:      {result.total_duration_seconds:.1f}s",
        "",
        "--- SIGNAL QUALITY " + "-" * 50,
        f"  Accuracy:      {m.signal_accuracy:.1%}",
        f"  Precision:     {m.signal_precision:.1%}",
        f"  Recall:        {m.signal_recall:.1%}",
        "",
    ]

    if m.total_trades > 0:
        lines.extend([
            "--- RETURNS " + "-" * 57,
            f"  Total Return:      {m.total_return_pct:+.2f}%",
            f"  Annualised:        {m.annualised_return_pct:+.2f}%",
            f"  Buy & Hold:        {m.buy_and_hold_return_pct:+.2f}%",
            "",
            "--- RISK " + "-" * 60,
            f"  Sharpe Ratio:      {m.sharpe_ratio:.2f}",
            f"  Sortino Ratio:     {m.sortino_ratio:.2f}",
            f"  Calmar Ratio:      {m.calmar_ratio:.2f}",
            f"  Max Drawdown:      {m.max_drawdown_pct:.2f}%",
            f"  Avg Drawdown:      {m.avg_drawdown_pct:.2f}%",
            f"  Max DD Duration:   {m.max_drawdown_days} days",
            "",
            "--- TRADES " + "-" * 58,
            f"  Total Trades:      {m.total_trades}",
            f"  Win Rate:          {m.win_rate:.1%}",
            f"  Profit Factor:     {m.profit_factor:.2f}",
            f"  Avg Win:           {m.avg_win_pct:+.2f}%",
            f"  Avg Loss:          {m.avg_loss_pct:+.2f}%",
            f"  Best Trade:        {m.best_trade_pct:+.2f}%",
            f"  Worst Trade:       {m.worst_trade_pct:+.2f}%",
            f"  Avg Hold:          {m.avg_hold_days:.1f} days",
            "",
        ])

        if m.per_source_accuracy:
            lines.append("--- SIGNAL ATTRIBUTION " + "-" * 46)
            for band, wr in sorted(m.per_source_accuracy.items()):
                lines.append(f"  {band:25s} win rate: {wr:.1%}")
            lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)
