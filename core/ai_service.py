from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from consensus import ConsensusEngine
from data_loader import fetch_universe_data
from features import build_universe_dataset, latest_feature_rows_per_ticker, FEATURE_COLUMNS
from features_advanced import (
    FEATURE_COLUMNS_V2,
    latest_feature_rows_v2,
    build_universe_dataset_v2,
)
from forecaster_statistical import StatisticalForecaster
from accuracy_tracker import AccuracyTracker
from claude_client import ClaudeClient, ClaudeConfig
from claude_personas import ClaudePersonaAnalyzer
from model import ModelConfig, load_model, train_model
from pipeline_tracker import PipelineTracker
from regime import RegimeDetector
from risk_manager import RiskManager
from strategy import StrategyConfig, generate_signals
from strategy_selector import StrategySelector
from strategy_profiles import load_research_profiles, REGIME_DEFAULT_MAPPING
from timeframe import MultiTimeframeEnsemble
from types_shared import (
    AssetClass,
    ConsensusResult,
    EnsembleConfig,
    ForecasterSignal,
    PersonaSignal,
    ModelSignal,
    RegimeState,
)

# Polymarket imports (lazy-safe — only used when asset_class == "polymarket")
try:
    from polymarket.types import PolymarketConfig
except ImportError:
    PolymarketConfig = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

ConfigDict = Dict[str, Any]


