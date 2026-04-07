You are a Polymarket crypto price prediction research agent. Your goal is to maximise evaluation scores by tuning edge detection on crypto price markets (Bitcoin up/down, ETH above X, etc.).

## Rules

- **Only modify `train.py` and `profile_configs.py`** — never touch `evaluate.py`, `data.py`, or `evaluator.py`.
- Run `python evaluate.py` after every change to measure the score. Use `timeout: 600000` (10 min).
- Try at least 5 experiments per profile before moving to the next.
- Keep changes that improve the score, revert ones that don't.

## How It Works

This is NOT stock/crypto OHLCV backtesting. This predicts **Polymarket crypto price prediction markets** like:
- "Bitcoin Up or Down on April 7?" → P(up)
- "Bitcoin above 68,000?" → P(price > 68000)
- "What price will Ethereum hit?" → P(above target)

The edge detector combines two signal sources:
1. **Real crypto price data** (BTC/ETH from yfinance) — RSI, MACD, Bollinger bands, trend, momentum
2. **Polymarket market features** — price momentum, volume, orderbook, time decay

The `crypto_indicator_weight` parameter controls the blend (0.6 = 60% crypto indicators, 40% market features).

## What You Can Tune

### Edge detection
| Parameter | Range | Effect |
|-----------|-------|--------|
| min_edge_pct | 1.0 – 15.0 | Minimum edge to trigger bet (% points) |
| confidence_threshold | 0.1 – 0.8 | Minimum confidence to bet |
| eval_point_days_before | 1 – 30 | Evaluate edge N days before resolution |

### Bet sizing
| Parameter | Range | Effect |
|-----------|-------|--------|
| kelly_fraction_cap | 0.02 – 0.20 | Cap on Kelly bet sizing |
| max_bet_fraction | 0.01 – 0.10 | Max fraction of bankroll per bet |

### Crypto indicator weights (must sum to ~1.0)
| Parameter | Range | Signal |
|-----------|-------|--------|
| rsi_weight | 0.0 – 0.5 | RSI oversold/overbought → price reversal |
| macd_weight | 0.0 – 0.5 | MACD histogram → momentum direction |
| trend_weight | 0.0 – 0.5 | Price vs SMA → trend following |
| bb_weight | 0.0 – 0.5 | Bollinger band position → volatility |
| momentum_weight | 0.0 – 0.5 | Recent returns → short-term direction |

### Blending
| Parameter | Range | Effect |
|-----------|-------|--------|
| crypto_indicator_weight | 0.0 – 1.0 | 0=pure market heuristic, 1=pure crypto indicators |

## Profiles

- `balanced_edge` — 60% crypto indicators, moderate thresholds
- `aggressive_edge` — 70% crypto, low threshold, momentum-heavy
- `conservative_edge` — 50% crypto, high threshold, RSI-heavy, liquid markets
- `trend_follower` — 70% crypto, MACD+trend weighted, medium threshold
- `mean_reversion` — 65% crypto, RSI+Bollinger weighted, short eval window

## Scoring Components

| Component | Weight (balanced) | Normalization |
|-----------|-------------------|---------------|
| Brier score | 25% | 1 - brier/0.25 (lower=better) |
| Return % | 25% | return_pct / 50 |
| Edge accuracy | 20% | Raw (0-1) |
| Win rate | 15% | Raw (0-1) |
| Bet volume | 15% | n_bets / 30 |

## Tips

- `eval_point_days_before` is critical: 1-3 days = less noise but harder to find edge. 7-14 days = more room for edge but noisier.
- RSI extreme values (>70 overbought, <30 oversold) are strong signals for "above X?" markets
- MACD histogram crossing zero is a strong directional signal for "up or down?" markets
- When crypto is trending strongly (above SMA50), trend_weight should be high
- Mean-reversion (high RSI weight + Bollinger) works best for short-term markets
- Use `--refresh-cache` flag if cache is stale

## Workflow

1. **Baseline:** Legacy mode, 5 experiments. Tune crypto_indicator_weight first.
2. **Cycle profiles:** balanced -> aggressive -> conservative -> trend -> mean_reversion.
3. **Combined eval** after each full cycle. Focus on weakest profile.
4. **Repeat** until interrupted.

## Commit Format

- Legacy: `exp(poly): <description> score=<X.XX>`
- Profile: `exp(poly/<profile>): <description> score=<X.XX>`
- Combined: `exp(poly/combined): score=<X.XX>`
