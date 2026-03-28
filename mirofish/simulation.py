"""Core simulation engine — runs one MiroFish simulation for one ticker.

All computation is numpy-vectorized.  A single simulation runs 1000 agents
for N ticks, producing belief histories, position histories, synthetic
price movements, and net order flow.
"""

from __future__ import annotations

import numpy as np

from mirofish.agents import (
    apply_social_influence,
    build_population,
    compute_observations,
    update_positions,
)
from mirofish.types import MarketContext, SimulationConfig, SimulationResult


def run_single_simulation(
    config: SimulationConfig,
    market_ctx: MarketContext,
    seed: int,
) -> SimulationResult:
    """Execute one complete MiroFish simulation run.

    Steps per tick:
        1. Agents observe market state (price return, news, features)
        2. Beliefs updated: decay × old + (1 - decay) × observation
        3. Social interaction: herding + contrarian dynamics via convolution
        4. Position decision: belief → position change
        5. Aggregate: net order flow → synthetic price impact
        6. Feedback: price change feeds into next tick's observation

    Args:
        config:     Simulation parameters (n_agents, n_ticks, etc.)
        market_ctx: External market data for this ticker
        seed:       Random seed for reproducibility across Monte Carlo runs

    Returns:
        SimulationResult with full history arrays
    """
    rng = np.random.default_rng(seed)
    n_ticks = config.n_ticks

    # --- Build population ---------------------------------------------------
    pop = build_population(config, market_ctx, rng)
    n_agents = len(pop["beliefs"])

    # --- Pre-allocate history arrays ----------------------------------------
    belief_history = np.zeros((n_ticks, n_agents))
    position_history = np.zeros((n_ticks, n_agents))
    synthetic_prices = np.ones(n_ticks)   # Normalised around 1.0
    order_flow_history = np.zeros(n_ticks)

    # --- Initial state ------------------------------------------------------
    beliefs = pop["beliefs"].copy()
    positions = pop["positions"].copy()
    current_price = 1.0
    prev_price = 1.0

    # Pre-compute feature signal from ensemble probability
    feature_signal = (market_ctx.ensemble_probability - 0.5) * 2.0

    # Inject external shocks from real price history
    real_returns = market_ctx.recent_returns
    n_real = len(real_returns)

    # --- Simulation loop ----------------------------------------------------
    for t in range(n_ticks):
        # Price return: blend synthetic + real (fading real influence over time)
        synthetic_return = (current_price - prev_price) / max(prev_price, 1e-8)
        real_weight = max(0.0, 1.0 - t / (n_ticks * 0.5))
        if t < n_real:
            price_return = real_weight * real_returns[t] + (1.0 - real_weight) * synthetic_return
        else:
            price_return = synthetic_return

        # 1. Observe
        obs = compute_observations(
            pop=_with_beliefs(pop, beliefs),
            price_return=price_return,
            news_sentiment=market_ctx.news_sentiment,
            feature_signal=feature_signal,
            rng=rng,
        )

        # 2. Update beliefs: exponential decay blend
        decays = pop["memory_decays"]
        beliefs = decays * beliefs + (1.0 - decays) * obs
        beliefs = np.clip(beliefs, -1.0, 1.0)

        # 3. Social interaction
        beliefs = apply_social_influence(
            beliefs=beliefs,
            herd_sus=pop["herd_sus"],
            contrarian_f=pop["contrarian_f"],
            radius=config.influence_radius,
        )
        beliefs = np.clip(beliefs, -1.0, 1.0)

        # 4. Position decision
        positions = update_positions(
            beliefs=beliefs,
            positions=positions,
            risk_tols=pop["risk_tols"],
            conv_thresholds=pop["conv_thresholds"],
        )

        # 5. Aggregate: net order flow → price impact
        net_flow = positions.mean()
        price_impact = (
            net_flow * config.price_impact_factor / config.liquidity
        )
        # Add stochastic vol
        price_noise = config.base_volatility * rng.standard_normal()

        prev_price = current_price
        current_price = current_price * (1.0 + price_impact + price_noise)
        current_price = max(current_price, 0.01)

        # 6. Record history
        belief_history[t] = beliefs
        position_history[t] = positions
        synthetic_prices[t] = current_price
        order_flow_history[t] = net_flow

    return SimulationResult(
        final_beliefs=beliefs,
        belief_history=belief_history,
        position_history=position_history,
        synthetic_prices=synthetic_prices,
        order_flow_history=order_flow_history,
        agent_types=pop["agent_types"],
    )


def _with_beliefs(pop: dict, beliefs: np.ndarray) -> dict:
    """Return a view of the population dict with updated beliefs."""
    updated = dict(pop)
    updated["beliefs"] = beliefs
    return updated
