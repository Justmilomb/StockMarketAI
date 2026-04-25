"""Provider factory + process-wide singleton accessor.

Use :func:`get_provider` from any caller that wants market data:

    from core.data import get_provider
    quotes = get_provider().fetch_live_prices(["AAPL", "RR.L"])

The active backend is decided once per process from ``config.json``:

    {
      "data_provider": {
        "primary": "yfinance",
        "fmp_enabled": false,
        "fmp_key_env": "FMP_KEY",
        "fmp_base_url": "https://financialmodelingprep.com/api/v3",
        "fmp_websocket_url": "wss://websockets.financialmodelingprep.com"
      }
    }

Switching to FMP requires both ``fmp_enabled = true`` AND
``primary = "fmp"`` AND a populated key. Any of those missing and we
fall back to yfinance with a one-line warning so a half-configured
machine never silently swaps backends.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.data.base_provider import BaseDataProvider

logger = logging.getLogger(__name__)


_lock = threading.Lock()
_provider: Optional[BaseDataProvider] = None


def _resolve_config_path() -> Path:
    """Pick the right config.json — frozen builds use %LOCALAPPDATA%, dev uses repo root."""
    import sys
    if getattr(sys, "frozen", False):
        try:
            from desktop.paths import config_path as _user_config_path
            return _user_config_path()
        except Exception:
            pass
    here = Path(__file__).resolve()
    # core/data/provider.py → repo root is two levels up from core/
    return here.parents[2] / "config.json"


def _load_provider_config() -> Dict[str, Any]:
    """Read just the ``data_provider`` block from config.json — safe defaults if missing."""
    defaults: Dict[str, Any] = {
        "primary": "yfinance",
        "fmp_enabled": False,
        "fmp_key_env": "FMP_KEY",
        "fmp_base_url": "https://financialmodelingprep.com/api/v3",
        "fmp_base_url_v4": "https://financialmodelingprep.com/api/v4",
        "fmp_websocket_url": "wss://websockets.financialmodelingprep.com",
    }
    try:
        path = _resolve_config_path()
        if not path.exists():
            return defaults
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.debug("could not read data_provider config: %s", e)
        return defaults
    block = data.get("data_provider")
    if not isinstance(block, dict):
        return defaults
    merged = dict(defaults)
    merged.update(block)
    return merged


def _build_provider(cfg: Dict[str, Any]) -> BaseDataProvider:
    """Construct the configured backend, falling back loudly to yfinance."""
    primary = str(cfg.get("primary", "yfinance")).strip().lower()
    fmp_enabled = bool(cfg.get("fmp_enabled", False))
    key_env = str(cfg.get("fmp_key_env", "FMP_KEY"))
    has_key = bool(os.environ.get(key_env, "").strip())

    if primary == "fmp":
        if not fmp_enabled:
            logger.warning(
                "data_provider.primary=fmp but fmp_enabled=false; "
                "using yfinance (set fmp_enabled=true to activate FMP)",
            )
        elif not has_key:
            logger.warning(
                "data_provider.primary=fmp but env var %s is empty; "
                "using yfinance (export the key to activate FMP)",
                key_env,
            )
        else:
            from core.data.fmp_provider import FMPProvider
            logger.info("data provider: FMP Enterprise (primary)")
            return FMPProvider(
                api_key_env=key_env,
                base_url=str(cfg.get("fmp_base_url")),
                base_url_v4=str(cfg.get("fmp_base_url_v4")),
                websocket_url=str(cfg.get("fmp_websocket_url")),
            )

    from core.data.yfinance_provider import YFinanceProvider
    logger.info("data provider: yfinance (primary)")
    return YFinanceProvider()


def get_provider() -> BaseDataProvider:
    """Return the process-wide data provider, building it on first call."""
    global _provider
    if _provider is not None:
        return _provider
    with _lock:
        if _provider is None:
            cfg = _load_provider_config()
            _provider = _build_provider(cfg)
    return _provider


def reset_provider() -> None:
    """Tear down the cached provider so the next ``get_provider`` rebuilds.

    Used by tests that flip config + want a fresh backend, and by the
    desktop app when the user changes the data-source setting at
    runtime. Closes any open WebSocket sessions on the way out.
    """
    global _provider
    with _lock:
        old = _provider
        _provider = None
    if old is not None:
        try:
            old.close()
        except Exception:
            logger.debug("provider close raised", exc_info=True)
