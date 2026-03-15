# Strategy

## Goal
Converts model probability predictions into actionable buy/sell/hold signals based on configurable thresholds and position limits.

## Implementation
Ranks tickers by P(up) descending. Applies buy threshold (default 0.6) for tickers not currently held, capped at `max_positions`. Applies sell threshold (default 0.4) for tickers currently held. Everything else is hold.

## Key Code
```python
@dataclass
class StrategyConfig:
    threshold_buy: float = 0.6
    threshold_sell: float = 0.4
    max_positions: int = 5
    position_size_fraction: float = 0.2

def generate_signals(prob_up, meta_latest, config, held_tickers) -> pd.DataFrame
```

## Notes
- Output columns: ticker, date, prob_up, signal
- Signal is always one of: "buy", "sell", "hold"
- Sell signals only generated for held tickers
- `position_size_fraction` used by daily_agent for sizing, not by strategy itself
