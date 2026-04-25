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
    plan: str = "starter"
    commission_pct: float = 20.0
    monthly_fee: float = 0.0
    is_dev: bool = False


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

    @property
    def plan(self) -> str:
        return self._snap.plan

    @property
    def commission_pct(self) -> float:
        return self._snap.commission_pct

    @property
    def monthly_fee(self) -> float:
        return self._snap.monthly_fee

    @property
    def is_dev(self) -> bool:
        return self._snap.is_dev

    def set_signed_in(self, email: str, name: str = "", avatar_id: int = 0) -> None:
        self._snap = AuthSnapshot(
            is_signed_in=True, email=email, name=name, avatar_id=avatar_id,
            plan=self._snap.plan,
            commission_pct=self._snap.commission_pct,
            monthly_fee=self._snap.monthly_fee,
            is_dev=self._snap.is_dev,
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
            plan=self._snap.plan,
            commission_pct=self._snap.commission_pct,
            monthly_fee=self._snap.monthly_fee,
            is_dev=self._snap.is_dev,
        )
        self.changed.emit()

    def set_plan(
        self,
        plan: str,
        commission_pct: float,
        monthly_fee: float,
        is_dev: bool = False,
    ) -> None:
        """Update the plan info; broadcast so UI fee badges refresh."""
        self._snap = AuthSnapshot(
            is_signed_in=self._snap.is_signed_in,
            email=self._snap.email,
            name=self._snap.name,
            avatar_id=self._snap.avatar_id,
            plan=str(plan or "starter"),
            commission_pct=float(commission_pct),
            monthly_fee=float(monthly_fee),
            is_dev=bool(is_dev),
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
