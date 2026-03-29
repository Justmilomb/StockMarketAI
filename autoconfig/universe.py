"""Broad stock universe for config optimisation backtesting.

Testing against 7 watchlist tickers overfits the config to a tiny sample.
This module provides 100+ diverse stocks across sectors, market caps,
and geographies so the autoconfig optimizer finds parameters that
generalise to any stock — not just the ones you happen to hold.

The optimizer picks random subsets per experiment to keep each run fast
while covering the full universe over many experiments.
"""

from __future__ import annotations

import random
from typing import Dict, List

# ---------------------------------------------------------------------------
# Universe: ~120 liquid stocks across sectors and geographies
# All must have history back to at least 2018 on Yahoo Finance.
# ---------------------------------------------------------------------------

UNIVERSE_US_MEGA = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "INTC", "CRM", "ORCL", "ADBE", "NFLX", "PYPL", "SQ",
    # Finance
    "JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "C",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY", "BMY",
    # Consumer
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "PG", "KO", "PEP",
    # Industrial
    "BA", "CAT", "GE", "HON", "UPS", "DE", "MMM",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Telecom / Media
    "DIS", "CMCSA", "T", "VZ",
]

UNIVERSE_US_MID = [
    # Mid-cap growth / volatile
    "ROKU", "SNAP", "PINS", "DKNG", "PLTR", "SOFI", "RIVN",
    "UPST", "ABNB", "DASH", "ZM", "CRWD", "SNOW", "NET",
    "COIN", "MARA", "RIOT",
]

UNIVERSE_UK = [
    # FTSE (yfinance .L suffix)
    "RR.L", "BBY.L", "VUKG.L", "SHEL.L", "BP.L", "AZN.L",
    "HSBA.L", "ULVR.L", "GSK.L", "RIO.L", "BARC.L", "LLOY.L",
    "VOD.L", "BT-A.L", "IAG.L",
]

UNIVERSE_EU = [
    # Major European stocks (yfinance format)
    "SAP.DE", "SIE.DE", "ALV.DE", "BAS.DE",     # Germany
    "MC.PA", "OR.PA", "SAN.PA", "BNP.PA",        # France
    "ASML.AS", "PHIA.AS",                         # Netherlands
]

UNIVERSE_CRYPTO_PROXIES = [
    # Crypto-adjacent equities (high volatility — good stress test)
    "MSTR", "COIN", "MARA",
]

# Full universe
FULL_UNIVERSE: List[str] = (
    UNIVERSE_US_MEGA
    + UNIVERSE_US_MID
    + UNIVERSE_UK
    + UNIVERSE_EU
    # CRYPTO_PROXIES already overlap with US_MID, skip dupes
)

# De-duplicate
FULL_UNIVERSE = list(dict.fromkeys(FULL_UNIVERSE))


def get_universe(size: str = "medium", seed: int | None = None) -> List[str]:
    """Return a stock universe for backtesting.

    Args:
        size: "small" (15), "medium" (30), "large" (60), "full" (~100+)
        seed: Random seed for reproducible subsets. None = random.

    Returns:
        List of yfinance-compatible ticker strings.
    """
    if size == "full":
        return list(FULL_UNIVERSE)

    counts = {"small": 15, "medium": 30, "large": 60}
    n = counts.get(size, 30)

    rng = random.Random(seed)

    # Stratified sampling: ensure mix of sectors/geographies
    pools = [
        (UNIVERSE_US_MEGA, 0.50),   # 50% US mega cap
        (UNIVERSE_US_MID, 0.20),    # 20% US mid cap (volatile)
        (UNIVERSE_UK, 0.15),        # 15% UK
        (UNIVERSE_EU, 0.15),        # 15% EU
    ]

    selected: List[str] = []
    for pool, frac in pools:
        pool_n = max(2, int(n * frac))
        picked = rng.sample(pool, min(pool_n, len(pool)))
        selected.extend(picked)

    # De-dupe and trim to target size
    selected = list(dict.fromkeys(selected))[:n]
    return selected


# Sector groupings for pattern-aware testing
SECTOR_GROUPS = {
    "tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "CRM", "NFLX"],
    "finance": ["JPM", "BAC", "GS", "V", "MA", "BRK-B", "HSBA.L", "BARC.L", "LLOY.L"],
    "healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "AZN.L", "GSK.L"],
    "consumer": ["WMT", "COST", "HD", "MCD", "NKE", "SBUX", "PG", "KO", "ULVR.L"],
    "energy": ["XOM", "CVX", "COP", "SLB", "SHEL.L", "BP.L"],
    "industrial": ["BA", "CAT", "GE", "HON", "UPS", "SIE.DE"],
    "volatile": ["TSLA", "ROKU", "SNAP", "COIN", "MARA", "RIVN", "DKNG", "PLTR"],
    "uk_ftse": UNIVERSE_UK,
    "eu_blue": UNIVERSE_EU,
}

# ---------------------------------------------------------------------------
# Crisis periods for stress testing
# Each defines a date window covering a significant market dislocation.
# ---------------------------------------------------------------------------

CRISIS_PERIODS: Dict[str, Dict[str, str]] = {
    "2008_financial_crisis": {"start": "2007-10-01", "end": "2009-03-31"},
    "2020_covid_crash": {"start": "2020-02-01", "end": "2020-06-30"},
    "2022_bear_market": {"start": "2022-01-01", "end": "2022-12-31"},
    "2018_q4_selloff": {"start": "2018-10-01", "end": "2019-01-31"},
    "2023_bank_crisis": {"start": "2023-03-01", "end": "2023-05-31"},
}


def get_crisis_period(name: str) -> Dict[str, str] | None:
    """Return start/end dates for a named crisis period, or None if unknown."""
    return CRISIS_PERIODS.get(name)


def get_all_crisis_periods() -> Dict[str, Dict[str, str]]:
    """Return a copy of all crisis period definitions."""
    return dict(CRISIS_PERIODS)


if __name__ == "__main__":
    print(f"Full universe: {len(FULL_UNIVERSE)} tickers")
    print(f"Small sample:  {get_universe('small', seed=42)}")
    print(f"Medium sample: {get_universe('medium', seed=42)}")
    print(f"Large sample:  {len(get_universe('large', seed=42))} tickers")
