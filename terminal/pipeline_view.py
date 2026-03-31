from __future__ import annotations

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, Label
from textual.timer import Timer

from pipeline_tracker import PipelineTracker
from types_shared import PipelineState, PipelineStage


class PipelineView(Vertical):
    """Bloomberg-style dual-mode pipeline visualization.

    Shows animated progress bars during pipeline execution,
    and a model performance dashboard when idle.
    """

    DEFAULT_CSS = """
    PipelineView {
        border: solid #444444;
        background: #0a0a0a;
        height: auto;
        min-height: 6;
        max-height: 18;
        padding: 0 1;
    }
    """

    def __init__(self, tracker: PipelineTracker, id: str = "pipeline-panel") -> None:
        super().__init__(id=id)
        self._tracker = tracker
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        """Compose the initial widget tree."""
        yield Label("[b][#ffb000]MODEL DASHBOARD[/][/b]", classes="panel-title", id="pipeline-title")
        yield Static("[#888888]  No pipeline data yet. Press [b]r[/b] to refresh.[/]", id="pipeline-content")

    def on_mount(self) -> None:
        """Start polling the tracker on mount."""
        self._poll_timer = self.set_interval(0.25, self._poll_tracker)

    def _poll_tracker(self) -> None:
        """Poll the pipeline tracker and update the display."""
        state = self._tracker.get_state()
        content = self.query_one("#pipeline-content", Static)
        title = self.query_one("#pipeline-title", Label)

        if state.is_running:
            title.update(self._render_pipeline_title(state))
            content.update(self._render_pipeline(state))
        else:
            title.update(self._render_dashboard_title(state))
            content.update(self._render_dashboard(state))

    def _render_pipeline_title(self, state: PipelineState) -> str:
        """Render the title bar during active pipeline execution."""
        return f"[b][#00bfff]AI PIPELINE[/][/b] [#666666]|[/] [#ffb000]{state.total_elapsed:.1f}s[/]"

    def _render_dashboard_title(self, state: PipelineState) -> str:
        """Render the title bar for idle model dashboard mode."""
        if state.last_run_duration > 0:
            return f"[b][#ffb000]MODEL DASHBOARD[/][/b] [#666666]|[/] [#888888]Last run: {state.last_run_duration:.1f}s[/]"
        return "[b][#ffb000]MODEL DASHBOARD[/][/b]"

    def _render_pipeline(self, state: PipelineState) -> str:
        """Render the active pipeline progress display with per-stage bars."""
        lines: List[str] = []
        bar_width = 28

        for stage in state.stages:
            icon = self._stage_icon(stage.status)
            bar = self._progress_bar(stage.progress, bar_width, stage.status)

            # Progress detail
            if stage.total > 0 and stage.status in ("running", "done"):
                progress_text = f"{stage.current}/{stage.total}"
                if stage.detail:
                    progress_text += f" {stage.detail}"
            else:
                progress_text = stage.detail or ("waiting" if stage.status == "pending" else "")

            # Timing
            if stage.status == "done":
                time_str = f"[#00ff00]{stage.elapsed_seconds:.1f}s[/]"
            elif stage.status == "running":
                time_str = f"[#00bfff]{stage.elapsed_seconds:.1f}s[/]"
            elif stage.status == "skipped":
                time_str = "[#888888]skip[/]"
            else:
                time_str = "[#666666]\u2014[/]"

            name_padded = stage.display_name.ljust(15)
            lines.append(f"  {icon} {name_padded} {bar}  {progress_text:<20s} {time_str}")

        # Overall progress
        done_count = sum(1 for s in state.stages if s.status in ("done", "skipped"))
        total_count = len(state.stages)
        overall_pct = done_count / total_count if total_count > 0 else 0

        if state.total_elapsed > 0 and overall_pct > 0.1:
            eta = state.total_elapsed / overall_pct * (1 - overall_pct)
            eta_str = f"~{eta:.0f}s remaining"
        else:
            eta_str = "estimating..."

        overall_bar = self._progress_bar(overall_pct, 20, "running")
        lines.append("")
        lines.append(
            f"  Overall: {overall_bar}  {overall_pct*100:.0f}%  "
            f"[#666666]|[/]  {state.total_elapsed:.1f}s elapsed  "
            f"[#666666]|[/]  {eta_str}"
        )

        return "\n".join(lines)

    def _render_dashboard(self, state: PipelineState) -> str:
        """Render the idle model dashboard with family stats and regime info."""
        stats = state.model_family_stats
        if not stats:
            return "  [#888888]No pipeline data yet. Press [b]r[/b] to refresh.[/]"

        lines: List[str] = []
        lines.append(f"  [#ffb000]{'FAMILY':<22s} {'COUNT':>5s}   {'WEIGHT':>6s}   {'AVG PROB':>8s}   STATUS[/]")
        lines.append(f"  [#444444]{'\u2500' * 70}[/]")

        for family_key in ["ml", "statistical", "deep_learning", "claude_personas"]:
            info = stats.get(family_key, {})
            if not info:
                continue
            name = str(info.get("display_name", family_key))
            count = int(info.get("count", 0))
            weight = float(info.get("weight", 0))
            avg_prob = float(info.get("avg_prob", 0))
            status = str(info.get("status", "\u2014"))

            weight_str = f"{weight*100:.0f}%" if weight > 0 else "\u2014"
            prob_str = f"{avg_prob:.3f}" if avg_prob > 0 else "N/A"
            status_color = "#00ff00" if any(w in status for w in ("trained", "fitted", "ready", "live")) else "#888888"

            lines.append(f"  {name:<22s} {count:>5d}   {weight_str:>6s}   {prob_str:>8s}   [{status_color}]{status}[/]")

        lines.append(f"  [#444444]{'\u2500' * 70}[/]")

        total_models = sum(int(s.get("count", 0)) for s in stats.values() if isinstance(s, dict) and "count" in s)
        regime = str(stats.get("_regime", "unknown"))
        regime_conf = float(stats.get("_regime_confidence", 0))
        consensus = float(stats.get("_consensus_bull_pct", 50))

        lines.append(
            f"  [#ffd700]Total: {total_models} models[/]  [#666666]|[/]  "
            f"Regime: [#00bfff]{regime}[/] ({regime_conf:.0f}%)  [#666666]|[/]  "
            f"Consensus: {consensus:.0f}% bull"
        )

        if state.last_run_duration > 0:
            lines.append(f"  [#888888]Last pipeline: {state.last_run_duration:.1f}s[/]")

        return "\n".join(lines)

    def _stage_icon(self, status: str) -> str:
        """Return a Rich-markup icon for the given stage status."""
        icons = {
            "done": "[#00ff00][b]\u25a0[/b][/]",
            "running": "[#00bfff][b]\u25b8[/b][/]",
            "pending": "[#666666]\u00b7[/]",
            "error": "[#ff0000][b]\u2717[/b][/]",
            "skipped": "[#888888]\u2014[/]",
        }
        return icons.get(status, "[#666666]\u00b7[/]")

    def _progress_bar(self, progress: float, width: int, status: str) -> str:
        """Render a coloured progress bar of the given width."""
        filled = int(progress * width)
        empty = width - filled

        color_map = {
            "done": "#00ff00",
            "running": "#00bfff",
            "error": "#ff0000",
        }
        color = color_map.get(status, "#333333")

        bar_filled = "\u2588" * filled
        bar_empty = "\u2591" * empty

        if filled > 0:
            return f"[{color}]{bar_filled}[/][#333333]{bar_empty}[/]"
        return f"[#333333]{bar_empty}[/]"

    def refresh_dashboard(self, dashboard_data: Dict[str, Any] | None = None) -> None:
        """Called by app.py when new dashboard data is available."""
        pass
