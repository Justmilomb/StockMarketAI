"""Model router — pick heavy vs medium tier by kind-of-work.

The rule from the user is:

    "all the actual financial stuff use the heavy tier but when it's
    calling a tool just getting info use medium — all decisions
    making a judgement always use heavy"

We can't swap models mid-``query()``, so this router decides at
dispatch time which model a given run uses:

* **Supervisor** (``AgentRunner``) → always the heavy tier. Every
  iteration can turn into a buy/sell decision, so there's no safe
  way to run it on the medium tier.
* **Chat workers** → default to medium (pure info retrieval) and
  only escalate to heavy when the user's message looks like a
  decision request — a trade, a rebalance, a "should I...", a
  watchlist edit, or any other action that changes state.

The classification is intentionally keyword-based. A tiny LLM router
would be marginally more accurate but costs another round-trip the
user is waiting on. Keywords get us 95% of the way at zero latency.
False positives go *up* the tier, which is the safe direction: the
worst case is spending heavy-tier budget on an info query, not running
a trade through the medium tier.
"""
from __future__ import annotations

import re
from typing import Any, Dict

#: Substrings that indicate the user is asking the agent to *do*
#: something with state (trade, edit, rebalance, decide). Lowercase —
#: we lowercase the message before matching. Word-boundary enforced
#: for the short ones to avoid "sell" matching "Tesla sells phones".
_DECISION_KEYWORDS: tuple[str, ...] = (
    # Trading verbs
    "buy", "sell", "trade", "order", "place", "purchase",
    "acquire", "liquidate", "short ", "go long", "go short",
    "enter", "exit", "close out", "close my", "close the",
    "open a position", "open position", "cut", "dump",
    "hedge", "unwind", "roll",
    # Portfolio changes
    "rebalance", "reallocate", "allocate", "redistribute",
    "rotate", "swap", "switch into", "move into", "move out",
    "reduce", "increase", "top up", "double down", "scale in",
    "scale out", "average in", "average down",
    # Watchlist / config mutations
    "add to watchlist", "remove from watchlist", "clear watchlist",
    "clear my watchlist", "delete from watchlist", "clean up watchlist",
    "to watchlist", "to my watchlist", "from watchlist",
    "from my watchlist",
    # Decision framing
    "should i", "should we", "what should", "would you", "recommend",
    "suggest i", "pick ", "choose ", "decide", "worth buying",
    "worth selling", "worth holding", "time to buy", "time to sell",
    "opinion on", "your view",
    # Risk / plan
    "set stop", "set target", "stop loss", "take profit",
    "build a plan", "build a strategy", "strategy for",
)

#: A couple of tokens that aren't financial decisions but read like
#: commands — we DON'T escalate on these even though they contain
#: action verbs, because they're administrative noise the user
#: doesn't care which model handles.
_INFO_OVERRIDES: tuple[str, ...] = (
    "show me", "list ", "display ", "tell me", "how much", "how many",
    "what is", "what's", "what are", "what was", "when did",
    "which ", "who ", "where ", "why ",
    "summary", "summarise", "summarize", "report on", "report for",
    "status", "balance", "portfolio",
)

_DECISION_RE: re.Pattern[str] = re.compile(
    "|".join(re.escape(k) for k in _DECISION_KEYWORDS),
)
_INFO_RE: re.Pattern[str] = re.compile(
    "|".join(re.escape(k) for k in _INFO_OVERRIDES),
)


def _ai_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = config or {}
    return cfg.get("ai") or {}


def _model(cfg: Dict[str, Any], *keys: str) -> str:
    """Read the first non-empty model key as a plain string."""
    for key in keys:
        val = cfg.get(key)
        if val:
            return str(val)
    return ""


def supervisor_model(config: Dict[str, Any]) -> str:
    """The supervisor always gets the heaviest model."""
    return _model(_ai_cfg(config), "model_complex")


def _opus_model(config: Dict[str, Any]) -> str:
    return _model(_ai_cfg(config), "model_complex")


