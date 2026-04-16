# Claude Client

Wraps the `claude` CLI as a subprocess to provide AI capabilities without requiring a separate API key — uses the user's existing Claude subscription.

## Purpose

All LLM calls in the pipeline route through `AIClient`. It handles model tier selection, subprocess invocation, JSON extraction from markdown-wrapped responses, and error detection for rate limits or CLI unavailability.

## Model Tiers

| Task Type | Model | Used For |
|-----------|-------|---------|
| `complex` | claude-opus-4-6 | Personas (sequential fallback), portfolio analysis, interactive chat |
| `medium` | claude-sonnet-4-20250514 | Signal generation, batched persona analysis, recommendations, news |
| `simple` | claude-haiku-4-5-20251001 | Memory extraction, lightweight data assembly |

## Key Methods

```python
class AIClient:
    def _call(prompt, use_system=True, timeout=120, task_type="medium") -> str
    def _parse_json(text) -> Dict  # Handles markdown code block wrappers

    # Signal generation
    def get_signal_for_ticker(ticker, closes, features, news_sentiment, news_summary) -> {"p_up_ai": float, "reason": str}

    # News
    def analyze_news(ticker, headlines) -> {"sentiment": float, "summary": str}

    # Interactive
    def chat_with_context(user_message, positions, signals, news_data, ...) -> str
    def get_recommendation(ticker, prob_up, news_sentiment, ...) -> {"action", "confidence", "reasoning"}
    def suggest_ticker(current_tickers) -> str
    def recommend_tickers(current_tickers, category, count) -> List[{"ticker", "reason"}]
    def search_tickers(query) -> List[{"ticker", "name", "sector"}]
    def analyze_portfolio(positions, signals_df) -> str
```

## System Instruction

All calls prepend a trading-focused system instruction that establishes Claude as an expert stock trading assistant embedded in a terminal-style trading app.

## Error Handling

- CLI not found on PATH: logs a warning, continues (all calls return empty string)
- Timeout (default 120s): returns empty string, logs warning
- Rate limit / usage limit markers in response: returns empty string with warning
- Subprocess errors: returns empty string

## Platform Notes

- On Windows, spawns subprocess with `CREATE_NO_WINDOW` to suppress console flicker
- JSON parsing strips markdown code fences and finds the outermost `{}` block

## Dependencies

- `claude` CLI must be installed and on PATH (`claude --version` is checked at init)
- No API key required — uses the user's CLI subscription
