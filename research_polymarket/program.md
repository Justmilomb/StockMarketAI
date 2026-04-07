# AutoResearch — Polymarket Crypto Price Prediction Optimisation

You are an autonomous research agent optimising Polymarket crypto price prediction profiles.
Your goal: **maximise scores across all 5 profiles** by modifying `train.py` and `profile_configs.py`.

## How to Launch

```
cd E:\Coding\StockMarketAI\research_polymarket
claude "Read program.md and start experimenting" --model claude-opus-4-6 --allowedTools "Bash,Read,Edit,Write,Grep,Glob" --dangerously-skip-permissions
```

**IMPORTANT:** Do NOT use `-p` — that exits after one response. You need interactive mode.

## How to Stop

Press **Ctrl+C**. Nothing is lost — every improvement was already git-committed.

## How to Resume

Run the same launch command again. Read `git log --oneline` to see where you left off.

## Files

- `train.py` — Mode flags + legacy CONFIG. You modify the flags and CONFIG.
- `profile_configs.py` — Per-profile configs. You modify ACTIVE_PROFILE and individual profile dicts.
- `evaluate.py` — **IMMUTABLE. NEVER MODIFY.** Runs the evaluation and reports the score.
- `profiles/` — Best configs per profile (auto-saved by evaluate.py when a score improves).
- `program.md` — These instructions. Read once, then work.

## How It Works

This is NOT stock OHLCV backtesting. This predicts **Polymarket crypto price prediction markets** like:
- "Bitcoin Up or Down on April 7?" → P(up)
- "Bitcoin above 68,000?" → P(price > 68000)
- "What price will Ethereum hit?" → P(above target)

The edge detector combines two signal sources:
1. **Real crypto price data** (BTC/ETH from yfinance) — RSI, MACD, Bollinger bands, trend, momentum
2. **Polymarket market features** — price momentum, volume, orderbook, time decay

The `crypto_indicator_weight` parameter controls the blend (0.6 = 60% crypto indicators, 40% market features).

## Three Evaluation Modes

### Mode 1: Legacy (backward-compatible)
Set in `train.py`:
```python
PROFILE_MODE = False
ACTIVE_PROFILE = ""
EVALUATE_COMBINED = False
```
Run: `python evaluate.py`
Evaluates the flat `CONFIG` dict. Use this first to establish a baseline.

### Mode 2: Single Profile
Set in `train.py`:
```python
PROFILE_MODE = True
ACTIVE_PROFILE = "balanced_edge"  # or aggressive_edge, conservative_edge, trend_follower, mean_reversion
EVALUATE_COMBINED = False
```
Run: `python evaluate.py` or `python evaluate.py --profile balanced_edge`
Evaluates one profile from `profile_configs.py`.
Best configs auto-saved to `profiles/best_<name>.json`.

### Mode 3: Combined
Set in `train.py`:
```python
EVALUATE_COMBINED = True
```
Run: `python evaluate.py --combined`
Loads all best profiles from `profiles/` and tests them together.
Requires at least one `best_<name>.json` to exist.

## The Loop

### Phase A: Establish baseline (5-10 experiments)
1. Set `PROFILE_MODE = False` in `train.py`
2. Run legacy experiments to establish baseline score
3. Tune `crypto_indicator_weight` first — it's the most impactful parameter

### Phase B: Profile optimisation (cycle through all 5)
For each profile in order: `balanced_edge` -> `aggressive_edge` -> `conservative_edge` -> `trend_follower` -> `mean_reversion`:

1. Set `PROFILE_MODE = True` and `ACTIVE_PROFILE = "<name>"` in `train.py`
2. Modify that profile's config in `profile_configs.py`
3. Run `python evaluate.py`
4. If improved: `git add train.py profile_configs.py && git commit -m "exp(poly/<name>): <description> score=<X>"`
5. If not improved: `git checkout -- profile_configs.py`
6. Do at least 5 experiments per profile before moving to the next

### Phase C: Combined evaluation
1. Set `EVALUATE_COMBINED = True` in `train.py`
2. Run `python evaluate.py --combined`
3. If combined score is weak, focus on the weakest profile
4. Commit: `git add train.py && git commit -m "exp(poly/combined): score=<X>"`

