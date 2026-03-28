# AutoConfig — Autonomous Config Optimisation for StockMarketAI

You are an autonomous research agent optimising the trading config for a stock market AI terminal. Your job is to find the config that maximises backtest performance by running experiments, evaluating results, and iterating. **NEVER STOP.** Keep running experiments until the human interrupts you.

---

## Setup (do this once at the start of each session)

1. Read `autoconfig/results.tsv` — this is your experiment log from prior sessions. If it doesn't exist, create it with this header:

```
id	score	accuracy	win_rate	sharpe	profit_factor	max_dd	duration	overrides	notes
```

2. Read `autoconfig/best_config.json` if it exists — this is the current best config. If it doesn't exist, the current `config.json` is your baseline.

3. Run the **baseline experiment** (no overrides) against a broad stock universe:
```bash
cd /e/Coding/StockMarketAI && python autoconfig/experiment.py --fast --no-mirofish --universe medium --universe-seed 42 2>/dev/null
```

This tests 30 diverse stocks (not just the 7 on the watchlist) to avoid overfitting.

4. Record the baseline result in `results.tsv` with id=0 and notes="baseline".

---

## Experiment Loop (repeat forever)

### Step 1: Choose what to change

Pick ONE or TWO parameters to change per experiment. Don't change everything at once — you need to isolate what works.

**Parameter space you can explore:**

| Parameter | Path in overrides JSON | Range | Current |
|---|---|---|---|
| Buy threshold | `strategy.threshold_buy` | [0.50, 0.72] | 0.58 |
| Sell threshold | `strategy.threshold_sell` | [0.30, 0.50] | 0.42 |
| Max positions | `strategy.max_positions` | [3, 15] | 8 |
| Position size | `strategy.position_size_fraction` | [0.05, 0.25] | 0.12 |
| ATR stop multiplier | `risk.atr_stop_multiplier` | [1.0, 3.5] | 1.8 |
| ATR profit multiplier | `risk.atr_profit_multiplier` | [1.5, 5.0] | 2.5 |
| Kelly cap | `risk.kelly_fraction_cap` | [0.15, 0.50] | 0.35 |
| Drawdown threshold | `risk.drawdown_threshold` | [0.08, 0.30] | 0.15 |
| Drawdown size reduction | `risk.drawdown_size_reduction` | [0.3, 0.8] | 0.5 |
| Consensus min % | `consensus.min_consensus_pct` | [45, 85] | 60 |
| Disagreement penalty | `consensus.disagreement_penalty` | [0.2, 0.9] | 0.5 |
| MiroFish ticks | `mirofish.n_ticks` | [40, 150] | 80 |
| MiroFish consensus weight | `mirofish.consensus_weight` | [0.05, 0.45] | 0.25 |
| MiroFish info decay | `mirofish.information_decay` | [0.80, 0.98] | 0.92 |
| MiroFish base volatility | `mirofish.base_volatility` | [0.005, 0.05] | 0.02 |
| MiroFish influence radius | `mirofish.influence_radius` | [5, 30] | 15 |
| Sklearn weight | `ai.sklearn_weight` | [0.3, 0.8] | 0.5 |
| AI weight | `ai.ai_weight` | [0.1, 0.5] | 0.3 |
| News weight | `ai.news_weight` | [0.0, 0.3] | 0.2 |
| Ensemble lookback | `ensemble.performance_lookback_days` | [30, 180] | 90 |
| Timeframe 1d weight | `timeframes.weights.1` | [0.4, 0.9] | 0.7 |
| Timeframe 5d weight | `timeframes.weights.5` | [0.05, 0.4] | 0.2 |
| Timeframe 20d weight | `timeframes.weights.20` | [0.0, 0.3] | 0.1 |
| ML family weight | `forecasters.meta_ensemble.family_weights.ml` | [0.3, 0.8] | 0.5 |
| Statistical family weight | `forecasters.meta_ensemble.family_weights.statistical` | [0.1, 0.4] | 0.25 |
| Deep family weight | `forecasters.meta_ensemble.family_weights.deep_learning` | [0.0, 0.4] | 0.25 |
| Regime lookback | `regime.lookback_days` | [20, 120] | 60 |
| Regime weight adjustment | `regime.regime_weight_adjustment` | [0.1, 0.6] | 0.3 |

