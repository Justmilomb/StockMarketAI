"""Dialogs for the single-active-session enforcement flow.

* :func:`prompt_takeover` — shown when the server returns 409 on
  ``/api/me/session/register``: another device is signed in. Returns
  ``True`` if the user wants to evict that device.
* :func:`show_taken_over` — shown when this terminal's heartbeat is
  rejected because a different device claimed the slot. The user can
  only acknowledge and the app quits.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMessageBox, QWidget


def prompt_takeover(parent: Optional[QWidget] = None) -> bool:
    """Ask whether to evict the other device. Returns True on confirm."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("blank")
    box.setText("blank is running on another device.")
    box.setInformativeText(
        "Only one blank terminal can run at a time per account. "
        "Take over and sign out the other device?",
    )
    take_over_btn = box.addButton("Take Over", QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(take_over_btn)
    _show = getattr(box, "exec")
    _show()
    return box.clickedButton() is take_over_btn


def show_taken_over(message: str, parent: Optional[QWidget] = None) -> None:
    """Tell the user their session was kicked. Modal — they only get OK."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("blank")
    box.setText("Your session was taken over.")
    box.setInformativeText(
        message or "blank was opened on another device. This terminal will close.",
    )
    box.setStandardButtons(QMessageBox.Ok)
    _show = getattr(box, "exec")
    _show()
