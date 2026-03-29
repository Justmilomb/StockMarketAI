# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for StockMarketAI desktop app.

Build:
    cd E:/Coding/StockMarketAI
    pyinstaller desktop/build/stockmarket.spec

Output: dist/StockMarketAI.exe
"""

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(SPECPATH).parent.parent)

a = Analysis(
    [str(Path(PROJECT_ROOT) / 'desktop' / 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (str(Path(PROJECT_ROOT) / 'config.json'), '.'),
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
        'pandas',
        'sklearn',
        'sklearn.ensemble',
        'sklearn.linear_model',
        'sklearn.svm',
        'sklearn.neighbors',
        'scipy',
        'scipy.stats',
        'statsmodels',
        'statsmodels.tsa',
        'joblib',
        # ML boosting (optional)
        'xgboost',
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
        'gemini_personas',
        'types_shared',
        'terminal.state',
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
    name='StockMarketAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'),
)
