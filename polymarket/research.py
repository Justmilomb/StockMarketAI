"""Research agent swarm for Polymarket probability estimation.

Dispatches multiple specialist Claude calls — each covering ALL events
in a single batched prompt — to gather diverse evidence and probability
estimates.  Four specialist agents run sequentially (one Claude call each):

1. News & Sentiment Analyst  — recent events, public opinion, media trends
2. Data Scientist            — base rates, polling, historical precedents
3. Domain Expert             — category-specific deep analysis
4. Contrarian                — market biases, overreaction, favourite-longshot

Each returns a per-event probability + reasoning.  The combined output
feeds into MiroFish Monte Carlo for final aggregation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from polymarket.types import PolymarketEvent

logger = logging.getLogger(__name__)


@dataclass
class AgentEstimate:
    """One specialist agent's probability estimate for one event."""

    agent_type: str
    probability: float      # [0.0, 1.0]
    confidence: float        # [0.0, 1.0]
    reasoning: str


@dataclass
class ResearchBrief:
    """Aggregated research output for a single event."""

    condition_id: str
    question: str
    estimates: List[AgentEstimate] = field(default_factory=list)

    @property
    def mean_probability(self) -> float:
        if not self.estimates:
            return 0.5
        return sum(e.probability for e in self.estimates) / len(self.estimates)

    @property
    def mean_confidence(self) -> float:
        if not self.estimates:
            return 0.0
        return sum(e.confidence for e in self.estimates) / len(self.estimates)


# ── Agent prompt templates ───────────────────────────────────────────

_AGENT_PROMPTS: Dict[str, str] = {
    "news_sentiment": (
        "You are a NEWS & SENTIMENT ANALYST specialising in prediction markets.\n\n"
        "For each event below, estimate the true probability based on:\n"
        "- Recent news and current events (what has happened that affects this?)\n"
        "- Public sentiment and social media trends\n"
        "- Media narrative direction (is coverage shifting?)\n"
        "- Breaking developments that the market may not have priced in yet\n\n"
        "Focus on INFORMATION ADVANTAGE — what do you know that the average "
        "market participant might be underweighting?\n\n"
    ),
    "data_scientist": (
        "You are a DATA SCIENTIST specialising in prediction-market calibration.\n\n"
        "For each event below, estimate the true probability based on:\n"
        "- Historical base rates for similar events\n"
        "- Available polling data, surveys, or statistical models\n"
        "- Reference class forecasting (how often do events like this happen?)\n"
        "- Bayesian updating from prior evidence\n\n"
        "Focus on QUANTITATIVE REASONING — use numbers, base rates, and "
        "statistical evidence over narratives.\n\n"
    ),
    "domain_expert": (
        "You are a DOMAIN EXPERT across politics, crypto, sports, science, and culture.\n\n"
        "For each event below, estimate the true probability based on:\n"
        "- Deep domain knowledge specific to the event's category\n"
        "- Insider-level understanding of the mechanisms that determine outcomes\n"
        "- Expert consensus in the relevant field\n"
        "- Technical/structural factors the general public often misses\n\n"
        "Focus on EXPERTISE — what does a true specialist in this area know "
        "that a generalist would miss?\n\n"
    ),
    "contrarian": (
        "You are a CONTRARIAN ANALYST who hunts for market inefficiencies.\n\n"
        "For each event below, estimate the true probability by looking for:\n"
        "- Favourite-longshot bias (markets overvalue high-probability outcomes)\n"
        "- Recency bias (recent news overweighted vs base rates)\n"
        "- Narrative bias (compelling stories priced above fundamentals)\n"
        "- Anchoring (market stuck near initial price despite new evidence)\n"
        "- Thin-market inefficiency (low liquidity = slow price discovery)\n\n"
        "Focus on WHERE THE MARKET IS WRONG — your job is to find the mispricing, "
        "not confirm the market's view.\n\n"
    ),
}

_RESPONSE_INSTRUCTION = (
    "Respond ONLY as a JSON array, one object per market:\n"
    '[{"id": 1, "probability": 0.72, "confidence": 0.6, "reasoning": "brief reason"}, ...]\n'
    "Rules:\n"
    "- probability: your estimate of P(YES) between 0.01 and 0.99\n"
    "- confidence: how confident you are in your estimate (0.0 = guessing, 1.0 = certain)\n"
    "- reasoning: one sentence explaining your key insight\n"
    "- EVERY market must have an entry. No other text."
)


