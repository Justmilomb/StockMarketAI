"""Broad stock universe for config optimisation backtesting.

Testing against 7 watchlist tickers overfits the config to a tiny sample.
This module provides ~250 diverse stocks across sectors, market caps,
and geographies so the autoconfig optimizer finds parameters that
generalise to any stock — not just the ones you happen to hold.

The optimizer picks random subsets per experiment to keep each run fast
while covering the full universe over many experiments.
"""

from __future__ import annotations

import random
from typing import Dict, List

# ---------------------------------------------------------------------------
# Universe: ~250 liquid stocks across sectors and geographies
# All must have history back to at least 2018 on Yahoo Finance.
# ---------------------------------------------------------------------------

# ── US Mega Cap (top ~60) ────────────────────────────────────────────

UNIVERSE_US_MEGA = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "INTC", "CRM", "ORCL", "ADBE", "NFLX", "PYPL", "SQ", "AVGO",
    "CSCO", "TXN", "QCOM", "IBM", "NOW", "INTU", "AMAT", "MU",
    # Finance
    "JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "C",
    "WFC", "SCHW", "BLK", "USB", "PNC", "TFC",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY", "BMY",
    "AMGN", "GILD", "ISRG", "MDT", "SYK", "ZTS", "VRTX",
    # Consumer
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "PG", "KO", "PEP",
    "CL", "EL", "TGT", "LOW", "LULU", "YUM", "CMG",
    # Industrial
    "BA", "CAT", "GE", "HON", "UPS", "DE", "MMM", "LMT", "RTX",
    "FDX", "GD", "NOC", "ITW", "EMR",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "VLO", "MPC", "OXY",
    # Telecom / Media
    "DIS", "CMCSA", "T", "VZ", "TMUS",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP",
    # REITs
    "AMT", "PLD", "CCI", "EQIX", "SPG",
    # Materials
    "LIN", "APD", "ECL", "SHW", "NEM", "FCX",
]

# ── US Mid/Small Cap (growth + volatile) ─────────────────────────────

UNIVERSE_US_MID = [
    # Mid-cap growth / volatile
    "ROKU", "SNAP", "PINS", "DKNG", "PLTR", "SOFI", "RIVN",
    "UPST", "ABNB", "DASH", "ZM", "CRWD", "SNOW", "NET",
    "COIN", "MARA", "RIOT", "HOOD", "AFRM", "PATH",
    # Mid-cap value / stable
    "ETSY", "BILL", "ZS", "DDOG", "OKTA", "TWLO", "TTD",
    "ENPH", "SEDG", "FSLR", "PLUG", "CHPT",
    # Biotech
    "MRNA", "BNTX", "REGN", "BIIB", "ILMN",
    # Semiconductors
    "MRVL", "ON", "SWKS", "KLAC", "LRCX", "NXPI",
    # Fintech / payments
    "FIS", "FISV", "GPN", "WEX",
    # Travel / leisure
    "MAR", "HLT", "RCL", "CCL", "WYNN", "LVS",
    # Food & beverage
    "MDLZ", "GIS", "KHC", "HSY", "STZ",
]

# ── UK FTSE ──────────────────────────────────────────────────────────

UNIVERSE_UK = [
    # FTSE 100 (yfinance .L suffix)
    "RR.L", "BBY.L", "VUKG.L", "SHEL.L", "BP.L", "AZN.L",
    "HSBA.L", "ULVR.L", "GSK.L", "RIO.L", "BARC.L", "LLOY.L",
    "VOD.L", "BT-A.L", "IAG.L", "LSEG.L", "REL.L", "NG.L",
    "SSE.L", "NWG.L", "STAN.L", "PRU.L", "ANTO.L", "CRH.L",
    "DGE.L", "RKT.L", "SMT.L", "EXPN.L",
]

# ── European Blue Chips ──────────────────────────────────────────────

UNIVERSE_EU = [
    # Germany
    "SAP.DE", "SIE.DE", "ALV.DE", "BAS.DE", "BMW.DE", "MBG.DE",
    "DTE.DE", "MUV2.DE", "ADS.DE", "HEN3.DE",
    # France
    "MC.PA", "OR.PA", "SAN.PA", "BNP.PA", "AI.PA", "SU.PA",
    "DG.PA", "CS.PA", "RI.PA",
    # Netherlands
    "ASML.AS", "PHIA.AS", "UNA.AS", "INGA.AS",
    # Spain / Italy
    "SAN.MC", "ITX.MC", "TEF.MC",
    # Switzerland (traded on US OTC / yfinance-compatible)
    "NSRGY", "RHHBY",
]

