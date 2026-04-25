"""Interactive first-launch onboarding tour.

Walks the user through the app with a spotlight overlay + a popover.
The overlay dims the whole window, cuts a rectangular hole around the
current target, and a floating card explains the panel in plain
English with Next / Back / Skip controls.

The tour is written for people whose only finance knowledge is "the
stock market can make you money" — every sentence is short, every
concept is introduced from zero. Kept to 4 steps (watchlist, chart,
start/stop, chat) so new users aren't overwhelmed.

Shown on first launch (a marker file in ``user_data_dir()`` tracks
completion) and can be replayed at any time via the Help menu.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.widgets.primitives.button import apply_variant


# ── Marker so the tour only auto-shows once ──────────────────────────

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
    target: Callable[[QMainWindow], Optional[QWidget]]


def _build_steps(window: QMainWindow) -> List[TourStep]:
    def attr(*names: str) -> Callable[[QMainWindow], Optional[QWidget]]:
        def _resolve(win: QMainWindow) -> Optional[QWidget]:
            for name in names:
                w = getattr(win, name, None)
                if w is not None:
                    return w
            return None
        return _resolve

    return [
        TourStep(
            kicker="STEP 1 OF 4",
            title="This is your watchlist.",
            body=(
                "A list of companies you want to follow. Each row shows "
                "the current price and how much it moved today.\n\n"
                "You add companies with the + button. Nothing is bought "
                "until you say so."
            ),
            target=attr("_watchlist_dock", "watchlist_panel"),
        ),
        TourStep(
            kicker="STEP 2 OF 4",
            title="This is the price chart.",
            body=(
                "Pick a company in the watchlist and this shows how its "
                "price has moved over time. Going up is good, going "
                "down is bad. That's it."
            ),
            target=attr("chart_panel", "_chart_dock"),
        ),
        TourStep(
            kicker="STEP 3 OF 4",
            title="Start and stop your blank advisor here.",
            body=(
                "Press START and your blank advisor begins watching the "
                "market and making trades for you. Press STOP and it "
                "stops.\n\n"
                "You are always in control. Nothing runs on its own."
            ),
            target=attr("_agent_dock", "agent_panel"),
        ),
        TourStep(
            kicker="STEP 4 OF 4",
            title="Ask your blank advisor anything.",
            body=(
                "Type a question here — \"why did you buy Apple?\", "
                "\"is Tesla a good buy?\", anything. Your blank advisor "
                "answers in plain English.\n\n"
                "You can open this tour again any time from the Help "
                "menu at the top."
            ),
            target=attr("_chat_dock", "chat_panel"),
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

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        full = QPainterPath()
        full.addRect(self.rect())
        if not self._target_rect.isEmpty():
            hole = QPainterPath()
            padded = self._target_rect.adjusted(-6, -6, 6, 6)
            hole.addRoundedRect(padded, 2, 2)
            full = full.subtracted(hole)

        painter.fillPath(full, QColor(0, 0, 0, 210))

        if not self._target_rect.isEmpty():
            painter.setPen(QColor(0, 255, 135, 180))
            painter.drawRoundedRect(
                self._target_rect.adjusted(-6, -6, 6, 6), 2, 2,
            )


# Popover sizing — keep smaller than the minimum window (1280x720) so
# we can always find room for it next to any dock.
_POPOVER_WIDTH = 340
_POPOVER_MAX_HEIGHT = 360
_POPOVER_MIN_HEIGHT = 220


class _PopoverCard(QFrame):
    """Floating info card pinned next to the spotlight."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("TourPopover")
        self.setStyleSheet(
            f"QFrame#TourPopover {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )
        self.setFixedWidth(_POPOVER_WIDTH)
        self.setMaximumHeight(_POPOVER_MAX_HEIGHT)
        self.setMinimumHeight(_POPOVER_MIN_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
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

        # Scrollable body so overlong copy never clips on tiny windows.
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._body.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px; line-height: 1.55;"
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        root.addSpacing(12)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        root.addSpacing(10)

        foot = QHBoxLayout()
        foot.setSpacing(6)

        self._progress = QLabel()
        self._progress.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        foot.addWidget(self._progress, 1)

        self.skip_btn = QPushButton("SKIP")
        apply_variant(self.skip_btn, "ghost")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.setFixedHeight(30)
        foot.addWidget(self.skip_btn)

        self.back_btn = QPushButton("BACK")
        apply_variant(self.back_btn, "ghost")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setFixedHeight(30)
        foot.addWidget(self.back_btn)

        self.next_btn = QPushButton("NEXT")
        apply_variant(self.next_btn, "primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setFixedHeight(30)
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

    def __init__(self, window: QMainWindow, *, mark_complete: bool = True) -> None:
        self._window = window
        self._steps = _build_steps(window)
        self._index = 0
        self._mark_complete = mark_complete

        self._overlay = _SpotlightOverlay(window)
        self._overlay.setGeometry(window.rect())
        self._overlay.show()
        self._overlay.raise_()

        self._popover = _PopoverCard(window)
        self._popover.show()
        self._popover.raise_()

        self._popover.next_btn.clicked.connect(self._next)
        self._popover.back_btn.clicked.connect(self._back)
        self._popover.skip_btn.clicked.connect(self._finish)

        # Keep a reference so Qt/Python doesn't GC the event filter.
        self._forwarder = _ResizeForwarder(self)
        window.installEventFilter(self._forwarder)
        # Give Qt time to finish the initial layout pass — dock
        # geometries are not final until after the window is shown and
        # the event loop spins once.
        QTimer.singleShot(200, self._render_current)

    def on_window_resized(self) -> None:
        self._overlay.setGeometry(self._window.rect())
        self._render_current()

    def _render_current(self) -> None:
        if self._index >= len(self._steps):
            self._finish()
            return
        step = self._steps[self._index]
        target = step.target(self._window)

        if target is None or not target.isVisible():
            self._index += 1
            self._render_current()
            return

        if isinstance(target, QDockWidget):
            if target.isFloating():
                target.setFloating(False)
            # A tabified dock may not be the active tab — raising it
            # brings it to the front so the spotlight lands on visible
            # content instead of the neighbour behind it.
            target.raise_()

        # Re-sync the overlay to window size every render — dock moves
        # and menu bar height changes can shift things between steps.
        self._overlay.setGeometry(self._window.rect())

        rect = self._target_rect_in_window(target)
        if rect.isEmpty():
            # Target is off-screen / zero-size — skip rather than
            # flashing an empty spotlight.
            self._index += 1
            self._render_current()
            return

        self._overlay.set_target_rect(rect)
        self._overlay.raise_()
        self._popover.set_step(
            step, self._index, len(self._steps),
            is_last=self._index == len(self._steps) - 1,
        )
        self._size_popover_to_window()
        self._popover.adjustSize()
        self._position_popover(rect)
        self._popover.raise_()

    def _target_rect_in_window(self, target: QWidget) -> QRect:
        top_left = target.mapTo(self._window, QPoint(0, 0))
        rect = QRect(top_left, target.size())
        return rect.intersected(self._window.rect())

    def _size_popover_to_window(self) -> None:
        """Shrink the popover if the window is smaller than its natural size."""
        win_rect = self._window.rect()
        margin = 16
        max_w = max(260, win_rect.width() - 2 * margin)
        max_h = max(200, win_rect.height() - 2 * margin)
        self._popover.setFixedWidth(min(_POPOVER_WIDTH, max_w))
        self._popover.setMaximumHeight(min(_POPOVER_MAX_HEIGHT, max_h))

    def _position_popover(self, target_rect: QRect) -> None:
        """Place the popover so it is always fully on-screen.

        Strategy:
        1. Try the four sides of the spotlight (right, left, below,
           above). Pick the first one that fits fully inside the
           window without overlapping the target.
        2. If none fit, park in whichever corner is furthest from the
           spotlight centre so the popover stays reachable.
        3. Clamp to the window rect as a last safety net.
        """
        win_rect = self._window.rect()
        margin = 16
        pop_size = self._popover.size()

        def centred_y() -> int:
            y = target_rect.top() + (target_rect.height() - pop_size.height()) // 2
            return max(margin, min(y, win_rect.height() - pop_size.height() - margin))

        def centred_x() -> int:
            x = target_rect.left() + (target_rect.width() - pop_size.width()) // 2
            return max(margin, min(x, win_rect.width() - pop_size.width() - margin))

        candidates = [
            QPoint(target_rect.right() + margin, centred_y()),
            QPoint(target_rect.left() - pop_size.width() - margin, centred_y()),
            QPoint(centred_x(), target_rect.bottom() + margin),
            QPoint(centred_x(), target_rect.top() - pop_size.height() - margin),
        ]

        def fits_in_window(p: QPoint) -> bool:
            return win_rect.contains(QRect(p, pop_size))

        def clear_of_target(p: QPoint) -> bool:
            return not QRect(p, pop_size).intersects(target_rect)

        chosen: Optional[QPoint] = None
        for p in candidates:
            if fits_in_window(p) and clear_of_target(p):
                chosen = p
                break

        if chosen is None:
            tc_x = target_rect.center().x()
            tc_y = target_rect.center().y()
            right = tc_x < win_rect.width() / 2
            bottom = tc_y < win_rect.height() / 2
            x = (
                win_rect.width() - pop_size.width() - margin
                if right else margin
            )
            y = (
                win_rect.height() - pop_size.height() - margin
                if bottom else margin
            )
            chosen = QPoint(x, y)

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
        if self._mark_complete:
            _mark_tour_complete()
        try:
            self._window.removeEventFilter(self._forwarder)
        except Exception:
            pass
        self._overlay.hide()
        self._popover.hide()
        self._overlay.deleteLater()
        self._popover.deleteLater()


class _ResizeForwarder(QWidget):
    """Lightweight forwarder that nudges the tour on window resize."""

    def __init__(self, tour: "OnboardingTour") -> None:
        super().__init__()
        self._tour = tour

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Resize:
            self._tour.on_window_resized()
        return False


# ── Entry points ────────────────────────────────────────────────────

_ACTIVE_TOUR: Optional[OnboardingTour] = None


def maybe_start_tour(window: QMainWindow) -> None:
    """Show the first-launch onboarding tour, or no-op if already run."""
    if _tour_has_run():
        return
    QTimer.singleShot(250, lambda: _start_tour(window, mark_complete=True))


def start_tour(window: QMainWindow) -> None:
    """Start the tour unconditionally (menu-triggered replay)."""
    _start_tour(window, mark_complete=False)


def _start_tour(window: QMainWindow, *, mark_complete: bool) -> None:
    global _ACTIVE_TOUR
    app = QApplication.instance()
    if app is None:
        return
    _ACTIVE_TOUR = OnboardingTour(window, mark_complete=mark_complete)
