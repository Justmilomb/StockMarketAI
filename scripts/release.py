"""One-command release flow for blank.

Usage:
    python scripts/release.py

Steps:
    1. Show current version, ask for new version
    2. Bump all four version sources
    3. Stage the bundled AI engine (portable Node + claude-code CLI)
    4. Run build.bat (PyInstaller + Inno Setup if available)
    5. Pause for manual Inno Setup compile if needed
    6. Compute SHA256 of dist/BlankSetup.exe
    7. Push to GitHub Releases
    8. Print exact admin-panel values to publish the update
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


def _release_exists(tag: str) -> bool:
    """Probe GitHub for a release with this tag.

    ``gh release view`` exits non-zero when the release is missing; we
    swallow that and return False. Any other non-zero exit (auth, rate
    limit) is treated as 'unknown → assume absent' since the subsequent
    ``gh release create`` will surface the real error with a better
    message than we could fabricate here.
    """
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", "Justmilomb/StockMarketAI"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _delete_release(tag: str) -> None:
    """Delete an existing GitHub release *and* its tag.

    ``--cleanup-tag`` removes the underlying git tag too, otherwise
    ``gh release create`` would refuse to recreate it. ``--yes`` skips
    the interactive confirmation — we've already asked the user at the
    outer level.
    """
    _run([
        "gh", "release", "delete", tag,
        "--repo", "Justmilomb/StockMarketAI",
        "--cleanup-tag",
        "--yes",
    ])


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

    # ── 2. Stage the bundled AI engine ───────────────────────────────────
    # Downloads Node + runs `npm install @anthropic-ai/claude-code`
    # into build/engine/, which bloomberg.iss then bundles into
    # {app}/engine/. Idempotent: re-runs are cheap (it skips the
    # Node download when the extracted runtime already exists).
    print()
    _run([sys.executable, str(ROOT / "scripts" / "prepare_engine.py")])

    # ── 3. Build ─────────────────────────────────────────────────────────
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

    # If a release already exists for this tag, offer to replace it.
    # Without this the flow crashes at the end of a long build with an
    # unhelpful "release already exists" from gh — awful UX when you
    # just want to re-publish v1.0.0 after a fix.
    if _release_exists(tag):
        print(f"  ⚠  Release {tag} already exists on GitHub.")
        choice = input("  Delete and re-create it? [y/N]: ").strip().lower()
        if choice != "y":
            raise SystemExit(
                f"Aborting: {tag} already exists. "
                f"Bump to a new version or re-run and confirm the replace.",
            )
        print(f"  Deleting existing release {tag}...")
        _delete_release(tag)

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
