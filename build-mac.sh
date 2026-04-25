#!/usr/bin/env bash
# Build blank desktop application — macOS edition.
#
# Mirrors build.bat one-for-one but produces dist/blank.app instead of
# dist/blank.exe. The Inno Setup / signtool steps are replaced with
# their macOS equivalents (codesign + optional dmg pack).
#
# Usage:
#   ./build-mac.sh
#
# Env vars:
#   SKIP_MODEL_DOWNLOAD=1   skip the HuggingFace bundle pre-download
#   HF_TOKEN_READ=...       HF token (avoids anonymous rate-limits)
#   BLANK_CODESIGN_ID="..." Developer ID Application certificate name
#                           (e.g. "Developer ID Application: Foo Bar (TEAMID)")
#                           — when set, the .app is signed and you can
#                           ship a notarised dmg via the standard
#                           xcrun notarytool flow.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Activate venv ────────────────────────────────────────────────────────
if [ -f ".venv-mac/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv-mac/bin/activate"
elif [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
else
    echo "  No .venv-mac or .venv found — falling back to system python3."
    echo "  (Strongly recommended: python3 -m venv .venv-mac && pip install -r requirements-mac.txt)"
fi

# ── Bundle HuggingFace models (Kronos + FinBERT) ─────────────────────────
# Idempotent: skips slugs whose config.json already exists. Set
# SKIP_MODEL_DOWNLOAD=1 to bypass entirely.
if [ -z "${SKIP_MODEL_DOWNLOAD:-}" ]; then
    echo "Downloading bundled models..."
    if ! python scripts/download_models.py; then
        echo "  FAILED — model download errored. Set HF_TOKEN_READ if rate-limited,"
        echo "  or SKIP_MODEL_DOWNLOAD=1 to fall back to first-run downloads."
        exit 1
    fi
fi

# ── PyInstaller .app bundle ──────────────────────────────────────────────
echo "Building blank.app..."
pyinstaller installer/blank-mac.spec --clean
if [ ! -d "dist/blank.app" ]; then
    echo "  FAILED — check errors above"
    exit 1
fi
echo "  Done: dist/blank.app"

# ── Codesigning (when certificate is available) ──────────────────────────
# macOS will refuse to launch an unsigned .app downloaded from the
# internet. Local builds can still run via "right-click → Open" on the
# first launch. Set BLANK_CODESIGN_ID to skip the warning at distribution
# time. Notarisation (xcrun notarytool submit) is a separate step that
# expects a properly-signed bundle to start with — we don't run it here
# because it requires Apple Developer credentials.
if [ -n "${BLANK_CODESIGN_ID:-}" ]; then
    echo "Signing dist/blank.app with $BLANK_CODESIGN_ID..."
    codesign --deep --force \
        --options runtime \
        --sign "$BLANK_CODESIGN_ID" \
        --timestamp \
        dist/blank.app
    codesign --verify --deep --strict --verbose=2 dist/blank.app
    echo "  Signed"
else
    echo "  Skipping codesign (BLANK_CODESIGN_ID not set)"
fi

# ── Stage AI engine (Node + Claude CLI rebranded to blank-ai) ────────────
# Same staging script the Windows build uses; it auto-picks the macOS
# Node distribution when run on Darwin. The current scripts/prepare_engine.py
# is Windows-only; on macOS the engine is staged at first run by the
# desktop app, so we skip it here and leave a note. (When a macOS
# port of prepare_engine.py is added, swap this branch for an
# unconditional call.)
if [ ! -d "build/engine/node" ]; then
    echo "  Skipping AI engine staging — desktop will fetch on first run on macOS."
fi

# ── DMG pack (optional) ──────────────────────────────────────────────────
# create-dmg is the standard tool; brew install create-dmg. Skipped
# silently when not installed so a developer building locally without
# DMG tooling still gets a usable .app.
if command -v create-dmg >/dev/null 2>&1; then
    echo "Building blank-setup.dmg..."
    rm -f dist/blank-setup.dmg
    create-dmg \
        --volname "blank" \
        --volicon "desktop/assets/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 128 \
        --icon "blank.app" 175 190 \
        --hide-extension "blank.app" \
        --app-drop-link 425 190 \
        "dist/blank-setup.dmg" \
        "dist/blank.app"
    if [ -n "${BLANK_CODESIGN_ID:-}" ]; then
        echo "Signing dmg..."
        codesign --sign "$BLANK_CODESIGN_ID" --timestamp dist/blank-setup.dmg
    fi
    echo "  Done: dist/blank-setup.dmg"
else
    echo "  create-dmg not installed — skipping dmg packaging"
    echo "  (brew install create-dmg if you want one)"
fi

echo
echo "  Build complete."
