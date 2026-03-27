from __future__ import annotations

import json
import logging
from typing import Callable, Dict, List, Optional

from claude_client import ClaudeClient
from types_shared import PersonaSignal

logger = logging.getLogger(__name__)

# ── Persona Definitions ──────────────────────────────────────────────────────

PERSONA_CONFIGS: Dict[str, Dict[str, str]] = {
    "technical": {
        "name": "Technical Analyst",
        "focus": (
            "Chart patterns, support/resistance levels, moving average crossovers, "
            "RSI divergence, MACD signals, Bollinger Band positioning, and momentum "
            "indicators. You read price action like a language."
        ),
        "style": (
            "You reason from charts and indicators first. You trust price data over "
            "narratives. You identify key levels and trend structure before forming "
            "a directional view. You are disciplined and pattern-driven."
        ),
    },
    "fundamental": {
        "name": "Fundamental Analyst",
        "focus": (
            "P/E ratios, revenue growth trajectory, competitive moat, sector "
            "positioning, valuation multiples, earnings quality, balance sheet "
            "strength, and long-term business fundamentals."
        ),
        "style": (
            "You think like a value investor. You assess whether the current price "
            "reflects the intrinsic worth of the business. You consider the company's "
            "competitive position, management quality, and growth runway. Even with "
            "limited data, you draw on your knowledge of the company and sector."
        ),
    },
    "momentum": {
        "name": "Momentum Trader",
        "focus": (
            "Trend persistence, relative strength vs. sector and market, breakout "
            "confirmation, volume surges, price acceleration, and the continuation "
            "vs. exhaustion question."
        ),
        "style": (
            "You follow the trend until it bends. You look for confirmation in "
            "volume and breadth. You are aggressive when momentum aligns and quick "
            "to cut when it fades. Speed and conviction matter to you."
        ),
    },
    "contrarian": {
        "name": "Contrarian Strategist",
        "focus": (
            "Overreaction detection, extreme sentiment readings, mean-reversion "
            "setups, crowd positioning errors, capitulation signals, and neglected "
            "or hated names with improving fundamentals."
        ),
        "style": (
            "You question the consensus. When everyone is bullish you look for "
            "cracks; when panic sets in you look for opportunity. You thrive on "
            "sentiment extremes and reversion-to-mean dynamics. You are sceptical "
            "by nature but not blindly oppositional."
        ),
    },
    "risk": {
        "name": "Risk Analyst",
        "focus": (
            "Downside scenarios, tail risks, liquidity concerns, volatility regime "
            "shifts, correlation breakdowns, worst-case analysis, and risk/reward "
            "asymmetry. You ask what could go wrong."
        ),
        "style": (
            "You are the voice of caution. You stress-test every thesis by imagining "
            "adverse outcomes. You quantify how much can be lost and whether the "
            "upside justifies the exposure. You do not predict direction so much as "
            "map the danger zones."
        ),
    },
}

_ALL_PERSONAS: List[str] = list(PERSONA_CONFIGS.keys())


# ── Per-persona analysis guidance (module-level constant) ─────────────────────

_ANALYSIS_GUIDANCE: Dict[str, str] = {
    "technical": (
        "Focus on the price data and technical indicators provided in the features. "
        "Identify chart patterns, support/resistance from the closes, moving average "
        "relationships (SMA, EMA), RSI readings, MACD signals, and momentum. "
        "Your view should flow from what the chart is telling you."
    ),
    "fundamental": (
        "Note that you only have price data and technical features — not full financial "
        "statements. Use your knowledge of this company: its sector, competitive position, "
        "recent earnings trajectory, valuation relative to peers, and any known catalysts. "
        "Combine that context with the price trend to form a fundamental view."
    ),
    "momentum": (
        "Focus on the trend direction in the closes and the momentum-related features "
        "(RSI, rate of change, moving average slopes, volume patterns). Determine "
        "whether the current move has follow-through potential or is showing exhaustion. "
        "A strong trend with confirming volume should make you bullish; divergence or "
        "flattening should make you cautious."
    ),
    "contrarian": (
        "Look for extremes and potential reversals. Is sentiment overly stretched in "
        "one direction? Has the price moved too far too fast? Are features like RSI "
        "at overbought/oversold extremes? Question the consensus — if the data "
        "screams BUY, ask what everyone is missing. If it screams SELL, ask whether "
        "capitulation has already occurred."
    ),
    "risk": (
        "Identify what could go wrong. Assess downside risk using the recent closes "
        "and volatility features. Consider tail-risk scenarios: earnings misses, "
        "sector rotation, macro shocks, liquidity traps. Evaluate whether the "
        "risk/reward is asymmetric — is the potential gain worth the potential loss? "
        "Your job is to protect capital, not to chase returns."
    ),
}


