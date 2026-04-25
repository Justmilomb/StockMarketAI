"""HuggingFace credential resolution.

Two keys, two purposes:

* ``HF_TOKEN_READ`` — model downloads (Kronos, FinBERT, Chronos, TimesFM).
  Used on every ``from_pretrained`` call so private / gated models the
  user has access to also resolve, and so the rate-limited anonymous
  endpoint isn't hit on first load.
* ``HF_TOKEN_WRITE`` — uploads only. Read by :func:`write_token` and
  consumed by any future ``upload_model`` / ``push_to_hub`` path.

Backwards compat: if neither ``HF_TOKEN_READ`` nor ``HF_TOKEN_WRITE``
is set but the legacy ``HF_TOKEN`` is, we treat it as the read token.
That keeps existing installs working while we transition.

Why we set ``HUGGING_FACE_HUB_TOKEN``: most of the HF stack (the hub
client, ``transformers.pipeline``, ``timesfm``) reads that env var
automatically. Calling :func:`apply_read_token` once at process start
is cheaper than passing ``token=`` to every loader.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_READ_ENV = "HF_TOKEN_READ"
_WRITE_ENV = "HF_TOKEN_WRITE"
_LEGACY_ENV = "HF_TOKEN"
_HUB_ENV = "HUGGING_FACE_HUB_TOKEN"

_apply_lock = threading.Lock()
_applied = False


def read_token() -> Optional[str]:
    """Return the read-only HuggingFace token, or ``None`` if unset.

    Preference order: ``HF_TOKEN_READ`` → legacy ``HF_TOKEN``. Empty
    strings count as unset.
    """
    val = os.environ.get(_READ_ENV, "").strip()
    if val:
        return val
    legacy = os.environ.get(_LEGACY_ENV, "").strip()
    return legacy or None


def write_token() -> Optional[str]:
    """Return the write-scope HuggingFace token, or ``None`` if unset."""
    val = os.environ.get(_WRITE_ENV, "").strip()
    return val or None


def apply_read_token() -> Optional[str]:
    """Export the read token as ``HUGGING_FACE_HUB_TOKEN``.

    Idempotent — only applies once per process. Returns the resolved
    token (or ``None`` if neither env var was set, in which case the
    HF stack falls back to anonymous downloads).
    """
    global _applied
    if _applied:
        return os.environ.get(_HUB_ENV, "").strip() or None
    with _apply_lock:
        if _applied:
            return os.environ.get(_HUB_ENV, "").strip() or None
        token = read_token()
        if token:
            # Don't clobber an explicit override the user already set.
            if not os.environ.get(_HUB_ENV, "").strip():
                os.environ[_HUB_ENV] = token
            logger.debug("hf_auth: read token applied to HUGGING_FACE_HUB_TOKEN")
        else:
            logger.debug("hf_auth: no read token set; HF downloads will be anonymous")
        _applied = True
        return token


def assert_write_token() -> str:
    """Return the write token, raising ``RuntimeError`` if missing.

    Use at the top of any upload path so a missing key fails loudly
    instead of getting a cryptic ``401`` halfway through ``push_to_hub``.
    """
    tok = write_token()
    if not tok:
        raise RuntimeError(
            f"HuggingFace write token not set: export {_WRITE_ENV}. "
            "(HF_TOKEN_READ is for downloads only.)",
        )
    return tok
