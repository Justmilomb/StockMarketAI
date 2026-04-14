"""Tests for ``desktop.paths`` — user-data dir resolution + v1 migration.

These tests exercise the path helpers and
``migrate_user_state_if_needed`` without touching the real
``%LOCALAPPDATA%\\blank\\`` directory. We monkeypatch ``LOCALAPPDATA``,
``PROGRAMFILES``, and ``PROGRAMFILES(X86)`` environment variables to
redirect the helpers at a ``tmp_path`` scratch area.

The migration function is deliberately idempotent and candidate-order
sensitive; both properties are load-bearing, so both get explicit
coverage here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop import paths


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def fake_localappdata(tmp_path, monkeypatch):
    """Redirect ``%LOCALAPPDATA%`` at a scratch dir for the test.

    Returns the redirected path so tests can assert on what got written
    to it. We also chdir to an empty scratch directory so the migrator's
    ``Path.cwd()`` fallback candidate doesn't accidentally pick up the
    repo's real ``config.json`` during local test runs.
    """
    target = tmp_path / "LocalAppData"
    target.mkdir()
    cwd_scratch = tmp_path / "cwd"
    cwd_scratch.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(target))
    monkeypatch.chdir(cwd_scratch)
    return target


@pytest.fixture
def fake_program_files(tmp_path, monkeypatch):
    """Redirect ``%ProgramFiles%`` + ``%ProgramFiles(x86)%``.

    Returns a dict with both paths. Tests populate them to simulate a
    previous v1 install and then assert migration picks the right one.
    """
    pf = tmp_path / "ProgramFiles"
    pf_x86 = tmp_path / "ProgramFilesX86"
    pf.mkdir()
    pf_x86.mkdir()
    monkeypatch.setenv("PROGRAMFILES", str(pf))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(pf_x86))
    return {"pf": pf, "pf_x86": pf_x86}


def _seed_v1_install(root: Path, config_blob: dict, db_bytes: bytes = b"v1-db") -> Path:
    """Build a realistic v1 install tree under ``root / blank``."""
    install = root / "blank"
    install.mkdir()
    (install / "config.json").write_text(json.dumps(config_blob), encoding="utf-8")
    (install / ".env").write_text("T212_API_KEY=v1secret\n", encoding="utf-8")
    data = install / "data"
    data.mkdir()
    (data / "terminal_history.db").write_bytes(db_bytes)
    (data / "agent_journal.log").write_text("v1 journal line\n", encoding="utf-8")
    return install


# ─── Path helpers ────────────────────────────────────────────────────────

def test_user_data_dir_creates_directory(fake_localappdata):
    """``user_data_dir()`` is responsible for making the dir exist."""
    expected = fake_localappdata / "blank"
    assert not expected.exists()
    result = paths.user_data_dir()
    assert result == expected
    assert result.is_dir()


def test_config_path_lives_under_user_data_dir(fake_localappdata):
    assert paths.config_path() == fake_localappdata / "blank" / "config.json"


def test_db_path_creates_data_subdir(fake_localappdata):
    """``db_path()`` returns the sqlite path **and** creates ``data/``."""
    result = paths.db_path()
    assert result == fake_localappdata / "blank" / "data" / "terminal_history.db"
    assert result.parent.is_dir()


def test_dotenv_path(fake_localappdata):
    assert paths.dotenv_path() == fake_localappdata / "blank" / ".env"


# ─── Migration ───────────────────────────────────────────────────────────

def test_migration_no_source(fake_localappdata, fake_program_files):
    """Fresh install — nowhere to migrate from → ``no_source_found``."""
    result = paths.migrate_user_state_if_needed()
    assert result.status == "no_source_found"
    assert result.source is None
    assert not paths.config_path().exists()


def test_migration_from_program_files(fake_localappdata, fake_program_files):
    """The canonical v1 → v2 upgrade path: copy from Program Files."""
    v1 = _seed_v1_install(
        fake_program_files["pf"],
        config_blob={"watchlists": {"Default": ["AAPL", "TSLA"]}, "capital": 12345},
    )

    result = paths.migrate_user_state_if_needed()

    assert result.status == "migrated"
    assert result.source == v1
    # config.json, .env, and data/ contents all land at the destination
    dst_config = paths.config_path()
    assert dst_config.exists()
    loaded = json.loads(dst_config.read_text(encoding="utf-8"))
    assert loaded["capital"] == 12345
    assert loaded["watchlists"]["Default"] == ["AAPL", "TSLA"]

    assert paths.dotenv_path().read_text(encoding="utf-8") == "T212_API_KEY=v1secret\n"
    assert paths.db_path().read_bytes() == b"v1-db"

    # files_copied should list the config + dotenv + at least the sqlite file
    assert "config.json" in result.files_copied
    assert ".env" in result.files_copied
    assert any("terminal_history.db" in f for f in result.files_copied)


def test_migration_is_idempotent(fake_localappdata, fake_program_files):
    """Second call after a successful migration is a no-op."""
    _seed_v1_install(
        fake_program_files["pf"],
        config_blob={"watchlists": {"Default": []}, "capital": 1},
    )

    first = paths.migrate_user_state_if_needed()
    assert first.status == "migrated"

    second = paths.migrate_user_state_if_needed()
    assert second.status == "already_migrated"
    assert second.files_copied == []


def test_migration_prefers_program_files_over_x86(fake_localappdata, fake_program_files):
    """Both candidates populated → the non-x86 dir wins (priority order).

    v1 shipped as 64-bit, so if both Program Files entries somehow have
    a v1 install we want the 64-bit one since that matches the
    ``{autopf}`` resolution used by the old installer.
    """
    _seed_v1_install(
        fake_program_files["pf"],
        config_blob={"marker": "primary"},
    )
    _seed_v1_install(
        fake_program_files["pf_x86"],
        config_blob={"marker": "x86"},
    )

    result = paths.migrate_user_state_if_needed()
    assert result.status == "migrated"

    loaded = json.loads(paths.config_path().read_text(encoding="utf-8"))
    assert loaded["marker"] == "primary"


def test_migration_skips_candidates_without_config(
    fake_localappdata, fake_program_files, tmp_path,
):
    """A ``blank\\`` dir with no ``config.json`` is not a valid source.

    Prevents the migrator from grabbing a random ``data/`` subtree out
    of the user's cwd that happens to share the project name.
    """
    # Program Files\blank exists but is empty — should be skipped
    (fake_program_files["pf"] / "blank").mkdir()

    # Program Files (x86)\blank has a real v1 install — should win
    _seed_v1_install(
        fake_program_files["pf_x86"],
        config_blob={"marker": "x86-fallback"},
    )

    result = paths.migrate_user_state_if_needed()
    assert result.status == "migrated"
    assert result.source == fake_program_files["pf_x86"] / "blank"


def test_migration_does_not_overwrite_existing_config(
    fake_localappdata, fake_program_files,
):
    """If the destination already has a config, migration is a no-op.

    Protects the user from accidentally losing their v2 state if a v1
    install is still lurking in Program Files after they've been on v2
    for a while.
    """
    _seed_v1_install(
        fake_program_files["pf"],
        config_blob={"marker": "v1"},
    )
    # Pre-seed the destination with v2 state
    existing = paths.config_path()
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(json.dumps({"marker": "v2"}), encoding="utf-8")

    result = paths.migrate_user_state_if_needed()
    assert result.status == "already_migrated"

    loaded = json.loads(existing.read_text(encoding="utf-8"))
    assert loaded["marker"] == "v2"


def test_migration_result_as_dict(fake_localappdata, fake_program_files):
    """``MigrationResult.as_dict`` serialises cleanly for logging."""
    _seed_v1_install(
        fake_program_files["pf"],
        config_blob={"watchlists": {"Default": []}},
    )
    result = paths.migrate_user_state_if_needed()
    d = result.as_dict()
    assert d["status"] == "migrated"
    assert isinstance(d["source"], str)
    assert isinstance(d["files"], list)
    assert "config.json" in d["files"]
