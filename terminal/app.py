from __future__ import annotations

import json
import os
import sys

# Force UTF-8 on Windows to fix unicode rendering issues (like ? instead of blocks)
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# Ensure the parent directory is in sys.path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_service import AiService
from auto_engine import AutoEngine
from broker_service import BrokerService
from news_agent import NewsAgent
from terminal.state import AppState
from terminal.views import (
    OrdersView, PositionsView, SettingsView, WatchlistView,
    NewsView, ChatView,
    AddTickerModal, TradeModal, SearchTickerModal, AiRecommendModal,
)
from terminal.charts import PriceChartView
from terminal.history_views import HistoryModal, PiesModal, InstrumentsModal

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header, Label
    from textual.containers import Grid
except ImportError:  # pragma: no cover
    App = object  # type: ignore


ConfigDict = Dict[str, Any]


class TradingTerminalApp(App):  # type: ignore[misc]
    CSS_PATH = "terminal.css"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_data", "Refresh"),
        ("a", "toggle_mode", "Mode"),
        ("w", "cycle_watchlist", "Watchlist"),
        ("s", "suggest_ticker", "AI Suggest"),
        ("i", "generate_insights", "AI Insights"),
        ("n", "refresh_news", "News"),
        ("c", "focus_chat", "Chat"),
        ("g", "show_chart", "Chart"),
        ("t", "open_trade", "Trade"),
        ("equal_sign", "add_ticker", "Add Tkr"),
        ("minus", "remove_ticker", "Rm Tkr"),
        ("slash", "search_ticker", "Search"),
        ("d", "ai_recommend", "AI Recs"),
        ("o", "ai_optimise", "AI Optimize"),
        ("h", "show_history", "History"),
        ("p", "show_pies", "Pies"),
        ("e", "show_instruments", "Instruments"),
    ]

    def __init__(self, config_path: Path | str = "config.json") -> None:
        super().__init__()
        self.config_path = Path(config_path)
        self.config: ConfigDict = self._load_config()
        self.state = self._init_state()
        self.ai_service = AiService(self.config_path)
        self.broker_service = BrokerService(self.config)
        self.auto_engine = AutoEngine(self.config, self.state, self.ai_service, self.broker_service)

        # Shared Gemini client — reused by chat, search, recommend, scan, etc.
        self._gemini_client: Optional[Any] = None
        self.news_agent: Optional[NewsAgent] = None
        try:
            from gemini_client import GeminiClient, GeminiConfig
            gemini_cfg_raw = self.config.get("gemini", {})
            gcfg = GeminiConfig(
                model=gemini_cfg_raw.get("model", "gemini-2.5-flash"),
                api_key_env=gemini_cfg_raw.get("api_key_env", "GEMINI_API_KEY"),
            )
            self._gemini_client = GeminiClient(gcfg)

            # History Manager
            from database import HistoryManager
            self.history_manager = HistoryManager()

            news_interval = self.config.get("news", {}).get("refresh_interval_minutes", 5)
            self.news_agent = NewsAgent(self._gemini_client, refresh_interval_minutes=news_interval)
        except Exception as e:
            print(f"[app] Could not init Gemini/news: {e}")

        # View references
        self.settings_view: Optional[SettingsView] = None
        self.watchlist_view: Optional[WatchlistView] = None
        self.positions_view: Optional[PositionsView] = None
        self.orders_view: Optional[OrdersView] = None
        # ai_insights_view removed — insights now route to chat panel
        self.news_view: Optional[NewsView] = None
        self.chat_view: Optional[ChatView] = None
        self.chart_view: Optional[PriceChartView] = None

        self.refresh_timer = None
        self.state.broker_is_live = self.broker_service.is_live

    def _load_config(self) -> ConfigDict:
        with self.config_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _init_state(self) -> AppState:
        from terminal.state import AppState
        t_cfg = self.config.get("terminal", {})
        return AppState(
            mode=t_cfg.get("mode", "recommendation"),
            refresh_interval_seconds=t_cfg.get("refresh_interval_seconds", 30),
            capital=t_cfg.get("capital", 10000.0),
            max_daily_loss=t_cfg.get("max_daily_loss", 0.05),
            active_watchlist=self.config.get("active_watchlist", "Default")
        )

    # ── Layout ─────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        yield Header(show_clock=True)
        yield Label(f"TERMINAL [#{mode_str}] | BLOOMBERG AI CORE", id="app-header-title")
        with Grid(id="main-grid"):
            # Left column (rows 1-3)
            self.settings_view = SettingsView(self.state)
            self.positions_view = PositionsView(self.state)
            self.orders_view = OrdersView(self.state)

            # Center column
            self.watchlist_view = WatchlistView(self.state)
            self.chart_view = PriceChartView(self.state)

            # Right column
            self.chat_view = ChatView(self.state)
            self.news_view = NewsView(self.state)

            # Yield in grid order: left-to-right, top-to-bottom
            # Row 1: Settings | Watchlist (spans 2 rows) | Chat (spans 2 rows)
            yield self.settings_view
            yield self.watchlist_view
            yield self.chat_view

            # Row 2: Positions | (watchlist continues) | (chat continues)
            yield self.positions_view

            # Row 3: Orders | Chart | News
            yield self.orders_view
            yield self.chart_view
            yield self.news_view

        yield Footer()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def on_mount(self) -> None:  # type: ignore[override]
        # Restore chat history from DB
        if hasattr(self, 'history_manager'):
            try:
                saved_chat = self.history_manager.load_chat_history(50)
                if saved_chat:
                    self.state.chat_history = saved_chat
                    if self.chat_view:
                        self.chat_view.refresh_view()
            except Exception:
                pass

        self.refresh_data()
        self.refresh_timer = self.set_interval(
            self.state.refresh_interval_seconds,
            self.refresh_data,
        )
        # Start news agent
        if self.news_agent:
            tickers = self._get_active_tickers()
            self.news_agent.update_tickers(tickers)
            self.news_agent.start()

        # Hourly AI watchlist review
        self._cleanup_timer = self.set_interval(3600, self._hourly_watchlist_review)

        # Auto-optimize weights every 6 hours
        self._optimize_timer = self.set_interval(21600, self._auto_optimize)

        # Continuous AI market scanner every 30 minutes
        self._scanner_timer = self.set_interval(1800, self._ai_market_scan)

    def on_unmount(self) -> None:
        """Cleanup on shutdown."""
        if self.news_agent:
            self.news_agent.stop()
        if self.refresh_timer:
            self.refresh_timer.stop()
        if hasattr(self, '_cleanup_timer') and self._cleanup_timer:
            self._cleanup_timer.stop()
        if hasattr(self, '_optimize_timer') and self._optimize_timer:
            self._optimize_timer.stop()
        if hasattr(self, '_scanner_timer') and self._scanner_timer:
            self._scanner_timer.stop()
        # Prune old chat on exit to prevent unbounded DB growth
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.clear_old_chat(200)
            except Exception:
                pass

    def _get_active_tickers(self) -> List[str]:
        # Get all tickers from all watchlists
        watchlists = self.config.get("watchlists", {})
        all_tickers = set()
        for tickers in watchlists.values():
            all_tickers.update(tickers)
        
        # Add held tickers
        for pos in self.state.positions:
            t = pos.get("ticker")
            if t:
                all_tickers.add(t)
                
        return sorted(list(all_tickers))

    # ── Data Refresh ───────────────────────────────────────────────────

    def action_refresh_data(self) -> None:
        self.refresh_data()

    @work(thread=True)
    def refresh_data(self) -> None:
        if not self.is_running:
            return
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                # 1. Start tasks in parallel
                future_pos = executor.submit(self.broker_service.get_positions)
                future_acct = executor.submit(self.broker_service.get_account_info)
                
                # 2. Wait for broker data (needed for signals)
                positions = future_pos.result()
                account_info = future_acct.result()
                held_tickers = [p.get("ticker") for p in positions if p.get("ticker")]
                
                # Feed news data to AI service for ensemble weighting
                if self.news_agent:
                    self.ai_service.update_news_data(self.news_agent.news_data)

                # 3. Start AI and Auto-engine in parallel now that we have held_tickers
                future_signals = executor.submit(self.ai_service.get_latest_signals, held_tickers=held_tickers)
                executor.submit(self.auto_engine.step) # Auto engine can run in bkg
                
                # 4. Fetch live prices (can overlap with AI thinking)
                from data_loader import fetch_live_prices
                active_watchlist_tickers = self._get_active_tickers()
                all_relevant = list(set(active_watchlist_tickers + held_tickers))
                live_data = fetch_live_prices(all_relevant)
                
                # 5. Harvest final signals
                signals_df, _meta = future_signals.result()

            # 6. Calculate PnL
            upnl = sum(pos.get('unrealised_pnl', 0.0) for pos in positions)

            # 6. News data
            news_data = {}
            if self.news_agent:
                news_data = self.news_agent.news_data

            # 7. Update state on main thread
            self.call_from_thread(
                self._update_state_and_views,
                signals_df, positions, upnl, live_data, account_info, news_data,
            )
        except Exception as e:
            # Don't let the UI disappear! Log error and keep current state.
            msg = f"REFRESH ERROR: {e}"
            print(msg)
            # Optionally add to chat history so user sees it
            self.call_from_thread(self._handle_refresh_error, msg)

    def _handle_refresh_error(self, error_msg: str) -> None:
        self.state.chat_history.append({"role": "system", "text": f"[Error] {error_msg}"})
        if self.chat_view:
            self.chat_view.refresh_view()

    def _update_state_and_views(
        self, signals_df, positions, upnl, live_data, account_info, news_data,
    ) -> None:
        # Fill in live prices from T212 positions for tickers yfinance couldn't resolve
        for pos in positions:
            ticker = pos.get("ticker", "")
            current_price = pos.get("current_price", 0.0)
            if ticker and current_price > 0:
                existing = live_data.get(ticker, {})
                if existing.get("price", 0.0) == 0.0:
                    avg = pos.get("avg_price", 0.0)
                    change_pct = ((current_price - avg) / avg * 100.0) if avg > 0 else 0.0
                    live_data[ticker] = {"price": current_price, "change_pct": change_pct}

        self.state.signals = signals_df
        self.state.positions = positions
        self.state.unrealised_pnl = upnl
        self.state.live_data = live_data
        self.state.account_info = account_info
        self.state.news_sentiment = news_data

        # Save snapshot
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.save_snapshot(self.state)
            except Exception as e:
                print(f"[app] Snapshot save error: {e}")

        if self.settings_view:
            self.settings_view.refresh_view()
        if self.watchlist_view:
            self.watchlist_view.refresh_view()
        if self.positions_view:
            self.positions_view.refresh_view()
        if self.orders_view:
            self.orders_view.refresh_view()
        if self.news_view:
            self.news_view.refresh_view()
        if self.chart_view:
            self.chart_view.refresh_view()

    # ── Mode Toggle ────────────────────────────────────────────────────

    def action_toggle_mode(self) -> None:
        """Switch between Recommendation (Advisor) and Auto-Trading modes."""
        old_mode = self.state.mode
        new_mode = "full_auto_limited" if old_mode == "recommendation" else "recommendation"
        self.state.mode = new_mode
        
        # Sync to config
        if "terminal" not in self.config:
            self.config["terminal"] = {}
        self.config["terminal"]["mode"] = new_mode
        self._save_config()
        
        mode_label = "AUTO" if new_mode == "full_auto_limited" else "ADVISOR"
        try:
            self.query_one("#app-header-title", Label).update(f"TERMINAL [#{mode_label}] | BLOOMBERG AI CORE")
        except Exception:
            pass
            
        self.notify(f"Trading Mode: {mode_label.title()}", severity="information")
        self.refresh_data()

    # ── Watchlist Cycling ──────────────────────────────────────────────

    def action_cycle_watchlist(self) -> None:
        watchlists = self.config.get("watchlists", {})
        if not watchlists:
            return
        keys = list(watchlists.keys())
        current_idx = keys.index(self.state.active_watchlist) if self.state.active_watchlist in keys else 0
        next_idx = (current_idx + 1) % len(keys)
        self.state.active_watchlist = keys[next_idx]

        self.config["active_watchlist"] = self.state.active_watchlist
        self._save_config()

        # Update news agent tickers
        if self.news_agent:
            self.news_agent.update_tickers(self._get_active_tickers())

        self.ai_service._config_cache = None
        self.refresh_data()

    # ── AI Suggest Ticker ──────────────────────────────────────────────

    @work(thread=True)
    def action_suggest_ticker(self) -> None:
        suggestion = self.ai_service.suggest_new_ticker()
        if suggestion:
            self.config = self.ai_service.load_config()
            self.refresh_data()

    # ── AI Insights ────────────────────────────────────────────────────

    @work(thread=True)
    def action_generate_insights(self) -> None:
        analysis = self.ai_service.generate_portfolio_analysis(
            self.state.positions, self.state.signals,
        )
        self.call_from_thread(self._update_ai_insights, analysis)

    def _update_ai_insights(self, analysis: str) -> None:
        self.state.ai_insights = analysis
        self._add_chat_response(f"[AI INSIGHTS]\n{analysis}")

    # ── News Refresh ───────────────────────────────────────────────────

    @work(thread=True)
    def action_refresh_news(self) -> None:
        if self.news_agent:
            self.news_agent.fetch_now()
            news_data = self.news_agent.news_data
            self.call_from_thread(self._update_news, news_data)

    def _update_news(self, news_data) -> None:
        self.state.news_sentiment = news_data
        if self.news_view:
            self.news_view.refresh_view()

    # ── Chat ───────────────────────────────────────────────────────────

    def action_focus_chat(self) -> None:
        if self.chat_view:
            self.chat_view.chat_input.focus()

    def handle_chat_message(self, message: str) -> None:
        self.state.chat_history.append({"role": "user", "text": message})
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.save_chat_message("user", message)
            except Exception:
                pass
        if self.chat_view:
            self.chat_view.refresh_view()
        self._process_chat(message)

    @work(thread=True)
    def _process_chat(self, message: str) -> None:
        try:
            if not self._gemini_client:
                raise RuntimeError("Gemini client not initialised")
            response = self._gemini_client.chat_with_context(
                user_message=message,
                positions=self.state.positions,
                signals=self.state.signals,
                news_data=self.state.news_sentiment,
                account_info=self.state.account_info,
            )
        except Exception as e:
            response = f"Error: {e}"

        self.call_from_thread(self._add_chat_response, response)

    def _add_chat_response(self, response: str) -> None:
        self.state.chat_history.append({"role": "ai", "text": response})
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.save_chat_message("ai", response)
            except Exception:
                pass
        if self.chat_view:
            self.chat_view.refresh_view()

    # ── Chart ──────────────────────────────────────────────────────────

    @work(thread=True)
    def action_show_chart(self) -> None:
        # Get selected ticker from watchlist cursor
        ticker = self._get_selected_watchlist_ticker()
        if not ticker:
            return

        closes: list = []

        # Try yfinance first
        try:
            from data_loader import _clean_ticker
            yf_ticker = _clean_ticker(ticker)

            import yfinance as yf
            data = yf.download(yf_ticker, period="3mo", interval="1d", progress=False)
            if data is not None and not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                closes = [float(c) for c in data["Close"].dropna().tolist()]
        except Exception as e:
            print(f"[chart] yfinance error for {ticker}: {e}")

        # Fallback: if yfinance returned nothing, build a minimal chart from
        # T212 position data (avg_price → current_price gives at least 2 points)
        if not closes:
            for pos in self.state.positions:
                if pos.get("ticker") == ticker:
                    avg = pos.get("avg_price", 0)
                    cur = pos.get("current_price", 0)
                    if avg > 0 and cur > 0:
                        closes = [float(avg)] * 5 + [float(cur)]
                    break

        if closes:
            self.call_from_thread(self._update_chart, ticker, closes)

    def _get_selected_watchlist_ticker(self) -> str:
        if self.watchlist_view and self.watchlist_view.table.cursor_row is not None:
            try:
                row_idx = self.watchlist_view.table.cursor_row
                row_data = self.watchlist_view.table.get_row_at(row_idx)
                if row_data:
                    return str(row_data[0])
            except Exception:
                pass
        # Fallback: first ticker
        tickers = self._get_active_tickers()
        return tickers[0] if tickers else ""

    def _update_chart(self, ticker: str, closes: List[float]) -> None:
        self.state.selected_ticker = ticker
        self.state.chart_data = closes
        if self.chart_view:
            self.chart_view.refresh_view()

    # ── Add Ticker ─────────────────────────────────────────────────────

    def action_add_ticker(self) -> None:
        self.push_screen(AddTickerModal(), callback=self._on_add_ticker)

    def _on_add_ticker(self, ticker: Optional[str]) -> None:
        if ticker:
            self._add_ticker_to_watchlist(ticker)

    # ── Remove Ticker ──────────────────────────────────────────────────

    def action_remove_ticker(self) -> None:
        ticker = self._get_selected_watchlist_ticker()
        if not ticker:
            return
        watchlists = self.config.get("watchlists", {})
        active = self.state.active_watchlist
        if active in watchlists and ticker in watchlists[active]:
            watchlists[active].remove(ticker)
            self._save_config()
            self.ai_service._config_cache = None
            self.refresh_data()

    # ── Trade ──────────────────────────────────────────────────────────

    def action_open_trade(self) -> None:
        ticker = self._get_selected_watchlist_ticker()
        if not ticker:
            return
        self.push_screen(TradeModal(ticker=ticker), callback=self._on_trade_submit)

    def _on_trade_submit(self, result: Optional[Dict]) -> None:
        if not result:
            return
        self._execute_trade(result)

    @work(thread=True)
    def _execute_trade(self, trade: Dict) -> None:
        result = self.broker_service.submit_order(
            ticker=trade["ticker"],
            side=trade["side"],
            quantity=trade["quantity"],
            order_type=trade["order_type"],
            limit_price=trade.get("price") if trade["order_type"] in ("limit", "stop_limit") else None,
            stop_price=trade.get("price") if trade["order_type"] in ("stop", "stop_limit") else None,
        )
        self.call_from_thread(self._on_trade_result, result)

    def _on_trade_result(self, result: Dict) -> None:
        self.state.recent_orders.append(result)
        if self.orders_view:
            self.orders_view.refresh_view()
        # Refresh positions after trade
        self.refresh_data()

    # ── Search Tickers ──────────────────────────────────────────────────

    def action_search_ticker(self) -> None:
        self.push_screen(SearchTickerModal(), callback=self._on_search_result)

    def _on_search_result(self, ticker: Optional[str]) -> None:
        if not ticker:
            return
        self._add_ticker_to_watchlist(ticker)

    def search_tickers_for_modal(self, query: str, callback) -> None:
        """Called by SearchTickerModal to search tickers in background."""
        self._do_search(query, callback)

    @work(thread=True)
    def _do_search(self, query: str, callback) -> None:
        try:
            if not self._gemini_client:
                raise RuntimeError("Gemini client not initialised")
            results = self._gemini_client.search_tickers(query)
        except Exception as e:
            results = []
            print(f"[search] Error: {e}")
        self.call_from_thread(callback, results)

    # ── AI Recommend Tickers ───────────────────────────────────────────

    def action_ai_recommend(self) -> None:
        self.push_screen(AiRecommendModal(), callback=self._on_recommend_result)

    def _on_recommend_result(self, result: Optional[Dict]) -> None:
        if not result:
            return
        if result.get("mode") == "single":
            self._add_ticker_to_watchlist(result["ticker"])
        elif result.get("mode") == "all":
            for ticker in result.get("tickers", []):
                self._add_ticker_to_watchlist(ticker)

    def get_ai_recommendations(self, category: str, callback) -> None:
        """Called by AiRecommendModal to get recommendations in background."""
        self._do_recommend(category, callback)

    @work(thread=True)
    def _do_recommend(self, category: str, callback) -> None:
        try:
            if not self._gemini_client:
                raise RuntimeError("Gemini client not initialised")
            current_tickers = self._get_active_tickers()
            results = self._gemini_client.recommend_tickers(current_tickers, category=category, count=5)
        except Exception as e:
            results = []
            print(f"[recommend] Error: {e}")
        self.call_from_thread(callback, results)

    # ── Shared Ticker Helpers ──────────────────────────────────────────

    def _add_ticker_to_watchlist(self, ticker: str) -> None:
        """Add a ticker to the active watchlist and refresh."""
        ticker = ticker.upper().strip()
        if not ticker:
            return
        watchlists = self.config.get("watchlists", {})
        active = self.state.active_watchlist
        if active in watchlists:
            if ticker not in watchlists[active]:
                watchlists[active].append(ticker)
                self._save_config()
                self.ai_service._config_cache = None
                if self.news_agent:
                    self.news_agent.update_tickers(self._get_active_tickers())
                self.refresh_data()

    # ── History Modal ──────────────────────────────────────────────────

    def action_show_history(self) -> None:
        self.load_history_data()
        self.push_screen(HistoryModal(self.state), callback=lambda _: None)

    @work(thread=True)
    def load_history_data(self, callback=None) -> None:
        """Fetch order history, dividends, and transactions from broker."""
        try:
            orders = self.broker_service.get_order_history(limit=50)
            dividends = self.broker_service.get_dividends(limit=50)
            transactions = self.broker_service.get_transactions(limit=50)
            self.call_from_thread(
                self._update_history_state,
                orders.get("items", []),
                dividends.get("items", []),
                transactions.get("items", []),
                callback,
            )
        except Exception as e:
            print(f"[history] Error loading history: {e}")

    def _update_history_state(self, orders, dividends, transactions, callback=None) -> None:
        self.state.order_history = orders
        self.state.dividend_history = dividends
        self.state.transaction_history = transactions
        if callback:
            callback()

    # ── Pies Modal ─────────────────────────────────────────────────────

    def action_show_pies(self) -> None:
        self.load_pies_data()
        self.push_screen(PiesModal(self.state), callback=lambda _: None)

    @work(thread=True)
    def load_pies_data(self, callback=None) -> None:
        """Fetch pies list from broker."""
        try:
            pies = self.broker_service.get_pies()
            self.call_from_thread(self._update_pies_state, pies, callback)
        except Exception as e:
            print(f"[pies] Error loading pies: {e}")

    def _update_pies_state(self, pies, callback=None) -> None:
        self.state.pies = pies
        if callback:
            callback()

    @work(thread=True)
    def load_pie_detail(self, pie_id: int, callback=None) -> None:
        """Fetch detail for a single pie."""
        try:
            detail = self.broker_service.get_pie(pie_id)
            if callback:
                self.call_from_thread(callback, detail)
        except Exception as e:
            print(f"[pies] Error loading pie {pie_id}: {e}")

    # ── Instruments Modal ──────────────────────────────────────────────

    def action_show_instruments(self) -> None:
        self.push_screen(InstrumentsModal(), callback=self._on_instrument_selected)

    def _on_instrument_selected(self, ticker: Optional[str]) -> None:
        if ticker:
            self._add_ticker_to_watchlist(ticker)

    @work(thread=True)
    def load_instruments(self, callback=None) -> None:
        """Fetch tradeable instruments from broker."""
        try:
            instruments = self.broker_service.get_instruments()
            if callback:
                self.call_from_thread(callback, instruments)
        except Exception as e:
            print(f"[instruments] Error loading instruments: {e}")
            if callback:
                self.call_from_thread(callback, [])

    # ── AI Self-Optimization ──────────────────────────────────────────

    @work(thread=True)
    def action_ai_optimise(self) -> None:
        """AI analyzes performance, proposes changes, notifies user, then applies them."""
        self.call_from_thread(
            self._add_chat_response,
            "[AI OPTIMIZER] Analyzing recent performance to tune algorithm weights..."
        )

        try:
            # 1. Gather performance data from DB
            history_lines = []
            dates = self.history_manager.get_recent_dates(7) if hasattr(self, 'history_manager') else []
            for d in dates:
                snap = self.history_manager.get_snapshot(d)
                if snap:
                    history_lines.append(
                        f"  {snap['date']}: equity=${snap['equity']:.2f}, pnl=${snap['pnl']:.2f}, mode={snap['mode']}"
                    )

            # Current config values
            ai_cfg = self.config.get("ai", {})
            strat_cfg = self.config.get("strategy", {})
            current = {
                "sklearn_weight": ai_cfg.get("sklearn_weight", 0.5),
                "gemini_weight": ai_cfg.get("gemini_weight", 0.3),
                "news_weight": ai_cfg.get("news_weight", 0.2),
                "threshold_buy": strat_cfg.get("threshold_buy", 0.6),
                "threshold_sell": strat_cfg.get("threshold_sell", 0.4),
            }

            history_text = "\n".join(history_lines) if history_lines else "  No history yet (first run)"

            # 2. Ask Gemini for concrete changes
            if not self._gemini_client:
                self.call_from_thread(self._add_chat_response, "[AI OPTIMIZER] Gemini client not available.")
                return
            client = self._gemini_client

            prompt = (
                "You are a quant advisor tuning a stock trading algorithm.\n\n"
                f"Recent performance:\n{history_text}\n\n"
                f"Current config:\n{json.dumps(current, indent=2)}\n\n"
                "Rules:\n"
                "- sklearn_weight + gemini_weight + news_weight should sum to ~1.0\n"
                "- threshold_buy must be between 0.5 and 0.8\n"
                "- threshold_sell must be between 0.2 and 0.5\n"
                "- Only change values if data supports it. Keep current if unsure.\n\n"
                "Respond strictly as JSON:\n"
                '{"changes": {"sklearn_weight": 0.5, "gemini_weight": 0.3, "news_weight": 0.2, '
                '"threshold_buy": 0.6, "threshold_sell": 0.4}, '
                '"explanation": "one paragraph explaining why these changes"}'
            )

            text = client._call(prompt)
            if not text:
                self.call_from_thread(self._add_chat_response, "[AI OPTIMIZER] Could not reach AI. No changes made.")
                return

            obj = client._parse_json(text)
            changes = obj.get("changes", {})
            explanation = obj.get("explanation", "No explanation provided.")

            if not changes:
                self.call_from_thread(self._add_chat_response, f"[AI OPTIMIZER] No changes recommended.\n{explanation}")
                return

            # 3. Notify user FIRST — show what will change
            diff_lines = []
            for key, new_val in changes.items():
                old_val = current.get(key)
                if old_val is not None and float(old_val) != float(new_val):
                    diff_lines.append(f"  {key}: {old_val} -> {new_val}")

            if not diff_lines:
                self.call_from_thread(
                    self._add_chat_response,
                    f"[AI OPTIMIZER] Analyzed — current weights are optimal. No changes.\n{explanation}"
                )
                return

            notification = (
                "[AI OPTIMIZER] Applying algorithm changes:\n"
                + "\n".join(diff_lines)
                + f"\n\nReason: {explanation}"
            )
            self.call_from_thread(self._add_chat_response, notification)

            # 4. Apply changes to config
            for key in ("sklearn_weight", "gemini_weight", "news_weight"):
                if key in changes:
                    val = max(0.0, min(1.0, float(changes[key])))
                    old = ai_cfg.get(key, 0)
                    ai_cfg[key] = val
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])

            for key in ("threshold_buy", "threshold_sell"):
                if key in changes:
                    val = float(changes[key])
                    if key == "threshold_buy":
                        val = max(0.5, min(0.8, val))
                    else:
                        val = max(0.2, min(0.5, val))
                    old = strat_cfg.get(key, 0)
                    strat_cfg[key] = val
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])

            self.config["ai"] = ai_cfg
            self.config["strategy"] = strat_cfg
            self._save_config()
            self.ai_service._config_cache = None  # Force reload

            self.call_from_thread(
                self._add_chat_response,
                "[AI OPTIMIZER] Changes applied and saved to config.json."
            )

        except Exception as e:
            self.call_from_thread(self._handle_refresh_error, f"Optimizer Error: {e}")

    def _auto_optimize(self) -> None:
        """Periodic self-optimization — reuses the manual optimizer logic."""
        if not hasattr(self, 'history_manager'):
            return
        dates = self.history_manager.get_recent_dates(3)
        if len(dates) < 2:
            return  # Not enough data to optimize yet
        self.action_ai_optimise()

    # ── History Analysis ──────────────────────────────────────────────

    @work(thread=True)
    def action_analyze_history(self) -> None:
        """Deep dive analysis of historical data using Gemini."""
        self.call_from_thread(self._handle_refresh_error, "AI Historian: Retrieving previous terminal states...")

        try:
            dates = self.history_manager.get_recent_dates(7)
            if not dates:
                self.call_from_thread(self._add_chat_response, "No historical data found in database yet.")
                return

            history_summary = ""
            for d in dates:
                snap = self.history_manager.get_snapshot(d)
                if snap:
                    history_summary += f"- {d}: Equity=${snap['equity']:.2f}, PnL=${snap['pnl']:.2f}\n"

            prompt = (
                f"Analyze my trading history for the past week:\n{history_summary}\n\n"
                "Provide a 3-sentence summary of the week's performance, identify the best day, "
                "and give one piece of actionable advice for tomorrow. Be a supportive but objective historian."
            )

            results = self.news_agent.gemini_client._call(prompt)
            self.call_from_thread(self._add_chat_response, f"[HISTORICAL ANALYSIS]\n{results}")
        except Exception as e:
            self.call_from_thread(self._handle_refresh_error, f"History Error: {e}")

    # ── Continuous AI Market Scanner ──────────────────────────────────

    @work(thread=True)
    def _ai_market_scan(self) -> None:
        """Periodic market intelligence scan — finds opportunities and alerts.

        Runs every 30 minutes. Checks:
        1. Strong signals from current watchlist that need attention
        2. Suggests new tickers to explore
        3. Flags risk events for held positions
        """
        try:
            if not self._gemini_client:
                return
            client = self._gemini_client

            # Build context from current state
            sig_summary = ""
            if self.state.signals is not None and not self.state.signals.empty:
                for _, row in self.state.signals.head(10).iterrows():
                    sig_summary += (
                        f"  {row.get('ticker','?')}: signal={row.get('signal','?')}, "
                        f"prob={row.get('prob_up',0):.2f}, ai_rec={row.get('ai_rec','')}\n"
                    )

            pos_summary = ""
            for p in self.state.positions:
                pos_summary += (
                    f"  {p.get('ticker','?')}: qty={p.get('quantity',0)}, "
                    f"pnl=${p.get('unrealised_pnl',0):.2f}\n"
                )

            all_tickers = self._get_active_tickers()

            prompt = (
                "You are a market intelligence scanner for a stock trading terminal.\n\n"
                f"Current watchlist: {all_tickers}\n"
                f"Current signals:\n{sig_summary or '  None yet'}\n"
                f"Open positions:\n{pos_summary or '  None'}\n\n"
                "Tasks:\n"
                "1. Flag any URGENT signals (strong buy/sell with >0.7 probability) that need immediate attention\n"
                "2. Identify any RISK to current positions based on recent market conditions\n"
                "3. Suggest ONE new ticker worth investigating (not already on the watchlist)\n\n"
                "Be concise — max 3-4 sentences total. Only report if something is notable. "
                "If nothing stands out, respond with just: 'SCAN: All clear.'\n"
                "Respond as plain text, not JSON."
            )

            result = client._call(prompt)
            if not result:
                return

            # Only post to chat if the scan found something notable
            result = result.strip()
            if result and "all clear" not in result.lower():
                self.call_from_thread(self._add_chat_response, f"[MARKET SCAN]\n{result}")

                # If a new ticker was suggested, offer to add it
                suggestion = client.suggest_ticker(all_tickers)
                if suggestion and suggestion not in all_tickers:
                    watchlists = self.config.get("watchlists", {})
                    active = self.state.active_watchlist
                    if active in watchlists and suggestion not in watchlists[active]:
                        watchlists[active].append(suggestion)
                        self._save_config()
                        if hasattr(self, 'history_manager'):
                            self.history_manager.log_watchlist_action(
                                "ADD", suggestion, active, "AI market scanner suggestion"
                            )
                        if self.news_agent:
                            self.news_agent.update_tickers(self._get_active_tickers())
                        self.call_from_thread(
                            self._add_chat_response,
                            f"[MARKET SCAN] Added {suggestion} to {active} watchlist for monitoring."
                        )

        except Exception as e:
            print(f"[app] Market scan error: {e}")

    # ── Hourly Watchlist Review ────────────────────────────────────────

    @work(thread=True)
    def _hourly_watchlist_review(self) -> None:
        """AI reviews watchlist and removes tickers it deems unnecessary.
        NEVER removes tickers with open positions or pending orders."""
        try:
            watchlists = self.config.get("watchlists", {})
            active = self.state.active_watchlist
            tickers = watchlists.get(active, [])
            if len(tickers) <= 3:
                return  # Too few to prune

            # Build protected set: positions + pending orders
            protected = set()
            for pos in self.state.positions:
                t = pos.get("ticker")
                if t:
                    protected.add(t)
            try:
                pending = self.broker_service.get_pending_orders()
                for o in pending:
                    t = o.get("ticker")
                    if t:
                        protected.add(t)
            except Exception:
                pass

            removable = [t for t in tickers if t not in protected]
            if not removable:
                return

            # Ask Gemini which tickers (if any) should be dropped
            if not self._gemini_client:
                return
            client = self._gemini_client

            prompt = (
                f"You are reviewing the active watchlist: {removable}\n"
                f"Protected tickers (CANNOT be removed): {list(protected)}\n\n"
                "Identify tickers that are no longer worth watching based on current "
                "market conditions, lack of momentum, or poor fundamentals. "
                "Be conservative — only remove tickers you are confident are not worth tracking. "
                "If all tickers are worth keeping, return an empty list.\n\n"
                "Respond strictly as JSON: "
                '{\"remove\": [\"TICK1\"], \"reasons\": {\"TICK1\": \"reason\"}}'
            )

            text = client._call(prompt)
            if not text:
                return
            obj = client._parse_json(text)
            to_remove = obj.get("remove", [])
            reasons = obj.get("reasons", {})

            if not to_remove:
                return

            for ticker in to_remove:
                ticker = str(ticker).upper().strip()
                if ticker in protected:
                    continue  # Safety guard
                if ticker in watchlists.get(active, []):
                    watchlists[active].remove(ticker)
                    reason = reasons.get(ticker, "AI deemed not worth watching")
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_watchlist_action("REMOVE", ticker, active, reason)
                    self.call_from_thread(
                        self._add_chat_response,
                        f"[AI WATCHLIST] Removed {ticker}: {reason}"
                    )

            if to_remove:
                self._save_config()
                self.ai_service._config_cache = None
                if self.news_agent:
                    self.news_agent.update_tickers(self._get_active_tickers())

        except Exception as e:
            print(f"[app] Watchlist review error: {e}")

    # ── Config Helpers ─────────────────────────────────────────────────

    def _save_config(self) -> None:
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)


def run_terminal() -> None:
    import os
    if not os.getenv("GEMINI_API_KEY"):
        print("\n" + "!" * 60)
        print("  WARNING: GEMINI_API_KEY is not set!")
        print("  AI features will not work without it.")
        print("  Set it permanently with:")
        print('  [System.Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "YOUR_KEY", "User")')
        print("!" * 60 + "\n")

    app = TradingTerminalApp()
    app.run()


if __name__ == "__main__":
    run_terminal()
