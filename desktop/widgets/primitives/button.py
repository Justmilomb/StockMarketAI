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


def _repolish(w: QWidget) -> None:
    """Force Qt to re-evaluate stylesheet selectors after a property changes.

    Required whenever a dynamic property used in a QSS selector
    (``QPushButton[variant="primary"]`` etc.) is assigned after the
    widget has been constructed. Without this, Qt keeps the initially
    computed style and the variant-specific rules never apply.
    """
    style = w.style()
    if style is None:
        return
    style.unpolish(w)
    style.polish(w)
    w.update()


def apply_variant(button: QPushButton, variant: str) -> None:
    """Set the ``variant`` dynamic property and re-polish the button."""
    button.setProperty("variant", variant)
    _repolish(button)


class _BaseButton(QPushButton):
    """Shared defaults (cursor, uppercase) for every variant."""

    variant: str = ""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text.upper() if text else "", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("variant", self.variant)
        # Dynamic property selectors (QPushButton[variant="primary"]) only
        # re-evaluate after unpolish/polish. Without this the button picks
        # up the default QSS rules and the variant-specific text colour
        # never applies — which is how the "invisible button text"
        # regression crept back in.
        _repolish(self)


class PrimaryButton(_BaseButton):
    """Solid green button for the main action in a dialog or card."""

    variant = "primary"


class SecondaryButton(_BaseButton):
    """Default hairline button — transparent with a 1 px white-alpha border."""

    variant = "secondary"


class GhostButton(_BaseButton):
    """Borderless button — used for tertiary actions like 'Skip' or 'Close'."""

    variant = "ghost"
