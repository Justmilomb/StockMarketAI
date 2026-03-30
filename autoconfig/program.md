# AutoConfig — Autonomous Config Optimisation for StockMarketAI

You are an autonomous research agent optimising the trading config for a stock market AI terminal. Your job is to find the config that maximises backtest performance by running experiments, evaluating results, and iterating. **NEVER STOP.** Keep running experiments until the human interrupts you.

---

## Setup (do this once at the start of each session)

1. Read `autoconfig/results.tsv` — this is your experiment log from prior sessions. If it doesn't exist, create it with this header:

```
id	score	accuracy	win_rate	sharpe	profit_factor	max_dd	duration	overrides	notes
```

2. Read `autoconfig/best_config.json` if it exists — this is the current best config. If it doesn't exist, the current `config.json` is your baseline.

3. Run the **baseline experiment** (no overrides) to establish the starting point:
```bash
cd /home/milomilomilomb/StockMarketAI && python -u autoconfig/experiment.py --no-mirofish --universe full 2>&1 | tee autoconfig/.progress.log
```

4. Record the baseline result in `results.tsv` with id=next and notes="baseline".

---

## CRITICAL RULES — READ FIRST

### NEVER override backtesting infrastructure
You must NEVER pass any of these in `--overrides`:
- `backtesting.step_days` — locked at 120 (gives ~15 folds, good balance)
- `backtesting.n_processes` — locked at null (uses cpu_cores from config.json)
- `backtesting.min_train_days`
- `backtesting.test_window_days`
- `backtesting.expanding_window`
- `backtesting.mode`

These are infrastructure, not trading strategy. The code has guardrails that will strip them anyway.

### NEVER use `--fast`
Fast mode skips trade simulation entirely. All trade metrics (Sharpe, win rate, profit factor, drawdown) will be **zero**. This makes 60% of the score components useless. Always run in full mode.

### ALWAYS use `--universe full`
- Every experiment runs against the full ~250 ticker universe.
- No subsampling — this eliminates seed noise and makes every experiment directly comparable.
- The machine uses 8 cores (configured via cpu_cores in config.json).

### ALWAYS use `--no-mirofish` unless specifically testing MiroFish params
MiroFish adds significant runtime. Only enable it when testing MiroFish-specific parameters.

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

**Strategy profile parameters** (per-profile overrides for the 5 trading profiles):

| Profile | Default buy | Default sell | Size | Stop | TP | Best for |
|---------|-------------|-------------|------|------|----|----------|
| `conservative` | 0.68 | 0.35 | 8% | 1.2x ATR | 1.8x ATR | High vol, tiny capital |
| `day_trader` | 0.60 | 0.42 | 15% | 1.5x ATR | 2.5x ATR | Mean-reverting markets |
| `swing` | 0.55 | 0.40 | 18% | 2.0x ATR | 3.0x ATR | Default / unknown regime |
| `crisis_alpha` | 0.72 | 0.30 | 10% | 1.0x ATR | 2.0x ATR | Contrarian in panics |
| `trend_follower` | 0.52 | 0.45 | 20% | 2.5x ATR | 4.0x ATR | Strong uptrends |

### Step 2: Run the experiment

**Standard command (use this for every experiment):**
```bash
cd /home/milomilomilomb/StockMarketAI && python -u autoconfig/experiment.py --no-mirofish --universe full --overrides '{"strategy": {"threshold_buy": 0.60}}' 2>&1 | tee autoconfig/.progress.log
```

**Flags you may add:**
- `--universe large` — 80 stocks, for validation runs only
- `--sector tech` / `volatile` / `finance` etc. — sector-specific tests
- `--strategy-profile conservative` — test a specific profile
- `--use-strategy-selector` — enable regime-aware strategy selection
- `--crisis 2020_covid_crash` — test against a specific crisis period
- `--stress-test` — run ALL crisis periods (slow, validation only)

**Flags you must NEVER use:**
- `--fast` — produces zero trade metrics, completely useless
- `--universe small` or `--universe medium` — always use `--universe full`