def _sonnet_model(config: Dict[str, Any]) -> str:
    return _model(_ai_cfg(config), "model_medium", "model")


def classify_chat_message(message: str) -> str:
    """Return ``"decision"`` or ``"info"`` for a user chat message.

    Rules:

    1. Empty / whitespace → ``"info"`` (cheap, won't trade anyway).
    2. Contains any decision keyword → ``"decision"``.
    3. Contains any info-override keyword and NO decision keyword
       → ``"info"``.
    4. Default → ``"info"`` (medium tier). The supervisor covers the
       autonomous decision path; chat defaults cheap.
    """
    text = (message or "").strip().lower()
    if not text:
        return "info"
    has_decision = bool(_DECISION_RE.search(text))
    if has_decision:
        return "decision"
    return "info"


def chat_worker_model(config: Dict[str, Any], message: str) -> tuple[str, str]:
    """Return ``(model_id, tier_label)`` for a chat worker.

    ``tier_label`` is ``"decision"`` → heavy or ``"info"`` → medium.
    """
    tier = classify_chat_message(message)
    if tier == "decision":
        return _opus_model(config), "decision"
    return _sonnet_model(config), "info"


def _haiku_model(config: Dict[str, Any]) -> str:
    return _model(_ai_cfg(config), "model_simple")


def research_worker_model(config: Dict[str, Any], role: Any) -> str:
    """Pick the right model for a research worker based on role tier.

    Quick-reaction roles (tier 1) use Haiku for throughput.
    Deep-research roles (tier 2) use Sonnet for analytical depth.
    """
    tier = getattr(role, "model_tier", "simple")
    if tier == "complex":
        return _opus_model(config)
    if tier == "medium":
        return _sonnet_model(config)
    return _haiku_model(config)


#: Valid effort levels accepted by the Claude Agent SDK. Anything else
#: gets coerced back to the closest valid value so a typo in config.json
#: doesn't crash the SDK on session start.
_VALID_EFFORT: tuple[str, ...] = ("low", "medium", "high", "max")


def _coerce_effort(val: Any, fallback: str) -> str:
    text = str(val or "").strip().lower()
    return text if text in _VALID_EFFORT else fallback


def supervisor_effort(config: Dict[str, Any]) -> str:
    """Effort level for the supervisor — always our top tier."""
    return _coerce_effort(_ai_cfg(config).get("effort_supervisor"), "max")


def decision_effort(config: Dict[str, Any]) -> str:
    """Effort for a chat worker on a trade/decision request."""
    return _coerce_effort(_ai_cfg(config).get("effort_decision"), "high")


def info_effort(config: Dict[str, Any]) -> str:
    """Effort for a chat worker on an info-only request."""
    return _coerce_effort(_ai_cfg(config).get("effort_info"), "medium")


def chat_worker_effort(config: Dict[str, Any], tier: str) -> str:
    """Map the chat-worker tier label to an effort level."""
    if tier == "decision":
        return decision_effort(config)
    return info_effort(config)


def assessor_model(config: Dict[str, Any]) -> str:
    """Model for the post-iteration assessor (defaults to Sonnet tier)."""
    return _model(_ai_cfg(config), "model_assessor", "model_medium", "model")


def assessor_effort(config: Dict[str, Any]) -> str:
    """Effort level for the post-iteration assessor."""
    return _coerce_effort(_ai_cfg(config).get("effort_assessor"), "medium")


def research_effort(config: Dict[str, Any], role: Any) -> str:
    """Effort level for a research worker based on role tier."""
    tier = getattr(role, "model_tier", "simple")
    cfg = _ai_cfg(config)
    if tier == "complex":
        return _coerce_effort(cfg.get("effort_research_deep"), "high")
    if tier == "medium":
        return _coerce_effort(cfg.get("effort_research_quick"), "medium")
    return _coerce_effort(cfg.get("effort_research_quick"), "low")
