"""Core dataclasses for the MiroFish multi-agent simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal

import numpy as np

# ---------------------------------------------------------------------------
# Agent taxonomy
# ---------------------------------------------------------------------------

AgentType = Literal[
    "momentum",
    "mean_reversion",
    "sentiment",
    "fundamental",
    "noise",
    "contrarian",
    "institutional",
    "algorithmic",
    "llm_seeded",
]

AGENT_TYPE_IDS: Dict[AgentType, int] = {
    "momentum": 0,
    "mean_reversion": 1,
    "sentiment": 2,
    "fundamental": 3,
    "noise": 4,
    "contrarian": 5,
    "institutional": 6,
    "algorithmic": 7,
    "llm_seeded": 8,
}


@dataclass
class AgentTypeConfig:
    """Parameters that define how one class of agents behaves."""

    agent_type: AgentType
    count: int

    # -- Belief update knobs --------------------------------------------------
    trend_sensitivity: float = 0.5      # How strongly price trends shift belief
    reversion_strength: float = 0.0     # Pull belief toward neutral (0)
    news_sensitivity: float = 0.3       # How strongly news sentiment shifts belief
    feature_sensitivity: float = 0.2    # How much ML features affect belief
    noise_scale: float = 0.05           # Per-tick Gaussian noise σ

    # -- Social dynamics ------------------------------------------------------
    herd_susceptibility: float = 0.2    # How much crowd opinion pulls belief
    contrarian_factor: float = 0.0      # How much to push *against* crowd

    # -- Agent character ------------------------------------------------------
    memory_decay: float = 0.95          # Exponential decay of past observations
    time_horizon: int = 5               # Typical holding period (days)
    risk_tolerance: float = 0.5         # Position-sizing aggressiveness [0, 1]
    conviction_threshold: float = 0.3   # Min |belief| to open a position


# ---------------------------------------------------------------------------
# Simulation configuration
# ---------------------------------------------------------------------------

@dataclass
class SimulationConfig:
    """Full configuration for one MiroFish run."""

    n_agents: int = 1000
    n_ticks: int = 100
    n_simulations: int = 16            # Monte Carlo runs per ticker
    n_processes: int | None = None     # None → os.cpu_count()

    # -- Market micro-structure -----------------------------------------------
    price_impact_factor: float = 0.001  # How much net demand moves price
    base_volatility: float = 0.02       # Baseline per-tick vol
    liquidity: float = 1.0              # Dampens price impact

    # -- Social interaction ---------------------------------------------------
    influence_radius: int = 15          # Convolution kernel half-width
    information_decay: float = 0.95     # Global belief persistence per tick

    # -- Agent distribution ---------------------------------------------------
    agent_distribution: Dict[AgentType, int] = field(default_factory=lambda: {
        "momentum": 150,
        "mean_reversion": 120,
        "sentiment": 100,
        "fundamental": 150,
        "noise": 30,
        "contrarian": 80,
        "institutional": 120,
        "algorithmic": 150,
        "llm_seeded": 100,
    })

    # -- Integration weight ---------------------------------------------------
    consensus_weight: float = 0.15      # Weight in final consensus blend


# ---------------------------------------------------------------------------
# Market state fed to each simulation tick
# ---------------------------------------------------------------------------

@dataclass
class MarketContext:
    """External data injected into the simulation at initialisation."""

    ticker: str
    recent_returns: np.ndarray          # Last N daily returns (newest last)
    trend_signal: float                 # [-1, 1] from moving-average crossover
    rsi_signal: float                   # Normalised RSI → [-1, 1]
    volatility: float                   # Recent realised vol
    news_sentiment: float               # [-1, 1] from news agent
    regime: str                         # "trending_up" / "trending_down" / etc.
    ensemble_probability: float         # P(up) from meta-ensemble
    features: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Simulation output
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """Raw output from one Monte Carlo simulation run."""

    final_beliefs: np.ndarray           # (n_agents,) in [-1, 1]
    belief_history: np.ndarray          # (n_ticks, n_agents)
    position_history: np.ndarray        # (n_ticks, n_agents) in [-1, 1]
    synthetic_prices: np.ndarray        # (n_ticks,) normalised around 1.0
    order_flow_history: np.ndarray      # (n_ticks,) net buy-sell each tick
    agent_types: np.ndarray             # (n_agents,) int type IDs


# ---------------------------------------------------------------------------
# Extracted trading signal
# ---------------------------------------------------------------------------

@dataclass
class MiroFishSignal:
    """Structured output from MiroFish for one ticker."""

    ticker: str

    # -- Core outputs ---------------------------------------------------------
    net_sentiment: float                # Mean belief [-1, 1]
    sentiment_momentum: float           # Δ(net_sentiment) per tick (recent)
    agreement_index: float              # 1 - normalised_std(beliefs) [0, 1]
    volatility_prediction: float        # Expected vol from belief disagreement
    order_flow: float                   # Net buy pressure [-1, 1]
    narrative_direction: str            # "bullish" / "bearish" / "uncertain"

    # -- Derived for consensus integration ------------------------------------
    probability: float                  # P(up) mapped from sentiment [0, 1]
    confidence: float                   # Signal reliability [0, 1]

    # -- Metadata -------------------------------------------------------------
    n_simulations: int = 0
    n_agents: int = 0
    convergence_rate: float = 0.0       # How fast beliefs converged
