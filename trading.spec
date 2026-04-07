# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Blank desktop app.

Build:
    pyinstaller trading.spec --clean

Output: dist/blank.exe
"""

import sys
import importlib
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = str(Path(SPECPATH))

# Collect all submodules for packages that use lazy loading
_scipy_imports = collect_submodules('scipy')
_numpy_imports = collect_submodules('numpy')
_sklearn_imports = collect_submodules('sklearn')
_statsmodels_imports = collect_submodules('statsmodels')
_patsy_imports = collect_submodules('patsy')
_pyarrow_imports = collect_submodules('pyarrow')
_opengl_imports = collect_submodules('OpenGL')

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
        (str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'), 'desktop/assets'),
        # xgboost and lightgbm need their VERSION files at runtime
        (str(Path(importlib.import_module('xgboost').__file__).parent / 'VERSION'), 'xgboost'),
        (str(Path(importlib.import_module('lightgbm').__file__).parent / 'VERSION.txt'), 'lightgbm'),
    ],
    hiddenimports=[
        # Bulk-collected submodules (resolves all lazy-loading warnings)
        *_scipy_imports,
        *_numpy_imports,
        *_sklearn_imports,
        *_statsmodels_imports,
        *_patsy_imports,
        *_pyarrow_imports,
        *_opengl_imports,
        # PySide6
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        # pyqtgraph (including OpenGL support)
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.PlotItem',
        'pyqtgraph.opengl',
        # pandas
        'pandas',
        'pandas.plotting',
        'pandas.io.formats.style',
        # joblib + ML boosting
        'joblib',
        'xgboost',
        'xgboost.core',
        'xgboost.tracker',
        'lightgbm',
        # Installed optional deps
        'jinja2',
        'markupsafe',
        'openpyxl',
        'openpyxl.cell',
        'openpyxl.descriptors',
        'openpyxl.styles',
        'openpyxl.workbook',
        'lxml',
        'lxml.etree',
        'lxml.html',
        'html5lib',
        'html5lib.constants',
        'html5lib.treebuilders',
        'bottleneck',
        'numexpr',
        'psutil',
        'yaml',
        'simplejson',
        'orjson',
        'brotli',
        'lz4',
        'lz4.frame',
        'xlrd',
        'xlsxwriter',
        'h5py',
        'chardet',
        # dateutil / six
        'dateutil.tz.tzfile',
        'six.moves',
        'six.moves.range',
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
        'forecaster_statistical',
        'types_shared',
        'asset_registry',
        'terminal.state',
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
        'polymarket.mirofish',
        'polymarket.research',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Deep learning (not used, saves ~500MB+)
        'torch', 'torchvision', 'torchaudio',
        'jax', 'jax.numpy', 'jax.nn', 'jax.experimental',
        # CUDA / GPU (not used)
        'cuda', 'cudf', 'cupy', 'cupyx', 'nvidia',
        'cuda.bindings',
        # Distributed computing (not used)
        'dask', 'distributed', 'numba',
        # TUI (not needed for desktop)
        'textual',
        # Test frameworks (keep unittest — numpy.testing needs it)
        'pytest',
        # Database drivers not used
        'psycopg', 'psycopg2', 'psycopg2cffi', 'pymysql', 'sqlalchemy',
        # Misc not needed
        'IPython', 'sphinx', 'numpydoc', 'traitlets',
        'matplotlib', 'tornado', 'werkzeug',
        'Cython', 'cython',
        'odf', 'polars', 'pyamg', 'sksparse', 'cvxopt',
        'graphviz', 'viztracer', 'uarray', 'ndonnx',
        'array_api_strict', 'sparse', 'colorcet',
        'datatable', 'python_calamine', 'pyxlsb',
        'tables', 'fsspec', 'botocore', 'adbc_driver_manager',
        # Polymarket CLOB (optional, not pip-installable)
        'py_clob_client',
        # Not applicable on Windows
        'AppKit', 'Foundation', 'android', 'java', 'jnius',
        'pyodide', 'pyodide_js', 'js',
        # Networking extras not used
        'h2', 'eventlet', 'gevent', 'python_socks', 'socks',
        'OpenSSL', 'cryptography',
        # Other optional deps not used
        'genshi', 'markdownify', 'readability',
        'ccxt', 'django', 'macholib', 'yapf',
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
    name='blank',
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
    icon=str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'),
    version=str(Path(PROJECT_ROOT) / 'version_info.py'),
)
