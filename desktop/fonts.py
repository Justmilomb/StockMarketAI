"""Bundle + register the two website fonts (Outfit, JetBrains Mono).

The website loads Outfit and JetBrains Mono from Google Fonts. For the
desktop app we either bundle TTFs under ``desktop/assets/fonts/`` and
register them with ``QFontDatabase`` at startup, or we fall back to the
system stack specified in ``desktop.tokens`` (``Segoe UI`` / ``Consolas``
on Windows).

This module is idempotent: calling :func:`register_app_fonts` twice is
safe — the database de-duplicates by file path. Missing fonts are logged
as debug, never as errors — the app is fully usable with fallbacks.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _fonts_dir() -> Path:
    """Resolve the directory holding bundled TTF files.

    Works for both the PyInstaller frozen build (``sys._MEIPASS``) and
    a dev checkout (``desktop/assets/fonts``).
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "."))
        return base / "desktop" / "assets" / "fonts"
    return Path(__file__).resolve().parent / "assets" / "fonts"


# Family stems we look for. We accept either the family-per-file layout
# (Outfit-Regular.ttf, Outfit-Bold.ttf, …) or a single variable-font
# file (Outfit.ttf, Outfit[wght].ttf, …). Whichever is present is fine.
_FAMILY_PATTERNS: List[str] = [
    "Outfit*.ttf",
    "Outfit*.otf",
    "JetBrainsMono*.ttf",
    "JetBrainsMono*.otf",
    "JetBrains*Mono*.ttf",
    "JetBrains*Mono*.otf",
]


def register_app_fonts() -> List[str]:
    """Register every bundled TTF/OTF under ``assets/fonts``.

    Returns the list of families that were actually loaded (useful for
    debug logging and tests). Silent no-op if the folder doesn't exist
    or if PySide6 isn't installed.
    """
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:  # PySide6 missing (test env)
        return []

    folder = _fonts_dir()
    if not folder.exists():
        logger.debug("No bundled fonts dir at %s — using system fallbacks", folder)
        return []

    loaded: List[str] = []
    for pattern in _FAMILY_PATTERNS:
        for path in folder.glob(pattern):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                logger.debug("Could not register font %s", path.name)
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            for fam in families:
                if fam not in loaded:
                    loaded.append(fam)

    if loaded:
        logger.info("Registered bundled fonts: %s", ", ".join(loaded))
    else:
        logger.debug("No bundled fonts found in %s", folder)
    return loaded
