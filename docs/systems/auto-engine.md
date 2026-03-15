# Auto Engine

## Goal
Converts AI signals into actual broker orders when the terminal is in `full_auto_limited` mode, respecting daily loss limits.

## Implementation
Single `step()` method called each refresh cycle. Only activates when `state.mode == "full_auto_limited"`. Fetches latest signals, generates market orders (qty=1) for all buy and sell signals. Checks unrealised PnL against `capital × max_daily_loss` — skips all orders if limit breached.

## Key Code
```python
@dataclass
class AutoEngine:
    config: ConfigDict
    state: AppState
    ai_service: AiService
    broker_service: BrokerService

    def step(self) -> None
```

## Notes
- Only submits market orders with fixed quantity 1.0
- Daily loss limit is a simple check, not a rolling window
- Results appended to `state.recent_orders` for display
- No position sizing logic yet — future enhancement
