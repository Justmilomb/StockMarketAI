"""Symmetric secret encryption for at-rest sensitive values (e.g. T212 API keys)."""
from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

_log = logging.getLogger("blank.encryption")


def _derive_dev_key(secret: str) -> bytes:
    """Build a deterministic Fernet key from any string.

    Used only when ``BLANK_T212_ENCRYPTION_KEY`` is unset (dev mode). The
    JWT secret is reused as the source so dev environments work without
    extra configuration. In production the env var must be set to a
    proper randomly generated Fernet key.
    """
    raw = secret.encode("utf-8")
    padded = raw.ljust(32, b"0")[:32]
    return base64.urlsafe_b64encode(padded)


def _get_fernet() -> Fernet:
    key = os.environ.get("BLANK_T212_ENCRYPTION_KEY", "").strip()
    if not key:
        secret = os.environ.get("BLANK_JWT_SECRET", "dev-jwt-secret-do-not-ship")
        _log.warning(
            "BLANK_T212_ENCRYPTION_KEY not set — falling back to JWT-derived key (UNSAFE for production)",
        )
        return Fernet(_derive_dev_key(secret))
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("encrypted secret could not be decrypted") from exc
