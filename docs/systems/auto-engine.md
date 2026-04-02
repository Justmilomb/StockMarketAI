# Auto Engine

## Goal
Converts AI signals into risk-managed broker orders when the terminal is in `full_auto_limited` mode, respecting daily loss limits.

## Implementation
Single `step()` method called each refresh cycle. Only activates when `state.mode == "full_auto_limited"`. Reads cached signals from `state.signals` (populated by the AI pipeline on refresh — does not re-run the pipeline). Skips protected/locked tickers. Checks unrealised PnL against `capital × max_daily_loss` — skips all orders if limit breached. Delegates to `RiskManager.generate_risk_enhanced_orders()` for Kelly + ATR-based sizing, then submits via `BrokerService.submit_orders()`.

## Key Code
```python
@dataclass
class AutoEngine:
    config: ConfigDict
    state: AppState
    ai_service: AiService
    broker_service: BrokerService
    _risk_manager: RiskManager | None = None

    def step(self) -> None
```

## Notes
- Uses cached signals from state — does not redundantly re-run the AI pipeline
- Position sizing via RiskManager (Kelly + ATR + drawdown + consensus disagreement)
- Protected tickers from `state.protected_tickers` are filtered out before order generation
- Daily loss limit is a simple unrealised PnL check, not a rolling window
- Results appended to `state.recent_orders` for display
- RiskManager is lazy-initialised on first `step()` call
