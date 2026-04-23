"""Process-wide auth state.

Every widget that gates on sign-in reads from and subscribes to this
singleton. Qt's signal/slot system lets a widget refresh the instant
the user signs in or out, without polling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class AuthSnapshot:
    is_signed_in: bool = False
    email: str = ""
    name: str = ""
    avatar_id: int = 0


class AuthState(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._snap = AuthSnapshot()

    @property
    def snapshot(self) -> AuthSnapshot:
        return self._snap

    @property
    def is_signed_in(self) -> bool:
        return self._snap.is_signed_in

    @property
    def email(self) -> str:
        return self._snap.email

    @property
    def name(self) -> str:
        return self._snap.name

    @property
    def avatar_id(self) -> int:
        return self._snap.avatar_id

    def set_signed_in(self, email: str, name: str = "", avatar_id: int = 0) -> None:
        self._snap = AuthSnapshot(
            is_signed_in=True, email=email, name=name, avatar_id=avatar_id,
        )
        self.changed.emit()

    def set_avatar(self, avatar_id: int) -> None:
        """Update the avatar without otherwise touching sign-in state."""
        if not self._snap.is_signed_in:
            return
        self._snap = AuthSnapshot(
            is_signed_in=True,
            email=self._snap.email,
            name=self._snap.name,
            avatar_id=int(avatar_id),
        )
        self.changed.emit()

    def set_signed_out(self) -> None:
        self._snap = AuthSnapshot()
        self.changed.emit()


_singleton: Optional[AuthState] = None


def auth_state() -> AuthState:
    global _singleton
    if _singleton is None:
        _singleton = AuthState()
    return _singleton