**Expected runtimes (8-core config, ~250 tickers):**
- `--no-mirofish --universe full` — ~10-20 min per experiment (standard)
- `--universe full` (with MiroFish) — ~30-60 min (MiroFish tuning)
- `--stress-test --universe full` — ~60-90 min (crisis validation)

### Step 3: Evaluate the result

Parse the JSON output after the `---JSON---` separator. The key metric is `score` — a composite of accuracy, win rate, Sharpe, profit factor, and drawdown. Higher is better.

**Sanity check before recording:** If `total_trades == 0` or `win_rate == 0.0`, something went wrong. Do NOT record the result — investigate why no trades were generated. Common cause: thresholds too extreme for the data.

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
- **Multi-strategy phase** (when single-strategy is optimised): Test each profile independently, then test the adaptive selector.

**Search strategies:**
- Binary search: If threshold_buy=0.55 scored X and 0.65 scored Y, try 0.60
- Grid sweep: Systematically try 5-7 values across a parameter's range
- Synergy: Once you find two individually-good changes, try them together
- Ablation: Remove one change from the best config to verify each part helps
- **Per-profile sweep**: Test each of the 5 profiles independently using `--strategy-profile <name>` to find the best params for each trading style
- **Regime-specific**: Use `--crisis <name>` to test how a config performs during specific market dislocations

### Step 7: Periodic validation

Every 10 experiments, run the current best config through validation:
1. `--sector volatile` — does it survive high-volatility stocks?
2. `--stress-test --universe full` — does it survive crises?
3. `--use-strategy-selector --universe full` — does the adaptive system beat the static config?

Record each as a validation run with notes like "validation:large", "validation:stress", "validation:adaptive".

### Step 8: Multi-strategy optimisation

Once single-strategy experiments are well-explored, optimise each profile independently:

1. **Test each profile as a standalone strategy:**
```bash
python -u autoconfig/experiment.py --strategy-profile conservative --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --strategy-profile day_trader --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --strategy-profile swing --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --strategy-profile crisis_alpha --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --strategy-profile trend_follower --universe full 2>&1 | tee autoconfig/.progress.log
```

2. **Optimise each profile's parameters** — use overrides ON TOP of the profile:
```bash
python -u autoconfig/experiment.py --strategy-profile conservative --overrides '{"strategy": {"threshold_buy": 0.70}}' --universe full 2>&1 | tee autoconfig/.progress.log
```

3. **Test crisis resilience per profile:**
```bash
python -u autoconfig/experiment.py --strategy-profile crisis_alpha --crisis 2020_covid_crash --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --strategy-profile conservative --stress-test --universe full 2>&1 | tee autoconfig/.progress.log
```

4. **Test the adaptive selector vs best static config:**
```bash
python -u autoconfig/experiment.py --use-strategy-selector --universe full 2>&1 | tee autoconfig/.progress.log
python -u autoconfig/experiment.py --use-strategy-selector --stress-test --universe full 2>&1 | tee autoconfig/.progress.log
```

Record profile-specific results with notes like "profile:conservative", "profile:crisis_alpha+covid".

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
10. **NEVER use `--fast`.** It produces zero trade metrics. Always use full mode.
11. **NEVER override backtesting params.** step_days, n_processes, mode are infrastructure — not tuneable.
12. **NEVER use `--universe small`.** 30 tickers overfits. Minimum is `--universe full` (100 tickers).
13. **Sanity-check every result.** If total_trades=0 or win_rate=0, the experiment is broken — don't record it, investigate.
14. **All commands must use `python -u ... 2>&1 | tee autoconfig/.progress.log`** for real-time output visibility.

---

## Applying the best config to the live terminal

When you've found a config that significantly beats baseline (score improvement > 2.0 points), update `autoconfig/best_config.json`. The human will review and apply it to `config.json` manually.

If the human asks you to apply it live, then and only then: copy the best values from `autoconfig/best_config.json` into `config.json`.
