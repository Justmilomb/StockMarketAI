"""Floating always-on-top overlay for mandatory updates.

The regular :class:`UpdateBanner` lives in the main window's layout and
can be dismissed or "skipped". Mandatory updates are different — the
user chose no side-door: the banner stays until the update is installed.
To satisfy that while still letting the user see whatever they were
working on, mandatory updates get a *separate* widget that:

* floats on top of the main window (not docked into any layout),
* can be grabbed anywhere on its surface and dragged, so the user can
  shove it out of the way,
* has no close button — ``closeEvent`` ignores close attempts,
* exposes only one action, INSTALL NOW, plus a collapsible notes pane.

The main window owns a single instance, constructed lazily on the first
mandatory manifest. When a later poll drops mandatory back to ``False``
(unlikely in practice), ``hide_overlay`` is called and the regular
in-layout banner takes over again.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T


_OVERLAY_QSS = f"""
QFrame#MandatoryUpdateOverlay {{
    background: {T.BG_1};
    border: 1px solid {T.ALERT};
    border-radius: 0;
}}
QFrame#MandatoryUpdateOverlay QLabel {{
    background: transparent;
    color: {T.FG_1_HEX};
    font-family: {T.FONT_SANS};
    font-size: 12px;
}}
QFrame#MandatoryUpdateOverlay QLabel#RequiredTag {{
    color: {T.ALERT};
    font-family: {T.FONT_MONO};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 3px;
}}
QFrame#MandatoryUpdateOverlay QLabel#HeadlineLabel {{
    color: {T.FG_0};
    font-family: {T.FONT_SANS};
    font-size: 20px;
    font-weight: 500;
    letter-spacing: -0.01em;
}}
QFrame#MandatoryUpdateOverlay QLabel#SubLabel {{
    color: {T.FG_2_HEX};
    font-family: {T.FONT_MONO};
    font-size: 10px;
    letter-spacing: 2px;
}}
QFrame#MandatoryUpdateOverlay QPushButton#InstallBtn {{
    background: {T.ALERT};
    color: {T.BG_0};
    border: 1px solid {T.ALERT};
    border-radius: 0;
    padding: 9px 20px;
    font-family: {T.FONT_MONO};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2px;
    min-height: 18px;
}}
QFrame#MandatoryUpdateOverlay QPushButton#InstallBtn:hover {{
    background: {T.FG_0};
    border-color: {T.FG_0};
}}
QFrame#MandatoryUpdateOverlay QPushButton#InstallBtn:disabled {{
    background: transparent;
    color: {T.FG_2_HEX};
    border-color: {T.BORDER_0};
}}
QFrame#MandatoryUpdateOverlay QPushButton#NotesToggle {{
    background: transparent;
    color: {T.FG_1_HEX};
    border: 1px solid {T.BORDER_1};
    border-radius: 0;
    padding: 7px 16px;
    font-family: {T.FONT_MONO};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2px;
    min-height: 16px;
}}
QFrame#MandatoryUpdateOverlay QPushButton#NotesToggle:hover {{
    color: {T.FG_0};
    border-color: {T.FG_0};
}}
QFrame#MandatoryUpdateOverlay QTextEdit#NotesView {{
    background: {T.BG_0};
    color: {T.FG_1_HEX};
    border: 1px solid {T.BORDER_0};
    border-radius: 0;
    font-family: {T.FONT_SANS};
    font-size: 12px;
    padding: 10px;
    selection-background-color: {T.ACCENT_DIM};
}}
QFrame#MandatoryUpdateOverlay QProgressBar {{
    background: {T.BG_0};
    border: none;
    border-radius: 0;
    text-align: center;
    max-height: 2px;
}}
QFrame#MandatoryUpdateOverlay QProgressBar::chunk {{
    background: {T.ALERT};
}}
QFrame#MandatoryUpdateOverlay QLabel#GrabLabel {{
    color: {T.FG_2_HEX};
    font-family: {T.FONT_MONO};
    font-size: 9px;
    letter-spacing: 2px;
}}
"""


class MandatoryUpdateOverlay(QFrame):
    """Frameless, always-on-top, draggable, undismissable update widget.

    The widget is a *top-level* window even though it's parented to the
    main window — ``Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint``
    makes it float over the main window (and everything else) without
    taking a taskbar slot of its own. It disappears only when
    ``hide_overlay`` is called or when the main window quits.
    """

    install_now_clicked = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setObjectName("MandatoryUpdateOverlay")
        self.setStyleSheet(_OVERLAY_QSS)
        self.setFixedWidth(520)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setVisible(False)

        self._manifest: Optional[dict[str, Any]] = None
        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        # Top row — REQUIRED tag + grab hint (the whole frame drags,
        # but users are used to title bars so we label the top edge).
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)

        self._required_tag = QLabel("UPDATE REQUIRED")
        self._required_tag.setObjectName("RequiredTag")
        top.addWidget(self._required_tag, 0)

        top.addStretch(1)

        self._grab_hint = QLabel("DRAG TO MOVE")
        self._grab_hint.setObjectName("GrabLabel")
        top.addWidget(self._grab_hint, 0)
        outer.addLayout(top)

        # Headline — "blank 2.1.0 must be installed to continue"
        self._headline = QLabel("")
        self._headline.setObjectName("HeadlineLabel")
        self._headline.setTextInteractionFlags(Qt.NoTextInteraction)
        self._headline.setWordWrap(True)
        outer.addWidget(self._headline)

        self._sub = QLabel("this update cannot be skipped or postponed.")
        self._sub.setObjectName("SubLabel")
        outer.addWidget(self._sub)

        # Action row — only install + notes toggle. No skip, no X.
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 4, 0, 0)

        self._install_btn = QPushButton("INSTALL NOW")
        self._install_btn.setObjectName("InstallBtn")
        self._install_btn.setCursor(Qt.PointingHandCursor)
        self._install_btn.clicked.connect(self._on_install_clicked)
        row.addWidget(self._install_btn, 0)

        self._notes_toggle = QPushButton("WHAT'S NEW")
        self._notes_toggle.setObjectName("NotesToggle")
        self._notes_toggle.setCursor(Qt.PointingHandCursor)
        self._notes_toggle.clicked.connect(self._toggle_notes)
        row.addWidget(self._notes_toggle, 0)

        row.addStretch(1)

        outer.addLayout(row)

        # Status line (downloading, error, installing) + progress bar.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {T.FG_2_HEX};")
        self._status_label.setVisible(False)
        outer.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        # Collapsible notes pane — hidden by default so the overlay is
        # compact and easy to move out of the way.
        self._notes_view = QTextEdit()
        self._notes_view.setObjectName("NotesView")
        self._notes_view.setReadOnly(True)
        self._notes_view.setMaximumHeight(160)
        self._notes_view.setVisible(False)
        outer.addWidget(self._notes_view)

    # ── public API ──────────────────────────────────────────────────────

    def show_mandatory(self, manifest: dict[str, Any]) -> None:
        """Populate and raise the overlay for a mandatory manifest."""
        self._manifest = dict(manifest)
        version = str(manifest.get("version") or "")
        self._headline.setText(
            f"blank {version} must be installed to keep using the app."
        )
        notes = str(manifest.get("notes") or "").strip() or "No release notes."
        self._notes_view.setPlainText(notes)
        self._notes_view.setVisible(False)
        self._notes_toggle.setText("WHAT'S NEW")
        self._install_btn.setEnabled(True)
        self._status_label.setVisible(False)
        self._progress.setVisible(False)

        self.adjustSize()
        self._position_near_parent()
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_overlay(self) -> None:
        self._manifest = None
        self.hide()

    def set_downloading(self, percent: int) -> None:
        if not self.isVisible():
            return
        self._status_label.setText(f"downloading — {percent}%")
        self._status_label.setStyleSheet(f"color: {T.FG_2_HEX};")
        self._status_label.setVisible(True)
        self._progress.setVisible(True)
        self._progress.setValue(max(0, min(100, percent)))
        self._install_btn.setEnabled(False)

    def set_error(self, message: str) -> None:
        if not self.isVisible():
            return
        self._status_label.setText(f"error — {message}")
        self._status_label.setStyleSheet(f"color: {T.ALERT};")
        self._status_label.setVisible(True)
        self._progress.setVisible(False)
        self._install_btn.setEnabled(True)

    def set_installing(self) -> None:
        if not self.isVisible():
            return
        self._status_label.setText("launching installer — blank will restart shortly")
        self._status_label.setStyleSheet(f"color: {T.ACCENT_HEX};")
        self._status_label.setVisible(True)
        self._progress.setVisible(False)
        self._install_btn.setEnabled(False)

    # ── drag-to-move ────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: D401
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── undismissable ───────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: D401
        """Refuse every close attempt — Alt-F4, taskbar right-click, etc.

        The only legitimate way to hide this overlay is for the app
        itself to call :meth:`hide_overlay` after the installer has
        launched (or, later, if a poll downgrades the manifest from
        mandatory). Users cannot close it.
        """
        event.ignore()

    # ── internal helpers ────────────────────────────────────────────────

    def _toggle_notes(self) -> None:
        showing = not self._notes_view.isVisible()
        self._notes_view.setVisible(showing)
        self._notes_toggle.setText("HIDE NOTES" if showing else "WHAT'S NEW")
        self.adjustSize()

    def _on_install_clicked(self) -> None:
        if self._manifest is not None:
            self.install_now_clicked.emit(self._manifest)

    def _position_near_parent(self) -> None:
        """Anchor the overlay near the top-centre of the parent window.

        On first show we want a predictable landing spot so users see
        the update immediately. After that, whatever position the user
        drags it to is preserved because we only call this from
        :meth:`show_mandatory` on a fresh manifest.
        """
        parent = self.parent()
        if not isinstance(parent, QWidget):
            return
        pg = parent.frameGeometry()
        # Centred horizontally, ~8% from the top — high enough to be
        # prominent, low enough that the user can see their menu bar.
        x = pg.x() + (pg.width() - self.width()) // 2
        y = pg.y() + max(40, int(pg.height() * 0.08))
        self.move(x, y)
