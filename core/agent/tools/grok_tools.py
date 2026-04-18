"""Grok AI tool — query grok.x.ai via headless Chromium (Playwright).

Lets research agents ask Grok questions about X/Twitter sentiment,
trending tickers, and social narrative without needing an X/Twitter
developer API key.

Architecture
------------
``_run_grok_query``   — async browser automation helper. Separated so
                        tests can mock it without launching a real browser.
``query_grok``        — @tool-decorated handler: rate-limits, validates,
                        calls ``_run_grok_query``, handles errors.

Rate limit
----------
Hard cap of ``MAX_GROK_QUERIES_PER_ITER`` (3) Grok calls per agent
iteration, tracked in ``ctx.stats["grok_queries"]``. Grok is a session-
based browser tool — it's expensive in both latency and resource usage,
so we keep the budget tight.

Session persistence
-------------------
Playwright's ``launch_persistent_context`` keeps cookies and localStorage
between runs so Grok stays logged in across iterations. The session path
is read from ``config["swarm"]["grok_session_path"]`` with a fallback of
``data/grok_session``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context

logger = logging.getLogger(__name__)

#: Hard cap on Grok queries per agent iteration.
MAX_GROK_QUERIES_PER_ITER: int = 3

#: Selectors we poll for the response container (in priority order).
_RESPONSE_SELECTORS: tuple[str, ...] = (
    '[class*="response"]',
    '[class*="message"]',
    '[class*="answer"]',
)

#: Input element selector — Grok's compose box may be a textarea or
#: a contenteditable div depending on the version.
_INPUT_SELECTOR: str = 'textarea, [contenteditable="true"], input[type="text"]'


# ── browser automation helper ──────────────────────────────────────────────────

async def _run_grok_query(
    query_text: str,
    session_path: str,
    timeout: float,
) -> str:
    """Drive a headless Chromium session to ask Grok a question.

    Args:
        query_text:   The question to send to Grok.
        session_path: Filesystem path for the persistent browser profile.
        timeout:      Hard wall-clock timeout in seconds.

    Returns:
        The response text extracted from the Grok page.

    Raises:
        RuntimeError:  If Playwright is not installed.
        TimeoutError:  If the response does not stabilise within *timeout* seconds.
    """
    try:
        from playwright.async_api import async_playwright  # lazy import
    except ImportError as exc:
        raise RuntimeError(
            f"playwright is not installed — run: pip install playwright && "
            f"playwright install chromium  ({exc})"
        ) from exc

    os.makedirs(session_path, exist_ok=True)

    async with async_playwright() as pw:
        browser_ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=session_path,
            headless=True,
        )
        try:
            page = browser_ctx.pages[0] if browser_ctx.pages else await browser_ctx.new_page()

            # Navigate with a per-call timeout.
            await asyncio.wait_for(
                page.goto("https://grok.x.ai", wait_until="domcontentloaded"),
                timeout=timeout,
            )

            # Wait for the input box.
            await asyncio.wait_for(
                page.wait_for_selector(_INPUT_SELECTOR),
                timeout=timeout,
            )

            # Type the query and submit.
            input_el = await page.query_selector(_INPUT_SELECTOR)
            if input_el is None:
                raise RuntimeError("Could not locate Grok input element after selector matched")
            await input_el.click()
            await input_el.fill(query_text)
            await input_el.press("Enter")

            # Poll for the response container, then wait until text stabilises.
            deadline = asyncio.get_event_loop().time() + timeout
            response_text = ""

            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)

                # Try each response selector in order.
                candidates: list[str] = []
                for selector in _RESPONSE_SELECTORS:
                    els = await page.query_selector_all(selector)
                    for el in els:
                        text = (await el.inner_text()) or ""
                        text = text.strip()
                        if text:
                            candidates.append(text)

                # Fallback: pick the longest text block among the last 20 elements.
                if not candidates:
                    all_els = await page.query_selector_all("*")
                    tail = all_els[-20:] if len(all_els) > 20 else all_els
                    for el in tail:
                        try:
                            text = (await el.inner_text()) or ""
                            text = text.strip()
                            if text:
                                candidates.append(text)
                        except Exception:
                            pass

                if candidates:
                    current_text = max(candidates, key=len)
                else:
                    current_text = ""

                if current_text and current_text == response_text:
                    # Text has not changed — run 4 stable checks (4 × 0.5 s = 2 s).
                    stable_count = 0
                    while stable_count < 4 and asyncio.get_event_loop().time() < deadline:
                        await asyncio.sleep(0.5)
                        rechecked: list[str] = []
                        for selector in _RESPONSE_SELECTORS:
                            els = await page.query_selector_all(selector)
                            for el in els:
                                t = (await el.inner_text()) or ""
                                t = t.strip()
                                if t:
                                    rechecked.append(t)
                        if not rechecked:
                            all_els = await page.query_selector_all("*")
                            tail = all_els[-20:] if len(all_els) > 20 else all_els
                            for el in tail:
                                try:
                                    t = (await el.inner_text()) or ""
                                    t = t.strip()
                                    if t:
                                        rechecked.append(t)
                                except Exception:
                                    pass
                        new_text = max(rechecked, key=len) if rechecked else ""
                        if new_text == current_text:
                            stable_count += 1
                        else:
                            # Text changed again — reset and keep polling.
                            response_text = new_text
                            stable_count = 0
                            break
                    else:
                        if stable_count >= 4:
                            return current_text
                else:
                    response_text = current_text

            raise TimeoutError(
                f"Grok did not return a stable response within {timeout:.0f}s"
            )
        finally:
            await browser_ctx.close()


# ── tool handler ───────────────────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "query_grok",
    "Ask Grok AI (grok.x.ai) a question about X/Twitter trends, social "
    "sentiment, or what people are saying about a ticker. Uses a persistent "
    "headless browser session — login is required once via the session path. "
    "Rate limited to 3 calls per iteration. Timeout is clamped to 10–120 s "
    "(default 60 s).",
    {"query": str, "timeout_seconds": int},
)
async def query_grok(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    # ── rate limit ─────────────────────────────────────────────────────────
    used = int(ctx.stats.get("grok_queries", 0))
    if used >= MAX_GROK_QUERIES_PER_ITER:
        return _text_result({
            "status": "rate_limited",
            "error": (
                f"query_grok rate limit reached "
                f"({used}/{MAX_GROK_QUERIES_PER_ITER} per iteration). "
                f"Call end_iteration and continue next wake-up."
            ),
            "queries_used": used,
            "queries_remaining": 0,
        })

    # ── validate ───────────────────────────────────────────────────────────
    q = str(args.get("query") or "").strip()
    if not q:
        return _text_result({"status": "error", "error": "query must not be empty"})

    # ── timeout ────────────────────────────────────────────────────────────
    try:
        timeout = float(args.get("timeout_seconds") or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = max(10.0, min(120.0, timeout))

    # ── session path ───────────────────────────────────────────────────────
    session_path: str = (
        ctx.config.get("swarm", {}).get("grok_session_path")
        or "data/grok_session"
    )

    # Count the attempt before the call so errors still burn budget.
    ctx.stats["grok_queries"] = used + 1
    new_used = used + 1
    remaining = max(0, MAX_GROK_QUERIES_PER_ITER - new_used)

    # ── execute ────────────────────────────────────────────────────────────
    try:
        response_text = await _run_grok_query(
            query_text=q,
            session_path=session_path,
            timeout=timeout,
        )
    except TimeoutError as exc:
        logger.warning("query_grok timed out for query %r: %s", q[:80], exc)
        return _text_result({
            "status": "error",
            "error": f"query_grok timed out after {timeout:.0f}s — try a shorter query or increase timeout_seconds",
            "query": q,
            "queries_used": new_used,
            "queries_remaining": remaining,
        })
    except Exception as exc:
        logger.warning("query_grok failed for query %r: %s", q[:80], exc)
        return _text_result({
            "status": "error",
            "error": f"query_grok failed: {exc}",
            "query": q,
            "queries_used": new_used,
            "queries_remaining": remaining,
        })

    return _text_result({
        "status": "ok",
        "response": response_text,
        "source": "grok_x",
        "query": q,
        "queries_used": new_used,
        "queries_remaining": remaining,
    })


GROK_TOOLS = [query_grok]
