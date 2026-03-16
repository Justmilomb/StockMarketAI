from __future__ import annotations

from typing import Any, List

from terminal.state import AppState

try:
    from textual.app import ComposeResult
    from textual.containers import Vertical, Horizontal, VerticalScroll
    from textual.widgets import DataTable, Static, Label, Input, Button, Select
    from textual.screen import ModalScreen
except ImportError:  # pragma: no cover
    pass


class Panel(Vertical):
    """A bordered container for a section."""
    DEFAULT_CSS = """
    Panel {
        border: solid #444444;
        background: #000000;
        height: 100%;
        padding: 0 1;
    }
    """
    def __init__(self, title: str, *children, id: str | None = None) -> None:
        super().__init__(*children, id=id)
        self.panel_title = title


# ═══════════════════════════════════════════════════════════════════════
#  WATCHLIST VIEW
# ═══════════════════════════════════════════════════════════════════════

class WatchlistView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("WATCHLIST [Signals]", id="watchlist-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        title = f"WATCHLIST [{self.state.active_watchlist}]" if self.state.active_watchlist else "WATCHLIST"
        yield Label(title, classes="panel-title", id="watchlist-title")
        yield self.table

    def on_mount(self) -> None:
        self.table.add_columns("Ticker", "Live Px", "Day %", "Prob", "Signal", "AI Rec", "Sentiment")
        self.refresh_view()

    def refresh_view(self) -> None:
        title = f"WATCHLIST [{self.state.active_watchlist}]" if self.state.active_watchlist else "WATCHLIST"
        try:
            self.query_one("#watchlist-title", Label).update(title)
        except Exception:
            pass

        self.table.clear()
        if self.state.signals is not None:
            # Extract held tickers for highlighting
            held_tickers = {p.get("ticker"): p for p in self.state.positions}

            for _, row in self.state.signals.head(30).iterrows():
                ticker = row['ticker']
                prob = f"{row['prob_up']:.2f}"
                signal = row['signal']
                
                # Is held?
                is_held = ticker in held_tickers
                ticker_display = f"[reverse #00ffff]{ticker}*[/]" if is_held else ticker

                # Live Data
                live_info = self.state.live_data.get(ticker, {})
                live_px = live_info.get("price", 0.0)
                day_pct = live_info.get("change_pct", 0.0)

                live_px_str = f"${live_px:.2f}" if live_px > 0 else "-"

                if day_pct > 0:
                    day_pct_str = f"[#00ff00]+{day_pct:.1f}%[/]"
                elif day_pct < 0:
                    day_pct_str = f"[#ff0000]{day_pct:.1f}%[/]"
                else:
                    day_pct_str = "-"

                # Signal color
                if signal.lower() == "buy":
                    signal_str = f"[#00ff00]{signal}[/]"
                elif signal.lower() == "sell":
                    signal_str = f"[#ff0000]{signal}[/]"
                else:
                    signal_str = f"[#ffb000]{signal}[/]"

                # AI Recommendation
                ai_rec = row.get("ai_rec", "")
                if ai_rec == "BUY":
                    ai_rec_str = "[#00ff00]BUY[/]"
                elif ai_rec == "SELL":
                    ai_rec_str = "[#ff0000]SELL[/]"
                elif ai_rec == "HOLD":
                    ai_rec_str = "[#ffb000]HOLD[/]"
                else:
                    ai_rec_str = "-"

                # News Sentiment
                news = self.state.news_sentiment.get(ticker)
                if news:
                    sent = news.sentiment if hasattr(news, 'sentiment') else news.get('sentiment', 0)
                    if sent > 0.2:
                        sent_str = f"[#00ff00]{sent:+.1f}[/]"
                    elif sent < -0.2:
                        sent_str = f"[#ff0000]{sent:+.1f}[/]"
                    else:
                        sent_str = f"[#ffb000]{sent:+.1f}[/]"
                else:
                    sent_str = "-"

                self.table.add_row(ticker_display, live_px_str, day_pct_str, prob, signal_str, ai_rec_str, sent_str)


# ═══════════════════════════════════════════════════════════════════════
#  POSITIONS VIEW
# ═══════════════════════════════════════════════════════════════════════

class PositionsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("POSITIONS", id="positions-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.table

    def on_mount(self) -> None:
        self.table.add_columns("Ticker", "Qty", "Avg Px", "Cur Px", "PnL")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.table.clear()
        if not self.state.positions:
            self.table.add_row("No Positions", "-", "-", "-", "-")
            return

        for p in self.state.positions:
            ticker = p.get("ticker", "")
            qty = f"{p.get('quantity', 0):.2f}"
            avg = f"${p.get('avg_price', 0.0):.2f}"
            cur = f"${p.get('current_price', 0.0):.2f}"
            pnl = p.get("unrealised_pnl", 0.0)
            pnl_color = "[#00ff00]" if pnl >= 0 else "[#ff0000]"
            pnl_str = f"{pnl_color}${pnl:.2f}[/]"

            # Highlighting ticker in cyan
            ticker_str = f"[#00ffff]{ticker}[/]"
            self.table.add_row(ticker_str, qty, avg, cur, pnl_str)


# ═══════════════════════════════════════════════════════════════════════
#  ORDERS VIEW
# ═══════════════════════════════════════════════════════════════════════

class OrdersView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("ORDERS", id="orders-panel")
        self.state = state
        self.table = DataTable(cursor_type="row")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.table

    def on_mount(self) -> None:
        self.table.add_columns("Ticker", "Side", "Qty", "Type", "Status")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.table.clear()
        if self.state.recent_orders:
            for order in self.state.recent_orders[-20:]:
                ticker = order.get('ticker', 'N/A')
                side = order.get('side', 'N/A')
                qty = order.get('quantity', 0)
                otype = order.get('order_type', 'market')
                status = order.get('status', 'FILLED')

                if side.upper() == 'BUY':
                    side_str = f"[#00ff00]BUY[/]"
                elif side.upper() == 'SELL':
                    side_str = f"[#ff0000]SELL[/]"
                else:
                    side_str = side

                self.table.add_row(ticker, side_str, str(qty), otype, status)
        else:
            self.table.add_row("No Orders", "-", "-", "-", "-")


# ═══════════════════════════════════════════════════════════════════════
#  METRICS / SETTINGS VIEW
# ═══════════════════════════════════════════════════════════════════════

class SettingsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("TERMINAL METRICS", id="settings-panel")
        self.state = state
        self.metrics_label = Label()

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.metrics_label

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        mode_color = "[#00ff00]" if self.state.mode == "full_auto_limited" else "[#ffb000]"
        upnl = self.state.unrealised_pnl
        upnl_color = "[#00ff00]" if upnl >= 0 else "[#ff0000]"

        acct = self.state.account_info
        balance = acct.get("free", self.state.capital)
        invested = acct.get("invested", 0.0)
        total = acct.get("total", self.state.capital)

        lines = [
            f"Mode:       {mode_color}{self.state.mode}[/]",
            f"Balance:    [#ffffff]${balance:,.2f}[/]",
            f"Invested:   [#ffffff]${invested:,.2f}[/]",
            f"Total:      [#ffffff]${total:,.2f}[/]",
            f"Unrlzd PnL: {upnl_color}${upnl:,.2f}[/]",
            f"Max Loss:   [#ffffff]{self.state.max_daily_loss * 100:.1f}%[/]",
        ]
        self.metrics_label.update("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════
#  AI INSIGHTS VIEW
# ═══════════════════════════════════════════════════════════════════════

class AiInsightsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("AI INSIGHTS", id="ai-insights-panel")
        self.state = state
        self.insights_label = Label(self.state.ai_insights)

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield self.insights_label

    def refresh_view(self) -> None:
        self.insights_label.update(self.state.ai_insights)


# ═══════════════════════════════════════════════════════════════════════
#  NEWS SENTIMENT VIEW
# ═══════════════════════════════════════════════════════════════════════

class NewsView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("NEWS SENTIMENT", id="news-panel")
        self.state = state
        self.news_label = Label("Fetching news...")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield VerticalScroll(self.news_label, id="news-scroll")

    def refresh_view(self) -> None:
        if not self.state.news_sentiment:
            self.news_label.update("No news data yet. Agent running in background...")
            return

        lines = []
        for ticker, nd in self.state.news_sentiment.items():
            if hasattr(nd, 'sentiment'):
                sent = nd.sentiment
                summary = nd.summary
                headlines = nd.headlines[:3]
            elif isinstance(nd, dict):
                sent = nd.get('sentiment', 0)
                summary = nd.get('summary', '')
                headlines = nd.get('headlines', [])[:3]
            else:
                continue

            if sent > 0.2:
                color = "#00ff00"
            elif sent < -0.2:
                color = "#ff0000"
            else:
                color = "#ffb000"

            lines.append(f"[{color}]■[/] {ticker} ({sent:+.2f}): {summary}")
            for h in headlines:
                lines.append(f"  • {h[:60]}")
            lines.append("")

        self.news_label.update("\n".join(lines) if lines else "No news data.")


# ═══════════════════════════════════════════════════════════════════════
#  CHAT VIEW
# ═══════════════════════════════════════════════════════════════════════

class ChatView(Panel):
    def __init__(self, state: AppState) -> None:
        super().__init__("AI ASSISTANT", id="chat-panel")
        self.state = state
        self.messages_label = Label("Type a message and press Enter to chat with AI.\n", id="chat-messages")
        self.chat_input = Input(placeholder="Ask AI anything...", id="chat-input")

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="panel-title")
        yield VerticalScroll(self.messages_label, id="chat-scroll")
        yield self.chat_input

    def refresh_view(self) -> None:
        lines = []
        for msg in self.state.chat_history[-20:]:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            if role == "user":
                lines.append(f"[#00bfff]You:[/] {text}")
            else:
                lines.append(f"[#ffb000]AI:[/] {text}")
            lines.append("")
        if lines:
            self.messages_label.update("\n".join(lines))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input" and event.value.strip():
            # Dispatch to app
            self.app.handle_chat_message(event.value.strip())
            event.input.value = ""


# ═══════════════════════════════════════════════════════════════════════
#  ADD TICKER MODAL
# ═══════════════════════════════════════════════════════════════════════

class AddTickerModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]
    DEFAULT_CSS = """
    AddTickerModal {
        align: center middle;
    }
    #add-ticker-dialog {
        width: 50;
        height: 14;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="add-ticker-dialog"):
            yield Label("[#ffb000]ADD TICKER[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to cancel)[/]")
            yield Input(placeholder="Enter ticker symbol (e.g., NVDA)", id="ticker-input")
            with Horizontal():
                yield Button("Add", variant="success", id="btn-add")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            inp = self.query_one("#ticker-input", Input)
            ticker = inp.value.strip().upper()
            if ticker:
                self.dismiss(ticker)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  TRADE MODAL
# ═══════════════════════════════════════════════════════════════════════

class TradeModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Cancel")]
    DEFAULT_CSS = """
    TradeModal {
        align: center middle;
    }
    #trade-dialog {
        width: 55;
        height: 24;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    .trade-row {
        height: 3;
        margin-bottom: 1;
    }
    """
    def __init__(self, ticker: str = "") -> None:
        super().__init__()
        self._ticker = ticker

    def compose(self) -> ComposeResult:
        with Vertical(id="trade-dialog"):
            yield Label(f"[#ffb000]TRADE – {self._ticker}[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to cancel)[/]")

            # Side
            yield Label("Side:")
            yield Select(
                [("BUY", "BUY"), ("SELL", "SELL")],
                value="BUY",
                id="trade-side",
            )

            # Quantity
            yield Label("Quantity:")
            yield Input(placeholder="1.0", id="trade-qty", type="number")

            # Order type
            yield Label("Order Type:")
            yield Select(
                [("Market", "market"), ("Limit", "limit"), ("Stop", "stop")],
                value="market",
                id="trade-type",
            )

            # Limit / Stop price
            yield Label("Price (for limit/stop):")
            yield Input(placeholder="Leave empty for market", id="trade-price", type="number")

            with Horizontal():
                yield Button("Submit Order", variant="success", id="btn-submit-trade")
                yield Button("Cancel", variant="error", id="btn-cancel-trade")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-trade":
            side = self.query_one("#trade-side", Select).value
            qty_raw = self.query_one("#trade-qty", Input).value.strip()
            otype = self.query_one("#trade-type", Select).value
            price_raw = self.query_one("#trade-price", Input).value.strip()

            try:
                qty = float(qty_raw) if qty_raw else 1.0
            except ValueError:
                qty = 1.0

            price = None
            try:
                if price_raw:
                    price = float(price_raw)
            except ValueError:
                pass

            self.dismiss({
                "ticker": self._ticker,
                "side": side,
                "quantity": qty,
                "order_type": otype,
                "price": price,
            })
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  SEARCH TICKER MODAL
# ═══════════════════════════════════════════════════════════════════════

class SearchTickerModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Close")]
    DEFAULT_CSS = """
    SearchTickerModal {
        align: center middle;
    }
    #search-dialog {
        width: 70;
        height: 22;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label("[#ffb000]SEARCH TICKERS[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to close)[/]")
            yield Label("Search by name, sector, or theme (e.g. 'AI companies', 'semiconductors')")
            yield Input(placeholder="Type to search...", id="search-input")
            yield Label("", id="search-status")
            self._results_table = DataTable(cursor_type="row", id="search-results")
            yield self._results_table
            with Horizontal():
                yield Button("Add Selected", variant="success", id="btn-search-add")
                yield Button("Close", variant="error", id="btn-search-close")

    def on_mount(self) -> None:
        self._results_table.add_columns("Ticker", "Company", "Sector")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input" and event.value.strip():
            query = event.value.strip()
            self.query_one("#search-status", Label).update("[#ffb000]Searching...[/]")
            self.app.search_tickers_for_modal(query, self._on_results)

    def _on_results(self, results: list) -> None:
        self._results_table.clear()
        if results:
            for r in results:
                self._results_table.add_row(
                    r.get("ticker", ""),
                    r.get("name", ""),
                    r.get("sector", ""),
                )
            self.query_one("#search-status", Label).update(
                f"[#00ff00]Found {len(results)} results.[/]"
            )
        else:
            self.query_one("#search-status", Label).update(
                "[#ff0000]No results found.[/]"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search-add":
            try:
                row_idx = self._results_table.cursor_row
                row_data = self._results_table.get_row_at(row_idx)
                if row_data:
                    self.dismiss(str(row_data[0]))
                    return
            except Exception:
                pass
            self.dismiss(None)
        else:
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════
#  AI RECOMMEND TICKERS MODAL
# ═══════════════════════════════════════════════════════════════════════

class AiRecommendModal(ModalScreen):
    BINDINGS = [("escape", "dismiss_modal", "Close")]
    DEFAULT_CSS = """
    AiRecommendModal {
        align: center middle;
    }
    #recommend-dialog {
        width: 75;
        height: 22;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="recommend-dialog"):
            yield Label("[#ffb000]AI TICKER RECOMMENDATIONS[/]", classes="panel-title")
            yield Label("[#666666](Press Esc to close)[/]")
            yield Label("Optional: specify a category (e.g. 'AI', 'biotech', 'dividends'):")
            yield Input(placeholder="Leave blank for general recommendations", id="rec-category")
            yield Button("Get Recommendations", variant="primary", id="btn-get-recs")
            yield Label("", id="rec-status")
            self._rec_table = DataTable(cursor_type="row", id="rec-results")
            yield self._rec_table
            with Horizontal():
                yield Button("Add Selected", variant="success", id="btn-rec-add")
                yield Button("Add All", variant="warning", id="btn-rec-add-all")
                yield Button("Close", variant="error", id="btn-rec-close")

    def on_mount(self) -> None:
        self._rec_table.add_columns("Ticker", "Reason")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-get-recs":
            category = self.query_one("#rec-category", Input).value.strip()
            self.query_one("#rec-status", Label).update("[#ffb000]AI is thinking...[/]")
            self.app.get_ai_recommendations(category, self._on_results)

        elif event.button.id == "btn-rec-add":
            try:
                row_idx = self._rec_table.cursor_row
                row_data = self._rec_table.get_row_at(row_idx)
                if row_data:
                    self.dismiss({"mode": "single", "ticker": str(row_data[0])})
                    return
            except Exception:
                pass
            self.dismiss(None)

        elif event.button.id == "btn-rec-add-all":
            tickers = []
            for i in range(self._rec_table.row_count):
                try:
                    row = self._rec_table.get_row_at(i)
                    if row:
                        tickers.append(str(row[0]))
                except Exception:
                    pass
            if tickers:
                self.dismiss({"mode": "all", "tickers": tickers})
            else:
                self.dismiss(None)

        elif event.button.id == "btn-rec-close":
            self.dismiss(None)

    def _on_results(self, results: list) -> None:
        self._rec_table.clear()
        if results:
            for r in results:
                self._rec_table.add_row(
                    r.get("ticker", ""),
                    r.get("reason", ""),
                )
            self.query_one("#rec-status", Label).update(
                f"[#00ff00]AI recommended {len(results)} tickers.[/]"
            )
        else:
            self.query_one("#rec-status", Label).update(
                "[#ff0000]Could not generate recommendations.[/]"
            )

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

