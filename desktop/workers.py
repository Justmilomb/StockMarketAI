"""Background worker threads for the desktop app.

Phase 3 removed ``RefreshWorker`` along with the rest of the ML
pipeline. The only thing left is the generic ``BackgroundTask`` —
which the app still uses for broker fetches, chart loads, and other
off-main-thread work. Phase 4 will add an ``AgentRunner`` QThread
that lives in ``core/agent/runner.py``.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class BackgroundTask(QThread):
    """Generic worker that runs a callable in a background thread."""
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))
