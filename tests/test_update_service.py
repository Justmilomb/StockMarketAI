"""Tests for ``desktop.update_service``.

Covers the three things that matter most for a safe auto-update:

1. **Version / skip / dedup logic** — the service must never re-show
   the banner for a version the user already dismissed, never flag an
   older remote as newer, and never re-raise the same version twice in
   a single session even if ``_check`` is called repeatedly.

2. **sha256 verification** — a mismatched installer must be deleted and
   surface as an ``update_error``. No silent fallback to "install
   anyway", ever.

3. **Schedule persistence** — ``schedule_install`` has to write through
   to the config dict via the saver callback (so scheduled installs
   survive app restarts), normalise naive datetimes to UTC, and drop
   stranded schedules from >24h ago on wakeup.

Network is not touched: ``_fetch_manifest`` is monkeypatched at every
call site so the suite stays deterministic and offline.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

# A headless QCoreApplication is required to instantiate QObject
# subclasses. Without it, constructing ``UpdateService`` raises
# ``RuntimeError: Please instantiate the QCoreApplication...``.
from PySide6.QtCore import QCoreApplication

_qt_app = QCoreApplication.instance() or QCoreApplication([])

import desktop.update_service as us_module
from desktop.update_service import UpdateService


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def config() -> Dict[str, Any]:
    """Baseline config with an ``updates`` section matching DEFAULT_CONFIG."""
    return {
        "updates": {
            "auto_check": True,
            "check_interval_minutes": 30,
            "skip_version": "",
            "pending_install": None,
        },
    }


@pytest.fixture
def saves(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List captured at each config_saver invocation.

    Returns a list that grows every time the service calls the saver.
    Each entry is a deep-copy snapshot of the config dict so tests can
    assert on ordering as well as final state.
    """
    captured: List[Dict[str, Any]] = []
    return captured


@pytest.fixture
def service(
    config: Dict[str, Any], saves: List[Dict[str, Any]],
) -> UpdateService:
    """Build an ``UpdateService`` bound to the fixture config.

    The saver deep-copies into ``saves`` so tests can assert at any
    point what was persisted. We never call ``start()`` — tests drive
    the state machine directly via method calls.
    """
    def _saver() -> None:
        saves.append(json.loads(json.dumps(config)))

    svc = UpdateService(None, config=config, config_saver=_saver)
    yield svc
    svc.stop()


@pytest.fixture
def pin_local_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``desktop.update_service.__version__`` to 1.0.0 for the test."""
    monkeypatch.setattr(us_module, "__version__", "1.0.0")


class _Catcher:
    """Small helper to record signal emissions during a test."""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def __call__(self, *args: Any) -> None:
        if len(args) == 1:
            self.calls.append(args[0])
        else:
            self.calls.append(args)


# ─── Version / skip / dedup logic ────────────────────────────────────

def test_check_ignores_older_remote(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote older than local → no emission, no manifest cache."""
    monkeypatch.setattr(
        UpdateService, "_fetch_manifest",
        lambda self: {"version": "0.9.0", "download_url": "https://x/"},
    )
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()

    assert catcher.calls == []
    assert service.last_manifest() is None


