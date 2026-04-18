# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for blank desktop application.

Build:
    pyinstaller installer/blank.spec --clean

Output: dist/blank.exe
"""

import sys
import importlib
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = str(Path(SPECPATH).parent)

_scipy_imports = collect_submodules('scipy')
_numpy_imports = collect_submodules('numpy')
_sklearn_imports = collect_submodules('sklearn')
_statsmodels_imports = collect_submodules('statsmodels')
_patsy_imports = collect_submodules('patsy')
_pyarrow_imports = collect_submodules('pyarrow')
_opengl_imports = collect_submodules('OpenGL')

_native_binaries = []

def _find_dll(package_name, dll_glob):
    try:
        pkg = importlib.import_module(package_name)
        pkg_dir = Path(pkg.__file__).parent
        for dll in pkg_dir.rglob(dll_glob):
            _native_binaries.append((str(dll), str(dll.parent.relative_to(pkg_dir.parent))))
            return
    except Exception:
        pass

_find_dll('xgboost', 'xgboost.dll')
_find_dll('lightgbm', 'lib_lightgbm.dll')


_font_datas = [
    (str(p), 'desktop/assets/fonts')
    for p in (Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'fonts').glob('*')
    if p.suffix.lower() in ('.ttf', '.otf')
]

a = Analysis(
    [str(Path(PROJECT_ROOT) / 'desktop' / 'main_desktop.py')],
    pathex=[PROJECT_ROOT, str(Path(PROJECT_ROOT) / 'core')],
    binaries=_native_binaries,
    datas=[
        (str(Path(PROJECT_ROOT) / 'config.json'), '.'),
        (str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'), 'desktop/assets'),
        *_font_datas,
        (str(Path(importlib.import_module('xgboost').__file__).parent / 'VERSION'), 'xgboost'),
        (str(Path(importlib.import_module('lightgbm').__file__).parent / 'VERSION.txt'), 'lightgbm'),
    ],
    hiddenimports=[
        *_scipy_imports, *_numpy_imports, *_sklearn_imports,
        *_statsmodels_imports, *_patsy_imports, *_pyarrow_imports, *_opengl_imports,
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtSvg', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'pyqtgraph', 'pyqtgraph.graphicsItems', 'pyqtgraph.graphicsItems.PlotItem', 'pyqtgraph.opengl',
        'pandas', 'pandas.plotting', 'pandas.io.formats.style',
        'joblib', 'xgboost', 'xgboost.core', 'xgboost.tracker', 'lightgbm',
        'jinja2', 'markupsafe',
        'openpyxl', 'openpyxl.cell', 'openpyxl.descriptors', 'openpyxl.styles', 'openpyxl.workbook',
        'lxml', 'lxml.etree', 'lxml.html',
        'html5lib', 'html5lib.constants', 'html5lib.treebuilders',
        'bottleneck', 'numexpr', 'psutil', 'yaml', 'simplejson', 'orjson',
        'brotli', 'lz4', 'lz4.frame', 'xlrd', 'xlsxwriter', 'h5py', 'chardet',
        'dateutil.tz.tzfile', 'six.moves', 'six.moves.range',
        'yfinance', 'feedparser', 'requests',
        # Core modules — post Phase-3 rebuild
        'broker_service', 'broker', 'trading212', 'news_agent',
        'ai_client', 'database', 'data_loader',
        'risk_manager', 'types_shared', 'asset_registry', 'cpu_config',
        'market_hours', 'core.market_hours',
        'desktop.panels.exchanges',
        'terminal.state',
        # v2.0.0: state durability + auto-update
        # paths is referenced from desktop.state + main, which PyInstaller
        # picks up via static imports, but the update_service + banner +
        # schedule dialog are loaded lazily by app.py (`from desktop.panels...
        # import UpdateBanner` etc.) so we must pin them explicitly.
        'desktop.paths',
        'desktop.fonts',
        'desktop.onboarding',
        'desktop.dialogs._base',
        'desktop.update_service',
        'desktop.panels.update_banner',
        'desktop.panels.mandatory_update_overlay',
        'desktop.dialogs.schedule_update',
        'packaging', 'packaging.version', 'packaging.specifiers',
        # Agent runtime (Phase 4+)
        'claude_agent_sdk', 'core.agent._sdk',
        'core.agent', 'core.agent.runner', 'core.agent.mcp_server',
        'core.agent.prompts', 'core.agent.context',
        'core.agent.tools', 'core.agent.tools.broker_tools',
        'core.agent.tools.market_tools', 'core.agent.tools.risk_tools',
        'core.agent.tools.memory_tools', 'core.agent.tools.watchlist_tools',
        'core.agent.tools.news_tools', 'core.agent.tools.social_tools',
        'core.agent.tools.browser_tools',
        'core.agent.tools.market_hours_tools',
        'core.agent.tools.backtest_tools',
        'core.agent.tools.flow_tools',
        # Research swarm (Phase 5+)
        'core.agent.swarm', 'core.agent.research_worker',
        'core.agent.research_queue', 'core.agent.research_roles',
        'core.agent.prompts_research',
        'core.agent.tools.research_tools', 'core.agent.tools.grok_tools',
        'playwright', 'playwright.async_api',
        # Scraper daemon (Phase 5)
        'core.scrapers', 'core.scrapers.base', 'core.scrapers.runner',
        'core.scrapers.google_news', 'core.scrapers.yahoo_finance',
        'core.scrapers.bbc', 'core.scrapers.bloomberg',
        'core.scrapers.marketwatch', 'core.scrapers.youtube',
        'core.scrapers.stocktwits', 'core.scrapers.reddit',
        'core.scrapers.x_via_gnews',
        # Multi-asset packages (on ice)
        'crypto', 'crypto.types', 'crypto.data_loader', 'crypto.features',
        'crypto.ensemble', 'crypto.regime', 'crypto.broker', 'crypto.strategy',
        'polymarket', 'polymarket.types', 'polymarket.data_loader', 'polymarket.features',
        'polymarket.model', 'polymarket.regime', 'polymarket.broker',
        'polymarket.strategy', 'polymarket.mirofish', 'polymarket.research',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'jax', 'jax.numpy', 'jax.nn', 'jax.experimental',
        'cuda', 'cudf', 'cupy', 'cupyx', 'nvidia', 'cuda.bindings',
        'dask', 'distributed', 'numba', 'textual', 'pytest',
        'psycopg', 'psycopg2', 'psycopg2cffi', 'pymysql', 'sqlalchemy',
        'IPython', 'sphinx', 'numpydoc', 'traitlets',
        'matplotlib', 'tornado', 'werkzeug', 'Cython', 'cython',
        'odf', 'polars', 'pyamg', 'sksparse', 'cvxopt',
        'graphviz', 'viztracer', 'uarray', 'ndonnx',
        'array_api_strict', 'sparse', 'colorcet',
        'datatable', 'python_calamine', 'pyxlsb',
        'tables', 'fsspec', 'botocore', 'adbc_driver_manager',
        'py_clob_client',
        'AppKit', 'Foundation', 'android', 'java', 'jnius',
        'pyodide', 'pyodide_js', 'js',
        'h2', 'eventlet', 'gevent', 'python_socks', 'socks',
        'OpenSSL', 'cryptography',
        'genshi', 'markdownify', 'readability',
        'ccxt', 'django', 'macholib', 'yapf',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='blank',
    debug=False, bootloader_ignore_signals=False, strip=False,
    upx=True, upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'),
    version=str(Path(PROJECT_ROOT) / 'version_info.py'),
)
