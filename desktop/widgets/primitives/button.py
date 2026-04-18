"""Button primitives matching the website's ``.btn`` / ``.btn-primary``.

Three variants:

* :class:`PrimaryButton` — solid green fill, black text (main CTA).
* :class:`SecondaryButton` — transparent with hairline border (default).
* :class:`GhostButton` — no border, hover fills with raised surface.

The variant is expressed via the ``variant`` dynamic property so the
global QSS in :mod:`desktop.theme` picks up the state automatically.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget


class _BaseButton(QPushButton):
    """Shared defaults (cursor, uppercase) for every variant."""

    variant: str = ""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text.upper() if text else "", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("variant", self.variant)


class PrimaryButton(_BaseButton):
    """Solid green button for the main action in a dialog or card."""

    variant = "primary"


class SecondaryButton(_BaseButton):
    """Default hairline button — transparent with a 1 px white-alpha border."""

    variant = "secondary"


class GhostButton(_BaseButton):
    """Borderless button — used for tertiary actions like 'Skip' or 'Close'."""

    variant = "ghost"
