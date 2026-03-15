from __future__ import annotations

from typing import Any, Dict, List

from terminal.state import AppState

try:
    from textual.app import ComposeResult
    from textual.containers import Vertical, Horizontal, VerticalScroll
    from textual.widgets import DataTable, Label, Button, TabbedContent, TabPane
    from textual.screen import ModalScreen
except ImportError:  # pragma: no cover
    pass


# ═══════════════════════════════════════════════════════════════════════
#  HISTORY MODAL — Order History + Dividends + Transactions
# ═══════════════════════════════════════════════════════════════════════

class HistoryModal(ModalScreen):
    """Tabbed modal showing order history, dividends, and transactions."""

    DEFAULT_CSS = """
    HistoryModal {
        align: center middle;
    }
    #history-dialog {
        width: 90;
        height: 30;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    #history-dialog DataTable {
        height: 1fr;
    }
    #history-dialog TabbedContent {
        height: 1fr;
    }
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._orders_table = DataTable(cursor_type="row", id="hist-orders")
        self._dividends_table = DataTable(cursor_type="row", id="hist-dividends")
        self._transactions_table = DataTable(cursor_type="row", id="hist-transactions")

    def compose(self) -> ComposeResult:
        with Vertical(id="history-dialog"):
            yield Label("[#ffb000]ACCOUNT HISTORY[/]", classes="panel-title")

            if not self.state.broker_is_live:
                yield Label(
                    "[#ff5555]Not connected to Trading 212. "
                    "Configure API key in config.json to view history.[/]"
                )

            with TabbedContent("Orders", "Dividends", "Transactions"):
                with TabPane("Orders"):
                    yield self._orders_table
                with TabPane("Dividends"):
                    yield self._dividends_table
                with TabPane("Transactions"):
                    yield self._transactions_table

            with Horizontal():
                yield Button("Refresh", variant="primary", id="btn-hist-refresh")
                yield Button("Close", variant="error", id="btn-hist-close")

    def on_mount(self) -> None:
        self._orders_table.add_columns("Date", "Ticker", "Side", "Qty", "Fill Px", "Cost", "Status")
        self._dividends_table.add_columns("Date", "Ticker", "Amount", "Qty", "Per Share")
        self._transactions_table.add_columns("Date", "Type", "Amount", "Currency", "Status")
        self._populate_tables()

    def _populate_tables(self) -> None:
        # Order history
        self._orders_table.clear()
        for o in self.state.order_history[:50]:
            date = str(o.get("date", ""))[:10]
            side = o.get("side", "")
            side_str = f"[#00ff00]{side}[/]" if side == "BUY" else f"[#ff0000]{side}[/]"
            self._orders_table.add_row(
                date,
                o.get("ticker", ""),
                side_str,
                str(o.get("quantity", "")),
                f"${o.get('fill_price', 0):.2f}",
                f"${abs(o.get('fill_cost', 0)):.2f}",
                o.get("status", ""),
            )
        if not self.state.order_history:
            self._orders_table.add_row("-", "No order history", "-", "-", "-", "-", "-")

        # Dividends
        self._dividends_table.clear()
        for d in self.state.dividend_history[:50]:
            date = str(d.get("paid_on", ""))[:10]
            self._dividends_table.add_row(
                date,
                d.get("ticker", ""),
                f"[#00ff00]${d.get('amount', 0):.2f}[/]",
                str(d.get("quantity", "")),
                f"${d.get('gross_per_share', 0):.4f}",
            )
        if not self.state.dividend_history:
            self._dividends_table.add_row("-", "No dividends", "-", "-", "-")

        # Transactions
        self._transactions_table.clear()
        for t in self.state.transaction_history[:50]:
            date = str(t.get("date", ""))[:10]
            amount = t.get("amount", 0)
            amount_color = "#00ff00" if amount >= 0 else "#ff0000"
            self._transactions_table.add_row(
                date,
                t.get("type", ""),
                f"[{amount_color}]${amount:.2f}[/]",
                t.get("currency", ""),
                t.get("status", ""),
            )
        if not self.state.transaction_history:
            self._transactions_table.add_row("-", "No transactions", "-", "-", "-")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-hist-refresh":
            self.app.load_history_data(callback=self._on_refresh)
        else:
            self.dismiss(None)

    def _on_refresh(self) -> None:
        self._populate_tables()


# ═══════════════════════════════════════════════════════════════════════
#  PIES MODAL — View and manage investment pies
# ═══════════════════════════════════════════════════════════════════════

class PiesModal(ModalScreen):
    """Modal showing Trading 212 investment pies."""

    DEFAULT_CSS = """
    PiesModal {
        align: center middle;
    }
    #pies-dialog {
        width: 85;
        height: 28;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    #pies-dialog DataTable {
        height: 1fr;
    }
    #pie-detail {
        height: 1fr;
        border-top: solid #333333;
        margin-top: 1;
        padding-top: 1;
    }
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._pies_table = DataTable(cursor_type="row", id="pies-table")
        self._detail_label = Label("Select a pie to view details", id="pie-detail-text")
        self._detail_table = DataTable(cursor_type="row", id="pie-instruments")

    def compose(self) -> ComposeResult:
        with Vertical(id="pies-dialog"):
            yield Label("[#ffb000]INVESTMENT PIES[/]", classes="panel-title")

            if not self.state.broker_is_live:
                yield Label(
                    "[#ff5555]Not connected to Trading 212. "
                    "Configure API key in config.json to manage pies.[/]"
                )

            yield self._pies_table

            with VerticalScroll(id="pie-detail"):
                yield self._detail_label
                yield self._detail_table

            with Horizontal():
                yield Button("View Detail", variant="primary", id="btn-pie-detail")
                yield Button("Refresh", variant="warning", id="btn-pie-refresh")
                yield Button("Close", variant="error", id="btn-pie-close")

    def on_mount(self) -> None:
        self._pies_table.add_columns("Name", "Invested", "Value", "Return %", "Cash", "Status")
        self._detail_table.add_columns("Ticker", "Target %", "Current %", "Qty", "Value")
        self._populate_pies()

    def _populate_pies(self) -> None:
        self._pies_table.clear()
        for p in self.state.pies:
            invested = p.get("invested", 0.0)
            value = p.get("value", 0.0)
            coef = p.get("result_coef", 1.0)
            ret_pct = (coef - 1.0) * 100.0

            if ret_pct > 0:
                ret_str = f"[#00ff00]+{ret_pct:.1f}%[/]"
            elif ret_pct < 0:
                ret_str = f"[#ff0000]{ret_pct:.1f}%[/]"
            else:
                ret_str = "0.0%"

            self._pies_table.add_row(
                p.get("name", "Unnamed"),
                f"${invested:.2f}",
                f"${value:.2f}",
                ret_str,
                f"${p.get('cash', 0):.2f}",
                p.get("status", ""),
            )
        if not self.state.pies:
            self._pies_table.add_row("No pies", "-", "-", "-", "-", "-")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-pie-detail":
            self._load_pie_detail()
        elif event.button.id == "btn-pie-refresh":
            self.app.load_pies_data(callback=self._on_refresh)
        else:
            self.dismiss(None)

    def _load_pie_detail(self) -> None:
        try:
            row_idx = self._pies_table.cursor_row
            if row_idx is not None and row_idx < len(self.state.pies):
                pie_id = self.state.pies[row_idx].get("id", 0)
                if pie_id:
                    self.app.load_pie_detail(pie_id, callback=self._on_detail)
        except Exception:
            pass

    def _on_detail(self, detail: Dict[str, Any]) -> None:
        self._detail_table.clear()
        name = detail.get("name", "")
        self._detail_label.update(
            f"[#ffb000]{name}[/] | "
            f"Invested: ${detail.get('invested', 0):.2f} | "
            f"Value: ${detail.get('value', 0):.2f} | "
            f"Cash: ${detail.get('cash', 0):.2f}"
        )
        for inst in detail.get("instruments", []):
            target = inst.get("expected_share", 0) * 100
            current = inst.get("current_share", 0) * 100
            self._detail_table.add_row(
                inst.get("ticker", ""),
                f"{target:.1f}%",
                f"{current:.1f}%",
                f"{inst.get('owned_quantity', 0):.4f}",
                f"${inst.get('value', 0):.2f}",
            )
        if not detail.get("instruments"):
            self._detail_table.add_row("No instruments", "-", "-", "-", "-")

    def _on_refresh(self) -> None:
        self._populate_pies()


