"""Agent type definitions and vectorized belief-update functions.

All 1000 agents are stored as contiguous numpy arrays.  Per-type behaviour
is expressed as vectorized update functions operating on masked slices —
no per-agent Python objects in the hot loop.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from mirofish.types import (
    AGENT_TYPE_IDS,
    AgentType,
    AgentTypeConfig,
    MarketContext,
    SimulationConfig,
)

# ---------------------------------------------------------------------------
# Default agent configs — one per type
# ---------------------------------------------------------------------------

DEFAULT_AGENT_CONFIGS: Dict[AgentType, AgentTypeConfig] = {
    "momentum": AgentTypeConfig(
        agent_type="momentum",
        count=150,
        trend_sensitivity=0.8,
        reversion_strength=0.0,
        news_sensitivity=0.2,
        feature_sensitivity=0.3,
        noise_scale=0.03,
        herd_susceptibility=0.35,
        contrarian_factor=0.0,
        memory_decay=0.92,
        time_horizon=5,
        risk_tolerance=0.6,
        conviction_threshold=0.2,
    ),
    "mean_reversion": AgentTypeConfig(
        agent_type="mean_reversion",
        count=120,
        trend_sensitivity=-0.6,       # Negative: believes trend will reverse
        reversion_strength=0.4,
        news_sensitivity=0.15,
        feature_sensitivity=0.25,
        noise_scale=0.04,
        herd_susceptibility=0.1,
        contrarian_factor=0.15,
        memory_decay=0.90,
        time_horizon=10,
        risk_tolerance=0.4,
        conviction_threshold=0.35,
    ),
    "sentiment": AgentTypeConfig(
        agent_type="sentiment",
        count=100,
        trend_sensitivity=0.3,
        reversion_strength=0.05,
        news_sensitivity=0.85,        # Very news-driven
        feature_sensitivity=0.1,
        noise_scale=0.06,
        herd_susceptibility=0.5,      # High herd — sentiment traders follow crowd
        contrarian_factor=0.0,
        memory_decay=0.85,
        time_horizon=3,
        risk_tolerance=0.55,
        conviction_threshold=0.15,
    ),
    "fundamental": AgentTypeConfig(
        agent_type="fundamental",
        count=150,
        trend_sensitivity=0.1,
        reversion_strength=0.3,
        news_sensitivity=0.2,
        feature_sensitivity=0.8,      # Lean harder on ML features
        noise_scale=0.02,
        herd_susceptibility=0.05,     # Independent thinkers
        contrarian_factor=0.1,
        memory_decay=0.97,            # Long memory
        time_horizon=20,
        risk_tolerance=0.35,
        conviction_threshold=0.35,    # Act slightly more often
    ),
    "noise": AgentTypeConfig(
        agent_type="noise",
        count=30,
        trend_sensitivity=0.2,
        reversion_strength=0.0,
        news_sensitivity=0.3,
        feature_sensitivity=0.0,
        noise_scale=0.15,             # Reduced noise — less random drag on accuracy
        herd_susceptibility=0.4,
        contrarian_factor=0.0,
        memory_decay=0.7,             # Short memory
        time_horizon=1,
        risk_tolerance=0.7,
        conviction_threshold=0.25,    # Less trigger-happy
    ),
    "contrarian": AgentTypeConfig(
        agent_type="contrarian",
        count=80,
        trend_sensitivity=-0.4,
        reversion_strength=0.2,
        news_sensitivity=-0.3,        # Negative: bets against news
        feature_sensitivity=0.3,
        noise_scale=0.04,
        herd_susceptibility=-0.3,     # Negative: repelled by crowd
        contrarian_factor=0.6,        # Strong contrarian pull
        memory_decay=0.93,
        time_horizon=7,
        risk_tolerance=0.5,
        conviction_threshold=0.3,
    ),
    "institutional": AgentTypeConfig(
        agent_type="institutional",
        count=120,
        trend_sensitivity=0.15,
        reversion_strength=0.1,
        news_sensitivity=0.1,
        feature_sensitivity=0.5,
        noise_scale=0.01,             # Very low noise — deliberate
        herd_susceptibility=0.05,
        contrarian_factor=0.05,
        memory_decay=0.98,            # Very long memory
        time_horizon=20,
        risk_tolerance=0.25,          # Conservative sizing
        conviction_threshold=0.4,     # Slightly lower bar — act more often
    ),
    "algorithmic": AgentTypeConfig(
        agent_type="algorithmic",
        count=150,
        trend_sensitivity=0.6,
        reversion_strength=0.15,
        news_sensitivity=0.1,
        feature_sensitivity=0.7,      # Lean harder on ML features
        noise_scale=0.02,
        herd_susceptibility=0.15,
        contrarian_factor=0.1,
        memory_decay=0.88,
        time_horizon=3,
        risk_tolerance=0.65,
        conviction_threshold=0.25,
    ),
    "llm_seeded": AgentTypeConfig(
        agent_type="llm_seeded",
        count=100,
        trend_sensitivity=0.4,
        reversion_strength=0.1,
        news_sensitivity=0.4,
        feature_sensitivity=0.5,
        noise_scale=0.03,
        herd_susceptibility=0.2,
        contrarian_factor=0.1,
        memory_decay=0.94,
        time_horizon=5,
        risk_tolerance=0.5,
        conviction_threshold=0.3,
    ),
}


# ---------------------------------------------------------------------------
# Population builder — initialises the flat numpy arrays
# ---------------------------------------------------------------------------

def build_population(
    config: SimulationConfig,
    market_ctx: MarketContext,
    rng: np.random.Generator,
) -> Dict[str, np.ndarray]:
    """Create the full agent population as flat numpy arrays.

    Returns a dict with keys:
        beliefs          (n,)   initial beliefs in [-1, 1]
        positions        (n,)   initial positions in [-1, 1]
        agent_types      (n,)   int type IDs
        trend_sens       (n,)   per-agent trend sensitivity
        reversion_str    (n,)   per-agent mean-reversion strength
        news_sens        (n,)   per-agent news sensitivity
        feature_sens     (n,)   per-agent feature sensitivity
        noise_scales     (n,)   per-agent noise σ
        herd_sus         (n,)   per-agent herd susceptibility
        contrarian_f     (n,)   per-agent contrarian factor
        memory_decays    (n,)   per-agent memory decay
        risk_tols        (n,)   per-agent risk tolerance
        conv_thresholds  (n,)   per-agent conviction threshold
    """
    n = config.n_agents
    dist = config.agent_distribution

    # Build ordered list of agent configs matching distribution
    configs: List[AgentTypeConfig] = []
    for atype, count in dist.items():
        base = DEFAULT_AGENT_CONFIGS.get(atype)
        if base is None:
            continue
        cfg = AgentTypeConfig(
            agent_type=atype,
            count=count,
            trend_sensitivity=base.trend_sensitivity,
            reversion_strength=base.reversion_strength,
            news_sensitivity=base.news_sensitivity,
            feature_sensitivity=base.feature_sensitivity,
            noise_scale=base.noise_scale,
            herd_susceptibility=base.herd_susceptibility,
            contrarian_factor=base.contrarian_factor,
            memory_decay=base.memory_decay,
            time_horizon=base.time_horizon,
            risk_tolerance=base.risk_tolerance,
            conviction_threshold=base.conviction_threshold,
        )
        configs.append(cfg)

    # Allocate arrays
    total_from_configs = sum(c.count for c in configs)
    actual_n = min(n, total_from_configs) if total_from_configs > 0 else n

    beliefs = np.zeros(actual_n)
    positions = np.zeros(actual_n)
    agent_types = np.zeros(actual_n, dtype=np.int32)
    trend_sens = np.zeros(actual_n)
    reversion_str = np.zeros(actual_n)
    news_sens = np.zeros(actual_n)
    feature_sens = np.zeros(actual_n)
    noise_scales = np.zeros(actual_n)
    herd_sus = np.zeros(actual_n)
    contrarian_f = np.zeros(actual_n)
    memory_decays = np.zeros(actual_n)
    risk_tols = np.zeros(actual_n)
    conv_thresholds = np.zeros(actual_n)

    idx = 0
    for cfg in configs:
        end = min(idx + cfg.count, actual_n)
        count = end - idx
        if count <= 0:
            break

        type_id = AGENT_TYPE_IDS.get(cfg.agent_type, 0)
        agent_types[idx:end] = type_id

        # Add per-agent variation (±20%) to avoid homogeneous herds
        def _jitter(base: float, n: int = count) -> np.ndarray:
            return base * (1.0 + 0.2 * rng.standard_normal(n))

        trend_sens[idx:end] = _jitter(cfg.trend_sensitivity)
        reversion_str[idx:end] = np.abs(_jitter(cfg.reversion_strength))
        news_sens[idx:end] = _jitter(cfg.news_sensitivity)
        feature_sens[idx:end] = _jitter(cfg.feature_sensitivity)
        noise_scales[idx:end] = np.abs(_jitter(cfg.noise_scale))
        herd_sus[idx:end] = _jitter(cfg.herd_susceptibility)
        contrarian_f[idx:end] = np.abs(_jitter(cfg.contrarian_factor))
        memory_decays[idx:end] = np.clip(_jitter(cfg.memory_decay), 0.5, 0.999)
        risk_tols[idx:end] = np.clip(_jitter(cfg.risk_tolerance), 0.05, 0.95)
        conv_thresholds[idx:end] = np.clip(_jitter(cfg.conviction_threshold), 0.05, 0.9)

        # Seed initial beliefs from market context
        base_belief = _seed_belief(cfg, market_ctx, rng, count)
        beliefs[idx:end] = np.clip(base_belief, -1.0, 1.0)

        idx = end

    # Shuffle agents so types are interspersed (important for interaction)
    perm = rng.permutation(actual_n)

    return {
        "beliefs": beliefs[perm],
        "positions": positions[perm],
        "agent_types": agent_types[perm],
        "trend_sens": trend_sens[perm],
        "reversion_str": reversion_str[perm],
        "news_sens": news_sens[perm],
        "feature_sens": feature_sens[perm],
        "noise_scales": noise_scales[perm],
        "herd_sus": herd_sus[perm],
        "contrarian_f": contrarian_f[perm],
        "memory_decays": memory_decays[perm],
        "risk_tols": risk_tols[perm],
        "conv_thresholds": conv_thresholds[perm],
    }


def _seed_belief(
    cfg: AgentTypeConfig,
    ctx: MarketContext,
    rng: np.random.Generator,
    n: int,
) -> np.ndarray:
    """Compute initial beliefs for *n* agents of a given type from market context."""

    # Weighted combination of signals based on agent type sensitivities
    trend_component = cfg.trend_sensitivity * ctx.trend_signal
    news_component = cfg.news_sensitivity * ctx.news_sentiment
    # Convert ensemble P(up) ∈ [0,1] → belief ∈ [-1,1]
    ensemble_belief = (ctx.ensemble_probability - 0.5) * 2.0
    feature_component = cfg.feature_sensitivity * ensemble_belief

    base = 0.4 * trend_component + 0.3 * news_component + 0.3 * feature_component

    # LLM-seeded agents start with a stronger prior from ensemble
    if cfg.agent_type == "llm_seeded":
        base = 0.7 * ensemble_belief + 0.2 * ctx.trend_signal + 0.1 * ctx.news_sentiment

    return base + cfg.noise_scale * rng.standard_normal(n)


# ---------------------------------------------------------------------------
# Vectorized per-tick observation function
# ---------------------------------------------------------------------------

def compute_observations(
    pop: Dict[str, np.ndarray],
    price_return: float,
    news_sentiment: float,
    feature_signal: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Compute per-agent observation signals for the current tick.

    Each agent type weights price trend, news, and features differently.
    Returns an array of observation deltas to be blended into beliefs.
    """
    n = len(pop["beliefs"])

    # Price trend signal (same for all, weighted per agent)
    trend_obs = pop["trend_sens"] * price_return

    # Mean-reversion pull toward neutral
    reversion_obs = -pop["reversion_str"] * pop["beliefs"]

    # News sentiment (same for all, weighted per agent)
    news_obs = pop["news_sens"] * news_sentiment

    # Feature/ML signal (same for all, weighted per agent)
    feature_obs = pop["feature_sens"] * feature_signal

    # Per-agent idiosyncratic noise
    noise = pop["noise_scales"] * rng.standard_normal(n)

    return trend_obs + reversion_obs + news_obs + feature_obs + noise


