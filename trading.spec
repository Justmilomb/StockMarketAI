# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for StockMarketAI desktop app.

Build:
    pyinstaller trading.spec --clean

Output: dist/trading.exe
"""

import sys
import importlib
from pathlib import Path

PROJECT_ROOT = str(Path(SPECPATH))

# ── Locate native DLLs for xgboost and lightgbm ────────────────────
_native_binaries = []

def _find_dll(package_name, dll_glob):
    """Find a native DLL inside an installed package."""
    try:
        pkg = importlib.import_module(package_name)
        pkg_dir = Path(pkg.__file__).parent
        for dll in pkg_dir.rglob(dll_glob):
            # (source_path, dest_dir_inside_bundle)
            _native_binaries.append((str(dll), str(dll.parent.relative_to(pkg_dir.parent))))
            return
    except Exception:
        pass

_find_dll('xgboost', 'xgboost.dll')
_find_dll('lightgbm', 'lib_lightgbm.dll')


a = Analysis(
    [str(Path(PROJECT_ROOT) / 'desktop' / 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=_native_binaries,
    datas=[
        (str(Path(PROJECT_ROOT) / 'config.json'), '.'),
        # xgboost and lightgbm need their VERSION files at runtime
        (str(Path(importlib.import_module('xgboost').__file__).parent / 'VERSION'), 'xgboost'),
        (str(Path(importlib.import_module('lightgbm').__file__).parent / 'VERSION.txt'), 'lightgbm'),
    ],
    hiddenimports=[
        # PySide6
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # pyqtgraph
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.PlotItem',
        # Data science
        'numpy',
        'numpy.testing',
        'pandas',
        'sklearn',
        'sklearn.ensemble',
        'sklearn.linear_model',
        'sklearn.svm',
        'sklearn.neighbors',
        'scipy',
        'scipy.stats',
        'scipy.sparse',
        'scipy._lib',
        'scipy._lib.array_api_compat',
        'scipy._lib.array_api_compat.numpy',
        'statsmodels',
        'statsmodels.tsa',
        'joblib',
        # ML boosting (optional)
        'xgboost',
        'xgboost.core',
        'xgboost.tracker',
        'lightgbm',
        # Data
        'yfinance',
        'feedparser',
        'requests',
        # Project modules
        'ai_service',
        'auto_engine',
        'broker_service',
        'news_agent',
        'claude_client',
        'claude_personas',
        'database',
        'accuracy_tracker',
        'pipeline_tracker',
        'ensemble',
        'features',
        'features_advanced',
        'model',
        'data_loader',
        'strategy',
        'strategy_profiles',
        'strategy_selector',
        'risk_manager',
        'consensus',
        'regime',
        'timeframe',
        'meta_ensemble',
        'forecaster_statistical',
        'forecaster_deep',
        'types_shared',
        'asset_registry',
        'terminal.state',
        'mirofish',
        # Multi-asset packages
        'crypto',
        'crypto.types',
        'crypto.data_loader',
        'crypto.features',
        'crypto.ensemble',
        'crypto.regime',
        'crypto.broker',
        'crypto.strategy',
        'polymarket',
        'polymarket.types',
        'polymarket.data_loader',
        'polymarket.features',
        'polymarket.model',
        'polymarket.regime',
        'polymarket.broker',
        'polymarket.strategy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude torch to save ~500MB (deep learning is optional)
        'torch',
        'torchvision',
        'torchaudio',
        # Exclude Textual (not needed for desktop)
        'textual',
        # Exclude test frameworks (keep unittest — numpy.testing needs it)
        'pytest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='trading',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'),
)
