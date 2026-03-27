"""N-BEATS deep learning time-series forecaster.

Implements a lightweight N-BEATS neural architecture for multi-horizon
stock return forecasting.  Falls back gracefully when PyTorch is absent.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

try:
    from scipy.stats import norm as _norm_dist
except ImportError:
    _norm_dist = None  # type: ignore[assignment]

from types_shared import ForecasterSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation — torch is optional
# ---------------------------------------------------------------------------

_HAS_TORCH = False
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    _HAS_TORCH = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# N-BEATS architecture (only materialised when torch is available)
# ---------------------------------------------------------------------------

if _HAS_TORCH:

    class NBeatsBlock(nn.Module):
        """Generic N-BEATS block with FC stack and dual linear heads.

        Each block learns a backcast (reconstruction of past) and a forecast
        (projection into the future) via basis expansion on theta vectors.
        """

        def __init__(
            self,
            lookback: int,
            horizon: int,
            hidden_dim: int,
        ) -> None:
            super().__init__()
            self.lookback = lookback
            self.horizon = horizon

            self.fc_stack = nn.Sequential(
                nn.Linear(lookback, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
            )

            # Theta vectors projected back into time-domain via simple linear basis
            self.theta_backcast = nn.Linear(hidden_dim, lookback)
            self.theta_forecast = nn.Linear(hidden_dim, horizon)

        def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            """Return (backcast, forecast) tensors."""
            h = self.fc_stack(x)
            backcast = self.theta_backcast(h)
            forecast = self.theta_forecast(h)
            return backcast, forecast

    class NBeatsStack(nn.Module):
        """Stack of N-BEATS blocks with residual subtraction."""

        def __init__(
            self,
            n_blocks: int,
            lookback: int,
            horizon: int,
            hidden_dim: int,
        ) -> None:
            super().__init__()
            self.blocks = nn.ModuleList(
                [NBeatsBlock(lookback, horizon, hidden_dim) for _ in range(n_blocks)]
            )

        def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            """Residual learning: subtract backcasts, accumulate forecasts."""
            residual = x
            stack_forecast = torch.zeros(
                x.size(0), self.blocks[0].horizon, device=x.device
            )
            for block in self.blocks:
                backcast, forecast = block(residual)
                residual = residual - backcast
                stack_forecast = stack_forecast + forecast
            return residual, stack_forecast

    class NBeatsModel(nn.Module):
        """Full N-BEATS model with two generic stacks (trend + detail).

        Input shape:  ``(batch, lookback_window)``
        Output shape: ``(batch, horizon)``
        """

        def __init__(
            self,
            lookback: int,
            horizon: int,
            hidden_dim: int = 128,
            n_blocks: int = 3,
        ) -> None:
            super().__init__()
            self.stacks = nn.ModuleList(
                [
                    NBeatsStack(n_blocks, lookback, horizon, hidden_dim),
                    NBeatsStack(n_blocks, lookback, horizon, hidden_dim),
                ]
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            """Each stack processes the residual; forecasts accumulate."""
            residual = x
            total_forecast = torch.zeros(
                x.size(0),
                self.stacks[0].blocks[0].horizon,
                device=x.device,
            )
            for stack in self.stacks:
                residual, stack_forecast = stack(residual)
                total_forecast = total_forecast + stack_forecast
            return total_forecast


# ---------------------------------------------------------------------------
# Default config values
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: Dict[str, int | float | str] = {
    "lookback_window": 60,
    "hidden_dim": 128,
    "n_blocks": 3,
    "epochs": 50,
    "batch_size": 32,
    "learning_rate": 0.001,
    "cache_dir": "models/deep",
}


# ---------------------------------------------------------------------------
# Public forecaster class
# ---------------------------------------------------------------------------


class DeepForecaster:
    """N-BEATS based deep learning forecaster.

    Pools cross-sectional return series from the entire universe, trains a
    single N-BEATS model per horizon, then produces ``ForecasterSignal``
    objects for every ticker.
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        cfg = {**_DEFAULT_CONFIG, **(config or {})}
        self._lookback: int = int(cfg["lookback_window"])
        self._hidden_dim: int = int(cfg["hidden_dim"])
        self._n_blocks: int = int(cfg["n_blocks"])
        self._epochs: int = int(cfg["epochs"])
        self._batch_size: int = int(cfg["batch_size"])
        self._lr: float = float(cfg["learning_rate"])
        self._cache_dir: Path = Path(str(cfg["cache_dir"]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True when PyTorch is installed and importable."""
        return _HAS_TORCH

    def fit_and_predict(
        self,
        universe_data: Dict[str, pd.DataFrame],
        horizons: List[int],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> Dict[str, List[ForecasterSignal]]:
        """Train (or load cached) N-BEATS models and produce signals.

        Args:
            universe_data: ``{ticker: OHLCV DataFrame}`` with DatetimeIndex.
            horizons: List of forecast horizons in trading days.
            on_progress: Optional ``(current, total, detail)`` callback.

        Returns:
            ``{ticker: [ForecasterSignal per horizon]}``; empty dict on
            any failure or if torch is unavailable.
        """
        if not _HAS_TORCH:
            logger.info("PyTorch not installed — deep forecaster skipped.")
            return {}

        try:
            return self._run(universe_data, horizons, on_progress)
        except Exception:
            logger.exception("Deep forecaster failed — returning empty results.")
            return {}

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run(
        self,
        universe_data: Dict[str, pd.DataFrame],
        horizons: List[int],
        on_progress: Callable[[int, int, str], None] | None,
    ) -> Dict[str, List[ForecasterSignal]]:
        """Core orchestration: collect returns, train per horizon, predict."""
        # Gather log-returns for every ticker with enough history
        all_returns: List[pd.Series] = []
        ticker_returns: Dict[str, pd.Series] = {}
        min_required = self._lookback + max(horizons) + 10  # small buffer

        for ticker, df in universe_data.items():
            if df is None or len(df) < min_required:
                continue
            close = df["Close"].dropna()
            if len(close) < min_required:
                continue
            rets = close.pct_change().dropna()
            all_returns.append(rets)
            ticker_returns[ticker] = rets

        if not all_returns:
            logger.warning("No tickers have enough history for deep forecaster.")
            return {}

        tickers = list(ticker_returns.keys())
        total_steps = len(horizons) * (1 + len(tickers))  # train + predict per ticker
        step = 0

        results: Dict[str, List[ForecasterSignal]] = {t: [] for t in tickers}

        for horizon in horizons:
            # --- train / load model ---
            if on_progress:
                on_progress(step, total_steps, f"N-BEATS h{horizon}: training")
            model = self._load_or_train(all_returns, horizon)
            if model is None:
                step += 1 + len(tickers)
                continue
            step += 1

            # --- predict per ticker ---
            for ticker in tickers:
                if on_progress:
                    on_progress(step, total_steps, f"N-BEATS h{horizon}: {ticker}")
                rets = ticker_returns[ticker]
                recent = rets.values[-self._lookback :]
                if len(recent) < self._lookback:
                    step += 1
                    continue

                prob, forecast_ret, conf = self._predict_ticker(
                    model, recent, horizon
                )
                results[ticker].append(
                    ForecasterSignal(
                        family="deep_learning",
                        ticker=ticker,
                        probability=prob,
                        confidence=conf,
                        forecast_return=forecast_ret,
                        horizon_days=horizon,
                        model_name="nbeats",
                    )
                )
                step += 1

        if on_progress:
            on_progress(total_steps, total_steps, "N-BEATS complete")

        # Drop tickers with no signals
        return {t: sigs for t, sigs in results.items() if sigs}

    # ------------------------------------------------------------------
    # Window preparation
    # ------------------------------------------------------------------

    def _prepare_windows(
        self,
        all_returns: List[pd.Series],
        lookback: int,
        horizon: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Create sliding-window (X, y) pairs from pooled return series.

        Args:
            all_returns: Per-ticker return series.
            lookback: Number of past returns per input window.
            horizon: Number of future returns per target window.

        Returns:
            ``(X, y)`` with shapes ``(n_windows, lookback)`` and
            ``(n_windows, horizon)``.
        """
        xs: List[np.ndarray] = []
        ys: List[np.ndarray] = []
        window_total = lookback + horizon

        for series in all_returns:
            vals = series.values
            if len(vals) < window_total:
                continue
            for i in range(len(vals) - window_total + 1):
                xs.append(vals[i : i + lookback])
                ys.append(vals[i + lookback : i + window_total])

        if not xs:
            return np.empty((0, lookback)), np.empty((0, horizon))

        return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train_model(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        horizon: int,
    ) -> object:
        """Train an N-BEATS model from scratch.

        Applies z-score normalisation per window, uses Adam + MSE, and
        performs early stopping when validation loss stalls for 10 epochs.

        Returns:
            Trained ``NBeatsModel`` (on CPU).
        """
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Chronological train/val split (80/20)
        split_idx = int(len(X_train) * 0.8)
        X_tr, X_val = X_train[:split_idx], X_train[split_idx:]
        y_tr, y_val = y_train[:split_idx], y_train[split_idx:]

        if len(X_tr) == 0 or len(X_val) == 0:
            logger.warning("Insufficient data for train/val split — skipping.")
            return None  # type: ignore[return-value]

        # Z-score normalisation per window
        X_tr, y_tr = self._normalize_windows(X_tr, y_tr)
        X_val, y_val = self._normalize_windows(X_val, y_val)

        # Tensors
        train_ds = TensorDataset(
            torch.tensor(X_tr, dtype=torch.float32),
            torch.tensor(y_tr, dtype=torch.float32),
        )
        val_ds = TensorDataset(
            torch.tensor(X_val, dtype=torch.float32),
            torch.tensor(y_val, dtype=torch.float32),
        )
        train_loader = DataLoader(train_ds, batch_size=self._batch_size, shuffle=True)
        val_loader = DataLoader(val_ds, batch_size=self._batch_size, shuffle=False)

        model = NBeatsModel(
            lookback=self._lookback,
            horizon=horizon,
            hidden_dim=self._hidden_dim,
            n_blocks=self._n_blocks,
        ).to(device)

        optimiser = torch.optim.Adam(model.parameters(), lr=self._lr)
        criterion = nn.MSELoss()

        best_val_loss = float("inf")
        patience_counter = 0
        best_state: Dict[str, Any] = {}

        for epoch in range(self._epochs):
            # --- training ---
            model.train()
            train_loss = 0.0
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                optimiser.zero_grad()
                pred = model(xb)
                loss = criterion(pred, yb)
                loss.backward()
                optimiser.step()
                train_loss += loss.item() * xb.size(0)
            train_loss /= len(train_ds)

            # --- validation ---
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    pred = model(xb)
                    val_loss += criterion(pred, yb).item() * xb.size(0)
            val_loss /= len(val_ds)

            # --- early stopping ---
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= 10:
                    logger.info(
                        "Early stop at epoch %d (val_loss=%.6f).", epoch + 1, best_val_loss
                    )
                    break

            if (epoch + 1) % 10 == 0:
                logger.debug(
                    "Epoch %d/%d  train=%.6f  val=%.6f",
                    epoch + 1,
                    self._epochs,
                    train_loss,
                    val_loss,
                )

        # Restore best weights
        if best_state:
            model.load_state_dict(best_state)
        model = model.cpu().eval()

        # Persist to cache
        self._save_model(model, horizon)
        return model

    # ------------------------------------------------------------------
    # Load / train gate
    # ------------------------------------------------------------------

    def _load_or_train(
        self,
        all_returns: List[pd.Series],
        horizon: int,
    ) -> object:
        """Return a cached model if fresh, otherwise train a new one.

        A cached model is considered fresh if its file is less than
        24 hours old.
        """
        cache_path = self._cache_dir / f"nbeats_h{horizon}.pt"
        if cache_path.exists():
            age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
            if age_hours < 24:
                try:
                    model = NBeatsModel(
                        lookback=self._lookback,
                        horizon=horizon,
                        hidden_dim=self._hidden_dim,
                        n_blocks=self._n_blocks,
                    )
                    model.load_state_dict(
                        torch.load(cache_path, map_location="cpu", weights_only=True)
                    )
                    model.eval()
                    logger.info("Loaded cached N-BEATS model for h=%d.", horizon)
                    return model
                except Exception:
                    logger.warning(
                        "Failed to load cached model for h=%d — retraining.",
                        horizon,
                    )

        X, y = self._prepare_windows(all_returns, self._lookback, horizon)
        if len(X) == 0:
            logger.warning("No training windows for h=%d — skipping.", horizon)
            return None
        return self._train_model(X, y, horizon)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def _predict_ticker(
        self,
        model: object,
        recent_returns: np.ndarray,
        horizon: int,
    ) -> Tuple[float, float, float]:
        """Run inference for a single ticker.

        Args:
            model: Trained ``NBeatsModel``.
            recent_returns: Last ``lookback`` daily returns.
            horizon: Number of days to forecast.

        Returns:
            ``(probability, forecast_return, confidence)``
        """
        net: NBeatsModel = model  # type: ignore[assignment]

        # Z-score normalise the input window
        window = recent_returns.astype(np.float32).copy()
        mu = window.mean()
        std = window.std()
        if std < 1e-9:
            std = 1e-9
        window_norm = (window - mu) / std

        x_tensor = torch.tensor(window_norm, dtype=torch.float32).unsqueeze(0)

        with torch.no_grad():
            forecast_norm = net(x_tensor).squeeze(0).numpy()

        # De-normalise forecast
        forecast = forecast_norm * std + mu
        cumulative_return: float = float(np.sum(forecast))
        forecast_std: float = float(np.std(forecast)) if len(forecast) > 1 else abs(cumulative_return) * 0.5

        # Probability conversion via normal CDF
        if forecast_std < 1e-9:
            probability = 0.95 if cumulative_return > 0 else 0.05
        else:
            probability = float(_norm_dist.cdf(0, loc=-cumulative_return, scale=forecast_std))

        # Clamp to [0.05, 0.95]
        probability = max(0.05, min(0.95, probability))

        # Confidence: how far from 0.5 the probability sits
        confidence = min(1.0, abs(probability - 0.5) * 4.0)

        return probability, cumulative_return, confidence

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_windows(
        X: np.ndarray,
        y: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Per-window z-score normalisation.

        Computes mean and std from the X (lookback) portion of each window,
        then applies to both X and y so the model learns scale-invariant
        patterns.

        Returns:
            Normalised copies of ``(X, y)``.
        """
        X_out = X.copy()
        y_out = y.copy()

        means = X.mean(axis=1, keepdims=True)
        stds = X.std(axis=1, keepdims=True)
        stds = np.where(stds < 1e-9, 1e-9, stds)

        X_out = (X_out - means) / stds
        y_out = (y_out - means) / stds

        return X_out, y_out

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_model(self, model: object, horizon: int) -> None:
        """Save model state dict to the cache directory."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"nbeats_h{horizon}.pt"
        try:
            torch.save(model.state_dict(), path)  # type: ignore[union-attr]
            logger.info("Saved N-BEATS model to %s.", path)
        except Exception:
            logger.warning("Could not save N-BEATS model to %s.", path)
