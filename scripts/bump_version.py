"""Bump the blank product version in all four sources at once.

blank's version lives in four places that must stay in lockstep:

1. ``desktop/__init__.py`` — ``__version__`` (what the running app
   reports; used by ``UpdateService`` for semver comparison)
2. ``version_info.py`` — Windows VERSIONINFO resource baked into the
   PyInstaller build so Explorer shows the right version on the .exe
3. ``installer/bloomberg.iss`` — Inno Setup's ``AppVersion`` used in
   the Control Panel "Apps" list and the installer wizard
4. ``server/app.py`` — the ``/api/version`` fallback string returned
   when the ``releases`` table is empty (keeps in-flight v1 clients
   happy during initial rollout)

Running ``python scripts/bump_version.py 2.0.1`` rewrites all four.
Idempotent: re-running with the same version is a no-op.

Fails loudly if any file is missing or the target pattern isn't found
— a silent partial bump is strictly worse than no bump, because it
creates a "which version is the real one" mystery at install time.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"bump_version: missing file {path}")
    return path.read_text(encoding="utf-8")


def _write_if_changed(path: Path, old: str, new: str) -> bool:
    # ASCII-only markers so this runs under cp1252 (default on
    # Windows consoles) without UnicodeEncodeError.
    if old == new:
        print(f"  -  {path.relative_to(ROOT)}  (already up to date)")
        return False
    path.write_text(new, encoding="utf-8")
    print(f"  OK {path.relative_to(ROOT)}")
    return True


def _sub_once(text: str, pattern: str, replacement: str, path: Path) -> str:
    """Replace exactly one match or raise — never silently miss."""
    new, count = re.subn(pattern, replacement, text, count=1)
    if count == 0:
        raise SystemExit(
            f"bump_version: pattern {pattern!r} not found in {path}"
        )
    return new


def _bump_desktop_init(version: str) -> bool:
    path = ROOT / "desktop" / "__init__.py"
    old = _read(path)
    new = _sub_once(
        old, r'__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', path,
    )
    return _write_if_changed(path, old, new)


def _bump_version_info(version: str) -> bool:
    """Rewrite filevers/prodvers tuples *and* the string fields."""
    path = ROOT / "version_info.py"
    old = _read(path)
    major, minor, patch = version.split(".")
    tup = f"({major}, {minor}, {patch}, 0)"
    new = old
    new = _sub_once(new, r"filevers=\([^)]*\)", f"filevers={tup}", path)
    new = _sub_once(new, r"prodvers=\([^)]*\)", f"prodvers={tup}", path)
    new = _sub_once(
        new,
        r'StringStruct\("FileVersion",\s*"[^"]+"\)',
        f'StringStruct("FileVersion", "{version}")',
        path,
    )
    new = _sub_once(
        new,
        r'StringStruct\("ProductVersion",\s*"[^"]+"\)',
        f'StringStruct("ProductVersion", "{version}")',
        path,
    )
    return _write_if_changed(path, old, new)


def _bump_installer(version: str) -> bool:
    path = ROOT / "installer" / "bloomberg.iss"
    old = _read(path)
    new = _sub_once(old, r"AppVersion=[^\r\n]+", f"AppVersion={version}", path)
    return _write_if_changed(path, old, new)


def _bump_server(version: str) -> bool:
    """Update the /api/version fallback string in server/app.py.

    Only the single literal inside the ``if not row`` fallback block is
    touched — the health endpoint's own version constant is left alone
    since it is the server's self-identifier, not the product version.
    """
    path = ROOT / "server" / "app.py"
    old = _read(path)
    # Match the specific fallback line within the /api/version handler.
    # Anchored loosely by looking for the dict key.
    new = _sub_once(
        old,
        r'"version":\s*"\d+\.\d+\.\d+",\s*\n\s*"download_url":\s*"https://github\.com/Justmilomb/StockMarketAI/releases/latest',
        f'"version": "{version}",\n            "download_url": "https://github.com/Justmilomb/StockMarketAI/releases/latest',
        path,
    )
    return _write_if_changed(path, old, new)


_BUMPERS: list[Callable[[str], bool]] = [
    _bump_desktop_init,
    _bump_version_info,
    _bump_installer,
    _bump_server,
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/bump_version.py X.Y.Z", file=sys.stderr)
        return 2
    version = argv[1].strip()
    if not _SEMVER.match(version):
        print(f"error: {version!r} is not a valid X.Y.Z version", file=sys.stderr)
        return 2

    print(f"bumping blank to {version}:")
    any_changed = False
    for bump in _BUMPERS:
        if bump(version):
            any_changed = True

    if not any_changed:
        print("(nothing to do — all sources already at this version)")
    else:
        print()
        print("next steps:")
        print("  1. git diff      # sanity check")
        print("  2. pytest tests/ # regressions")
        print("  3. build.bat     # dist/blank.exe + BlankSetup.exe")
        print("  4. upload BlankSetup.exe to GitHub Releases as v" + version)
        print("  5. /admin -> releases -> publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
