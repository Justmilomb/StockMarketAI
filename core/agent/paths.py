"""Single source of truth for the bundled AI engine location.

We ship a portable Node runtime + the ``@anthropic-ai/claude-code``
npm package inside the installer so users never need to run
``npm install`` themselves. On a frozen install the files live next
to the .exe:

    {app}/engine/node/node.exe
    {app}/engine/cli/node_modules/@anthropic-ai/claude-code/cli.js

In dev mode (running from source in a venv) the ``engine/`` dir is
absent — the runner and chat worker fall back to whatever ``claude``
is on ``PATH``. That keeps the dev workflow painless without forcing
contributors to build the bundled engine locally.

``AgentRunner`` and ``ChatWorker`` both call :func:`cli_path_for_sdk`
and pass the result to ``ClaudeAgentOptions(cli_path=...)``. When it
returns ``None``, the SDK runs its own CLI discovery which matches
the dev behaviour. Before constructing the options they also call
:func:`prepare_env_for_bundled_engine` so the bundled Node binary is
the one the SDK picks up when it spawns ``cli.js``.
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
    """Path to the bundled ``node.exe``."""
    return bundled_node_dir() / "node.exe"


def bundled_engine_cli() -> Path:
    """Path to the ``@anthropic-ai/claude-code`` ``cli.js`` entry script."""
    return (
        _install_root()
        / "engine"
        / "cli"
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "cli.js"
    )


def engine_available() -> bool:
    """Return True iff both the bundled Node and CLI exist on disk."""
    return bundled_node().is_file() and bundled_engine_cli().is_file()


def cli_path_for_sdk() -> Optional[str]:
    """Return a value suitable for ``ClaudeAgentOptions.cli_path``.

    If the bundled engine is present, return the ``cli.js`` path as a
    string so the SDK spawns it via our bundled Node (see
    :func:`prepare_env_for_bundled_engine` which prepends the Node dir
    to ``PATH``). Otherwise return ``None`` and let the SDK discover a
    system-installed ``claude`` itself — that's the dev path.
    """
    if engine_available():
        return str(bundled_engine_cli())
    return None


def prepare_env_for_bundled_engine() -> None:
    """Prepend the bundled Node dir to ``PATH`` so ``cli.js`` finds node.

    The SDK spawns the CLI via subprocess; the CLI's shebang maps to
    whatever ``node`` resolves to first on ``PATH``. Prepending our
    bundled Node dir guarantees the SDK uses the version we shipped
    and tested against, not whatever the user happens to have
    installed globally (or nothing at all).

    Safe to call multiple times — it's a no-op when the bundled
    engine is missing, and also a no-op when ``PATH`` already starts
    with our dir.
    """
    if not engine_available():
        return
    node_dir = str(bundled_node_dir())
    current = os.environ.get("PATH", "")
    if current.startswith(node_dir + os.pathsep):
        return
    os.environ["PATH"] = node_dir + os.pathsep + current
