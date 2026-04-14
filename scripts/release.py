"""One-command release flow for blank.

Usage:
    python scripts/release.py

Steps:
    1. Show current version, ask for new version
    2. Bump all four version sources
    3. Run build.bat (PyInstaller + Inno Setup if available)
    4. Pause for manual Inno Setup compile if needed
    5. Compute SHA256 of dist/BlankSetup.exe
    6. Push to GitHub Releases
    7. Print exact admin-panel values to publish the update
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _current_version() -> str:
    text = (ROOT / "desktop" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("Could not read __version__ from desktop/__init__.py")
    return m.group(1)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _pause(prompt: str) -> None:
    input(prompt)


def _run(cmd: list[str], **kwargs) -> None:  # type: ignore[type-arg]
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"\nCommand failed (exit {result.returncode}): {' '.join(cmd)}")


def main() -> None:
    current = _current_version()

    print()
    print(f"  Current version : {current}")
    new_version = input("  New version     : ").strip()

    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        raise SystemExit(f"Invalid version: {new_version!r} — must be X.Y.Z")

    print()

    # ── 1. Bump (skip if already at target) ──────────────────────────────
    print("── Bumping version ─────────────────────────────────────────────")
    if new_version == current:
        print(f"  Already at {new_version} — skipping bump.")
    else:
        _run([sys.executable, str(ROOT / "scripts" / "bump_version.py"), new_version])

    # ── 2. Build ─────────────────────────────────────────────────────────
    import time as _time
    build_start = _time.time()
    print()
    print("── Building exe ────────────────────────────────────────────────")
    _run(["cmd", "/c", str(ROOT / "build.bat")], cwd=str(ROOT))

    # ── 3. Installer compile pause ───────────────────────────────────────
    installer = ROOT / "dist" / "BlankSetup.exe"

    print()
    print("── Compile the installer ───────────────────────────────────────")
    print("  ► Open Inno Setup Compiler")
    print("  ► File → Open → installer\\bloomberg.iss")
    print("  ► Build → Compile  (or press F9)")
    print()
    _pause("  Press Enter once dist\\BlankSetup.exe is ready...")
    if not installer.exists():
        raise SystemExit("dist/BlankSetup.exe not found — aborting.")

    # ── 4. SHA256 ────────────────────────────────────────────────────────
    print()
    print("── Computing SHA256 ────────────────────────────────────────────")
    sha = _sha256(installer)
    size_mb = installer.stat().st_size / 1_048_576
    print(f"  {sha}")
    print(f"  ({size_mb:.1f} MB)")

    # ── 5. GitHub release ────────────────────────────────────────────────
    print()
    print("── Pushing to GitHub Releases ──────────────────────────────────")
    notes = input("  Release notes (one line, Enter to skip): ").strip()
    if not notes:
        notes = f"blank v{new_version}"

    tag = f"v{new_version}"
    _run([
        "gh", "release", "create", tag,
        str(installer),
        "--repo", "Justmilomb/StockMarketAI",
        "--title", f"blank {tag}",
        "--notes", notes,
        "--latest",
    ])

    # ── 6. Admin panel instructions ──────────────────────────────────────
    download_url = (
        f"https://github.com/Justmilomb/StockMarketAI/releases/download/{tag}/BlankSetup.exe"
    )

    print()
    print("────────────────────────────────────────────────────────────────")
    print("  GitHub release pushed.  Now publish on the admin page:")
    print()
    print(f"  Version      {new_version}")
    print(f"  Download URL {download_url}")
    print(f"  SHA256       {sha}")
    print(f"  Notes        {notes}")
    print()
    print("  Admin page → Releases → fill in the fields above → Publish Release")
    print("────────────────────────────────────────────────────────────────")
    print()


if __name__ == "__main__":
    main()
