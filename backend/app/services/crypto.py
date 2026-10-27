"""Credential encryption at rest (Fernet envelope).

Addresses the long-standing ``# TODO: encrypt with Fernet`` in the connection
registry. Design goals from the SAP connector spec:

- Never store plaintext credentials in the connection table.
- Keep the encryption key OUTSIDE the database (configured via
  ``CREDENTIAL_ENCRYPTION_KEY``; derived from ``APP_SECRET_KEY`` only as a
  development convenience so the app runs out of the box).
- Support key rotation: newer values are encrypted with the current key, and a
  list of *previous* keys is retained only so older ciphertext can still be
  decrypted during a rotation window.
- Stay backward compatible: any value that is not marked as encrypted is treated
  as a legacy plaintext secret and returned unchanged, so existing rows (and the
  cross-source bootstrap) keep working until they are rewritten.

Nothing here logs secret material. Callers must not log the return values.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)

# Marker prefix so we can distinguish encrypted values from legacy plaintext.
_ENC_PREFIX = "fernet:v1:"


def _derive_key(secret: str) -> bytes:
    """Derive a deterministic 32-byte urlsafe Fernet key from an arbitrary secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _current_key() -> bytes:
    settings = get_settings()
    configured = (settings.credential_encryption_key or "").strip()
    if configured:
        # Validate it is a usable Fernet key; fall back to derived on misconfig.
        try:
            Fernet(configured.encode("utf-8"))
            return configured.encode("utf-8")
        except Exception:
            logger.warning("CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key; deriving from APP_SECRET_KEY")
    return _derive_key(settings.app_secret_key)


def _candidate_keys() -> list[bytes]:
    """Current key first, then any configured previous keys (for decryption)."""
    keys = [_current_key()]
    settings = get_settings()
    for prev in (settings.credential_encryption_key_previous or "").split(","):
        prev = prev.strip()
        if prev:
            keys.append(prev.encode("utf-8"))
    return keys


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_ENC_PREFIX)


def encrypt_secret(plaintext: str | None) -> str:
    """Encrypt a secret for storage. Idempotent: already-encrypted values pass through."""
    if plaintext is None:
        return ""
    if is_encrypted(plaintext):
        return plaintext  # already encrypted; do not double-wrap
    token = Fernet(_current_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_secret(stored: str | None) -> str:
    """Return the usable secret.

    Encrypted values are decrypted with the current key (then any rotation keys).
    Unmarked legacy values are assumed to already be plaintext and returned as-is,
    so existing rows and the cross-source bootstrap keep working until rewritten.
    """
    if not stored:
        return ""
    if not is_encrypted(stored):
        return stored  # legacy plaintext
    token = stored[len(_ENC_PREFIX):].encode("ascii")
    for key in _candidate_keys():
        try:
            return Fernet(key).decrypt(token).decode("utf-8")
        except InvalidToken:
            continue
    # Never surface token material in the exception message.
    logger.error("Failed to decrypt a stored credential (no matching key)")
    raise ValueError("Unable to decrypt stored credential: encryption key mismatch")


def reencrypt_if_needed(stored: str | None) -> str | None:
    """Return a value encrypted with the CURRENT key.

    Used to transparently upgrade legacy plaintext (or older-key ciphertext) on
    the next write, supporting rotation without a bulk migration.
    """
    if not stored:
        return stored
    if is_encrypted(stored):
        # Verify it decrypts with the current key; if not, re-wrap.
        key = _current_key()
        token = stored[len(_ENC_PREFIX):].encode("ascii")
        try:
            Fernet(key).decrypt(token)
            return stored
        except InvalidToken:
            return encrypt_secret(decrypt_secret(stored))
    return encrypt_secret(stored)  # upgrade plaintext to encrypted
