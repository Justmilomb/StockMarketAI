"""Top-right profile widget.

Renders a small circular avatar (chosen during signup) as the button
face. Signed-out state shows a neutral grey placeholder labelled
"sign in". Clicking while signed in opens a dropdown with shortcuts to
the Account Dashboard, Settings, and sign out.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from desktop import tokens as T
from desktop.auth import clear_token
from desktop.auth_state import auth_state
from desktop.avatars import avatar_icon_size, placeholder_pixmap, render_avatar


class ProfileButton(QToolButton):
    """Circular avatar with sign-in aware dropdown.

    Emits :attr:`signin_requested` when the signed-out placeholder is
    clicked, and :attr:`dashboard_requested` / :attr:`settings_requested`
    when the matching menu item is chosen. The parent wires those to the
    panels it owns.
    """

    signin_requested = Signal()
    signout_requested = Signal()
    dashboard_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(avatar_icon_size())
        self.setFixedSize(QSize(36, 36))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._apply_stylesheet()
        auth_state().changed.connect(self._refresh)
        self.clicked.connect(self._on_click)
        self._refresh()

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            "QToolButton { background: transparent; border: none; padding: 0;"
            " margin: 0; }"
            f"QToolButton:hover {{ background: {T.BG_1}; }}"
            "QToolButton::menu-indicator { image: none; width: 0; }"
            f"QMenu {{ background: {T.BG_0}; color: {T.FG_0};"
            f" border: 1px solid {T.BORDER_1}; padding: 4px 0;"
            f" font-family: {T.FONT_MONO}; font-size: 10px; letter-spacing: 2px; }}"
            f"QMenu::item {{ padding: 6px 18px; }}"
            f"QMenu::item:selected {{ background: {T.BG_1}; color: {T.ACCENT_HEX}; }}"
            f"QMenu::separator {{ height: 1px; background: {T.BORDER_0};"
            f" margin: 4px 0; }}"
        )

    def _refresh(self) -> None:
        state = auth_state()
        if state.is_signed_in:
            self.setToolTip(state.email or state.name or "Account")
            self.setIcon(QIcon(render_avatar(state.avatar_id or 0, size=28)))
            self.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(self)
            act_dash = QAction("account dashboard", menu)
            act_dash.triggered.connect(self.dashboard_requested.emit)
            menu.addAction(act_dash)
            act_settings = QAction("settings", menu)
            act_settings.triggered.connect(self.settings_requested.emit)
            menu.addAction(act_settings)
            menu.addSeparator()
            act_out = QAction("sign out", menu)
            act_out.triggered.connect(self._on_signout)
            menu.addAction(act_out)
            self.setMenu(menu)
        else:
            self.setToolTip("Sign in")
            self.setIcon(QIcon(placeholder_pixmap(size=28)))
            self.setPopupMode(QToolButton.DelayedPopup)
            self.setMenu(None)

    def _on_click(self) -> None:
        if not auth_state().is_signed_in:
            self.signin_requested.emit()

    def _on_signout(self) -> None:
        clear_token()
        auth_state().set_signed_out()
        self.signout_requested.emit()
