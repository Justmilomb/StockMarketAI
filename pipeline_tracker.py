import copy
import threading
import time
from typing import Any, Dict, List

from types_shared import PipelineStage, PipelineState

# Default pipeline stage definitions
PIPELINE_STAGES = [
    ("data_fetch", "DATA FETCH"),
    ("features", "FEATURES V2"),
    ("regime", "REGIME DETECT"),
    ("ml_ensemble", "ML ENSEMBLE"),
    ("statistical", "ARIMA/ETS"),
    ("deep_learning", "N-BEATS"),
    ("meta_blend", "META-BLEND"),
    ("claude_personas", "CLAUDE PERSONAS"),
    ("consensus", "CONSENSUS"),
    ("risk", "RISK SIZING"),
]


class PipelineTracker:
    """Thread-safe progress tracker for the AI analysis pipeline.

    The AI service calls mutation methods from background threads;
    the TUI polls get_state() from the main thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: List[PipelineStage] = []
        self._is_running = False
        self._start_time = 0.0
        self._last_run_duration = 0.0
        self._stage_start_times: Dict[str, float] = {}
        self._model_family_stats: Dict[str, Dict[str, Any]] = {}
        self._accuracy_history: List[float] = []

    def begin(self) -> None:
        """Start a new pipeline run. Resets all stages to pending."""
        with self._lock:
            self._stages = [
                PipelineStage(name=name, display_name=display)
                for name, display in PIPELINE_STAGES
            ]
            self._is_running = True
            self._start_time = time.monotonic()
            self._stage_start_times.clear()

    def start_stage(self, name: str, total: int = 1) -> None:
        """Mark a stage as running with expected total items."""
        with self._lock:
            for stage in self._stages:
                if stage.name == name:
                    stage.status = "running"
                    stage.total = total
                    stage.current = 0
                    stage.progress = 0.0
                    self._stage_start_times[name] = time.monotonic()
                    break

    def update_stage(self, name: str, current: int, detail: str = "") -> None:
        """Update a running stage's progress."""
        with self._lock:
            for stage in self._stages:
                if stage.name == name:
                    stage.current = current
                    stage.progress = current / stage.total if stage.total > 0 else 0.0
                    if detail:
                        stage.detail = detail
                    start = self._stage_start_times.get(name, self._start_time)
                    stage.elapsed_seconds = time.monotonic() - start
                    break

    def complete_stage(self, name: str, detail: str = "") -> None:
        """Mark a stage as done."""
        with self._lock:
            for stage in self._stages:
                if stage.name == name:
                    stage.status = "done"
                    stage.progress = 1.0
                    stage.current = stage.total
                    if detail:
                        stage.detail = detail
                    start = self._stage_start_times.get(name, self._start_time)
                    stage.elapsed_seconds = time.monotonic() - start
                    break

    def skip_stage(self, name: str, reason: str = "") -> None:
        """Mark a stage as skipped."""
        with self._lock:
            for stage in self._stages:
                if stage.name == name:
                    stage.status = "skipped"
                    stage.detail = reason
                    break

    def error_stage(self, name: str, detail: str = "") -> None:
        """Mark a stage as errored."""
        with self._lock:
            for stage in self._stages:
                if stage.name == name:
                    stage.status = "error"
                    stage.detail = detail
                    start = self._stage_start_times.get(name, self._start_time)
                    stage.elapsed_seconds = time.monotonic() - start
                    break

    def end(self) -> None:
        """End the pipeline run."""
        with self._lock:
            self._is_running = False
            self._last_run_duration = time.monotonic() - self._start_time

    def update_dashboard_stats(
        self,
        family_stats: Dict[str, Dict[str, Any]],
        accuracy_history: List[float] | None = None,
    ) -> None:
        """Update the model dashboard stats shown when pipeline is idle."""
        with self._lock:
            self._model_family_stats = family_stats
            if accuracy_history is not None:
                self._accuracy_history = accuracy_history

    def get_state(self) -> PipelineState:
        """Return a deep copy snapshot of current state. Thread-safe."""
        with self._lock:
            return PipelineState(
                stages=[copy.copy(s) for s in self._stages],
                is_running=self._is_running,
                total_elapsed=time.monotonic() - self._start_time if self._is_running else 0.0,
                current_stage=next(
                    (s.name for s in self._stages if s.status == "running"), ""
                ),
                last_run_duration=self._last_run_duration,
                model_family_stats=copy.deepcopy(self._model_family_stats),
                accuracy_history=list(self._accuracy_history),
            )
