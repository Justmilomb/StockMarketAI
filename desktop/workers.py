"""Background worker threads for the desktop app."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


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

    When skip_broker=True, skips broker data fetch (phases 1-4) and goes
    straight to news + AI signals.  Broker data should be fetched
    separately first so the UI populates before the slow pipeline starts.
    """
    finished_signal = Signal(object)  # Dict with all results
    error_signal = Signal(str)
    progress_signal = Signal(str)     # Status updates: "phase: detail"

    def __init__(
        self,
        ai_service: Any,
        broker_service: Any,
        news_agent: Any,
        config: Dict[str, Any],
        state: Any,
        run_signals: bool = False,
        skip_broker: bool = False,
    ) -> None:
        super().__init__()
        self._ai = ai_service
        self._broker = broker_service
        self._news = news_agent
        self._config = config
        self._state = state
        self._run_signals = run_signals
        self._skip_broker = skip_broker

    def run(self) -> None:
        asset_class = self._state.active_asset_class
        if asset_class == "polymarket":
            self._run_polymarket()
        else:
            self._run_stocks()

    def _run_stocks(self) -> None:
        """Refresh loop for stocks — broker data + AI signals."""
        result: Dict[str, Any] = {}
        errors: List[str] = []
        t0 = time.monotonic()

        if not self._skip_broker:
            # ── Phase 1: Broker positions ────────────────────────────
            self.progress_signal.emit("Fetching positions...")
            try:
                result["positions"] = self._broker.get_positions()
            except Exception as e:
                result["positions"] = []
                errors.append(f"Positions: {e}")

            # ── Phase 2: Account info ────────────────────────────────
            self.progress_signal.emit("Fetching account info...")
            try:
                result["account_info"] = self._broker.get_account_info()
            except Exception as e:
                result["account_info"] = {}
                errors.append(f"Account: {e}")

            # ── Phase 3: Pending orders ──────────────────────────────
            self.progress_signal.emit("Fetching orders...")
            try:
                result["recent_orders"] = self._broker.get_pending_orders()
            except Exception as e:
                result["recent_orders"] = []
                errors.append(f"Orders: {e}")

            # ── Phase 4: Live prices ─────────────────────────────────
            self.progress_signal.emit("Fetching live prices...")
            try:
                live_data: Dict[str, Any] = {}
                watchlist_name = self._state.active_watchlist
                tickers = self._config.get("watchlists", {}).get(watchlist_name, [])

                for pos in result.get("positions", []):
                    t = pos.get("ticker", "")
                    cur = pos.get("current_price", 0)
                    avg = pos.get("avg_price", 0)
                    if t and cur:
                        change_pct = ((cur - avg) / avg * 100) if avg else 0
                        live_data[t] = {"price": cur, "change_pct": change_pct}

                missing = [t for t in tickers if t not in live_data]
                if missing:
                    self.progress_signal.emit(f"Fetching prices for {len(missing)} tickers...")
                    try:
                        import yfinance as yf
                        from data_loader import _clean_ticker

                        yf_to_t212 = {_clean_ticker(t): t for t in missing}
                        for yf_t, orig_t in yf_to_t212.items():
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
                        logger.debug("yfinance batch fetch failed: %s", e)
                        errors.append(f"Prices: {e}")

                result["live_data"] = live_data
            except Exception as e:
                result["live_data"] = {}
                errors.append(f"Live data: {e}")

        # ── Phase 5: News sentiment ──────────────────────────────────
        if self._news:
            self.progress_signal.emit("Loading news sentiment...")
            try:
                result["news_sentiment"] = self._news.news_data
            except Exception as e:
                result["news_sentiment"] = {}
                errors.append(f"News: {e}")

        # ── Phase 6: AI signal pipeline (expensive) ──────────────────
        if self._run_signals:
            self.progress_signal.emit("Running AI signal pipeline...")
            try:
                if self._news:
                    try:
                        news_data = self._news.news_data
                        self._ai.update_news_data(news_data)
                    except Exception:
                        pass

                signals_df, _meta_df = self._ai.get_latest_signals()
                result["signals"] = signals_df

                last_consensus = getattr(self._ai, "_last_consensus", None)
                if last_consensus:
                    result["consensus_data"] = last_consensus

                regime_state = getattr(self._ai, "_last_regime", None)
                if regime_state:
                    result["current_regime"] = getattr(regime_state, "regime", "unknown")
                    result["regime_confidence"] = getattr(regime_state, "confidence", 0.0)

                result["ensemble_model_count"] = self._ai.get_ensemble_model_count()

                strategy_assigns = getattr(self._ai, "_last_strategy_assignments", {})
                if strategy_assigns:
                    result["strategy_assignments"] = strategy_assigns

            except Exception as e:
                result["signals"] = None
                errors.append(f"AI pipeline: {e}")
                logger.warning("Stock signal pipeline error: %s", e)

        # ── Done ─────────────────────────────────────────────────────
        elapsed = time.monotonic() - t0
        result["_errors"] = errors
        result["_elapsed"] = round(elapsed, 1)

        if errors:
            self.progress_signal.emit(f"Done in {elapsed:.0f}s — {len(errors)} error(s)")
        else:
            self.progress_signal.emit(f"Done in {elapsed:.0f}s")

        try:
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))

    def _run_polymarket(self) -> None:
        """Refresh loop for polymarket — fetch markets from Gamma API."""
        result: Dict[str, Any] = {}
        errors: List[str] = []

        self.progress_signal.emit("Fetching Polymarket data...")
        try:
            poly_cfg = self._config.get("polymarket", {})
            categories = poly_cfg.get("categories", ["crypto"])
            category = categories[0] if categories else "crypto"

            try:
                from polymarket.data_loader import fetch_markets
                events = fetch_markets(
                    active_only=True,
                    min_volume=float(poly_cfg.get("min_volume", 0)),
                    limit=int(poly_cfg.get("max_markets", 50)),
                    category=category,
                )

                import pandas as pd
                live_data: Dict[str, Any] = {}
                signal_rows: List[Dict[str, Any]] = []

                for event in events:
                    cid = event.condition_id
                    yes_price = event.outcome_prices.get("Yes", 0.5)
                    no_price = event.outcome_prices.get("No", 0.5)

                    live_data[cid] = {
                        "price": yes_price,
                        "change_pct": 0,
                    }

                    signal_rows.append({
                        "ticker": event.question[:60],
                        "prob_up": yes_price,
                        "signal": "BUY" if yes_price > 0.6 else "SELL" if yes_price < 0.4 else "HOLD",
                        "ai_rec": f"Vol: ${event.volume_24h:,.0f}",
                        "condition_id": cid,
                    })

                result["signals"] = pd.DataFrame(signal_rows) if signal_rows else None
                result["live_data"] = live_data
                result["positions"] = []
                result["recent_orders"] = []
                result["account_info"] = {}
                result["news_sentiment"] = {}

            except Exception as e:
                logger.warning("Polymarket fetch error: %s", e)
                errors.append(f"Polymarket fetch: {e}")
                result["signals"] = None
                result["live_data"] = {}
                result["positions"] = []
                result["recent_orders"] = []

            if self._run_signals:
                self.progress_signal.emit("Running Polymarket AI pipeline...")
                try:
                    signals_df, metadata = self._ai.get_latest_signals()
                    if signals_df is not None:
                        result["signals"] = signals_df
                    if metadata:
                        result["consensus_data"] = metadata.get("consensus_data", {})
                except Exception as e:
                    errors.append(f"Polymarket AI: {e}")
                    logger.warning("Polymarket signal pipeline error: %s", e)

            result["_errors"] = errors
            self.progress_signal.emit("Done" if not errors else f"Done — {len(errors)} error(s)")
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))
