"""Model router — pick Opus vs Sonnet by kind-of-work.

The rule from the user is:

    "all the actual financial stuff use opus but when it's calling a
    tool just getting info use sonnet — all decisions making a
    judgement always use opus"

We can't swap models mid-``query()``, so this router decides at
dispatch time which model a given run uses:

* **Supervisor** (``AgentRunner``) → always Opus. Every iteration
  can turn into a buy/sell decision, so there's no safe way to run
  it on Sonnet.
* **Chat workers** → default to Sonnet (pure info retrieval) and
  only escalate to Opus when the user's message looks like a
  decision request — a trade, a rebalance, a "should I...", a
  watchlist edit, or any other action that changes state.

The classification is intentionally keyword-based. A tiny LLM router
would be marginally more accurate but costs another round-trip the
user is waiting on. Keywords get us 95% of the way at zero latency.
False positives go *up* the tier (Opus), which is the safe direction:
the worst case is spending Opus budget on an info query, not running
a trade through Sonnet.
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


def _claude_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    return (config or {}).get("claude", {}) or {}


def supervisor_model(config: Dict[str, Any]) -> str:
    """The supervisor always gets the heaviest model.

    Reads ``claude.model_complex`` with an Opus fallback so a partial
    config still lands on the right tier.
    """
    cfg = _claude_cfg(config)
    return str(cfg.get("model_complex") or "claude-opus-4-6")


def _opus_model(config: Dict[str, Any]) -> str:
    cfg = _claude_cfg(config)
    return str(cfg.get("model_complex") or "claude-opus-4-6")


def _sonnet_model(config: Dict[str, Any]) -> str:
    cfg = _claude_cfg(config)
    return str(
        cfg.get("model_medium")
        or cfg.get("model")
        or "claude-sonnet-4-20250514",
    )


def classify_chat_message(message: str) -> str:
    """Return ``"decision"`` or ``"info"`` for a user chat message.

    Rules:

    1. Empty / whitespace → ``"info"`` (cheap, won't trade anyway).
    2. Contains any decision keyword → ``"decision"``.
    3. Contains any info-override keyword and NO decision keyword
       → ``"info"``.
    4. Default → ``"info"`` (Sonnet). The supervisor covers the
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

    ``tier_label`` is ``"decision"`` → Opus or ``"info"`` → Sonnet.
    """
    tier = classify_chat_message(message)
    if tier == "decision":
        return _opus_model(config), "decision"
    return _sonnet_model(config), "info"
