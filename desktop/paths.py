"""Single source of truth for the locations of the user's durable state.

**Why this module exists**

Before v2.0.0 the frozen build wrote ``config.json`` and
``data/terminal_history.db`` next to the executable. That meant all of
the user's runtime state lived inside the install directory — which,
under the old per-machine ``{autopf}\\blank`` installer, translates to
``C:\\Program Files\\blank\\``. That location is:

1. Read-only for unprivileged processes (needed an admin UAC elevation
   just to save a watchlist edit), and
2. Actively wiped by the old ``[UninstallDelete]`` block of
   ``installer/bloomberg.iss`` — so reinstalling blank destroyed the
   user's chat history, agent journal, position notes, backtest runs
   and everything else worth remembering.

The v2.0.0 cut moves all of that to ``%LOCALAPPDATA%\\blank\\`` — the
standard Windows per-user data location used by VSCode, Chrome, and
anything else that wants to be friendly to users without admin rights.
The binary lives in ``%LOCALAPPDATA%\\Programs\\blank\\`` (a sibling
directory) so the installer can wipe/replace the executable without
ever touching user state.

**Migration**

``migrate_user_state_if_needed`` is the one-shot copy that runs on
every launch. It's idempotent: if the destination ``config.json``
already exists it returns immediately. Otherwise it walks a priority
list of likely old homes (the two Program Files variants first, then
the current exe's parent, then the cwd), and the first hit wins — we
copy ``config.json``, ``.env``, and the entire ``data/`` subtree into
the new home. Nothing is deleted from the source; the user can
uninstall the old version at their leisure.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

APP_DIR_NAME = "blank"
CONFIG_FILENAME = "config.json"
DOTENV_FILENAME = ".env"
DATA_SUBDIR = "data"
DB_FILENAME = "terminal_history.db"


# ─── Path helpers ────────────────────────────────────────────────────────

def _localappdata() -> Path:
    """Return the Windows ``%LOCALAPPDATA%`` directory.

    Falls back to ``~/.local/share`` on non-Windows platforms for dev
    work — blank ships as a Windows .exe but we still want the path
    helpers to be importable from pytest on macOS/Linux CI hosts.
    """
    env = os.environ.get("LOCALAPPDATA")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        # Best-effort reconstruction if the env var was stripped
        return Path.home() / "AppData" / "Local"
    return Path.home() / ".local" / "share"


def user_data_dir() -> Path:
    """Absolute path to ``%LOCALAPPDATA%\\blank\\``. Creates it if missing."""
    path = _localappdata() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Absolute path to the user's ``config.json``."""
    return user_data_dir() / CONFIG_FILENAME


def dotenv_path() -> Path:
    """Absolute path to the user's ``.env`` file."""
    return user_data_dir() / DOTENV_FILENAME


def db_path() -> Path:
    """Absolute path to the sqlite history DB. Creates ``data/`` if needed."""
    data_dir = user_data_dir() / DATA_SUBDIR
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / DB_FILENAME


# ─── Migration ───────────────────────────────────────────────────────────

@dataclass
class MigrationResult:
    """What ``migrate_user_state_if_needed`` actually did.

    ``status`` is one of:

    * ``already_migrated`` — destination config already present; no-op
    * ``no_source_found`` — fresh install, nothing to copy
    * ``migrated`` — found a source and copied files
    """

    status: str
    source: Optional[Path] = None
    files_copied: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "source": str(self.source) if self.source else None,
            "files": list(self.files_copied),
        }


def _candidate_sources() -> List[Path]:
    """Directories that might hold a previous version's user state.

    Order matters: the first candidate that contains a ``config.json``
    wins. We check the two ``Program Files`` locations first because
    those are the old per-machine install dirs used by every shipped
    v1.0.0 installer. Only then do we fall back to exe-adjacent
    (portable builds, dev builds) and cwd (pure ``python -m`` runs).
    """
    candidates: List[Path] = []

    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / APP_DIR_NAME)

    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / APP_DIR_NAME)

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent)

    candidates.append(Path.cwd())

    return candidates


def _copy_file_if_present(src: Path, dst: Path, name: str, log: List[str]) -> None:
    """Copy a single file if the source exists. Safe to call repeatedly."""
    src_file = src / name
    if not src_file.exists() or not src_file.is_file():
        return
    dst_file = dst / name
    if dst_file.exists():
        return
    shutil.copy2(src_file, dst_file)
    log.append(name)


def _copy_data_tree(src: Path, dst: Path, log: List[str]) -> None:
    """Copy the entire ``data/`` subtree if the source has one.

    Uses ``dirs_exist_ok=True`` so a partially-populated destination
    (e.g. a failed migration resumed on next launch) converges.
    """
    src_data = src / DATA_SUBDIR
    if not src_data.exists() or not src_data.is_dir():
        return
    dst_data = dst / DATA_SUBDIR
    shutil.copytree(src_data, dst_data, dirs_exist_ok=True)
    # Walk the tree so we can report exactly what landed.
    for path in dst_data.rglob("*"):
        if path.is_file():
            log.append(str(path.relative_to(dst)))


def migrate_user_state_if_needed() -> MigrationResult:
    """Copy config + data from any old install to ``%LOCALAPPDATA%\\blank\\``.

    Idempotent: if ``config_path()`` already exists we return
    immediately with ``status == "already_migrated"``. Otherwise we
    walk ``_candidate_sources()`` and copy the first hit.

    This function does **not** delete anything from the source. The
    user can uninstall the old version after verifying v2.0.0 works.
    """
    dst = user_data_dir()
    if config_path().exists():
        return MigrationResult(status="already_migrated", source=dst)

    copied: List[str] = []
    for candidate in _candidate_sources():
        # Resolve symlinks and check existence; skip phantom candidates.
        try:
            if not candidate.exists() or not candidate.is_dir():
                continue
        except OSError:
            continue

        # The candidate must actually look like a blank install — we
        # require a config.json at its root. Without that we'd risk
        # copying a random ``data/`` dir from the user's cwd.
        if not (candidate / CONFIG_FILENAME).exists():
            continue

        logger.info("Migrating blank user state from %s -> %s", candidate, dst)
        _copy_file_if_present(candidate, dst, CONFIG_FILENAME, copied)
        _copy_file_if_present(candidate, dst, DOTENV_FILENAME, copied)
        _copy_data_tree(candidate, dst, copied)
        return MigrationResult(
            status="migrated", source=candidate, files_copied=copied,
        )

    logger.info("No previous blank install found — starting fresh in %s", dst)
    return MigrationResult(status="no_source_found", source=None)
