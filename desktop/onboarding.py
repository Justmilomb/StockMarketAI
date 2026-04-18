"""Interactive first-launch onboarding tour.

Walks the user through every dockable panel with a spotlight overlay +
a popover. The overlay dims the whole window, cuts a rectangular hole
around the current target, and a floating card explains what the panel
does with Next / Skip controls. Shown exactly once — a marker file in
``user_data_dir()`` tracks completion.

Design notes:

* **Pure Qt widgets** so it works with the existing PySide6 stack and
  respects Qt's DPI scaling out of the box.
* The overlay is a top-level frameless widget parented to MainWindow.
  We position it precisely over the window and let the main window
  keep its size / keep events flowing; the overlay sits on top and
  intercepts clicks on everything except its own buttons.
* The popover auto-positions next to the target — right side first,
  falling back to left or below if there isn't room.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T


# ── Marker so we only show the tour once ─────────────────────────────

def _tour_marker_path() -> Path:
    try:
        from desktop.paths import user_data_dir
        return user_data_dir() / ".onboarding_complete"
    except Exception:
        return Path.home() / ".blank" / "onboarding_complete"


def _tour_has_run() -> bool:
    return _tour_marker_path().exists()


def _mark_tour_complete() -> None:
    path = _tour_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1", encoding="utf-8")


# ── Step definitions ─────────────────────────────────────────────────

@dataclass
class TourStep:
    kicker: str
    title: str
    body: str
    # Callable resolving to the target QWidget at display time so the
    # tour handles docks being moved/closed.
    target: Callable[[QMainWindow], Optional[QWidget]]


def _build_steps(window: QMainWindow) -> List[TourStep]:
    """Resolve steps against the MainWindow's dock widgets."""
    def dock(name: str) -> Callable[[QMainWindow], Optional[QWidget]]:
        def _resolve(win: QMainWindow) -> Optional[QWidget]:
            return getattr(win, name, None)
        return _resolve

    def panel(name: str) -> Callable[[QMainWindow], Optional[QWidget]]:
        def _resolve(win: QMainWindow) -> Optional[QWidget]:
            return getattr(win, name, None)
        return _resolve

    return [
        TourStep(
            kicker="01 · WATCHLIST",
            title="Your universe of tickers.",
            body=(
                "Live prices, day change, and news sentiment for every ticker "
                "you're tracking. The agent auto-adds anything it buys."
            ),
            target=dock("_watchlist_dock"),
        ),
        TourStep(
            kicker="02 · CHART",
            title="Candlesticks with a 20-day SMA.",
            body=(
                "Press G with a ticker selected to load its chart here. "
                "A faint PAPER watermark over this panel is the only "
                "signal that you're in paper mode."
            ),
            target=panel("chart_panel"),
        ),
        TourStep(
            kicker="03 · POSITIONS",
            title="What you own, live.",
            body=(
                "Quantity, average entry, current price, and unrealised P/L "
                "for every open position."
            ),
            target=dock("_positions_dock"),
        ),
        TourStep(
            kicker="04 · ORDERS",
            title="Recent orders — pending, filled, cancelled.",
            body=(
                "Everything the agent and you have sent to the broker in the "
                "last session."
            ),
            target=dock("_orders_dock"),
        ),
        TourStep(
            kicker="05 · AGENT",
            title="Start, stop, and watch the agent loop.",
            body=(
                "Click START to begin an autonomous trading cycle. The log "
                "below streams every thought, tool call, and decision."
            ),
            target=dock("_agent_dock"),
        ),
        TourStep(
            kicker="06 · CHAT",
            title="Talk to the agent.",
            body=(
                "Ask questions, request research, or challenge its decisions. "
                "The agent answers with live access to your account."
            ),
            target=dock("_chat_dock"),
        ),
        TourStep(
            kicker="07 · INFORMATION",
            title="News + research findings.",
            body=(
                "Curated market news, per-ticker sentiment, and the research "
                "swarm's latest findings — all in one stream."
            ),
            target=dock("_news_dock"),
        ),
        TourStep(
            kicker="08 · STATUS",
            title="Account and agent snapshot.",
            body=(
                "Balance, invested, total, unrealised P/L, cadence, and time "
                "since the agent's last iteration."
            ),
            target=dock("_settings_dock"),
        ),
    ]


# ── Overlay widget ───────────────────────────────────────────────────

class _SpotlightOverlay(QWidget):
    """Translucent overlay that cuts a rectangular hole over the target."""

    def __init__(self, parent: QMainWindow) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._target_rect = QRect()

    def set_target_rect(self, rect: QRect) -> None:
        self._target_rect = rect
        self.update()

    def paintEvent(self, event) -> None:  # Qt camelCase
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        full = QPainterPath()
        full.addRect(self.rect())
        hole = QPainterPath()
        if not self._target_rect.isEmpty():
            padded = self._target_rect.adjusted(-6, -6, 6, 6)
            hole.addRoundedRect(padded, 2, 2)
            full = full.subtracted(hole)

        painter.fillPath(full, QColor(0, 0, 0, 200))

        if not self._target_rect.isEmpty():
            painter.setPen(QColor(0, 255, 135, 160))
            painter.drawRoundedRect(
                self._target_rect.adjusted(-6, -6, 6, 6), 2, 2,
            )


