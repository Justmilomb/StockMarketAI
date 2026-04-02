# CPU Config

Central CPU core allocation module. All code that spawns processes, threads, or sets scikit-learn `n_jobs` must call this module rather than using `os.cpu_count()` or hardcoding `n_jobs=-1`.

## Purpose

Prevents over-subscription when multiple parallelism layers nest (e.g. parallel backtest folds each running sklearn models with multiple threads). Provides a single controllable knob for the entire system, overridable via env vars for autoconfig experiments.

## Functions

```python
def get_cpu_cores() -> int
# Resolution: AUTOCONFIG_CPU_CORES env var → config.json "cpu_cores" → os.cpu_count() → fallback 4
# Capped at os.cpu_count() so stale configs on smaller machines don't over-request

def get_max_parallel_folds() -> int
# Resolution: AUTOCONFIG_MAX_FOLDS env var → config.json "max_parallel_folds" → cpu_cores // 2
# Capped at cpu_cores // 2 — leaves headroom for sklearn threads inside each fold

def get_n_jobs_per_fold() -> int
# Returns cpu_cores // max_parallel_folds
# Used by sklearn models inside backtest fold workers to avoid thread explosion

def get_n_jobs() -> int
# Returns cpu_cores — used outside backtesting (live pipeline, single-model training)
```

## Configuration

```json
{
  "cpu_cores": 12,
  "max_parallel_folds": 6
}
```

If `cpu_cores` is omitted, `os.cpu_count()` is used. If `max_parallel_folds` is omitted, defaults to `cpu_cores // 2`.

## Environment Variable Overrides

| Var | Overrides | Used By |
|-----|-----------|---------|
| `AUTOCONFIG_CPU_CORES` | `get_cpu_cores()` | autoconfig experiments |
| `AUTOCONFIG_MAX_FOLDS` | `get_max_parallel_folds()` | autoconfig experiments |

## Threading Budget Example

On a 12-core machine with `max_parallel_folds=6`:
- 6 fold processes run in parallel
- Each fold's sklearn models use `n_jobs=2` (12 // 6)
- Total threads ≈ 12 — no over-subscription

## Dependencies

- `config.json` (read at import time, cached via `@lru_cache`)
