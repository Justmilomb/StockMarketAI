"""Entry point for Blank Simple edition."""
from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

multiprocessing.freeze_support()

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    sys.path.insert(0, str(BUNDLE_DIR))
    sys.path.insert(0, str(BUNDLE_DIR / "core"))
    EXE_DIR = Path(sys.executable).parent
    os.chdir(EXE_DIR)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
    os.chdir(PROJECT_ROOT)

from desktop.main import launch

if __name__ == "__main__":
    launch(mode="simple")
