"""Stage the bundled AI engine for the installer.

Run before ``scripts/release.py`` / ``ISCC.exe installer\\bloomberg.iss``.
The result is a ``build/engine/`` tree Inno Setup bundles into
``{app}/engine/``:

    build/engine/node/   ← portable Node for Windows (~30MB)
    build/engine/cli/    ← npm --prefix target for @anthropic-ai/claude-code

What this script does:

1. Download ``node-v20.x.x-win-x64.zip`` from nodejs.org (skipped if
   the target node.exe is already present, so re-runs are cheap).
2. Extract it into ``build/engine/node/``, stripping the top-level
   ``node-v20.x.x-win-x64/`` directory Node's zip wraps everything in.
3. Run ``build/engine/node/npm.cmd install @anthropic-ai/claude-code``
   with ``--prefix build/engine/cli`` so the package lands at
   ``build/engine/cli/node_modules/@anthropic-ai/claude-code/``.
4. Sanity-check that ``cli.js`` exists — if it doesn't, Inno Setup
   would happily bundle an empty tree and users would get a broken
   app on first launch.

Legal note: the Node.js Windows zip is MIT-licensed and freely
redistributable. The ``@anthropic-ai/claude-code`` package is
distributed on npm under its own terms, same as any other npm
dependency; bundling it in our installer is mechanically identical
to how Electron apps ship every dep they use.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "engine"
NODE_DIR = BUILD_DIR / "node"
CLI_DIR = BUILD_DIR / "cli"

# Pinned Node version — bump intentionally. 20.x is current LTS as of
# the v1.0.0 launch and is known to run @anthropic-ai/claude-code
# without warnings.
NODE_VERSION = "20.18.1"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64"
NODE_ZIP_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}.zip"

CLI_PACKAGE = "@anthropic-ai/claude-code"
CLI_JS_RELATIVE = Path("node_modules") / "@anthropic-ai" / "claude-code" / "cli.js"


def _log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _download_node_zip(target: Path) -> None:
    """Download the pinned Node zip into ``target``.

    Streams the response to disk so we don't have a 30MB buffer in
    memory — the build box has plenty of RAM but this is free.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Downloading {NODE_ZIP_URL}")
    with urllib.request.urlopen(NODE_ZIP_URL) as resp, target.open("wb") as out:
        shutil.copyfileobj(resp, out)
    _log(f"Saved → {target} ({target.stat().st_size / 1_048_576:.1f} MB)")


def _extract_node_zip(zip_path: Path, dest: Path) -> None:
    """Extract the Node zip into ``dest`` with the top dir stripped.

    The upstream zip wraps everything in ``node-v20.x.x-win-x64/``.
    We strip that so ``node.exe`` and ``npm.cmd`` land directly
    under ``dest``, matching the layout ``core/agent/paths.py``
    expects.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    _log(f"Extracting → {dest}")
    prefix = f"{NODE_ARCHIVE}/"
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix):]
            if not relative:
                continue
            out_path = dest / relative
            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out_path.open("wb") as fh:
                shutil.copyfileobj(src, fh)


def _ensure_node_present() -> None:
    """Make sure ``node.exe`` + ``npm.cmd`` exist under ``NODE_DIR``."""
    node_exe = NODE_DIR / "node.exe"
    npm_cmd = NODE_DIR / "npm.cmd"
    if node_exe.is_file() and npm_cmd.is_file():
        _log("Node runtime already staged — skipping download.")
        return

    zip_path = BUILD_DIR / f"{NODE_ARCHIVE}.zip"
    if not zip_path.is_file():
        _download_node_zip(zip_path)
    else:
        _log(f"Using cached {zip_path.name}")
    _extract_node_zip(zip_path, NODE_DIR)

    if not node_exe.is_file() or not npm_cmd.is_file():
        raise SystemExit(
            "Node extraction failed: node.exe or npm.cmd missing after unzip",
        )


def _run(cmd: Iterable[str], cwd: Path | None = None) -> None:
    """Thin ``subprocess.run`` wrapper that SystemExits on failure."""
    cmd_list = list(cmd)
    _log(f"$ {' '.join(cmd_list)}")
    result = subprocess.run(cmd_list, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise SystemExit(
            f"Command failed (exit {result.returncode}): {' '.join(cmd_list)}",
        )


def _install_cli_package() -> None:
    """Run ``npm install`` into ``CLI_DIR`` using the staged Node."""
    CLI_DIR.mkdir(parents=True, exist_ok=True)
    npm_cmd = NODE_DIR / "npm.cmd"
    # --prefix puts node_modules/ under CLI_DIR, --no-audit /
    # --no-fund keep output small, --omit=dev avoids shipping test
    # tooling we don't need at runtime.
    _run(
        [
            str(npm_cmd),
            "install",
            CLI_PACKAGE,
            "--prefix", str(CLI_DIR),
            "--no-audit",
            "--no-fund",
            "--omit=dev",
        ],
        cwd=CLI_DIR,
    )

    cli_js = CLI_DIR / CLI_JS_RELATIVE
    if not cli_js.is_file():
        raise SystemExit(
            f"npm install appeared to succeed but {cli_js} is missing — "
            "something is wrong with the CLI package layout.",
        )
    _log(f"CLI staged → {cli_js}")


def main() -> None:
    print()
    print("── Preparing bundled AI engine ────────────────────────────────")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_node_present()
    _install_cli_package()
    print()
    print("  Engine ready.")
    print(f"    node : {NODE_DIR}")
    print(f"    cli  : {CLI_DIR / CLI_JS_RELATIVE}")
    print()


if __name__ == "__main__":
    main()
