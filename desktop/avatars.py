"""Avatar helpers for the desktop app.

Resolves the path to a bundled avatar SVG (one of ``avatar_001.svg`` …
``avatar_100.svg`` under ``desktop/assets/avatars/``) and renders it to
a circular ``QPixmap`` so widgets can drop it in without knowing about
SVGs or rounding.

The server serves the same files at ``/api/avatars/{id}.svg``; bundling
them locally means the profile button has zero network dependency when
the user is offline.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

AVATAR_COUNT = 100


def avatars_dir() -> Path:
    """Directory holding the bundled avatar SVGs."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "."))
        return base / "desktop" / "assets" / "avatars"
    return Path(__file__).resolve().parent / "assets" / "avatars"


def avatar_path(avatar_id: int) -> Optional[Path]:
    """Absolute path to a single avatar SVG, or ``None`` if out of range
    or missing from the deploy."""
    if avatar_id < 1 or avatar_id > AVATAR_COUNT:
        return None
    path = avatars_dir() / f"avatar_{avatar_id:03d}.svg"
    return path if path.is_file() else None


def render_avatar(avatar_id: int, size: int = 28) -> QPixmap:
    """Render the given avatar as a circular pixmap. Falls back to a
    neutral green-on-black mark when the file is missing — prevents a
    pink placeholder if the bundle was built without the avatars dir."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Circular clip — a single path re-used for fill + mask.
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(path)

    path_svg = avatar_path(avatar_id)
    if path_svg is not None:
        renderer = QSvgRenderer(str(path_svg))
        if renderer.isValid():
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            return pm

    # Fallback: solid black disc with a subtle green ring.
    painter.fillPath(path, QBrush(QColor("#000000")))
    pen_rect = QRectF(1.5, 1.5, size - 3, size - 3)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#00ff87"))
    painter.drawEllipse(pen_rect)
    painter.end()
    return pm


def placeholder_pixmap(size: int = 28) -> QPixmap:
    """Neutral grey disc for the signed-out state."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    painter.fillPath(path, QBrush(QColor("#1a1a1a")))
    painter.setPen(QColor("#555555"))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(1.0, 1.0, size - 2, size - 2))
    painter.end()
    return pm


def avatar_icon_size() -> QSize:
    """Default size for the top-right profile button."""
    return QSize(28, 28)
