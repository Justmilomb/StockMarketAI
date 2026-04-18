"""Full-window SVG-noise overlay — ports the ``body::before`` grain effect.

The marketing site paints an SVG fractal-noise texture over the whole
page at 4 % opacity. This widget does the equivalent for the desktop
app: a transparent top-level overlay that reuses a single cached
pixmap. Mouse events pass through.

The grain is a subtle touch; if PySide's compositor hates it on a
given machine, callers can simply skip instantiating the overlay.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget


def _build_noise_pixmap(size: int = 256) -> QPixmap:
    """Build a tileable mono-noise pixmap at 256x256."""
    import random
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    # Populate alpha with a cheap procedural noise. Not fractal — but
    # tile-friendly and good enough for a 4 % overlay nobody will
    # stare at.
    rng = random.Random(20260101)  # fixed seed so the pattern is deterministic
    for y in range(size):
        for x in range(size):
            a = rng.randint(0, 36)
            img.setPixelColor(x, y, QColor(255, 255, 255, a))
    return QPixmap.fromImage(img)


_CACHED_PIXMAP: Optional[QPixmap] = None


def _noise_pixmap() -> QPixmap:
    global _CACHED_PIXMAP
    if _CACHED_PIXMAP is None:
        _CACHED_PIXMAP = _build_noise_pixmap()
    return _CACHED_PIXMAP


class GrainOverlay(QWidget):
    """Transparent top-level overlay that tiles a noise pixmap."""

    def __init__(self, parent: Optional[QWidget] = None, opacity: float = 0.04) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._opacity = max(0.0, min(1.0, float(opacity)))
        if parent is not None:
            parent.installEventFilter(self)
            self.resize(parent.size())
            self.raise_()

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.resize(self.parent().size())
            self.raise_()
        return False

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt API
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        pm = _noise_pixmap()
        painter.drawTiledPixmap(QRect(0, 0, self.width(), self.height()), pm)
        painter.end()
