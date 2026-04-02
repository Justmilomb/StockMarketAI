"""Backtest runner — orchestrates the full walk-forward lifecycle.

Loads data, computes features, generates walk-forward splits, runs folds
(optionally in parallel across CPU cores), then aggregates metrics into
a single BacktestResult.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import pickle
import tempfile
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

# Shared data loaded once per worker process via initializer
_worker_shared_data: Dict[str, Any] = {}


def _detect_parallel_folds() -> int:
    """Return configured max parallel folds from cpu_config."""
    from cpu_config import get_max_parallel_folds
    return get_max_parallel_folds()


def _detect_n_jobs_per_fold() -> int:
    """Return n_jobs for scikit-learn inside each parallel fold worker."""
    from cpu_config import get_n_jobs_per_fold
    return get_n_jobs_per_fold()


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

        # 4. Run folds — always prefer parallel when multiple folds exist
        detected_folds = _detect_parallel_folds()
        if self._config.n_processes is not None and self._config.n_processes > 1:
            n_workers = self._config.n_processes
        else:
            n_workers = detected_folds
        # Ensure we use at least as many workers as cores allow
        n_workers = max(n_workers, 2)
        use_parallel = len(splits) > 1

        from cpu_config import get_cpu_cores, _load_config as _load_cpu_config
        _raw = _load_cpu_config()
        _progress(
            f"[debug] cpu_cores={get_cpu_cores()}, "
            f"config_raw={_raw.get('cpu_cores')}, "
            f"max_folds={_raw.get('max_parallel_folds')}, "
            f"os.cpu_count={os.cpu_count()}, "
            f"n_processes_cfg={self._config.n_processes}, "
            f"detected_folds={detected_folds}, "
            f"n_workers={n_workers}"
        )

        if use_parallel:
            n_jobs = _detect_n_jobs_per_fold()
            _progress(f"Running {len(splits)} folds across {n_workers} workers × {n_jobs} threads each = {n_workers * n_jobs} total threads")
            folds = self._run_parallel(
                splits, features_by_ticker, labels_by_ticker,
                universe_data, n_workers, _progress,
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

        Shared data (features, labels, universe) is written to a temp file
        once, then each worker reads it at startup via the process initializer.
        This avoids re-pickling the full dataset for every fold submission
        (the old .tolist() approach was 10-100x slower).
        """
        config_dict = _config_to_dict(self._config)
        results: Dict[int, FoldResult] = {}
        tmp_path: Optional[str] = None

        try:
            # Write shared data to temp file — workers load once via initializer
            on_progress("Serialising shared data for workers...")
            t_ser = time.time()
            shared_data = {
                "features": features_by_ticker,
                "labels": labels_by_ticker,
                "universe": universe_data,
            }
            fd, tmp_path = tempfile.mkstemp(suffix=".pkl")
            with os.fdopen(fd, "wb") as tmp:
                pickle.dump(shared_data, tmp, protocol=pickle.HIGHEST_PROTOCOL)
            ser_mb = os.path.getsize(tmp_path) / (1024 * 1024)
            on_progress(f"Shared data written: {ser_mb:.1f} MB in {time.time() - t_ser:.1f}s")

            # Force "spawn" on Linux — "fork" deadlocks inside OpenBLAS/MKL
            # when numpy/sklearn are already loaded in the parent process.
            # Windows already defaults to "spawn" so this is a no-op there.
            ctx = mp.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=n_cores,
                initializer=_init_fold_worker,
                initargs=(tmp_path, n_jobs),
                mp_context=ctx,
            ) as executor:
                future_to_fold = {
                    executor.submit(
                        _run_fold_worker,
                        split,
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
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

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
# Worker process initializer + fold executor
# ---------------------------------------------------------------------------

def _init_fold_worker(shared_data_path: str, n_jobs_per_fold: int) -> None:
    """Load shared data from disk once when worker process starts.

    Uses pickle for internal IPC — all data originates from this
    application's own DataFrames, not external/untrusted sources.
    """
    # Limit per-worker CPU usage so sklearn models don't over-subscribe.
    # Must be set BEFORE any call to get_cpu_cores() (which is lru_cached).
    os.environ["AUTOCONFIG_CPU_CORES"] = str(n_jobs_per_fold)

    global _worker_shared_data
    with open(shared_data_path, "rb") as f:  # noqa: S301 — trusted internal IPC
        _worker_shared_data = pickle.load(f)  # noqa: S301


def _run_fold_worker(
    split: WalkForwardSplit,
    config_dict: Dict[str, Any],
) -> FoldResult:
    """Execute one fold in a worker process using shared data from initializer."""
    warnings.filterwarnings("ignore", category=UserWarning, module=r"sklearn\..*")
    warnings.filterwarnings("ignore", category=FutureWarning, module=r"sklearn\..*")

    config = _dict_to_config(config_dict)

    engine = BacktestEngine(config)
    return engine.run_fold(
        split,
        _worker_shared_data["features"],
        _worker_shared_data["labels"],
        _worker_shared_data["universe"],
    )


def _config_to_dict(config: BacktestConfig) -> Dict[str, Any]:
    """Serialise BacktestConfig to a plain dict."""
    from dataclasses import asdict
    return asdict(config)


def _dict_to_config(d: Dict[str, Any]) -> BacktestConfig:
    """Reconstruct BacktestConfig from a dict."""
    return BacktestConfig(**d)