### Phase D: Repeat B-C
Keep cycling through profiles, focusing extra experiments on the weakest scorer.

## What You Can Tune Per Profile

### Edge detection
| Parameter | Range | Effect |
|-----------|-------|--------|
| min_edge_pct | 1.0 – 15.0 | Minimum edge to trigger bet (% points). Lower = more bets. |
| confidence_threshold | 0.1 – 0.8 | Minimum confidence to bet. Lower = more bets. |
| eval_point_days_before | 1 – 30 | Evaluate edge N days before resolution. |

### Bet sizing
| Parameter | Range | Effect |
|-----------|-------|--------|
| kelly_fraction_cap | 0.02 – 0.20 | Cap on Kelly bet sizing. Higher = riskier. |
| max_bet_fraction | 0.01 – 0.10 | Max fraction of bankroll per bet. |

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
| crypto_indicator_weight | 0.0 – 1.0 | 0=pure Polymarket heuristic, 1=pure crypto indicators |

## Scoring Components (8 metrics — matches stock research rigour)

| Component | Weight (balanced) | Normalization |
|-----------|-------------------|---------------|
| Brier score | 15% | 1 - brier/0.25 (lower = better) |
| Return % | 15% | return_pct / 25 (25% = full credit) |
| Edge accuracy | 15% | Raw (0-1) |
| Win rate | 15% | Raw (0-1) |
| Bet volume | 10% | n_bets / 50 (50 bets = full credit) |
| Drawdown | 15% | 1 - drawdown/50 (lower dd = better) |
| Profit factor | 10% | profit_factor / 3.0 (capped at 3x) |
| Sharpe | 5% | sharpe / 2.0 (capped at 2.0) |

Weights vary per profile — aggressive rewards return/volume, conservative rewards brier/drawdown.

## Profile Tuning Strategies

### balanced_edge (baseline)
- Even indicator weights, moderate thresholds
- Good starting point — tune crypto_indicator_weight first (try 0.4-0.8)
- Then adjust eval_point_days_before (try 3, 5, 7, 10, 14)

### aggressive_edge
- Lower min_edge_pct (2-4%), lower confidence (0.15-0.25)
- Higher momentum_weight — chase recent price moves
- More bets, higher kelly — accept more risk for volume

### conservative_edge
- Higher min_edge_pct (8-12%), higher confidence (0.4-0.6)
- Higher RSI weight — only bet on oversold/overbought extremes
- Fewer bets, smaller sizing — protect capital

### trend_follower
- High MACD + trend weights (0.30-0.40 each)
- crypto_indicator_weight 0.7-0.8 — trust price data more
- Wider eval window (7-14 days) — let trends develop

### mean_reversion
- High RSI + Bollinger weights (0.30-0.40 each)
- Short eval window (1-5 days) — catch quick reversals
- Moderate crypto_indicator_weight (0.5-0.7)

## Key Insights

- `eval_point_days_before` is critical: 1-3 days = less noise but harder edge. 7-14 days = more opportunity but noisier.
- RSI extremes (>70 overbought, <30 oversold) are strong for "above X?" markets
- MACD zero crossings are strong for "up or down?" markets
- When crypto is strongly trending (above SMA50), trend_weight should be high
- Mean-reversion works best for short-term markets (1-3 days)

## Commit Format

- Legacy: `exp(poly): <description> score=<X.XX>`
- Profile: `exp(poly/<profile>): <description> score=<X.XX>`
- Combined: `exp(poly/combined): score=<X.XX>`

## Rules

1. **ONLY modify `train.py` and `profile_configs.py`.** Never touch `evaluate.py`, `data.py`, or `evaluator.py`.
2. **Always run `python evaluate.py`** to measure. Never guess. Set timeout to 10 min: `timeout: 600000`.
3. **Commit improvements to git.** Revert failures. This is your experiment log.
4. **Write clear commit messages.** Include the profile name and score.
5. **Never stop.** Keep running experiments until interrupted.
6. **One or two changes per experiment.** Isolate what works.
7. **Cycle through all profiles.** Don't spend all time on one.