class _PopoverCard(QFrame):
    """Floating info card pinned next to the spotlight."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("TourPopover")
        self.setStyleSheet(
            f"QFrame#TourPopover {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )
        self.setFixedWidth(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(0)

        self._kicker = QLabel()
        self._kicker.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        root.addWidget(self._kicker)

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 18px; font-weight: 500;"
            f" letter-spacing: -0.01em; padding: 6px 0 10px 0;"
        )
        root.addWidget(self._title)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px; line-height: 1.6;"
        )
        root.addWidget(self._body)

        root.addSpacing(14)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        root.addSpacing(12)

        foot = QHBoxLayout()
        foot.setSpacing(8)

        self._progress = QLabel()
        self._progress.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        foot.addWidget(self._progress, 1)

        self.skip_btn = QPushButton("SKIP")
        self.skip_btn.setProperty("variant", "ghost")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.skip_btn)

        self.back_btn = QPushButton("BACK")
        self.back_btn.setProperty("variant", "ghost")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.back_btn)

        self.next_btn = QPushButton("NEXT")
        self.next_btn.setProperty("variant", "primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        foot.addWidget(self.next_btn)

        root.addLayout(foot)

    def set_step(self, step: TourStep, index: int, total: int, is_last: bool) -> None:
        self._kicker.setText(step.kicker)
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._progress.setText(f"{index + 1} / {total}")
        self.next_btn.setText("DONE" if is_last else "NEXT")
        self.back_btn.setEnabled(index > 0)


class OnboardingTour:
    """Orchestrates the spotlight + popover over a MainWindow."""

    def __init__(self, window: QMainWindow) -> None:
        self._window = window
        self._steps = _build_steps(window)
        self._index = 0

        self._overlay = _SpotlightOverlay(window)
        self._overlay.setGeometry(window.rect())
        self._overlay.show()

        self._popover = _PopoverCard(window)
        self._popover.show()
        self._popover.raise_()

        self._popover.next_btn.clicked.connect(self._next)
        self._popover.back_btn.clicked.connect(self._back)
        self._popover.skip_btn.clicked.connect(self._finish)

        window.installEventFilter(_ResizeForwarder(self))
        QTimer.singleShot(50, self._render_current)

    # ── Public API ──────────────────────────────────────────────────

    def on_window_resized(self) -> None:
        self._overlay.setGeometry(self._window.rect())
        self._render_current()

    # ── Internals ───────────────────────────────────────────────────

    def _render_current(self) -> None:
        if self._index >= len(self._steps):
            self._finish()
            return
        step = self._steps[self._index]
        target = step.target(self._window)

        if target is None or not target.isVisible():
            # Skip unresolved targets but keep the step count truthful.
            self._index += 1
            self._render_current()
            return

        if isinstance(target, QDockWidget) and target.isFloating():
            target.setFloating(False)

        rect = self._target_rect_in_window(target)
        self._overlay.set_target_rect(rect)
        self._popover.set_step(
            step, self._index, len(self._steps),
            is_last=self._index == len(self._steps) - 1,
        )
        self._popover.adjustSize()
        self._position_popover(rect)
        self._popover.raise_()

    def _target_rect_in_window(self, target: QWidget) -> QRect:
        top_left = target.mapTo(self._window, QPoint(0, 0))
        return QRect(top_left, target.size())

    def _position_popover(self, target_rect: QRect) -> None:
        win_rect = self._window.rect()
        pop_size = self._popover.size()
        margin = 16

        candidates = [
            # Right of target
            QPoint(
                target_rect.right() + margin,
                target_rect.top() + (target_rect.height() - pop_size.height()) // 2,
            ),
            # Left of target
            QPoint(
                target_rect.left() - pop_size.width() - margin,
                target_rect.top() + (target_rect.height() - pop_size.height()) // 2,
            ),
            # Below target
            QPoint(
                target_rect.left() + (target_rect.width() - pop_size.width()) // 2,
                target_rect.bottom() + margin,
            ),
            # Above target
            QPoint(
                target_rect.left() + (target_rect.width() - pop_size.width()) // 2,
                target_rect.top() - pop_size.height() - margin,
            ),
        ]

        def fits(p: QPoint) -> bool:
            r = QRect(p, pop_size)
            return win_rect.contains(r) and not r.intersects(target_rect)

        chosen = next((p for p in candidates if fits(p)), candidates[0])
        # Clamp to the window so it never paints off-screen.
        x = max(margin, min(chosen.x(), win_rect.width() - pop_size.width() - margin))
        y = max(margin, min(chosen.y(), win_rect.height() - pop_size.height() - margin))
        self._popover.move(x, y)

    def _next(self) -> None:
        if self._index >= len(self._steps) - 1:
            self._finish()
            return
        self._index += 1
        self._render_current()

    def _back(self) -> None:
        if self._index == 0:
            return
        self._index -= 1
        self._render_current()

    def _finish(self) -> None:
        _mark_tour_complete()
        self._overlay.hide()
        self._popover.hide()
        self._overlay.deleteLater()
        self._popover.deleteLater()


class _ResizeForwarder:
    """Lightweight forwarder that nudges the tour on window resize."""

    def __init__(self, tour: "OnboardingTour") -> None:
        self._tour = tour

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Resize:
            self._tour.on_window_resized()
        return False


# ── Entry point ─────────────────────────────────────────────────────

_ACTIVE_TOUR: Optional[OnboardingTour] = None


def maybe_start_tour(window: QMainWindow) -> None:
    """Show the first-launch onboarding tour, or no-op if already run."""
    global _ACTIVE_TOUR
    if _tour_has_run():
        return
    # Wait one event-loop tick so the window has finished laying out.
    QTimer.singleShot(250, lambda: _start_tour(window))


def _start_tour(window: QMainWindow) -> None:
    global _ACTIVE_TOUR
    app = QApplication.instance()
    if app is None:
        return
    _ACTIVE_TOUR = OnboardingTour(window)
