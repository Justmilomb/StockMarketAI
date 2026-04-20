"""Chart panel — candlestick + volume chart with pyqtgraph.

Rendered on the terminal-dark palette: white and green-accent hairlines,
no gridlines, a tracked-out mono title strip, a dashed SMA overlay, and
a thin crosshair that follows the mouse across both the price and
volume panes. A "PAPER" watermark is painted over the chart in paper
mode and is the *only* visual cue separating paper from live.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QFont, QPainter, QColor
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from desktop import tokens as T

logger = logging.getLogger(__name__)

_PERIODS = ["1y", "6mo", "3mo", "1mo"]


class ChartPanel(QGroupBox):
    """OHLC candlestick chart with volume bars, 20-day SMA, and crosshair."""

    def __init__(self, state: Any) -> None:
        super().__init__("CHART")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 18, 4, 4)
        layout.setSpacing(4)

        self._title_label = QLabel("SELECT A TICKER (G)")
        self._title_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px; padding: 2px 4px;"
        )
        layout.addWidget(self._title_label)

        self._price_plot = None
        self._volume_plot = None
        self._has_pyqtgraph = False
        self._price_vline = None
        self._price_hline = None
        self._volume_vline = None
        self._paper_mode = bool(getattr(state, "agent_paper_mode", True))
        self._chart_host = None
        self._info_label = QLabel("")
        self._info_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO}; font-size: 10px;"
            f" padding: 2px 4px;"
        )
        self._info_label.setTextFormat(Qt.RichText)

        try:
            import pyqtgraph as pg

            pg.setConfigOptions(background=T.BG_0, foreground=T.FG_1_HEX, antialias=True)

            axis_pen = pg.mkPen(T.BORDER_0_HEX, width=1)
            axis_text = {"color": T.FG_2_HEX, "font-size": "9pt"}

            self._price_plot = pg.PlotWidget()
            self._price_plot.showGrid(x=False, y=False)
            self._price_plot.setMouseEnabled(x=True, y=False)
            self._price_plot.setMenuEnabled(False)
            self._price_plot.hideButtons()
            for axis in ("bottom", "left"):
                ax = self._price_plot.getAxis(axis)
                ax.setPen(axis_pen)
                ax.setTextPen(pg.mkPen(T.FG_2_HEX))
                ax.setStyle(tickFont=QFont(T.FONT_MONO_FAMILY, 8))
            self._price_plot.setLabel("left", "PRICE", **axis_text)
            layout.addWidget(self._price_plot, 4)

            self._volume_plot = pg.PlotWidget()
            self._volume_plot.showGrid(x=False, y=False)
            self._volume_plot.setMouseEnabled(x=True, y=False)
            self._volume_plot.setMenuEnabled(False)
            self._volume_plot.hideButtons()
            for axis in ("bottom", "left"):
                ax = self._volume_plot.getAxis(axis)
                ax.setPen(axis_pen)
                ax.setTextPen(pg.mkPen(T.FG_2_HEX))
                ax.setStyle(tickFont=QFont(T.FONT_MONO_FAMILY, 8))
            self._volume_plot.setLabel("left", "VOL", **axis_text)
            layout.addWidget(self._volume_plot, 1)

            self._volume_plot.setXLink(self._price_plot)

            cross_pen = pg.mkPen(color=T.FG_2_HEX, style=Qt.DashLine, width=1)
            self._price_vline = pg.InfiniteLine(angle=90, movable=False, pen=cross_pen)
            self._price_hline = pg.InfiniteLine(angle=0, movable=False, pen=cross_pen)
            self._volume_vline = pg.InfiniteLine(angle=90, movable=False, pen=cross_pen)
            self._price_plot.addItem(self._price_vline, ignoreBounds=True)
            self._price_plot.addItem(self._price_hline, ignoreBounds=True)
            self._volume_plot.addItem(self._volume_vline, ignoreBounds=True)
            for ln in (self._price_vline, self._price_hline, self._volume_vline):
                ln.setVisible(False)

            self._price_plot.scene().sigMouseMoved.connect(self._on_price_mouse)
            self._volume_plot.scene().sigMouseMoved.connect(self._on_volume_mouse)

            self._chart_host = self._price_plot
            self._has_pyqtgraph = True
        except Exception as exc:
            logger.warning("pyqtgraph chart init failed: %s", exc)
            fallback = QLabel(f"Chart unavailable — {type(exc).__name__}: {exc}")
            fallback.setStyleSheet(f"color: {T.ALERT}; font-size: 11px;")
            layout.addWidget(fallback, 1)

        layout.addWidget(self._info_label)
        self._current_ticker = ""

        self._paper_watermark: _PaperWatermark | None = None
        if self._price_plot is not None:
            self._paper_watermark = _PaperWatermark(self._price_plot.viewport())
            self._paper_watermark.setVisible(self._paper_mode)

        # Debounce resize: suppress pyqtgraph repaints during rapid resize
        # drag; re-enable once the user pauses for 120 ms.
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(120)
        self._resize_debounce.timeout.connect(self._on_resize_settled)

    def _on_price_mouse(self, pos: Any) -> None:
        if not self._has_pyqtgraph or self._price_plot is None:
            return
        vb = self._price_plot.plotItem.vb
        if not self._price_plot.plotItem.sceneBoundingRect().contains(pos):
            for ln in (self._price_vline, self._price_hline, self._volume_vline):
                if ln is not None:
                    ln.setVisible(False)
            return
        p = vb.mapSceneToView(pos)
        for ln in (self._price_vline, self._price_hline, self._volume_vline):
            if ln is not None:
                ln.setVisible(True)
        self._price_vline.setPos(p.x())
        self._price_hline.setPos(p.y())
        self._volume_vline.setPos(p.x())

    def _on_volume_mouse(self, pos: Any) -> None:
        if not self._has_pyqtgraph or self._volume_plot is None:
            return
        vb = self._volume_plot.plotItem.vb
        if not self._volume_plot.plotItem.sceneBoundingRect().contains(pos):
            return
        p = vb.mapSceneToView(pos)
        for ln in (self._price_vline, self._volume_vline):
            if ln is not None:
                ln.setVisible(True)
        self._price_vline.setPos(p.x())
        self._volume_vline.setPos(p.x())

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self._has_pyqtgraph:
            if self._price_plot is not None:
                self._price_plot.setUpdatesEnabled(False)
            if self._volume_plot is not None:
                self._volume_plot.setUpdatesEnabled(False)
            self._resize_debounce.start()

    def _on_resize_settled(self) -> None:
        if self._price_plot is not None:
            self._price_plot.setUpdatesEnabled(True)
        if self._volume_plot is not None:
            self._volume_plot.setUpdatesEnabled(True)

    def refresh_view(self, state: Any) -> None:
        paper = bool(getattr(state, "agent_paper_mode", True))
        if paper != self._paper_mode:
            self._paper_mode = paper
            if self._paper_watermark is not None:
                self._paper_watermark.setVisible(paper)

    def clear(self) -> None:
        """Reset to blank state — no ticker, empty plots."""
        self._current_ticker = ""
        self._title_label.setText("CHART")
        self._info_label.setText("")
        if self._has_pyqtgraph:
            import numpy as np
            self._draw_candlestick(
                np.array([]), np.array([]), np.array([]), np.array([]), np.array([])
            )

    def load_chart(self, ticker: str) -> None:
        self._current_ticker = ticker
        self._title_label.setText(f"CHART · {ticker.upper()}")
        self._info_label.setText("Loading…")

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

            if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
                data.columns = data.columns.droplevel(1)

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
            chg_colour = T.ACCENT_HEX if change_pct >= 0 else T.ALERT

            dim = T.FG_2_HEX
            val = T.FG_1_HEX
            self._info_label.setText(
                f'<span style="color:{dim};">O</span> '
                f'<span style="color:{val};">${opens[-1]:.2f}</span>  '
                f'<span style="color:{dim};">H</span> '
                f'<span style="color:{val};">${hi:.2f}</span>  '
                f'<span style="color:{dim};">L</span> '
                f'<span style="color:{val};">${lo:.2f}</span>  '
                f'<span style="color:{dim};">C</span> '
                f'<span style="color:{T.FG_0};">${cur:.2f}</span>  '
                f'<span style="color:{chg_colour};">{change_pct:+.2f}%</span>  '
                f'<span style="color:{dim};">VOL</span> '
                f'<span style="color:{val};">{vol:,.0f}</span>'
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
        if not self._has_pyqtgraph:
            return

        import pyqtgraph as pg

        # Clear everything except the crosshair lines we manage ourselves.
        for plot, lines in (
            (self._price_plot, (self._price_vline, self._price_hline)),
            (self._volume_plot, (self._volume_vline,)),
        ):
            plot.clear()
            for ln in lines:
                if ln is not None:
                    plot.addItem(ln, ignoreBounds=True)

        n = len(closes)
        x = np.arange(n, dtype=np.float64)
        bar_width = 0.6

        green_body = pg.mkBrush(0, 255, 135, 230)
        green_edge = pg.mkPen(0, 255, 135)
        red_body = pg.mkBrush(255, 59, 59, 230)
        red_edge = pg.mkPen(255, 59, 59)

        green_mask = closes >= opens
        red_mask = ~green_mask

        # Draw all wicks as two bulk plots (NaN separators break lines
        # between candles) — replaces O(n) individual plot() calls.
        for mask, pen in ((green_mask, green_edge), (red_mask, red_edge)):
            idx = np.where(mask)[0]
            if idx.size:
                xs = np.empty(idx.size * 3)
                ys = np.empty(idx.size * 3)
                xs[0::3] = x[idx]
                xs[1::3] = x[idx]
                xs[2::3] = np.nan
                ys[0::3] = lows[idx]
                ys[1::3] = highs[idx]
                ys[2::3] = np.nan
                self._price_plot.plot(xs, ys, pen=pen, connect="finite")

        if green_mask.any():
            self._price_plot.addItem(pg.BarGraphItem(
                x=x[green_mask], y=opens[green_mask],
                height=np.maximum(closes[green_mask] - opens[green_mask], 0.01),
                width=bar_width, brush=green_body, pen=green_edge,
            ))

        if red_mask.any():
            self._price_plot.addItem(pg.BarGraphItem(
                x=x[red_mask], y=closes[red_mask],
                height=np.maximum(opens[red_mask] - closes[red_mask], 0.01),
                width=bar_width, brush=red_body, pen=red_edge,
            ))

        if n >= 20:
            import pandas as pd

            sma = pd.Series(closes).rolling(20).mean().values
            valid = ~np.isnan(sma)
            if valid.any():
                self._price_plot.plot(
                    x[valid], sma[valid],
                    pen=pg.mkPen(
                        color=T.FG_1_HEX, width=1,
                        style=Qt.DashLine,
                    ),
                    name="SMA 20",
                )

        if self._volume_plot is not None and len(volumes) > 0:
            vol_green = pg.mkBrush(0, 255, 135, 110)
            vol_red = pg.mkBrush(255, 59, 59, 110)
            v_green = np.where(green_mask)[0]
            v_red = np.where(red_mask)[0]
            if v_green.size:
                self._volume_plot.addItem(pg.BarGraphItem(
                    x=x[v_green], height=volumes[v_green],
                    width=bar_width, brush=vol_green, pen=pg.mkPen(None),
                ))
            if v_red.size:
                self._volume_plot.addItem(pg.BarGraphItem(
                    x=x[v_red], height=volumes[v_red],
                    width=bar_width, brush=vol_red, pen=pg.mkPen(None),
                ))

        self._price_plot.setXRange(0, n - 1, padding=0.02)
        self._price_plot.setYRange(float(lows.min()), float(highs.max()), padding=0.05)

    def selected_ticker(self) -> str:
        return self._current_ticker


class _PaperWatermark(QWidget):
    """Diagonal 'PAPER MODE' overlay floated over the price plot.

    The *only* visual difference between paper and live modes anywhere
    in the app. Live mode hides this widget; paper mode paints the
    word large, rotated 30°, at very low opacity so it's unmistakable
    without being loud.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, event: Any) -> None:
        if not self.isVisible():
            return
        rect = self.rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        font = QFont(T.FONT_MONO_FAMILY)
        font.setPixelSize(max(48, int(rect.height() * 0.22)))
        font.setWeight(QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 8.0)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 18))
        painter.translate(rect.center())
        painter.rotate(-30)
        painter.drawText(
            -rect.width(), -rect.height() // 2,
            rect.width() * 2, rect.height(),
            Qt.AlignCenter, "PAPER MODE",
        )
