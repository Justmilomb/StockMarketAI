"""One-command release flow for blank.

Two paths, picked at the top of the prompt:

* **remote** (default) — bump the version locally, commit, tag ``vX.Y.Z``
  and push. The ``.github/workflows/release.yml`` workflow then builds
  the Windows .exe on a GitHub-hosted runner, attaches it to the
  GitHub Release, and POSTs a row into ``/api/admin/releases`` so
  every desktop client sees the update on its next heartbeat. No
  local PyInstaller / Inno Setup needed.

* **local** — original flow: bump version, run ``build.bat`` here,
  pause for an Inno Setup compile, compute the SHA256, push to GitHub
  Releases manually with ``gh``, and print the values to paste into
  the admin panel.

Usage::

    python scripts/release.py
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "Justmilomb/StockMarketAI"


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
    """Probe GitHub for a release with this tag."""
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", REPO],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _delete_release(tag: str) -> None:
    """Delete an existing GitHub release *and* its tag."""
    _run([
        "gh", "release", "delete", tag,
        "--repo", REPO,
        "--cleanup-tag",
        "--yes",
    ])


def _git(*args: str, capture: bool = False) -> str:
    """Run a git subcommand, surfacing failures with the same wording
    we use everywhere else."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"\ngit {' '.join(args)} failed (exit {result.returncode}): "
            f"{(result.stderr or '').strip()}",
        )
    return (result.stdout or "").strip()


def _ensure_clean_worktree() -> None:
    """Refuse to release on top of uncommitted changes.

    A dirty worktree means the bumped files would land in a commit
    alongside whatever is staged/unstaged — which is exactly the kind
    of "what did I actually ship" mystery the version-bump script is
    supposed to eliminate.
    """
    porcelain = _git("status", "--porcelain", capture=True)
    if porcelain:
        print("  Uncommitted changes detected:")
        for line in porcelain.splitlines():
            print(f"    {line}")
        raise SystemExit(
            "\nCommit or stash your changes before tagging a release.",
        )


def _release_remote(new_version: str) -> None:
    """Bump → commit → tag → push. CI does the heavy lifting."""
    tag = f"v{new_version}"

    print()
    print("── Sanity checks ──────────────────────────────────────────────")
    _ensure_clean_worktree()
    if _release_exists(tag):
        choice = input(f"  Release {tag} already exists on GitHub. Re-run CI for it? [y/N]: ").strip().lower()
        if choice != "y":
            raise SystemExit("Aborting — bump to a new version or delete the existing release.")
        # Re-running CI on an existing tag means triggering
        # workflow_dispatch with that tag input, not re-tagging. Bail
        # out and tell the operator how to do it from the UI; scripting
        # workflow_dispatch needs a PAT, which we deliberately don't
        # require here.
        print()
        print("  To rebuild an existing tag without changing the version:")
        print(f"    gh workflow run release.yml --ref main -f tag={tag}")
        print()
        sys.exit(0)

    # 1. Bump (skip if already at target).
    print()
    print("── Bumping version ────────────────────────────────────────────")
    if new_version != _current_version():
        _run([sys.executable, str(ROOT / "scripts" / "bump_version.py"), new_version])
    else:
        print(f"  Already at {new_version} — skipping bump.")

    # 2. Commit any version-bump changes.
    porcelain = _git("status", "--porcelain", capture=True)
    if porcelain:
        print()
        print("── Committing bump ────────────────────────────────────────────")
        _git("add", "-A")
        _git("commit", "-m", f"chore(release): bump to {new_version}")
    else:
        print("  No file changes to commit.")

    # 3. Tag + push.
    print()
    print("── Tagging + pushing ──────────────────────────────────────────")
    _git("tag", "-a", tag, "-m", f"blank {tag}")
    _git("push", "origin", "HEAD")
    _git("push", "origin", tag)

    # 4. Tell the operator where to watch.
    print()
    print("───────────────────────────────────────────────────────────────")
    print(f"  Pushed tag {tag}.  CI is now building the Windows installer.")
    print()
    print(f"  Watch:  gh run watch --repo {REPO}")
    print(f"  Or:     https://github.com/{REPO}/actions/workflows/release.yml")
    print()
    print("  When CI succeeds:")
    print("    * blank-setup.exe is attached to the GitHub Release")
    print("    * /api/version starts pointing every running client")
    print("      at the new download_url within the next heartbeat")
    print("───────────────────────────────────────────────────────────────")
    print()


def _release_local(new_version: str) -> None:
    """Original flow — build + sign + Inno Setup compile on this box,
    then push the artefact via ``gh`` directly. Use this when you
    can't (or don't want to) run CI."""
    current = _current_version()

    # 1. Bump (skip if already at target).
    print()
    print("── Bumping version ─────────────────────────────────────────────")
    if new_version == current:
        print(f"  Already at {new_version} — skipping bump.")
    else:
        _run([sys.executable, str(ROOT / "scripts" / "bump_version.py"), new_version])

    # 2. Stage the bundled AI engine.
    print()
    _run([sys.executable, str(ROOT / "scripts" / "prepare_engine.py")])

    # 3. Build.
    print()
    print("── Building exe ────────────────────────────────────────────────")
    _run(["cmd", "/c", str(ROOT / "build.bat")], cwd=str(ROOT))

    # 4. Installer compile pause (kept for boxes without ISCC.exe).
    installer = ROOT / "dist" / "blank-setup.exe"
    if not installer.exists():
        print()
        print("── Compile the installer ───────────────────────────────────────")
        print("  ► Open Inno Setup Compiler")
        print("  ► File → Open → installer\\blank.iss")
        print("  ► Build → Compile  (or press F9)")
        print()
        _pause("  Press Enter once dist\\blank-setup.exe is ready...")
        if not installer.exists():
            raise SystemExit("dist/blank-setup.exe not found — aborting.")

    # 5. SHA256.
    print()
    print("── Computing SHA256 ────────────────────────────────────────────")
    sha = _sha256(installer)
    size_mb = installer.stat().st_size / 1_048_576
    print(f"  {sha}")
    print(f"  ({size_mb:.1f} MB)")

    # 6. GitHub release.
    print()
    print("── Pushing to GitHub Releases ──────────────────────────────────")
    notes = input("  Release notes (one line, Enter to skip): ").strip()
    if not notes:
        notes = f"blank v{new_version}"

    tag = f"v{new_version}"
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
        "--repo", REPO,
        "--title", f"blank {tag}",
        "--notes", notes,
        "--latest",
    ])

    # 7. Admin panel instructions.
    download_url = (
        f"https://github.com/{REPO}/releases/download/{tag}/blank-setup.exe"
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


def main() -> None:
    current = _current_version()

    print()
    print(f"  Current version : {current}")
    new_version = input("  New version     : ").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        raise SystemExit(f"Invalid version: {new_version!r} — must be X.Y.Z")

    print()
    print("  Build path:")
    print("    [r] remote — tag + push, GitHub Actions builds (default)")
    print("    [l] local  — build .exe + installer here")
    choice = input("  Choose [r/l] (Enter = r): ").strip().lower() or "r"

    if choice.startswith("l"):
        _release_local(new_version)
    else:
        _release_remote(new_version)


if __name__ == "__main__":
    main()
