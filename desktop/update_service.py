"""Auto-update service for the blank desktop app.

Polls the remote manifest endpoint on a timer. When a newer version is
published, emits ``update_available`` — the banner UI subscribes to that
signal to show the user an actionable banner.

On ``install_now(manifest)``, downloads the installer to ``%TEMP%`` in a
worker thread (emitting ``update_download_progress``), verifies the
sha256 if one is provided in the manifest, then launches the installer
with the ``/VERYSILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`` flags
and quits the app — Inno Setup takes over from there, kills us via the
``BlankTradingTerminalMutex_v2`` mutex, installs the new bundle, and
restarts blank automatically.

The service also owns a ``pending_install`` slot in the config so
scheduled installs survive app restarts. A second QTimer polls that slot
every minute; when the scheduled time is reached, the install runs
automatically.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from desktop import __version__

logger = logging.getLogger(__name__)

#: Where the desktop app fetches its update manifest from. Matches the
#: ``/api/version`` endpoint served by ``server/app.py``.
DEFAULT_MANIFEST_URL = "https://blan-api.onrender.com/api/version"

#: Default polling interval for the manifest endpoint when the config
#: doesn't override it. 30 minutes is chosen so the server doesn't get
#: hammered and a busy dev cycle (publish → test on a client) sees
#: updates within half an hour without any manual refresh button.
DEFAULT_CHECK_INTERVAL_MINUTES = 30

#: How often the schedule watchdog wakes to check whether a pending
#: install has come due. 60 s is fine-grained enough that the worst-case
#: latency between "scheduled time" and "install starts" is under a
#: minute, which is imperceptible for the user's chosen install window.
POLL_PENDING_INSTALL_SECONDS = 60

MANIFEST_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 65_536

# Windows process creation flags so the installer survives our own quit.
# DETACHED_PROCESS (0x08) severs the console inheritance; CREATE_NEW_
# PROCESS_GROUP (0x200) detaches the process group so the installer is
# not a child of the dying Qt process.
_WIN_DETACHED_PROCESS = 0x00000008
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200


class _DownloadWorker(QThread):
    """Background thread that streams an installer to disk.

    Separated from :class:`UpdateService` so the download runs off the
    Qt main thread — otherwise the app would freeze for hundreds of MB.
    Emits ``progress`` (0-100) during the copy and either ``finished_ok``
    (with the final path) or ``failed`` (with a message) at the end.
    """

    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest: Path, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._url = url
        self._dest = dest
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            req = Request(self._url, headers={"User-Agent": f"blank/{__version__}"})
            with urlopen(req, timeout=MANIFEST_TIMEOUT_SECONDS) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                last_pct = -1
                with open(self._dest, "wb") as f:
                    while True:
                        if self._abort:
                            self.failed.emit("cancelled")
                            return
                        chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct:
                                self.progress.emit(pct)
                                last_pct = pct
            self.finished_ok.emit(str(self._dest))
        except (HTTPError, URLError) as exc:
            self.failed.emit(f"download failed: {exc}")
        except OSError as exc:
            self.failed.emit(f"write failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — broad on purpose; surface to UI
            logger.exception("unexpected download error")
            self.failed.emit(f"download failed: {exc}")


class UpdateService(QObject):
    """Polls the manifest endpoint and orchestrates silent self-install.

    Owns:
        - the periodic manifest poll
        - the download worker
        - the sha256 verification step
        - the pending-install schedule (persisted in the config dict)
        - the final subprocess that launches the Inno Setup installer

    Signals out the following events so the main window's banner /
    status bar can react:
        ``update_available(dict)``      — newer manifest fetched
        ``update_download_progress(int)`` — 0-100 during install_now
        ``update_error(str)``           — any user-visible failure
        ``update_installing(str)``      — installer launched (path)
        ``schedule_changed(object)``    — pending_install dict or None
    """

    update_available = Signal(dict)
    update_download_progress = Signal(int)
    update_error = Signal(str)
    update_installing = Signal(str)
    schedule_changed = Signal(object)
    maintenance_changed = Signal(bool, str)   # (active, message)
    notification_received = Signal(str)       # message to display once

    def __init__(
        self,
        parent: QObject,
        config: dict[str, Any],
        config_saver: Callable[[], None],
        manifest_url: str = DEFAULT_MANIFEST_URL,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._config_saver = config_saver
        self._manifest_url = manifest_url

        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check)

        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._poll_schedule)

        self._download: Optional[_DownloadWorker] = None
        self._last_manifest: Optional[dict[str, Any]] = None
        self._latest_seen: Optional[str] = None
        self._maintenance_active: bool = False
        self._notif_seen_at: Optional[str] = None  # notification_at we've already fired

    # ─── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        settings = self._config.get("updates", {}) or {}
        if not settings.get("auto_check", True):
            logger.info("update service: auto-check disabled by config")
            return
        interval_min = int(settings.get("check_interval_minutes") or DEFAULT_CHECK_INTERVAL_MINUTES)
        interval_min = max(5, interval_min)  # prevent a user typo from DoSing the server
        self._check_timer.start(interval_min * 60_000)
        self._schedule_timer.start(POLL_PENDING_INSTALL_SECONDS * 1000)
        # Kick off an immediate check shortly after startup so the user
        # doesn't have to wait a full interval on first boot.
        QTimer.singleShot(2_000, self._check)
        # If a schedule was stashed from a prior session, re-emit it.
        QTimer.singleShot(2_500, self._emit_existing_schedule)

    def stop(self) -> None:
        self._check_timer.stop()
        self._schedule_timer.stop()
        if self._download is not None:
            self._download.abort()
            self._download.wait(1_500)
            self._download = None

    # ─── manifest fetch ─────────────────────────────────────────────────

    def _check(self) -> None:
        manifest = self._fetch_manifest()
        if manifest is None:
            return

        # ── Maintenance mode ─────────────────────────────────────────────
        maintenance = bool(manifest.get("maintenance", False))
        maint_msg = str(manifest.get("maintenance_message", "") or "")
        if maintenance != self._maintenance_active:
            self._maintenance_active = maintenance
            self.maintenance_changed.emit(maintenance, maint_msg)
        elif maintenance and maint_msg:
            # message may have changed even if mode didn't flip
            self.maintenance_changed.emit(True, maint_msg)

        # ── Scheduled notification ───────────────────────────────────────
        notif_msg = str(manifest.get("notification_message", "") or "")
        notif_at_raw = str(manifest.get("notification_at", "") or "")
        if notif_msg and notif_at_raw and notif_at_raw != self._notif_seen_at:
            notif_at = self._parse_scheduled_at(notif_at_raw)
            if notif_at is not None:
                now = datetime.now(timezone.utc)
                # Fire if the scheduled time has passed but is within the
                # last 24 hours (so stale notifications don't haunt restarts)
                if notif_at <= now <= notif_at + timedelta(hours=24):
                    self._notif_seen_at = notif_at_raw
                    self.notification_received.emit(notif_msg)

        # ── Update check ─────────────────────────────────────────────────
        remote = str(manifest.get("version", "") or "")
        if not remote:
            return

        try:
            if Version(remote) <= Version(__version__):
                return
        except InvalidVersion:
            logger.warning("invalid remote version %r; ignoring", remote)
            return

        settings = self._config.get("updates", {}) or {}
        if settings.get("skip_version") == remote:
            logger.debug("update %s skipped by user", remote)
            return

        if self._latest_seen == remote:
            return  # already raised this version in-session
        self._latest_seen = remote
        self._last_manifest = manifest
        logger.info("update available: %s (running %s)", remote, __version__)
        self.update_available.emit(manifest)

    def _fetch_manifest(self) -> Optional[dict[str, Any]]:
        try:
            req = Request(self._manifest_url, headers={"User-Agent": f"blank/{__version__}"})
            with urlopen(req, timeout=MANIFEST_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as exc:  # noqa: BLE001 — network errors are many and boring
            logger.debug("manifest fetch failed: %s", exc)
            return None

    # ─── install ────────────────────────────────────────────────────────

    def install_now(self, manifest: dict[str, Any]) -> None:
        url = str(manifest.get("download_url") or "")
        version = str(manifest.get("version") or "")
        if not url or not version:
            self.update_error.emit("invalid manifest: missing version or download url")
            return

        if self._download is not None:
            logger.warning("install already in progress; ignoring duplicate trigger")
            return

        dest = Path(tempfile.gettempdir()) / f"BlankSetup-{version}.exe"
        # Remove any stale partial download from a prior attempt.
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass

        worker = _DownloadWorker(url, dest, parent=self)
        self._download = worker
        worker.progress.connect(self.update_download_progress.emit)
        worker.finished_ok.connect(
            lambda p, m=manifest: self._on_download_ok(p, m)
        )
        worker.failed.connect(self._on_download_failed)
        worker.start()

    def _on_download_ok(self, path: str, manifest: dict[str, Any]) -> None:
        self._download = None

        expected_sha = str(manifest.get("sha256") or "").lower().strip()
        if expected_sha:
            actual = self._sha256_of(Path(path))
            if actual != expected_sha:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
                self.update_error.emit(
                    f"sha256 mismatch: expected {expected_sha[:16]}…, got {actual[:16]}…"
                )
                return

        # Installing now — any scheduled install is superseded.
        self._clear_pending_install()

        self.update_installing.emit(path)
        self._launch_installer(path)

    def _on_download_failed(self, msg: str) -> None:
        self._download = None
        self.update_error.emit(msg)

    @staticmethod
    def _sha256_of(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                block = f.read(1 << 20)
                if not block:
                    break
                h.update(block)
        return h.hexdigest().lower()

    def _launch_installer(self, path: str) -> None:
        """Spawn the Inno Setup installer detached and quit the app.

        The ``AppMutex`` in ``installer/bloomberg.iss`` is what enables
        the ``/CLOSEAPPLICATIONS`` + ``/RESTARTAPPLICATIONS`` handshake
        — Inno Setup waits briefly for us to exit, then restarts us
        after the bundle swap. We call ``QApplication.quit`` on a short
        delay so Qt has time to flush any pending signals.
        """
        args = [
            path,
            "/VERYSILENT",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
            "/NORESTART",
            "/SUPPRESSMSGBOXES",
        ]
        try:
            flags = 0
            if sys.platform.startswith("win"):
                flags = _WIN_DETACHED_PROCESS | _WIN_CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(args, creationflags=flags, close_fds=True)
        except Exception as exc:  # noqa: BLE001 — surface any spawn failure to UI
            self.update_error.emit(f"installer launch failed: {exc}")
            return

        from PySide6.QtWidgets import QApplication

        qt_app = QApplication.instance()
        if qt_app is not None:
            # Wait long enough for Inno Setup to initialise and register this
            # process with Windows Restart Manager before we exit. If we quit
            # in under ~1 s, RM never sees us and /RESTARTAPPLICATIONS has
            # nothing to relaunch. 8 s is conservative — Inno Setup typically
            # sends WM_CLOSE well before this fires, so in practice the app
            # closes sooner and the timer is just a fallback.
            QTimer.singleShot(8_000, qt_app.quit)

    # ─── schedule ───────────────────────────────────────────────────────

    def schedule_install(self, manifest: dict[str, Any], when: datetime) -> None:
        """Persist a pending install and emit ``schedule_changed``.

        Uses a timezone-aware UTC timestamp on disk so the schedule is
        interpretable regardless of the user's local clock. The poll
        loop compares against ``datetime.now(timezone.utc)``.
        """
        if when.tzinfo is None:
            # Interpret naive datetimes as local wall-clock time — the
            # schedule dialog constructs these via
            # ``datetime.now() + timedelta(...)`` which is naive.
            when = when.astimezone(timezone.utc)
        else:
            when = when.astimezone(timezone.utc)

        payload = {
            "version": str(manifest.get("version") or ""),
            "download_url": str(manifest.get("download_url") or ""),
            "sha256": str(manifest.get("sha256") or ""),
            "notes": str(manifest.get("notes") or ""),
            "mandatory": bool(manifest.get("mandatory", False)),
            "scheduled_at": when.isoformat(),
        }
        updates = self._config.setdefault("updates", {})
        updates["pending_install"] = payload
        self._save_config_safely()
        logger.info("scheduled install %s for %s", payload["version"], payload["scheduled_at"])
        self.schedule_changed.emit(payload)

    def cancel_schedule(self) -> None:
        self._clear_pending_install()
        self.schedule_changed.emit(None)

    def _clear_pending_install(self) -> None:
        updates = self._config.setdefault("updates", {})
        if updates.get("pending_install") is not None:
            updates["pending_install"] = None
            self._save_config_safely()

    def _emit_existing_schedule(self) -> None:
        pending = self.pending_install()
        if pending is not None:
            self.schedule_changed.emit(pending)

    def _poll_schedule(self) -> None:
        pending = self.pending_install()
        if pending is None:
            return
        scheduled_at = self._parse_scheduled_at(pending.get("scheduled_at"))
        if scheduled_at is None:
            logger.warning("invalid scheduled_at %r; clearing", pending.get("scheduled_at"))
            self._clear_pending_install()
            return

        now = datetime.now(timezone.utc)
        if scheduled_at < now - timedelta(hours=24):
            # Stranded schedule: the user chose a time, then left the
            # app closed past it. Drop the schedule and re-raise the
            # manifest so they can re-choose.
            logger.info("stranded schedule at %s; clearing", scheduled_at)
            self._clear_pending_install()
            QTimer.singleShot(0, self._check)
            return

        if scheduled_at <= now:
            logger.info("scheduled install fired: %s", pending.get("version"))
            manifest = {
                "version": pending.get("version", ""),
                "download_url": pending.get("download_url", ""),
                "sha256": pending.get("sha256", ""),
                "notes": pending.get("notes", ""),
                "mandatory": pending.get("mandatory", False),
            }
            self.install_now(manifest)

    def pending_install(self) -> Optional[dict[str, Any]]:
        settings = self._config.get("updates", {}) or {}
        p = settings.get("pending_install")
        return p if isinstance(p, dict) else None

    def is_schedule_imminent(self, within_minutes: int = 5) -> bool:
        """True if a pending install is within ``within_minutes`` minutes.

        The main window consults this in ``closeEvent`` so a user who
        closes shortly before an impending upgrade gets it applied
        immediately instead of missing the window.
        """
        pending = self.pending_install()
        if pending is None:
            return False
        scheduled_at = self._parse_scheduled_at(pending.get("scheduled_at"))
        if scheduled_at is None:
            return False
        delta = scheduled_at - datetime.now(timezone.utc)
        return delta.total_seconds() <= within_minutes * 60

    @staticmethod
    def _parse_scheduled_at(raw: Any) -> Optional[datetime]:
        if not isinstance(raw, str) or not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # ─── dismissal ──────────────────────────────────────────────────────

    def dismiss_version(self, version: str) -> None:
        """Remember that the user doesn't want the banner for this version.

        Mandatory updates are *never* dismissable — if the latest
        manifest we've seen marks the version as mandatory, we refuse
        to write ``skip_version`` and leave ``_latest_seen`` alone so
        the banner / overlay gets re-raised on the next tick.
        """
        last = self._last_manifest or {}
        if (
            str(last.get("version") or "") == version
            and bool(last.get("mandatory", False))
        ):
            logger.info("refusing to dismiss mandatory version %s", version)
            return
        updates = self._config.setdefault("updates", {})
        updates["skip_version"] = version
        self._save_config_safely()
        # Mark it seen so the next in-session poll doesn't re-emit.
        self._latest_seen = version

    # ─── helpers ────────────────────────────────────────────────────────

    def _save_config_safely(self) -> None:
        try:
            self._config_saver()
        except Exception:  # noqa: BLE001 — never let a save failure crash the app
            logger.exception("update_service: config save failed")

    def last_manifest(self) -> Optional[dict[str, Any]]:
        return self._last_manifest
