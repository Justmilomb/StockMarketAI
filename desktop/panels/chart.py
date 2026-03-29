"""Chart panel — pyqtgraph price chart with dark theme."""
from __future__ import annotations
from typing import Any, List
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

class ChartPanel(QGroupBox):
    """Price chart using pyqtgraph (falls back to text if unavailable)."""

    def __init__(self, state: Any) -> None:
        super().__init__("CHART")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 16, 4, 4)

        self._title_label = QLabel("Select a ticker (G)")
        self._title_label.setStyleSheet("color: #ffb000; font-weight: bold;")
        layout.addWidget(self._title_label)

        self._plot_widget = None
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #888888; font-size: 11px;")

        try:
            import pyqtgraph as pg
            pg.setConfigOptions(background="#000000", foreground="#ffd700", antialias=True)
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
            self._plot_widget.getAxis("bottom").setPen("#444444")
            self._plot_widget.getAxis("left").setPen("#444444")
            layout.addWidget(self._plot_widget, 1)
        except ImportError:
            fallback = QLabel("pyqtgraph not installed — chart unavailable")
            fallback.setStyleSheet("color: #ff5555;")
            layout.addWidget(fallback, 1)

        layout.addWidget(self._info_label)
        self._current_ticker = ""

    def refresh_view(self, state: Any) -> None:
        """Update chart info label if data is loaded."""
        pass  # Chart updates via load_chart() only

    def load_chart(self, ticker: str) -> None:
        """Fetch 3-month data and render line chart."""
        self._current_ticker = ticker
        self._title_label.setText(f"CHART - {ticker}")

        try:
            import yfinance as yf
            data = yf.download(ticker, period="3mo", interval="1d", progress=False)
            if data.empty:
                self._info_label.setText("No data available")
                return

            closes = data["Close"].values.flatten().tolist()
            if not closes:
                return

            if self._plot_widget:
                self._plot_widget.clear()
                self._plot_widget.plot(
                    closes,
                    pen={"color": "#00bfff", "width": 2},
                )

            open_px = closes[0]
            cur_px = closes[-1]
            change_pct = ((cur_px - open_px) / open_px * 100) if open_px else 0
            color = "#00ff00" if change_pct >= 0 else "#ff0000"
            self._info_label.setText(
                f"Open: ${open_px:.2f} | Current: ${cur_px:.2f} | "
                f'<span style="color:{color};">Change: {change_pct:+.1f}%</span> | '
                f"Points: {len(closes)}"
            )
        except Exception as e:
            self._info_label.setText(f"Chart error: {e}")

    def selected_ticker(self) -> str:
        return self._current_ticker
