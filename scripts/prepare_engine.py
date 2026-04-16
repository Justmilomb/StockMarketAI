"""Stage the bundled AI engine for the installer.

Run before ``scripts/release.py`` / the Inno Setup compile step.
The result is a ``build/engine/`` tree the ``installer/blank.iss``
bundles into ``{app}/engine/``:

    build/engine/node/   <- portable Node runtime for Windows
    build/engine/cli/rt/ <- flattened AI engine runtime (entry.js + vendor)

Steps:
1. Download the pinned Node zip from nodejs.org (skipped on re-run).
2. Extract into ``build/engine/node/``.
3. npm-install the AI engine CLI into a temp tree.
4. Flatten the npm tree into ``build/engine/cli/rt/`` so no
   third-party package names survive in the shipped directory
   structure.
5. Rebrand ``node.exe`` -> ``blank-ai.exe`` and write a launcher.
6. Verify no third-party brand names leak in any file/dir path.
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

# Pinned Node version — bump intentionally. 20.x is current LTS.
NODE_VERSION = "20.18.1"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64"
NODE_ZIP_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}.zip"

CLI_PACKAGE = "@anthropic-ai/claude-code"
CLI_JS_RELATIVE = Path("node_modules") / "@anthropic-ai" / "claude-code" / "cli.js"

# Flattened runtime directory — the shipped layout after repackaging.
RT_DIR = CLI_DIR / "rt"

# Strings that must not appear in any shipped file/dir path.
_BANNED_STRINGS = ("claude", "anthropic")


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


def _flatten_engine() -> None:
    """Repackage the npm tree into a flat directory with no brand names.

    Copies only the files the runtime actually needs (entry script +
    vendor binaries) into ``build/engine/cli/rt/``, then deletes the
    original npm tree so no third-party package paths survive.
    """
    src_pkg = CLI_DIR / "node_modules" / "@anthropic-ai" / "claude-code"
    src_cli_js = src_pkg / "cli.js"
    src_vendor = src_pkg / "vendor"

    if not src_cli_js.is_file():
        raise SystemExit(f"Cannot flatten: {src_cli_js} not found")

    # Wipe any previous flatten so re-runs are clean.
    if RT_DIR.exists():
        shutil.rmtree(RT_DIR)
    RT_DIR.mkdir(parents=True)

    # Copy the single entry script.
    shutil.copy2(src_cli_js, RT_DIR / "entry.js")
    _log(f"Copied cli.js -> rt/entry.js")

    # Copy vendor binaries (ripgrep, audio-capture, seccomp).
    if src_vendor.is_dir():
        shutil.copytree(src_vendor, RT_DIR / "vendor")
        _log("Copied vendor/ -> rt/vendor/")

    # Remove the entire npm tree — only rt/ survives.
    for item in ("node_modules", "package.json", "package-lock.json"):
        target = CLI_DIR / item
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
    _log("Deleted npm tree — only rt/ remains")


def _rebrand_engine() -> None:
    """Rename node.exe and write a launcher with no brand names."""
    src = NODE_DIR / "node.exe"
    dst = NODE_DIR / "blank-ai.exe"
    if dst.is_file():
        _log("blank-ai.exe already present — skipping rebrand.")
    else:
        shutil.copy2(src, dst)
        _log(f"Copied node.exe -> {dst.name}")

    # Launcher points at the flattened rt/entry.js path.
    launcher = NODE_DIR / "blank-ai.cmd"
    launcher.write_text(
        '@echo off\r\n'
        '"%~dp0blank-ai.exe" "%~dp0..\\cli\\rt\\entry.js" %*\r\n',
        encoding="utf-8",
    )
    _log(f"Wrote launcher -> {launcher.name}")


def _verify_clean() -> None:
    """Walk build/engine/ and fail if any path contains banned strings."""
    violations: list[str] = []
    for path in BUILD_DIR.rglob("*"):
        name_lower = path.name.lower()
        for banned in _BANNED_STRINGS:
            if banned in name_lower:
                violations.append(str(path.relative_to(BUILD_DIR)))
    if violations:
        raise SystemExit(
            "Brand leak check failed — these paths contain banned strings:\n"
            + "\n".join(f"  {v}" for v in violations),
        )


def main() -> None:
    print()
    print("-- Preparing bundled AI engine --")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_node_present()
    _install_cli_package()
    _flatten_engine()
    _rebrand_engine()
    _verify_clean()
    print()
    print("  Engine ready (clean).")
    print(f"    runtime : {NODE_DIR / 'blank-ai.exe'}")
    print(f"    entry   : {RT_DIR / 'entry.js'}")
    print()


if __name__ == "__main__":
    main()
