"""Backtest runner — orchestrates the full walk-forward lifecycle.

Loads data, computes features, generates walk-forward splits, runs folds
(optionally in parallel across CPU cores), then aggregates metrics into
a single BacktestResult.
"""

from __future__ import annotations

import logging
import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from backtesting.data_prep import (
    generate_walk_forward_splits,
    prepare_backtest_data,
)
from backtesting.engine import BacktestEngine
from backtesting.metrics import compute_metrics
from backtesting.types import (
    BacktestConfig,
    BacktestResult,
    FoldResult,
    WalkForwardSplit,
)

logger = logging.getLogger(__name__)


class BacktestRunner:
    """Runs a complete walk-forward backtest.

    Usage:
        runner = BacktestRunner(config)
        result = runner.run(on_progress=print)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

    def run(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> BacktestResult:
        """Execute the full backtest pipeline.

        Steps:
            1. Load historical data for all tickers
            2. Pre-compute features and labels
            3. Generate walk-forward splits
            4. Run each fold (parallel or serial)
            5. Aggregate metrics
        """
        t0 = time.time()

        def _progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        # 1. Load data
        _progress("Loading historical data...")
        universe_data = self._load_data()
        if not universe_data:
            logger.error("No data loaded — aborting backtest")
            return BacktestResult(config=self._config, folds=[])

        _progress(f"Loaded {len(universe_data)} tickers")

        # 2. Pre-compute features
        _progress("Computing features for entire history...")
        features_by_ticker, labels_by_ticker = prepare_backtest_data(
            universe_data, self._config,
        )
        if not features_by_ticker:
            logger.error("No features computed — aborting backtest")
            return BacktestResult(config=self._config, folds=[])

        _progress(
            f"Features ready: {len(features_by_ticker)} tickers, "
            f"{sum(len(f) for f in features_by_ticker.values())} rows"
        )

        # 3. Generate walk-forward splits
        _progress("Generating walk-forward splits...")
        splits = generate_walk_forward_splits(features_by_ticker, self._config)
        if not splits:
            logger.error("No walk-forward splits generated — aborting")
            return BacktestResult(config=self._config, folds=[])

        _progress(f"Generated {len(splits)} walk-forward folds")

        # 4. Run folds
        n_cores = self._config.n_processes or os.cpu_count() or 4
        use_parallel = n_cores > 1 and len(splits) > 1

        if use_parallel:
            _progress(f"Running {len(splits)} folds across {n_cores} cores...")
            folds = self._run_parallel(
                splits, features_by_ticker, labels_by_ticker,
                universe_data, n_cores, _progress,
            )
        else:
            _progress(f"Running {len(splits)} folds serially...")
            folds = self._run_serial(
                splits, features_by_ticker, labels_by_ticker,
                universe_data, _progress,
            )

        _progress(f"All {len(folds)} folds complete")

        # 5. Aggregate metrics
        _progress("Computing aggregate metrics...")
        metrics = compute_metrics(folds, self._config) if folds else None

        duration = time.time() - t0
        _progress(f"Backtest finished in {duration:.1f}s")

        return BacktestResult(
            config=self._config,
            folds=folds,
            metrics=metrics,
            total_duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> Dict[str, pd.DataFrame]:
        """Load OHLCV data for all tickers in the config."""
        import json
        from data_loader import fetch_universe_data

        tickers = list(self._config.tickers)
        if not tickers:
            # Fall back to config.json watchlist
            try:
                with open("config.json") as f:
                    cfg = json.load(f)
                watchlists = cfg.get("watchlists", {})
                active = cfg.get("active_watchlist", "")
                tickers = watchlists.get(active, cfg.get("tickers", []))
            except Exception:
                pass

        if not tickers:
            logger.error("No tickers specified for backtest")
            return {}

        result = fetch_universe_data(
            tickers,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
        )

        # Filter out tickers with insufficient data
        filtered: Dict[str, pd.DataFrame] = {}
        for ticker, df in result.items():
            if len(df) >= 60:
                filtered[ticker] = df
            else:
                logger.warning("Skipping %s — only %d bars", ticker, len(df))

        return filtered

    # ------------------------------------------------------------------
    # Parallel execution
    # ------------------------------------------------------------------

    def _run_parallel(
        self,
        splits: List[WalkForwardSplit],
        features_by_ticker: Dict[str, pd.DataFrame],
        labels_by_ticker: Dict[str, pd.Series],
        universe_data: Dict[str, pd.DataFrame],
        n_cores: int,
        on_progress: Callable[[str], None],
    ) -> List[FoldResult]:
        """Run folds in parallel using ProcessPoolExecutor.

        Data is serialised via standard Python multiprocessing (pickle)
        for cross-process transfer — this is internal computation, not
        deserialisation of untrusted external data.
        """
        # Serialise shared data once (avoids repeated pickle overhead)
        shared_feats = _serialise_dataframes(features_by_ticker)
        shared_labels = _serialise_series(labels_by_ticker)
        shared_universe = _serialise_dataframes(universe_data)
        config_dict = _config_to_dict(self._config)

        results: Dict[int, FoldResult] = {}

        try:
            with ProcessPoolExecutor(max_workers=n_cores) as executor:
                future_to_fold = {
                    executor.submit(
                        _run_fold_worker,
                        split,
                        shared_feats,
                        shared_labels,
                        shared_universe,
                        config_dict,
                    ): split.fold_id
                    for split in splits
                }

                for future in as_completed(future_to_fold):
                    fold_id = future_to_fold[future]
                    try:
                        fold_result = future.result()
                        results[fold_id] = fold_result
                        on_progress(
                            f"Fold {fold_id}/{len(splits) - 1} complete "
                            f"(acc={fold_result.accuracy:.1%})"
                        )
                    except Exception as e:
                        logger.error("Fold %d failed: %s", fold_id, e)

        except Exception as e:
            logger.warning(
                "Parallel execution failed (%s) — falling back to serial", e
            )
            return self._run_serial(
                splits,
                features_by_ticker,
                labels_by_ticker,
                universe_data,
                on_progress,
            )

        # Return in fold order
        return [results[s.fold_id] for s in splits if s.fold_id in results]

    # ------------------------------------------------------------------
    # Serial execution (fallback)
    # ------------------------------------------------------------------

    def _run_serial(
        self,
        splits: List[WalkForwardSplit],
        features_by_ticker: Dict[str, pd.DataFrame],
        labels_by_ticker: Dict[str, pd.Series],
        universe_data: Dict[str, pd.DataFrame],
        on_progress: Callable[[str], None],
    ) -> List[FoldResult]:
        """Run folds one at a time (used when n_cores=1 or as fallback)."""
        engine = BacktestEngine(self._config)
        results: List[FoldResult] = []

        for i, split in enumerate(splits):
            fold_result = engine.run_fold(
                split,
                features_by_ticker,
                labels_by_ticker,
                universe_data,
                on_progress=lambda msg: on_progress(f"[{i+1}/{len(splits)}] {msg}"),
            )
            results.append(fold_result)
            on_progress(
                f"Fold {split.fold_id}/{len(splits) - 1} complete "
                f"(acc={fold_result.accuracy:.1%})"
            )

        return results


# ---------------------------------------------------------------------------
# Top-level worker function (must be picklable — no lambdas, no closures)
# ---------------------------------------------------------------------------

def _run_fold_worker(
    split: WalkForwardSplit,
    serialised_feats: Dict[str, Dict[str, Any]],
    serialised_labels: Dict[str, Dict[str, Any]],
    serialised_universe: Dict[str, Dict[str, Any]],
    config_dict: Dict[str, Any],
) -> FoldResult:
    """Execute one fold in a worker process.

    Accepts serialised (dict) versions of DataFrames to avoid pickling
    issues across process boundaries.
    """
    warnings.filterwarnings("ignore", category=UserWarning, module=r"sklearn\..*")
    warnings.filterwarnings("ignore", category=FutureWarning, module=r"sklearn\..*")

    config = _dict_to_config(config_dict)
    features = _deserialise_dataframes(serialised_feats)
    labels = _deserialise_series(serialised_labels)
    universe = _deserialise_dataframes(serialised_universe)

    engine = BacktestEngine(config)
    return engine.run_fold(split, features, labels, universe)


# ---------------------------------------------------------------------------
# Serialisation helpers (DataFrame ↔ dict for cross-process transfer)
# ---------------------------------------------------------------------------

def _serialise_dataframes(data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
    """Convert DataFrames to dicts for safe cross-process transfer."""
    return {
        ticker: {
            "values": df.values.tolist(),
            "columns": list(df.columns),
            "index": df.index.tolist(),
        }
        for ticker, df in data.items()
    }


def _deserialise_dataframes(data: Dict[str, Dict[str, Any]]) -> Dict[str, pd.DataFrame]:
    """Reconstruct DataFrames from serialised dicts."""
    result: Dict[str, pd.DataFrame] = {}
    for ticker, parts in data.items():
        df = pd.DataFrame(
            parts["values"],
            columns=parts["columns"],
            index=pd.DatetimeIndex(parts["index"]),
        )
        result[ticker] = df
    return result


def _serialise_series(data: Dict[str, pd.Series]) -> Dict[str, Dict[str, Any]]:
    """Convert Series to dicts for safe cross-process transfer."""
    return {
        ticker: {
            "values": s.values.tolist(),
            "index": s.index.tolist(),
            "name": s.name,
        }
        for ticker, s in data.items()
    }


def _deserialise_series(data: Dict[str, Dict[str, Any]]) -> Dict[str, pd.Series]:
    """Reconstruct Series from serialised dicts."""
    result: Dict[str, pd.Series] = {}
    for ticker, parts in data.items():
        s = pd.Series(
            parts["values"],
            index=pd.DatetimeIndex(parts["index"]),
            name=parts["name"],
        )
        result[ticker] = s
    return result


def _config_to_dict(config: BacktestConfig) -> Dict[str, Any]:
    """Serialise BacktestConfig to a plain dict."""
    from dataclasses import asdict
    return asdict(config)


def _dict_to_config(d: Dict[str, Any]) -> BacktestConfig:
    """Reconstruct BacktestConfig from a dict."""
    return BacktestConfig(**d)
