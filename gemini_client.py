from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List

from google import genai
from google.genai import types


@dataclass
class GeminiConfig:
    model: str = "gemini-2.5-flash"
    api_key_env: str = "GEMINI_API_KEY"


class GeminiClient:
    """
    Wrapper around the Google Gemini API for signal generation, news analysis,
    portfolio analysis, and interactive chat.
    """

    SYSTEM_INSTRUCTION = (
        "You are an expert AI stock trading assistant integrated into a Bloomberg-style "
        "trading terminal. You specialize in US equities and have deep knowledge of "
        "technical analysis, fundamental analysis, market sentiment, and macroeconomic trends.\n\n"
        "RULES:\n"
        "1. Always respond in the exact format requested (JSON, plain text, etc.)\n"
        "2. When suggesting tickers, only suggest real, actively traded US stock tickers\n"
        "3. Base recommendations on technical indicators, recent price action, and news sentiment\n"
        "4. Be concise and actionable - traders need fast, clear information\n"
        "5. Always include confidence levels and risk disclaimers when giving trade advice\n"
        "6. When analyzing, consider: RSI, moving averages, volume, volatility, and sector trends"
    )

    def __init__(self, config: GeminiConfig | None = None) -> None:
        if config is None:
            config = GeminiConfig()
        self.config = config

        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{self.config.api_key_env} is not set. "
                "Export your Gemini API key in the environment before running the app."
            )

        self._client = genai.Client(api_key=api_key)

    def _call(self, prompt: str, use_system: bool = True) -> str:
        """Helper to make a Gemini API call with system instructions and fallback."""
        full_prompt = f"{self.SYSTEM_INSTRUCTION}\n\n{prompt}" if use_system else prompt
        
        # Priority 1: User's requested model
        # Priority 2: Gemini 2.5 Pro (Most Advanced)
        # Priority 3: Gemini 2.5 Flash (Fast/Cheap)
        # Priority 4: Gemini 1.5 Pro (Legacy Stable)
        models_to_try = [self.config.model, "gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"]
        # Remove duplicates while preserving order
        models_to_try = [m for m in dict.fromkeys(models_to_try) if m]
        
        # Pruning system: skip models that we already know don't exist
        if not hasattr(self, "_invalid_models"):
            self._invalid_models = set()
        
        models_to_try = [m for m in models_to_try if m not in self._invalid_models]

        last_err = None
        for m in models_to_try:
            try:
                resp = self._client.models.generate_content(
                    model=m,
                    contents=full_prompt,
                )
                if resp.text:
                    return resp.text.strip()
            except Exception as e:
                last_err = e
                err_str = str(e).upper()
                # If error 429 (Resource Exhausted), shift to next model immediately
                if "429" in err_str or "RESOURCE EXHAUSTED" in err_str:
                    print(f"[gemini_client] Resource exhausted on {m}. Auto-shifting to next available model...")
                # If error 404 (Not Found), mark model as invalid for this session
                elif "404" in err_str or "NOT FOUND" in err_str or "NOT_FOUND" in err_str:
                    print(f"[gemini_client] Model {m} not found. Blacklisting for this session.")
                    self._invalid_models.add(m)
                continue
        
        if last_err:
            print(f"[gemini_client] All models failed. Last error: {last_err}")
        return ""

    def _parse_json(self, text: str) -> Dict:
        """Parse JSON from Gemini response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        
        if text.endswith("```"):
            text = text[:-3]
        
        # Sometimes Gemini adds text after the JSOn block, find the first '{' and last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]
            
        return json.loads(text.strip())

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
        Ask Gemini for a probability that tomorrow's close will be higher,
        plus a short explanation. Returns { 'p_up_gemini': float, 'reason': str }.
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
            text = self._call(prompt)
            if not text:
                raise ValueError("Empty response from AI")
            obj = self._parse_json(text)
            p_up = float(obj.get("p_up", 0.5))
            reason = str(obj.get("reason", "No explanation provided."))
        except Exception as e:
            print(f"[gemini_client] Signal error for {ticker}: {e}")
            p_up = 0.5
            reason = f"AI Error: {e}"

        p_up = max(0.0, min(1.0, p_up))
        return {"p_up_gemini": p_up, "reason": reason}

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
            "Respond strictly as JSON: {\"sentiment\": float, \"summary\": string}"
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
            text = self._call(prompt)
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
    ) -> str:
        """
        Multi-context chat: builds a system prompt with all terminal data
        and responds to the user's question.
        """
        # Build context
        pos_lines = []
        for p in positions:
            t = p.get("ticker", "?")
            q = p.get("quantity", 0)
            pnl = p.get("unrealised_pnl", 0.0)
            pos_lines.append(f"  {t}: {q} shares, PnL=${pnl:.2f}")
        pos_text = "\n".join(pos_lines) if pos_lines else "  No open positions"

        sig_lines = []
        if signals is not None and hasattr(signals, 'iterrows'):
            for _, row in signals.head(15).iterrows():
                ticker = row.get('ticker', '?')
                prob = row.get('prob_up', 0)
                signal = row.get('signal', '?')
                ai_rec = row.get('ai_rec', '')
                p_sk = row.get('p_up_sklearn', 0)
                p_gm = row.get('p_up_gemini', 0)
                p_fin = row.get('p_up_final', 0)
                reason = row.get('reason', '')
                line = (
                    f"  {ticker}: signal={signal}, ai_rec={ai_rec}, "
                    f"prob_final={p_fin:.2f} (sklearn={p_sk:.2f}, gemini={p_gm:.2f})"
                )
                if reason and reason != "No reason provided.":
                    line += f"\n    Reason: {reason[:120]}"
                sig_lines.append(line)
        sig_text = "\n".join(sig_lines) if sig_lines else "  No signals available"

        news_lines = []
        for ticker, nd in news_data.items():
            if hasattr(nd, 'sentiment'):
                news_lines.append(f"  {ticker}: sentiment={nd.sentiment:.2f} – {nd.summary}")
            elif isinstance(nd, dict):
                news_lines.append(f"  {ticker}: sentiment={nd.get('sentiment', 0):.2f}")
        news_text = "\n".join(news_lines) if news_lines else "  No news data"

        acct = account_info or {}
        acct_text = (
            f"  Balance: ${acct.get('free', 0):.2f}\n"
            f"  Invested: ${acct.get('invested', 0):.2f}\n"
            f"  Total: ${acct.get('total', 0):.2f}"
        )

        system_context = (
            "You are an AI trading assistant embedded in a stock trading terminal. "
            "You have access to the following real-time data:\n\n"
            f"ACCOUNT:\n{acct_text}\n\n"
            f"OPEN POSITIONS:\n{pos_text}\n\n"
            f"ACTIVE SIGNALS:\n{sig_text}\n\n"
            f"NEWS SENTIMENT:\n{news_text}\n\n"
            "Answer the user's question helpfully. If they ask about a trade, "
            "give specific actionable advice with reasoning. Be concise and professional."
        )

        prompt = f"{system_context}\n\nUser: {user_message}\nAssistant:"
        try:
            return self._call(prompt)
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
            text = self._call(prompt).upper().strip()
            # Clean up any extra text
            text = text.split()[0] if text else ""
            if text and len(text) <= 5 and text.isalpha():
                return text
        except Exception as e:
            print(f"Error getting ticker suggestion: {e}")
        return ""

    def recommend_tickers(
        self,
        current_tickers: List[str],
        category: str = "",
        count: int = 5,
    ) -> List[Dict[str, str]]:
        """
        Ask Gemini to recommend multiple tickers with reasoning.
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
            text = self._call(prompt)
            results = self._parse_json(text)
            if isinstance(results, list):
                return [
                    {"ticker": str(r.get("ticker", "")).upper(), "reason": str(r.get("reason", ""))}
                    for r in results
                    if r.get("ticker")
                ]
        except Exception as e:
            print(f"Error getting recommendations: {e}")
        return []

    def search_tickers(self, query: str) -> List[Dict[str, str]]:
        """
        Search for tickers matching a natural language query.
        Returns [{'ticker': 'AAPL', 'name': 'Apple Inc', 'sector': 'Technology'}, ...]
        """
        prompt = (
            f"The user is searching for stocks matching: \"{query}\"\n\n"
            "Return up to 10 matching real, actively traded US stock tickers. "
            "If the query is a company name, find its ticker. "
            "If the query is a sector or theme, find relevant stocks.\n\n"
            "Respond strictly as JSON array: "
            '[{"ticker": "SYMBOL", "name": "Company Name", "sector": "Sector"}, ...]'
        )
        try:
            text = self._call(prompt)
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
            print(f"Error searching tickers: {e}")
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
            return self._call(prompt)
        except Exception as e:
            return f"Error generating analysis: {e}"
