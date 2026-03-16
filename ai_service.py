from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple, List

import json
import numpy as np
import pandas as pd

from data_loader import fetch_universe_data
from features import build_universe_dataset, latest_feature_rows_per_ticker, FEATURE_COLUMNS
from gemini_client import GeminiClient, GeminiConfig
from model import ModelConfig, load_model, train_model
from strategy import StrategyConfig, generate_signals
import concurrent.futures


ConfigDict = Dict[str, Any]


@dataclass
class AiService:
    """
    Thin service layer around the core ML pipeline, so that other
    parts of the app (like the TUI) can call simple methods without
    knowing implementation details.
    """

    config_path: Path = Path("config.json")
    _config_cache: ConfigDict | None = None
    _model_loaded: bool = False
    _gemini_client: GeminiClient | None = None

    def load_config(self) -> ConfigDict:
        if self._config_cache is None:
            with self.config_path.open("r", encoding="utf-8") as f:
                self._config_cache = json.load(f)
        return self._config_cache

    def _get_universe_data(
        self, 
        cfg: ConfigDict, 
        extra_tickers: List[str] | None = None,
        lookback_days: int | None = None
    ) -> Dict[str, pd.DataFrame]:
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        tickers = watchlists.get(active, cfg.get("tickers", []))
        
        # Combine with extra tickers (like held positions)
        combined = set(tickers)
        if extra_tickers:
            combined.update(extra_tickers)
        
        tickers_list = list(combined)
        
        if lookback_days:
            start_dt = datetime.now() - timedelta(days=lookback_days)
            start_date = start_dt.strftime("%Y-%m-%d")
        else:
            start_date = cfg.get("start_date", "2015-01-01")

        # Ensure end_date is at least today
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        return fetch_universe_data(tickers_list, start_date, end_date)

    def _get_gemini_client(self, cfg: ConfigDict) -> GeminiClient:
        if self._gemini_client is not None:
            return self._gemini_client
        gemini_cfg_raw = cfg.get("gemini", {}) or {}
        config = GeminiConfig(
            model=gemini_cfg_raw.get("model", "gemini-2.5-pro"),
            api_key_env=gemini_cfg_raw.get("api_key_env", "GEMINI_API_KEY"),
        )
        self._gemini_client = GeminiClient(config)
        return self._gemini_client

    def _ensure_model(self, cfg: ConfigDict):
        model_path = Path(cfg.get("model_path", "models/rf_tomorrow_up.joblib"))
        if model_path.exists() and self._model_loaded:
            return load_model(model_path)

        universe_data = self._get_universe_data(cfg)
        X, y, meta = build_universe_dataset(universe_data)

        model_cfg = ModelConfig(model_path=model_path)
        clf = train_model(X, y, meta, model_cfg)
        self._model_loaded = True
        return clf

    def suggest_new_ticker(self) -> str:
        """Suggests a new ticker for the currently active watchlist."""
        cfg = self.load_config()
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        current_tickers = watchlists.get(active, cfg.get("tickers", []))
        
        client = self._get_gemini_client(cfg)
        suggestion = client.suggest_ticker(current_tickers)
        if suggestion and suggestion not in current_tickers:
            # Update config and write to disk
            watchlists[active].append(suggestion)
            cfg["watchlists"] = watchlists
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            # Clear cache to force reload
            self._config_cache = None
            return suggestion
        return ""

    def generate_portfolio_analysis(self, positions: List[Dict[str, Any]], signals_df: pd.DataFrame) -> str:
        """Generates a natural language analysis of the portfolio and current signals."""
        cfg = self.load_config()
        client = self._get_gemini_client(cfg)
        return client.analyze_portfolio(positions, signals_df)

    def get_latest_signals(
        self,
        held_tickers: List[str] | None = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Compute the latest per-ticker signals using the current model.

        Returns:
          - signals_df: DataFrame with columns [ticker, date, prob_up, signal]
          - meta_df: DataFrame with the raw latest feature rows meta (ticker/date)
        """
        cfg = self.load_config()

        # For daily signals, we only need ~90 days of history for indicators
        universe_data = self._get_universe_data(cfg, extra_tickers=held_tickers, lookback_days=90)
        try:
            latest_features_df, latest_meta_df = latest_feature_rows_per_ticker(universe_data)
        except Exception as e:
            print(f"[ai_service] Error generating features: {e}")
            return pd.DataFrame(), pd.DataFrame()

        if latest_features_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        # Sklearn model probabilities
        try:
            clf = self._ensure_model(cfg)
            p_sklearn = clf.predict_proba(latest_features_df.to_numpy(dtype=float))[:, 1]
        except Exception as e:
            print(f"[ai_service] Sklearn prediction error: {e}")
            p_sklearn = np.full(len(latest_features_df), 0.5)

        # Gemini probabilities and reasons
        gemini_client = self._get_gemini_client(cfg)
        
        # Helper for parallel execution
        def analyze_one(ticker_meta: tuple):
            idx, meta_row = ticker_meta
            ticker = str(meta_row["ticker"])
            try:
                df_ticker = universe_data[ticker]
                recent_closes = df_ticker["Close"].tail(30).tolist()
                feature_row = latest_features_df.loc[ticker].to_dict()
                
                # 1. Get raw probability and reason
                out = gemini_client.get_signal_for_ticker(ticker, recent_closes, feature_row)
                p_val = float(out.get("p_up_gemini", 0.5))
                
                # 2. Get high-level recommendation
                rec_out = gemini_client.get_recommendation(
                    ticker=ticker,
                    current_position=None,
                    prob_up=p_val,
                    news_sentiment=0.0,
                    news_summary="",
                    features=feature_row
                )
                return {
                    "p_up": p_val,
                    "reason": str(out.get("reason", "No reason provided.")),
                    "ai_rec": rec_out.get("action", "HOLD")
                }
            except Exception as e:
                print(f"[ai_service] Gemini error for {ticker}: {e}")
                return {"p_up": 0.5, "reason": f"Error: {e}", "ai_rec": "HOLD"}

        # Execute in parallel
        p_gemini_list = []
        reasons = []
        ai_recs = []
        
        # Group data for mapping
        items = list(latest_meta_df.iterrows())
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(analyze_one, items))
            
        for res in results:
            p_gemini_list.append(res["p_up"])
            reasons.append(res["reason"])
            ai_recs.append(res["ai_rec"])

        p_gemini = np.array(p_gemini_list, dtype=float)

        ai_cfg = cfg.get("ai", {}) or {}
        w_sklearn = float(ai_cfg.get("sklearn_weight", 0.5))
        w_gemini = float(ai_cfg.get("gemini_weight", 0.3))
        # w_news = float(ai_cfg.get("news_weight", 0.2)) # Placeholder for future expansion

        p_final = w_sklearn * p_sklearn + w_gemini * p_gemini

        strat_cfg_raw = cfg.get("strategy", {})
        strat_cfg = StrategyConfig(
            threshold_buy=strat_cfg_raw.get("threshold_buy", 0.6),
            threshold_sell=strat_cfg_raw.get("threshold_sell", 0.4),
            max_positions=strat_cfg_raw.get("max_positions", 5),
            position_size_fraction=strat_cfg_raw.get("position_size_fraction", 0.2),
        )

        signals_df = generate_signals(
            p_final, latest_meta_df, strat_cfg,
            held_tickers=held_tickers or [],
        )
        signals_df["p_up_sklearn"] = p_sklearn
        signals_df["p_up_gemini"] = p_gemini
        signals_df["p_up_final"] = p_final
        signals_df["reason"] = reasons
        signals_df["ai_rec"] = ai_recs
        return signals_df, latest_meta_df

    def retrain_model(self) -> None:
        """
        Force a full retrain of the model using the latest configuration.
        """
        cfg = self.load_config()
        universe_data = self._get_universe_data(cfg)
        X, y, meta = build_universe_dataset(universe_data)

        model_path = Path(cfg.get("model_path", "models/rf_tomorrow_up.joblib"))
        model_cfg = ModelConfig(model_path=model_path)
        train_model(X, y, meta, model_cfg)
        self._model_loaded = True

