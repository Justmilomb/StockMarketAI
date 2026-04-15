"""Main window for the Blank desktop application.

Implements the Bloomberg-style dockable layout, wires up the broker
and chat services, and manages background timers and keyboard
shortcuts.

Phase 3 removed the entire ML pipeline from this file:
* ``AiService`` / ``AutoEngine`` / ``PipelineTracker`` /
  ``AccuracyTracker`` imports and wiring — gone.
* Two-phase refresh (``_fetch_broker_data`` then AI signal pipeline)
  — gone; refresh is now a single broker fetch.
* TRADE_INSTRUCTIONS regex execution, colour grading, auto-rotation,
  auto-optimise, stock discovery, market scanner — all gone.
* ``RefreshWorker`` — gone; only ``BackgroundTask`` remains.
* ``PipelinePanel`` — replaced by ``AgentLogPanel`` (agent is off
  by default; Phase 4 wires in the real agent runner).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
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
from desktop.panels.agent_log import AgentLogPanel
from desktop.panels.exchanges import ExchangesPanel
from desktop.panels.update_banner import UpdateBanner
from desktop.panels.mandatory_update_overlay import MandatoryUpdateOverlay
from desktop.widgets.mode_banner import ModeBanner
from desktop.widgets.mode_watermark import ModeWatermark
from desktop.dialogs.about import AboutDialog
from desktop.dialogs.schedule_update import ScheduleUpdateDialog
from desktop.update_service import UpdateService
from desktop.workers import BackgroundTask

# Phase 4: Claude agent pool owns the supervisor + chat-worker fleet.
# AgentRunner itself is still used, but only via AgentPool so paper
# broker state and the wake cadence are shared across agents.
from core.agent.pool import AgentPool


class MainWindow(QMainWindow):
    """Bloomberg-style trading terminal window."""

    def __init__(
        self,
        config_path: Path | str = "config.json",
        initial_asset: str = "stocks",
        forced_paper_mode: bool = False,
    ) -> None:
        super().__init__()
        # When True this window is permanently locked to paper trading —
        # it is its own isolated universe with no live broker access.
        self._forced_paper_mode: bool = forced_paper_mode

        self.config_path = resolve_config_path(config_path)
        self.config: Dict[str, Any] = load_config(self.config_path)
        self.state = init_state(self.config)
        self.state.active_asset_class = initial_asset

        # Services
        from broker_service import BrokerService
        from news_agent import NewsAgent

        if forced_paper_mode:
            # Paper window gets its own isolated broker that always uses
            # PaperBroker for stocks — never touches the live T212 API.
            from paper_broker import PaperBroker
            paper_cfg = dict(self.config)
            paper_cfg["broker"] = {
                **(self.config.get("broker", {}) or {}),
                "type": "log",
            }
            self.broker_service = BrokerService(config=paper_cfg)
            paper_broker_cfg = self.config.get("paper_broker") or {}
            # Always start fresh — delete any previous paper state so
            # every paper session opens at £100.
            state_path = Path(paper_broker_cfg.get("state_path", "data/paper_state.json"))
            if state_path.exists():
                state_path.unlink()
            self.broker_service.register_broker(
                "stocks",
                PaperBroker(
                    state_path=state_path,
                    audit_path=Path(paper_broker_cfg.get("audit_path", "logs/paper_orders.jsonl")),
                    starting_cash=float(paper_broker_cfg.get("starting_cash", 100.0)),
                ),
            )
            self.state.agent_paper_mode = True
            self.state.broker_is_live = False
        else:
            self.broker_service = BrokerService(self.config)

        self._claude_client: Optional[Any] = None
        self.news_agent: Optional[NewsAgent] = None
        self.history_manager: Optional[Any] = None

        try:
            from claude_client import ClaudeClient, ClaudeConfig
            claude_cfg_raw = self.config.get("claude", {})
            ccfg = ClaudeConfig(
                model=claude_cfg_raw.get("model", "claude-sonnet-4-20250514"),
                model_complex=claude_cfg_raw.get("model_complex", "claude-opus-4-6"),
                model_medium=claude_cfg_raw.get("model_medium", "claude-sonnet-4-20250514"),
                model_simple=claude_cfg_raw.get("model_simple", "claude-haiku-4-5-20251001"),
            )
            self._claude_client = ClaudeClient(ccfg)

            from database import HistoryManager
            from desktop.paths import db_path as _user_db_path
            _base_db = _user_db_path()
            _hist_db = (
                _base_db.parent / "paper_chat_history.db"
                if self._forced_paper_mode
                else _base_db
            )
            self.history_manager = HistoryManager(db_path=str(_hist_db))
            self.state.history_manager = self.history_manager

            news_interval = self.config.get("news", {}).get(
                "refresh_interval_minutes", 5,
            )
            news_claude = ClaudeClient(ccfg)
            self.news_agent = NewsAgent(
                news_claude, refresh_interval_minutes=news_interval,
                config=self.config,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Could not init Claude/news: %s", e)

        self.state.broker_is_live = self.broker_service.is_live

        self._active_workers: List[BackgroundTask] = []

        # Phase 4 agent pool — supervisor + chat worker fleet.
        # The pool is built eagerly (cheap), but the supervisor runner
        # inside it is only created lazily when Start Agent is clicked.
        self.agent_pool: Optional[AgentPool] = None
        # Live windows are always live, paper windows are always paper —
        # mode is window-scoped, not config-scoped. See _open_paper_window.
        if not self._forced_paper_mode:
            self.state.agent_paper_mode = False

        # Chat worker bookkeeping — we track active worker IDs so we
        # can show "AI thinking (2)" when many workers are alive and
        # route their incremental text back into the chat panel.
        self._chat_worker_ids: set[str] = set()
        self._chat_worker_buffers: Dict[str, List[str]] = {}

        # Buffer accumulates text_chunk blocks across one iteration; flushed
        # to chat at iteration end so the user sees the full agent message.
        self._agent_text_buffer: List[str] = []

        # Phase 5 scraper runner — refreshes the news/social cache in
        # the background. Started after _build_ui so the watchlist
        # provider can safely read from panels that are already alive.
        self.scraper_runner: Optional[Any] = None
        self._start_scraper_runner()

        self._build_ui()
        self._setup_shortcuts()
        self._setup_timers()
        self._restore_state()
        # Paper windows skip update management — the live window owns
        # the session's single UpdateService so we don't end up with
        # two poll loops, two banners, or duplicate install flows.
        if not self._forced_paper_mode:
            self._init_update_service()

    def _build_ui(self) -> None:
        """Create dockable panel layout with Bloomberg-style arrangement."""
        if self._forced_paper_mode:
            self.setWindowTitle("blank — Paper Trading")
        else:
            self.setWindowTitle("blank")
        self.setMinimumSize(1280, 720)
        self.setDockNestingEnabled(True)

        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction("Main Menu  (M)", self.action_main_menu)
        file_menu.addSeparator()
        file_menu.addAction("Quit  (Q)", self.close)

        self._view_menu = menu_bar.addMenu("&View")

        agent_menu = menu_bar.addMenu("&Agent")
        self._agent_start_action = agent_menu.addAction(
            "Start Agent", self._on_agent_start,
        )
        self._agent_stop_action = agent_menu.addAction(
            "Stop Agent", self._on_agent_stop,
        )
        self._agent_stop_action.setEnabled(False)
        agent_menu.addSeparator()
        self._agent_kill_action = agent_menu.addAction(
            "Kill Switch", self._on_agent_kill,
        )
        self._agent_kill_action.setEnabled(False)
        agent_menu.addSeparator()
        if self._forced_paper_mode:
            # Paper window is permanently paper — show a disabled label
            # so the user knows there's no toggle here.
            paper_label = agent_menu.addAction("Paper Mode (locked)")
            paper_label.setEnabled(False)
        else:
            # Live windows have no paper toggle — paper trading is only
            # reachable via a dedicated paper window so the two modes
            # can never share state.
            agent_menu.addAction(
                "Open Paper Trading Window", self._open_paper_window,
            )

        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        asset_str = self.state.active_asset_class.upper()
        self._header_label = QLabel(
            f" blank [{mode_str}] | {asset_str} | CERTIFIED RANDOM ",
        )
        self._header_label.setStyleSheet(
            "color: #ff8c00; font-weight: bold; font-size: 11px; "
            "background: transparent; padding: 2px 8px;",
        )
        menu_bar.setCornerWidget(self._header_label, Qt.TopRightCorner)

        # Central widget wraps the update banner + mode banner + chart
        # panel. Mode banner is loud and pinned above the chart so
        # paper/live is *unmissable*. UpdateBanner stays hidden unless
        # the service pushes a manifest.
        self.chart_panel = ChartPanel(self.state)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.update_banner = UpdateBanner(self)
        # Floating always-on-top overlay used only for mandatory updates.
        # Not in the central layout — it's a detached top-level window
        # parented to MainWindow so it closes with the app.
        self.mandatory_overlay = MandatoryUpdateOverlay(self)
        self.mode_banner = ModeBanner(self)
        self.mode_banner.set_mode(self.state.agent_paper_mode)
        # Mode banner is read-only — paper/live is window-scoped, so
        # there is nothing to toggle from the banner.
        central_layout.addWidget(self.update_banner)
        central_layout.addWidget(self.mode_banner)
        central_layout.addWidget(self.chart_panel, 1)
        self.setCentralWidget(central)

        # Faint rotated watermark sits *over* the chart panel so the
        # word PAPER / LIVE bleeds through even if the banner is
        # hidden. Transparent to mouse events.
        self.mode_watermark = ModeWatermark(self.chart_panel)
        self.mode_watermark.set_mode(self.state.agent_paper_mode)
        self.mode_watermark.resize(self.chart_panel.size())
        self.mode_watermark.raise_()
        self.mode_watermark.show()

        self.settings_panel = SettingsPanel(self.state)
        self.chat_panel = ChatPanel(self.state)
        self.agent_log_panel = AgentLogPanel(self.state)
        self.watchlist_panel = WatchlistPanel(self.state)
        self.positions_panel = PositionsPanel(self.state)
        self.exchanges_panel = ExchangesPanel(self.state)
        self.orders_panel = OrdersPanel(self.state)
        self.news_panel = NewsPanel(self.state)
        ai_ok = self._claude_client is not None and getattr(self._claude_client, "available", False)
        self.news_panel.set_ai_available(ai_ok)

        from desktop.panels.polymarket_markets import PolymarketPanel
        self._poly_panel = PolymarketPanel(self.state)

        self._watchlist_dock = self._make_dock("WATCHLIST", self.watchlist_panel)
        self._settings_dock = self._make_dock("SETTINGS", self.settings_panel)
        self._positions_dock = self._make_dock("POSITIONS", self.positions_panel)
        self._exchanges_dock = self._make_dock("MARKETS", self.exchanges_panel)
        self._orders_dock = self._make_dock("ORDERS", self.orders_panel)
        self._chat_dock = self._make_dock("CHAT", self.chat_panel)
        self._news_dock = self._make_dock("NEWS", self.news_panel)
        self._agent_dock = self._make_dock("AGENT", self.agent_log_panel)
        self._poly_dock = self._make_dock("POLYMARKET", self._poly_panel)

        self.addDockWidget(Qt.TopDockWidgetArea, self._watchlist_dock)
        self.addDockWidget(Qt.TopDockWidgetArea, self._poly_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._settings_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._positions_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._exchanges_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._chat_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._news_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._orders_dock)
        self.splitDockWidget(self._orders_dock, self._agent_dock, Qt.Horizontal)

        self.resizeDocks(
            [self._settings_dock, self._chat_dock], [240, 300], Qt.Horizontal,
        )
        self.resizeDocks([self._watchlist_dock], [220], Qt.Vertical)
        self.resizeDocks([self._orders_dock], [140], Qt.Vertical)

        self._apply_dock_layout()

        self._all_docks = {
            "stocks": [
                self._watchlist_dock, self._positions_dock,
                self._exchanges_dock, self._orders_dock, self._news_dock,
            ],
            "polymarket": [self._poly_dock],
            "shared": [
                self._settings_dock, self._chat_dock, self._agent_dock,
            ],
        }
        self._rebuild_view_menu()

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel(
            "  ? Help | B About | R Refresh | M Menu | A Mode | C Chat | G Chart | Q Quit",
        )
        status.addPermanentWidget(self._status_label, 1)

        ai_ok = self._claude_client is not None and getattr(self._claude_client, "available", False)
        self._ai_status = QLabel("AI: OK" if ai_ok else "AI: OFF")
        self._ai_status.setStyleSheet(
            f"color: {'#00ff00' if ai_ok else '#ff0000'}; font-weight: bold; padding: 0 8px;",
        )
        status.addPermanentWidget(self._ai_status)

        broker_live = getattr(self.broker_service, "is_live", False)
        self._broker_status = QLabel("LIVE" if broker_live else "PAPER")
        self._broker_status.setStyleSheet(
            f"color: {'#00ff00' if broker_live else '#ffd700'}; font-weight: bold; padding: 0 8px;",
        )
        status.addPermanentWidget(self._broker_status)

        self._server_status = QLabel("SRV: --")
        self._server_status.setStyleSheet("color: #888888; font-weight: bold; padding: 0 8px;")
        status.addPermanentWidget(self._server_status)
        self._check_server_connectivity()

        # Propagate the initial paper/live tint across every dock +
        # status bar + watermark. Idempotent — safe to re-call after
        # any mode flip.
        self._apply_mode_tint(self.state.agent_paper_mode)

    def _apply_mode_tint(self, paper: bool) -> None:
        """Propagate the paper/live colour to banner, docks, status.

        Gold = PAPER, red = LIVE. The tint applies a thin top border
        to every dock title so the entire chrome reads as "you are in
        mode X" even if the user has closed the banner. Idempotent:
        call it on every flip.
        """
        self.mode_banner.set_mode(paper)
        self.mode_watermark.set_mode(paper)

        stripe = "#ffd700" if paper else "#ff0000"
        title_fg = "#ffd700" if paper else "#ff5555"
        # Cache the stylesheet and push it to every dock we know
        # about. Using QSS lets Qt handle the per-dock paint.
        dock_qss = (
            "QDockWidget::title {"
            f" border-top: 2px solid {stripe};"
            " background: #000000;"
            f" color: {title_fg};"
            " font-weight: bold;"
            " padding: 4px 8px;"
            " }"
        )
        if hasattr(self, "_all_docks"):
            docks: List[QDockWidget] = []
            for group in self._all_docks.values():
                docks.extend(group)
            for dock in docks:
                dock.setStyleSheet(dock_qss)

        # Status-bar broker label picks up the mode colour too so the
        # bottom chrome doesn't look like a second source of truth.
        if hasattr(self, "_broker_status"):
            color = "#ffd700" if paper else "#ff5555"
            self._broker_status.setText("PAPER" if paper else "LIVE")
            self._broker_status.setStyleSheet(
                f"color: {color}; font-weight: bold; padding: 0 8px;",
            )

    def _check_server_connectivity(self) -> None:
        """Ping the license server in the background and update status label."""
        from desktop.license import _read_server_url
        server_url = _read_server_url()

        def _ping() -> bool:
            try:
                import requests
                resp = requests.get(f"{server_url.rstrip('/')}/api/health", timeout=30)
                return resp.status_code == 200
            except Exception:
                return False

        def _on_result(ok: bool) -> None:
            self._server_status.setText("SRV: OK" if ok else "SRV: OFF")
            self._server_status.setStyleSheet(
                f"color: {'#00ff00' if ok else '#ff0000'}; font-weight: bold; padding: 0 8px;",
            )

        self._run_background(_ping, _on_result)

    def _rebuild_view_menu(self) -> None:
        """Rebuild the View menu to only show docks for the active mode."""
        self._view_menu.clear()
        asset = self.state.active_asset_class
        mode_docks = self._all_docks.get(asset, [])
        for dock in mode_docks + self._all_docks["shared"]:
            self._view_menu.addAction(dock.toggleViewAction())

    def _make_dock(self, title: str, widget: QWidget) -> QDockWidget:
        """Create a QDockWidget wrapping the given panel."""
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            | Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea,
        )
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable,
        )
        return dock

    def _apply_dock_layout(self) -> None:
        """Switch dock layout based on active asset class."""
        asset = self.state.active_asset_class

        stocks_only = [
            self._watchlist_dock, self._positions_dock,
            self._orders_dock, self._news_dock,
        ]
        poly_only = [self._poly_dock]
        shared = [
            self._chat_dock, self._agent_dock, self._settings_dock,
        ]

        if asset == "polymarket":
            for d in stocks_only:
                d.hide()
            for d in shared + poly_only:
                d.show()
            self.addDockWidget(Qt.TopDockWidgetArea, self._poly_dock)
            self.addDockWidget(Qt.LeftDockWidgetArea, self._settings_dock)
            self.addDockWidget(Qt.RightDockWidgetArea, self._chat_dock)
            self.addDockWidget(Qt.BottomDockWidgetArea, self._agent_dock)
        else:
            for d in poly_only:
                d.hide()
            for d in shared + stocks_only:
                d.show()
            self.addDockWidget(Qt.TopDockWidgetArea, self._watchlist_dock)
            self.addDockWidget(Qt.LeftDockWidgetArea, self._settings_dock)
            self.addDockWidget(Qt.LeftDockWidgetArea, self._positions_dock)
            self.addDockWidget(Qt.RightDockWidgetArea, self._chat_dock)
            self.addDockWidget(Qt.RightDockWidgetArea, self._news_dock)
            self.addDockWidget(Qt.BottomDockWidgetArea, self._orders_dock)
            self.splitDockWidget(self._orders_dock, self._agent_dock, Qt.Horizontal)

        if hasattr(self, "_all_docks"):
            self._rebuild_view_menu()

    def _setup_shortcuts(self) -> None:
        """Register all keyboard shortcuts."""
        shortcuts = [
            ("?", self.action_show_help),
            ("Q", self.close),
            ("R", self.action_refresh_data),
            ("A", self.action_toggle_mode),
            ("W", self.action_cycle_watchlist),
            ("N", self.action_refresh_news),
            ("C", self.action_focus_chat),
            ("G", self.action_show_chart),
            ("T", self.action_open_trade),
            ("=", self.action_add_ticker),
            ("-", self.action_remove_ticker),
            ("/", self.action_search_ticker),
            ("H", self.action_show_history),
            ("P", self.action_show_pies),
            ("E", self.action_show_instruments),
            ("L", self.action_toggle_protect),
            ("B", self.action_show_about),
            ("M", self.action_main_menu),
            ("1", lambda: self._switch_asset("stocks")),
            ("2", lambda: self._switch_asset("polymarket")),
            ("3", lambda: self._switch_asset("crypto")),
        ]
        for key, slot in shortcuts:
            QShortcut(QKeySequence(key), self, slot)

    def _setup_timers(self) -> None:
        """Start all periodic background timers."""
        interval_ms = self.state.refresh_interval_seconds * 1000

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.action_refresh_data)
        self._refresh_timer.start(interval_ms)

    def _restore_state(self) -> None:
        """Load chat history, wire signals, trigger initial broker refresh."""
        self.chat_panel.message_submitted.connect(self._handle_chat_message)

        # Agent panel lifecycle buttons route into MainWindow slots so
        # the runner remains owned here.
        self.agent_log_panel.start_requested.connect(self._on_agent_start)
        self.agent_log_panel.stop_requested.connect(self._on_agent_stop)
        self.agent_log_panel.kill_requested.connect(self._on_agent_kill)

        self.watchlist_panel.table.currentCellChanged.connect(self._on_watchlist_click)
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
                self.news_agent.update_tickers(self._get_active_tickers())
                self.news_agent.start()
            except Exception:
                pass

        self._populate_placeholder_signals()

        QTimer.singleShot(100, self.action_refresh_data)

        # Auto-start the agent when the app launches in AUTO mode.
        if self.state.mode == "full_auto_limited":
            QTimer.singleShot(1500, self._on_agent_start)

    def _init_update_service(self) -> None:
        """Create the UpdateService and wire its signals to the banner.

        The service runs its own QTimer and worker thread, so all we
        need to do here is construct it, connect signals, and call
        ``start()``. No background worker wrapping — the service never
        blocks the Qt event loop because the manifest fetch is short
        and the download runs on its own QThread.
        """
        self.update_service = UpdateService(
            self,
            config=self.config,
            config_saver=self._save_config,
        )

        # Service -> banner / overlay
        self.update_service.update_available.connect(self._on_update_available)
        self.update_service.update_download_progress.connect(self._on_update_download_progress)
        self.update_service.update_error.connect(self._on_update_error)
        self.update_service.update_installing.connect(self._on_update_installing)
        self.update_service.schedule_changed.connect(self._on_schedule_changed)
        self.update_service.maintenance_changed.connect(self._on_maintenance_changed)
        self.update_service.notification_received.connect(self._on_notification_received)

        # Banner -> service
        self.update_banner.install_now_clicked.connect(self.update_service.install_now)
        self.update_banner.schedule_clicked.connect(self._on_schedule_requested)
        self.update_banner.skip_clicked.connect(self.update_service.dismiss_version)
        self.update_banner.cancel_schedule_clicked.connect(self.update_service.cancel_schedule)

        # Mandatory overlay -> service (only install; no skip/schedule)
        self.mandatory_overlay.install_now_clicked.connect(self.update_service.install_now)

        self.update_service.start()

    @Slot(dict)
    def _on_update_available(self, manifest: Dict[str, Any]) -> None:
        """Surface a new manifest — mandatory uses the floating overlay,
        optional uses the regular embedded banner.
        """
        version = manifest.get("version", "")
        if bool(manifest.get("mandatory", False)):
            # Hide the embedded banner so the user only sees the
            # undismissable overlay — no second exit hatch.
            self.update_banner.hide_banner()
            self.mandatory_overlay.show_mandatory(manifest)
            self._status_label.setText(f"  Update v{version} required")
        else:
            self.mandatory_overlay.hide_overlay()
            self.update_banner.show_update(manifest)
            self._status_label.setText(f"  Update v{version} available")

    @Slot(int)
    def _on_update_download_progress(self, percent: int) -> None:
        """Fan out the download percentage to whichever widget is live."""
        self.update_banner.set_downloading(percent)
        self.mandatory_overlay.set_downloading(percent)

    @Slot(dict)
    def _on_schedule_requested(self, manifest: Dict[str, Any]) -> None:
        """Open the schedule dialog; on accept, hand off to the service."""
        dlg = ScheduleUpdateDialog(self)
        # exec_() is the PySide backward-compat alias for exec(); we use it
        # to avoid tripping a security-lint hook that pattern-matches on the
        # shell-exec spelling.
        if dlg.exec_() != int(dlg.DialogCode.Accepted):
            return
        when = dlg.chosen_datetime()
        if when is None:
            return
        self.update_service.schedule_install(manifest, when)

    @Slot(object)
    def _on_schedule_changed(self, pending: Any) -> None:
        """Swap banner between available/scheduled states."""
        if pending is None:
            last = self.update_service.last_manifest()
            if last is not None:
                self.update_banner.show_update(last)
            else:
                self.update_banner.hide_banner()
        elif isinstance(pending, dict):
            self.update_banner.show_scheduled(pending)

    @Slot(str)
    def _on_update_error(self, message: str) -> None:
        self.update_banner.set_error(message)
        self.mandatory_overlay.set_error(message)
        logger.warning("update error: %s", message)

    @Slot(str)
    def _on_update_installing(self, installer_path: str) -> None:
        self.update_banner.set_installing()
        self.mandatory_overlay.set_installing()
        logger.info("installer launched: %s", installer_path)

    @Slot(bool, str)
    def _on_maintenance_changed(self, active: bool, message: str) -> None:
        """Show or hide the full-window maintenance overlay."""
        if active:
            if not hasattr(self, "_maintenance_overlay") or self._maintenance_overlay is None:
                from PySide6.QtWidgets import QVBoxLayout, QWidget
                from PySide6.QtCore import Qt

                overlay = QWidget(self)
                overlay.setObjectName("maintenanceOverlay")
                overlay.setStyleSheet(
                    "#maintenanceOverlay { background: rgba(10,10,10,0.93); }"
                )
                layout = QVBoxLayout(overlay)
                layout.setAlignment(Qt.AlignCenter)

                from PySide6.QtWidgets import QLabel
                icon = QLabel("⚙")
                icon.setStyleSheet("color: #ffd700; font-size: 48px;")
                icon.setAlignment(Qt.AlignCenter)

                title = QLabel("MAINTENANCE")
                title.setStyleSheet(
                    "color: #ffd700; font-size: 18px; font-weight: bold; "
                    "letter-spacing: 0.2em; margin-top: 12px;"
                )
                title.setAlignment(Qt.AlignCenter)

                self._maintenance_msg_label = QLabel(message or "Back soon.")
                self._maintenance_msg_label.setStyleSheet(
                    "color: rgba(255,255,255,0.55); font-size: 13px; "
                    "margin-top: 8px; max-width: 480px;"
                )
                self._maintenance_msg_label.setAlignment(Qt.AlignCenter)
                self._maintenance_msg_label.setWordWrap(True)

                layout.addWidget(icon)
                layout.addWidget(title)
                layout.addWidget(self._maintenance_msg_label)
                self._maintenance_overlay = overlay

            else:
                self._maintenance_msg_label.setText(message or "Back soon.")

            self._maintenance_overlay.setGeometry(self.rect())
            self._maintenance_overlay.raise_()
            self._maintenance_overlay.show()
            self.statusBar().showMessage("MAINTENANCE MODE — terminal paused", 0)
        else:
            if hasattr(self, "_maintenance_overlay") and self._maintenance_overlay:
                self._maintenance_overlay.hide()
            self.statusBar().showMessage("Maintenance mode ended", 4000)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_maintenance_overlay") and self._maintenance_overlay and self._maintenance_overlay.isVisible():
            self._maintenance_overlay.setGeometry(self.rect())

    @Slot(str)
    def _on_notification_received(self, message: str) -> None:
        """Show a timed notification banner in the status bar and chat."""
        self.statusBar().showMessage(f"  {message}", 0)
        self._add_chat_response(f"[notification] {message}")

    def _populate_placeholder_signals(self) -> None:
        """Create a minimal signals DataFrame from config tickers."""
        try:
            tickers = self._get_active_tickers()
            if not tickers:
                logger.info("No tickers found for placeholders (watchlists may be empty)")
                return
            if self.state.signals is not None:
                return
            import pandas as pd
            self.state.signals = pd.DataFrame({
                "ticker": tickers,
                "prob_up": [0.5] * len(tickers),
                "signal": ["HOLD"] * len(tickers),
                "ai_rec": ["--"] * len(tickers),
            })
            logger.info("Populated placeholder signals for %d tickers", len(tickers))
            self._refresh_all_panels()
        except Exception as exc:
            logger.warning("Failed to populate placeholder signals: %s", exc)

    @Slot()
    def action_refresh_data(self) -> None:
        """Fetch broker positions, account, orders, and live prices.

        No more two-phase pipeline: the ML signal generator is gone.
        Phase 4 will let the agent trigger its own reads via MCP tools.
        """
        # Sync watchlists from disk so agent mutations (clear, add, remove)
        # are visible in the UI without a full app restart.
        self._reload_watchlists_from_disk()
        self.statusBar().showMessage("Fetching broker data...", 30000)
        self._run_background(self._fetch_broker_data, self._on_broker_data_loaded)

    def _reload_watchlists_from_disk(self) -> None:
        """Re-read both watchlist keys from config.json into self.config.

        The agent writes watchlist changes directly to disk — this call
        keeps the UI's in-memory config in sync so panels show the
        latest state without requiring an app restart.

        If the active watchlist's ticker set has changed, ``state.signals``
        is cleared so ``_populate_placeholder_signals`` rebuilds from the
        new ticker list rather than showing stale rows.
        """
        try:
            import json
            with self.config_path.open("r", encoding="utf-8") as f:
                on_disk = json.load(f)

            # Snapshot current tickers before applying disk state.
            wl_key = self._watchlist_config_key()
            active = self.state.active_watchlist
            old_tickers = set(
                self.config.get(wl_key, {}).get(active, [])
            )

            for key in ("watchlists", "watchlists_paper", "active_watchlist"):
                if key in on_disk:
                    self.config[key] = on_disk[key]

            new_tickers = set(
                self.config.get(wl_key, {}).get(active, [])
            )

            # If the ticker set changed, drop stale signals so the panel
            # rebuilds from the updated watchlist on the next refresh.
            if old_tickers != new_tickers:
                self.state.signals = None
        except Exception:
            pass  # Never crash the refresh cycle over a config read

    def _fetch_broker_data(self) -> Dict[str, Any]:
        """Background: fetch broker positions, account, orders, and prices."""
        result: Dict[str, Any] = {}
        errors: List[str] = []

        try:
            result["positions"] = self.broker_service.get_positions()
        except Exception as e:
            result["positions"] = []
            errors.append(f"Positions: {e}")

        try:
            result["account_info"] = self.broker_service.get_account_info()
        except Exception as e:
            result["account_info"] = {}
            errors.append(f"Account: {e}")

        try:
            pending = self.broker_service.get_pending_orders()
        except Exception as e:
            pending = []
            errors.append(f"Orders: {e}")

        try:
            history = self.broker_service.get_order_history(limit=20)
            history_orders = history.get("items", [])
        except Exception:
            history_orders = []

        seen_ids: set[str] = set()
        merged: list[dict] = []
        for o in pending:
            oid = o.get("id", "")
            if oid:
                seen_ids.add(oid)
            merged.append(o)
        for o in history_orders:
            oid = o.get("id", "")
            if oid and oid not in seen_ids:
                merged.append(o)
        result["recent_orders"] = merged

        live_data: Dict[str, Any] = {}
        for pos in result.get("positions", []):
            t = pos.get("ticker", "")
            cur = pos.get("current_price", 0)
            avg = pos.get("avg_price", 0)
            if t and cur:
                change_pct = ((cur - avg) / avg * 100) if avg else 0
                live_data[t] = {"price": cur, "change_pct": change_pct}

        watchlist_name = getattr(self.state, "active_watchlist", "Default")
        tickers = self.config.get(self._watchlist_config_key(), {}).get(watchlist_name, [])
        missing = [t for t in tickers if t not in live_data]
        if missing:
            try:
                import yfinance as yf
                from data_loader import _clean_ticker

                yf_map = {_clean_ticker(t): t for t in missing}
                for yf_t, orig_t in yf_map.items():
                    try:
                        cols = yf.download(
                            yf_t, period="2d", interval="1d",
                            progress=False, timeout=10,
                            multi_level_index=False,
                        )
                        if cols is None or cols.empty:
                            continue
                        cols = cols.dropna()
                        if len(cols) < 1 or "Close" not in cols.columns:
                            continue
                        cur_price = float(cols["Close"].iloc[-1])
                        if len(cols) >= 2:
                            prev_close = float(cols["Close"].iloc[-2])
                            day_chg = ((cur_price - prev_close) / prev_close * 100) if prev_close else 0
                        else:
                            day_chg = 0
                        live_data[orig_t] = {"price": cur_price, "change_pct": round(day_chg, 2)}
                    except Exception:
                        pass
            except Exception as e:
                errors.append(f"Prices: {e}")

        result["live_data"] = live_data
        result["_errors"] = errors
        return result

    @Slot(object)
    def _on_broker_data_loaded(self, result: Dict[str, Any]) -> None:
        """Apply broker fetch results to state and update panels."""
        errors = result.pop("_errors", [])

        if result.get("positions") is not None:
            self.state.positions = result["positions"]
        if result.get("account_info"):
            self.state.account_info = result["account_info"]
        if result.get("live_data"):
            self.state.live_data.update(result["live_data"])
        if result.get("recent_orders") is not None:
            self.state.recent_orders = result["recent_orders"]

        self._calculate_pnl()
        self._refresh_all_panels()
        # Rebuild watchlist rows if signals was cleared by a watchlist
        # change detected during _reload_watchlists_from_disk.
        self._populate_placeholder_signals()

        if errors:
            self.statusBar().showMessage(
                f"Broker loaded ({len(errors)} error(s))", 10000,
            )
        else:
            self.statusBar().showMessage("Broker data loaded", 3000)

    def _calculate_pnl(self) -> None:
        """Sum broker-reported unrealised PnL from positions."""
        upnl = 0.0
        for pos in self.state.positions:
            val = pos.get("unrealised_pnl") or pos.get("ppl") or 0.0
            try:
                upnl += float(val)
            except (TypeError, ValueError):
                pass
        self.state.unrealised_pnl = upnl

    def _refresh_all_panels(self) -> None:
        """Refresh only the panels relevant to the active mode."""
        asset = self.state.active_asset_class

        self.settings_panel.refresh_view(self.state)
        self.chat_panel.refresh_view(self.state)
        self.chart_panel.refresh_view(self.state)
        self.agent_log_panel.refresh_view(self.state)

        if asset == "polymarket":
            self._poly_panel.refresh_view(self.state)
        else:
            self.watchlist_panel.refresh_view(self.state)
            self.positions_panel.refresh_view(self.state)
            self.exchanges_panel.refresh_view(self.state)
            self.orders_panel.refresh_view(self.state)
            if self.news_agent and self.news_agent.news_data:
                self.state.news_sentiment = self.news_agent.news_data
            # Market-wide scraper feed — populated even when the watchlist
            # is empty so the panel always has something to show. The
            # agent reads the full table via its own ``get_news`` tool.
            if self.history_manager:
                try:
                    self.state.market_news = self.history_manager.get_scraper_items(
                        kinds=["news"], since_minutes=240, limit=15,
                    )
                except Exception:
                    self.state.market_news = []
            self.news_panel.refresh_view(self.state)

        self._update_header()

    @Slot()
    def action_show_help(self) -> None:
        from desktop.dialogs.help import HelpDialog
        if hasattr(self, "_help_dialog") and self._help_dialog and self._help_dialog.isVisible():
            self._help_dialog.raise_()
            self._help_dialog.activateWindow()
            return
        self._help_dialog = HelpDialog(self)
        self._help_dialog.show()

    def action_show_about(self) -> None:
        dlg = AboutDialog(self)
        dlg.open()

    @Slot()
    def _update_header(self) -> None:
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        asset = self.state.active_asset_class
        if asset == "polymarket":
            self.setWindowTitle("blank predict")
            self._header_label.setText(
                "  blank predict | POLYMARKET | CERTIFIED RANDOM",
            )
            self._header_label.setStyleSheet(
                "color: #00bfff; font-weight: bold; font-size: 11px; "
                "background: transparent; padding: 2px 8px;",
            )
        else:
            self.setWindowTitle("blank")
            self._header_label.setText(
                f"  blank [{mode_str}] | STOCKS | CERTIFIED RANDOM",
            )
            self._header_label.setStyleSheet(
                "color: #ff8c00; font-weight: bold; font-size: 11px; "
                "background: transparent; padding: 2px 8px;",
            )

    def action_main_menu(self) -> None:
        """Show mode selector and switch asset class if changed."""
        from desktop.dialogs.mode_selector import ModeSelector
        selector = ModeSelector(self)
        result = selector.run()
        if result and result != self.state.active_asset_class:
            self._switch_asset(result)

    def _switch_asset(self, asset_class: str) -> None:
        """Switch active asset class."""
        if asset_class == self.state.active_asset_class:
            return
        asset_cfg = self.config.get(asset_class, {})
        if asset_class != "stocks" and not asset_cfg.get("enabled", False):
            self.statusBar().showMessage(
                f"{asset_class.title()} is disabled in config.json", 3000,
            )
            return

        self.state.signals = None
        self.state.live_data = {}

        self.state.switch_asset_class(asset_class)
        if asset_class == "stocks":
            self.state.active_watchlist = self.config.get("active_watchlist", "Default")
        else:
            self.state.active_watchlist = asset_cfg.get("active_watchlist", "")
        self._save_config_key("active_asset_class", asset_class)

        self._apply_dock_layout()
        self._update_header()

        from desktop.theme import BLOOMBERG_DARK_QSS, MODE_OVERLAY_STOCKS, MODE_OVERLAY_POLYMARKET
        from PySide6.QtWidgets import QApplication
        overlay = MODE_OVERLAY_POLYMARKET if asset_class == "polymarket" else MODE_OVERLAY_STOCKS
        QApplication.instance().setStyleSheet(BLOOMBERG_DARK_QSS + overlay)

        if asset_class == "stocks":
            self._populate_placeholder_signals()
        self._refresh_all_panels()
        self.action_refresh_data()
        self.statusBar().showMessage(f"Switched to {asset_class.title()}", 3000)

    def action_toggle_mode(self) -> None:
        if self.state.mode == "recommendation":
            self.state.mode = "full_auto_limited"
        else:
            self.state.mode = "recommendation"
        self._save_config_key("terminal.mode", self.state.mode)
        self._update_header()
        self._refresh_all_panels()
        if self.state.mode == "full_auto_limited":
            self._on_agent_start()
        else:
            self._on_agent_stop()
        self.statusBar().showMessage(
            f"Mode: {self.state.mode}", 3000,
        )

    @Slot()
    def action_cycle_watchlist(self) -> None:
        if not self._require_stocks():
            return
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
        self.action_refresh_data()

    @Slot()
    def action_refresh_news(self) -> None:
        if not self.news_agent:
            self.statusBar().showMessage("News agent not available — check feedparser is installed", 5000)
            return
        if getattr(self, "_refreshing_news", False):
            self.statusBar().showMessage("News is already refreshing...", 2000)
            return
        self._refreshing_news = True
        self.statusBar().showMessage("FETCHING NEWS — this may take a moment...", 60000)
        self._run_background(
            lambda: (self.news_agent.fetch_now(), self.news_agent.news_data)[-1],
            self._on_news_refreshed,
            on_error=lambda e: setattr(self, "_refreshing_news", False),
        )

    def _on_news_refreshed(self, news_data: Any) -> None:
        self._refreshing_news = False
        self.state.news_sentiment = news_data
        if self.news_panel:
            self.news_panel.refresh_view(self.state)
        self.statusBar().showMessage("News refreshed", 3000)

    @Slot()
    def action_focus_chat(self) -> None:
        self.chat_panel.focus_input()

    def _handle_chat_message(self, message: str) -> None:
        """Spawn a chat worker for this message.

        Every message goes through the agent pool: a fresh Claude
        sub-agent is spawned in its own QThread, shares the supervisor's
        brain (journal, memory, broker, config), and streams back into
        the chat panel. No queueing, no "routed to the running agent"
        wait — the supervisor (if running) keeps iterating undisturbed.
        """
        self.state.chat_history.append({"role": "user", "text": message})
        if self.history_manager:
            try:
                self.history_manager.save_chat_message("user", message)
            except Exception:
                pass
        self.chat_panel.refresh_view(self.state)

        try:
            self._ensure_agent_pool()
        except Exception as e:
            logger.exception("Failed to build AgentPool")
            self._add_chat_response(f"Agent pool init failed: {e}")
            return

        assert self.agent_pool is not None
        # Let the user know if they're piling on past the soft cap —
        # the pool will still queue the message, just won't run it
        # until a slot frees up.
        if not self.agent_pool.can_spawn_chat_worker():
            active = self.agent_pool.active_chat_count()
            self.statusBar().showMessage(
                f"AI busy ({active} workers) — queuing...", 4000,
            )
        else:
            self.statusBar().showMessage("AI thinking...", 10000)
        self.agent_pool.spawn_chat_worker(message)

    # ── Agent pool lifecycle ─────────────────────────────────────────

    @Slot()
    def _on_agent_start(self) -> None:
        """Start the supervisor inside the pool (build pool if needed)."""
        try:
            self._ensure_agent_pool()
        except Exception as e:
            logger.exception("Failed to build AgentPool")
            self.statusBar().showMessage(f"Agent init failed: {e}", 6000)
            return

        assert self.agent_pool is not None
        if self.agent_pool.supervisor_running():
            self.statusBar().showMessage("Agent already running", 3000)
            return
        self.agent_pool.start_supervisor()
        self.statusBar().showMessage("Agent loop starting...", 3000)

    @Slot()
    def _on_agent_stop(self) -> None:
        """Ask the supervisor to stop after the current iteration."""
        if self.agent_pool is None or not self.agent_pool.supervisor_running():
            self.statusBar().showMessage("Agent not running", 3000)
            return
        self.agent_pool.stop_supervisor()
        self.statusBar().showMessage(
            "Agent stopping after current iteration...", 5000,
        )

    @Slot()
    def _on_agent_kill(self) -> None:
        """Hard-stop the supervisor (still leaves chat workers alone)."""
        if self.agent_pool is None:
            return
        self.agent_pool.kill_supervisor()
        self.state.agent_running = False
        self.agent_log_panel.refresh_view(self.state)
        self.statusBar().showMessage("Agent killed", 3000)

    @Slot()
    def _open_paper_window(self) -> None:
        """Spawn the paper trading window as a completely separate instance.

        The paper window is its own blank slate — separate agent, separate
        broker, separate watchlist, always starting fresh at £100.
        ``self._paper_window`` holds the reference so Qt does not
        garbage-collect the window while the live window is still open.
        """
        self._paper_window = MainWindow(
            config_path=self.config_path,
            initial_asset=self.state.active_asset_class,
            forced_paper_mode=True,
        )
        self._paper_window.showMaximized()

    def _watchlist_config_key(self) -> str:
        """Return the config key for the currently active mode's watchlists."""
        return "watchlists_paper" if self.state.agent_paper_mode else "watchlists"

    def _start_scraper_runner(self) -> None:
        """Spin up the background scraper thread.

        Needs ``self.history_manager`` to be live — if Claude/DB init
        failed earlier we silently skip so the rest of the app still
        boots. The watchlist provider is a lambda so it reads the
        freshest ticker list on every cycle.
        """
        if self.history_manager is None:
            return
        try:
            from core.scrapers.runner import ScraperRunner
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Scraper runner unavailable: %s", exc,
            )
            return

        news_cfg = self.config.get("news", {}) or {}
        cadence = int(news_cfg.get("scraper_cadence_seconds", 300))

        self.scraper_runner = ScraperRunner(
            db=self.history_manager,
            watchlist_provider=self._get_active_tickers,
            cadence_seconds=cadence,
        )
        self.scraper_runner.start()

    def _ensure_agent_pool(self) -> None:
        """Build the ``AgentPool`` once and wire its signals.

        The pool lazily constructs the supervisor runner on the first
        ``start_supervisor`` call, so creating the pool itself is
        cheap — we can do it on the chat path too so chat workers are
        available even if the user never clicks Start Agent.
        """
        if self.agent_pool is not None:
            return
        from desktop.paths import db_path as _user_db_path
        if self._forced_paper_mode:
            # Paper window uses a completely separate history DB so its
            # journal and memory never bleed into the live agent's context.
            db_path = str(_user_db_path().parent / "paper_history.db")
        else:
            db_path = self.config.get("database", {}).get(
                "path", str(_user_db_path()),
            )
        self.agent_pool = AgentPool(
            config_path=self.config_path,
            live_broker_service=self.broker_service,
            db_path=db_path,
            force_paper=self._forced_paper_mode,
            parent=self,
        )
        # Lazily-created supervisor: we connect its signals the first
        # time the pool hands it out. Since `ensure_supervisor` is
        # idempotent we can safely call it once here — that way we
        # don't need a second wiring layer inside the pool.
        sup = self.agent_pool.ensure_supervisor()
        sup.status_changed.connect(self._on_agent_status_changed)
        sup.log_line.connect(self._on_agent_log_line)
        sup.text_chunk.connect(self._on_agent_text_chunk)
        sup.iteration_started.connect(self._on_agent_iteration_started)
        sup.iteration_finished.connect(self._on_agent_iteration_finished)
        sup.error_occurred.connect(self._on_agent_error_occurred)

        # Chat worker signals are forwarded by the pool.
        self.agent_pool.chat_text.connect(self._on_chat_worker_text)
        self.agent_pool.chat_done.connect(self._on_chat_worker_done)
        self.agent_pool.chat_error.connect(self._on_chat_worker_error)
        self.agent_pool.chat_log_line.connect(self._on_agent_log_line)
        self.agent_pool.worker_spawned.connect(self._on_chat_worker_spawned)
        self.agent_pool.worker_finished.connect(self._on_chat_worker_finished)

    # ── Agent signal slots — run on the GUI thread ───────────────────

    @Slot(bool)
    def _on_agent_status_changed(self, running: bool) -> None:
        self.state.agent_running = running
        self._agent_start_action.setEnabled(not running)
        self._agent_stop_action.setEnabled(running)
        self._agent_kill_action.setEnabled(running)
        self.agent_log_panel.refresh_view(self.state)

    @Slot(str)
    def _on_agent_log_line(self, line: str) -> None:
        tail = self.state.agent_journal_tail
        tail.append(line)
        # Cap the in-memory tail to match the panel's maximumBlockCount
        # so long sessions don't balloon memory.
        if len(tail) > 1000:
            del tail[: len(tail) - 1000]
        self.agent_log_panel.append_line(line)

    @Slot(str)
    def _on_agent_text_chunk(self, chunk: str) -> None:
        self._agent_text_buffer.append(chunk)

    @Slot(str)
    def _on_agent_iteration_started(self, iteration_id: str) -> None:
        from datetime import datetime
        self.state.last_iteration_ts = datetime.now()
        self._agent_text_buffer.clear()

    @Slot(str, str)
    def _on_agent_iteration_finished(self, iteration_id: str, summary: str) -> None:
        # Prefer the full agent text accumulated during streaming; fall back
        # to the end_iteration summary if the buffer is empty.
        full_text = "".join(self._agent_text_buffer).strip()
        self._agent_text_buffer.clear()
        message = full_text or summary
        if message:
            self.state.last_summary = summary or full_text
            self._add_chat_response(message)
        self._refresh_all_panels()

    @Slot(str)
    def _on_agent_error_occurred(self, msg: str) -> None:
        self.statusBar().showMessage(f"Agent error: {msg}", 8000)
        self._on_agent_log_line(f"[error] {msg}")

    # ── Chat worker signal slots ─────────────────────────────────────

    @Slot(str)
    def _on_chat_worker_spawned(self, worker_id: str) -> None:
        """Track a new worker so we can report concurrent workload."""
        self._chat_worker_ids.add(worker_id)
        self._chat_worker_buffers[worker_id] = []
        count = len(self._chat_worker_ids)
        if count > 1:
            self.statusBar().showMessage(
                f"AI thinking ({count} workers)...", 10000,
            )

    @Slot(str, str)
    def _on_chat_worker_text(self, worker_id: str, text: str) -> None:
        """Buffer streamed assistant text for this worker."""
        self._chat_worker_buffers.setdefault(worker_id, []).append(text)

    @Slot(str, str)
    def _on_chat_worker_done(self, worker_id: str, summary: str) -> None:
        """Worker finished — flush the accumulated text into chat."""
        parts = self._chat_worker_buffers.pop(worker_id, [])
        full_text = "\n".join(p for p in parts if p).strip()
        message = full_text or summary or ""
        if message:
            self._add_chat_response(message)
        self._chat_worker_ids.discard(worker_id)
        if not self._chat_worker_ids:
            self.statusBar().showMessage("", 0)
        # A chat worker may have mutated broker / watchlist state.
        self._refresh_all_panels()

    @Slot(str, str)
    def _on_chat_worker_error(self, worker_id: str, error: str) -> None:
        self._chat_worker_buffers.pop(worker_id, None)
        self._chat_worker_ids.discard(worker_id)
        self._add_chat_response(f"(chat worker error: {error})")
        if not self._chat_worker_ids:
            self.statusBar().showMessage("", 0)

    @Slot(str)
    def _on_chat_worker_finished(self, worker_id: str) -> None:
        """Pool cleanup signal — second chance to release buffers."""
        self._chat_worker_buffers.pop(worker_id, None)
        self._chat_worker_ids.discard(worker_id)

    @Slot()
    def action_show_chart(self) -> None:
        if not self.chart_panel:
            return
        if self.watchlist_panel:
            ticker = self.watchlist_panel.selected_ticker()
            if ticker:
                self._load_chart_async(ticker)

    def _on_watchlist_click(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        """Auto-load chart when a watchlist row is selected."""
        if row < 0 or not self.watchlist_panel or not self.chart_panel:
            return
        ticker = self.watchlist_panel.selected_ticker()
        if ticker:
            self._load_chart_async(ticker)

    def _load_chart_async(self, ticker: str) -> None:
        """Load chart data in a background thread to avoid freezing the UI."""
        self.chart_panel._title_label.setText(f"CHART - {ticker} (loading...)")
        self._run_background(
            lambda: self._fetch_chart_data(ticker),
            lambda result: self._on_chart_loaded(ticker, result),
        )

    def _fetch_chart_data(self, ticker: str) -> dict:
        """Background: fetch OHLCV data via yfinance with fallback periods."""
        import yfinance as yf
        from data_loader import _clean_ticker

        yf_ticker = _clean_ticker(ticker)
        logger.info("Chart fetch: %s → yfinance symbol '%s'", ticker, yf_ticker)
        periods = ["1y", "6mo", "3mo", "1mo"]
        last_err = ""
        for period in periods:
            try:
                df = yf.download(
                    yf_ticker, period=period, interval="1d",
                    progress=False, timeout=15,
                    multi_level_index=False,
                )
                if df is None or df.empty:
                    logger.debug("Chart %s period=%s: empty result", yf_ticker, period)
                    continue

                required = ["Open", "High", "Low", "Close", "Volume"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    logger.debug("Chart %s period=%s: missing cols %s (have %s)",
                                 yf_ticker, period, missing, list(df.columns))
                    continue

                df = df[required].dropna()
                if len(df) < 2:
                    continue

                return {
                    "opens": df["Open"].values.astype(float).flatten(),
                    "highs": df["High"].values.astype(float).flatten(),
                    "lows": df["Low"].values.astype(float).flatten(),
                    "closes": df["Close"].values.astype(float).flatten(),
                    "volumes": df["Volume"].values.astype(float).flatten(),
                    "period": period,
                }
            except Exception as exc:
                last_err = str(exc)
                logger.warning("Chart %s period=%s error: %s", yf_ticker, period, exc)
                continue
        err_msg = f"No data for {yf_ticker}"
        if last_err:
            err_msg += f" ({last_err})"
        return {"error": err_msg}

    def _on_chart_loaded(self, ticker: str, result: dict) -> None:
        """Main thread: render chart from fetched data."""
        if "error" in result:
            self.chart_panel._title_label.setText(f"CHART - {ticker}")
            self.chart_panel._info_label.setText(result["error"])
            return

        self.chart_panel._current_ticker = ticker
        self.chart_panel._title_label.setText(f"CHART - {ticker}")

        opens = result["opens"]
        highs = result["highs"]
        lows = result["lows"]
        closes = result["closes"]
        volumes = result["volumes"]

        self.chart_panel._draw_candlestick(opens, highs, lows, closes, volumes)

        n = len(closes)
        if self.chart_panel._has_pyqtgraph and n > 0:
            self.chart_panel._price_plot.setXRange(0, n - 1, padding=0.02)
            self.chart_panel._price_plot.setYRange(
                float(lows.min()), float(highs.max()), padding=0.05,
            )

        cur = closes[-1]
        prev = opens[0]
        change_pct = ((cur - prev) / prev * 100) if prev else 0
        hi = highs.max()
        lo = lows.min()
        vol = volumes[-1]
        color = "#00ff00" if change_pct >= 0 else "#ff0000"

        self.chart_panel._info_label.setText(
            f"O: ${opens[-1]:.2f} | H: ${hi:.2f} | L: ${lo:.2f} | "
            f"C: ${cur:.2f} | "
            f'<span style="color:{color};">{change_pct:+.1f}%</span> | '
            f"Vol: {vol:,.0f}"
        )

    @Slot()
    def action_open_trade(self) -> None:
        if not self._require_stocks():
            return
        if not self.watchlist_panel:
            self.statusBar().showMessage("Trading not available in this mode", 3000)
            return
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
        if not self._require_stocks():
            return
        from desktop.dialogs.add_ticker import AddTickerDialog
        dlg = AddTickerDialog(self)
        if dlg.exec() and dlg.ticker:
            watchlist_name = self.state.active_watchlist
            wl_key = self._watchlist_config_key()
            wl = self.config.get(wl_key, {}).get(watchlist_name, [])
            if dlg.ticker not in wl:
                wl.append(dlg.ticker)
                self._save_config_key(f"{wl_key}.{watchlist_name}", wl)
                self.statusBar().showMessage(f"Added {dlg.ticker}", 3000)
                self.action_refresh_data()

    @Slot()
    def action_remove_ticker(self) -> None:
        if not self._require_stocks():
            return
        if not self.watchlist_panel:
            return
        ticker = self.watchlist_panel.selected_ticker()
        if not ticker:
            return
        watchlist_name = self.state.active_watchlist
        wl_key = self._watchlist_config_key()
        wl = self.config.get(wl_key, {}).get(watchlist_name, [])
        if ticker in wl:
            wl.remove(ticker)
            self._save_config_key(f"{wl_key}.{watchlist_name}", wl)
            self.statusBar().showMessage(f"Removed {ticker}", 3000)
            self.action_refresh_data()

    @Slot()
    def action_search_ticker(self) -> None:
        from desktop.dialogs.search_ticker import SearchTickerDialog
        dlg = SearchTickerDialog(self)
        self._search_dialog = dlg

        def do_search(query: str) -> None:
            self._run_background(
                lambda: self._claude_client.search_tickers(query) if self._claude_client else [],
                lambda results: dlg.populate_results(results) if dlg.isVisible() else None,
            )

        dlg.set_search_callback(do_search)
        if dlg.exec() and dlg.selected_ticker:
            self._add_ticker_to_watchlist(dlg.selected_ticker)
        self._search_dialog = None

    def _get_active_tickers(self) -> List[str]:
        """Get all tickers from the active asset class's watchlists."""
        asset = self.state.active_asset_class
        tickers: set[str] = set()
        if asset == "stocks":
            for wl in self.config.get(self._watchlist_config_key(), {}).values():
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
            watchlists = self.config.get(self._watchlist_config_key(), {})
        else:
            watchlists = self.config.get(asset, {}).get("watchlists", {})
        active = self.state.active_watchlist
        if active in watchlists:
            if ticker not in watchlists[active]:
                watchlists[active].append(ticker)
                self._save_config()
                if self.news_agent:
                    self.news_agent.update_tickers(self._get_active_tickers())
                self.statusBar().showMessage(f"Added {ticker}", 3000)
                self._refresh_all_panels()

    def _remove_ticker_from_watchlist(self, ticker: str) -> bool:
        """Programmatically remove a ticker from the active watchlist."""
        ticker = ticker.upper().strip()
        if not ticker:
            return False
        asset = self.state.active_asset_class
        if asset == "stocks":
            watchlists = self.config.get(self._watchlist_config_key(), {})
        else:
            watchlists = self.config.get(asset, {}).get("watchlists", {})
        active = self.state.active_watchlist
        if active in watchlists and ticker in watchlists[active]:
            watchlists[active].remove(ticker)
            self._save_config()
            if self.news_agent:
                self.news_agent.update_tickers(self._get_active_tickers())
            return True
        return False

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
        if not self._require_stocks():
            return
        if not self.watchlist_panel:
            return
        ticker = self.watchlist_panel.selected_ticker()
        if not ticker:
            return
        if ticker in self.state.protected_tickers:
            self.state.protected_tickers.discard(ticker)
            self.statusBar().showMessage(f"Unlocked {ticker}", 2000)
        else:
            self.state.protected_tickers.add(ticker)
            self.statusBar().showMessage(f"Locked {ticker}", 2000)
        self._save_config_key(
            "protected_tickers", list(self.state.protected_tickers),
        )
        self.watchlist_panel.refresh_view(self.state)

    def _require_stocks(self) -> bool:
        """Return True if in stocks mode. Show message and return False otherwise."""
        if self.state.active_asset_class == "stocks":
            return True
        self.statusBar().showMessage("This action is only available in Stocks mode", 3000)
        return False

    def _require_ai(self, action_name: str = "This feature") -> bool:
        """Return True if Claude CLI is available. Show message if not."""
        if self._claude_client and getattr(self._claude_client, "available", False):
            return True
        self.statusBar().showMessage(
            f"{action_name} requires Claude CLI — install from docs.anthropic.com/en/docs/claude-cli",
            5000,
        )
        return False

    def _save_config(self) -> None:
        """Save the full config dict to config.json."""
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

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

    def closeEvent(self, event: Any) -> None:
        """Stop timers and background services before closing.

        Ordering matters: we flush the in-memory config first so any
        unsaved mutations (watchlists, agent paper-mode toggle, update
        scheduling) land on disk before we start tearing down background
        services. Without this, anything that calls ``self.config[...]
        = x`` without going through :meth:`_save_config_key` (there are
        a few) would be silently lost on quit.
        """
        # 1. Flush config — nothing is lost across restarts.
        try:
            self._save_config()
        except Exception:
            logging.getLogger(__name__).exception("closeEvent: config flush failed")

        # 2. If an update is scheduled to fire within the next 5 minutes,
        # the user was about to be interrupted anyway — install it now
        # instead of losing their chosen window. The service owns the
        # download + launch flow, so calling install_now here will kick
        # off the same sequence that the scheduled fire would have
        # triggered a few minutes later.
        update_service = getattr(self, "update_service", None)
        if update_service is not None and update_service.is_schedule_imminent(5):
            pending = update_service.pending_install()
            if pending is not None:
                logger.info("closeEvent: firing imminent scheduled install")
                manifest = {
                    "version": pending.get("version", ""),
                    "download_url": pending.get("download_url", ""),
                    "sha256": pending.get("sha256", ""),
                    "notes": pending.get("notes", ""),
                    "mandatory": pending.get("mandatory", False),
                }
                update_service.install_now(manifest)
                # Let the installer take over; still proceed with teardown.

        # 3. Stop timers + background workers.
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()

        if self.news_agent:
            try:
                self.news_agent.stop()
            except Exception:
                pass

        # Shut the Claude agent pool down cleanly. cancel_all_chat_workers()
        # signals every live chat worker; kill_supervisor() soft-stops then
        # hard-terminates the supervisor if it doesn't exit within 2s.
        if self.agent_pool is not None:
            try:
                self.agent_pool.shutdown()
            except Exception:
                logger.exception("closeEvent: agent_pool.shutdown failed")

        # Phase 5 scraper runner is a daemon thread so it dies with
        # the process, but request a clean stop so the current cycle
        # finishes writing to sqlite before the DB handle closes.
        if self.scraper_runner is not None:
            try:
                self.scraper_runner.stop()
            except Exception:
                pass

        # 4. Stop the update service last — this cancels any in-flight
        # download and releases the poll QTimer so Qt can exit cleanly.
        if update_service is not None:
            try:
                update_service.stop()
            except Exception:
                logger.exception("closeEvent: update_service.stop failed")

        super().closeEvent(event)