# ---------------------------------------------------------------------------
# Social interaction via convolution
# ---------------------------------------------------------------------------

def apply_social_influence(
    beliefs: np.ndarray,
    herd_sus: np.ndarray,
    contrarian_f: np.ndarray,
    radius: int,
) -> np.ndarray:
    """Apply herding and contrarian dynamics via neighbourhood averaging.

    Uses a uniform convolution kernel to compute local crowd belief,
    then applies herd pull and contrarian push per agent.
    """
    if radius <= 0:
        return beliefs.copy()

    kernel_size = 2 * radius + 1
    kernel = np.ones(kernel_size) / kernel_size

    # Padded convolution to get local average belief
    padded = np.pad(beliefs, radius, mode="wrap")
    crowd_belief = np.convolve(padded, kernel, mode="valid")[:len(beliefs)]

    # Herd pull: move toward crowd
    herd_delta = herd_sus * (crowd_belief - beliefs)

    # Contrarian push: move away from crowd
    contrarian_delta = contrarian_f * (beliefs - crowd_belief)

    return beliefs + herd_delta + contrarian_delta


# ---------------------------------------------------------------------------
# Position decision
# ---------------------------------------------------------------------------

def update_positions(
    beliefs: np.ndarray,
    positions: np.ndarray,
    risk_tols: np.ndarray,
    conv_thresholds: np.ndarray,
) -> np.ndarray:
    """Convert beliefs into position changes.

    Agents only change position when their belief exceeds conviction threshold.
    Position change is proportional to belief strength × risk tolerance.
    """
    # Only act when conviction exceeds threshold
    active = np.abs(beliefs) > conv_thresholds
    target = np.where(active, np.sign(beliefs) * np.abs(beliefs) * risk_tols, positions)

    # Smooth position changes (agents don't flip instantly)
    new_positions = 0.7 * positions + 0.3 * target
    return np.clip(new_positions, -1.0, 1.0)
