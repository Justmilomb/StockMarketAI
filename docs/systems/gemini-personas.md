# Gemini Personas

## Purpose
5 parallel Gemini analyst personas that each independently analyse a ticker from a different perspective. Adds diverse AI opinions to the consensus engine alongside ML model signals.

## Personas
| Persona | Focus | Style |
|---------|-------|-------|
| technical | Charts, S/R, MA crossovers, RSI | Pattern-driven, trusts price |
| fundamental | P/E, growth, moat, valuation | Value investor, intrinsic worth |
| momentum | Trend, volume, breakouts | Follow trend until it bends |
| contrarian | Extremes, mean-reversion | Questions consensus, sceptical |
| risk | Downside, tail risks, worst-case | Voice of caution, protects capital |

## Public API
- `GeminiPersonaAnalyzer.analyze_ticker(ticker, closes, features, news_sentiment, news_summary) -> List[GeminiPersonaSignal]` — 5 parallel persona calls
- `GeminiPersonaAnalyzer.analyze_batch(ticker_data) -> Dict[str, List[GeminiPersonaSignal]]` — Multi-ticker batch
- `GeminiPersonaAnalyzer.aggregate_personas(signals) -> (weighted_prob, avg_confidence)` — Confidence-weighted average

## Error Handling
- Failed persona → neutral signal (prob=0.5, conf=0.0, rec=HOLD)
- JSON parse failure → neutral fallback
- Per-persona failures don't block others

## Configuration
- gemini_personas.enabled (true), gemini_personas.personas (list of 5)

## Dependencies
- gemini_client.py (GeminiClient), types_shared.py (GeminiPersonaSignal), concurrent.futures
