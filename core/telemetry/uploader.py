"""Nightly batch uploader for telemetry events.

Runs as a daemon thread. Sleeps until either:

* the configured nightly window (defaults to ``03:00`` local time), or
* :meth:`request_upload` is called from outside (e.g. shutdown flush).

On wake the uploader reads every pending row from
``TelemetryCollector.pending()``, gzips the JSON batch, POSTs it to the
blank server's ``/api/telemetry`` endpoint with the install's licence
key in the ``X-Licence-Key`` header, and marks the rows as uploaded on
a 2xx response. Failures retry on the next cycle with an exponential
backoff capped at 6 h.

Bandwidth: gzipped JSON, batched at 500 events per request, one
request per nightly run (plus retries). An average session produces
~2000 events; a typical nightly payload is ~80 KB compressed.
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover — bundled at install time
    requests = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from core.telemetry.collector import TelemetryCollector

logger = logging.getLogger(__name__)


#: Default window for the nightly upload (local time, 24-h clock).
DEFAULT_UPLOAD_HOUR: int = 3

#: Batch size ceiling per HTTP request. One nightly cycle may issue
#: several requests back-to-back until the queue drains.
DEFAULT_BATCH_SIZE: int = 500

#: Exponential-backoff ceiling after repeated upload failures.
MAX_BACKOFF_SECONDS: int = 6 * 3600

#: Retention window for already-uploaded local rows.
LOCAL_RETENTION_DAYS: int = 30


class TelemetryUploader(threading.Thread):
    """Daemon thread that ships pending telemetry to the server nightly."""

    def __init__(
        self,
        collector: "TelemetryCollector",
        *,
        upload_hour: int = DEFAULT_UPLOAD_HOUR,
        batch_size: int = DEFAULT_BATCH_SIZE,
        http_timeout: float = 20.0,
    ) -> None:
        super().__init__(daemon=True, name="telemetry-uploader")
        self._collector = collector
        self._upload_hour: int = max(0, min(23, int(upload_hour)))
        self._batch_size: int = max(1, int(batch_size))
        self._http_timeout: float = float(http_timeout)

        self._stop_event: threading.Event = threading.Event()
        self._wake_event: threading.Event = threading.Event()
        self._failure_streak: int = 0

    # ── lifecycle ─────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — Thread API
        if not self._collector.enabled:
            logger.info("telemetry disabled — uploader exiting immediately")
            return
        if requests is None:
            logger.info("requests not installed — telemetry uploader inactive")
            return

        logger.info(
            "telemetry uploader started (endpoint=%s upload_hour=%02d:00)",
            self._collector.endpoint, self._upload_hour,
        )
        while not self._stop_event.is_set():
            wait_s = self._seconds_until_next_window()
            self._wake_event.wait(timeout=wait_s)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._one_upload_cycle()
        logger.info("telemetry uploader stopped")

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()

    def request_upload(self) -> None:
        """Break out of the sleep and run one upload cycle now."""
        self._wake_event.set()

    # ── one cycle ─────────────────────────────────────────────────────

    def _one_upload_cycle(self) -> None:
        try:
            sent_any = False
            while not self._stop_event.is_set():
                batch = self._collector.pending(limit=self._batch_size)
                if not batch:
                    break
                if not self._ship(batch):
                    self._failure_streak += 1
                    return
                self._collector.mark_uploaded([int(row[0]) for row in batch])
                sent_any = True
                # Small yield so other threads get a chance.
                time.sleep(0.05)
            if sent_any:
                self._collector.purge_uploaded(older_than_days=LOCAL_RETENTION_DAYS)
            self._failure_streak = 0
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("telemetry uploader cycle crashed: %s", exc)
            self._failure_streak += 1

    def _ship(self, batch: List[tuple]) -> bool:
        """POST one batch. Return True on 2xx, False otherwise."""
        if requests is None:
            return False

        events = []
        for row in batch:
            event_id, event_type, session_id, created_at, payload_json = row
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except json.JSONDecodeError:
                payload = {}
            events.append({
                "event_type": event_type,
                "session_id": session_id,
                "created_at": created_at,
                "payload": payload,
            })

        body = json.dumps({
            "machine_id": self._collector.machine_id,
            "events": events,
        }, ensure_ascii=False, default=str).encode("utf-8")
        compressed = gzip.compress(body, compresslevel=6)

        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-Licence-Key": self._collector.licence_key,
            "X-Machine-Id": self._collector.machine_id,
        }
        try:
            response = requests.post(
                self._collector.endpoint,
                data=compressed,
                headers=headers,
                timeout=self._http_timeout,
            )
        except requests.RequestException as exc:
            logger.info("telemetry ship failed (network): %s", exc)
            return False

        if 200 <= response.status_code < 300:
            return True
        logger.info(
            "telemetry ship rejected status=%s body=%s",
            response.status_code, response.text[:200],
        )
        return False

    # ── scheduling ────────────────────────────────────────────────────

    def _seconds_until_next_window(self) -> float:
        """Seconds to sleep until the next upload window.

        If we had failures, use an exponential backoff so a broken
        server doesn't burn the client's bandwidth retrying every
        minute. A healthy run resets the streak back to the daily
        cadence.
        """
        if self._failure_streak > 0:
            backoff = min(60 * (2 ** self._failure_streak), MAX_BACKOFF_SECONDS)
            return float(backoff)

        now = datetime.now()
        target = now.replace(
            hour=self._upload_hour, minute=0, second=0, microsecond=0,
        )
        if target <= now:
            target = target + timedelta(days=1)
        return max(60.0, (target - now).total_seconds())
