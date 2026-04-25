"""Bundled-model resolver.

The desktop installer ships a handful of HuggingFace models inside
``desktop/assets/models/<slug>``. At runtime each loader asks this
module first; if the slug exists on disk we hand back the absolute
path and the loader passes that to ``from_pretrained`` (which
recognises a local directory and skips the download). Missing
bundles fall through to the regular HF repo id, so source runs
and incomplete builds still work — they just download on first use.

Slugs we ship:

  * ``kronos-tokenizer`` — NeoQuasar/Kronos-Tokenizer-base
  * ``kronos-base``      — NeoQuasar/Kronos-base (102M params)
  * ``finbert``          — ProsusAI/finbert
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _bundle_root() -> Path:
    """Where the spec drops bundled models. Differs between source + frozen runs."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass) / "desktop" / "assets" / "models"
    # Source layout: core/local_models.py → repo root is one up from core/
    return Path(__file__).resolve().parent.parent / "desktop" / "assets" / "models"


def local_path(slug: str) -> Optional[Path]:
    """Return the bundled model directory for ``slug`` if it exists, else ``None``.

    "Exists" means the directory is present *and* non-empty — a stub
    directory left by a half-finished download must not be returned
    or ``from_pretrained`` will fail trying to read missing weights.
    """
    candidate = _bundle_root() / slug
    if not candidate.is_dir():
        return None
    try:
        if not any(candidate.iterdir()):
            return None
    except Exception:
        return None
    return candidate


def resolve(slug: str, hub_id: str) -> str:
    """Pick the bundled directory if present, else fall back to the hub id.

    Loaders should ``from_pretrained(resolve("kronos-small", "NeoQuasar/Kronos-small"))``
    so a build with bundled models stays offline-safe and a source
    checkout still works against the hub.
    """
    path = local_path(slug)
    return str(path) if path is not None else hub_id
