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

from desktop.state import init_state, load_config
from desktop.panels.settings import SettingsPanel
from desktop.panels.watchlist import WatchlistPanel
from desktop.panels.positions import PositionsPanel
from desktop.panels.orders import OrdersPanel
from desktop.panels.chat import ChatPanel
from desktop.panels.news import NewsPanel
from desktop.panels.chart import ChartPanel
from desktop.panels.pipeline import PipelinePanel
from desktop.workers import RefreshWorker


class MainWindow(QMainWindow):
    """Bloomberg-style trading terminal window."""

    def __init__(self, config_path: Path | str = "config.json") -> None:
        super().__init__()
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = load_config(self.config_path)
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

        # Active worker reference (prevent GC)
        self._refresh_worker: Optional[RefreshWorker] = None

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

    def _restore_state(self) -> None:
        """Load chat history and trigger initial data refresh."""
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
        self.statusBar().showMessage("AI suggesting ticker...", 3000)

    @Slot()
    def action_generate_insights(self) -> None:
        self.statusBar().showMessage("Generating AI insights...", 3000)

    @Slot()
    def action_refresh_news(self) -> None:
        self.statusBar().showMessage("Refreshing news...", 3000)

    @Slot()
    def action_focus_chat(self) -> None:
        self.chat_panel.focus_input()

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
            self.statusBar().showMessage(
                f"Order: {dlg.result_data['side']} {dlg.result_data['quantity']} "
                f"{dlg.result_data['ticker']}", 5000,
            )

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
        if dlg.exec() and dlg.selected_ticker:
            watchlist_name = self.state.active_watchlist
            wl = self.config.get("watchlists", {}).get(watchlist_name, [])
            if dlg.selected_ticker not in wl:
                wl.append(dlg.selected_ticker)
                self._save_config_key(f"watchlists.{watchlist_name}", wl)
                self.statusBar().showMessage(f"Added {dlg.selected_ticker}", 3000)

    @Slot()
    def action_ai_recommend(self) -> None:
        from desktop.dialogs.ai_recommend import AiRecommendDialog
        dlg = AiRecommendDialog(self)
        if dlg.exec() and dlg.selected_tickers:
            watchlist_name = self.state.active_watchlist
            wl = self.config.get("watchlists", {}).get(watchlist_name, [])
            added = []
            for t in dlg.selected_tickers:
                if t not in wl:
                    wl.append(t)
                    added.append(t)
            if added:
                self._save_config_key(f"watchlists.{watchlist_name}", wl)
                self.statusBar().showMessage(f"Added {', '.join(added)}", 3000)

    @Slot()
    def action_ai_optimise(self) -> None:
        self.statusBar().showMessage("AI optimise running...", 3000)

    @Slot()
    def action_show_history(self) -> None:
        from desktop.dialogs.history import HistoryDialog
        dlg = HistoryDialog(self)
        # Populate with whatever history we have in state
        if self.state.order_history:
            dlg.populate_orders(self.state.order_history)
        if self.state.dividend_history:
            dlg.populate_dividends(self.state.dividend_history)
        if self.state.transaction_history:
            dlg.populate_transactions(self.state.transaction_history)
        dlg.exec()

    @Slot()
    def action_show_pies(self) -> None:
        from desktop.dialogs.pies import PiesDialog
        dlg = PiesDialog(self)
        if self.state.pies:
            dlg.populate_pies(self.state.pies)
        dlg.exec()

    @Slot()
    def action_show_instruments(self) -> None:
        from desktop.dialogs.instruments import InstrumentsDialog
        dlg = InstrumentsDialog(self)
        dlg.exec()

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
        pass  # Phase 9

    def _auto_optimize(self) -> None:
        pass  # Phase 9

    def _daily_stock_discovery(self) -> None:
        pass  # Phase 9

    # ══════════════════════════════════════════════════════════════════
    #  Config Helpers
    # ══════════════════════════════════════════════════════════════════

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