**MiroFish agent distribution** (must sum to 1000):
```json
{"mirofish": {"agent_distribution": {"momentum": N, "mean_reversion": N, ...}}}
```

### Step 2: Run the experiment

```bash
cd /e/Coding/StockMarketAI && python autoconfig/experiment.py --fast --no-mirofish --universe medium --overrides '{"strategy": {"threshold_buy": 0.60}}' 2>/dev/null
```

**Universe options** (ALWAYS use a universe — never just the watchlist):
- `--universe small` — 15 stocks, fastest iteration
- `--universe medium` — 30 stocks, good balance (default for most experiments)
- `--universe large` — 60 stocks, thorough validation
- `--universe full` — 100+ stocks, final validation only
- `--sector tech` — tech stocks only (test sector-specific patterns)
- `--sector volatile` — high-vol stocks (stress test)
- `--sector finance` / `healthcare` / `energy` etc.
- `--universe-seed N` — use same seed for comparable experiments

**Speed tiers** (use the fastest tier that tests what you need):
- `--fast --no-mirofish --universe small` — ~1-3 min. Quick screening.
- `--fast --no-mirofish --universe medium` — ~3-8 min. Standard experiments.
- `--fast --universe medium` — ~10-20 min. With MiroFish. Use when testing MiroFish params.
- `--universe large` — ~20-60 min. Full trade simulation. Validate top candidates only.

**IMPORTANT: Use `--universe-seed 42` for the first pass of each parameter** so results are comparable. Then re-test winners with different seeds to check they generalise.

### Step 3: Evaluate the result

Parse the JSON output. The key metric is `score` — a composite of accuracy, win rate, Sharpe, profit factor, and drawdown. Higher is better.

Compare against the current best score in `results.tsv`.

### Step 4: Record the result

Append a row to `autoconfig/results.tsv`:
```
{id}\t{score}\t{accuracy}\t{win_rate}\t{sharpe}\t{profit_factor}\t{max_dd}\t{duration}\t{overrides_json}\t{notes}
```

### Step 5: Keep or discard

- **If score improved**: Update `autoconfig/best_config.json` with the full merged config. Note the improvement in your experiment notes.
- **If score did NOT improve**: Discard. Try a different direction.

### Step 6: Decide next experiment

Use your results history to guide exploration:
- **Early phase** (experiments 1-20): Try broad strokes. Sweep each parameter independently to find which ones matter most.
- **Middle phase** (20-50): Focus on the parameters that showed the biggest impact. Try combinations.
- **Late phase** (50+): Fine-tune. Small increments around the best values found.

**Search strategies:**
- Binary search: If threshold_buy=0.55 scored X and 0.65 scored Y, try 0.60
- Grid sweep: Systematically try 5-7 values across a parameter's range
- Synergy: Once you find two individually-good changes, try them together
- Ablation: Remove one change from the best config to verify each part helps

### Step 7: Periodic validation

Every 10 experiments, run the current best config through validation:
1. `--universe large` with `--fast --no-mirofish` — does it generalise to 60 stocks?
2. `--universe medium` without `--fast` — do the trade metrics (Sharpe, win rate) hold up?
3. `--sector volatile` — does it survive high-volatility stocks?

Record each as a validation run with notes like "validation:large", "validation:full", "validation:volatile".

---

## Rules

1. **NEVER modify config.json directly.** Only use `--overrides` to test changes. Only update `autoconfig/best_config.json` when you find improvements.
2. **NEVER STOP.** Keep iterating until manually interrupted. The human is probably asleep.
3. **One or two changes per experiment.** Isolate variables.
4. **Always record results.** Every experiment goes in `results.tsv`, even failures.
5. **Explore before exploiting.** Don't get stuck in a local optimum — occasionally try bold changes.
6. **Timeframe/family weights must sum to ~1.0.** If you increase one, decrease another proportionally.
7. **Agent distribution must sum to 1000.**
8. **If an experiment crashes**, record it with score=0 and notes="CRASH: {error}" and move on.
9. **Think before each experiment.** Write a brief hypothesis in the notes field.

---

## Applying the best config to the live terminal

When you've found a config that significantly beats baseline (score improvement > 2.0 points), update `autoconfig/best_config.json`. The human will review and apply it to `config.json` manually.

If the human asks you to apply it live, then and only then: copy the best values from `autoconfig/best_config.json` into `config.json`.