# ── Persona Analyzer ─────────────────────────────────────────────────────────

class ClaudePersonaAnalyzer:
    """Run multiple Claude analyst personas to produce diverse AI opinions per ticker.

    The primary path uses a single batched Sonnet call per ticker (all 5 personas
    in one prompt).  The legacy sequential Opus path is preserved as a fallback.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        personas: List[str] | None = None,
    ) -> None:
        self._client = claude_client
        self._personas = personas if personas is not None else list(_ALL_PERSONAS)

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_ticker(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float = 0.0,
        news_summary: str = "",
    ) -> List[PersonaSignal]:
        """Run all configured personas for *ticker* and return their signals.

        Attempts the batched path first (single Sonnet call).  Falls back to
        the sequential per-persona Opus approach if batching fails.
        """
        try:
            signals = self._run_all_personas_batched(
                ticker, closes, features, news_sentiment, news_summary,
            )
            if signals:
                return signals
        except Exception:
            logger.warning(
                "Batched persona call failed for %s — falling back to sequential",
                ticker,
                exc_info=True,
            )

        # Sequential fallback (original behaviour)
        return self._run_personas_sequential(
            ticker, closes, features, news_sentiment, news_summary,
        )

    def analyze_batch(
        self,
        ticker_data: Dict[str, Dict[str, float | List[float] | str]],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, List[PersonaSignal]]:
        """Process multiple tickers using the batched path (one Sonnet call per ticker).

        *ticker_data* maps ``ticker -> {"closes", "features", "news_sentiment", "news_summary"}``.
        *on_progress* is an optional ``(completed: int, total: int, detail: str) -> None``
        callback invoked after every ticker completes.

        The progress total reflects one call per ticker rather than one per persona,
        since the batched path collapses all 5 personas into a single model call.
        """
        results: Dict[str, List[PersonaSignal]] = {}
        total_tickers = len(ticker_data)
        completed = 0

        for ticker, data in ticker_data.items():
            closes: List[float] = data.get("closes", [])  # type: ignore[assignment]
            features: Dict[str, float] = data.get("features", {})  # type: ignore[assignment]
            news_sentiment: float = float(data.get("news_sentiment", 0.0))  # type: ignore[arg-type]
            news_summary: str = str(data.get("news_summary", ""))

            signals: List[PersonaSignal] = []
            batched_ok = False

            try:
                signals = self._run_all_personas_batched(
                    ticker, closes, features, news_sentiment, news_summary,
                )
                if signals:
                    batched_ok = True
            except Exception:
                logger.warning(
                    "Batched persona call failed for %s — falling back to sequential",
                    ticker,
                    exc_info=True,
                )

            if not batched_ok:
                # Sequential fallback preserves the old per-persona progress ticks
                # so the UI doesn't stall during degraded operation.
                signals = self._run_personas_sequential_with_progress(
                    ticker, closes, features, news_sentiment, news_summary,
                    completed_base=completed,
                    total_override=total_tickers,
                    on_progress=on_progress,
                )

            results[ticker] = signals
            completed += 1

            if on_progress is not None:
                on_progress(completed, total_tickers, ticker)

        return results

    def aggregate_personas(
        self,
        signals: List[PersonaSignal],
    ) -> tuple[float, float]:
        """Return ``(weighted_avg_probability, weighted_avg_confidence)`` across persona signals.

        Weights each persona's probability by its confidence.  Falls back to
        ``(0.5, 0.0)`` when there are no signals or total confidence is zero.
        """
        if not signals:
            return 0.5, 0.0

        total_conf = sum(s.confidence for s in signals)
        if total_conf == 0.0:
            return 0.5, 0.0

        weighted_prob = sum(s.probability * s.confidence for s in signals) / total_conf
        avg_confidence = total_conf / len(signals)
        return weighted_prob, avg_confidence

    # ── Batched path ──────────────────────────────────────────────────────

    def _run_all_personas_batched(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> List[PersonaSignal]:
        """Analyse *ticker* from all persona perspectives in a single Sonnet call.

        Returns a list of PersonaSignal objects — one per active persona.
        Raises on network/CLI failure so callers can fall back gracefully.
        Falls back to neutral signals for individual personas whose JSON entries
        are malformed, rather than aborting the entire batch.
        """
        prompt = self._build_batched_prompt(
            ticker, closes, features, news_sentiment, news_summary,
        )
        # Sonnet is sufficient for structured JSON extraction; Opus is unnecessary here.
        raw = self._client._call(prompt, use_system=True, task_type="medium")
        return self._parse_batched_response(ticker, raw)

    def _build_batched_prompt(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> str:
        """Build a single prompt that requests all persona analyses in one JSON block."""
        closes_str = ", ".join(f"{c:.2f}" for c in closes[-30:])
        feats_str = ", ".join(f"{k}={v:.4f}" for k, v in features.items())

        news_block = ""
        if news_summary:
            news_block = (
                f"\nNews Sentiment Score: {news_sentiment:.2f} (-1 = bearish, +1 = bullish)\n"
                f"News Summary: {news_summary}\n"
            )

        # Build one numbered section per active persona
        persona_sections: List[str] = []
        for i, persona_key in enumerate(self._personas, start=1):
            cfg = PERSONA_CONFIGS[persona_key]
            guidance = _ANALYSIS_GUIDANCE[persona_key]
            persona_sections.append(
                f"{i}. **{cfg['name']}** (key: \"{persona_key}\")\n"
                f"   Focus: {cfg['focus']}\n"
                f"   Style: {cfg['style']}\n"
                f"   Analysis task: {guidance}"
            )

        personas_block = "\n\n".join(persona_sections)

        # Build the expected JSON template to guide the model
        example_entries = ",\n  ".join(
            f'{{"persona": "{p}", "probability": 0.5, "recommendation": "HOLD", '
            f'"confidence": 0.5, "reasoning": "..."}}'
            for p in self._personas
        )

        prompt = (
            f"You are an investment committee analysing {ticker} from {len(self._personas)} "
            f"distinct analyst perspectives simultaneously.\n\n"
            f"── Market Data for {ticker} ──\n"
            f"Recent daily closes (oldest → newest): {closes_str}\n"
            f"Engineered features: {feats_str}\n"
            f"{news_block}\n"
            f"── Analyst Perspectives ──\n\n"
            f"{personas_block}\n\n"
            f"── Instructions ──\n"
            f"For EACH analyst above, independently estimate the probability (0.0–1.0) "
            f"that tomorrow's closing price will be higher than today's, state a "
            f"recommendation (BUY, SELL, or HOLD), a confidence score (0.0–1.0), "
            f"and a concise reasoning paragraph.\n\n"
            f"Each analyst must reason from their own lens — do NOT let them agree "
            f"blindly. Genuine disagreement between perspectives is expected and valuable.\n\n"
            f"Respond ONLY with valid JSON — no commentary outside the braces:\n"
            f'{{"analyses": [\n  {example_entries}\n]}}'
        )
        return prompt

    def _is_rate_limited_response(self, response: str) -> bool:
        """Check if a Claude CLI response indicates rate limiting."""
        if not response or len(response.strip()) < 20:
            return True
        rate_limit_indicators = [
            "usage limit", "rate limit", "try again",
            "capacity", "overloaded", "too many requests",
        ]
        lower = response.lower()
        return any(indicator in lower for indicator in rate_limit_indicators)

    def _parse_batched_response(
        self,
        ticker: str,
        response: str,
    ) -> List[PersonaSignal]:
        """Parse the batched JSON response into PersonaSignal objects.

        Malformed individual entries fall back to neutral signals rather than
        discarding the entire batch.  Returns an empty list only when the
        top-level JSON structure itself is unrecoverable (triggering the
        sequential fallback in the caller).
        """
        if self._is_rate_limited_response(response):
            logger.warning(
                "Rate-limited or empty batched response for %s — triggering sequential fallback",
                ticker,
            )
            return []

        try:
            obj = self._client._parse_json(response)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Batched JSON parse failed for %s: %s", ticker, exc,
            )
            return []

        analyses = obj.get("analyses")
        if not isinstance(analyses, list) or not analyses:
            logger.warning(
                "Batched response for %s missing 'analyses' list", ticker,
            )
            return []

        # Build a lookup so we can match response entries back to active personas
        active_persona_set = set(self._personas)
        signals: List[PersonaSignal] = []
        seen_personas: set[str] = set()

        for entry in analyses:
            if not isinstance(entry, dict):
                continue

            persona_key = str(entry.get("persona", "")).lower().strip()

            # Accept the key directly if it matches, otherwise skip unknown keys
            if persona_key not in active_persona_set:
                logger.debug(
                    "Batched response for %s contained unknown persona key '%s' — skipping",
                    ticker, persona_key,
                )
                continue

            if persona_key in seen_personas:
                # Deduplicate if the model returned the same persona twice
                continue
            seen_personas.add(persona_key)

            try:
                probability = max(0.0, min(1.0, float(entry.get("probability", 0.5))))
                confidence = max(0.0, min(1.0, float(entry.get("confidence", 0.0))))
                recommendation = str(entry.get("recommendation", "HOLD")).upper().strip()
                reasoning = str(entry.get("reasoning", ""))

                if recommendation not in {"BUY", "SELL", "HOLD"}:
                    recommendation = "HOLD"

                signals.append(PersonaSignal(
                    persona=persona_key,
                    ticker=ticker,
                    probability=probability,
                    recommendation=recommendation,
                    confidence=confidence,
                    reasoning=reasoning,
                ))
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "Field extraction failed for persona '%s' on %s in batched response: %s",
                    persona_key, ticker, exc,
                )
                signals.append(self._neutral_signal(persona_key, ticker, f"Field error: {exc}"))

        # Fill in neutral signals for any personas the model omitted entirely
        for persona_key in self._personas:
            if persona_key not in seen_personas:
                logger.warning(
                    "Batched response for %s omitted persona '%s' — using neutral fallback",
                    ticker, persona_key,
                )
                signals.append(self._neutral_signal(persona_key, ticker, "Omitted from batched response"))

        # Detect suspiciously uniform responses — all personas returning exactly
        # 0.5 probability is a hallmark of a rate-limited or non-substantive reply.
        if len(signals) > 1:
            probs = [s.probability for s in signals]
            all_near_half = all(abs(p - 0.5) <= 0.01 for p in probs)
            if all_near_half:
                logger.warning(
                    "Suspicious uniform responses for %s — all personas returned ~0.5 "
                    "(possible rate limit) — triggering sequential fallback",
                    ticker,
                )
                return []

        return signals

    # ── Sequential path (legacy / fallback) ───────────────────────────────

    def _run_personas_sequential(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> List[PersonaSignal]:
        """Run all configured personas sequentially (one Opus call each).

        Used as a fallback when the batched path fails entirely.
        """
        signals: List[PersonaSignal] = []
        for persona in self._personas:
            try:
                signal = self._run_single_persona(
                    persona, ticker, closes, features, news_sentiment, news_summary,
                )
                signals.append(signal)
            except Exception:
                logger.warning(
                    "Persona '%s' failed for %s — skipping",
                    persona,
                    ticker,
                    exc_info=True,
                )
        return signals

    def _run_personas_sequential_with_progress(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
        completed_base: int,
        total_override: int,
        on_progress: Optional[Callable[[int, int, str], None]],
    ) -> List[PersonaSignal]:
        """Sequential fallback that fires per-persona progress ticks.

        Used inside analyze_batch when the batched call fails so the UI
        doesn't appear frozen during degraded operation.
        """
        signals: List[PersonaSignal] = []
        for persona in self._personas:
            try:
                signal = self._run_single_persona(
                    persona, ticker, closes, features, news_sentiment, news_summary,
                )
                signals.append(signal)
            except Exception:
                logger.warning(
                    "Persona '%s' failed for %s — skipping",
                    persona,
                    ticker,
                    exc_info=True,
                )
            # Fire a sub-tick so callers know something is happening.
            # We don't increment completed_base here — the caller does that once
            # after the ticker finishes — so we pass the base value unchanged.
            if on_progress is not None:
                on_progress(completed_base, total_override, f"{ticker}/{persona}")

        return signals

    def _run_single_persona(
        self,
        persona: str,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> PersonaSignal:
        """Build a prompt, call Claude (Opus), and parse the response for one persona.

        Preserved as the legacy sequential path and as a fallback when the
        batched call fails.
        """
        prompt = self._build_persona_prompt(
            persona, ticker, closes, features, news_sentiment, news_summary,
        )
        raw = self._client._call(prompt, use_system=True, task_type="complex")
        if self._is_rate_limited_response(raw):
            raise RuntimeError(
                f"Rate-limited or empty response for persona '{persona}' on {ticker} — skipping"
            )
        return self._parse_persona_response(persona, ticker, raw)

    def _build_persona_prompt(
        self,
        persona: str,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> str:
        """Build a tailored analysis prompt for *persona*."""
        config = PERSONA_CONFIGS[persona]
        closes_str = ", ".join(f"{c:.2f}" for c in closes[-30:])
        feats_str = ", ".join(f"{k}={v:.4f}" for k, v in features.items())

        analysis_guidance = _ANALYSIS_GUIDANCE[persona]

        news_block = ""
        if news_summary:
            news_block = (
                f"\nNews Sentiment Score: {news_sentiment:.2f} (-1 = bearish, +1 = bullish)\n"
                f"News Summary: {news_summary}\n"
            )

        prompt = (
            f"You are the **{config['name']}** on a multi-analyst investment committee.\n"
            f"YOUR FOCUS: {config['focus']}\n"
            f"YOUR STYLE: {config['style']}\n\n"
            f"── Data for {ticker} ──\n"
            f"Recent daily closes (oldest → newest): {closes_str}\n"
            f"Engineered features: {feats_str}\n"
            f"{news_block}\n"
            f"── Your task ──\n"
            f"{analysis_guidance}\n\n"
            "Estimate the probability (0.0–1.0) that tomorrow's closing price will be "
            "higher than today's. State your recommendation and confidence.\n\n"
            "Respond ONLY with valid JSON — no commentary outside the braces:\n"
            "{\n"
            '  "probability": <float 0-1>,\n'
            '  "recommendation": "<BUY | SELL | HOLD>",\n'
            '  "confidence": <float 0-1>,\n'
            '  "reasoning": "<one paragraph explaining your view>"\n'
            "}"
        )
        return prompt

    def _parse_persona_response(
        self,
        persona: str,
        ticker: str,
        response: str,
    ) -> PersonaSignal:
        """Parse Claude JSON into a PersonaSignal, with safe fallback."""
        if not response:
            return self._neutral_signal(persona, ticker, "Empty response from Claude")

        try:
            obj = self._client._parse_json(response)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "JSON parse failed for persona '%s' on %s: %s",
                persona, ticker, exc,
            )
            return self._neutral_signal(persona, ticker, f"Parse error: {exc}")

        try:
            probability = max(0.0, min(1.0, float(obj.get("probability", 0.5))))
            confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
            recommendation = str(obj.get("recommendation", "HOLD")).upper().strip()
            reasoning = str(obj.get("reasoning", ""))

            if recommendation not in {"BUY", "SELL", "HOLD"}:
                recommendation = "HOLD"

            return PersonaSignal(
                persona=persona,
                ticker=ticker,
                probability=probability,
                recommendation=recommendation,
                confidence=confidence,
                reasoning=reasoning,
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Field extraction failed for persona '%s' on %s: %s",
                persona, ticker, exc,
            )
            return self._neutral_signal(persona, ticker, f"Field error: {exc}")

    @staticmethod
    def _neutral_signal(persona: str, ticker: str, reason: str) -> PersonaSignal:
        """Return a non-committal fallback signal when a persona call fails."""
        return PersonaSignal(
            persona=persona,
            ticker=ticker,
            probability=0.5,
            recommendation="HOLD",
            confidence=0.0,
            reasoning=reason,
        )
