from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

# Hide console windows when spawning AI engine on Windows
_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

logger = logging.getLogger(__name__)


def _compute_verdict(prob: float, consensus_pct: float) -> str:
    """Compute verdict from probability and consensus percentage."""
    if prob > 0.65 and consensus_pct >= 70:
        return "STR BUY"
    if prob > 0.55 and consensus_pct >= 60:
        return "BUY"
    if prob < 0.35 and consensus_pct >= 70:
        return "STR SELL"
    if prob < 0.45 and consensus_pct >= 60:
        return "SELL"
    return "NEUTRAL"


def _decode_model(val: str) -> str:
    """Decode a base64-encoded model ID, or pass through if plain."""
    if not val:
        return val
    try:
        return base64.b64decode(val).decode()
    except Exception:
        return val


@dataclass
class AIConfig:
    model: str = ""
    model_complex: str = ""
    model_medium: str = ""
    model_simple: str = ""

    def __post_init__(self) -> None:
        self.model = _decode_model(self.model)
        self.model_complex = _decode_model(self.model_complex)
        self.model_medium = _decode_model(self.model_medium)
        self.model_simple = _decode_model(self.model_simple)


class AIClient:
    """AI client that calls the engine CLI as a subprocess."""

    SYSTEM_INSTRUCTION = (
        "You are an expert AI stock trading assistant "
        "integrated into a professional trading terminal. "
        "You specialize in US equities and have deep knowledge of "
        "technical analysis, fundamental analysis, market sentiment, and macroeconomic trends.\n\n"
        "RULES:\n"
        "1. Always respond in the exact format requested (JSON, plain text, etc.)\n"
        "2. When suggesting tickers, only suggest real, actively traded US stock tickers\n"
        "3. Base recommendations on technical indicators, recent price action, and news sentiment\n"
        "4. Be concise and actionable - traders need fast, clear information\n"
        "5. Always include confidence levels and risk disclaimers when giving trade advice\n"
        "6. When analyzing, consider: RSI, moving averages, volume, volatility, and sector trends\n"
        "7. You are AI-powered, used via the user's subscription"
    )

    def __init__(self, config: AIConfig | None = None) -> None:
        if config is None:
            config = AIConfig()
        self.config = config
        self._available = True

    @property
    def available(self) -> bool:
        """Whether the AI engine is installed and reachable."""
        return self._available

    def _get_model_for_task(self, task_type: str) -> str:
        """Select the appropriate model based on task complexity."""
        if task_type == "complex":
            return self.config.model_complex
        elif task_type == "simple":
            return self.config.model_simple
        else:  # "medium" or default
            return self.config.model_medium

    def _cli_command(self) -> str:
        """Resolve the AI engine CLI executable."""
        from core.agent.paths import bundled_engine_cmd, engine_available
        if engine_available():
            return str(bundled_engine_cmd())
        return "claude"  # dev fallback

    def _call(
        self,
        prompt: str,
        use_system: bool = True,
        timeout: int = 120,
        task_type: str = "medium",
    ) -> str:
        """Call the AI engine CLI and return the response text.

        task_type: 'complex', 'medium', or 'simple'
        Falls back to an empty string on any subprocess error.
        """
        if not self._available:
            return ""
        full_prompt = f"{self.SYSTEM_INSTRUCTION}\n\n{prompt}" if use_system else prompt
        model = self._get_model_for_task(task_type)

        try:
            result = subprocess.run(
                [self._cli_command(), "-p", full_prompt, "--model", model, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                **_SUBPROCESS_FLAGS,
            )
            output = result.stdout.strip()

            _ERROR_MARKERS = [
                "out of extra usage",
                "rate limit",
                "quota exceeded",
                "overloaded",
                "too many requests",
                "capacity",
            ]
            output_lower = output.lower()
            for marker in _ERROR_MARKERS:
                if marker in output_lower:
                    logger.warning("AI engine usage limit hit: %s", output[:120])
                    return ""

            return output
        except subprocess.TimeoutExpired:
            logger.warning("AI engine timed out after %ds on %s", timeout, model)
            return ""
        except subprocess.CalledProcessError as e:
            logger.warning("AI engine process error: %s", e)
            return ""
        except Exception as e:
            logger.warning("Unexpected error calling AI engine: %s", e)
            return ""

    def _parse_json(self, text: str) -> Dict:
        """Parse JSON from AI response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        # Sometimes the AI adds text after the JSON block, find the first '{' and last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]

        return json.loads(text.strip())

    # ── Strategy Profile Selection ────────────────────────────────────

    _PROFILE_DESCRIPTIONS = {
        "day_trader": "Short-term trades, 1-day horizon, tight stops, high conviction only",
        "swing": "Multi-day holds (5-20 days), moderate risk, balanced approach",
        "trend_follower": "Rides established trends, wide stops, lets winners run",
        "conservative": "Capital preservation first, very selective, small positions",
        "crisis_alpha": "Extreme caution, minimal exposure, only highest-conviction trades",
    }

    def select_strategy_profile(
        self,
        regime: str,
        regime_confidence: float,
        market_summary: str,
        available_profiles: list[str] | None = None,
    ) -> str:
        """Ask the AI to pick the best strategy profile for current conditions.

        Returns one of the profile names, or empty string on failure.
        Falls back to caller's default if AI is unavailable.
        """
        profiles = available_profiles or list(self._PROFILE_DESCRIPTIONS.keys())
        profile_list = "\n".join(
            f"  - {name}: {self._PROFILE_DESCRIPTIONS.get(name, 'No description')}"
            for name in profiles
        )

        prompt = (
            "You are the chief strategist for an AI trading desk. "
            "Based on the current market conditions, pick the single best strategy profile to deploy.\n\n"
            f"DETECTED REGIME: {regime} (confidence: {regime_confidence:.0%})\n\n"
            f"MARKET CONTEXT:\n{market_summary}\n\n"
            f"AVAILABLE PROFILES:\n{profile_list}\n\n"
            "Respond with ONLY the profile name (e.g., 'day_trader'). Nothing else."
        )

        response = self._call(prompt, use_system=False, timeout=30, task_type="complex")
        response = response.strip().lower().replace("'", "").replace('"', '')

        if response in profiles:
            logger.info("AI selected profile: %s (regime=%s)", response, regime)
            return response

        logger.warning("AI returned invalid profile '%s', falling back", response)
        return ""

    # ── Signal Generation ──────────────────────────────────────────────

    def get_signal_for_ticker(
        self,
        ticker: str,
        recent_closes: List[float],
        features: Dict[str, float],
        news_sentiment: float = 0.0,
        news_summary: str = "",
    ) -> Dict[str, Any]:
        """
        Ask the AI for a probability that tomorrow's close will be higher,
        plus a short explanation. Returns { 'p_up_ai': float, 'reason': str }.
        """
        closes_str = ", ".join(f"{float(p):.2f}" for p in recent_closes[-30:])
        feats_str = ", ".join(f"{k}={v:.4f}" for k, v in features.items())

        news_context = ""
        if news_summary:
            news_context = (
                f"\nNews Sentiment Score: {news_sentiment:.2f} (-1=bearish, +1=bullish)\n"
                f"News Summary: {news_summary}\n"
            )

        prompt = (
            "You are helping with very short-term stock prediction.\n"
            f"Ticker: {ticker}\n"
            f"Recent daily closes (oldest -> newest): {closes_str}\n"
            f"Engineered features: {feats_str}\n"
            f"{news_context}\n"
            "Estimate the probability (between 0 and 1) that tomorrow's closing "
            "price will be higher than today's, and give a brief reason.\n"
            "Respond strictly as JSON with fields 'p_up' (float) and 'reason' (string)."
        )

        try:
            text = self._call(prompt, task_type="medium")
            if not text:
                raise ValueError("Empty response from AI")
            obj = self._parse_json(text)
            p_up = float(obj.get("p_up", 0.5))
            reason = str(obj.get("reason", "No explanation provided."))
        except Exception as e:
            logger.warning("Signal error for %s: %s", ticker, e)
            p_up = 0.5
            reason = f"AI Error: {e}"

        p_up = max(0.0, min(1.0, p_up))
        return {"p_up_ai": p_up, "reason": reason}

    # ── News Sentiment Analysis ────────────────────────────────────────

    def analyze_news(self, ticker: str, headlines: List[str]) -> Dict[str, Any]:
        """
        Given headlines for a ticker, return a sentiment score and one-line summary.
        Returns { 'sentiment': float (-1 to 1), 'summary': str }
        """
        if not headlines:
            return {"sentiment": 0.0, "summary": "No news available."}

        headlines_str = "\n".join(f"- {h}" for h in headlines[:15])
        prompt = (
            f"Analyze these recent news headlines for {ticker} stock:\n"
            f"{headlines_str}\n\n"
            "Rate the overall sentiment from -1.0 (very bearish) to +1.0 (very bullish) "
            "and write a one-sentence summary of the news sentiment.\n"
            'Respond strictly as JSON: {"sentiment": float, "summary": string}'
        )
        try:
            text = self._call(prompt)
            if not text:
                 return {"sentiment": 0.0, "summary": "AI could not reach a conclusion."}
            obj = self._parse_json(text)
            sentiment = max(-1.0, min(1.0, float(obj.get("sentiment", 0.0))))
            summary = str(obj.get("summary", "No clear opinion found."))
            return {"sentiment": sentiment, "summary": summary}
        except Exception as e:
            # If JSON parsing fails, the AI might have just sent a sentence.
            if text and "{" not in text:
                return {"sentiment": 0.0, "summary": text[:100]}
            return {"sentiment": 0.0, "summary": "Could not analyze news."}

    # ── AI Recommendation ──────────────────────────────────────────────

    def get_recommendation(
        self,
        ticker: str,
        prob_up: float,
        news_sentiment: float,
        news_summary: str,
        current_position: bool,
        features: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Generate a clear BUY/SELL/HOLD recommendation with reasoning.
        Returns { 'action': str, 'confidence': float, 'reasoning': str }
        """
        feats_str = ", ".join(f"{k}={v:.4f}" for k, v in features.items())
        pos_status = "Currently HOLDING this stock" if current_position else "NOT currently holding"

        prompt = (
            f"You are an AI trading advisor. Give a clear recommendation for {ticker}.\n\n"
            f"ML Model Probability (up tomorrow): {prob_up:.2f}\n"
            f"News Sentiment: {news_sentiment:.2f} (-1=bearish, +1=bullish)\n"
            f"News: {news_summary}\n"
            f"Technical Features: {feats_str}\n"
            f"Position Status: {pos_status}\n\n"
            "Respond strictly as JSON with fields:\n"
            "- 'action': one of 'BUY', 'SELL', 'HOLD'\n"
            "- 'confidence': float 0-1\n"
            "- 'reasoning': one sentence explanation"
        )
        try:
            text = self._call(prompt, task_type="medium")
            obj = self._parse_json(text)
            return {
                "action": str(obj.get("action", "HOLD")).upper(),
                "confidence": max(0.0, min(1.0, float(obj.get("confidence", 0.5)))),
                "reasoning": str(obj.get("reasoning", "")),
            }
        except Exception:
            return {"action": "HOLD", "confidence": 0.0, "reasoning": "Could not generate recommendation."}

    # ── Interactive Chat ───────────────────────────────────────────────

    def chat_with_context(
        self,
        user_message: str,
        positions: List[Dict[str, Any]],
        signals: Any,
        news_data: Dict[str, Any],
        account_info: Dict[str, Any],
        *,
        chat_history: List[Dict[str, str]] | None = None,
        protected_tickers: set[str] | None = None,
        regime: str = "unknown",
        regime_confidence: float = 0.0,
        consensus_data: Dict[str, Any] | None = None,
        memory_summary: str = "",
        live_data: Dict[str, Dict[str, float]] | None = None,
    ) -> str:
        """
        Multi-context chat: builds a system prompt with all terminal data
        (positions, signals, news, regime, consensus, meta-ensemble, memory)
        and responds to the user's question.
        """
        # ── Positions (detailed for actionable advice) ──
        pos_lines: list[str] = []
        for p in positions:
            t = p.get("ticker", "?")
            q = p.get("quantity", 0)
            pnl = p.get("unrealised_pnl", 0.0)
            avg = p.get("avg_price", 0.0)
            cur = p.get("current_price", 0.0)
            pct = ((cur - avg) / avg * 100) if avg > 0 else 0.0
            pos_lines.append(
                f"  {t}: {q} shares, avg=${avg:.2f}, current=${cur:.2f}, "
                f"PnL=${pnl:.2f} ({pct:+.1f}%)"
            )
        pos_text = "\n".join(pos_lines) if pos_lines else "  No open positions"

        # ── Signals + Watchlist Overview (all tickers) ──
        sig_lines: list[str] = []
        if signals is not None and hasattr(signals, 'iterrows'):
            live = live_data or {}
            cons_d = consensus_data or {}
            for _, row in signals.head(30).iterrows():
                ticker = row.get('ticker', '?')
                signal = row.get('signal', '?')
                ai_rec = row.get('ai_rec', '')
                p_sk = row.get('p_up_sklearn', 0)
                p_gm = row.get('p_up_ai', 0)
                p_fin = row.get('p_up_final', 0)
                prob_up = float(row.get('prob_up', p_fin))
                reason = row.get('reason', '')

                # Live price + day change
                live_info = live.get(ticker, {})
                live_px = live_info.get("price", 0.0)
                day_pct = live_info.get("change_pct", 0.0)

                # Consensus data for this ticker
                cons = cons_d.get(ticker)
                if cons:
                    cpct = cons.get("consensus_pct", 0) if isinstance(cons, dict) else getattr(cons, "consensus_pct", 0)
                    cconf = cons.get("confidence", 0) if isinstance(cons, dict) else getattr(cons, "confidence", 0)
                    cons_prob = cons.get("probability", prob_up) if isinstance(cons, dict) else getattr(cons, "probability", prob_up)
                else:
                    cpct = 50.0
                    cconf = 0.0
                    cons_prob = prob_up

                verdict = _compute_verdict(cons_prob, cpct)

                # News sentiment for this ticker
                nd = news_data.get(ticker)
                if nd:
                    sent = nd.sentiment if hasattr(nd, 'sentiment') else nd.get('sentiment', 0)
                else:
                    sent = 0.0

                # Is protected?
                is_prot = ticker.upper() in {t.upper() for t in (protected_tickers or set())}

                px_str = f"${live_px:.2f}" if live_px > 0 else "N/A"
                day_str = f"{day_pct:+.1f}%" if live_px > 0 else "N/A"

                line = (
                    f"  {ticker}: verdict={verdict}, signal={signal}, ai_rec={ai_rec}, "
                    f"prob_final={p_fin:.2f} (sklearn={p_sk:.2f}, ai={p_gm:.2f}), "
                    f"consensus={cpct:.0f}%, confidence={cconf:.2f}, "
                    f"live_px={px_str}, day_chg={day_str}, "
                    f"sentiment={sent:+.2f}"
                )
                if is_prot:
                    line += " [PROTECTED/LOCKED]"
                if reason and reason != "No reason provided.":
                    line += f"\n    Reason: {reason[:120]}"
                sig_lines.append(line)
        sig_text = "\n".join(sig_lines) if sig_lines else "  No signals available"

        # ── News sentiment ──
        news_lines: list[str] = []
        for ticker, nd in news_data.items():
            if hasattr(nd, 'sentiment'):
                news_lines.append(f"  {ticker}: sentiment={nd.sentiment:.2f} – {nd.summary}")
            elif isinstance(nd, dict):
                news_lines.append(f"  {ticker}: sentiment={nd.get('sentiment', 0):.2f}")
        news_text = "\n".join(news_lines) if news_lines else "  No news data"

        # ── Account ──
        acct = account_info or {}
        acct_text = (
            f"  Balance: ${acct.get('free', 0):.2f}\n"
            f"  Invested: ${acct.get('invested', 0):.2f}\n"
            f"  Total: ${acct.get('total', 0):.2f}"
        )

        # ── Conversation history (last 10 messages) ──
        conversation_lines: list[str] = []
        if chat_history:
            for msg in chat_history[-10:]:
                role_label = "User" if msg.get("role") == "user" else "Assistant"
                conversation_lines.append(f"  {role_label}: {msg.get('text', '')[:200]}")
        conversation_text = "\n".join(conversation_lines) if conversation_lines else "  (First message in this session)"

        # ── Market regime ──
        regime_text = f"  Current: {regime} (confidence: {regime_confidence:.0%})"

        # ── Protected tickers ──
        protected_text = (
            f"  Locked tickers (DO NOT trade): {', '.join(sorted(protected_tickers))}"
            if protected_tickers
            else "  None"
        )

        # ── Consensus committee (top 10) ──
        cons_lines: list[str] = []
        if consensus_data:
            for ticker, cons in list(consensus_data.items())[:10]:
                if isinstance(cons, dict):
                    cpct = cons.get("consensus_pct", 0)
                    conf = cons.get("confidence", 0)
                else:
                    cpct = getattr(cons, "consensus_pct", 0)
                    conf = getattr(cons, "confidence", 0)
                cons_lines.append(f"  {ticker}: consensus={cpct:.0f}%, confidence={conf:.2f}")
        cons_text = "\n".join(cons_lines) if cons_lines else "  No consensus data"

        # ── AI memory ──
        memory_text = f"\nAI MEMORY (facts from previous sessions):\n{memory_summary}" if memory_summary else ""

        # ── Assemble system context ──
        system_context = (
            "You are an expert AI trading assistant "
            "embedded in a professional trading terminal. "
            "You have FULL access to ALL real-time trading data below and make informed judgments. "
            "You remember previous conversations within this session and key facts from prior sessions (AI MEMORY).\n\n"
            "DATA YOU HAVE ACCESS TO:\n"
            "- Account balance, invested capital, total equity\n"
            "- Current open positions with unrealised PnL\n"
            "- Market regime (bullish/bearish/neutral) with confidence score\n"
            "- Verdict per ticker (STR BUY/BUY/NEUTRAL/SELL/STR SELL) based on probability + consensus\n"
            "- Live prices and day change percentages\n"
            "- Full watchlist signals with probabilities from multiple models (up to 30 tickers)\n"
            "- Consensus committee percentage and confidence\n"
            "- News sentiment scores for each ticker\n"
            "- Protected (locked) tickers that CANNOT be traded\n"
            "- Recent chat history within this session\n"
            "- Persistent AI memory from previous sessions\n\n"
            f"ACCOUNT:\n{acct_text}\n\n"
            f"MARKET REGIME:\n{regime_text}\n\n"
            f"PROTECTED TICKERS:\n{protected_text}\n\n"
            f"OPEN POSITIONS:\n{pos_text}\n\n"
            f"ACTIVE SIGNALS (top 15):\n{sig_text}\n\n"
            f"CONSENSUS COMMITTEE:\n{cons_text}\n\n"
            f"NEWS SENTIMENT:\n{news_text}\n\n"
            f"{memory_text}\n\n"
            f"RECENT CONVERSATION:\n{conversation_text}\n\n"
            "RULES:\n"
            "- Give specific, actionable advice grounded in the data above\n"
            "- The user is a SHORT-TERM TRADER (days to weeks). Frame all advice around short-term setups, momentum, mean reversion, and swing trades — NOT long-term fundamentals or buy-and-hold.\n"
            "- When evaluating positions: consider short-term overbought/oversold, recent momentum, and whether the trade thesis still has runway this week.\n"
            "- Consider the account balance when suggesting trades (e.g. 'with £5 free, you could buy X')\n"
            "- NEVER suggest trading protected/locked tickers — the user has explicitly locked them\n"
            "- Reference the conversation history when the user refers to earlier messages\n"
            "- Use technical analysis terminology. Be concise and professional.\n"
            "- Always include a brief risk disclaimer with trade recommendations\n"
            "- Use AI reasoning and all available data to make the best judgment\n\n"
            "POSITION ADVICE RULES (when user asks about positions):\n"
            "- Review EACH open position individually — state whether to HOLD, ADD, REDUCE, or CLOSE\n"
            "- Cross-reference each position against its signal probability, consensus %, and news sentiment\n"
            "- Flag any position where the signal is SELL but user is still holding (potential exit)\n"
            "- Flag any position with PnL below -5% as a risk to review\n"
            "- If consensus confidence is high (>70%) and disagrees with the current position direction, alert the user\n"
            "- Suggest specific actions: 'Close TSLA (prob 0.32, consensus bearish)' not vague 'review your portfolio'\n"
            "- Consider the market regime when advising — in bearish regime, be more defensive"
            "\n\n"
            "COLOUR GRADING RULES (when user asks to colour grade):\n"
            "- When the user asks to 'colour grade', 'color grade', or 'grade' the portfolio:\n"
            "- You must assign GREEN, RED, or ORANGE to EACH ticker in the watchlist\n"
            "- GREEN = strong confidence to hold/buy, bullish signals across multiple indicators\n"
            "- RED = strong confidence to sell/avoid, bearish signals across multiple indicators\n"
            "- ORANGE = mixed signals, uncertain, or neutral — needs monitoring\n"
            "- Format each grade as: TICKER: GRADE (e.g. 'TSLA: GREEN')\n"
            "- Base your grade on ALL available data: verdict, signal, AI rec, consensus, confidence, sentiment, day%, and live price\n"
            "- You are the FINAL judge — your grade overrides the computed verdict\n"
            "- After grading, briefly explain each grade (1 sentence per ticker)"
            "\n\n"
            "TRADE EXECUTION RULES (when user asks to buy, sell, close, trim, or trade):\n"
            "- You have DIRECT TRADE EXECUTION capability. When the user requests a trade action, you MUST include a TRADE_INSTRUCTIONS block.\n"
            "- Format EXACTLY as shown — the app parses this programmatically:\n\n"
            "TRADE_INSTRUCTIONS_START\n"
            "TICKER: <ticker> | ACTION: <BUY|SELL> | FRACTION: <0.0-1.0>\n"
            "TRADE_INSTRUCTIONS_END\n\n"
            "- ACTION: BUY or SELL only.\n"
            "- FRACTION: for SELL, 1.0 = close full position, 0.5 = sell half. For BUY, always use 1.0 (the risk manager determines sizing).\n"
            "- Multiple lines allowed for multiple tickers.\n"
            "- NEVER include protected/locked tickers — they CANNOT be traded.\n"
            "- For SELL: only include tickers the user currently holds (check OPEN POSITIONS).\n"
            "- For BUY: only include tickers you have signal data for, or that the user explicitly names.\n"
            "- If the user says 'sell my losers', analyse all positions, identify losers, and list each one.\n"
            "- If the user says 'sell everything', list every non-protected open position.\n"
            "- Always provide your analysis and reasoning BEFORE the TRADE_INSTRUCTIONS block.\n"
            "- After the block, add a brief summary of what will be executed.\n"
            "- Think SHORT-TERM: sell losers quickly, take profits on extended moves, buy momentum setups."
        )

        prompt = f"{system_context}\n\nUser: {user_message}\nAssistant:"
        try:
            return self._call(prompt, task_type="complex")
        except Exception as e:
            return f"Error: {e}"

    # ── Legacy Methods ─────────────────────────────────────────────────

    def chat(self, context: str, message: str) -> str:
        """Generic chat helper."""
        prompt = f"{context}\n\nUser: {message}\nAssistant:"
        return self._call(prompt)

    def suggest_ticker(self, current_tickers: List[str]) -> str:
        """Suggest a new ticker for the watchlist."""
        curr_str = ", ".join(current_tickers)
        prompt = (
            f"Given this stock watchlist: {curr_str}\n\n"
            "Suggest ONE new US stock ticker that would complement this list well "
            "or is currently interesting based on current market conditions. "
            "Consider sector diversification, momentum, and recent catalysts. "
            "Respond ONLY with the ticker symbol (e.g., TSLA). No other text."
        )
        try:
            text = self._call(prompt, task_type="medium").upper().strip()
            # Clean up any extra text
            text = text.split()[0] if text else ""
            if text and len(text) <= 5 and text.isalpha():
                return text
        except Exception as e:
            logger.warning("Error getting ticker suggestion: %s", e)
        return ""

    def recommend_tickers(
        self,
        current_tickers: List[str],
        category: str = "",
        count: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Ask the AI to recommend multiple tickers with reasoning.
        Returns [{'ticker': 'AAPL', 'reason': '...'}, ...]
        """
        curr_str = ", ".join(current_tickers) if current_tickers else "empty"
        cat_hint = f" Focus on: {category}." if category else ""

        prompt = (
            f"Current watchlist: {curr_str}\n"
            f"Recommend {count} US stock tickers to add to this watchlist.{cat_hint}\n"
            "Consider: sector diversification, current momentum, earnings catalysts, "
            "and market trends. Do NOT suggest tickers already in the list.\n\n"
            "Respond strictly as JSON array: "
            '[{"ticker": "SYMBOL", "reason": "one sentence why"}, ...]'
        )
        try:
            text = self._call(prompt, task_type="medium")
            results = self._parse_json(text)
            if isinstance(results, list):
                return [
                    {"ticker": str(r.get("ticker", "")).upper(), "reason": str(r.get("reason", ""))}
                    for r in results
                    if r.get("ticker")
                ]
        except Exception as e:
            logger.warning("Error getting recommendations: %s", e)
        return []

    def search_tickers(self, query: str) -> List[Dict[str, str]]:
        """
        Search for tickers matching a natural language query.
        Returns [{'ticker': 'AAPL', 'name': 'Apple Inc', 'sector': 'Technology'}, ...]
        """
        prompt = (
            f'The user is searching for stocks matching: "{query}"\n\n'
            "Return up to 10 matching real, actively traded US stock tickers. "
            "If the query is a company name, find its ticker. "
            "If the query is a sector or theme, find relevant stocks.\n\n"
            "Respond strictly as JSON array: "
            '[{"ticker": "SYMBOL", "name": "Company Name", "sector": "Sector"}, ...]'
        )
        try:
            text = self._call(prompt, task_type="medium")
            results = self._parse_json(text)
            if isinstance(results, list):
                return [
                    {
                        "ticker": str(r.get("ticker", "")).upper(),
                        "name": str(r.get("name", "")),
                        "sector": str(r.get("sector", "")),
                    }
                    for r in results
                    if r.get("ticker")
                ]
        except Exception as e:
            logger.warning("Error searching tickers: %s", e)
        return []

    def analyze_portfolio(self, positions: List[Dict[str, Any]], signals_df: Any) -> str:
        """Analyze portfolio and signals."""
        pos_strs = []
        for p in positions:
            ticker = p.get('ticker', 'Unknown')
            upnl = p.get('unrealised_pnl', 0.0)
            pos_strs.append(f"{ticker}: ${upnl:.2f} PnL")
        pos_summary = ", ".join(pos_strs) if pos_strs else "No current positions."

        sig_strs = []
        if signals_df is not None and not signals_df.empty:
            for _, row in signals_df.head(5).iterrows():
                sig_strs.append(f"{row['ticker']} ({row['signal']}, prob={row['prob_up']:.2f})")
        sig_summary = ", ".join(sig_strs) if sig_strs else "No signals available."

        prompt = (
            "You are a helpful AI trading assistant.\n"
            f"Current Portfolio: {pos_summary}\n"
            f"Top Active Signals: {sig_summary}\n\n"
            "Write a concise, 2-3 sentence paragraph analyzing the current state "
            "and providing high-level advice. Keep it punchy and professional."
        )
        try:
            return self._call(prompt, task_type="complex")
        except Exception as e:
            return f"Error generating analysis: {e}"

    def grade_portfolio(
        self,
        positions: List[Dict[str, Any]],
        signals_df: Any,
        consensus_data: Dict[str, Any] | None = None,
        news_data: Dict[str, Any] | None = None,
        regime: str = "unknown",
        live_data: Dict[str, Dict[str, float]] | None = None,
    ) -> str:
        """Colour-grade every watchlist ticker as GREEN/RED/ORANGE.

        Returns raw text that the caller should parse for per-ticker grades.
        Uses the simple model (Haiku) for speed since this runs every pipeline.
        """
        cons_d = consensus_data or {}
        live = live_data or {}
        news = news_data or {}

        ticker_lines: list[str] = []
        if signals_df is not None and hasattr(signals_df, "iterrows"):
            for _, row in signals_df.head(30).iterrows():
                ticker = row.get("ticker", "?")
                signal = row.get("signal", "?")
                prob_up = float(row.get("prob_up", 0.5))

                cons = cons_d.get(ticker)
                if cons:
                    cpct = cons.get("consensus_pct", 0) if isinstance(cons, dict) else getattr(cons, "consensus_pct", 0)
                else:
                    cpct = 50.0

                lv = live.get(ticker, {})
                day_pct = lv.get("change_pct", 0.0)

                nd = news.get(ticker)
                sent = 0.0
                if nd:
                    sent = nd.sentiment if hasattr(nd, "sentiment") else nd.get("sentiment", 0)

                # Is this ticker held?
                held = any(p.get("ticker") == ticker for p in positions)

                ticker_lines.append(
                    f"{ticker}: signal={signal}, prob={prob_up:.2f}, consensus={cpct:.0f}%, "
                    f"day={day_pct:+.1f}%, sentiment={sent:+.2f}, held={'YES' if held else 'NO'}"
                )

        if not ticker_lines:
            return ""

        tickers_block = "\n".join(ticker_lines)

        prompt = (
            f"Market regime: {regime}\n\n"
            f"Tickers:\n{tickers_block}\n\n"
            "Assign GREEN, RED, or ORANGE to EACH ticker above.\n"
            "GREEN = bullish across multiple indicators, hold/buy.\n"
            "RED = bearish across multiple indicators, sell/avoid.\n"
            "ORANGE = mixed signals, uncertain.\n\n"
            "Reply with ONLY the grades, one per line: TICKER: GRADE\n"
            "No explanations, no headers, no markdown."
        )

        try:
            return self._call(prompt, task_type="simple", timeout=30)
        except Exception as e:
            logger.debug("Colour grade call failed: %s", e)
            return ""