# ── User's watchlist tickers (always included) ───────────────────────

USER_WATCHLIST = [
    "CCCX", "VLVLY", "KRKNF",
    # VUKG.L, RR.L, BBY.L already in UNIVERSE_UK
    # TSLA already in UNIVERSE_US_MEGA
]

# ── Crypto-adjacent equities ─────────────────────────────────────────

UNIVERSE_CRYPTO_PROXIES = [
    "MSTR", "COIN", "MARA", "RIOT", "BITF", "HUT",
]

# ── Full universe ────────────────────────────────────────────────────

FULL_UNIVERSE: List[str] = (
    UNIVERSE_US_MEGA
    + UNIVERSE_US_MID
    + UNIVERSE_UK
    + UNIVERSE_EU
    + USER_WATCHLIST
    + UNIVERSE_CRYPTO_PROXIES
)

# De-duplicate
FULL_UNIVERSE = list(dict.fromkeys(FULL_UNIVERSE))


def get_universe(size: str = "medium", seed: int | None = None) -> List[str]:
    """Return a stock universe for backtesting.

    Args:
        size: "small" (15), "medium" (30), "large" (80), "full" (~250)
        seed: Random seed for reproducible subsets. None = random.

    Returns:
        List of yfinance-compatible ticker strings.
    """
    if size == "full":
        return list(FULL_UNIVERSE)

    counts = {"small": 15, "medium": 30, "large": 80}
    n = counts.get(size, 30)

    rng = random.Random(seed)

    # Stratified sampling: ensure mix of sectors/geographies
    pools = [
        (UNIVERSE_US_MEGA, 0.45),   # 45% US mega cap
        (UNIVERSE_US_MID, 0.25),    # 25% US mid cap (volatile)
        (UNIVERSE_UK, 0.15),        # 15% UK
        (UNIVERSE_EU, 0.15),        # 15% EU
    ]

    selected: List[str] = []
    for pool, frac in pools:
        pool_n = max(2, int(n * frac))
        picked = rng.sample(pool, min(pool_n, len(pool)))
        selected.extend(picked)

    # Always include user watchlist tickers for relevance
    for t in USER_WATCHLIST:
        if t not in selected:
            selected.append(t)

    # De-dupe and trim to target size
    selected = list(dict.fromkeys(selected))[:n]
    return selected


# Sector groupings for pattern-aware testing
SECTOR_GROUPS = {
    "tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "CRM", "NFLX", "AVGO", "CSCO", "TXN", "QCOM", "IBM"],
    "finance": ["JPM", "BAC", "GS", "V", "MA", "BRK-B", "WFC", "BLK", "SCHW", "HSBA.L", "BARC.L", "LLOY.L", "BNP.PA"],
    "healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "AMGN", "GILD", "MRNA", "AZN.L", "GSK.L"],
    "consumer": ["WMT", "COST", "HD", "MCD", "NKE", "SBUX", "PG", "KO", "LULU", "ULVR.L", "DGE.L"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "OXY", "SHEL.L", "BP.L"],
    "industrial": ["BA", "CAT", "GE", "HON", "UPS", "LMT", "RTX", "SIE.DE"],
    "volatile": ["TSLA", "ROKU", "SNAP", "COIN", "MARA", "RIVN", "DKNG", "PLTR", "UPST", "SOFI", "HOOD"],
    "defensive": ["JNJ", "PG", "KO", "PEP", "WMT", "NEE", "DUK", "AMT", "CL", "GIS"],
    "growth": ["NVDA", "CRWD", "SNOW", "NET", "DDOG", "TTD", "ZS", "PLTR", "ABNB"],
    "uk_ftse": UNIVERSE_UK,
    "eu_blue": UNIVERSE_EU,
    "reits": ["AMT", "PLD", "CCI", "EQIX", "SPG"],
    "crypto": UNIVERSE_CRYPTO_PROXIES,
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
    print(f"Medium sample: {len(get_universe('medium', seed=42))} tickers")
    print(f"Large sample:  {len(get_universe('large', seed=42))} tickers")
    print(f"\nSector groups: {', '.join(SECTOR_GROUPS.keys())}")
