"""Pipeline monitor panel — progress bars or model dashboard."""
from __future__ import annotations
from typing import Any, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

class PipelinePanel(QGroupBox):
    """Dual-mode: progress bars when running, model dashboard when idle."""

    def __init__(self, tracker: Any) -> None:
        super().__init__("PIPELINE MONITOR")
        self._tracker = tracker
        self.setMaximumHeight(180)

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
        self._dashboard.setMaximumHeight(120)

        layout.addWidget(self._progress_container)
        layout.addWidget(self._overall_bar)
        layout.addWidget(self._overall_label)
        layout.addWidget(self._dashboard)

        # Start in dashboard mode
        self._progress_container.hide()
        self._overall_bar.hide()

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

            icon = {"done": "OK", "running": ">>", "error": "!!", "skipped": "--"}.get(status, "..")
            color = {"done": "#00ff00", "running": "#00bfff", "error": "#ff0000", "skipped": "#888888"}.get(status, "#888888")

            lbl.setText(f'<span style="color:{color};">[{icon}]</span> {name}')
            bar.setValue(int(progress * 100) if progress <= 1 else int(progress))

        # Overall
        total_elapsed = getattr(state, "total_elapsed", 0)
        done = sum(1 for s in stages if getattr(s, "status", "") == "done")
        total = len(stages) or 1
        pct = int(done / total * 100)
        self._overall_bar.setValue(pct)
        self._overall_label.setText(f"Pipeline: {pct}% | Elapsed: {total_elapsed:.0f}s")
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
            weight = f"{fam.get('weight', 0):.0%}" if isinstance(fam, dict) else ""
            avg_prob = f"{fam.get('avg_prob', 0):.3f}" if isinstance(fam, dict) else ""
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
