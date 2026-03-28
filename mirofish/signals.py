"""Signal extraction — converts raw simulation results into trading signals.

Aggregates across Monte Carlo runs, computes population statistics,
and converts to ModelSignal format for the consensus engine.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from mirofish.types import AGENT_TYPE_IDS, MiroFishSignal

# Maps from type ID → human-readable name for signal attribution
_TYPE_NAMES: Dict[int, str] = {v: k for k, v in AGENT_TYPE_IDS.items()}


def aggregate_simulations(sim_results: List[dict]) -> dict:
    """Combine N simulation runs into aggregate statistics.

    Each sim_result dict has keys: final_beliefs, belief_history,
    position_history, synthetic_prices, order_flow_history, agent_types.

    Returns a dict of aggregated numpy arrays.
    """
    n_runs = len(sim_results)
    if n_runs == 0:
        return {}

    # Stack final beliefs across runs → (n_runs, n_agents)
    all_final_beliefs = np.stack([r["final_beliefs"] for r in sim_results])

    # Stack belief histories → (n_runs, n_ticks, n_agents)
    all_belief_hist = np.stack([r["belief_history"] for r in sim_results])

    # Stack position histories → (n_runs, n_ticks, n_agents)
    all_position_hist = np.stack([r["position_history"] for r in sim_results])

    # Stack synthetic prices → (n_runs, n_ticks)
    all_prices = np.stack([r["synthetic_prices"] for r in sim_results])

    # Stack order flow → (n_runs, n_ticks)
    all_flow = np.stack([r["order_flow_history"] for r in sim_results])

    # Agent types (same across runs if same config)
    agent_types = sim_results[0]["agent_types"]

    return {
        "all_final_beliefs": all_final_beliefs,
        "all_belief_hist": all_belief_hist,
        "all_position_hist": all_position_hist,
        "all_prices": all_prices,
        "all_flow": all_flow,
        "agent_types": agent_types,
        "n_runs": n_runs,
    }


def extract_signal_from_aggregate(
    ticker: str,
    agg: dict,
    n_simulations: int,
    n_agents: int,
) -> MiroFishSignal:
    """Extract a structured MiroFishSignal from aggregated simulation data."""

    if not agg:
        return _neutral_signal(ticker, n_simulations, n_agents)

    final_beliefs = agg["all_final_beliefs"]       # (n_runs, n_agents)
    belief_hist = agg["all_belief_hist"]            # (n_runs, n_ticks, n_agents)
    all_flow = agg["all_flow"]                      # (n_runs, n_ticks)
    all_prices = agg["all_prices"]                  # (n_runs, n_ticks)

    # --- Net sentiment: mean belief across all agents and runs ---------------
    net_sentiment = float(np.mean(final_beliefs))

    # --- Sentiment momentum: rate of change in last 20% of ticks -------------
    n_ticks = belief_hist.shape[1]
    tail_start = max(0, int(n_ticks * 0.8))
    mean_beliefs_over_time = belief_hist.mean(axis=(0, 2))  # (n_ticks,)
    if tail_start < n_ticks - 1:
        recent_beliefs = mean_beliefs_over_time[tail_start:]
        sentiment_momentum = float(
            (recent_beliefs[-1] - recent_beliefs[0]) / max(len(recent_beliefs), 1)
        )
    else:
        sentiment_momentum = 0.0

    # --- Agreement index: 1 - normalised std of final beliefs ----------------
    belief_std = float(np.std(final_beliefs))
    # Max possible std for [-1,1] is 1.0 (all at extremes)
    agreement_index = float(np.clip(1.0 - belief_std, 0.0, 1.0))

    # --- Volatility prediction: from belief disagreement + price dispersion --
    price_returns = np.diff(all_prices, axis=1) / np.maximum(all_prices[:, :-1], 1e-8)
    price_vol = float(np.std(price_returns))
    # Blend belief disagreement and synthetic price vol
    volatility_prediction = 0.6 * belief_std + 0.4 * min(price_vol * 10, 1.0)

    # --- Order flow: mean final net flow across runs -------------------------
    order_flow = float(np.mean(all_flow[:, -1]))

    # --- Narrative direction -------------------------------------------------
    if net_sentiment > 0.15 and sentiment_momentum > 0.001:
        narrative = "bullish"
    elif net_sentiment < -0.15 and sentiment_momentum < -0.001:
        narrative = "bearish"
    else:
        narrative = "uncertain"

    # --- P(up): map net sentiment [-1, 1] → probability [0, 1] --------------
    # Sigmoid-like mapping that compresses extreme values
    probability = float(1.0 / (1.0 + np.exp(-3.0 * net_sentiment)))

    # --- Confidence: based on agreement, simulation consistency, conviction --
    # Cross-run consistency: how similar are final mean beliefs across runs?
    per_run_means = final_beliefs.mean(axis=1)  # (n_runs,)
    cross_run_std = float(np.std(per_run_means))
    consistency = float(np.clip(1.0 - cross_run_std * 3, 0.0, 1.0))

    # Conviction: how far from neutral is the average belief?
    conviction = float(min(abs(net_sentiment) * 2, 1.0))

    confidence = 0.4 * agreement_index + 0.35 * consistency + 0.25 * conviction

    # --- Convergence rate: how fast beliefs settled -------------------------
    if n_ticks > 10:
        early_std = float(np.std(belief_hist[:, :10, :]))
        late_std = float(np.std(belief_hist[:, -10:, :]))
        convergence_rate = float(np.clip((early_std - late_std) / max(early_std, 1e-8), 0.0, 1.0))
    else:
        convergence_rate = 0.0

    return MiroFishSignal(
        ticker=ticker,
        net_sentiment=net_sentiment,
        sentiment_momentum=sentiment_momentum,
        agreement_index=agreement_index,
        volatility_prediction=volatility_prediction,
        order_flow=order_flow,
        narrative_direction=narrative,
        probability=probability,
        confidence=confidence,
        n_simulations=n_simulations,
        n_agents=n_agents,
        convergence_rate=convergence_rate,
    )


def mirofish_signals_to_model_signals(
    mf_signals: Dict[str, MiroFishSignal],
) -> Dict[str, list]:
    """Convert MiroFishSignals to ModelSignal-compatible dicts for consensus.

    Each MiroFish signal produces multiple ModelSignal entries representing
    different aspects of the simulation (sentiment, flow, agreement).
    """
    from types_shared import ModelSignal

    result: Dict[str, list] = {}

    for ticker, mf in mf_signals.items():
        signals: list = []

        # Primary sentiment signal
        signals.append(ModelSignal(
            model_name="mirofish_sentiment",
            ticker=ticker,
            probability=mf.probability,
            confidence=mf.confidence,
            feature_group="mirofish",
            horizon_days=1,
        ))

        # Order flow signal — maps flow [-1,1] to probability [0,1]
        flow_prob = float(np.clip((mf.order_flow + 1.0) / 2.0, 0.0, 1.0))
        signals.append(ModelSignal(
            model_name="mirofish_flow",
            ticker=ticker,
            probability=flow_prob,
            confidence=mf.confidence * 0.8,
            feature_group="mirofish",
            horizon_days=1,
        ))

        # Agreement-weighted momentum signal
        momentum_prob = float(np.clip(0.5 + mf.sentiment_momentum * 50, 0.0, 1.0))
        signals.append(ModelSignal(
            model_name="mirofish_momentum",
            ticker=ticker,
            probability=momentum_prob,
            confidence=mf.agreement_index * mf.confidence,
            feature_group="mirofish",
            horizon_days=1,
        ))

        result[ticker] = signals

    return result


def _neutral_signal(ticker: str, n_sims: int, n_agents: int) -> MiroFishSignal:
    """Return a neutral (no-opinion) signal when simulation produces no data."""
    return MiroFishSignal(
        ticker=ticker,
        net_sentiment=0.0,
        sentiment_momentum=0.0,
        agreement_index=0.5,
        volatility_prediction=0.5,
        order_flow=0.0,
        narrative_direction="uncertain",
        probability=0.5,
        confidence=0.0,
        n_simulations=n_sims,
        n_agents=n_agents,
        convergence_rate=0.0,
    )
