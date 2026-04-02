# Risk Manager

## Purpose
Portfolio-level risk management: Kelly criterion sizing, ATR-based stops/targets, drawdown protection, concentration limits. Replaces hard-coded qty=1 orders.

## Position Sizing Pipeline
1. Kelly fraction from probability → cap at 25%
2. Volatility-adjusted size (1 ATR = 2% of capital)
3. Take minimum of (Kelly, vol-adjusted, max position cap at 15% of capital)
4. Drawdown multiplier (halve sizes when >10% drawdown)
5. Consensus disagreement penalty (up to 50% reduction at max disagreement)
6. Floor at minimum position ($1 default); zero out if below floor
7. Convert to fractional shares (T212) or whole shares

## Public API
- `RiskManager.kelly_criterion(probability, win_loss_ratio) -> float` — Capped Kelly fraction
- `RiskManager.volatility_adjusted_size(capital, atr, price, risk_pct) -> float` — Dollar sizing
- `RiskManager.compute_stop_loss/take_profit(entry, atr, side) -> float` — ATR-based levels
- `RiskManager.check_portfolio_risk(positions, account, ticker, size) -> (allowed, reason)` — Guards
- `RiskManager.check_drawdown_protection(account, capital) -> float` — 1.0 or reduction multiplier
- `RiskManager.assess_position(...) -> RiskAssessment` — Full sizing pipeline
- `RiskManager.generate_risk_enhanced_orders(signals_df, consensus, ...) -> List[order]` — Complete order generation

## Configuration
- risk.kelly_fraction_cap (0.25), risk.max_position_pct (0.15)
- risk.atr_stop_multiplier (2.0), risk.atr_profit_multiplier (3.0)
- risk.drawdown_threshold (0.10), risk.drawdown_size_reduction (0.5)
- risk.min_position_dollars (1.0), risk.max_open_positions (10)
- risk.cash_buffer_pct (0.05), risk.fractional_shares (True)

## Dependencies
- types_shared.py (ConsensusResult, RiskAssessment), pandas, numpy
