# Autoconfig

Autonomous parameter optimisation system. Repeatedly launches Claude Code CLI sessions to run backtest experiments and iteratively improve `config.json` parameters without human intervention.

## Purpose

Implements an outer loop around the backtest engine: Claude acts as an agent that reads previous results, proposes parameter changes, runs experiments, and records outcomes. Inspired by Karpathy's autoresearch pattern. The human can interrupt at any time — all progress is persisted to disk.

## Architecture

```
autoconfig/run.py (outer loop)
    │
    └── Launches Claude Code CLI session (claude-opus-4-6)
            │
            └── Reads autoconfig/program.md for instructions
                    │
                    ├── python autoconfig/experiment.py --overrides '{"strategy": {...}}'
                    │       └── Runs full backtest with in-memory config override
                    │           Returns JSON metrics to stdout
                    │
                    ├── Records results to autoconfig/results.tsv
                    └── Updates autoconfig/best_config.json if improved
```

## Key Files

| File | Purpose |
|------|---------|
| `autoconfig/run.py` | Outer launcher loop — spawns Claude Code sessions, handles interrupts |
| `autoconfig/experiment.py` | Single experiment runner — accepts `--overrides` JSON, runs BacktestRunner, prints metrics JSON |
| `autoconfig/program.md` | Instructions for the Claude agent (rules, workflow, what to optimise) |
| `autoconfig/results.tsv` | Append-only experiment log (all runs with metrics) |
| `autoconfig/best_config.json` | Best config found so far (updated when Sharpe improves) |
| `autoconfig/universe.py` | Named ticker universes: small (15), medium (30), large (60), full (100+) |
| `autoconfig/strategy_profiles.py` | Named strategy presets (momentum, conservative, etc.) |

## experiment.py CLI

```bash
python autoconfig/experiment.py                          # Watchlist tickers
python autoconfig/experiment.py --universe medium        # 30 diverse stocks (default for experiments)
python autoconfig/experiment.py --overrides '{"strategy": {"threshold_buy": 0.60}}'
python autoconfig/experiment.py --fast --no-mirofish     # Fastest mode (signal accuracy only)
python autoconfig/experiment.py --crisis 2020_covid_crash
python autoconfig/experiment.py --stress-test            # All crisis periods
python autoconfig/experiment.py --strategy-profile momentum
python autoconfig/experiment.py --use-strategy-selector  # Regime-aware strategy selection
```

Outputs a JSON object to stdout with all backtest metrics. `config.json` is **never** modified — overrides are in-memory only.

## run.py CLI

```bash
python autoconfig/run.py                    # 10 experiments/session, infinite sessions
python autoconfig/run.py --batch-size 20    # 20 experiments/session
python autoconfig/run.py --max-sessions 50  # Stop after 50 sessions
python autoconfig/run.py --dry-run          # Print the prompt without running
```

## Key Rules (from program.md)

- Never use `--fast` (produces zero trade metrics)
- Always use `--universe medium` for fast iteration; `--universe full` only for final validation
- Never modify `config.json` — only `--overrides`
- Step size of 120 days in experiments (vs 20 days live) for speed

## Configuration

Session control in `run.py`: `batch_size`, `max_sessions`. Experiment config via `--overrides` JSON keys matching `config.json` structure.

## Dependencies

- `backtesting/runner.py`, `backtesting/types.py`
- `claude` CLI (Claude Code, not just Claude)
- `autoconfig/universe.py`, `autoconfig/strategy_profiles.py`