# ═══════════════════════════════════════════════════════════════════════
#  INSTRUMENTS MODAL — Browse available instruments
# ═══════════════════════════════════════════════════════════════════════

class InstrumentsModal(ModalScreen):
    """Modal for browsing tradeable instruments and exchange metadata."""

    DEFAULT_CSS = """
    InstrumentsModal {
        align: center middle;
    }
    #instruments-dialog {
        width: 90;
        height: 28;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    #instruments-dialog DataTable {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._table = DataTable(cursor_type="row", id="instruments-table")
        self._status = Label("Loading instruments...", id="inst-status")
        self._instruments: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        from textual.widgets import Input
        with Vertical(id="instruments-dialog"):
            yield Label("[#ffb000]INSTRUMENT BROWSER[/]", classes="panel-title")
            yield Input(placeholder="Filter by ticker or name...", id="inst-filter")
            yield self._status
            yield self._table
            with Horizontal():
                yield Button("Add to Watchlist", variant="success", id="btn-inst-add")
                yield Button("Close", variant="error", id="btn-inst-close")

    def on_mount(self) -> None:
        self._table.add_columns("Ticker", "Name", "Exchange", "Type", "Currency", "Min Qty")
        self.app.load_instruments(callback=self._on_loaded)

    def _on_loaded(self, instruments: List[Dict[str, Any]]) -> None:
        self._instruments = instruments
        self._status.update(f"[#00ff00]{len(instruments)} instruments available[/]")
        self._filter_and_display("")

    def _filter_and_display(self, query: str) -> None:
        self._table.clear()
        query_lower = query.lower()
        shown = 0
        for inst in self._instruments:
            if shown >= 100:
                break
            ticker = inst.get("ticker", "")
            name = inst.get("name", "")
            if query_lower and query_lower not in ticker.lower() and query_lower not in name.lower():
                continue
            self._table.add_row(
                ticker,
                name[:40],
                inst.get("exchange", ""),
                inst.get("type", ""),
                inst.get("currency", ""),
                str(inst.get("min_trade_qty", "")),
            )
            shown += 1

    def on_input_changed(self, event) -> None:
        from textual.widgets import Input
        if hasattr(event, 'input') and event.input.id == "inst-filter":
            self._filter_and_display(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-inst-add":
            try:
                row_idx = self._table.cursor_row
                row_data = self._table.get_row_at(row_idx)
                if row_data:
                    self.dismiss(str(row_data[0]))
                    return
            except Exception:
                pass
            self.dismiss(None)
        else:
            self.dismiss(None)
