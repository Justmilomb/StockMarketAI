"""Top-right profile widget.

Shows "SIGN IN" when signed out and the user's email + a dropdown
(account details / sign out) when signed in."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from desktop import tokens as T
from desktop.auth import clear_token
from desktop.auth_state import auth_state


class ProfileButton(QToolButton):
    signin_requested = Signal()
    signout_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QToolButton {{ color: {T.FG_0}; background: transparent;"
            f" border: 1px solid {T.BORDER_1}; padding: 4px 10px;"
            f" font-family: {T.FONT_MONO}; font-size: 10px; letter-spacing: 2px; }}"
            f"QToolButton:hover {{ border: 1px solid {T.ACCENT_HEX}; color: {T.ACCENT_HEX}; }}"
            f"QToolButton::menu-indicator {{ image: none; width: 0; }}"
        )
        auth_state().changed.connect(self._refresh)
        self.clicked.connect(self._on_click)
        self._refresh()

    def _refresh(self) -> None:
        state = auth_state()
        if state.is_signed_in:
            label = state.email or state.name or "ACCOUNT"
            self.setText(label.upper())
            self.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(self)
            act_account = menu.addAction("account details")
            act_account.setEnabled(False)  # Placeholder — account page TBD.
            act_out = menu.addAction("sign out")
            act_out.triggered.connect(self._on_signout)
            self.setMenu(menu)
        else:
            self.setText("SIGN IN")
            self.setPopupMode(QToolButton.DelayedPopup)
            self.setMenu(None)

    def _on_click(self) -> None:
        if not auth_state().is_signed_in:
            self.signin_requested.emit()

    def _on_signout(self) -> None:
        clear_token()
        auth_state().set_signed_out()
        self.signout_requested.emit()