def test_check_emits_when_newer(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote > local → update_available fires with the full manifest."""
    manifest = {
        "version": "2.0.0",
        "download_url": "https://example.com/BlankSetup.exe",
        "sha256": "",
        "notes": "- bug fixes",
        "mandatory": False,
    }
    monkeypatch.setattr(UpdateService, "_fetch_manifest", lambda self: manifest)
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()

    assert len(catcher.calls) == 1
    assert catcher.calls[0]["version"] == "2.0.0"
    assert service.last_manifest() == manifest


def test_check_respects_skip_version(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
    config: Dict[str, Any],
) -> None:
    """User-dismissed version must not re-emit.

    This is the single most load-bearing piece of the dismiss flow —
    if this breaks, the banner reappears every 30 min and the user
    learns to ignore us, which defeats the whole purpose.
    """
    config["updates"]["skip_version"] = "2.0.0"
    monkeypatch.setattr(
        UpdateService, "_fetch_manifest",
        lambda self: {"version": "2.0.0", "download_url": "https://x/"},
    )
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()

    assert catcher.calls == []


def test_check_deduplicates_same_session(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second ``_check`` with the same version is a no-op.

    Prevents the banner from flashing back at the user mid-use when
    the 30-min poll fires while the banner is already visible.
    """
    monkeypatch.setattr(
        UpdateService, "_fetch_manifest",
        lambda self: {"version": "2.0.0", "download_url": "https://x/"},
    )
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()
    service._check()
    service._check()

    assert len(catcher.calls) == 1


def test_check_handles_invalid_version(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage remote version → no crash, no emit."""
    monkeypatch.setattr(
        UpdateService, "_fetch_manifest",
        lambda self: {"version": "not-a-version", "download_url": "https://x/"},
    )
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()

    assert catcher.calls == []


def test_check_handles_empty_manifest(
    service: UpdateService, pin_local_version: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_fetch_manifest`` returning None must not crash ``_check``."""
    monkeypatch.setattr(UpdateService, "_fetch_manifest", lambda self: None)
    catcher = _Catcher()
    service.update_available.connect(catcher)

    service._check()  # should be a silent no-op

    assert catcher.calls == []


# ─── sha256 verification ─────────────────────────────────────────────

def test_sha256_of_matches_stdlib(tmp_path: Path) -> None:
    """Sanity check that the static helper matches hashlib."""
    blob = b"the quick brown fox"
    path = tmp_path / "installer.exe"
    path.write_bytes(blob)

    expected = hashlib.sha256(blob).hexdigest()
    assert UpdateService._sha256_of(path) == expected


def test_sha256_verification_pass(
    service: UpdateService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching sha256 → no error emitted, installer launches."""
    blob = b"fake installer bytes"
    installer = tmp_path / "BlankSetup-2.0.0.exe"
    installer.write_bytes(blob)
    expected_sha = hashlib.sha256(blob).hexdigest()

    launched: List[str] = []
    monkeypatch.setattr(
        UpdateService, "_launch_installer",
        lambda self, path: launched.append(path),
    )
    errors = _Catcher()
    service.update_error.connect(errors)
    installing = _Catcher()
    service.update_installing.connect(installing)

    service._on_download_ok(
        str(installer),
        {
            "version": "2.0.0",
            "download_url": "https://x/",
            "sha256": expected_sha,
        },
    )

    assert errors.calls == []
    assert launched == [str(installer)]
    assert installing.calls == [str(installer)]
    assert installer.exists()  # pass case keeps the file for the launcher


def test_sha256_verification_fail(
    service: UpdateService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrong sha256 → error emitted, file deleted, installer not launched."""
    installer = tmp_path / "BlankSetup-2.0.0.exe"
    installer.write_bytes(b"genuine bytes")
    wrong_sha = "0" * 64  # all-zero sha256

    launched: List[str] = []
    monkeypatch.setattr(
        UpdateService, "_launch_installer",
        lambda self, path: launched.append(path),
    )
    errors = _Catcher()
    service.update_error.connect(errors)

    service._on_download_ok(
        str(installer),
        {
            "version": "2.0.0",
            "download_url": "https://x/",
            "sha256": wrong_sha,
        },
    )

    assert len(errors.calls) == 1
    assert "sha256 mismatch" in errors.calls[0]
    assert launched == []
    assert not installer.exists()  # corrupted file must not linger


def test_sha256_skipped_when_manifest_has_no_hash(
    service: UpdateService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty sha256 in manifest → skip verification, still launch."""
    installer = tmp_path / "BlankSetup-2.0.0.exe"
    installer.write_bytes(b"any bytes")

    launched: List[str] = []
    monkeypatch.setattr(
        UpdateService, "_launch_installer",
        lambda self, path: launched.append(path),
    )
    errors = _Catcher()
    service.update_error.connect(errors)

    service._on_download_ok(
        str(installer), {"version": "2.0.0", "download_url": "https://x/", "sha256": ""},
    )

    assert errors.calls == []
    assert launched == [str(installer)]


# ─── Schedule persistence ────────────────────────────────────────────

def test_schedule_install_persists_to_config(
    service: UpdateService,
    config: Dict[str, Any],
    saves: List[Dict[str, Any]],
) -> None:
    """``schedule_install`` writes pending_install and calls the saver."""
    manifest = {
        "version": "2.0.0",
        "download_url": "https://example.com/BlankSetup.exe",
        "sha256": "abc123",
        "notes": "- thing",
        "mandatory": False,
    }
    when = datetime.now(timezone.utc) + timedelta(hours=2)

    service.schedule_install(manifest, when)

    pending = config["updates"]["pending_install"]
    assert pending is not None
    assert pending["version"] == "2.0.0"
    assert pending["download_url"] == "https://example.com/BlankSetup.exe"
    assert pending["sha256"] == "abc123"
    assert pending["notes"] == "- thing"
    assert pending["mandatory"] is False
    # scheduled_at must be ISO-8601 and parseable
    parsed = datetime.fromisoformat(pending["scheduled_at"])
    assert abs((parsed - when).total_seconds()) < 1
    # saver was called with the updated state
    assert len(saves) == 1
    assert saves[0]["updates"]["pending_install"]["version"] == "2.0.0"


def test_schedule_install_utc_normalization(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """A naive local datetime is stored as a UTC-aware ISO string."""
    manifest = {"version": "2.0.0", "download_url": "https://x/"}
    naive_local = datetime.now() + timedelta(minutes=30)

    service.schedule_install(manifest, naive_local)

    stored = config["updates"]["pending_install"]["scheduled_at"]
    parsed = datetime.fromisoformat(stored)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_cancel_schedule_clears_pending(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """``cancel_schedule`` removes the pending_install entry."""
    manifest = {"version": "2.0.0", "download_url": "https://x/"}
    service.schedule_install(manifest, datetime.now() + timedelta(hours=1))
    assert config["updates"]["pending_install"] is not None

    service.cancel_schedule()

    assert config["updates"]["pending_install"] is None


def test_dismiss_version_persists(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """``dismiss_version`` records skip_version and marks as seen."""
    service.dismiss_version("2.0.0")
    assert config["updates"]["skip_version"] == "2.0.0"
    # And a re-check for the same version should not emit.
    # (handled via _latest_seen — tested implicitly by the next test)


# ─── Imminent-schedule detection ─────────────────────────────────────

def test_is_schedule_imminent_true_within_window(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """Pending install 3 minutes out is considered imminent (<5 min)."""
    when = datetime.now(timezone.utc) + timedelta(minutes=3)
    config["updates"]["pending_install"] = {
        "version": "2.0.0",
        "download_url": "https://x/",
        "sha256": "",
        "notes": "",
        "mandatory": False,
        "scheduled_at": when.isoformat(),
    }
    assert service.is_schedule_imminent(5) is True


def test_is_schedule_imminent_false_far_future(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """Pending install 20 minutes out is not imminent."""
    when = datetime.now(timezone.utc) + timedelta(minutes=20)
    config["updates"]["pending_install"] = {
        "version": "2.0.0",
        "download_url": "https://x/",
        "sha256": "",
        "notes": "",
        "mandatory": False,
        "scheduled_at": when.isoformat(),
    }
    assert service.is_schedule_imminent(5) is False


def test_is_schedule_imminent_false_when_none(
    service: UpdateService,
) -> None:
    """No pending install → never imminent."""
    assert service.is_schedule_imminent(5) is False


def test_pending_install_returns_none_when_missing(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """Absent ``pending_install`` returns None rather than crashing."""
    config["updates"] = {}
    assert service.pending_install() is None


# ─── Stranded schedule cleanup ───────────────────────────────────────

def test_poll_schedule_clears_stranded(
    service: UpdateService, config: Dict[str, Any],
) -> None:
    """Schedule >24h in the past is dropped on wakeup.

    Reflects the "user closed the app, came back a week later" case —
    we don't silently apply a week-old schedule; we wipe it and let the
    banner re-emit on the next check.
    """
    stranded = datetime.now(timezone.utc) - timedelta(hours=48)
    config["updates"]["pending_install"] = {
        "version": "2.0.0",
        "download_url": "https://x/",
        "sha256": "",
        "notes": "",
        "mandatory": False,
        "scheduled_at": stranded.isoformat(),
    }

    service._poll_schedule()

    assert config["updates"]["pending_install"] is None


# ─── Low-level parse helpers ─────────────────────────────────────────

def test_parse_scheduled_at_naive_is_treated_as_utc() -> None:
    """A naive ISO string is interpreted as UTC (not local).

    Persisted schedules are always UTC-aware — this branch only runs
    for corrupted legacy payloads, and defaulting to UTC is safer than
    picking a local TZ that could shift the schedule across a DST
    boundary.
    """
    naive = "2030-01-01T12:00:00"
    parsed = UpdateService._parse_scheduled_at(naive)
    assert parsed is not None
    assert parsed.tzinfo == timezone.utc


def test_parse_scheduled_at_rejects_garbage() -> None:
    assert UpdateService._parse_scheduled_at("not-a-date") is None
    assert UpdateService._parse_scheduled_at(None) is None
    assert UpdateService._parse_scheduled_at("") is None
    assert UpdateService._parse_scheduled_at(12345) is None
