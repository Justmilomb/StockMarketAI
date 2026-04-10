"""Simple app — clean, minimal trading view matching the website aesthetic."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QInputDialog,
    QLabel,
    QMainWindow,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from desktop.design import BG, BORDER, GLOW, RED, AMBER, TEXT, TEXT_DIM, TEXT_MID, FONT_FAMILY
from desktop.simple.theme import COLORS, SIMPLE_QSS
from desktop.simple.widgets.header import HeaderBar
from desktop.simple.widgets.ticker_card import TickerCard

logger = logging.getLogger("blank.simple")


class BackgroundTask(QThread):
    """Generic background worker."""

    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, fn: Any) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
            self.result_ready.emit(result)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


def load_config(path: Path) -> dict:
    """Load config.json, return empty dict on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class SimpleWindow(QMainWindow):
    """Minimal trading terminal — card-based layout, website aesthetic."""

    def __init__(
        self,
        config_path: Path = Path("config.json"),
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.config = load_config(config_path)

        # ── Services ─────────────────────────────────────────────────
        self._claude_client: Optional[Any] = None
        self._news_agent: Optional[Any] = None
        self._ai_service: Optional[Any] = None
        self._broker_service: Optional[Any] = None
        self._active_workers: List[BackgroundTask] = []

        # State
        self._signals: Optional[Any] = None  # DataFrame
        self._live_data: Dict[str, Dict] = {}
        self._news_sentiment: Dict[str, Dict] = {}
        self._last_refresh: float = 0.0

        self._init_services()
        self._build_ui()
        self._setup_timers()

        # Stage 1: fast price fetch (instant), then stage 2: full pipeline
        QTimer.singleShot(200, self._fetch_prices_fast)
        QTimer.singleShot(500, self._run_pipeline)

    # ══════════════════════════════════════════════════════════════════
    #  Service Initialisation
    # ══════════════════════════════════════════════════════════════════

    def _init_services(self) -> None:
        """Initialise shared backend services (same as MainWindow)."""
        try:
            from ai_service import AiService
            self._ai_service = AiService(config_path=self.config_path)
        except Exception as exc:
            logger.warning("Could not init AiService: %s", exc)

        try:
            from broker_service import BrokerService
            self._broker_service = BrokerService(self.config)
        except Exception as exc:
            logger.warning("Could not init BrokerService: %s", exc)

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
        except Exception as exc:
            logger.warning("Could not init ClaudeClient: %s", exc)

        try:
            from news_agent import NewsAgent
            if self._claude_client:
                from claude_client import ClaudeClient
                interval = self.config.get("news", {}).get("refresh_interval_minutes", 5)
                # Own ClaudeClient so sentiment doesn't queue behind pipeline
                news_claude = ClaudeClient(self._claude_client.config)
                self._news_agent = NewsAgent(news_claude, refresh_interval_minutes=interval)
                self._news_agent.update_tickers(self._get_tickers())
                self._news_agent.start()
        except Exception as exc:
            logger.warning("Could not init NewsAgent: %s", exc)

    # ══════════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.setWindowTitle("blank")
        self.setMinimumSize(600, 500)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = HeaderBar()
        self._header.add_clicked.connect(self._add_ticker)
        self._header.refresh_clicked.connect(self._refresh)
        root.addWidget(self._header)

        # Update header status
        ai_ok = self._claude_client and getattr(self._claude_client, "available", False)
        broker_live = self._broker_service and getattr(self._broker_service, "is_live", False)
        if ai_ok and broker_live:
            self._header.set_status("all systems operational", True)
        elif ai_ok:
            self._header.set_status("paper mode", True)
        else:
            self._header.set_status("ai offline", False)

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(28, 20, 28, 20)
        self._card_layout.setSpacing(12)
        self._card_layout.addStretch()

        scroll.setWidget(self._card_container)
        root.addWidget(scroll, 1)

        # Status bar
        status = QStatusBar()
        status.setStyleSheet(f"""
            QStatusBar {{
                background: {BG};
                color: {TEXT_DIM};
                border-top: 1px solid {BORDER};
                font-size: 12px; font-weight: 300;
                font-family: {FONT_FAMILY};
                padding: 4px 28px;
            }}
        """)
        self.setStatusBar(status)

        self._time_label = QLabel("--")
        self._time_label.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 12px; font-weight: 300;
            font-family: {FONT_FAMILY};
            padding: 0 8px; background: transparent;
        """)
        status.addPermanentWidget(self._time_label)

        # Populate initial cards
        self._cards: Dict[str, TickerCard] = {}
        self._populate_cards()

    def _populate_cards(self) -> None:
        """Create ticker cards from the active watchlist."""
        # Remove old cards
        for card in self._cards.values():
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        tickers = self._get_tickers()
        if not tickers:
            placeholder = QLabel("no tickers -- press + add to start")
            placeholder.setStyleSheet(f"""
                color: {TEXT_DIM}; font-size: 14px; font-weight: 300;
                font-family: {FONT_FAMILY};
                padding: 60px; background: transparent;
                letter-spacing: 0.02em;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            self._card_layout.insertWidget(0, placeholder)
            self._cards["__placeholder__"] = placeholder  # type: ignore
            return

        for i, ticker in enumerate(tickers):
            card = TickerCard()
            card.update_data(ticker=ticker, signal="--", prob=0.5, summary="loading...")
            card.clicked.connect(self._on_card_clicked)
            self._card_layout.insertWidget(i, card)
            self._cards[ticker] = card

    # ══════════════════════════════════════════════════════════════════
    #  Data Refresh
    # ══════════════════════════════════════════════════════════════════

    def _setup_timers(self) -> None:
        interval_s = self.config.get("refresh_interval_seconds", 120)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(interval_s * 1000)

    @Slot()
    def _refresh(self) -> None:
        """Full refresh: prices first, then pipeline."""
        self._fetch_prices_fast()
        self._run_pipeline()

    # ── Stage 1: Fast prices (2-3 seconds) ───────────────────────────

    def _fetch_prices_fast(self) -> None:
        """Fetch just prices in background — cards populate instantly."""
        self._header.set_status("fetching prices...", True)
        self._run_background(self._fetch_prices_only, self._on_prices)

    def _fetch_prices_only(self) -> Dict[str, Any]:
        """Background: quick yfinance price fetch only."""
        try:
            import yfinance as yf
            from data_loader import _clean_ticker

            tickers = self._get_tickers()
            yf_tickers = [_clean_ticker(t) for t in tickers]
            if not yf_tickers:
                return {}

            batch = yf.download(
                yf_tickers, period="2d", interval="1d",
                progress=False, timeout=15, multi_level_index=False,
            )
            live: Dict[str, Dict] = {}
            for orig, yf_t in zip(tickers, yf_tickers):
                try:
                    if len(yf_tickers) == 1:
                        close_col = batch["Close"]
                    else:
                        close_col = batch["Close"][yf_t] if yf_t in batch["Close"].columns else None
                    if close_col is not None and len(close_col.dropna()) >= 1:
                        vals = close_col.dropna().values
                        cur = float(vals[-1])
                        prev = float(vals[-2]) if len(vals) > 1 else cur
                        chg = ((cur - prev) / prev * 100) if prev else 0
                        live[orig] = {"price": cur, "change_pct": round(chg, 2)}
                except Exception:
                    pass
            return live
        except Exception as exc:
            logger.warning("Price fetch error: %s", exc)
            return {}

    @Slot(object)
    def _on_prices(self, live_data: Dict[str, Any]) -> None:
        """Update cards with prices immediately."""
        if live_data:
            self._live_data.update(live_data)

        self._last_refresh = time.time()
        t = time.strftime("%H:%M")
        self._time_label.setText(f"refreshed {t}")

        for ticker, card in list(self._cards.items()):
            if ticker.startswith("__"):
                continue
            live = self._live_data.get(ticker, {})
            price = float(live.get("price", 0))
            change_pct = float(live.get("change_pct", 0))
            card.update_data(
                ticker=ticker,
                signal="--",
                prob=0.5,
                change_pct=change_pct,
                summary="analysing...",
                price=price,
            )

        self._header.set_status("prices loaded", True)

    # ── Stage 2: Full ML pipeline (1-3 minutes) ─────────────────────

    def _run_pipeline(self) -> None:
        """Run the full ML pipeline in background."""
        self._header.set_status("running ai pipeline...", True)
        self.statusBar().showMessage("generating signals — this takes a minute or two", 120000)
        self._run_background(self._fetch_signals, self._on_signals)

    def _fetch_signals(self) -> Dict[str, Any]:
        """Background: full ML pipeline + news."""
        result: Dict[str, Any] = {}

        if self._ai_service:
            try:
                signals_df, metadata = self._ai_service.get_latest_signals()
                result["signals"] = signals_df
            except Exception as exc:
                logger.warning("Signal pipeline error: %s", exc)

        if self._news_agent:
            try:
                result["news"] = self._news_agent.news_data
            except Exception:
                pass

        return result

    @Slot(object)
    def _on_signals(self, result: Dict[str, Any]) -> None:
        """Main thread: overlay signals onto already-populated cards."""
        import pandas as pd

        if result.get("signals") is not None:
            self._signals = result["signals"]
        if result.get("news"):
            self._news_sentiment.update(result["news"])

        self._header.set_status("all systems operational", True)
        self.statusBar().showMessage("", 0)

        for ticker, card in list(self._cards.items()):
            if ticker.startswith("__"):
                continue

            signal = "--"
            prob = 0.5
            summary = ""

            if self._signals is not None and isinstance(self._signals, pd.DataFrame):
                row = self._signals[self._signals["ticker"] == ticker]
                if not row.empty:
                    r = row.iloc[0]
                    signal = str(r.get("signal", "--"))
                    prob = float(r.get("prob_up", 0.5))
                    reason = str(r.get("reason", ""))
                    ai_rec = str(r.get("ai_rec", ""))
                    summary = ai_rec if ai_rec and ai_rec != "--" else reason

            live = self._live_data.get(ticker, {})
            change_pct = float(live.get("change_pct", 0))
            price = float(live.get("price", 0))

            news = self._news_sentiment.get(ticker, {})
            if not summary and news.get("summary"):
                summary = news["summary"]

            card.update_data(
                ticker=ticker,
                signal=signal,
                prob=prob,
                change_pct=change_pct,
                summary=summary,
                price=price,
            )

    # ══════════════════════════════════════════════════════════════════
    #  Actions
    # ══════════════════════════════════════════════════════════════════

    @Slot()
    def _add_ticker(self) -> None:
        """Prompt user for a ticker to add."""
        text, ok = QInputDialog.getText(
            self, "add ticker", "enter ticker symbol:",
        )
        if ok and text.strip():
            ticker = text.strip().upper()
            watchlists = self.config.get("watchlists", {})
            active = self.config.get("active_watchlist", "Default")
            watchlists.setdefault(active, [])
            if ticker not in watchlists[active]:
                watchlists[active].append(ticker)
                self._save_config()
                self._populate_cards()
                self.statusBar().showMessage(f"added {ticker}", 3000)

    @Slot(str)
    def _on_card_clicked(self, ticker: str) -> None:
        """Expand card or show detail (future: inline expansion)."""
        self.statusBar().showMessage(f"selected {ticker}", 2000)

    # ══════════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════════

    def _get_tickers(self) -> List[str]:
        """Get tickers from the active watchlist."""
        watchlists = self.config.get("watchlists", {})
        active = self.config.get("active_watchlist", "Default")
        return list(watchlists.get(active, []))

    def _save_config(self) -> None:
        """Persist config to disk."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save config: %s", exc)

    def _run_background(self, fn: Any, on_result: Any) -> None:
        """Run a function in a background thread."""
        worker = BackgroundTask(fn)
        worker.result_ready.connect(on_result)
        def _on_error(e: str) -> None:
            self.statusBar().showMessage(f"error: {e}", 5000)
            self._header.set_status("pipeline error", False)

        worker.error_occurred.connect(_on_error)
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()

    def _cleanup_worker(self, worker: BackgroundTask) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass

    def closeEvent(self, event: Any) -> None:
        self._refresh_timer.stop()
        if self._news_agent:
            self._news_agent.stop()
        super().closeEvent(event)