@dataclass
class AiService:
    """Orchestration hub for the 1000-analyst ensemble pipeline.

    Wires together: V2 features, multi-timeframe ensemble, regime detection,
    Claude personas, consensus engine, and risk management — all lazily
    initialised on first use.
    """

    config_path: Path = Path("config.json")
    _config_cache: ConfigDict | None = None
    _model_loaded: bool = False
    _claude_client: ClaudeClient | None = None

    # Lazy-init components
    _timeframe_ensemble: MultiTimeframeEnsemble | None = None
    _regime_detector: RegimeDetector | None = None
    _persona_analyzer: ClaudePersonaAnalyzer | None = None
    _risk_manager: RiskManager | None = None
    _consensus_engine: ConsensusEngine | None = None
    _statistical_forecaster: StatisticalForecaster | None = None
    _accuracy_tracker: AccuracyTracker | None = None
    _force_retrain: bool = False

    # Pipeline progress tracker (set by terminal app)
    tracker: PipelineTracker | None = None

    # Expose latest features for auto_engine risk manager
    _last_features_df: pd.DataFrame | None = None

    # Latest news sentiment data
    _last_news_data: Dict[str, Any] = field(default_factory=dict)

    # Strategy selector assignments for TUI display
    _last_strategy_assignments: Dict[str, Any] = field(default_factory=dict)

    def load_config(self) -> ConfigDict:
        if self._config_cache is None:
            if not self.config_path.exists():
                # Desktop app creates the default; if running headless, use
                # the desktop state module's DEFAULT_CONFIG as fallback.
                try:
                    from desktop.state import DEFAULT_CONFIG
                    self._config_cache = dict(DEFAULT_CONFIG)
                except ImportError:
                    self._config_cache = {"watchlists": {"Default": []}, "active_watchlist": "Default"}
                return self._config_cache
            with self.config_path.open("r", encoding="utf-8") as f:
                self._config_cache = json.load(f)
        return self._config_cache

    def get_asset_config(
        self, cfg: ConfigDict, asset_class: AssetClass, key: str, default: Any = None,
    ) -> Any:
        """Read a config value with asset-class-specific override.

        Checks cfg[asset_class][key] first, falls back to cfg[key].
        """
        asset_section = cfg.get(asset_class, {})
        if key in asset_section:
            return asset_section[key]
        return cfg.get(key, default)

    def _get_universe_data(
        self,
        cfg: ConfigDict,
        extra_tickers: List[str] | None = None,
        lookback_days: int | None = None,
    ) -> Dict[str, pd.DataFrame]:
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        tickers = watchlists.get(active, cfg.get("tickers", []))

        combined = set(tickers)
        if extra_tickers:
            combined.update(extra_tickers)

        tickers_list = list(combined)

        if lookback_days:
            start_dt = datetime.now() - timedelta(days=lookback_days)
            start_date = start_dt.strftime("%Y-%m-%d")
        else:
            start_date = cfg.get("start_date", "2015-01-01")

        end_date = datetime.now().strftime("%Y-%m-%d")
        return fetch_universe_data(tickers_list, start_date, end_date)

    # ── Lazy initialisers ─────────────────────────────────────────────

    def _get_claude_client(self, cfg: ConfigDict) -> ClaudeClient:
        if self._claude_client is not None:
            return self._claude_client
        claude_cfg_raw = cfg.get("claude", {}) or {}
        config = ClaudeConfig(
            model=claude_cfg_raw.get("model", "claude-sonnet-4-20250514"),
            model_complex=claude_cfg_raw.get("model_complex", "claude-opus-4-6"),
            model_medium=claude_cfg_raw.get("model_medium", "claude-sonnet-4-20250514"),
            model_simple=claude_cfg_raw.get("model_simple", "claude-haiku-4-5-20251001"),
        )
        self._claude_client = ClaudeClient(config)
        return self._claude_client

    def _ensure_model(self, cfg: ConfigDict) -> Any:
        """Load or train the legacy single RandomForest model."""
        model_path = Path(cfg.get("model_path", "models/rf_tomorrow_up.joblib"))
        if model_path.exists():
            if not self._model_loaded:
                clf = load_model(model_path)
                self._model_loaded = True
                return clf
            return load_model(model_path)

        universe_data = self._get_universe_data(cfg)
        X, y, meta = build_universe_dataset(universe_data)

        model_cfg = ModelConfig(model_path=model_path)
        clf = train_model(X, y, meta, model_cfg)
        self._model_loaded = True
        return clf

    def _ensure_ensemble(self, cfg: ConfigDict, universe_data: Dict[str, pd.DataFrame]) -> MultiTimeframeEnsemble:
        """Load or train the multi-timeframe ensemble."""
        if self._timeframe_ensemble is not None:
            return self._timeframe_ensemble

        ensemble_cfg_raw = cfg.get("ensemble", {})
        ensemble_config = EnsembleConfig(
            n_models=int(ensemble_cfg_raw.get("n_models", 12)),
            stacking_enabled=bool(ensemble_cfg_raw.get("stacking_enabled", True)),
            performance_lookback_days=int(ensemble_cfg_raw.get("performance_lookback_days", 60)),
            min_model_weight=float(ensemble_cfg_raw.get("min_model_weight", 0.02)),
        )

        tf_cfg_raw = cfg.get("timeframes", {})
        horizons = tf_cfg_raw.get("horizons", [1, 5, 20])
        weights_raw = tf_cfg_raw.get("weights", {"1": 0.5, "5": 0.3, "20": 0.2})
        weights = {int(k): float(v) for k, v in weights_raw.items()}

        mte = MultiTimeframeEnsemble(
            horizons=horizons,
            weights=weights,
            ensemble_config=ensemble_config,
        )

        # Try loading pre-trained ensemble
        ensemble_dir = Path(ensemble_config.model_dir)
        horizon_file = ensemble_dir / f"horizon_{horizons[0]}.joblib"
        if horizon_file.exists():
            logger.info("Loading pre-trained multi-timeframe ensemble...")
            mte.load(ensemble_dir)
        else:
            # Train on first run — needs full history
            logger.info("Training multi-timeframe ensemble (first run)...")
            full_data = self._get_universe_data(cfg)
            mte.train_all_horizons(full_data)
            mte.save(ensemble_dir)
            logger.info("Ensemble trained and saved.")

        self._timeframe_ensemble = mte
        return mte

    def _get_regime(self, cfg: ConfigDict, asset_class: AssetClass = "stocks") -> RegimeDetector:
        if self._regime_detector is not None:
            return self._regime_detector
        regime_cfg = self.get_asset_config(cfg, asset_class, "regime", {})
        self._regime_detector = RegimeDetector(regime_cfg)
        return self._regime_detector

    def _get_claude_personas(self, cfg: ConfigDict) -> ClaudePersonaAnalyzer | None:
        personas_cfg = cfg.get("claude_personas", {})
        if not personas_cfg.get("enabled", True):
            return None
        if self._persona_analyzer is not None:
            return self._persona_analyzer
        client = self._get_claude_client(cfg)
        persona_list = personas_cfg.get("personas", None)
        self._persona_analyzer = ClaudePersonaAnalyzer(client, persona_list)
        return self._persona_analyzer

    def _get_risk_manager(self, cfg: ConfigDict, asset_class: AssetClass = "stocks") -> RiskManager:
        if self._risk_manager is not None:
            return self._risk_manager
        risk_cfg = self.get_asset_config(cfg, asset_class, "risk", {})
        self._risk_manager = RiskManager(risk_cfg)
        return self._risk_manager

    def _get_consensus_engine(self, cfg: ConfigDict) -> ConsensusEngine:
        if self._consensus_engine is not None:
            return self._consensus_engine
        consensus_cfg = cfg.get("consensus", {})
        self._consensus_engine = ConsensusEngine(consensus_cfg)
        return self._consensus_engine

    def _ensure_statistical(self, cfg: ConfigDict) -> StatisticalForecaster:
        if self._statistical_forecaster is not None:
            return self._statistical_forecaster
        forecaster_cfg = cfg.get("forecasters", {}).get("statistical", {})
        self._statistical_forecaster = StatisticalForecaster(forecaster_cfg)
        return self._statistical_forecaster

    def _track(self, method: str, *args: Any) -> None:
        """Call a tracker method if tracker is available."""
        if self.tracker is not None:
            getattr(self.tracker, method)(*args)

    # ── Public API ────────────────────────────────────────────────────

    def update_news_data(self, news_data: Dict[str, Any]) -> None:
        """Store latest news sentiment data for use in ensemble weighting."""
        self._last_news_data = news_data

    def suggest_new_ticker(self) -> str:
        """Suggests a new ticker for the currently active watchlist."""
        cfg = self.load_config()
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        current_tickers = watchlists.get(active, cfg.get("tickers", []))

        client = self._get_claude_client(cfg)
        suggestion = client.suggest_ticker(current_tickers)
        if suggestion and suggestion not in current_tickers:
            watchlists.setdefault(active, []).append(suggestion)
            cfg["watchlists"] = watchlists
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            self._config_cache = None
            return suggestion
        return ""

    def generate_portfolio_analysis(self, positions: List[Dict[str, Any]], signals_df: pd.DataFrame) -> str:
        """Generates a natural language analysis of the portfolio and current signals."""
        cfg = self.load_config()
        client = self._get_claude_client(cfg)
        return client.analyze_portfolio(positions, signals_df)

    def get_latest_signals(
        self,
        held_tickers: List[str] | None = None,
        protected_tickers: set[str] | None = None,
        asset_class: AssetClass = "stocks",
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Main signal pipeline — routes to asset-class-specific sub-pipeline.

        For stocks/crypto: ML ensemble + statistical + Claude personas + consensus.
        For polymarket: event fetch + features + Claude edge detection + strategy.

        Returns:
            signals_df: DataFrame with signal columns + consensus metadata
            meta_df: Feature metadata (ticker/date)
        """
        cfg = self.load_config()
        self._track("begin")

        # Route polymarket to its dedicated pipeline
        if asset_class == "polymarket":
            return self._run_polymarket_pipeline(cfg)

        # Auto-retrain if accuracy degradation was detected
        if self._force_retrain:
            logger.info("Auto-retrain triggered by accuracy degradation")
            self._timeframe_ensemble = None  # Force re-creation
            self._force_retrain = False

        # 1. Fetch universe data
        watchlists = self.get_asset_config(cfg, asset_class, "watchlists", {})
        active_wl = self.get_asset_config(cfg, asset_class, "active_watchlist", "")
        tickers_cfg = watchlists.get(active_wl, cfg.get("tickers", []))
        n_tickers = len(set(tickers_cfg) | set(held_tickers or []))
        self._track("start_stage", "data_fetch", n_tickers)
        universe_data = self._get_universe_data(
            cfg, extra_tickers=held_tickers, lookback_days=180
        )
        self._track("complete_stage", "data_fetch", f"{len(universe_data)} tickers")

        # 1a. Resolve yesterday's predictions against today's actual prices
        if self._accuracy_tracker is not None:
            for ticker, df_t in universe_data.items():
                if len(df_t) >= 2:
                    try:
                        close_today = pd.to_numeric(df_t["Close"].iloc[-1], errors="coerce")
                        close_yesterday = pd.to_numeric(df_t["Close"].iloc[-2], errors="coerce")
                        if pd.notna(close_today) and pd.notna(close_yesterday):
                            self._accuracy_tracker.resolve_outcomes(
                                ticker,
                                actual_close_today=float(close_today),
                                actual_close_yesterday=float(close_yesterday),
                            )
                    except Exception:
                        pass

        # 2. Compute V2 features
        self._track("start_stage", "features", 31)
        try:
            latest_features_df, latest_meta_df = latest_feature_rows_v2(universe_data)
        except Exception as e:
            logger.error("Error generating V2 features: %s", e)
            self._track("error_stage", "features", str(e))
            self._track("end")
            return pd.DataFrame(), pd.DataFrame()

        if latest_features_df.empty:
            self._track("error_stage", "features", "empty features")
            self._track("end")
            return pd.DataFrame(), pd.DataFrame()

        self._track("complete_stage", "features", "31 indicators")

        # Store for auto_engine risk manager access
        self._last_features_df = latest_features_df

        # 3. Detect market regime
        self._track("start_stage", "regime", 1)
        try:
            regime_detector = self._get_regime(cfg)
            regime_state = regime_detector.detect(universe_data)
        except Exception as e:
            logger.warning("Regime detection failed: %s — using unknown", e)
            regime_state = RegimeState(
                regime="unknown", confidence=0.0,
                vix_proxy=0.0, breadth=50.0, trend_strength=0.0,
            )
        self._track("complete_stage", "regime", regime_state.regime)

        # ── Stage 4: ML ensemble first (others depend on its probs) ────
        tickers = list(latest_meta_df["ticker"])
        forecaster_cfg = cfg.get("forecasters", {})
        tf_horizons = cfg.get("timeframes", {}).get("horizons", [1, 5, 20])

        # 4. Multi-timeframe ML ensemble predictions (runs first)
        self._track("start_stage", "ml_ensemble", 36)
        all_model_signals: Dict[str, List[ModelSignal]] = {}
        horizon_breakdown: Dict[str, Dict[int, float]] = {}
        ensemble_model_count = 0
        try:
            mte = self._ensure_ensemble(cfg, universe_data)
            ensemble_probs, all_model_signals, horizon_breakdown = mte.get_all_signals(
                latest_features_df, latest_meta_df
            )
            ensemble_model_count = sum(
                1 for e in mte._ensembles.values() for _ in range(e.n_models)
            ) if mte._ensembles else 0
            self._track("complete_stage", "ml_ensemble", f"{ensemble_model_count} models")
        except Exception as e:
            logger.warning("Ensemble prediction failed: %s — falling back to legacy", e)
            ensemble_probs = np.full(len(latest_features_df), 0.5)
            self._track("error_stage", "ml_ensemble", str(e))

        # Legacy sklearn fallback
        try:
            clf = self._ensure_model(cfg)
            p_sklearn = clf.predict_proba(
                latest_features_df[FEATURE_COLUMNS].to_numpy(dtype=float)
            )[:, 1]
        except Exception as e:
            logger.warning("Legacy sklearn prediction error: %s", e)
            p_sklearn = np.full(len(latest_features_df), 0.5)

        # 4a. Statistical forecasters (ARIMA/ETS baseline)
        stat_signals: Dict[str, List[ForecasterSignal]] = {}
        stat_enabled = forecaster_cfg.get("statistical", {}).get("enabled", True)
        if stat_enabled:
            self._track("start_stage", "statistical", len(tickers))
            try:
                stat_forecaster = self._ensure_statistical(cfg)
                if stat_forecaster.is_available:
                    def _stat_progress(current: int, total: int, detail: str) -> None:
                        self._track("update_stage", "statistical", current, detail)

                    stat_signals = stat_forecaster.fit_and_predict(
                        universe_data, tf_horizons, on_progress=_stat_progress,
                    )
                    stat_count = sum(len(v) for v in stat_signals.values())
                    self._track("complete_stage", "statistical", f"{stat_count} forecasts")
                else:
                    self._track("skip_stage", "statistical", "statsmodels not installed")
            except Exception as e:
                logger.warning("Statistical forecaster failed: %s", e)
                self._track("error_stage", "statistical", str(e))
        else:
            self._track("skip_stage", "statistical", "disabled")

        # Merge statistical signals into all_model_signals for consensus
        for ticker_key, sigs in stat_signals.items():
            if ticker_key not in all_model_signals:
                all_model_signals[ticker_key] = []
            for sig in sigs:
                all_model_signals[ticker_key].append(
                    ModelSignal(
                        model_name=f"{sig.family}_{sig.model_name}",
                        ticker=ticker_key,
                        probability=sig.probability,
                        confidence=sig.confidence,
                        feature_group=sig.family,
                        horizon_days=sig.horizon_days,
                    )
                )

        # 5. Claude persona analysis
        all_persona_signals: Dict[str, List[PersonaSignal]] = {}
        claude_client = self._get_claude_client(cfg)

        persona_analyzer = self._get_claude_personas(cfg)
        if persona_analyzer is not None:
            try:
                ticker_data = {}
                for ticker in tickers:
                    if ticker not in universe_data:
                        continue
                    df_ticker = universe_data[ticker]
                    closes = df_ticker["Close"].tail(30).tolist()
                    feat_row = latest_features_df.loc[ticker].to_dict() if ticker in latest_features_df.index else {}
                    nd = getattr(self, "_last_news_data", {}).get(ticker)
                    news_sent = 0.0
                    news_sum = ""
                    if nd is not None:
                        news_sent = nd.sentiment if hasattr(nd, "sentiment") else nd.get("sentiment", 0.0)
                        news_sum = nd.summary if hasattr(nd, "summary") else nd.get("summary", "")
                    ticker_data[ticker] = {
                        "closes": closes,
                        "features": feat_row,
                        "news_sentiment": news_sent,
                        "news_summary": news_sum,
                    }

                n_personas = len(persona_analyzer._personas)
                total_persona_calls = len(ticker_data) * n_personas
                self._track("start_stage", "claude_personas", total_persona_calls)

                def _persona_progress(done: int, total: int, detail: str) -> None:
                    self._track("update_stage", "claude_personas", done, detail)

                # No timeout wrapper — pipeline takes however long it needs
                all_persona_signals = persona_analyzer.analyze_batch(
                    ticker_data, on_progress=_persona_progress,
                )
            except Exception as e:
                logger.warning("Claude persona analysis failed: %s — falling back to single-call", e)
        else:
            self._track("start_stage", "claude_personas", 1)
        self._track("complete_stage", "claude_personas", f"{len(all_persona_signals)} tickers")

        # Rate-limit detection: if personas returned signals but all are
        # suspiciously uniform (all probabilities ~0.5), Claude likely hit
        # usage limits and returned garbage.  Fall back to ML-only.
        personas_usable = bool(all_persona_signals)
        if all_persona_signals:
            all_probs = [
                s.probability
                for sigs in all_persona_signals.values()
                for s in sigs
            ]
            if all_probs and all(abs(p - 0.5) < 0.01 for p in all_probs):
                logger.warning(
                    "All persona probabilities are 0.5 — likely rate-limited. "
                    "Ignoring persona signals for this cycle."
                )
                all_persona_signals = {}
                personas_usable = False

        # Fallback: single Claude call only for tickers where personas
        # produced no results.  If personas succeeded, derive p_ai + rec
        # from persona signals to avoid redundant Claude CLI calls.
        # If rate-limited, skip all Claude calls and use neutral values.
        p_ai_list: List[float] = []
        reasons: List[str] = []
        ai_recs: List[str] = []

        for _, meta_row in latest_meta_df.iterrows():
            ticker = str(meta_row["ticker"])

            # If personas produced signals for this ticker, use them directly
            persona_sigs = all_persona_signals.get(ticker, [])
            if persona_sigs:
                avg_p = sum(s.probability for s in persona_sigs) / len(persona_sigs)
                avg_rec_votes: Dict[str, int] = {}
                for s in persona_sigs:
                    avg_rec_votes[s.recommendation] = avg_rec_votes.get(s.recommendation, 0) + 1
                top_rec = max(avg_rec_votes, key=avg_rec_votes.get)  # type: ignore[arg-type]
                reason_parts = [f"{s.persona}: {s.reasoning[:60]}" for s in persona_sigs[:3]]
                p_ai_list.append(avg_p)
                reasons.append("; ".join(reason_parts))
                ai_recs.append(top_rec)
                continue

            # If personas were rate-limited, don't waste credits on fallback calls
            if not personas_usable:
                p_ai_list.append(0.5)
                reasons.append("Claude unavailable (usage limits) — ML-only")
                ai_recs.append("HOLD")
                continue

            # No persona data for this ticker — fall back to single Claude call
            try:
                df_ticker = universe_data.get(ticker)
                if df_ticker is None or df_ticker.empty:
                    raise ValueError(f"No data for {ticker}")
                recent_closes = df_ticker["Close"].tail(30).tolist()
                feature_row = latest_features_df.loc[ticker].to_dict() if ticker in latest_features_df.index else {}

                out = claude_client.get_signal_for_ticker(ticker, recent_closes, feature_row)
                if not out or not out.get("p_up_ai"):
                    raise ValueError("Empty Claude response")
                p_val = float(out.get("p_up_ai", 0.5))

                rec_out = claude_client.get_recommendation(
                    ticker=ticker,
                    current_position=None,
                    prob_up=p_val,
                    news_sentiment=0.0,
                    news_summary="",
                    features=feature_row,
                )
                p_ai_list.append(p_val)
                reasons.append(str(out.get("reason", "No reason provided.")))
                ai_recs.append(rec_out.get("action", "HOLD"))
            except Exception as e:
                logger.warning("Claude error for %s: %s", ticker, e)
                p_ai_list.append(0.5)
                reasons.append(f"Error: {e}")
                ai_recs.append("HOLD")

        p_ai = np.array(p_ai_list, dtype=float)

        # 6. Aggregate through consensus engine
        self._track("start_stage", "consensus", 1)
        consensus_engine = self._get_consensus_engine(cfg)
        consensus_results: Dict[str, ConsensusResult] = consensus_engine.compute_all(
            all_signals=all_model_signals,
            all_personas=all_persona_signals,
            regime=regime_state,
            all_horizon_probs=horizon_breakdown,
        )
        self._track("complete_stage", "consensus", f"{len(consensus_results)} tickers")

        # Build final probability: blend ensemble + Claude AI + news
        ai_cfg = cfg.get("ai", {}) or {}
        w_sklearn = float(ai_cfg.get("sklearn_weight", 0.5))
        w_ai = float(ai_cfg.get("ai_weight", 0.3))
        w_news = float(ai_cfg.get("news_weight", 0.2))

        # News sentiment -> probability
        p_news = np.full(len(latest_meta_df), 0.5)
        if hasattr(self, "_last_news_data"):
            for i, (_, meta_row) in enumerate(latest_meta_df.iterrows()):
                ticker = str(meta_row["ticker"])
                nd = self._last_news_data.get(ticker)
                if nd is not None:
                    sent = nd.sentiment if hasattr(nd, "sentiment") else nd.get("sentiment", 0.0)
                    p_news[i] = (float(sent) + 1.0) / 2.0

        # Final blend: use consensus probability as primary if available, fall back to legacy
        self._track("start_stage", "risk", 1)
        p_final = np.full(len(latest_meta_df), 0.5)
        for i, (_, meta_row) in enumerate(latest_meta_df.iterrows()):
            ticker = str(meta_row["ticker"])
            cons = consensus_results.get(ticker)
            if cons and (cons.bull_count + cons.bear_count) > 0:
                # Consensus-driven: weight consensus probability heavily
                p_final[i] = 0.6 * cons.probability + 0.2 * p_ai[i] + 0.2 * p_news[i]
            else:
                # Legacy fallback
                p_final[i] = w_sklearn * p_sklearn[i] + w_ai * p_ai[i] + w_news * p_news[i]

        # 7. Generate strategy signals (regime-aware per-ticker selection)
        strat_cfg_raw = cfg.get("strategy", {})
        strat_cfg = StrategyConfig(
            threshold_buy=strat_cfg_raw.get("threshold_buy", 0.6),
            threshold_sell=strat_cfg_raw.get("threshold_sell", 0.4),
            max_positions=strat_cfg_raw.get("max_positions", 5),
            position_size_fraction=strat_cfg_raw.get("position_size_fraction", 0.2),
        )

        per_ticker_configs: Dict[str, StrategyConfig] | None = None
        strategy_assignments: Dict[str, Any] = {}

        strategy_profiles_cfg = cfg.get("strategy_profiles", {})
        if strategy_profiles_cfg.get("enabled", False) and regime_state:
            capital = float(cfg.get("capital", 100_000))
            profiles = load_research_profiles(cfg)
            regime_mapping_raw = strategy_profiles_cfg.get("regime_mapping")
            regime_mapping = dict(REGIME_DEFAULT_MAPPING)
            if regime_mapping_raw:
                regime_mapping.update(regime_mapping_raw)

            # Ask Claude to pick the profile instead of using the static mapping
            claude = self._get_claude_client(cfg)
            market_summary = (
                f"Regime: {regime_state.regime} (confidence {regime_state.confidence:.0%})\n"
                f"VIX proxy: {regime_state.vix_proxy:.2f}, Breadth: {regime_state.breadth:.2f}, "
                f"Trend strength: {regime_state.trend_strength:.2f}\n"
                f"Tickers in play: {len(consensus_results)}"
            )
            claude_pick = claude.select_strategy_profile(
                regime=regime_state.regime,
                regime_confidence=regime_state.confidence,
                market_summary=market_summary,
                available_profiles=list(profiles.keys()),
            )
            if claude_pick:
                # Claude overrides: use its pick for all regime mappings
                regime_mapping = {k: claude_pick for k in regime_mapping}
                logger.info("Claude selected profile '%s' for regime '%s'", claude_pick, regime_state.regime)

            selector = StrategySelector(
                profiles=profiles,
                regime_mapping=regime_mapping,
                capital=capital,
            )
            assignments = selector.select_strategies(
                regime=regime_state,
                consensus=consensus_results,
            )
            # Convert assignments to per-ticker StrategyConfigs
            per_ticker_configs = {}
            for ticker, assignment in assignments.items():
                per_ticker_configs[ticker] = StrategySelector.to_strategy_config(
                    assignment.profile
                )
            strategy_assignments = {
                ticker: {"name": a.profile.name, "reason": a.reason, "regime": a.regime}
                for ticker, a in assignments.items()
            }
            self._last_strategy_assignments = strategy_assignments

        signals_df = generate_signals(
            p_final, latest_meta_df, strat_cfg,
            held_tickers=held_tickers or [],
            protected_tickers=protected_tickers,
            per_ticker_configs=per_ticker_configs,
        )
        self._track("complete_stage", "risk", "signals generated")

        # 8. Attach all metadata
        signals_df["p_up_sklearn"] = p_sklearn
        signals_df["p_up_ai"] = p_ai
        signals_df["p_up_ensemble"] = ensemble_probs
        signals_df["p_up_final"] = p_final
        signals_df["reason"] = reasons
        signals_df["ai_rec"] = ai_recs

        # Attach per-ticker statistical probabilities
        p_stat_list: List[float] = []
        for _, row in signals_df.iterrows():
            t = str(row["ticker"])
            sigs = stat_signals.get(t, [])
            if sigs:
                p_stat_list.append(sum(s.probability for s in sigs) / len(sigs))
            else:
                p_stat_list.append(0.5)
        signals_df["p_up_statistical"] = p_stat_list

        # Attach consensus metadata per ticker
        consensus_pcts: List[float] = []
        confidences: List[float] = []
        for _, row in signals_df.iterrows():
            ticker = str(row["ticker"])
            cons = consensus_results.get(ticker)
            if cons:
                consensus_pcts.append(cons.consensus_pct)
                confidences.append(cons.confidence)
            else:
                consensus_pcts.append(50.0)
                confidences.append(0.0)

        signals_df["consensus_pct"] = consensus_pcts
        signals_df["consensus_confidence"] = confidences

        # Attach strategy assignments to DataFrame
        strat_names: List[str] = []
        for _, row in signals_df.iterrows():
            t = str(row["ticker"])
            sa = strategy_assignments.get(t, {})
            strat_names.append(sa.get("name", "") if isinstance(sa, dict) else "")
        signals_df["strategy"] = strat_names

        # Store consensus and regime state for other components
        self._last_consensus = consensus_results
        self._last_regime = regime_state
        self._ensemble_model_count = ensemble_model_count
        self._last_stat_signals = stat_signals

        # Update pipeline dashboard stats
        self._update_dashboard_stats(
            cfg, ensemble_model_count, stat_signals,
            regime_state, consensus_results,
        )

        # 9. Log predictions for accuracy tracking
        if self._accuracy_tracker is not None:
            try:
                self._accuracy_tracker.log_predictions(signals_df)
            except Exception as e:
                logger.warning("Failed to log predictions: %s", e)

        # 10. Ensure every requested ticker has a signal row.
        #     Tickers can be missing if yfinance returned no data OR if feature
        #     computation dropped them (insufficient history / NaN filtering).
        present_upper = set(signals_df["ticker"].str.upper()) if not signals_df.empty else set()
        all_requested = set(tickers_cfg) | set(held_tickers or [])
        missing_tickers = [t for t in all_requested if t.upper() not in present_upper]

        if missing_tickers:
            today_str = datetime.now().strftime("%Y-%m-%d")
            stub_rows = [
                {
                    "ticker": ticker,
                    "date": today_str,
                    "prob_up": 0.5,
                    "signal": "hold",
                    "p_up_sklearn": 0.5,
                    "p_up_ai": 0.5,
                    "p_up_ensemble": 0.5,
                    "p_up_final": 0.5,
                    "p_up_statistical": 0.5,
                    "reason": "No market data available",
                    "ai_rec": "N/A",
                    "consensus_pct": 50.0,
                    "consensus_confidence": 0.0,
                }
                for ticker in missing_tickers
            ]
            signals_df = pd.concat(
                [signals_df, pd.DataFrame(stub_rows)], ignore_index=True,
            )
            logger.info("Added stub signals for %d missing tickers: %s", len(missing_tickers), missing_tickers)

        # 11. Self-tune weights based on accuracy data
        self._auto_tune_weights(cfg)

        self._track("end")
        return signals_df, latest_meta_df

    # ── Polymarket pipeline ─────────────────────────────────────────────

    def _run_polymarket_pipeline(
        self, cfg: ConfigDict,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Edge-detection pipeline for Polymarket prediction markets.

        Stages:
        1. Fetch active markets from Gamma API
        2. Build event features (probability dynamics, volume, orderbook)
        3. Detect market regime (category/activity patterns)
        4. Detect edges (Claude-powered or heuristic fallback)
        5. Convert edges to trading signals with Kelly sizing
        """
        from polymarket import data_loader as poly_dl
        from polymarket import features as poly_feat
        from polymarket.model import EdgeDetector
        from polymarket.regime import PolymarketRegimeDetector
        from polymarket.strategy import generate_polymarket_signals

        poly_cfg = PolymarketConfig.from_config(cfg) if PolymarketConfig else None
        strat_cfg = cfg.get("polymarket", {}).get("strategy", {})
        risk_cfg = cfg.get("polymarket", {}).get("risk", {})

        min_volume = poly_cfg.min_volume if poly_cfg else 1_000
        min_liquidity = poly_cfg.min_liquidity if poly_cfg else 500
        max_markets = poly_cfg.max_markets if poly_cfg else 20
        use_claude = poly_cfg.use_claude if poly_cfg else True

        # 1. Fetch markets (filtered by first configured category)
        categories = poly_cfg.categories if poly_cfg else []
        category = categories[0] if categories else None
        self._track("start_stage", "data_fetch", max_markets)
        events = poly_dl.fetch_markets(
            active_only=True,
            min_volume=min_volume,
            limit=max_markets,
            category=category,
        )
        self._track("complete_stage", "data_fetch", f"{len(events)} markets")

        if not events:
            logger.warning("No Polymarket events fetched")
            self._track("end")
            return pd.DataFrame(), pd.DataFrame()

        # 2. Build features per event
        self._track("start_stage", "features", len(events))
        features_list: List[Dict[str, float]] = []
        for i, event in enumerate(events):
            token_id = event.tokens.get("Yes", "")
            history = poly_dl.fetch_market_history(event.condition_id, token_id) if event.condition_id else pd.DataFrame()
            orderbook = poly_dl.fetch_orderbook(token_id) if token_id else {"bids": [], "asks": []}
            feat = poly_feat.build_event_features(event, history, orderbook)
            features_list.append(feat)
            self._track("update_stage", "features", i + 1, event.question[:30])
        self._track("complete_stage", "features", f"{len(features_list)} events")

        # 3. Detect regime
        self._track("start_stage", "regime", 1)
        regime_detector = PolymarketRegimeDetector()
        regime_state = regime_detector.detect(events)
        self._last_regime = regime_state
        self._track("complete_stage", "regime", regime_state.regime)

        # 4. Edge detection — Research Swarm + MiroFish (or heuristic fallback)
        model_cfg = cfg.get("polymarket", {}).get("model", {})
        edge_detector = EdgeDetector(model_cfg)

        if use_claude:
            self._track("start_stage", "claude_personas", len(events) * 4)
            claude_client = self._get_claude_client(cfg)

            def _swarm_progress(done: int, total: int, detail: str) -> None:
                self._track("update_stage", "claude_personas", done, f"Agent: {detail}")

            edges = edge_detector.detect_edges_v2(
                events, features_list, claude_client,
                min_edge_pct=float(strat_cfg.get("min_edge_pct", 5.0)),
                on_progress=_swarm_progress,
            )
            self._track("complete_stage", "claude_personas", f"{len(edges)} edges (Swarm+MiroFish)")
        else:
            self._track("start_stage", "ml_ensemble", len(events))
            edges = edge_detector.detect_edges(
                events, features_list,
                min_edge_pct=float(strat_cfg.get("min_edge_pct", 5.0)),
            )
            self._track("complete_stage", "ml_ensemble", f"{len(edges)} edges")

        # 5. Generate trading signals
        self._track("start_stage", "risk", 1)
        merged_cfg = {**strat_cfg, **risk_cfg}
        signals_df = generate_polymarket_signals(edges, merged_cfg)

        # Enrich signals with display data the terminal view expects
        if not signals_df.empty:
            event_lookup = {e.condition_id: e for e in events}
            volumes: List[float] = []
            liquidities: List[float] = []
            resolves_list: List[str] = []
            categories: List[str] = []

            for _, row in signals_df.iterrows():
                cid = str(row.get("condition_id", ""))
                ev = event_lookup.get(cid)
                if ev:
                    volumes.append(ev.volume_24h)
                    liquidities.append(ev.liquidity)
                    resolves_list.append(ev.end_date.strftime("%Y-%m-%d") if ev.end_date else "-")
                    categories.append(ev.category)
                else:
                    volumes.append(0.0)
                    liquidities.append(0.0)
                    resolves_list.append("-")
                    categories.append("-")

            signals_df["volume"] = volumes
            signals_df["liquidity"] = liquidities
            signals_df["resolves"] = resolves_list
            signals_df["category"] = categories

        self._track("complete_stage", "risk", "signals generated")
        self._track("end")

        # Build a minimal meta DataFrame for compatibility
        meta_df = pd.DataFrame({
            "ticker": signals_df["question"] if not signals_df.empty else [],
            "date": [datetime.now().strftime("%Y-%m-%d")] * len(signals_df),
        })

        return signals_df, meta_df

    def get_consensus_data(self) -> Dict[str, ConsensusResult]:
        """Return the most recent consensus results (for state updates)."""
        return getattr(self, "_last_consensus", {})

    def get_regime_state(self) -> RegimeState | None:
        """Return the most recent regime detection result."""
        return getattr(self, "_last_regime", None)

    def get_ensemble_model_count(self) -> int:
        """Return the total number of models across all horizon ensembles."""
        return getattr(self, "_ensemble_model_count", 0)

    def _update_dashboard_stats(
        self,
        cfg: ConfigDict,
        ensemble_model_count: int,
        stat_signals: Dict[str, List[ForecasterSignal]],
        regime_state: RegimeState,
        consensus_results: Dict[str, ConsensusResult],
    ) -> None:
        """Push model family stats to the pipeline tracker for dashboard display."""
        if self.tracker is None:
            return

        stat_count = sum(len(v) for v in stat_signals.values())

        # Consensus bull percentage
        bull_pct = 50.0
        if consensus_results:
            total_bulls = sum(c.bull_count for c in consensus_results.values())
            total_all = sum(c.bull_count + c.bear_count for c in consensus_results.values())
            if total_all > 0:
                bull_pct = total_bulls / total_all * 100

        family_stats: Dict[str, Dict[str, Any]] = {
            "ml": {
                "display_name": "ML Ensemble (3hz)",
                "count": ensemble_model_count,
                "weight": 0.75,
                "status": "ready",
            },
            "statistical": {
                "display_name": "ARIMA/ETS",
                "count": stat_count,
                "weight": 0.25,
                "status": "fitted" if stat_count > 0 else "unavailable",
            },
            "claude_personas": {
                "display_name": "Claude Personas",
                "count": 3,
                "weight": 0.20,
                "status": "live (consensus + p_ai)",
            },
            "regime": {
                "display_name": f"Regime: {regime_state.regime}",
                "count": "",
                "weight": "",
                "avg_prob": regime_state.confidence,
                "status": f"{regime_state.confidence * 100:.0f}% conf",
            },
            "consensus": {
                "display_name": "Consensus",
                "count": "",
                "weight": "",
                "avg_prob": bull_pct / 100,
                "status": f"{bull_pct:.0f}% bull",
            },
        }
        self.tracker.update_dashboard_stats(family_stats)

    def retrain_model(self) -> None:
        """Force a full retrain of legacy model, ensemble, and forecasters."""
        cfg = self.load_config()
        universe_data = self._get_universe_data(cfg)

        # Legacy RF
        X, y, meta = build_universe_dataset(universe_data)
        model_path = Path(cfg.get("model_path", "models/rf_tomorrow_up.joblib"))
        model_cfg = ModelConfig(model_path=model_path)
        train_model(X, y, meta, model_cfg)
        self._model_loaded = True

        # Multi-timeframe ensemble
        try:
            ensemble_cfg_raw = cfg.get("ensemble", {})
            ensemble_config = EnsembleConfig(
                n_models=int(ensemble_cfg_raw.get("n_models", 12)),
                stacking_enabled=bool(ensemble_cfg_raw.get("stacking_enabled", True)),
                performance_lookback_days=int(ensemble_cfg_raw.get("performance_lookback_days", 60)),
                min_model_weight=float(ensemble_cfg_raw.get("min_model_weight", 0.02)),
            )

            tf_cfg_raw = cfg.get("timeframes", {})
            horizons = tf_cfg_raw.get("horizons", [1, 5, 20])
            weights_raw = tf_cfg_raw.get("weights", {"1": 0.5, "5": 0.3, "20": 0.2})
            weights = {int(k): float(v) for k, v in weights_raw.items()}

            mte = MultiTimeframeEnsemble(
                horizons=horizons, weights=weights, ensemble_config=ensemble_config,
            )
            mte.train_all_horizons(universe_data)
            mte.save(Path(ensemble_config.model_dir))
            self._timeframe_ensemble = mte
            logger.info("Multi-timeframe ensemble retrained and saved.")
        except Exception as e:
            logger.error("Ensemble retrain failed: %s", e)

        # Statistical forecasters (force re-fit)
        try:
            self._statistical_forecaster = None
            stat = self._ensure_statistical(cfg)
            if stat.is_available:
                stat.fit_and_predict(universe_data, horizons)
                logger.info("Statistical forecasters retrained.")
        except Exception as e:
            logger.error("Statistical retrain failed: %s", e)

    def _auto_tune_weights(self, cfg: ConfigDict) -> None:
        """Check if overall accuracy degraded and trigger retrain if needed."""
        if self._accuracy_tracker is None:
            return

        try:
            overall = self._accuracy_tracker.get_rolling_accuracy(window_days=14)
            if 0.0 < overall < 0.45:
                logger.info("Accuracy %.1f%% below threshold — will retrain next cycle", overall * 100)
                self._force_retrain = True
        except Exception as e:
            logger.warning("Auto-tune check failed: %s", e)
