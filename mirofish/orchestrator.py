"""Monte Carlo orchestrator — runs parallel MiroFish simulations across all CPU cores.

For each ticker in the universe:
    1. Build a MarketContext from real data + ML features + news
    2. Launch N simulation runs in parallel (different seeds)
    3. Aggregate results across runs → robust MiroFishSignal

Uses ProcessPoolExecutor so the GIL is not a bottleneck for numpy-heavy work.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from cpu_config import get_cpu_cores as _get_cpu_cores

from mirofish.signals import aggregate_simulations, extract_signal_from_aggregate
from mirofish.simulation import run_single_simulation
from mirofish.types import MarketContext, MiroFishSignal, SimulationConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level pickle-friendly function for multiprocessing
# ---------------------------------------------------------------------------

def _run_sim_worker(args: Tuple[dict, dict, int]) -> dict:
    """Process-pool target — must be a top-level function for pickling.

    Accepts serialised config/context dicts (not dataclasses) because
    Windows spawn-based multiprocessing requires everything to be picklable.
    Returns a dict of numpy arrays.
    """
    cfg_dict, ctx_dict, seed = args

    config = SimulationConfig(**{
        k: v for k, v in cfg_dict.items()
        if k in SimulationConfig.__dataclass_fields__
    })
    ctx = MarketContext(
        ticker=ctx_dict["ticker"],
        recent_returns=np.array(ctx_dict["recent_returns"]),
        trend_signal=ctx_dict["trend_signal"],
        rsi_signal=ctx_dict["rsi_signal"],
        volatility=ctx_dict["volatility"],
        news_sentiment=ctx_dict["news_sentiment"],
        regime=ctx_dict["regime"],
        ensemble_probability=ctx_dict["ensemble_probability"],
        features=ctx_dict.get("features", {}),
    )

    result = run_single_simulation(config, ctx, seed)

    return {
        "final_beliefs": result.final_beliefs,
        "belief_history": result.belief_history,
        "position_history": result.position_history,
        "synthetic_prices": result.synthetic_prices,
        "order_flow_history": result.order_flow_history,
        "agent_types": result.agent_types,
    }


class MiroFishOrchestrator:
    """Top-level entry point for MiroFish multi-agent simulation."""

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self._config = config or SimulationConfig()
        self._n_processes = self._config.n_processes or _get_cpu_cores()

    @classmethod
    def from_config_dict(cls, raw: Dict[str, Any]) -> MiroFishOrchestrator:
        """Build from the 'mirofish' section of config.json."""
        dist_raw = raw.get("agent_distribution", {})
        dist = {k: int(v) for k, v in dist_raw.items()} if dist_raw else None

        cfg = SimulationConfig(
            n_agents=int(raw.get("n_agents", 1000)),
            n_ticks=int(raw.get("n_ticks", 100)),
            n_simulations=int(raw.get("n_simulations", 16)),
            n_processes=raw.get("n_processes"),
            price_impact_factor=float(raw.get("price_impact_factor", 0.001)),
            base_volatility=float(raw.get("base_volatility", 0.02)),
            liquidity=float(raw.get("liquidity", 1.0)),
            influence_radius=int(raw.get("influence_radius", 15)),
            information_decay=float(raw.get("information_decay", 0.95)),
            consensus_weight=float(raw.get("consensus_weight", 0.15)),
        )
        if dist:
            cfg.agent_distribution = dist  # type: ignore[assignment]

        return cls(cfg)

    @property
    def config(self) -> SimulationConfig:
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_universe(
        self,
        universe_data: Dict[str, pd.DataFrame],
        features_df: pd.DataFrame,
        regime: str,
        ensemble_probs: Dict[str, float],
        news_data: Dict[str, Any],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, MiroFishSignal]:
        """Run MiroFish simulations for every ticker in the universe.

        Args:
            universe_data:   {ticker: OHLCV DataFrame}
            features_df:     Latest feature rows (indexed by ticker)
            regime:          Current market regime string
            ensemble_probs:  {ticker: P(up)} from meta-ensemble
            news_data:       {ticker: news object with .sentiment}
            on_progress:     Optional (done, total, detail) callback

        Returns:
            {ticker: MiroFishSignal}
        """
        tickers = list(universe_data.keys())
        total_jobs = len(tickers) * self._config.n_simulations

        # Build per-ticker MarketContext dicts (serialisable for multiprocessing)
        ticker_contexts: Dict[str, dict] = {}
        for ticker in tickers:
            ctx = self._build_context(
                ticker, universe_data, features_df,
                regime, ensemble_probs, news_data,
            )
            if ctx is not None:
                ticker_contexts[ticker] = ctx

        if not ticker_contexts:
            logger.warning("MiroFish: no valid ticker contexts — skipping")
            return {}

        # Build work items: (config_dict, context_dict, seed)
        cfg_dict = _serialise_config(self._config)
        work_items: List[Tuple[dict, dict, int]] = []
        base_seed = int.from_bytes(os.urandom(4), "little")
        for i, (ticker, ctx_dict) in enumerate(ticker_contexts.items()):
            for sim_idx in range(self._config.n_simulations):
                seed = base_seed + i * 10000 + sim_idx
                work_items.append((cfg_dict, ctx_dict, seed))

        # Execute in parallel across CPU cores
        results_by_ticker: Dict[str, List[dict]] = {t: [] for t in ticker_contexts}
        done_count = 0

        try:
            with ProcessPoolExecutor(max_workers=self._n_processes) as pool:
                futures = {
                    pool.submit(_run_sim_worker, item): item[1]["ticker"]
                    for item in work_items
                }
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        result = future.result()
                        results_by_ticker[ticker].append(result)
                    except Exception as e:
                        logger.warning("MiroFish sim failed for %s: %s", ticker, e)

                    done_count += 1
                    if on_progress is not None:
                        on_progress(done_count, total_jobs, ticker)
        except Exception as e:
            logger.error("MiroFish parallel execution failed: %s — falling back to serial", e)
            results_by_ticker = self._run_serial(work_items, ticker_contexts, on_progress)

        # Aggregate per-ticker results → MiroFishSignal
        signals: Dict[str, MiroFishSignal] = {}
        for ticker, sim_results in results_by_ticker.items():
            if not sim_results:
                continue
            agg = aggregate_simulations(sim_results)
            signals[ticker] = extract_signal_from_aggregate(
                ticker=ticker,
                agg=agg,
                n_simulations=len(sim_results),
                n_agents=self._config.n_agents,
            )

        return signals

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_context(
        self,
        ticker: str,
        universe_data: Dict[str, pd.DataFrame],
        features_df: pd.DataFrame,
        regime: str,
        ensemble_probs: Dict[str, float],
        news_data: Dict[str, Any],
    ) -> dict | None:
        """Build a serialisable MarketContext dict for one ticker."""
        df = universe_data.get(ticker)
        if df is None or len(df) < 20:
            return None

        closes = df["Close"].values.astype(float)
        returns = np.diff(closes) / np.maximum(closes[:-1], 1e-8)
        recent_returns = returns[-60:].tolist()  # Last 60 trading days

        # Trend signal: 5-day SMA vs 20-day SMA normalised
        sma5 = closes[-5:].mean() if len(closes) >= 5 else closes[-1]
        sma20 = closes[-20:].mean() if len(closes) >= 20 else closes[-1]
        trend_signal = float(np.clip((sma5 - sma20) / max(sma20, 1e-8) * 10, -1, 1))

        # RSI signal: convert 0-100 RSI to [-1, 1]
        rsi_val = 50.0
        if ticker in features_df.index:
            feat_row = features_df.loc[ticker]
            if "rsi_14" in feat_row.index:
                rsi_val = float(feat_row["rsi_14"])
        rsi_signal = float(np.clip((rsi_val - 50) / 50, -1, 1))

        # Realised volatility (20-day)
        vol = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.02

        # News sentiment
        news_sent = 0.0
        nd = news_data.get(ticker)
        if nd is not None:
            if hasattr(nd, "sentiment"):
                news_sent = float(nd.sentiment)
            elif isinstance(nd, dict):
                news_sent = float(nd.get("sentiment", 0.0))

        # Ensemble probability
        ens_prob = float(ensemble_probs.get(ticker, 0.5))

        # Feature dict for seeding
        features: Dict[str, float] = {}
        if ticker in features_df.index:
            try:
                features = features_df.loc[ticker].to_dict()
                features = {k: float(v) for k, v in features.items() if isinstance(v, (int, float))}
            except Exception:
                pass

        return {
            "ticker": ticker,
            "recent_returns": recent_returns,
            "trend_signal": trend_signal,
            "rsi_signal": rsi_signal,
            "volatility": vol,
            "news_sentiment": news_sent,
            "regime": regime,
            "ensemble_probability": ens_prob,
            "features": features,
        }

    def _run_serial(
        self,
        work_items: List[Tuple[dict, dict, int]],
        ticker_contexts: Dict[str, dict],
        on_progress: Optional[Callable[[int, int, str], None]],
    ) -> Dict[str, List[dict]]:
        """Fallback: run simulations sequentially if multiprocessing fails."""
        results_by_ticker: Dict[str, List[dict]] = {t: [] for t in ticker_contexts}
        total = len(work_items)

        for i, item in enumerate(work_items):
            ticker = item[1]["ticker"]
            try:
                result = _run_sim_worker(item)
                results_by_ticker[ticker].append(result)
            except Exception as e:
                logger.warning("MiroFish serial sim failed for %s: %s", ticker, e)
            if on_progress is not None:
                on_progress(i + 1, total, ticker)

        return results_by_ticker


def _serialise_config(config: SimulationConfig) -> dict:
    """Convert SimulationConfig to a plain dict for pickling across processes."""
    return {
        "n_agents": config.n_agents,
        "n_ticks": config.n_ticks,
        "n_simulations": config.n_simulations,
        "n_processes": config.n_processes,
        "price_impact_factor": config.price_impact_factor,
        "base_volatility": config.base_volatility,
        "liquidity": config.liquidity,
        "influence_radius": config.influence_radius,
        "information_decay": config.information_decay,
        "agent_distribution": dict(config.agent_distribution),
        "consensus_weight": config.consensus_weight,
    }
