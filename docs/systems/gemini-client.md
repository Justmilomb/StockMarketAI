# Gemini Client

## Goal
Wraps the Google Gemini API to provide LLM-powered signal generation, news sentiment analysis, ticker recommendations, interactive chat, and portfolio analysis.

## Implementation
Uses `google.genai.Client` with a system instruction establishing an expert trading assistant persona. All responses parsed as JSON with markdown code block stripping. Provides six main capabilities: per-ticker signal estimation, news sentiment scoring, BUY/SELL/HOLD recommendations, context-aware chat, ticker suggestions, and multi-ticker search.

## Key Code
```python
def get_signal_for_ticker(ticker, recent_closes, features) -> {"p_up_gemini": float, "reason": str}
def analyze_news(ticker, headlines) -> {"sentiment": float, "summary": str}
def chat_with_context(message, positions, signals, news, account) -> str
```

## Notes
- API key from env var `GEMINI_API_KEY` (raises RuntimeError if missing)
- Default model: `gemini-2.5-flash`
- All probabilities clamped to [0.0, 1.0], sentiments to [-1.0, 1.0]
- Graceful fallback on parse errors (returns neutral defaults)
