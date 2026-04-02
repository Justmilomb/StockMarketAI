# Consensus Engine

## Purpose
The "investment committee" — aggregates all signal sources (ML models + Claude personas + MiroFish simulation signals + statistical/deep forecasters via the meta-ensemble) into a single ConsensusResult per ticker. Provides gating logic and size modifiers for the strategy layer.

## Aggregation Logic
- ML model signals: weighted by confidence (as-is)
- Claude persona signals: weighted by confidence * 0.8 (slight ML preference)
- MiroFish signals: contributed as ModelSignal entries (3 per ticker: sentiment, flow, momentum)
- Statistical/deep forecasters: adapted to ModelSignal via MetaEnsemble.to_model_signals()
- Disagreement: population variance * 4 (normalised to 0-1)
- Signal strength: abs(probability - 0.5), range 0-0.5

## Public API
- `ConsensusEngine.compute_consensus(ticker, model_signals, persona_signals, regime?, horizon_probs?) -> ConsensusResult`
- `ConsensusEngine.compute_all(all_signals, all_personas, regime?, all_horizon_probs?) -> Dict[str, ConsensusResult]`
- `ConsensusEngine.should_trade(result) -> bool` — Gate: consensus_pct >= 60%
- `ConsensusEngine.position_size_modifier(result) -> float` — 0.0 at 50%, 0.5 at 75%, 1.0 at 100%

## ConsensusResult Fields
probability, consensus_pct, confidence, signal_strength, disagreement, bull_count, bear_count, regime, horizon_breakdown

## Configuration
- consensus.min_consensus_pct (60), consensus.disagreement_penalty (0.5)

## Dependencies
- types_shared.py (ModelSignal, ConsensusResult, PersonaSignal, RegimeState)
