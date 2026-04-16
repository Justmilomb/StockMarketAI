"""Entry point for blank desktop application."""
from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

multiprocessing.freeze_support()

# ─── Windows AppMutex ────────────────────────────────────────────────────
# Create a named mutex so the Inno Setup installer's `AppMutex` directive
# (BlankTradingTerminalMutex_v2) can detect a running blank instance and
# gracefully terminate it via /CLOSEAPPLICATIONS during an auto-update.
# The handle is kept alive at module level for the entire process
# lifetime; we never explicitly release it because Windows tears it down
# when the process exits. This is **not** a single-instance lock — we
# don't check the GetLastError ERROR_ALREADY_EXISTS return; multiple
# blank windows are allowed.
_MUTEX_HANDLE = None
if sys.platform.startswith("win"):
    try:
        import ctypes
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None, False, "BlankTradingTerminalMutex_v2",
        )
    except Exception:
        _MUTEX_HANDLE = None

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    sys.path.insert(0, str(BUNDLE_DIR))
    sys.path.insert(0, str(BUNDLE_DIR / "core"))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "core"))

from desktop.main import launch

if __name__ == "__main__":
    launch(mode="desktop")
