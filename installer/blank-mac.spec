# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for blank desktop application — macOS edition.

Build:
    pyinstaller installer/blank-mac.spec --clean

Output: dist/blank.app

Mirrors installer/blank.spec one-for-one — same datas, same
hiddenimports, same excludes — and adds a BUNDLE step at the end so
PyInstaller emits a proper .app rather than a bare Mach-O. Differences
from the Windows spec:

    * icon is desktop/assets/icon.icns (not .ico)
    * no Windows VERSIONINFO resource (the .app's Info.plist takes its
      version from the BUNDLE info kwarg below)
    * no xgboost/lightgbm DLL hunting — the macOS wheels ship .dylibs
      that PyInstaller picks up automatically via the standard binary
      analysis.
"""

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


_font_datas = [
    (str(p), 'desktop/assets/fonts')
    for p in (Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'fonts').glob('*')
    if p.suffix.lower() in ('.ttf', '.otf')
]

_avatar_datas = [
    (str(p), 'desktop/assets/avatars')
    for p in (Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'avatars').glob('*.svg')
]

# Bundled HuggingFace models — populated by ``scripts/download_models.py``
# before the build runs. Empty if the script wasn't run, in which case
# the desktop app falls back to downloading on first use.
_model_datas = []
_models_root = Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'models'
if _models_root.is_dir():
    for path in _models_root.rglob('*'):
        if not path.is_file():
            continue
        if any(part in {'.cache', '.huggingface'} for part in path.parts):
            continue
        rel_dir = path.parent.relative_to(_models_root.parent.parent)
        _model_datas.append((str(path), str(rel_dir).replace('\\', '/')))


# Resolve the icon. Inno Setup needs a .ico on Windows; macOS .app
# bundles need a .icns. We don't generate the .icns here — the user is
# expected to drop one alongside icon.ico. When it's missing we fall
# back to the .ico (PyInstaller will warn but produce a usable bundle
# with a generic icon) so a fresh checkout still builds.
_icon_path = Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.icns'
if not _icon_path.exists():
    _icon_path = Path(PROJECT_ROOT) / 'desktop' / 'assets' / 'icon.ico'
icon_for_bundle = str(_icon_path) if _icon_path.exists() else None


a = Analysis(
    [str(Path(PROJECT_ROOT) / 'desktop' / 'main_desktop.py')],
    pathex=[PROJECT_ROOT, str(Path(PROJECT_ROOT) / 'core')],
    binaries=[],
    datas=[
        (str(Path(PROJECT_ROOT) / 'config.default.json'), '.'),
        # Ship whichever icon variants exist so the app can render
        # window icons even when running from inside the .app bundle.
        *(
            [(str(Path(PROJECT_ROOT) / 'desktop' / 'assets' / name), 'desktop/assets')]
            for name in ('icon.icns', 'icon.ico')
            if (Path(PROJECT_ROOT) / 'desktop' / 'assets' / name).exists()
        ),
        *_font_datas,
        *_avatar_datas,
        *_model_datas,
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
        'vaderSentiment', 'vaderSentiment.vaderSentiment',
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
        # --- core.agent ---
        'claude_agent_sdk', 'core.agent._sdk', 'core.agent.subprocess_patch',
        'core.agent', 'core.agent.runner', 'core.agent.mcp_server',
        'core.agent.prompts', 'core.agent.prompts_research',
        'core.agent.context', 'core.agent.paths',
        'core.agent.pool', 'core.agent.chat_worker',
        'core.agent.assessor', 'core.agent.model_router',
        'core.agent.swarm', 'core.agent.research_worker',
        'core.agent.research_queue', 'core.agent.research_roles',
        # --- core.agent.tools ---
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
        # --- desktop ---
        'desktop.paths', 'desktop.fonts', 'desktop.onboarding',
        'desktop.onboarding_state',
        'desktop.theme', 'desktop.tokens', 'desktop.design',
        'desktop.license', 'desktop.update_service', 'desktop.updater',
        'desktop.data_export', 'desktop.workers', 'desktop.state',
        'desktop.dev_monitor',
        'desktop.auth', 'desktop.auth_state', 'desktop.auth_gate',
        'desktop.auth_callback_server', 'desktop.avatars',
        # panels
        'desktop.panels', 'desktop.panels.agent_log', 'desktop.panels.chart',
        'desktop.panels.chat', 'desktop.panels.exchanges',
        'desktop.panels.mandatory_update_overlay', 'desktop.panels.news',
        'desktop.panels.orders', 'desktop.panels.positions',
        'desktop.panels.settings', 'desktop.panels.update_banner',
        'desktop.panels.watchlist',
        # dialogs
        'desktop.dialogs', 'desktop.dialogs._base',
        'desktop.dialogs.about',
        'desktop.dialogs.account_dashboard', 'desktop.dialogs.account_settings',
        'desktop.dialogs.help', 'desktop.dialogs.history',
        'desktop.dialogs.signin',
        'desktop.dialogs.live_onboarding',
        'desktop.dialogs.mode_selector',
        'desktop.dialogs.paper_onboarding',
        'desktop.dialogs.risk_disclosure', 'desktop.dialogs.schedule_update',
        'desktop.dialogs.setup_wizard',
        # widgets + primitives
        'desktop.widgets', 'desktop.widgets.mode_banner',
        'desktop.widgets.mode_watermark',
        'desktop.widgets.profile_button', 'desktop.widgets.signin_banner',
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
        'android', 'java', 'jnius',
        'pyodide', 'pyodide_js', 'js',
        'h2', 'eventlet', 'gevent', 'python_socks', 'socks',
        'OpenSSL', 'cryptography',
        'genshi', 'markdownify', 'readability',
        'ccxt', 'django', 'yapf',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# windowed=True == bundle as a .app on macOS — without this PyInstaller
# emits a CLI binary that opens a Terminal window when launched from
# Finder.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='blank',
    debug=False, bootloader_ignore_signals=False, strip=False,
    upx=False,  # upx on macOS is not worth the codesign hassle.
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    # Universal2 builds require both wheels; default to native arch.
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_for_bundle,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='blank',
)

# Read the product version from desktop/__init__.py so the .app's
# Info.plist matches the in-app version banner. Falls back to "1.0.0"
# when the file is missing — never fails the build.
def _read_version() -> str:
    init_path = Path(PROJECT_ROOT) / 'desktop' / '__init__.py'
    try:
        text = init_path.read_text(encoding='utf-8')
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('__version__'):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return '1.0.0'


app = BUNDLE(
    coll,
    name='blank.app',
    icon=icon_for_bundle,
    # CFBundleIdentifier — keep this stable, macOS uses it as the key
    # for launch-services registration, login items, and TCC privacy
    # prompts. Renaming it forces every Mac user to re-grant
    # microphone/camera/network permissions on the next launch.
    bundle_identifier='ai.useblank.desktop',
    version=_read_version(),
    info_plist={
        'CFBundleName': 'blank',
        'CFBundleDisplayName': 'blank',
        'CFBundleShortVersionString': _read_version(),
        'CFBundleVersion': _read_version(),
        'NSHighResolutionCapable': True,
        # Tell macOS this is a regular GUI app, not an agent or
        # menubar-only utility — Dock icon + menubar appear normally.
        'LSApplicationCategoryType': 'public.app-category.finance',
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription': 'blank uses AppleScript to control its own dock icon during updates.',
    },
)
