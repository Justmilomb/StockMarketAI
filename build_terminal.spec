# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for StockMarketAI Terminal (trading.exe)"""

import os
from pathlib import Path

a = Analysis(
    ['terminal/app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('terminal/terminal.css', 'terminal'),
        ('models', 'models'),
        ('data', 'data'),
    ],
    hiddenimports=[
        'sklearn.ensemble',
        'sklearn.linear_model',
        'xgboost',
        'lightgbm',
        'statsmodels.tsa.arima.model',
        'statsmodels.tsa.holtwinters',
        'scipy.optimize',
        'numpy',
        'pandas',
        'feedparser',
        'textual.widgets',
        'textual.containers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
