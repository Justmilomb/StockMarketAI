"""MiroFish Monte Carlo agent simulation for prediction markets.

Takes research briefs (specialist AI estimates) and runs a
population of simulated agents with diverse biases to produce
a robust probability consensus + confidence interval.

Agent population (default 500):
  - Research-anchored agents:  seeded from each specialist's estimate,
    perturbed by Gaussian noise scaled to the specialist's confidence
  - Trend-follower agents:     lean toward the market price
  - Contrarian agents:         lean away from the market price
  - Noise agents:              uniform random for calibration baseline

The Monte Carlo output is:
  - Median probability (more robust than mean to outlier agents)
  - Confidence: inverse of inter-quartile range (tight = high confidence)
  - Distribution percentiles for risk sizing
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from polymarket.research import ResearchBrief
from polymarket.types import PolymarketEvent

logger = logging.getLogger(__name__)


@dataclass
class MiroFishResult:
    """Monte Carlo consensus for one prediction market event."""

    condition_id: str
    probability: float       # median of agent population
    confidence: float        # [0.0, 1.0] — based on agent agreement
    p25: float               # 25th percentile
    p75: float               # 75th percentile
    n_agents: int
    agent_std: float         # standard deviation of agent estimates


@dataclass
class MiroFishConfig:
    """Configuration for the Monte Carlo simulation."""

    n_agents: int = 500
    research_agent_fraction: float = 0.50   # 50% seeded from research
    trend_agent_fraction: float = 0.15      # 15% lean toward market
    contrarian_agent_fraction: float = 0.15 # 15% lean away from market
    noise_agent_fraction: float = 0.20      # 20% random baseline
    noise_scale: float = 0.12              # base Gaussian noise σ
    seed: int | None = None

    @classmethod
    def from_config(cls, cfg: Dict) -> "MiroFishConfig":
        mf = cfg.get("polymarket", {}).get("mirofish", {})
        return cls(
            n_agents=int(mf.get("n_agents", 500)),
            noise_scale=float(mf.get("noise_scale", 0.12)),
            seed=mf.get("seed"),
        )


class MiroFishSimulator:
    """Monte Carlo agent simulation for prediction-market probability estimation."""

    def __init__(self, config: MiroFishConfig | None = None) -> None:
        self._cfg = config or MiroFishConfig()
        self._rng = np.random.default_rng(self._cfg.seed)

    def simulate(
        self,
        events: List[PolymarketEvent],
        briefs: List[ResearchBrief],
    ) -> List[MiroFishResult]:
        """Run Monte Carlo simulation for all events.

        Args:
            events: Market events with current prices.
            briefs: Research briefs with specialist agent estimates.

        Returns:
            List of MiroFishResult, one per event.
        """
        results: List[MiroFishResult] = []

        for event, brief in zip(events, briefs):
            result = self._simulate_one(event, brief)
            results.append(result)

        logger.info(
            "MiroFish: simulated %d events with %d agents each",
            len(results), self._cfg.n_agents,
        )
        return results

    def _simulate_one(
        self,
        event: PolymarketEvent,
        brief: ResearchBrief,
    ) -> MiroFishResult:
        """Run Monte Carlo for a single event."""
        cfg = self._cfg
        n = cfg.n_agents
        market_prob = event.market_probability

        # Partition agent counts
        n_research = int(n * cfg.research_agent_fraction)
        n_trend = int(n * cfg.trend_agent_fraction)
        n_contrarian = int(n * cfg.contrarian_agent_fraction)
        n_noise = n - n_research - n_trend - n_contrarian

        estimates = np.empty(n, dtype=np.float64)
        idx = 0

        # ── Research-anchored agents ─────────────────────────────────
        # Distribute evenly across specialist estimates
        if brief.estimates and n_research > 0:
            per_specialist = max(1, n_research // len(brief.estimates))
            for est in brief.estimates:
                count = min(per_specialist, n_research - idx)
                if count <= 0:
                    break
                # Lower confidence → more noise (wider distribution)
                sigma = cfg.noise_scale * (1.5 - est.confidence)
                estimates[idx:idx + count] = self._rng.normal(
                    est.probability, sigma, size=count,
                )
                idx += count
            # Fill remaining research slots with mean-anchored agents
            while idx < n_research:
                estimates[idx] = self._rng.normal(
                    brief.mean_probability, cfg.noise_scale,
                )
                idx += 1
        else:
            # No research data — use market price with wide noise
            estimates[:n_research] = self._rng.normal(
                market_prob, cfg.noise_scale * 2.0, size=n_research,
            )
            idx = n_research

        # ── Trend-follower agents (lean toward market) ───────────────
        trend_anchor = market_prob
        estimates[idx:idx + n_trend] = self._rng.normal(
            trend_anchor, cfg.noise_scale * 0.5, size=n_trend,
        )
        idx += n_trend

        # ── Contrarian agents (lean away from market) ────────────────
        # Mirror the research mean across the market price
        if brief.estimates:
            contrarian_anchor = 2 * brief.mean_probability - market_prob
        else:
            contrarian_anchor = 1.0 - market_prob
        contrarian_anchor = max(0.05, min(0.95, contrarian_anchor))
        estimates[idx:idx + n_contrarian] = self._rng.normal(
            contrarian_anchor, cfg.noise_scale * 1.5, size=n_contrarian,
        )
        idx += n_contrarian

        # ── Noise agents (uniform random calibration) ────────────────
        estimates[idx:idx + n_noise] = self._rng.uniform(0.01, 0.99, size=n_noise)

        # Clamp all estimates to [0.01, 0.99]
        np.clip(estimates, 0.01, 0.99, out=estimates)

        # ── Aggregate ────────────────────────────────────────────────
        median = float(np.median(estimates))
        p25 = float(np.percentile(estimates, 25))
        p75 = float(np.percentile(estimates, 75))
        std = float(np.std(estimates))

        # Confidence: inverse of IQR — tight agreement = high confidence
        iqr = p75 - p25
        confidence = max(0.05, min(0.95, 1.0 - iqr * 2.0))

        return MiroFishResult(
            condition_id=event.condition_id,
            probability=round(median, 4),
            confidence=round(confidence, 4),
            p25=round(p25, 4),
            p75=round(p75, 4),
            n_agents=n,
            agent_std=round(std, 4),
        )
