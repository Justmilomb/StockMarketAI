"""Central gating helper — every interactive action routes through
``require_auth(parent, action)``.

When signed in: runs the action.
When signed out: shows a small non-modal toast near the parent widget
saying 'sign in to use blank' and emits a bus signal so the main
window can raise the sign-in dialog."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QWidget

from desktop import tokens as T
from desktop.auth_state import auth_state


class _AuthGateBus(QObject):
    signin_requested = Signal()


_bus = _AuthGateBus()


def bus() -> _AuthGateBus:
    return _bus


def _toast(parent: QWidget, text: str) -> None:
    lbl = QLabel(text.upper(), parent)
    lbl.setWindowFlags(Qt.ToolTip)
    lbl.setAttribute(Qt.WA_DeleteOnClose)
    lbl.setStyleSheet(
        f"QLabel {{ background: {T.BG_0}; border: 1px solid {T.ACCENT_HEX};"
        f" color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding: 8px 14px; }}"
    )
    lbl.adjustSize()
    try:
        centre = parent.mapToGlobal(parent.rect().center())
        lbl.move(centre.x() - lbl.width() // 2, centre.y() - lbl.height() // 2)
    except Exception:
        pass
    lbl.show()
    QTimer.singleShot(2200, lbl.close)


def require_auth(parent: QWidget, action: Callable[[], None]) -> None:
    """Run ``action`` if the user is signed in. Otherwise toast a nudge
    and emit the bus signal so the window can raise the sign-in dialog."""
    if auth_state().is_signed_in:
        action()
        return
    _toast(parent, "sign in to use blank")
    _bus.signin_requested.emit()
