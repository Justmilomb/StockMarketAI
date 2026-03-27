from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from gemini_client import GeminiClient
from types_shared import GeminiPersonaSignal

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


# ── Persona Analyzer ─────────────────────────────────────────────────────────

class GeminiPersonaAnalyzer:
    """Run multiple Gemini analyst personas to produce diverse AI opinions per ticker."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        personas: List[str] | None = None,
    ) -> None:
        self._client = gemini_client
        self._personas = personas if personas is not None else list(_ALL_PERSONAS)

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_ticker(
        self,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float = 0.0,
        news_summary: str = "",
    ) -> List[GeminiPersonaSignal]:
        """Run all configured personas for *ticker* in parallel and return their signals."""
        signals: List[GeminiPersonaSignal] = []

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(
                    self._run_single_persona,
                    persona,
                    ticker,
                    closes,
                    features,
                    news_sentiment,
                    news_summary,
                ): persona
                for persona in self._personas
            }

            for future in as_completed(futures, timeout=60):
                persona = futures[future]
                try:
                    signal = future.result(timeout=30)
                    signals.append(signal)
                except TimeoutError:
                    logger.warning("Persona '%s' timed out for %s — skipping", persona, ticker)
                except Exception:
                    logger.warning(
                        "Persona '%s' failed for %s — skipping",
                        persona,
                        ticker,
                        exc_info=True,
                    )

        return signals

    def analyze_batch(
        self,
        ticker_data: Dict[str, Dict[str, float | List[float] | str]],
    ) -> Dict[str, List[GeminiPersonaSignal]]:
        """Process multiple tickers sequentially (personas within each run in parallel).

        *ticker_data* maps ``ticker -> {"closes", "features", "news_sentiment", "news_summary"}``.
        """
        results: Dict[str, List[GeminiPersonaSignal]] = {}
        for ticker, data in ticker_data.items():
            closes: List[float] = data.get("closes", [])  # type: ignore[assignment]
            features: Dict[str, float] = data.get("features", {})  # type: ignore[assignment]
            news_sentiment: float = float(data.get("news_sentiment", 0.0))  # type: ignore[arg-type]
            news_summary: str = str(data.get("news_summary", ""))
            results[ticker] = self.analyze_ticker(
                ticker,
                closes,
                features,
                news_sentiment,
                news_summary,
            )
        return results

    def aggregate_personas(
        self,
        signals: List[GeminiPersonaSignal],
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

    # ── Internal helpers ──────────────────────────────────────────────────

    def _run_single_persona(
        self,
        persona: str,
        ticker: str,
        closes: List[float],
        features: Dict[str, float],
        news_sentiment: float,
        news_summary: str,
    ) -> GeminiPersonaSignal:
        """Build a prompt, call Gemini, and parse the response for one persona."""
        prompt = self._build_persona_prompt(
            persona, ticker, closes, features, news_sentiment, news_summary,
        )
        raw = self._client._call(prompt, use_system=True)
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

        # Persona-specific analysis guidance
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
    ) -> GeminiPersonaSignal:
        """Parse Gemini JSON into a GeminiPersonaSignal, with safe fallback."""
        if not response:
            return self._neutral_signal(persona, ticker, "Empty response from Gemini")

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

            return GeminiPersonaSignal(
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
    def _neutral_signal(persona: str, ticker: str, reason: str) -> GeminiPersonaSignal:
        """Return a non-committal fallback signal when a persona call fails."""
        return GeminiPersonaSignal(
            persona=persona,
            ticker=ticker,
            probability=0.5,
            recommendation="HOLD",
            confidence=0.0,
            reasoning=reason,
        )


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
