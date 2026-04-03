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
    NewsView, ChatView, HelpModal, ResearchView,
    AddTickerModal, TradeModal, SearchTickerModal, AiRecommendModal,
)
from terminal.charts import PriceChartView
from terminal.history_views import HistoryModal, PiesModal, InstrumentsModal
from terminal.mode_selector import ModeSelectorModal
from terminal.pipeline_view import PipelineView
from pipeline_tracker import PipelineTracker

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Label
from textual.containers import Grid


ConfigDict = Dict[str, Any]


def _load_css() -> str:
    """Load CSS from file — works both normally and inside PyInstaller bundle."""
    candidates = [
        Path(__file__).resolve().parent / "terminal.css",
        Path(getattr(sys, '_MEIPASS', '.')) / "terminal" / "terminal.css",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


class TradingTerminalApp(App):  # type: ignore[misc]
    CSS = _load_css()
    BINDINGS = [
        ("question_mark", "show_help", "? Help"),
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
        ("l", "toggle_protect", "Lock"),
        ("1", "switch_asset('stocks')", "Stocks"),
        ("2", "switch_asset('polymarket')", "Polymarket"),
        ("3", "switch_asset('crypto')", "Crypto"),
        ("f5", "apply_research", "Apply Research"),
        ("m", "show_mode_menu", "Mode Menu"),
    ]

    def __init__(self, config_path: Path | str = "config.json") -> None:
        super().__init__()
        self.config_path = Path(config_path)
        self.config: ConfigDict = self._load_config()
        self.state = self._init_state()
        self.pipeline_tracker = PipelineTracker()
        self.ai_service = AiService(self.config_path)
        self.ai_service.tracker = self.pipeline_tracker
        self.broker_service = BrokerService(self.config)
        self.auto_engine = AutoEngine(self.config, self.state, self.ai_service, self.broker_service)

        # Shared Claude client — reused by chat, search, recommend, scan, etc.
        self._claude_client: Optional[Any] = None
        self.news_agent: Optional[NewsAgent] = None
        try:
            from claude_client import ClaudeClient, ClaudeConfig
            claude_cfg_raw = self.config.get("claude", {})
            ccfg = ClaudeConfig(
                model=claude_cfg_raw.get("model", "claude-sonnet-4-20250514"),
            )
            self._claude_client = ClaudeClient(ccfg)

            # History Manager
            from database import HistoryManager
            self.history_manager = HistoryManager()

            # Wire accuracy tracker into AI service
            from accuracy_tracker import AccuracyTracker
            self.ai_service._accuracy_tracker = AccuracyTracker(self.history_manager)

            news_interval = self.config.get("news", {}).get("refresh_interval_minutes", 5)
            self.news_agent = NewsAgent(self._claude_client, refresh_interval_minutes=news_interval)
        except Exception as e:
            print(f"[app] Could not init Claude/news: {e}")

        # View references
        self.settings_view: Optional[SettingsView] = None
        self.watchlist_view: Optional[WatchlistView] = None
        self.positions_view: Optional[PositionsView] = None
        self.orders_view: Optional[OrdersView] = None
        # ai_insights_view removed — insights now route to chat panel
        self.news_view: Optional[NewsView] = None
        self.chat_view: Optional[ChatView] = None
        self.chart_view: Optional[PriceChartView] = None
        self.pipeline_view: Optional[PipelineView] = None
        self.research_view: Optional[ResearchView] = None

        self.refresh_timer = None
        self.state.broker_is_live = self.broker_service.is_live

        # Signal cache — avoids re-running the full AI pipeline every 60s
        import time as _time
        self._last_signal_run: float = 0.0
        self._pipeline_running: bool = False
        self._pipeline_start_time: float = 0.0
        # Full pipeline runs at most once per 10 minutes; interim refreshes
        # only update broker data (positions, live prices, account).
        self._signal_cache_seconds: float = 120.0
        # Safety: auto-reset _pipeline_running if stuck longer than this
        self._pipeline_timeout_seconds: float = 600.0

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
            active_watchlist=self.config.get("active_watchlist", "Default"),
            protected_tickers=set(self.config.get("protected_tickers", [])),
            active_asset_class=self.config.get("active_asset_class", "stocks"),
            enabled_asset_classes=self.config.get("enabled_asset_classes", ["stocks"]),
        )

    # ── Layout ─────────────────────────────────────────────────────────

    def _header_text(self) -> str:
        mode_str = "AUTO" if self.state.mode == "full_auto_limited" else "ADVISOR"
        asset = self.state.active_asset_class.upper()
        return f"TERMINAL [#{mode_str}] | {asset} | BLOOMBERG AI CORE"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(self._header_text(), id="app-header-title")
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

            # Row 4: Research Lab (spans all 3 columns)
            self.research_view = ResearchView(self.state)
            yield self.research_view

            # Row 5: Pipeline Monitor (spans all 3 columns)
            self.pipeline_view = PipelineView(self.pipeline_tracker)
            yield self.pipeline_view

        yield Footer()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def on_mount(self) -> None:  # type: ignore[override]
        # Show mode selector on startup
        self.push_screen(ModeSelectorModal(), callback=self._on_mode_selected)

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

        self.refresh_data(force_signals=True)
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

        # Auto-optimize weights every 4 hours
        self._optimize_timer = self.set_interval(14400, self._auto_optimize)

        # Continuous AI market scanner every 15 minutes
        self._scanner_timer = self.set_interval(900, self._ai_market_scan)

        # AI stock discovery every 2 hours (day trading needs frequent scans)
        self._discovery_timer = self.set_interval(7200, self._daily_stock_discovery)

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
        if hasattr(self, '_discovery_timer') and self._discovery_timer:
            self._discovery_timer.stop()
        # Prune old chat and memories on exit to prevent unbounded DB growth
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.clear_old_chat(200)
                self.history_manager.clear_old_memories(50)
            except Exception:
                pass

    def _on_mode_selected(self, asset_class: Optional[str]) -> None:
        """Callback from ModeSelectorModal — switch to chosen asset class."""
        if asset_class and asset_class != self.state.active_asset_class:
            self.action_switch_asset(asset_class)

    def action_show_mode_menu(self) -> None:
        """Reopen the mode selector modal."""
        self.push_screen(ModeSelectorModal(), callback=self._on_mode_selected)

    def _get_active_tickers(self) -> List[str]:
        asset = self.state.active_asset_class
        all_tickers: set[str] = set()

        if asset == "stocks":
            watchlists = self.config.get("watchlists", {})
            for tickers in watchlists.values():
                all_tickers.update(tickers)
        else:
            asset_cfg = self.config.get(asset, {})
            watchlists = asset_cfg.get("watchlists", {})
            for tickers in watchlists.values():
                all_tickers.update(tickers)

        # Add held tickers
        for pos in self.state.positions:
            t = pos.get("ticker")
            if t:
                all_tickers.add(t)

        return sorted(list(all_tickers))

    # ── Auto-sync T212 positions → watchlist ─────────────────────────

    def _sync_held_to_watchlist(self, held_tickers: List[str]) -> None:
        """Ensure every T212 held position appears on the active watchlist.

        T212 returns instrument IDs like ``TSLA_US_EQ``.  We store both the
        raw T212 ID (so the pipeline can match positions) and check against
        cleaned names to avoid duplicates like TSLA + TSLA_US_EQ.
        Runs on every refresh — cheap dict check, no API calls.

        Case-insensitive matching: config may have ``VUKGl_EQ`` (lowercase l)
        while T212 returns ``VUKGL_EQ``.  We normalise both sides via upper().
        """
        if not held_tickers:
            return
        from data_loader import _clean_ticker

        # Asset-class-aware watchlist lookup (matches _get_active_tickers pattern)
        asset = self.state.active_asset_class
        if asset == "stocks":
            watchlists = self.config.get("watchlists", {})
        else:
            watchlists = self.config.get(asset, {}).setdefault("watchlists", {})
        active = self.state.active_watchlist
        current = watchlists.setdefault(active, [])

        # Build lookup sets — case-insensitive for both raw and cleaned forms
        existing_raw_upper = {t.upper() for t in current}
        existing_cleaned = {_clean_ticker(t) for t in current}

        added: list[str] = []
        for raw_ticker in held_tickers:
            # Already on watchlist (case-insensitive exact or cleaned match)?
            if raw_ticker.upper() in existing_raw_upper:
                continue
            cleaned = _clean_ticker(raw_ticker)
            if cleaned in existing_cleaned:
                continue
            # Add the raw T212 ticker so position-matching works
            current.append(raw_ticker)
            existing_raw_upper.add(raw_ticker.upper())
            existing_cleaned.add(cleaned)
            added.append(raw_ticker)

        if added:
            watchlists[active] = current
            self._save_config()
            self.ai_service._config_cache = None
            print(f"[app] ✓ Synced {len(added)} T212 positions to watchlist: {added}")
            if self.news_agent:
                new_tickers = self._get_active_tickers()
                self.news_agent.update_tickers(new_tickers)
                print(f"[app] ✓ News agent now tracking {len(new_tickers)} tickers")

    # ── Daily Stock Discovery ─────────────────────────────────────────

    @work(thread=True)
    def _daily_stock_discovery(self) -> None:
        """Every 2 hours, ask Claude to suggest volatile day-trading candidates.
        Uses a single Claude call — not per-ticker."""
        try:
            if not self._claude_client:
                return

            all_tickers = self._get_active_tickers()
            held = [p.get("ticker", "") for p in self.state.positions]

            prompt = (
                "You are a day trading stock screener for an active intraday terminal.\n\n"
                f"Current watchlist: {all_tickers}\n"
                f"Currently held positions: {held}\n\n"
                "Suggest 3-5 NEW stock tickers (not already on the watchlist) "
                "ideal for DAY TRADING right now. Prioritise:\n"
                "- High intraday volatility (large daily ranges, frequent 2%+ moves)\n"
                "- Unusual volume spikes or pre-market activity\n"
                "- Stocks with upcoming catalysts (earnings, FDA, sector rotation)\n"
                "- Gap-play candidates (recent gaps up/down that may fill)\n"
                "- Small/mid-cap names with momentum and liquidity\n"
                "- Avoid illiquid penny stocks below $5\n\n"
                "Think beyond FAANG. Include lesser-known volatile names from "
                "biotech, cannabis, EV, SPAC, or meme sectors if they have volume.\n\n"
                "Respond strictly as JSON:\n"
                '{"tickers": [{"symbol": "TICK", "reason": "one sentence why"}]}'
            )

            text = self._claude_client._call(prompt, task_type="medium")
            if not text:
                return

            obj = self._claude_client._parse_json(text)
            suggestions = obj.get("tickers", [])
            if not suggestions:
                return

            watchlists = self.config.get("watchlists", {})
            active = self.state.active_watchlist
            current = watchlists.get(active, [])
            added: list[str] = []

            for item in suggestions[:5]:
                ticker = str(item.get("symbol", "")).upper().strip()
                reason = str(item.get("reason", "AI discovery"))
                if not ticker or ticker in current:
                    continue
                current.append(ticker)
                added.append(ticker)
                if hasattr(self, 'history_manager'):
                    self.history_manager.log_watchlist_action(
                        "ADD", ticker, active, f"Daily AI discovery: {reason}"
                    )

            if added:
                watchlists[active] = current
                self._save_config()
                self.ai_service._config_cache = None
                if self.news_agent:
                    self.news_agent.update_tickers(self._get_active_tickers())
                self.call_from_thread(
                    self._add_chat_response,
                    f"[DAILY DISCOVERY] Added {', '.join(added)} to {active} watchlist."
                )

        except Exception as e:
            print(f"[app] Daily stock discovery error: {e}")

    # ── Help ──────────────────────────────────────────────────────────

    def action_show_help(self) -> None:
        self.push_screen(HelpModal(), callback=lambda _: None)

    # ── Data Refresh ───────────────────────────────────────────────────

    def action_refresh_data(self) -> None:
        self.refresh_data(force_signals=True)

    @work(thread=True)
    def refresh_data(self, force_signals: bool = False) -> None:
        if not self.is_running:
            return
        try:
            import concurrent.futures
            import time as _time

            # Decide whether to re-run the full AI pipeline or just refresh
            # broker data.  The pipeline is expensive (Claude CLI calls),
            # so we cache signals for _signal_cache_seconds.
            # Never start a second pipeline while one is already running.
            now = _time.monotonic()
            cache_expired = (now - self._last_signal_run >= self._signal_cache_seconds)

            # Safety: auto-reset _pipeline_running if stuck too long
            if self._pipeline_running:
                stuck_seconds = now - self._pipeline_start_time
                if stuck_seconds > self._pipeline_timeout_seconds:
                    print(f"[app] Pipeline stuck for {stuck_seconds:.0f}s — force-resetting")
                    self._pipeline_running = False

            run_pipeline = (force_signals or cache_expired) and not self._pipeline_running

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                # 1. Always refresh broker data (with timeout)
                future_pos = executor.submit(self.broker_service.get_positions)
                future_acct = executor.submit(self.broker_service.get_account_info)

                # 2. Wait for broker data — 30s timeout prevents hang
                try:
                    positions = future_pos.result(timeout=30)
                except (concurrent.futures.TimeoutError, Exception) as e:
                    print(f"[app] Broker positions timeout/error: {e}")
                    positions = self.state.positions if hasattr(self.state, 'positions') else []
                try:
                    account_info = future_acct.result(timeout=30)
                except (concurrent.futures.TimeoutError, Exception) as e:
                    print(f"[app] Broker account timeout/error: {e}")
                    account_info = self.state.account_info if hasattr(self.state, 'account_info') else {}

                held_tickers = [p.get("ticker") for p in positions if p.get("ticker")]

                # 2a. Auto-sync: ensure every T212 position is on the active watchlist
                if held_tickers:
                    print(f"[app] Loaded {len(held_tickers)} positions from Trading212: {held_tickers}")
                self._sync_held_to_watchlist(held_tickers)

                # 3. Only run the full AI pipeline on cooldown
                if run_pipeline:
                    self._pipeline_running = True
                    self._pipeline_start_time = _time.monotonic()
                    # Feed news data to AI service for ensemble weighting
                    if self.news_agent:
                        self.ai_service.update_news_data(self.news_agent.news_data)

                    future_signals = executor.submit(
                        self.ai_service.get_latest_signals,
                        held_tickers=held_tickers,
                        protected_tickers=self.state.protected_tickers,
                    )

                # 4. Fetch live prices (always — cheap yfinance/T212 call)
                from data_loader import fetch_live_prices
                active_watchlist_tickers = self._get_active_tickers()
                all_relevant = list(set(active_watchlist_tickers + held_tickers))
                try:
                    live_data = fetch_live_prices(all_relevant)
                except Exception as e:
                    print(f"[app] Live price fetch error: {e}")
                    live_data = self.state.live_data if hasattr(self.state, 'live_data') else {}

                # 5. Harvest signals (new or cached)
                if run_pipeline:
                    try:
                        new_signals_df, _meta = future_signals.result(timeout=300)
                        # Only accept new signals if they're non-empty;
                        # don't wipe the display with an empty DataFrame
                        # from a transient error (e.g. weekend, API down).
                        if new_signals_df is not None and not new_signals_df.empty:
                            signals_df = new_signals_df
                            self._last_signal_run = _time.monotonic()
                        else:
                            print("[app] Pipeline returned empty signals — keeping cached data")
                            signals_df = self.state.signals
                    except concurrent.futures.TimeoutError:
                        print("[app] AI pipeline timed out (5min) — keeping cached data")
                        signals_df = self.state.signals
                    finally:
                        self._pipeline_running = False
                else:
                    # Reuse cached signals
                    signals_df = self.state.signals

            # 6. Calculate PnL
            upnl = sum(pos.get('unrealised_pnl', 0.0) for pos in positions)

            # 6b. News data
            news_data = {}
            if self.news_agent:
                news_data = self.news_agent.news_data

            # 6c. Pre-set signals on state so auto_engine.step() can read them
            if signals_df is not None and hasattr(signals_df, 'empty') and not signals_df.empty:
                self.state.signals = signals_df
                self.state.positions = positions
                self.state.live_data = live_data
                self.state.account_info = account_info

            # 6d. Run auto-engine AFTER signals are ready (reads state.signals)
            if run_pipeline:
                try:
                    self.auto_engine.step()
                except Exception as e:
                    print(f"[app] Auto-engine error: {e}")

            # 7. Update state on main thread
            self.call_from_thread(
                self._update_state_and_views,
                signals_df, positions, upnl, live_data, account_info, news_data,
            )
        except Exception as e:
            self._pipeline_running = False
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

        # Update consensus / regime / ensemble metadata
        self.state.consensus_data = self.ai_service.get_consensus_data()
        regime = self.ai_service.get_regime_state()
        if regime is not None:
            self.state.current_regime = regime.regime
            self.state.regime_confidence = regime.confidence
        self.state.ensemble_model_count = self.ai_service.get_ensemble_model_count()

        # Update strategy selector assignments
        self.state.strategy_assignments = getattr(self.ai_service, "_last_strategy_assignments", {})
        # Regime→strategy mapping from config
        cfg = self.ai_service.load_config()
        sp_cfg = cfg.get("strategy_profiles", {})
        from strategy_profiles import REGIME_DEFAULT_MAPPING
        mapping = dict(REGIME_DEFAULT_MAPPING)
        if sp_cfg.get("regime_mapping"):
            mapping.update(sp_cfg["regime_mapping"])
        self.state.regime_strategy_map = mapping

        # Update forecaster metadata
        self.state.statistical_model_count = sum(
            len(v) for v in getattr(self.ai_service, "_last_stat_signals", {}).values()
        )

        # Save snapshot
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.save_snapshot(self.state)
            except Exception as e:
                print(f"[app] Snapshot save error: {e}")

        # Update research lab data
        self._refresh_research_state()

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
        if self.research_view:
            self.research_view.refresh_view()

    # ── Research Data ──────────────────────────────────────────────────

    def _refresh_research_state(self) -> None:
        """Load experiment data from the research/ git repo."""
        try:
            from terminal.research_data import (
                is_research_available, get_experiment_log,
                get_best_score, get_current_config, is_research_running,
                get_live_progress,
            )
            if not is_research_available():
                return

            experiments = get_experiment_log(limit=30)
            self.state.research_experiments = experiments
            self.state.research_best_score = get_best_score(experiments)
            self.state.research_total_experiments = sum(
                1 for e in experiments if e.get("is_experiment")
            )
            self.state.research_current_config = get_current_config()
            self.state.research_is_running = is_research_running()
            self.state.research_live_progress = get_live_progress() or {}
        except Exception as e:
            print(f"[app] Research data error: {e}")

    def action_apply_research(self) -> None:
        """Apply the best research config (train.py) to the live config.json."""
        try:
            from terminal.research_data import get_current_config
            research_cfg = get_current_config()
            if not research_cfg:
                self.notify("No research config found", severity="warning")
                return

            strat = research_cfg.get("strategy", {})
            risk = research_cfg.get("risk", {})

            # Update config.json strategy + risk sections
            if strat:
                self.config.setdefault("strategy", {}).update(strat)
            if risk:
                self.config.setdefault("risk", {}).update(risk)

            self._save_config()
            self.ai_service._config_cache = None  # force reload

            self.notify(
                f"Applied research config: buy={strat.get('threshold_buy')}, "
                f"sell={strat.get('threshold_sell')}, "
                f"stop={risk.get('atr_stop_multiplier')}x",
                severity="information",
            )
        except Exception as e:
            self.notify(f"Apply failed: {e}", severity="error")

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
            self.query_one("#app-header-title", Label).update(self._header_text())
        except Exception:
            pass
            
        self.notify(f"Trading Mode: {mode_label.title()}", severity="information")
        self.refresh_data()

    # ── Asset Class Switching ─────────────────────────────────────────

    def action_switch_asset(self, asset_class: str) -> None:
        """Switch the active asset class (1=stocks, 2=polymarket, 3=crypto)."""
        from types_shared import AssetClass
        valid: list[AssetClass] = ["stocks", "polymarket", "crypto"]
        if asset_class not in valid:
            return

        if asset_class == self.state.active_asset_class:
            self.notify(f"Already on {asset_class.title()}", severity="information")
            return

        # Check if asset class is enabled
        enabled = self.config.get("enabled_asset_classes", ["stocks"])
        asset_cfg = self.config.get(asset_class, {})
        if asset_class != "stocks" and not asset_cfg.get("enabled", False):
            self.notify(
                f"{asset_class.title()} is disabled — set '{asset_class}.enabled: true' in config.json",
                severity="warning",
            )
            return

        # Swap state data (cache old, load new)
        self.state.switch_asset_class(asset_class)

        # Switch watchlist to the asset class's active watchlist
        if asset_class == "stocks":
            self.state.active_watchlist = self.config.get("active_watchlist", "Default")
        else:
            asset_wl = asset_cfg.get("active_watchlist", "")
            self.state.active_watchlist = asset_wl

        # Persist to config
        self.config["active_asset_class"] = asset_class
        if asset_class not in enabled:
            enabled.append(asset_class)
            self.config["enabled_asset_classes"] = enabled
        self._save_config()

        # Update header
        try:
            self.query_one("#app-header-title", Label).update(self._header_text())
        except Exception:
            pass

        # Refresh views
        if self.settings_view:
            self.settings_view.refresh_view()
        if self.watchlist_view:
            self.watchlist_view.refresh_view()

        self.notify(f"Switched to {asset_class.title()}", severity="information")
        self.refresh_data(force_signals=True)

    # ── Watchlist Cycling ──────────────────────────────────────────────

    def action_cycle_watchlist(self) -> None:
        asset = self.state.active_asset_class
        if asset == "stocks":
            watchlists = self.config.get("watchlists", {})
        else:
            watchlists = self.config.get(asset, {}).get("watchlists", {})
        if not watchlists:
            return
        keys = list(watchlists.keys())
        current_idx = keys.index(self.state.active_watchlist) if self.state.active_watchlist in keys else 0
        next_idx = (current_idx + 1) % len(keys)
        self.state.active_watchlist = keys[next_idx]

        if asset == "stocks":
            self.config["active_watchlist"] = self.state.active_watchlist
        else:
            self.config[asset]["active_watchlist"] = self.state.active_watchlist
        self._save_config()

        # Update news agent tickers
        if self.news_agent:
            self.news_agent.update_tickers(self._get_active_tickers())

        self.ai_service._config_cache = None
        self.refresh_data(force_signals=True)

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
            if not self._claude_client:
                raise RuntimeError("Claude client not initialised")

            # Build memory summary from DB
            memory_summary = ""
            if hasattr(self, 'history_manager'):
                try:
                    memory_summary = self.history_manager.get_memory_summary()
                except Exception:
                    pass

            # Detect color grade request
            msg_lower = message.lower()
            is_color_grade = any(
                phrase in msg_lower
                for phrase in [
                    "colour grade", "color grade", "grade portfolio",
                    "grade stocks", "grade my", "grade the",
                ]
            )

            response = self._claude_client.chat_with_context(
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
                memory_summary=memory_summary,
                live_data=self.state.live_data,
            )

            # Parse color grades from response if this was a grade request
            if is_color_grade and response:
                self._parse_color_grades(response)

        except Exception as e:
            response = f"Error: {e}"

        self.call_from_thread(self._add_chat_response, response)

    def _parse_color_grades(self, response: str) -> None:
        """Parse AI response for per-ticker colour grades (GREEN/RED/ORANGE).

        Looks for lines like 'TSLA: GREEN' or 'AAPL: RED' in the response.
        """
        import re
        grades: dict[str, str] = {}
        # Match patterns like "TICKER: GREEN" or "TICKER — RED" or "**TICKER**: ORANGE"
        pattern = re.compile(
            r'\*{0,2}([A-Z][A-Z0-9.]{0,9})\*{0,2}\s*[:—\-–]\s*(GREEN|RED|ORANGE)',
            re.IGNORECASE,
        )
        for match in pattern.finditer(response):
            ticker = match.group(1).upper()
            grade = match.group(2).upper()
            grades[ticker] = grade

        if grades:
            # Map grades to tickers in the signals DataFrame (handle T212 format)
            # The signals use the original ticker names from config
            if self.state.signals is not None and not self.state.signals.empty:
                signal_tickers = set(self.state.signals["ticker"].tolist())
                mapped_grades: dict[str, str] = {}
                for sig_ticker in signal_tickers:
                    sig_upper = sig_ticker.upper()
                    # Try exact match first
                    if sig_upper in grades:
                        mapped_grades[sig_ticker] = grades[sig_upper]
                    else:
                        # Try matching the cleaned ticker name
                        for grade_ticker, grade_val in grades.items():
                            if grade_ticker in sig_upper or sig_upper.startswith(grade_ticker):
                                mapped_grades[sig_ticker] = grade_val
                                break
                if mapped_grades:
                    grades = mapped_grades

            self.state.ai_color_grades = grades
            # Refresh watchlist to show new grades
            self.call_from_thread(self._refresh_watchlist_with_grades)

    def _refresh_watchlist_with_grades(self) -> None:
        """Refresh the watchlist view after colour grades are applied."""
        if hasattr(self, 'watchlist_view') and self.watchlist_view:
            self.watchlist_view.refresh_view()

    def _add_chat_response(self, response: str) -> None:
        self.state.chat_history.append({"role": "ai", "text": response})
        if hasattr(self, 'history_manager'):
            try:
                self.history_manager.save_chat_message("ai", response)
            except Exception:
                pass
        if self.chat_view:
            self.chat_view.refresh_view()
        self._maybe_extract_memories()

    def _maybe_extract_memories(self) -> None:
        """Memory extraction disabled — was spawning Claude CLI subprocesses
        every 5 AI messages, burning credits even when user wasn't chatting.
        Chat history is already persisted in SQLite; that's sufficient."""
        pass

    # ── Chart ──────────────────────────────────────────────────────────

    @work(thread=True)
    def action_show_chart(self) -> None:
        # Get selected ticker from watchlist cursor
        ticker = self._get_selected_watchlist_ticker()
        if not ticker:
            return

        closes: list = []

        if self.state.active_asset_class == "polymarket":
            # Polymarket: fetch probability history via condition_id
            condition_id = self.state.polymarket_id_map.get(ticker, "")
            if condition_id:
                try:
                    from polymarket.data_loader import fetch_market_history
                    history = fetch_market_history(condition_id)
                    if not history.empty and "price" in history.columns:
                        closes = [float(p) for p in history["price"].dropna().tolist()]
                except Exception as e:
                    print(f"[chart] polymarket history error: {e}")
        else:
            # Stocks/crypto: yfinance
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

            # Fallback: T212 position data (avg_price → current_price)
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

    # ── Protect / Lock Ticker ───────────────────────────────────────────

    def _extract_plain_ticker(self, raw: str) -> str:
        """Strip Rich markup and decorators from a ticker string."""
        import re
        cleaned = re.sub(r'\[.*?\]', '', raw)
        cleaned = cleaned.replace('*', '').replace('\U0001f512', '').strip()
        return cleaned.upper()

    def action_toggle_protect(self) -> None:
        """Toggle protection (lock) status of the selected ticker.

        Stores the original-case ticker from the signals DF so that
        ``is_protected`` checks in WatchlistView match exactly.
        Also stores the uppercased form so both variants are covered.
        """
        raw = self._get_selected_watchlist_ticker()
        if not raw:
            return
        ticker = self._extract_plain_ticker(raw)
        if not ticker:
            return

        # Check membership case-insensitively
        existing_match = self._find_protected_match(ticker)
        if existing_match is not None:
            self.state.protected_tickers.discard(existing_match)
            # Also remove the other case variant if present
            self.state.protected_tickers.discard(ticker)
            self.state.protected_tickers.discard(ticker.upper())
            self.notify(f"{ticker} UNLOCKED — trading enabled", severity="information")
        else:
            self.state.protected_tickers.add(ticker)
            self.notify(f"{ticker} LOCKED — trading disabled", severity="warning")

        self.config["protected_tickers"] = sorted(list(self.state.protected_tickers))
        self._save_config()
        if self.watchlist_view:
            self.watchlist_view.refresh_view()

    def _find_protected_match(self, ticker: str) -> str | None:
        """Case-insensitive lookup in protected_tickers. Returns the stored
        form if found, else None."""
        upper = ticker.upper()
        for t in self.state.protected_tickers:
            if t.upper() == upper:
                return t
        return None

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
            if not self._claude_client:
                raise RuntimeError("Claude client not initialised")
            results = self._claude_client.search_tickers(query)
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
            if not self._claude_client:
                raise RuntimeError("Claude client not initialised")
            current_tickers = self._get_active_tickers()
            results = self._claude_client.recommend_tickers(current_tickers, category=category, count=5)
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

            # Current config values (expanded for day trading)
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

            # 2. Ask Claude for concrete changes
            if not self._claude_client:
                self.call_from_thread(self._add_chat_response, "[AI OPTIMIZER] Claude client not available.")
                return
            client = self._claude_client

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

            text = client._call(prompt, task_type="medium")
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
            for key in ("sklearn_weight", "ai_weight", "news_weight"):
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
                        val = max(0.50, min(0.70, val))
                    else:
                        val = max(0.30, min(0.50, val))
                    old = strat_cfg.get(key, 0)
                    strat_cfg[key] = val
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])

            # Timeframe weights
            tf_weights = self.config.get("timeframes", {}).get("weights", {})
            tf_keys = {"tf_weight_1d": "1", "tf_weight_5d": "5", "tf_weight_20d": "20"}
            for opt_key, cfg_key in tf_keys.items():
                if opt_key in changes:
                    val = max(0.05, min(0.90, float(changes[opt_key])))
                    old = tf_weights.get(cfg_key, 0)
                    tf_weights[cfg_key] = val
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_config_change("AI_OPTIMIZER", opt_key, str(old), str(val), explanation[:200])
            if "timeframes" not in self.config:
                self.config["timeframes"] = {}
            self.config["timeframes"]["weights"] = tf_weights

            # Risk parameters
            risk_bounds = {
                "kelly_fraction_cap": (0.20, 0.50),
                "atr_stop_multiplier": (1.0, 3.0),
            }
            for key, (lo, hi) in risk_bounds.items():
                if key in changes:
                    val = max(lo, min(hi, float(changes[key])))
                    old = risk_cfg.get(key, 0)
                    risk_cfg[key] = val
                    if hasattr(self, 'history_manager'):
                        self.history_manager.log_config_change("AI_OPTIMIZER", key, str(old), str(val), explanation[:200])
            self.config["risk"] = risk_cfg

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
        """Periodic self-optimization — uses Sonnet (not Opus) every 4 hours.
        Skips if insufficient accuracy data to base decisions on."""
        tracker = getattr(self.ai_service, "_accuracy_tracker", None)
        if tracker is None:
            return
        try:
            stats = tracker.get_rolling_accuracy("final", window_days=14)
            # Only optimise if we have meaningful data (accuracy > 0 means resolved predictions exist)
            if stats <= 0.0:
                return
        except Exception:
            return
        self.action_ai_optimise()

    # ── History Analysis ──────────────────────────────────────────────

    @work(thread=True)
    def action_analyze_history(self) -> None:
        """Deep dive analysis of historical data using Claude."""
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

            results = self._claude_client._call(prompt, task_type="medium")
            self.call_from_thread(self._add_chat_response, f"[HISTORICAL ANALYSIS]\n{results}")
        except Exception as e:
            self.call_from_thread(self._handle_refresh_error, f"History Error: {e}")

    # ── Continuous AI Market Scanner ──────────────────────────────────

    @work(thread=True)
    def _ai_market_scan(self) -> None:
        """Periodic market intelligence scan — finds opportunities and alerts.

        Runs every 30 minutes. Uses locally-available signal data instead of
        making additional Claude CLI calls, to avoid burning credits.  Only
        calls Claude when it has a genuinely notable finding to expand on.
        """
        try:
            # Build scan from cached signal data — NO Claude call needed
            urgent_lines: list[str] = []
            risk_lines: list[str] = []

            if self.state.signals is not None and not self.state.signals.empty:
                for _, row in self.state.signals.iterrows():
                    ticker = row.get("ticker", "?")
                    prob = float(row.get("prob_up", 0.5))
                    signal = str(row.get("signal", "HOLD"))
                    if prob >= 0.7 and signal.upper() == "BUY":
                        urgent_lines.append(f"  {ticker}: STRONG BUY (prob {prob:.2f})")
                    elif prob <= 0.3 and signal.upper() == "SELL":
                        urgent_lines.append(f"  {ticker}: STRONG SELL (prob {prob:.2f})")

            for p in self.state.positions:
                pnl = p.get("unrealised_pnl", 0.0)
                ticker = p.get("ticker", "?")
                if pnl < -50:
                    risk_lines.append(f"  {ticker}: PnL ${pnl:.2f} — consider reviewing")

            if not urgent_lines and not risk_lines:
                return  # All clear — no chat spam

            scan_msg = "[MARKET SCAN]\n"
            if urgent_lines:
                scan_msg += "URGENT SIGNALS:\n" + "\n".join(urgent_lines) + "\n"
            if risk_lines:
                scan_msg += "RISK ALERTS:\n" + "\n".join(risk_lines)

            self.call_from_thread(self._add_chat_response, scan_msg)

        except Exception as e:
            print(f"[app] Market scan error: {e}")

    # ── Hourly Watchlist Review ────────────────────────────────────────

    def _hourly_watchlist_review(self) -> None:
        """Periodic watchlist health check — logs stale tickers but does NOT
        auto-remove them.  Watchlist modifications should be user-initiated.
        No Claude CLI calls — uses cached signal data only."""
        # Intentionally a no-op now.  The user controls their own watchlist
        # via +/- keys and the AI recommend modal.  Autonomous removal was
        # confusing and wasted Claude credits.
        pass

    # ── Config Helpers ─────────────────────────────────────────────────

    def _save_config(self) -> None:
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)


def run_terminal() -> None:
    app = TradingTerminalApp()
    app.run()


if __name__ == "__main__":
    run_terminal()