class ResearchSwarm:
    """Dispatches specialist Claude agents to research prediction markets.

    Each agent type makes one batched Claude call covering all events.
    Results are returned as ResearchBriefs for downstream aggregation.
    """

    def __init__(
        self,
        agent_types: List[str] | None = None,
        task_type: str = "medium",
    ) -> None:
        self._agent_types = agent_types or list(_AGENT_PROMPTS.keys())
        self._task_type = task_type

    def research(
        self,
        events: List[PolymarketEvent],
        claude_client: object,
        on_progress: Optional[callable] = None,
    ) -> List[ResearchBrief]:
        """Run all specialist agents and return briefs per event.

        Args:
            events: Prediction market events to research.
            claude_client: ClaudeClient instance for Claude CLI calls.
            on_progress: Optional callback(done, total, detail).

        Returns:
            List of ResearchBrief, one per event, containing all agent estimates.
        """
        # Initialise briefs
        briefs: Dict[str, ResearchBrief] = {}
        for event in events:
            briefs[event.condition_id] = ResearchBrief(
                condition_id=event.condition_id,
                question=event.question,
            )

        total_agents = len(self._agent_types)
        for i, agent_type in enumerate(self._agent_types):
            if on_progress:
                on_progress(i, total_agents, agent_type)

            prompt_prefix = _AGENT_PROMPTS.get(agent_type)
            if not prompt_prefix:
                logger.warning("Unknown agent type: %s", agent_type)
                continue

            estimates = self._run_agent(
                agent_type, prompt_prefix, events, claude_client,
            )

            # Merge estimates into briefs
            for event, estimate in zip(events, estimates):
                if estimate is not None:
                    briefs[event.condition_id].estimates.append(estimate)

            logger.info(
                "Agent '%s' completed: %d/%d estimates returned",
                agent_type,
                sum(1 for e in estimates if e is not None),
                len(events),
            )

        if on_progress:
            on_progress(total_agents, total_agents, "done")

        return [briefs[e.condition_id] for e in events]

    def _run_agent(
        self,
        agent_type: str,
        prompt_prefix: str,
        events: List[PolymarketEvent],
        claude_client: object,
    ) -> List[Optional[AgentEstimate]]:
        """Run one specialist agent across all events (single Claude call)."""
        # Build event list for the prompt
        event_lines: List[str] = []
        for i, event in enumerate(events, 1):
            end_str = event.end_date.strftime("%Y-%m-%d") if event.end_date else "unknown"
            event_lines.append(
                f'{i}. "{event.question}"\n'
                f'   Market price (YES): {event.market_probability:.2f} | '
                f'Category: {event.category} | '
                f'Resolves: {end_str} | '
                f'Volume 24h: ${event.volume_24h:,.0f} | '
                f'Liquidity: ${event.liquidity:,.0f} | '
                f'Traders: {event.num_traders:,}'
            )

        prompt = (
            prompt_prefix
            + "MARKETS TO ANALYSE:\n\n"
            + "\n\n".join(event_lines)
            + "\n\n"
            + _RESPONSE_INSTRUCTION
        )

        try:
            response = claude_client._call(
                prompt, use_system=False, task_type=self._task_type,
            )
            if not response:
                return [None] * len(events)
            return self._parse_response(response, agent_type, len(events))
        except Exception as e:
            logger.warning("Agent '%s' failed: %s", agent_type, e)
            return [None] * len(events)

    def _parse_response(
        self,
        response: str,
        agent_type: str,
        expected_count: int,
    ) -> List[Optional[AgentEstimate]]:
        """Parse one agent's JSON response into AgentEstimate objects."""
        text = response.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Agent '%s': no JSON array in response", agent_type)
            return [None] * expected_count

        try:
            items = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning("Agent '%s': JSON parse error: %s", agent_type, e)
            return [None] * expected_count

        # Build id-indexed map
        estimate_map: Dict[int, AgentEstimate] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = int(item.get("id", 0))
            prob = float(item.get("probability", -1))
            conf = float(item.get("confidence", 0.3))
            reasoning = str(item.get("reasoning", ""))

            if not (0.0 <= prob <= 1.0):
                continue
            conf = max(0.0, min(1.0, conf))

            estimate_map[item_id] = AgentEstimate(
                agent_type=agent_type,
                probability=prob,
                confidence=conf,
                reasoning=reasoning,
            )

        result: List[Optional[AgentEstimate]] = []
        for i in range(1, expected_count + 1):
            result.append(estimate_map.get(i))

        return result
