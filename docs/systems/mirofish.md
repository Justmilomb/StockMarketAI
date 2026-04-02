# MiroFish — Multi-Agent Market Simulation

## Purpose

MiroFish simulates ~1000 heterogeneous AI agents that represent different market participants. Unlike traditional models that predict price directly, MiroFish generates **emergent behaviour** — price direction, momentum, and volatility arise from agent interactions.

It models crowd psychology, momentum cascades, panic selling, contrarian reversals, and herd effects that statistical models cannot capture.

## Architecture

```
MarketContext (real data)
    │
    ▼
┌─────────────────────────────────────────────┐
│            MiroFishOrchestrator              │
│  ProcessPoolExecutor (all CPU cores)         │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │  Per-ticker Monte Carlo (×16 runs)      │ │
│  │                                          │ │
│  │  ┌──────────────────────────────────┐   │ │
│  │  │  Simulation Engine (100 ticks)   │   │ │
│  │  │                                   │   │ │
│  │  │  1. Agents observe market state  │   │ │
│  │  │  2. Beliefs update (per-type)    │   │ │
│  │  │  3. Social interaction           │   │ │
│  │  │     (herding + contrarian)       │   │ │
│  │  │  4. Position decisions           │   │ │
│  │  │  5. Aggregate → price impact     │   │ │
│  │  │  6. Feedback loop                │   │ │
│  │  └──────────────────────────────────┘   │ │
│  └─────────────────────────────────────────┘ │
│                                              │
│  Aggregate across runs → MiroFishSignal      │
│  Convert → ModelSignal for consensus         │
└──────────────────────────────────────────────┘
```

## Agent Types (9 classes, 1000 total)

Default counts from `agents.py` (overridable via config.json `agent_distribution`):

| Type | Default Count | Behaviour | Key Parameters |
|------|-------|-----------|----------------|
| Momentum | 150 | Follow trends | High trend sensitivity (0.8), moderate herd (0.35) |
| Mean Reversion | 120 | Bet on reversals | Negative trend sens (-0.6), high reversion (0.4) |
| Sentiment | 100 | News-driven | Very high news sensitivity (0.85), high herd (0.5) |
| Fundamental | 150 | Value-based | High feature sensitivity (0.8), very low herd (0.05) |
| Noise | 30 | Irrational/random | High noise scale (0.15), short memory |
| Contrarian | 80 | Against the crowd | Negative herd susceptibility (-0.3), strong contrarian factor (0.6) |
| Institutional | 120 | Large/slow/deliberate | Very low noise (0.01), very long memory (0.98 decay) |
| Algorithmic | 150 | Pattern-based | High feature + trend sensitivity, low noise (0.02) |
| LLM-seeded | 100 | ML-prior initial beliefs | Balanced news + feature sensitivity, ML ensemble probability weighting |

Each agent has per-instance parameter jitter (±20%) to avoid homogeneous herds.

## Simulation Mechanics

### Per Tick
1. **Observation**: Each agent computes an observation signal from price returns, news sentiment, and ML features, weighted by their type-specific sensitivities.
2. **Belief Update**: `belief = decay × old_belief + (1 - decay) × observation`, clamped to [-1, 1].
3. **Social Interaction**: Convolution-based neighbourhood averaging. Herd-susceptible agents move toward local crowd; contrarians push away.
4. **Position Decision**: Agents act when |belief| exceeds their conviction threshold. Position change ∝ belief strength × risk tolerance.
5. **Aggregation**: Net order flow = mean(positions). Price impact = flow × impact_factor / liquidity + noise.
6. **Feedback**: Synthetic price change feeds into next tick's observation.

### Monte Carlo
Each ticker gets 16 independent simulation runs with different random seeds. Results are aggregated across runs for robust statistics.

## Outputs

| Signal | Range | Derivation |
|--------|-------|------------|
| Net Sentiment | [-1, 1] | Mean belief across all agents and runs |
| Sentiment Momentum | float | Rate of change in mean belief (last 20% of ticks) |
| Agreement Index | [0, 1] | 1 - normalised std of beliefs |
| Volatility Prediction | [0, 1] | Blend of belief disagreement + synthetic price vol |
| Order Flow | [-1, 1] | Mean final net position across runs |
| Narrative Direction | str | "bullish" / "bearish" / "uncertain" |
| P(up) | [0, 1] | Sigmoid mapping of net sentiment |
| Confidence | [0, 1] | Blend of agreement, cross-run consistency, conviction |

## Integration

MiroFish runs as **pipeline step 4d** (after meta-blend, before Claude personas):

```
meta_blend → mirofish → claude_personas → consensus → risk
```

Each ticker produces 3 `ModelSignal` entries for the consensus engine:
- `mirofish_sentiment` — primary belief probability
- `mirofish_flow` — order flow pressure signal
- `mirofish_momentum` — sentiment rate-of-change

## Performance

- **Single simulation** (1000 agents × 100 ticks): ~17ms
- **Full pipeline** (7 tickers × 16 Monte Carlo runs): ~1.3s using 12 CPU cores
- Uses `ProcessPoolExecutor` for true parallelism (bypasses GIL)
- Falls back to serial execution on Windows if multiprocessing fails

## Configuration

All parameters configurable via `config.json` → `"mirofish"` section:

```json
{
  "mirofish": {
    "enabled": true,
    "n_agents": 1000,
    "n_ticks": 100,
    "n_simulations": 16,
    "n_processes": null,
    "price_impact_factor": 0.001,
    "base_volatility": 0.02,
    "liquidity": 1.0,
    "influence_radius": 15,
    "information_decay": 0.95,
    "consensus_weight": 0.15,
    "agent_distribution": {
      "momentum": 200,
      "mean_reversion": 150,
      "sentiment": 150,
      "fundamental": 100,
      "noise": 100,
      "contrarian": 100,
      "institutional": 50,
      "algorithmic": 100,
      "llm_seeded": 50
    }
  }
}
```

## Files

| File | Responsibility |
|------|---------------|
| `mirofish/__init__.py` | Package exports |
| `mirofish/types.py` | Dataclasses: AgentTypeConfig, SimulationConfig, MarketContext, SimulationResult, MiroFishSignal |
| `mirofish/agents.py` | Agent type definitions, population builder, vectorized observation/interaction/decision functions |
| `mirofish/simulation.py` | Core simulation engine (100-tick loop with feedback) |
| `mirofish/orchestrator.py` | Multi-process Monte Carlo orchestrator |
| `mirofish/signals.py` | Signal extraction + ModelSignal conversion for consensus |
