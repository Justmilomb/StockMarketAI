"""Main window for the StockMarketAI desktop application.

Implements the Bloomberg-style 3x4 grid layout using QGridLayout,
wires up all services (AI, broker, news, etc.), and manages
background timers and keyboard shortcuts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from desktop.state import init_state, load_config, resolve_config_path
from desktop.panels.settings import SettingsPanel
from desktop.panels.watchlist import WatchlistPanel
from desktop.panels.positions import PositionsPanel
from desktop.panels.orders import OrdersPanel
from desktop.panels.chat import ChatPanel
from desktop.panels.news import NewsPanel
from desktop.panels.chart import ChartPanel
from desktop.panels.pipeline import PipelinePanel
from desktop.workers import BackgroundTask, RefreshWorker


class MainWindow(QMainWindow):
    """Bloomberg-style trading terminal window."""

    def __init__(self, config_path: Path | str = "config.json") -> None:
        super().__init__()
        self.config_path = resolve_config_path(config_path)
        self.config: Dict[str, Any] = load_config(self.config_path)
        self._is_fresh_config = self._detect_fresh_config()
        self.state = init_state(self.config)

        # ── Services ──────────────────────────────────────────────────
        from ai_service import AiService
        from auto_engine import AutoEngine
        from broker_service import BrokerService
        from news_agent import NewsAgent
        from pipeline_tracker import PipelineTracker

        self.pipeline_tracker = PipelineTracker()
        self.ai_service = AiService(self.config_path)
        self.ai_service.tracker = self.pipeline_tracker
        self.broker_service = BrokerService(self.config)
        self.auto_engine = AutoEngine(
            self.config, self.state, self.ai_service, self.broker_service,
        )

        self._claude_client: Optional[Any] = None
        self.news_agent: Optional[NewsAgent] = None
        self.history_manager: Optional[Any] = None

        try:
            from claude_client import ClaudeClient, ClaudeConfig
            claude_cfg_raw = self.config.get("claude", {})
            ccfg = ClaudeConfig(
                model=claude_cfg_raw.get("model", "claude-sonnet-4-20250514"),
            )
            self._claude_client = ClaudeClient(ccfg)

            from database import HistoryManager
            self.history_manager = HistoryManager()

            from accuracy_tracker import AccuracyTracker
            self.ai_service._accuracy_tracker = AccuracyTracker(self.history_manager)

            news_interval = self.config.get("news", {}).get(
                "refresh_interval_minutes", 5,
            )
            self.news_agent = NewsAgent(
                self._claude_client, refresh_interval_minutes=news_interval,
            )
        except Exception as e:
            print(f"[desktop] Could not init Claude/news: {e}")

        self.state.broker_is_live = self.broker_service.is_live

        # Pipeline / signal cache state
        self._last_signal_run: float = 0.0
        self._pipeline_running: bool = False
        self._pipeline_start_time: float = 0.0
        self._signal_cache_seconds: float = 120.0
        self._pipeline_timeout_seconds: float = 600.0

        # Active worker references (prevent GC)
        self._refresh_worker: Optional[RefreshWorker] = None
        self._active_workers: List[BackgroundTask] = []

        # ── Build UI ──────────────────────────────────────────────────
        self._build_ui()
        self._setup_shortcuts()
        self._setup_timers()
        self._restore_state()

    # ══════════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Create the 3x4 grid layout with all panels."""
        self.setWindowTitle("StockMarketAI Terminal")
        self.setMinimumSize(1280, 720)

        # ── Menu bar ─────────────────────────────────────────────────
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        file_menu.addAction("Import Config...", self._import_config)
        file_menu.addAction("Export Config...", self._export_config)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header label
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        asset_str = self.state.active_asset_class.upper()
        self._header_label = QLabel(
            f"  TERMINAL [{mode_str}] | {asset_str} | BLOOMBERG AI CORE",
        )
        self._header_label.setFixedHeight(28)
        self._header_label.setStyleSheet(
            "background-color: #0a0a0a; color: #ffb000; font-weight: bold; "
            "border-bottom: 1px solid #333333; padding-left: 8px;",
        )
        root_layout.addWidget(self._header_label)

        # ── Grid ──────────────────────────────────────────────────────
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # Column stretch: 1fr 2fr 1fr
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)

        # Row stretch: 1fr 1fr 1fr (row 3 is auto-height for pipeline)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        grid.setRowStretch(3, 0)

        # ── Create panels ─────────────────────────────────────────────
        self.settings_panel = SettingsPanel(self.state)
        self.watchlist_panel = WatchlistPanel(self.state)
        self.chat_panel = ChatPanel(self.state)
        self.positions_panel = PositionsPanel(self.state)
        self.orders_panel = OrdersPanel(self.state)
        self.chart_panel = ChartPanel(self.state)
        self.news_panel = NewsPanel(self.state)
        self.pipeline_panel = PipelinePanel(self.pipeline_tracker)

        # ── Place panels in grid ──────────────────────────────────────
        # (row, col, rowSpan, colSpan)
        grid.addWidget(self.settings_panel,   0, 0, 1, 1)  # L1
        grid.addWidget(self.watchlist_panel,   0, 1, 2, 1)  # C1-2 (span 2 rows)
        grid.addWidget(self.chat_panel,        0, 2, 2, 1)  # R1-2 (span 2 rows)
        grid.addWidget(self.positions_panel,   1, 0, 1, 1)  # L2
        grid.addWidget(self.orders_panel,      2, 0, 1, 1)  # L3
        grid.addWidget(self.chart_panel,       2, 1, 1, 1)  # C3
        grid.addWidget(self.news_panel,        2, 2, 1, 1)  # R3
        grid.addWidget(self.pipeline_panel,    3, 0, 1, 3)  # Row 4, full width

        root_layout.addWidget(grid_widget, 1)

        # ── Status bar (replaces Textual Footer) ──────────────────────
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel(
            "  1 Stocks | 2 Poly | 3 Crypto | ? Help | R Refresh | A Mode | "
            "W Watchlist | T Trade | C Chat | G Chart | H History | Q Quit",
        )
        status.addPermanentWidget(self._status_label, 1)

    # ══════════════════════════════════════════════════════════════════
    #  Keyboard Shortcuts
    # ══════════════════════════════════════════════════════════════════

    def _setup_shortcuts(self) -> None:
        """Register all keyboard shortcuts matching the Textual BINDINGS."""
        shortcuts = [
            ("?", self.action_show_help),
            ("Q", self.close),
            ("R", self.action_refresh_data),
            ("A", self.action_toggle_mode),
            ("W", self.action_cycle_watchlist),
            ("S", self.action_suggest_ticker),
            ("I", self.action_generate_insights),
            ("N", self.action_refresh_news),
            ("C", self.action_focus_chat),
            ("G", self.action_show_chart),
            ("T", self.action_open_trade),
            ("=", self.action_add_ticker),
            ("-", self.action_remove_ticker),
            ("/", self.action_search_ticker),
            ("D", self.action_ai_recommend),
            ("O", self.action_ai_optimise),
            ("H", self.action_show_history),
            ("P", self.action_show_pies),
            ("E", self.action_show_instruments),
            ("L", self.action_toggle_protect),
            ("1", lambda: self._switch_asset("stocks")),
            ("2", lambda: self._switch_asset("polymarket")),
            ("3", lambda: self._switch_asset("crypto")),
        ]
        for key, slot in shortcuts:
            QShortcut(QKeySequence(key), self, slot)

    # ══════════════════════════════════════════════════════════════════
    #  Timers
    # ══════════════════════════════════════════════════════════════════

    def _setup_timers(self) -> None:
        """Start all periodic background timers."""
        interval_ms = self.state.refresh_interval_seconds * 1000

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.action_refresh_data)
        self._refresh_timer.start(interval_ms)

        self._scanner_timer = QTimer(self)
        self._scanner_timer.timeout.connect(self._ai_market_scan)
        self._scanner_timer.start(900_000)  # 15 min

        self._optimize_timer = QTimer(self)
        self._optimize_timer.timeout.connect(self._auto_optimize)
        self._optimize_timer.start(14_400_000)  # 4 hr

        self._discovery_timer = QTimer(self)
        self._discovery_timer.timeout.connect(self._daily_stock_discovery)
        self._discovery_timer.start(7_200_000)  # 2 hr

        # Pipeline progress poll (250ms)
        self._pipeline_poll_timer = QTimer(self)
        self._pipeline_poll_timer.timeout.connect(
            self.pipeline_panel.poll_tracker,
        )
        self._pipeline_poll_timer.start(250)

    def _detect_fresh_config(self) -> bool:
        """True if config was just created with defaults (no real tickers)."""
        watchlists = self.config.get("watchlists", {})
        return all(len(v) == 0 for v in watchlists.values())

    def _restore_state(self) -> None:
        """Load chat history, wire signals, trigger initial data refresh."""
        # Wire chat submission
        self.chat_panel.message_submitted.connect(self._handle_chat_message)
        if self.history_manager:
            try:
                saved_chat = self.history_manager.load_chat_history(50)
                for msg in saved_chat:
                    self.state.chat_history.append({
                        "role": msg.get("role", "user"),
                        "text": msg.get("text", ""),
                    })
                self.chat_panel.refresh_view(self.state)
            except Exception:
                pass

        if self.news_agent:
            try:
                self.news_agent.start()
            except Exception:
                pass

        # First launch with default config — prompt user to import
        if self._is_fresh_config:
            QTimer.singleShot(500, self._prompt_first_run_import)

        # Initial data fetch
        QTimer.singleShot(100, self.action_refresh_data)

    # ══════════════════════════════════════════════════════════════════
    #  Data Refresh (main loop)
    # ══════════════════════════════════════════════════════════════════

    @Slot()
    def action_refresh_data(self, force_signals: bool = False) -> None:
        """Kick off a background data refresh."""
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            return  # Already running

        now = time.time()
        need_signals = force_signals or (
            now - self._last_signal_run > self._signal_cache_seconds
        )

        # Safety: reset stale pipeline flag
        if self._pipeline_running and (
            now - self._pipeline_start_time > self._pipeline_timeout_seconds
        ):
            self._pipeline_running = False

        if need_signals and self._pipeline_running:
            need_signals = False

        self._refresh_worker = RefreshWorker(
            ai_service=self.ai_service,
            broker_service=self.broker_service,
            news_agent=self.news_agent,
            config=self.config,
            state=self.state,
            run_signals=need_signals,
        )
        self._refresh_worker.finished_signal.connect(self._on_refresh_done)
        self._refresh_worker.error_signal.connect(self._on_refresh_error)

        if need_signals:
            self._pipeline_running = True
            self._pipeline_start_time = now

        self._refresh_worker.start()

    @Slot(object)
    def _on_refresh_done(self, result: Dict[str, Any]) -> None:
        """Apply refresh results to state and update all panels."""
        if result.get("signals") is not None:
            self.state.signals = result["signals"]
            self._last_signal_run = time.time()
            self._pipeline_running = False

        if result.get("positions") is not None:
            self.state.positions = result["positions"]
        if result.get("account_info"):
            self.state.account_info = result["account_info"]
        if result.get("live_data"):
            self.state.live_data = result["live_data"]
        if result.get("recent_orders") is not None:
            self.state.recent_orders = result["recent_orders"]
        if result.get("news_sentiment"):
            self.state.news_sentiment = result["news_sentiment"]

        # Ensemble / regime metadata
        if result.get("consensus_data"):
            self.state.consensus_data = result["consensus_data"]
        if result.get("current_regime"):
            self.state.current_regime = result["current_regime"]
        if result.get("regime_confidence") is not None:
            self.state.regime_confidence = result["regime_confidence"]
        if result.get("ensemble_model_count") is not None:
            self.state.ensemble_model_count = result["ensemble_model_count"]
        if result.get("strategy_assignments"):
            self.state.strategy_assignments = result["strategy_assignments"]

        # Calculate PnL
        self._calculate_pnl()

        # Refresh all panels
        self._refresh_all_panels()

    @Slot(str)
    def _on_refresh_error(self, error_msg: str) -> None:
        """Handle refresh errors."""
        self._pipeline_running = False
        self.statusBar().showMessage(f"Refresh error: {error_msg}", 5000)

    def _calculate_pnl(self) -> None:
        """Calculate unrealised PnL from positions and live data."""
        upnl = 0.0
        for pos in self.state.positions:
            ticker = pos.get("ticker", "")
            qty = float(pos.get("quantity", 0))
            avg_px = float(pos.get("averagePrice", pos.get("avg_price", 0)))
            live = self.state.live_data.get(ticker, {})
            cur_px = float(live.get("price", avg_px))
            upnl += (cur_px - avg_px) * qty
        self.state.unrealised_pnl = upnl

    def _refresh_all_panels(self) -> None:
        """Refresh every panel with current state."""
        self.settings_panel.refresh_view(self.state)
        self.watchlist_panel.refresh_view(self.state)
        self.positions_panel.refresh_view(self.state)
        self.orders_panel.refresh_view(self.state)
        self.chart_panel.refresh_view(self.state)
        self.news_panel.refresh_view(self.state)
        self.chat_panel.refresh_view(self.state)

        # Update header
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        self._header_label.setText(
            f"  TERMINAL [{mode_str}] | BLOOMBERG AI CORE",
        )

    # ══════════════════════════════════════════════════════════════════
    #  Action Stubs (will be implemented in Phases 7-9)
    # ══════════════════════════════════════════════════════════════════

    @Slot()
    def action_show_help(self) -> None:
        from desktop.dialogs.help import HelpDialog
        HelpDialog(self).exec()

    @Slot()
    def _update_header(self) -> None:
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        asset_str = self.state.active_asset_class.upper()
        self._header_label.setText(
            f"  TERMINAL [{mode_str}] | {asset_str} | BLOOMBERG AI CORE",
        )

    def _switch_asset(self, asset_class: str) -> None:
        """Switch active asset class (1=stocks, 2=polymarket, 3=crypto)."""
        if asset_class == self.state.active_asset_class:
            return
        asset_cfg = self.config.get(asset_class, {})
        if asset_class != "stocks" and not asset_cfg.get("enabled", False):
            self.statusBar().showMessage(
                f"{asset_class.title()} is disabled in config.json", 3000,
            )
            return
        self.state.switch_asset_class(asset_class)
        if asset_class == "stocks":
            self.state.active_watchlist = self.config.get("active_watchlist", "Default")
        else:
            self.state.active_watchlist = asset_cfg.get("active_watchlist", "")
        self._save_config_key("active_asset_class", asset_class)
        self._update_header()
        self._refresh_all_panels()
        self.statusBar().showMessage(f"Switched to {asset_class.title()}", 3000)

    def action_toggle_mode(self) -> None:
        if self.state.mode == "recommendation":
            self.state.mode = "full_auto_limited"
        else:
            self.state.mode = "recommendation"
        self._save_config_key("terminal.mode", self.state.mode)
        self._update_header()
        self._refresh_all_panels()
        self.statusBar().showMessage(
            f"Mode: {self.state.mode}", 3000,
        )

    @Slot()
    def action_cycle_watchlist(self) -> None:
        watchlists = list(self.config.get("watchlists", {}).keys())
        if not watchlists:
            return
        try:
            idx = watchlists.index(self.state.active_watchlist)
            next_idx = (idx + 1) % len(watchlists)
        except ValueError:
            next_idx = 0
        self.state.active_watchlist = watchlists[next_idx]
        self._save_config_key("active_watchlist", self.state.active_watchlist)
        self.statusBar().showMessage(
            f"Watchlist: {self.state.active_watchlist}", 3000,
        )
        self.action_refresh_data(force_signals=True)

    @Slot()
    def action_suggest_ticker(self) -> None:
        self.statusBar().showMessage("AI suggesting ticker...", 10000)
        self._run_background(
            lambda: self.ai_service.suggest_new_ticker(),
            self._on_suggest_result,
        )

    def _on_suggest_result(self, suggestion: str) -> None:
        if suggestion:
            self.config = load_config(self.config_path)
            self.statusBar().showMessage(f"AI suggested: {suggestion}", 5000)
            self._add_chat_response(f"[AI SUGGEST] Added {suggestion} to watchlist.")
            self._refresh_all_panels()
        else:
            self.statusBar().showMessage("AI had no suggestions", 3000)

    @Slot()
    def action_generate_insights(self) -> None:
        self.statusBar().showMessage("Generating AI insights...", 10000)
        self._run_background(
            lambda: self.ai_service.generate_portfolio_analysis(
                self.state.positions, self.state.signals,
            ),
            self._on_insights_result,
        )

    def _on_insights_result(self, analysis: str) -> None:
        self.statusBar().showMessage("", 0)
        self.state.ai_insights = analysis
        self._add_chat_response(f"[AI INSIGHTS]\n{analysis}")

    @Slot()
    def action_refresh_news(self) -> None:
        if not self.news_agent:
            self.statusBar().showMessage("News agent not available", 3000)
            return
        self.statusBar().showMessage("Refreshing news...", 10000)
        self._run_background(
            lambda: (self.news_agent.fetch_now(), self.news_agent.news_data)[-1],
            self._on_news_refreshed,
        )

    def _on_news_refreshed(self, news_data: Any) -> None:
        self.state.news_sentiment = news_data
        self.news_panel.refresh_view(self.state)
        self.statusBar().showMessage("News refreshed", 3000)

    @Slot()
    def action_focus_chat(self) -> None:
        self.chat_panel.focus_input()

    def _handle_chat_message(self, message: str) -> None:
        """User submitted a chat message — persist, display, process in background."""
        self.state.chat_history.append({"role": "user", "text": message})
        if self.history_manager:
            try:
                self.history_manager.save_chat_message("user", message)
            except Exception:
                pass
        self.chat_panel.refresh_view(self.state)

        if not self._claude_client:
            self._add_chat_response("Claude client not available.")
            return

        # Snapshot context for background thread
        msg_lower = message.lower()
        is_color_grade = any(
            p in msg_lower
            for p in ["colour grade", "color grade", "grade portfolio", "grade stocks", "grade my", "grade the"]
        )
        self.statusBar().showMessage("AI thinking...", 10000)
        self._run_background(
            lambda: self._do_chat(message),
            lambda response: self._on_chat_result(response, is_color_grade),
        )

    def _do_chat(self, message: str) -> str:
        """Background: call Claude with full context."""
        memory_summary = ""
        if self.history_manager:
            try:
                memory_summary = self.history_manager.get_memory_summary()
            except Exception:
                pass
        return self._claude_client.chat_with_context(
            user_message=message,
            positions=self.state.positions,
            signals=self.state.signals,
            news_data=self.state.news_sentiment,
            account_info=self.state.account_info,
            chat_history=self.state.chat_history,
            protected_tickers=self.state.protected_tickers,
            regime=self.state.current_regime,
            regime_confidence=self.state.regime_confidence,
            consensus_data=self.state.consensus_data,
            meta_ensemble_data=self.state.meta_ensemble_data,
            memory_summary=memory_summary,
            live_data=self.state.live_data,
        )

    def _on_chat_result(self, response: str, is_color_grade: bool) -> None:
        """Main thread: add response, parse color grades if applicable."""
        self.statusBar().showMessage("", 0)
        self._add_chat_response(response)
        if is_color_grade and response:
            self._parse_color_grades(response)

    def _parse_color_grades(self, response: str) -> None:
        """Parse AI response for per-ticker colour grades (GREEN/RED/ORANGE)."""
        import re
        grades: dict[str, str] = {}
        pattern = re.compile(
            r'\*{0,2}([A-Z][A-Z0-9.]{0,9})\*{0,2}\s*[:—\-–]\s*(GREEN|RED|ORANGE)',
            re.IGNORECASE,
        )
        for match in pattern.finditer(response):
            ticker = match.group(1).upper()
            grade = match.group(2).upper()
            grades[ticker] = grade

        if grades and self.state.signals is not None and not self.state.signals.empty:
            signal_tickers = set(self.state.signals["ticker"].tolist())
            mapped: dict[str, str] = {}
            for sig_ticker in signal_tickers:
                sig_upper = sig_ticker.upper()
                if sig_upper in grades:
                    mapped[sig_ticker] = grades[sig_upper]
                else:
                    for grade_ticker, grade_val in grades.items():
                        if grade_ticker in sig_upper or sig_upper.startswith(grade_ticker):
                            mapped[sig_ticker] = grade_val
                            break
            if mapped:
                grades = mapped

        if grades:
            self.state.ai_color_grades = grades
            self.watchlist_panel.refresh_view(self.state)

    @Slot()
    def action_show_chart(self) -> None:
        ticker = self.watchlist_panel.selected_ticker()
        if ticker:
            self.chart_panel.load_chart(ticker)

    @Slot()
    def action_open_trade(self) -> None:
        ticker = self.watchlist_panel.selected_ticker()
        if not ticker:
            self.statusBar().showMessage("Select a ticker first", 3000)
            return
        from desktop.dialogs.trade import TradeDialog
        dlg = TradeDialog(ticker, self)
        if dlg.exec() and dlg.result_data:
            trade = dlg.result_data
            self.statusBar().showMessage(
                f"Submitting: {trade['side']} {trade['quantity']} {trade['ticker']}...", 10000,
            )
            self._run_background(
                lambda: self.broker_service.submit_order(
                    ticker=trade["ticker"],
                    side=trade["side"].lower(),
                    quantity=trade["quantity"],
                    order_type=trade["order_type"],
                    limit_price=trade.get("price") if trade["order_type"] in ("limit", "stop_limit") else None,
                    stop_price=trade.get("price") if trade["order_type"] in ("stop", "stop_limit") else None,
                ),
                self._on_trade_result,
            )

    def _on_trade_result(self, result: Dict[str, Any]) -> None:
        self.state.recent_orders.append(result)
        self.orders_panel.refresh_view(self.state)
        self.statusBar().showMessage("Order submitted", 5000)
        self.action_refresh_data()

    @Slot()
    def action_add_ticker(self) -> None:
        from desktop.dialogs.add_ticker import AddTickerDialog
        dlg = AddTickerDialog(self)
        if dlg.exec() and dlg.ticker:
            watchlist_name = self.state.active_watchlist
            wl = self.config.get("watchlists", {}).get(watchlist_name, [])
            if dlg.ticker not in wl:
                wl.append(dlg.ticker)
                self._save_config_key(f"watchlists.{watchlist_name}", wl)
                self.statusBar().showMessage(f"Added {dlg.ticker}", 3000)
                self.action_refresh_data(force_signals=True)

    @Slot()
    def action_remove_ticker(self) -> None:
        ticker = self.watchlist_panel.selected_ticker()
        if not ticker:
            return
        watchlist_name = self.state.active_watchlist
        wl = self.config.get("watchlists", {}).get(watchlist_name, [])
        if ticker in wl:
            wl.remove(ticker)
            self._save_config_key(f"watchlists.{watchlist_name}", wl)
            self.statusBar().showMessage(f"Removed {ticker}", 3000)
            self.action_refresh_data(force_signals=True)

    @Slot()
    def action_search_ticker(self) -> None:
        from desktop.dialogs.search_ticker import SearchTickerDialog
        dlg = SearchTickerDialog(self)
        self._search_dialog = dlg  # prevent GC

        def do_search(query: str) -> None:
            self._run_background(
                lambda: self._claude_client.search_tickers(query) if self._claude_client else [],
                lambda results: dlg.populate_results(results) if dlg.isVisible() else None,
            )

        dlg.set_search_callback(do_search)
        if dlg.exec() and dlg.selected_ticker:
            self._add_ticker_to_watchlist(dlg.selected_ticker)
        self._search_dialog = None

    @Slot()
    def action_ai_recommend(self) -> None:
        from desktop.dialogs.ai_recommend import AiRecommendDialog
        dlg = AiRecommendDialog(self)
        self._recommend_dialog = dlg  # prevent GC

        def do_recommend(category: str) -> None:
            tickers = self._get_active_tickers()
            self._run_background(
                lambda: self._claude_client.recommend_tickers(tickers, category=category, count=5) if self._claude_client else [],
                lambda results: dlg.populate_results(results) if dlg.isVisible() else None,
            )

        dlg.set_request_callback(do_recommend)
        if dlg.exec() and dlg.selected_tickers:
            for t in dlg.selected_tickers:
                self._add_ticker_to_watchlist(t)
        self._recommend_dialog = None

    def _get_active_tickers(self) -> List[str]:
        """Get all tickers from the active asset class's watchlists."""
        asset = self.state.active_asset_class
        tickers: set[str] = set()
        if asset == "stocks":
            for wl in self.config.get("watchlists", {}).values():
                tickers.update(wl)
        else:
            for wl in self.config.get(asset, {}).get("watchlists", {}).values():
                tickers.update(wl)
        for pos in self.state.positions:
            t = pos.get("ticker")
            if t:
                tickers.add(t)
        return sorted(tickers)

    def _add_ticker_to_watchlist(self, ticker: str) -> None:
        """Add a ticker to the active watchlist and refresh."""
        ticker = ticker.upper().strip()
        if not ticker:
            return
        asset = self.state.active_asset_class
        if asset == "stocks":
            watchlists = self.config.get("watchlists", {})
        else:
            watchlists = self.config.get(asset, {}).get("watchlists", {})
        active = self.state.active_watchlist
        if active in watchlists:
            if ticker not in watchlists[active]:
                watchlists[active].append(ticker)
                self._save_config()
                self.ai_service._config_cache = None
                if self.news_agent:
                    self.news_agent.update_tickers(self._get_active_tickers())
                self.statusBar().showMessage(f"Added {ticker}", 3000)
                self._refresh_all_panels()

    @Slot()
    def action_ai_optimise(self) -> None:
        self._add_chat_response("[AI OPTIMIZER] Analyzing recent performance to tune algorithm weights...")
        self.statusBar().showMessage("AI optimise running...", 30000)
        self._run_background(self._do_ai_optimise, self._on_optimise_result)

    def _do_ai_optimise(self) -> Dict[str, Any]:
        """Background: gather history, ask Claude, return changes."""
        history_lines = []
        if self.history_manager:
            dates = self.history_manager.get_recent_dates(7)
            for d in dates:
                snap = self.history_manager.get_snapshot(d)
                if snap:
                    history_lines.append(
                        f"  {snap['date']}: equity=${snap['equity']:.2f}, pnl=${snap['pnl']:.2f}, mode={snap['mode']}"
                    )

        ai_cfg = self.config.get("ai", {})
        strat_cfg = self.config.get("strategy", {})
        tf_cfg = self.config.get("timeframes", {}).get("weights", {})
        risk_cfg = self.config.get("risk", {})
        current = {
            "sklearn_weight": ai_cfg.get("sklearn_weight", 0.5),
            "ai_weight": ai_cfg.get("ai_weight", 0.3),
            "news_weight": ai_cfg.get("news_weight", 0.2),
            "threshold_buy": strat_cfg.get("threshold_buy", 0.55),
            "threshold_sell": strat_cfg.get("threshold_sell", 0.45),
            "tf_weight_1d": float(tf_cfg.get("1", 0.7)),
            "tf_weight_5d": float(tf_cfg.get("5", 0.2)),
            "tf_weight_20d": float(tf_cfg.get("20", 0.1)),
            "kelly_fraction_cap": risk_cfg.get("kelly_fraction_cap", 0.35),
            "atr_stop_multiplier": risk_cfg.get("atr_stop_multiplier", 1.5),
        }
        history_text = "\n".join(history_lines) if history_lines else "  No history yet (first run)"

        if not self._claude_client:
            return {"error": "Claude client not available"}

        prompt = (
            "You are a quant advisor tuning a DAY TRADING algorithm "
            "that favours medium-to-high risk, volatile instruments.\n\n"
            f"Recent performance:\n{history_text}\n\n"
            f"Current config:\n{json.dumps(current, indent=2)}\n\n"
            "Rules:\n"
            "- sklearn_weight + ai_weight + news_weight should sum to ~1.0\n"
            "- threshold_buy: 0.50-0.70 (lower = more aggressive)\n"
            "- threshold_sell: 0.30-0.50 (higher = quicker exits)\n"
            "- tf_weight_1d + tf_weight_5d + tf_weight_20d should sum to ~1.0\n"
            "  (day trading should heavily favour 1d)\n"
            "- kelly_fraction_cap: 0.20-0.50 (higher = more aggressive sizing)\n"
            "- atr_stop_multiplier: 1.0-3.0 (lower = tighter stops)\n"
            "- Only change values if data supports it. Keep current if unsure.\n\n"
            "Respond strictly as JSON:\n"
            '{"changes": {"sklearn_weight": 0.5, "ai_weight": 0.3, "news_weight": 0.2, '
            '"threshold_buy": 0.55, "threshold_sell": 0.45, '
            '"tf_weight_1d": 0.7, "tf_weight_5d": 0.2, "tf_weight_20d": 0.1, '
            '"kelly_fraction_cap": 0.35, "atr_stop_multiplier": 1.5}, '
            '"explanation": "one paragraph explaining why these changes"}'
        )

        text = self._claude_client._call(prompt, task_type="medium")
        if not text:
            return {"error": "Could not reach AI"}

        obj = self._claude_client._parse_json(text)
        changes = obj.get("changes", {})
        explanation = obj.get("explanation", "No explanation provided.")
        return {"changes": changes, "explanation": explanation, "current": current}

    def _on_optimise_result(self, result: Dict[str, Any]) -> None:
        """Main thread: apply config changes from optimizer."""
        self.statusBar().showMessage("", 0)
        if "error" in result:
            self._add_chat_response(f"[AI OPTIMIZER] {result['error']}")
            return

        changes = result.get("changes", {})
        explanation = result.get("explanation", "")
        current = result.get("current", {})

        if not changes:
            self._add_chat_response(f"[AI OPTIMIZER] No changes recommended.\n{explanation}")
            return

        diff_lines = []
        for key, new_val in changes.items():
            old_val = current.get(key)
            if old_val is not None and float(old_val) != float(new_val):
                diff_lines.append(f"  {key}: {old_val} -> {new_val}")

        if not diff_lines:
            self._add_chat_response(f"[AI OPTIMIZER] Current weights are optimal. No changes.\n{explanation}")
            return

        self._add_chat_response(
            "[AI OPTIMIZER] Applying changes:\n" + "\n".join(diff_lines) + f"\n\nReason: {explanation}"
        )

        # Apply changes
        ai_cfg = self.config.get("ai", {})
        strat_cfg = self.config.get("strategy", {})
        risk_cfg = self.config.get("risk", {})

        for key in ("sklearn_weight", "ai_weight", "news_weight"):
            if key in changes:
                val = max(0.0, min(1.0, float(changes[key])))
                old = ai_cfg.get(key, 0)
                ai_cfg[key] = val
                if self.history_manager:
                    self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])

        for key in ("threshold_buy", "threshold_sell"):
            if key in changes:
                val = float(changes[key])
                val = max(0.50, min(0.70, val)) if key == "threshold_buy" else max(0.30, min(0.50, val))
                old = strat_cfg.get(key, 0)
                strat_cfg[key] = val
                if self.history_manager:
                    self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])

        tf_weights = self.config.get("timeframes", {}).get("weights", {})
        tf_keys = {"tf_weight_1d": "1", "tf_weight_5d": "5", "tf_weight_20d": "20"}
        for opt_key, cfg_key in tf_keys.items():
            if opt_key in changes:
                val = max(0.05, min(0.90, float(changes[opt_key])))
                old = tf_weights.get(cfg_key, 0)
                tf_weights[cfg_key] = val
                if self.history_manager:
                    self.history_manager.log_config_change("AI_OPTIMIZER", opt_key, str(old), str(val), explanation[:200])
        self.config.setdefault("timeframes", {})["weights"] = tf_weights

        risk_bounds = {"kelly_fraction_cap": (0.20, 0.50), "atr_stop_multiplier": (1.0, 3.0)}
        for key, (lo, hi) in risk_bounds.items():
            if key in changes:
                val = max(lo, min(hi, float(changes[key])))
                old = risk_cfg.get(key, 0)
                risk_cfg[key] = val
                if self.history_manager:
                    self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])
        self.config["risk"] = risk_cfg
        self.config["ai"] = ai_cfg
        self.config["strategy"] = strat_cfg
        self._save_config()
        self.ai_service._config_cache = None

        self._add_chat_response("[AI OPTIMIZER] Changes applied and saved to config.json.")

    @Slot()
    def action_show_history(self) -> None:
        from desktop.dialogs.history import HistoryDialog
        dlg = HistoryDialog(self)
        self._history_dialog = dlg

        def load_history() -> Dict[str, List[Any]]:
            return {
                "orders": self.broker_service.get_order_history(limit=50).get("items", []),
                "dividends": self.broker_service.get_dividends(limit=50).get("items", []),
                "transactions": self.broker_service.get_transactions(limit=50).get("items", []),
            }

        def on_loaded(data: Dict[str, List[Any]]) -> None:
            self.state.order_history = data["orders"]
            self.state.dividend_history = data["dividends"]
            self.state.transaction_history = data["transactions"]
            if dlg.isVisible():
                dlg.populate_orders(data["orders"])
                dlg.populate_dividends(data["dividends"])
                dlg.populate_transactions(data["transactions"])

        self._run_background(load_history, on_loaded)
        dlg.exec()
        self._history_dialog = None

    @Slot()
    def action_show_pies(self) -> None:
        from desktop.dialogs.pies import PiesDialog
        dlg = PiesDialog(self)
        self._pies_dialog = dlg

        def on_loaded(pies: List[Dict[str, Any]]) -> None:
            self.state.pies = pies
            if dlg.isVisible():
                dlg.populate_pies(pies)

        self._run_background(
            lambda: self.broker_service.get_pies(),
            on_loaded,
        )
        dlg.exec()
        self._pies_dialog = None

    @Slot()
    def action_show_instruments(self) -> None:
        from desktop.dialogs.instruments import InstrumentsDialog
        dlg = InstrumentsDialog(self)
        self._instruments_dialog = dlg

        def on_loaded(instruments: List[Dict[str, Any]]) -> None:
            if dlg.isVisible():
                dlg.populate(instruments)

        self._run_background(
            lambda: self.broker_service.get_instruments(),
            on_loaded,
        )
        dlg.exec()
        self._instruments_dialog = None

    @Slot()
    def action_toggle_protect(self) -> None:
        ticker = self.watchlist_panel.selected_ticker()
        if not ticker:
            return
        if ticker in self.state.protected_tickers:
            self.state.protected_tickers.discard(ticker)
            self.statusBar().showMessage(f"Unlocked {ticker}", 3000)
        else:
            self.state.protected_tickers.add(ticker)
            self.statusBar().showMessage(f"Locked {ticker}", 3000)
        self._save_config_key(
            "protected_tickers", list(self.state.protected_tickers),
        )
        self.watchlist_panel.refresh_view(self.state)

    # ══════════════════════════════════════════════════════════════════
    #  Background tasks (stubs -- implemented in later phases)
    # ══════════════════════════════════════════════════════════════════

    def _ai_market_scan(self) -> None:
        """Scan cached signals for strong buy/sell/risk alerts."""
        if self.state.signals is None or self.state.signals.empty:
            return
        alerts: List[str] = []
        for _, row in self.state.signals.iterrows():
            ticker = row.get("ticker", "")
            prob = float(row.get("prob_up", 0.5))
            signal = str(row.get("signal", ""))
            if prob >= 0.7 and "BUY" in signal.upper():
                alerts.append(f"  STRONG BUY: {ticker} (prob={prob:.2f})")
            elif prob <= 0.3 and "SELL" in signal.upper():
                alerts.append(f"  STRONG SELL: {ticker} (prob={prob:.2f})")

        # Check for risky positions
        for pos in self.state.positions:
            pnl = float(pos.get("pnl", pos.get("unrealised_pnl", 0)))
            if pnl < -50:
                alerts.append(f"  RISK: {pos.get('ticker', '?')} unrealised PnL ${pnl:.2f}")

        if alerts:
            self._add_chat_response("[MARKET SCAN]\n" + "\n".join(alerts))

    def _auto_optimize(self) -> None:
        """Periodic self-optimization — skip if insufficient data."""
        tracker = getattr(self.ai_service, "_accuracy_tracker", None)
        if tracker is None:
            return
        try:
            stats = tracker.get_rolling_accuracy("final", window_days=14)
            if stats <= 0.0:
                return
        except Exception:
            return
        self.action_ai_optimise()

    def _daily_stock_discovery(self) -> None:
        """Ask AI for 5 new volatile ticker suggestions."""
        if not self._claude_client:
            return
        current = self._get_active_tickers()

        def do_discover() -> List[str]:
            prompt = (
                "You are a stock screener for day trading. "
                f"Current watchlist: {', '.join(current[:20])}\n\n"
                "Suggest 5 new high-volatility US stocks NOT in the watchlist. "
                "Focus on stocks with high average daily volume and recent price movement.\n"
                "Respond strictly as JSON: {\"tickers\": [\"TICKER1\", \"TICKER2\", ...]}"
            )
            text = self._claude_client._call(prompt, task_type="simple")
            if text:
                obj = self._claude_client._parse_json(text)
                return obj.get("tickers", [])
            return []

        def on_discovered(tickers: List[str]) -> None:
            added = []
            for t in tickers:
                t = t.upper().strip()
                if t and t not in current:
                    self._add_ticker_to_watchlist(t)
                    added.append(t)
            if added:
                self._add_chat_response(f"[DAILY DISCOVERY] Added {', '.join(added)} to watchlist.")

        self._run_background(do_discover, on_discovered)

    # ══════════════════════════════════════════════════════════════════
    #  Config Helpers
    # ══════════════════════════════════════════════════════════════════

    def _prompt_first_run_import(self) -> None:
        """On first launch with an empty default config, ask user to import."""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Welcome to StockMarketAI",
            "No config.json was found, so a default was created.\n\n"
            "Would you like to import your config now?\n"
            "(You can also do this later via File > Import Config)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._import_config()

    def _save_config(self) -> None:
        """Save the full config dict to config.json."""
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

    def _import_config(self) -> None:
        """Import a config.json file via file picker."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getOpenFileName(self, "Import Config", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                new_config = json.load(f)
            if "watchlists" not in new_config:
                QMessageBox.warning(self, "Invalid Config", "Config must contain 'watchlists' key.")
                return
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=2)
            self.config = new_config
            self.state = init_state(self.config)
            self.ai_service._config_cache = None
            self._refresh_all_panels()
            self.statusBar().showMessage("Config imported successfully", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _export_config(self) -> None:
        """Export current config.json via file picker."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Config", "config.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            import shutil
            shutil.copy2(self.config_path, path)
            self.statusBar().showMessage(f"Config exported to {path}", 5000)
        except Exception as e:
            self.statusBar().showMessage(f"Export error: {e}", 5000)

    def _save_config_key(self, dotpath: str, value: Any) -> None:
        """Update a single key in config.json using dot notation."""
        parts = dotpath.split(".")
        cfg = load_config(self.config_path)
        target = cfg
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        self.config = cfg

    # ══════════════════════════════════════════════════════════════════
    #  Background Task Helper
    # ══════════════════════════════════════════════════════════════════

    def _run_background(
        self,
        fn: Any,
        on_result: Any,
        on_error: Optional[Any] = None,
    ) -> BackgroundTask:
        """Spawn a BackgroundTask, wire signals, prevent GC."""
        worker = BackgroundTask(fn)
        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error or self._on_background_error)
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()
        return worker

    def _cleanup_worker(self, worker: BackgroundTask) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass

    def _on_background_error(self, error_msg: str) -> None:
        self.statusBar().showMessage(f"Error: {error_msg}", 5000)

    def _add_chat_response(self, response: str) -> None:
        """Append AI response to chat history, persist, refresh panel."""
        self.state.chat_history.append({"role": "ai", "text": response})
        if self.history_manager:
            try:
                self.history_manager.save_chat_message("ai", response)
            except Exception:
                pass
        self.chat_panel.refresh_view(self.state)

    # ══════════════════════════════════════════════════════════════════
    #  Cleanup
    # ══════════════════════════════════════════════════════════════════

    def closeEvent(self, event: Any) -> None:
        """Stop timers and background services before closing."""
        for timer in [
            self._refresh_timer,
            self._scanner_timer,
            self._optimize_timer,
            self._discovery_timer,
            self._pipeline_poll_timer,
        ]:
            timer.stop()

        if self.news_agent:
            try:
                self.news_agent.stop()
            except Exception:
                pass

        if self._refresh_worker and self._refresh_worker.isRunning():
            self._refresh_worker.quit()
            self._refresh_worker.wait(2000)

        super().closeEvent(event)
