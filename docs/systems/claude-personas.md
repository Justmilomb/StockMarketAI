# Claude Personas

Five specialist Claude analyst personas that each evaluate a ticker from a distinct investment perspective, producing diverse `PersonaSignal` entries for the consensus engine.

## Purpose

Prevents group-think in the investment committee by forcing explicit disagreement. Each persona has different analytical focus and style, so they can legitimately disagree on the same price data. Their signals are weighted at 80% of ML model signals in the consensus aggregation.

## The Five Personas

| Key | Name | Focus |
|-----|------|-------|
| `technical` | Technical Analyst | Chart patterns, MA crossovers, RSI divergence, MACD, Bollinger Bands |
| `fundamental` | Fundamental Analyst | P/E, revenue growth, competitive moat, valuation multiples, balance sheet |
| `momentum` | Momentum Trader | Trend persistence, relative strength, breakout confirmation, volume surges |
| `contrarian` | Contrarian Strategist | Overreaction detection, sentiment extremes, mean-reversion setups, crowd errors |
| `risk` | Risk Analyst | Downside scenarios, tail risks, volatility regimes, risk/reward asymmetry |

## Batched vs Sequential Execution

**Primary path (batched):** All 5 personas analysed in a single Sonnet call. The prompt presents all personas simultaneously and requests a JSON `{"analyses": [...]}` response. One call per ticker.

**Fallback path (sequential):** If batching fails, each persona runs as a separate Opus call. Used for degraded operation — preserves progress tick granularity.

## Public API

```python
class ClaudePersonaAnalyzer:
    def analyze_ticker(
        ticker, closes, features, news_sentiment, news_summary
    ) -> List[PersonaSignal]

    def analyze_batch(
        ticker_data: Dict[str, Dict],
        on_progress: Callable | None,
    ) -> Dict[str, List[PersonaSignal]]

    def aggregate_personas(signals: List[PersonaSignal]) -> (float, float)
    # Returns (weighted_avg_probability, weighted_avg_confidence)
```

## PersonaSignal Fields

`persona, ticker, probability, recommendation (BUY|SELL|HOLD), confidence, reasoning`

## Robustness

- Batched response detected as rate-limited or suspiciously uniform (all ~0.5 prob) triggers sequential fallback
- Individual malformed JSON entries fall back to neutral signals rather than aborting the batch
- Personas missing from the batched response receive neutral fallback signals (probability=0.5, confidence=0.0)

## Integration

Personas run as pipeline step 4e (after MiroFish, before consensus):

```
meta_blend → mirofish → claude_personas → consensus → risk
```

## Dependencies

- `claude_client.ClaudeClient`
- `types_shared.PersonaSignal`
