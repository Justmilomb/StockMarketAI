"""Pipeline monitor panel — progress bars, model dashboard, and status log."""
from __future__ import annotations
from typing import Any, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)


class PipelinePanel(QGroupBox):
    """Dual-mode: progress bars when running, model dashboard when idle.
    Always shows a status log at the bottom with the latest activity."""

    def __init__(self, tracker: Any) -> None:
        super().__init__("PIPELINE MONITOR")
        self._tracker = tracker

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 4)
        layout.setSpacing(2)

        # Progress mode widgets
        self._progress_container = QWidget()
        self._progress_layout = QVBoxLayout(self._progress_container)
        self._progress_layout.setContentsMargins(0, 0, 0, 0)
        self._progress_layout.setSpacing(1)
        self._stage_bars: list[tuple[QLabel, QProgressBar]] = []
        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        self._overall_label = QLabel("Idle")
        self._overall_label.setStyleSheet("color: #888888; font-size: 10px;")

        # Dashboard mode widgets
        self._dashboard = QTableWidget(0, 5)
        self._dashboard.setHorizontalHeaderLabels(
            ["FAMILY", "COUNT", "WEIGHT", "AVG PROB", "STATUS"]
        )
        self._dashboard.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._dashboard.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._dashboard.verticalHeader().setVisible(False)

        # Status log — persistent, always visible
        self._status_log = QLabel("Waiting for first refresh...")
        self._status_log.setStyleSheet("color: #888888; font-size: 10px;")
        self._status_log.setWordWrap(True)

        layout.addWidget(self._progress_container, 1)
        layout.addWidget(self._overall_bar)
        layout.addWidget(self._overall_label)
        layout.addWidget(self._dashboard, 1)
        layout.addWidget(self._status_log)

        # Start in dashboard mode
        self._progress_container.hide()
        self._overall_bar.hide()

        # Error tracking
        self._last_errors: List[str] = []

    def update_status(self, message: str) -> None:
        """Called by app.py when RefreshWorker emits progress."""
        self._overall_label.setText(message)
        self._overall_label.setStyleSheet("color: #00bfff; font-size: 10px;")

    def set_refresh_result(self, elapsed: float, errors: List[str]) -> None:
        """Called after a refresh completes. Shows persistent summary."""
        self._last_errors = errors
        if errors:
            error_text = " | ".join(errors[:3])
            if len(errors) > 3:
                error_text += f" (+{len(errors) - 3} more)"
            self._status_log.setText(f"Last refresh: {elapsed:.0f}s — ERRORS: {error_text}")
            self._status_log.setStyleSheet("color: #ff5555; font-size: 10px;")
        else:
            self._status_log.setText(f"Last refresh: {elapsed:.0f}s — all OK")
            self._status_log.setStyleSheet("color: #00ff00; font-size: 10px;")

    def poll_tracker(self) -> None:
        """Called every 250ms by the main window timer."""
        if not self._tracker:
            return

        try:
            pipeline_state = self._tracker.get_state()
        except Exception:
            return

        if pipeline_state.is_running:
            self._show_progress(pipeline_state)
        else:
            self._show_dashboard(pipeline_state)

    def _show_progress(self, state: Any) -> None:
        """Show per-stage progress bars."""
        self._dashboard.hide()
        self._progress_container.show()
        self._overall_bar.show()

        stages = state.stages if hasattr(state, "stages") else []

        # Create/update stage bars
        while len(self._stage_bars) < len(stages):
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            lbl = QLabel("")
            lbl.setFixedWidth(200)
            lbl.setStyleSheet("font-size: 10px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setMaximumHeight(12)
            hl.addWidget(lbl)
            hl.addWidget(bar, 1)
            self._progress_layout.addWidget(row)
            self._stage_bars.append((lbl, bar))

        for i, stage in enumerate(stages):
            if i >= len(self._stage_bars):
                break
            lbl, bar = self._stage_bars[i]
            name = getattr(stage, "display_name", f"Stage {i}")
            status = getattr(stage, "status", "pending")
            progress = getattr(stage, "progress", 0)
            detail = getattr(stage, "detail", "")

            icon = {"done": "OK", "running": ">>", "error": "!!", "skipped": "--"}.get(status, "..")
            color = {"done": "#00ff00", "running": "#00bfff", "error": "#ff0000", "skipped": "#888888"}.get(status, "#888888")

            label_text = f'<span style="color:{color};">[{icon}]</span> {name}'
            if status == "error" and detail:
                label_text += f' <span style="color:#ff5555;">({detail[:30]})</span>'
            lbl.setText(label_text)
            bar.setValue(int(progress * 100) if progress <= 1 else int(progress))

        # Overall
        total_elapsed = getattr(state, "total_elapsed", 0)
        done = sum(1 for s in stages if getattr(s, "status", "") == "done")
        errored = sum(1 for s in stages if getattr(s, "status", "") == "error")
        total = len(stages) or 1
        pct = int(done / total * 100)
        self._overall_bar.setValue(pct)

        status_parts = [f"Pipeline: {pct}%", f"Elapsed: {total_elapsed:.0f}s"]
        if errored:
            status_parts.append(f"{errored} error(s)")
        self._overall_label.setText(" | ".join(status_parts))
        self._overall_label.setStyleSheet("color: #00bfff; font-size: 10px;")

    def _show_dashboard(self, state: Any) -> None:
        """Show model family stats table."""
        self._progress_container.hide()
        self._overall_bar.hide()
        self._dashboard.show()

        families = getattr(state, "model_family_stats", {})
        if not families:
            self._overall_label.setText("Pipeline idle — waiting for first run")
            self._overall_label.setStyleSheet("color: #888888; font-size: 10px;")
            self._dashboard.setRowCount(0)
            return

        self._dashboard.setRowCount(len(families))
        for row, (key, fam) in enumerate(families.items()):
            name = fam.get("display_name", key) if isinstance(fam, dict) else str(key)
            count = str(fam.get("count", 0)) if isinstance(fam, dict) else ""
            raw_weight = fam.get("weight", 0) if isinstance(fam, dict) else ""
            try:
                weight = f"{float(raw_weight):.0%}" if raw_weight != "" else ""
            except (TypeError, ValueError):
                weight = str(raw_weight)
            raw_prob = fam.get("avg_prob", 0) if isinstance(fam, dict) else ""
            try:
                avg_prob = f"{float(raw_prob):.3f}" if raw_prob != "" else ""
            except (TypeError, ValueError):
                avg_prob = str(raw_prob)
            status = fam.get("status", "") if isinstance(fam, dict) else ""

            items = [
                _item(name, "#ffb000"),
                _item(count, "#ffd700"),
                _item(weight, "#ffd700"),
                _item(avg_prob, "#00bfff"),
                _item(status, "#00ff00" if status == "active" else "#888888"),
            ]
            for col, item in enumerate(items):
                self._dashboard.setItem(row, col, item)

        dur = getattr(state, "last_run_duration", 0)
        self._overall_label.setText(f"Last run: {dur:.1f}s | Models: {sum(f.get('count', 0) for f in families.values() if isinstance(f, dict))}")
        self._overall_label.setStyleSheet("color: #888888; font-size: 10px;")


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
