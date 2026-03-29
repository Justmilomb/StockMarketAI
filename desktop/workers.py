"""Background worker threads for the desktop app."""
from __future__ import annotations
from typing import Any, Dict, Optional
from PySide6.QtCore import QThread, Signal

class BackgroundTask(QThread):
    """Generic worker that runs a callable in a background thread."""
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))


class RefreshWorker(QThread):
    """Dedicated worker for the main refresh loop.

    Fetches broker data (positions, account, orders, live prices)
    and optionally runs the full AI signal pipeline.
    """
    finished_signal = Signal(object)  # Dict with all results
    error_signal = Signal(str)

    def __init__(
        self,
        ai_service: Any,
        broker_service: Any,
        news_agent: Any,
        config: Dict[str, Any],
        state: Any,
        run_signals: bool = False,
    ) -> None:
        super().__init__()
        self._ai = ai_service
        self._broker = broker_service
        self._news = news_agent
        self._config = config
        self._state = state
        self._run_signals = run_signals

    def run(self) -> None:
        result: Dict[str, Any] = {}
        try:
            # Always fetch broker data
            try:
                result["positions"] = self._broker.get_positions()
            except Exception:
                result["positions"] = []

            try:
                result["account_info"] = self._broker.get_account_info()
            except Exception:
                result["account_info"] = {}

            try:
                result["recent_orders"] = self._broker.get_orders()
            except Exception:
                result["recent_orders"] = []

            # Live prices
            try:
                live_data = {}
                watchlist_name = self._state.active_watchlist
                tickers = self._config.get("watchlists", {}).get(watchlist_name, [])
                # Try broker prices first, fall back to yfinance
                for t in tickers:
                    try:
                        price_info = self._broker.get_live_price(t)
                        if price_info:
                            live_data[t] = price_info
                    except Exception:
                        pass
                result["live_data"] = live_data
            except Exception:
                result["live_data"] = {}

            # News sentiment
            if self._news:
                try:
                    result["news_sentiment"] = self._news.get_all_sentiment()
                except Exception:
                    result["news_sentiment"] = {}

            # AI signals (expensive — only when requested)
            if self._run_signals:
                try:
                    if self._news:
                        try:
                            news_data = self._news.get_all_sentiment()
                            self._ai.update_news_data(news_data)
                        except Exception:
                            pass

                    signals_df, metadata = self._ai.get_latest_signals()
                    result["signals"] = signals_df

                    # Extract metadata
                    if metadata:
                        result["consensus_data"] = metadata.get("consensus_data", {})
                        regime = metadata.get("regime_state")
                        if regime:
                            result["current_regime"] = getattr(regime, "regime", "unknown")
                            result["regime_confidence"] = getattr(regime, "confidence", 0.0)
                        result["ensemble_model_count"] = metadata.get("model_count", 0)

                    # Strategy assignments
                    strategy_assigns = getattr(self._ai, "_last_strategy_assignments", {})
                    if strategy_assigns:
                        result["strategy_assignments"] = strategy_assigns

                except Exception as e:
                    result["signals"] = None
                    print(f"[RefreshWorker] Signal pipeline error: {e}")

            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))
