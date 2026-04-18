"""Single source of truth for the bundled AI engine location.

The installer ships a portable runtime + the AI engine CLI next to
the .exe:

    {app}/engine/node/blank-ai.exe   (runtime)
    {app}/engine/cli/rt/entry.js     (engine entry script)

In dev mode the engine dir is absent and callers fall back to
whatever is on PATH.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _install_root() -> Path:
    """Return the directory the executable lives in.

    * **Frozen** (PyInstaller onefile): ``sys.executable`` is the
      installed ``blank.exe``, so the engine dir sits next to it at
      ``{app}/engine/``.
    * **Dev**: ``sys.executable`` is ``python.exe`` inside a venv; we
      still return its directory so :func:`engine_available` returns
      False and callers fall back to system PATH.
    """
    return Path(sys.executable).resolve().parent


def bundled_node_dir() -> Path:
    """Directory holding the portable Node runtime (and ``npm.cmd``)."""
    return _install_root() / "engine" / "node"


def bundled_node() -> Path:
    """Path to the bundled runtime (``blank-ai.exe``, renamed from node)."""
    return bundled_node_dir() / "blank-ai.exe"


def bundled_engine_cli() -> Path:
    """Path to the AI engine entry script (``rt/entry.js``)."""
    return _install_root() / "engine" / "cli" / "rt" / "entry.js"


def bundled_engine_cmd() -> Path:
    """Path to the ``blank-ai.cmd`` launcher in the engine/node dir."""
    return bundled_node_dir() / "blank-ai.cmd"


def engine_available() -> bool:
    """Return True iff both the bundled Node and CLI exist on disk."""
    return bundled_node().is_file() and bundled_engine_cli().is_file()


def cli_path_for_sdk() -> Optional[str]:
    """Return the launcher path for the agent SDK, or None for dev."""
    if engine_available():
        return str(bundled_engine_cmd())
    return None


def prepare_env_for_bundled_engine() -> None:
    """Prepend the bundled runtime dir to PATH so the engine finds it."""
    if not engine_available():
        return
    node_dir = str(bundled_node_dir())
    current = os.environ.get("PATH", "")
    if current.startswith(node_dir + os.pathsep):
        return
    os.environ["PATH"] = node_dir + os.pathsep + current
