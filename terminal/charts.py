from __future__ import annotations

from typing import List
from terminal.state import AppState

try:
    from textual.app import ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Label, Sparkline
except ImportError:
    pass


class PriceChartView(Vertical):
    """ASCII-style sparkline chart for a selected ticker's price history."""

    DEFAULT_CSS = """
    PriceChartView {
        border: solid #444444;
        background: #000000;
        height: 100%;
        padding: 0 1;
    }
    PriceChartView Sparkline {
        height: 1fr;
    }
    """

    def __init__(self, state: AppState) -> None:
        super().__init__(id="chart-panel")
        self.state = state
        self._title_label = Label("CHART", classes="panel-title", id="chart-title")
        self._sparkline = Sparkline([], id="price-sparkline")
        self._info_label = Label("Select a ticker to view chart", id="chart-info")

    def compose(self) -> ComposeResult:
        yield self._title_label
        yield self._sparkline
        yield self._info_label

    def refresh_view(self) -> None:
        ticker = self.state.selected_ticker
        prices = self.state.chart_data

        if not ticker or not prices:
            self._title_label.update("CHART – No ticker selected")
            self._sparkline.data = [0]
            self._info_label.update("Press 'g' to view chart for selected ticker")
            return

        self._title_label.update(f"CHART – {ticker}")
        self._sparkline.data = prices

        # Summary info
        if len(prices) >= 2:
            first = prices[0]
            last = prices[-1]
            chg = ((last - first) / first) * 100 if first else 0
            chg_color = "#00ff00" if chg >= 0 else "#ff0000"
            sign = "+" if chg >= 0 else ""
            info = (
                f"Open: ${first:.2f}  |  "
                f"Current: ${last:.2f}  |  "
                f"Change: [{chg_color}]{sign}{chg:.1f}%[/]  |  "
                f"Points: {len(prices)}"
            )
        else:
            info = f"Points: {len(prices)}"

        self._info_label.update(info)
