"""Telemetry collection pipeline for the blank desktop app.

Every session's anonymised events (scraped items, agent iterations,
chat turns, trade fills, forecasts, errors, personality lessons) are
written to a local SQLite store and batch-shipped to the blank server
once a day for model-training. Nothing about the user's identity,
credentials or T212 account is sent — only a stable hashed install ID
so we can stitch one machine's history together server-side.

Public API:

    from core import telemetry

    telemetry.init(config, user_data_dir, licence_key)
    telemetry.emit("scraper_item", {"source": "bbc", ...})
    telemetry.flush()    # force an upload cycle
    telemetry.close()    # called at graceful shutdown

When the user disables telemetry in ``config.json`` the ``emit`` calls
become no-ops and no uploader thread is started. Callers never need to
check ``is_enabled()`` first.
"""
from __future__ import annotations

from core.telemetry.collector import (
    TelemetryCollector,
    init,
    close,
    emit,
    flush,
    get,
    is_enabled,
    session_id,
)

__all__ = [
    "TelemetryCollector",
    "init",
    "close",
    "emit",
    "flush",
    "get",
    "is_enabled",
    "session_id",
]
