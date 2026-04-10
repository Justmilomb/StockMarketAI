"""Chart panel — candlestick + volume chart with pyqtgraph."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

logger = logging.getLogger(__name__)

# Fallback periods if the first one returns no data
_PERIODS = ["1y", "6mo", "3mo", "1mo"]


class ChartPanel(QGroupBox):
    """OHLC candlestick chart with volume bars and 20-day SMA."""

    def __init__(self, state: Any) -> None:
        super().__init__("CHART")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 16, 4, 4)

        self._title_label = QLabel("Select a ticker (G)")
        self._title_label.setStyleSheet("color: #ff8c00; font-weight: bold;")
        layout.addWidget(self._title_label)

        self._price_plot = None
        self._volume_plot = None
        self._has_pyqtgraph = False
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888888; font-size: 11px;")

        try:
            import pyqtgraph as pg

            pg.setConfigOptions(background="#000000", foreground="#ffd700", antialias=True)

            # Price pane (candlestick + SMA)
            self._price_plot = pg.PlotWidget()
            self._price_plot.showGrid(x=True, y=True, alpha=0.15)
            self._price_plot.getAxis("bottom").setPen("#333333")
            self._price_plot.getAxis("left").setPen("#333333")
            self._price_plot.setLabel("left", "Price", color="#888888")
            layout.addWidget(self._price_plot, 4)

            # Volume pane
            self._volume_plot = pg.PlotWidget()
            self._volume_plot.showGrid(x=True, y=True, alpha=0.10)
            self._volume_plot.getAxis("bottom").setPen("#333333")
            self._volume_plot.getAxis("left").setPen("#333333")
            self._volume_plot.setLabel("left", "Vol", color="#888888")
            layout.addWidget(self._volume_plot, 1)

            # Link X axes
            self._volume_plot.setXLink(self._price_plot)

            self._has_pyqtgraph = True
        except Exception as exc:
            logger.warning("pyqtgraph chart init failed: %s", exc)
            fallback = QLabel(f"Chart unavailable — {type(exc).__name__}: {exc}")
            fallback.setStyleSheet("color: #ff5555;")
            layout.addWidget(fallback, 1)

        layout.addWidget(self._info_label)
        self._current_ticker = ""

    def refresh_view(self, state: Any) -> None:
        """Chart updates via load_chart() only."""

    def load_chart(self, ticker: str) -> None:
        """Fetch OHLCV data via yfinance and render candlestick chart.

        Tries multiple periods as fallback. Handles yfinance MultiIndex
        columns and NaN values gracefully.
        """
        self._current_ticker = ticker
        self._title_label.setText(f"CHART - {ticker}")
        self._info_label.setText("Loading...")

        try:
            import yfinance as yf

            data = None
            for period in _PERIODS:
                try:
                    df = yf.download(
                        ticker, period=period, interval="1d",
                        progress=False, timeout=10,
                    )
                    if df is not None and not df.empty and len(df) >= 2:
                        data = df
                        break
                except Exception:
                    continue

            if data is None or data.empty:
                self._info_label.setText(f"No data for {ticker}")
                return

            # Handle yfinance MultiIndex columns (newer versions)
            if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
                data.columns = data.columns.droplevel(1)

            # Extract arrays, drop NaN rows
            required = ["Open", "High", "Low", "Close", "Volume"]
            missing = [c for c in required if c not in data.columns]
            if missing:
                self._info_label.setText(f"Missing columns: {missing}")
                return

            data = data[required].dropna()
            if len(data) < 2:
                self._info_label.setText(f"Insufficient data for {ticker}")
                return

            opens = data["Open"].values.astype(float).flatten()
            highs = data["High"].values.astype(float).flatten()
            lows = data["Low"].values.astype(float).flatten()
            closes = data["Close"].values.astype(float).flatten()
            volumes = data["Volume"].values.astype(float).flatten()

            self._draw_candlestick(opens, highs, lows, closes, volumes)

            cur = closes[-1]
            prev = opens[0]
            change_pct = ((cur - prev) / prev * 100) if prev else 0
            hi = highs.max()
            lo = lows.min()
            vol = volumes[-1]
            color = "#00ff00" if change_pct >= 0 else "#ff0000"

            self._info_label.setText(
                f"O: ${opens[-1]:.2f} | H: ${hi:.2f} | L: ${lo:.2f} | "
                f"C: ${cur:.2f} | "
                f'<span style="color:{color};">{change_pct:+.1f}%</span> | '
                f"Vol: {vol:,.0f}"
            )
        except Exception as e:
            logger.warning("Chart load failed for %s: %s", ticker, e)
            self._info_label.setText(f"Chart error: {e}")

    def _draw_candlestick(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> None:
        """Render OHLC candlestick bars, SMA, and volume."""
        if not self._has_pyqtgraph:
            return

        import pyqtgraph as pg

        self._price_plot.clear()
        self._volume_plot.clear()

        n = len(closes)
        x = np.arange(n, dtype=np.float64)
        bar_width = 0.6

        green = (0, 200, 0)
        red = (200, 0, 0)

        # ── Candlestick wicks (high-low lines) ──────────────────────
        for i in range(n):
            colour = green if closes[i] >= opens[i] else red
            pen = pg.mkPen(color=colour, width=1)
            self._price_plot.plot(
                [float(i), float(i)],
                [float(lows[i]), float(highs[i])],
                pen=pen,
            )

        # ── Candlestick bodies (bar items) ───────────────────────────
        green_mask = closes >= opens
        red_mask = ~green_mask

        if green_mask.any():
            g_x = x[green_mask]
            g_bottom = opens[green_mask]
            g_height = closes[green_mask] - opens[green_mask]
            g_height = np.maximum(g_height, 0.01)
            green_bars = pg.BarGraphItem(
                x=g_x, y=g_bottom, height=g_height, width=bar_width,
                brush=pg.mkBrush(0, 180, 0, 200),
                pen=pg.mkPen(0, 200, 0),
            )
            self._price_plot.addItem(green_bars)

        if red_mask.any():
            r_x = x[red_mask]
            r_bottom = closes[red_mask]
            r_height = opens[red_mask] - closes[red_mask]
            r_height = np.maximum(r_height, 0.01)
            red_bars = pg.BarGraphItem(
                x=r_x, y=r_bottom, height=r_height, width=bar_width,
                brush=pg.mkBrush(180, 0, 0, 200),
                pen=pg.mkPen(200, 0, 0),
            )
            self._price_plot.addItem(red_bars)

        # ── 20-day SMA overlay ───────────────────────────────────────
        if n >= 20:
            import pandas as pd

            sma = pd.Series(closes).rolling(20).mean().values
            valid = ~np.isnan(sma)
            if valid.any():
                self._price_plot.plot(
                    x[valid], sma[valid],
                    pen=pg.mkPen(color="#ff8c00", width=2, style=pg.QtCore.Qt.DashLine),
                    name="SMA 20",
                )

        # ── Volume bars ──────────────────────────────────────────────
        if self._volume_plot is not None and len(volumes) > 0:
            vol_green_mask = closes >= opens
            vol_colours = [
                pg.mkBrush(0, 150, 0, 150) if vol_green_mask[i]
                else pg.mkBrush(150, 0, 0, 150)
                for i in range(n)
            ]
            for i in range(n):
                bar = pg.BarGraphItem(
                    x=[float(i)], height=[float(volumes[i])],
                    width=bar_width, brush=vol_colours[i],
                    pen=pg.mkPen(None),
                )
                self._volume_plot.addItem(bar)

        # ── Auto-fit to visible data range (no blank space) ──────
        self._price_plot.setXRange(0, n - 1, padding=0.02)
        self._price_plot.setYRange(float(lows.min()), float(highs.max()), padding=0.05)

    def selected_ticker(self) -> str:
        return self._current_ticker
