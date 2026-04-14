"""Tests for core.agent.tools.browser_tools.fetch_page.

These tests exercise every guard rail in the fetch_page tool without
touching the network. The happy path uses a stubbed urlopen so the
tests run in any CI or offline environment.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from broker_service import BrokerService
from database import HistoryManager
from risk_manager import RiskManager

from core.agent.context import (
    clear_agent_context,
    get_agent_context,
    init_agent_context,
)
from core.agent.tools.browser_tools import (
    MAX_FETCHES_PER_ITER,
    fetch_page,
)


# ─── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def agent_ctx(tmp_path: Path):
    """Initialise a throwaway AgentContext backed by an in-tmp sqlite DB."""
    db_path = str(tmp_path / "browser_test.db")
    config: Dict[str, Any] = {
        "broker": {"type": "log"},
        "agent": {"paper_mode": True},
        "database": {"path": db_path},
    }
    db = HistoryManager(db_path)
    broker = BrokerService(config=config)
    risk = RiskManager(config=config)
    ctx = init_agent_context(
        config=config,
        broker_service=broker,
        db=db,
        risk_manager=risk,
        iteration_id=f"test-{uuid.uuid4().hex[:8]}",
        paper_mode=True,
    )
    yield ctx
    clear_agent_context()


def _call(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run fetch_page.handler synchronously and return the unwrapped payload."""
    result = asyncio.run(fetch_page.handler(args))
    return json.loads(result["content"][0]["text"])


class _StubResponse:
    """Minimal urlopen response stand-in for monkeypatched tests."""

    def __init__(self, body: bytes, headers: Dict[str, str], status: int = 200) -> None:
        self._buf = BytesIO(body)
        self.headers = headers
        self.status = status

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size) if size and size > 0 else self._buf.read()

    def __enter__(self) -> "_StubResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        self._buf.close()


# ─── guard rails — no network ────────────────────────────────────────────

class TestGuardRails:
    def test_empty_url_rejected(self, agent_ctx) -> None:
        payload = _call({"url": ""})
        assert payload["error"] == "url is required"

    def test_non_http_scheme_rejected(self, agent_ctx) -> None:
        payload = _call({"url": "ftp://example.com/"})
        assert "unsupported scheme" in payload["error"]

    def test_localhost_blocked(self, agent_ctx) -> None:
        payload = _call({"url": "http://localhost:8080/"})
        assert payload["error"] == "blocked: localhost"

    def test_private_ip_blocked(self, agent_ctx) -> None:
        payload = _call({"url": "http://192.168.1.1/"})
        assert "blocked: private address" in payload["error"]

    def test_loopback_ip_blocked(self, agent_ctx) -> None:
        payload = _call({"url": "http://127.0.0.1/"})
        assert "blocked: private address" in payload["error"]

    def test_rate_limit_stops_fetches(self, agent_ctx) -> None:
        get_agent_context().stats["browser_fetches"] = MAX_FETCHES_PER_ITER
        payload = _call({"url": "https://example.com/"})
        assert "rate limit reached" in payload["error"]


# ─── happy path — stubbed urlopen ────────────────────────────────────────

class TestHappyPath:
    def test_extracts_article_text(self, agent_ctx) -> None:
        html = (
            b"<html><head><title>Earnings beat</title></head>"
            b"<body><article><h1>Earnings beat</h1>"
            b"<p>Revenue grew 14% on cloud strength.</p></article>"
            b"<script>tracker();</script></body></html>"
        )
        stub = _StubResponse(html, {"Content-Type": "text/html; charset=utf-8"})
        with patch("core.agent.tools.browser_tools.urlopen", return_value=stub):
            payload = _call({"url": "https://news.example.com/story", "max_chars": 500})

        assert payload["status"] == 200
        assert payload["title"] == "Earnings beat"
        assert "Revenue grew 14%" in payload["text"]
        assert "tracker" not in payload["text"], "script content must be stripped"
        assert payload["fetch_count"] == 1
        assert payload["fetches_remaining"] == MAX_FETCHES_PER_ITER - 1
        assert payload["truncated"] is False

    def test_truncates_to_max_chars(self, agent_ctx) -> None:
        big = b"<html><body><article>" + (b"word " * 5000) + b"</article></body></html>"
        stub = _StubResponse(big, {"Content-Type": "text/html"})
        with patch("core.agent.tools.browser_tools.urlopen", return_value=stub):
            payload = _call({"url": "https://big.example.com/", "max_chars": 500})

        assert payload["truncated"] is True
        assert len(payload["text"]) <= 510  # max_chars + ellipsis slack

    def test_rejects_unsupported_content_type(self, agent_ctx) -> None:
        stub = _StubResponse(b"binary garbage", {"Content-Type": "application/octet-stream"})
        with patch("core.agent.tools.browser_tools.urlopen", return_value=stub):
            payload = _call({"url": "https://bin.example.com/"})

        assert "unsupported content-type" in payload["error"]


# ─── journal write ───────────────────────────────────────────────────────

class TestJournal:
    def test_success_writes_journal_row(self, agent_ctx, tmp_path: Path) -> None:
        html = b"<html><body><article><p>hi</p></article></body></html>"
        stub = _StubResponse(html, {"Content-Type": "text/html"})
        with patch("core.agent.tools.browser_tools.urlopen", return_value=stub):
            _call({"url": "https://example.com/", "max_chars": 100})

        import sqlite3
        with sqlite3.connect(str(agent_ctx.db.db_path)) as conn:
            rows = list(conn.execute(
                "SELECT kind, tool, tags FROM agent_journal "
                "WHERE iteration_id = ?", (agent_ctx.iteration_id,),
            ))
        assert rows == [("browser_fetch", "fetch_page", "browser")]
