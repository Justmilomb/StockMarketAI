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
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T


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
    # Callable resolving to the target QWidget at display time so the
    # tour handles docks being moved/closed.
    target: Callable[[QMainWindow], Optional[QWidget]]


def _build_steps(window: QMainWindow) -> List[TourStep]:
    """Resolve steps against the MainWindow's panels.

    Only four steps — the absolute essentials. Anything more and new
    users glaze over.
    """
    def attr(name: str) -> Callable[[QMainWindow], Optional[QWidget]]:
        def _resolve(win: QMainWindow) -> Optional[QWidget]:
            return getattr(win, name, None)
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
            target=attr("_watchlist_dock"),
        ),
        TourStep(
            kicker="STEP 2 OF 4",
            title="This is the price chart.",
            body=(
                "Pick a company in the watchlist and this shows how its "
                "price has moved over time. Going up is good, going "
                "down is bad. That's it."
            ),
            target=attr("chart_panel"),
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
            target=attr("_agent_dock"),
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
            target=attr("_chat_dock"),
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


# Popover geometry — keep it comfortably smaller than the smallest
# supported window (MainWindow.setMinimumSize(1280, 720)) so we can
# always find room for it.
_POPOVER_WIDTH = 360
_POPOVER_MAX_HEIGHT = 440


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

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(0)

        self._kicker = QLabel()
        self._kicker.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px; letter-spacing: 2px;"
        )
        root.addWidget(self._kicker)

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em; padding: 8px 0 12px 0;"
        )
        root.addWidget(self._title)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 14px; line-height: 1.6;"
        )
        root.addWidget(self._body)

        root.addSpacing(16)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        root.addSpacing(14)

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

    def __init__(self, window: QMainWindow, *, mark_complete: bool = True) -> None:
        self._window = window
        self._steps = _build_steps(window)
        self._index = 0
        # When False (replay from Help menu), don't overwrite the marker
        # — it's already set.
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
        self._resize_forwarder = _ResizeForwarder(self)
        window.installEventFilter(self._resize_forwarder)
        # Give Qt time to finish the initial layout pass — dock
        # geometries are not final until after the window is shown and
        # the event loop spins once.
        QTimer.singleShot(200, self._render_current)

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
        self._popover.adjustSize()
        self._position_popover(rect)
        self._popover.raise_()

    def _target_rect_in_window(self, target: QWidget) -> QRect:
        top_left = target.mapTo(self._window, QPoint(0, 0))
        rect = QRect(top_left, target.size())
        # Clip to window so the spotlight border never paints outside
        # the visible area (e.g. a dock that extends past the edge on
        # odd layouts).
        return rect.intersected(self._window.rect())

    def _position_popover(self, target_rect: QRect) -> None:
        """Place the popover so it never clips off-screen.

        Strategy:
        1. Try the four sides of the spotlight (right, left, below,
           above). Pick the first one that fits fully inside the
           window without overlapping the target.
        2. If none fit — the target is huge (chart panel on a small
           window, etc.) — float the popover in the window's nearest
           empty corner and let it overlap the spotlight. An
           always-visible popover beats a "clean" but invisible one.
        """
        win_rect = self._window.rect()
        margin = 16

        # Bound popover size to window first — shrinks on small windows
        # so the "does it fit" test can ever succeed.
        max_w = max(240, win_rect.width() - 2 * margin)
        max_h = max(200, win_rect.height() - 2 * margin)
        self._popover.setFixedWidth(min(_POPOVER_WIDTH, max_w))
        self._popover.setMaximumHeight(min(_POPOVER_MAX_HEIGHT, max_h))
        self._popover.adjustSize()

        pop_size = self._popover.size()

        def centred_y() -> int:
            return target_rect.top() + (target_rect.height() - pop_size.height()) // 2

        def centred_x() -> int:
            return target_rect.left() + (target_rect.width() - pop_size.width()) // 2

        candidates = [
            QPoint(target_rect.right() + margin, centred_y()),
            QPoint(target_rect.left() - pop_size.width() - margin, centred_y()),
            QPoint(centred_x(), target_rect.bottom() + margin),
            QPoint(centred_x(), target_rect.top() - pop_size.height() - margin),
        ]

        def fits_in_window(p: QPoint) -> bool:
            r = QRect(p, pop_size)
            return win_rect.contains(r)

        def clear_of_target(p: QPoint) -> bool:
            return not QRect(p, pop_size).intersects(target_rect)

        chosen = None
        for p in candidates:
            if fits_in_window(p) and clear_of_target(p):
                chosen = p
                break

        if chosen is None:
            # Nothing clean — park the popover in whichever window
            # corner is furthest from the spotlight centre. Always
            # visible, always tappable.
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

        # Final clamp so the popover is always fully on-screen, even
        # if a candidate just barely spilled over.
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


# ── Entry points ────────────────────────────────────────────────────

_ACTIVE_TOUR: Optional[OnboardingTour] = None


def maybe_start_tour(window: QMainWindow) -> None:
    """Show the first-launch onboarding tour, or no-op if already run."""
    if _tour_has_run():
        return
    # Wait one event-loop tick so the window has finished laying out.
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
