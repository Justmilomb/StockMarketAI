"""Polymarket-specific dataclasses.

These sit alongside the shared types in types_shared.py but capture
concepts unique to prediction markets: events (not tickers) and
probability edges (not price movements).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal


@dataclass
class PolymarketConfig:
    """Polymarket-specific configuration loaded from config.json."""

    enabled: bool = False
    min_volume: float = 1_000
    min_liquidity: float = 500
    max_markets: int = 20
    edge_threshold: float = 5.0       # minimum edge in percentage points
    use_claude: bool = True           # Claude probability estimation
    max_resolution_days: float = 90
    categories: List[str] = field(default_factory=lambda: [
        "crypto", "politics", "sports", "science",
    ])

    @classmethod
    def from_config(cls, cfg: Dict) -> "PolymarketConfig":
        """Build from the config.json 'polymarket' section."""
        poly = cfg.get("polymarket", {})
        strat = poly.get("strategy", {})
        model = poly.get("model", {})
        return cls(
            enabled=bool(poly.get("enabled", False)),
            min_volume=float(strat.get("min_volume_24h", 1_000)),
            min_liquidity=float(strat.get("min_liquidity", 500)),
            max_markets=int(poly.get("max_markets", 20)),
            edge_threshold=float(strat.get("min_edge_pct", 5.0)),
            use_claude=bool(model.get("use_claude", True)),
            max_resolution_days=float(strat.get("max_resolution_days", 90)),
            categories=poly.get("categories", [
                "crypto", "politics", "sports", "science",
            ]),
        )


@dataclass
class PolymarketEvent:
    """A single prediction-market event from Polymarket.

    The *outcome_prices* dict maps outcome labels (e.g. "Yes" / "No")
    to the current market price in [0.0, 1.0], which IS the market's
    implied probability for that outcome.
    """

    condition_id: str
    question: str
    description: str
    category: str
    end_date: datetime
    outcome_prices: Dict[str, float]       # e.g. {"Yes": 0.65, "No": 0.35}
    volume_24h: float = 0.0
    liquidity: float = 0.0
    num_traders: int = 0
    slug: str = ""
    active: bool = True
    closed: bool = False
    tokens: Dict[str, str] = field(default_factory=dict)  # outcome -> token_id

    @property
    def market_probability(self) -> float:
        """Current market-implied probability for YES."""
        return self.outcome_prices.get("Yes", 0.5)

    @property
    def is_binary(self) -> bool:
        """Whether this is a simple Yes/No market."""
        return set(self.outcome_prices.keys()) == {"Yes", "No"}


@dataclass
class PolymarketEdge:
    """Detected mispricing edge on a prediction market.

    The core thesis: if our AI estimates P(event) differently from
    the market price, and the gap exceeds our confidence threshold,
    there is a trading edge.
    """

    condition_id: str
    question: str
    ai_probability: float       # our estimate of P(Yes) in [0.0, 1.0]
    market_probability: float   # current YES price in [0.0, 1.0]
    edge: float                 # ai_probability - market_probability
    confidence: float           # [0.0, 1.0] — how sure we are about the edge
    recommended_side: Literal["YES", "NO"]
    kelly_size: float           # Kelly-optimal fraction of bankroll
