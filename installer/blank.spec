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
        # --- Qt ---
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtSvg', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'pyqtgraph', 'pyqtgraph.graphicsItems', 'pyqtgraph.graphicsItems.PlotItem', 'pyqtgraph.opengl',
        # --- Scientific stack ---
        'pandas', 'pandas.plotting', 'pandas.io.formats.style',
        'joblib', 'xgboost', 'xgboost.core', 'xgboost.tracker', 'lightgbm',
        'einops',
        # --- IO / parsing ---
        'jinja2', 'markupsafe',
        'openpyxl', 'openpyxl.cell', 'openpyxl.descriptors', 'openpyxl.styles', 'openpyxl.workbook',
        'lxml', 'lxml.etree', 'lxml.html',
        'html5lib', 'html5lib.constants', 'html5lib.treebuilders',
        'bottleneck', 'numexpr', 'psutil', 'yaml', 'simplejson', 'orjson',
        'brotli', 'lz4', 'lz4.frame', 'xlrd', 'xlsxwriter', 'h5py', 'chardet',
        'dateutil.tz.tzfile', 'six.moves', 'six.moves.range',
        'yfinance', 'feedparser', 'requests',
        'packaging', 'packaging.version', 'packaging.specifiers',
        # --- Sentiment / NLP ---
        # vaderSentiment loads eagerly at module import in core.scrapers._sentiment
        'vaderSentiment', 'vaderSentiment.vaderSentiment',
        # transformers + youtube_transcript_api are lazy-imported inside
        # core.nlp.finbert and core.scrapers.youtube_transcripts respectively,
        # but PyInstaller's static analysis misses them.
        'transformers', 'youtube_transcript_api',
        # --- core (top-level, on sys.path via pathex) ---
        'broker_service', 'broker', 'trading212',
        'database', 'data_loader', 'paper_broker',
        'risk_manager', 'types_shared', 'asset_registry', 'cpu_config',
        'market_hours', 'core.market_hours',
        'fx', 'personality_seeder', 'trader_personality',
        'trade_reflector', 'kronos_forecaster',
        'core.config_schema', 'core.database', 'core.paper_broker',
        'core.trade_reflector', 'core.fx',
        # --- core.agent (Claude Agent loop) ---
        'claude_agent_sdk', 'core.agent._sdk', 'core.agent.subprocess_patch',
        'core.agent', 'core.agent.runner', 'core.agent.mcp_server',
        'core.agent.prompts', 'core.agent.prompts_research',
        'core.agent.context', 'core.agent.paths',
        'core.agent.pool', 'core.agent.chat_worker',
        'core.agent.assessor', 'core.agent.model_router',
        'core.agent.swarm', 'core.agent.research_worker',
        'core.agent.research_queue', 'core.agent.research_roles',
        # --- core.agent.tools (24 modules) ---
        'core.agent.tools',
        'core.agent.tools.alt_data_tools',
        'core.agent.tools.backtest_tools',
        'core.agent.tools.broker_tools',
        'core.agent.tools.browser_tools',
        'core.agent.tools.ensemble_tools',
        'core.agent.tools.execution_tools',
        'core.agent.tools.flow_tools',
        'core.agent.tools.forecast_tools',
        'core.agent.tools.grok_tools',
        'core.agent.tools.indicator_tools',
        'core.agent.tools.insider_tools',
        'core.agent.tools.market_hours_tools',
        'core.agent.tools.market_tools',
        'core.agent.tools.memory_tools',
        'core.agent.tools.news_tools',
        'core.agent.tools.performance_tools',
        'core.agent.tools.personality_tools',
        'core.agent.tools.research_tools',
        'core.agent.tools.risk_tools',
        'core.agent.tools.rl_tools',
        'core.agent.tools.sentiment_tools',
        'core.agent.tools.social_tools',
        'core.agent.tools.strategy_backtest_tools',
        'core.agent.tools.watchlist_tools',
        'playwright', 'playwright.async_api',
        # --- core.scrapers ---
        'core.scrapers', 'core.scrapers.base', 'core.scrapers.runner',
        'core.scrapers._sentiment', 'core.scrapers._transcript_summariser',
        'core.scrapers._vision_summariser',
        'core.scrapers.google_news', 'core.scrapers.yahoo_finance',
        'core.scrapers.bbc', 'core.scrapers.bloomberg',
        'core.scrapers.marketwatch', 'core.scrapers.youtube',
        'core.scrapers.stocktwits', 'core.scrapers.reddit',
        'core.scrapers.x_via_gnews',
        'core.scrapers.sec_insider', 'core.scrapers.options_flow',
        'core.scrapers.youtube_transcripts', 'core.scrapers.youtube_live_vision',
        # --- core.forecasting / nlp / alt_data / execution / rl / kronos ---
        'core.forecasting', 'core.forecasting.chronos_forecaster',
        'core.forecasting.timesfm_forecaster', 'core.forecasting.tft_forecaster',
        'core.forecasting.ensemble', 'core.forecasting.meta_learner',
        'core.nlp', 'core.nlp.finbert',
        'core.alt_data', 'core.alt_data.analyst_revisions',
        'core.execution', 'core.execution.vwap',
        'core.rl', 'core.rl.finrl_scaffold',
        'core.kronos', 'core.kronos.kronos', 'core.kronos.module',
        'core.finetune', 'core.finetune.terminal_finetune',
        # --- desktop (lazy imports not caught by static analysis) ---
        'desktop.paths', 'desktop.fonts', 'desktop.onboarding',
        'desktop.theme', 'desktop.tokens', 'desktop.design',
        'desktop.license', 'desktop.update_service', 'desktop.updater',
        'desktop.data_export', 'desktop.workers', 'desktop.state',
        # panels
        'desktop.panels', 'desktop.panels.agent_log', 'desktop.panels.chart',
        'desktop.panels.chat', 'desktop.panels.exchanges',
        'desktop.panels.mandatory_update_overlay', 'desktop.panels.news',
        'desktop.panels.orders', 'desktop.panels.positions',
        'desktop.panels.settings', 'desktop.panels.update_banner',
        'desktop.panels.watchlist',
        # dialogs
        'desktop.dialogs', 'desktop.dialogs._base',
        'desktop.dialogs.about', 'desktop.dialogs.add_ticker',
        'desktop.dialogs.help', 'desktop.dialogs.history',
        'desktop.dialogs.instruments', 'desktop.dialogs.license',
        'desktop.dialogs.mode_selector', 'desktop.dialogs.pies',
        'desktop.dialogs.risk_disclosure', 'desktop.dialogs.schedule_update',
        'desktop.dialogs.search_ticker', 'desktop.dialogs.setup_wizard',
        'desktop.dialogs.trade',
        # widgets + primitives
        'desktop.widgets', 'desktop.widgets.mode_banner',
        'desktop.widgets.mode_watermark',
        'desktop.widgets.primitives',
        'desktop.widgets.primitives.button', 'desktop.widgets.primitives.card',
        'desktop.widgets.primitives.divider',
        'desktop.widgets.primitives.grain_overlay',
        'desktop.widgets.primitives.kicker',
        'desktop.widgets.primitives.segmented',
        'desktop.widgets.primitives.sentiment_bar',
        'desktop.widgets.primitives.status_dot',
        'desktop.widgets.primitives.underline_input',
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
