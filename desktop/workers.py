"""Background worker threads for the desktop app."""
from __future__ import annotations

import logging
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

    Fetches broker data (positions, account, orders, live prices)
    and optionally runs the full AI signal pipeline.
    Asset-class aware — stocks use Trading 212, polymarket uses Gamma API.
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
        asset_class = self._state.active_asset_class
        if asset_class == "polymarket":
            self._run_polymarket()
        else:
            self._run_stocks()

    def _run_stocks(self) -> None:
        """Refresh loop for stocks — broker data + AI signals."""
        result: Dict[str, Any] = {}
        try:
            try:
                result["positions"] = self._broker.get_positions()
            except Exception:
                result["positions"] = []

            try:
                result["account_info"] = self._broker.get_account_info()
            except Exception:
                result["account_info"] = {}

            try:
                result["recent_orders"] = self._broker.get_pending_orders()
            except Exception:
                result["recent_orders"] = []

            # Live prices — from T212 positions + yfinance for the rest
            try:
                live_data: Dict[str, Any] = {}
                watchlist_name = self._state.active_watchlist
                tickers = self._config.get("watchlists", {}).get(watchlist_name, [])

                # Extract current prices from broker positions
                for pos in result.get("positions", []):
                    t = pos.get("ticker", "")
                    cur = pos.get("current_price", 0)
                    avg = pos.get("avg_price", 0)
                    if t and cur:
                        change_pct = ((cur - avg) / avg * 100) if avg else 0
                        live_data[t] = {"price": cur, "change_pct": change_pct}

                # Batch fetch remaining tickers from yfinance
                missing = [t for t in tickers if t not in live_data]
                if missing:
                    try:
                        import yfinance as yf
                        batch = yf.download(
                            missing, period="2d", interval="1d",
                            progress=False, timeout=15, group_by="ticker",
                        )
                        if batch is not None and not batch.empty:
                            for t in missing:
                                try:
                                    if len(missing) == 1:
                                        # Single ticker: columns are flat
                                        cols = batch
                                    else:
                                        cols = batch[t] if t in batch.columns.get_level_values(0) else None
                                    if cols is None or cols.empty:
                                        continue
                                    cols = cols.dropna()
                                    if len(cols) < 1:
                                        continue
                                    cur_price = float(cols["Close"].iloc[-1])
                                    if len(cols) >= 2:
                                        prev_close = float(cols["Close"].iloc[-2])
                                        day_chg = ((cur_price - prev_close) / prev_close * 100) if prev_close else 0
                                    else:
                                        day_chg = 0
                                    live_data[t] = {"price": cur_price, "change_pct": round(day_chg, 2)}
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.debug("yfinance batch fetch failed: %s", e)

                result["live_data"] = live_data
            except Exception:
                result["live_data"] = {}

            # News sentiment
            if self._news:
                try:
                    result["news_sentiment"] = self._news.news_data
                except Exception:
                    result["news_sentiment"] = {}

            # AI signals (expensive — only when requested)
            if self._run_signals:
                try:
                    if self._news:
                        try:
                            news_data = self._news.news_data
                            self._ai.update_news_data(news_data)
                        except Exception:
                            pass

                    signals_df, metadata = self._ai.get_latest_signals()
                    result["signals"] = signals_df

                    if metadata:
                        result["consensus_data"] = metadata.get("consensus_data", {})
                        regime = metadata.get("regime_state")
                        if regime:
                            result["current_regime"] = getattr(regime, "regime", "unknown")
                            result["regime_confidence"] = getattr(regime, "confidence", 0.0)
                        result["ensemble_model_count"] = metadata.get("model_count", 0)

                    strategy_assigns = getattr(self._ai, "_last_strategy_assignments", {})
                    if strategy_assigns:
                        result["strategy_assignments"] = strategy_assigns

                except Exception as e:
                    result["signals"] = None
                    logger.warning("Stock signal pipeline error: %s", e)

            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))

    def _run_polymarket(self) -> None:
        """Refresh loop for polymarket — fetch markets from Gamma API."""
        result: Dict[str, Any] = {}
        try:
            poly_cfg = self._config.get("polymarket", {})
            categories = poly_cfg.get("categories", ["crypto"])
            category = categories[0] if categories else "crypto"

            # Fetch live market data
            try:
                from polymarket.data_loader import fetch_markets
                events = fetch_markets(
                    active_only=True,
                    min_volume=float(poly_cfg.get("min_volume", 0)),
                    limit=int(poly_cfg.get("max_markets", 50)),
                    category=category,
                )

                # Build live_data and a simple signals-like structure
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
                result["signals"] = None
                result["live_data"] = {}
                result["positions"] = []
                result["recent_orders"] = []

            # Run full polymarket pipeline if signals requested
            if self._run_signals:
                try:
                    signals_df, metadata = self._ai.get_latest_signals()
                    if signals_df is not None:
                        result["signals"] = signals_df
                    if metadata:
                        result["consensus_data"] = metadata.get("consensus_data", {})
                except Exception as e:
                    logger.warning("Polymarket signal pipeline error: %s", e)

            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))
