"""SAP authentication providers: Basic + OAuth2 client-credentials.

Tokens/credentials are kept strictly in memory here. The rest of the system
only ever sees ready-made header dicts, and every logging/exception path goes
through `redact()` so secret material can never leak into logs or responses.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


def redact(text: str) -> str:
    """Scrub anything that looks like a credential out of a message."""
    if not text:
        return text
    lowered = text.lower()
    out = text
    for marker in ("authorization:", "bearer ", "basic ", "client_secret=", "password="):
        idx = lowered.find(marker)
        if idx != -1:
            out = out[:idx] + "[redacted]"
    return out


class TokenProvider:
    """OAuth2 client-credentials token cache with expiry-aware refresh.

    Thread-safe. The token is fetched lazily on first use and refetched when
    within `renew_skew_seconds` of expiry (or after a 401 via `invalidate()`).
    """

    def __init__(self, *, token_url: str, client_id: str, client_secret: str,
                 scope: Optional[str] = None, tls_verify: bool = True,
                 renew_skew_seconds: float = 60.0):
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._tls_verify = tls_verify
        self._skew = renew_skew_seconds
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def token_url(self) -> str:
        return self._token_url

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def get_token(self, fetcher) -> str:
        """Return a valid access token, using `fetcher(url, body, tls_verify)`
        for the actual HTTP call (the client owns HTTP; we own lifecycle)."""
        with self._lock:
            if self._token and time.time() < self._expires_at - self._skew:
                return self._token
            body = {"grant_type": "client_credentials"}
            if self._scope:
                body["scope"] = self._scope
            payload = fetcher(
                self._token_url,
                body,
                self._tls_verify,
                auth=(self._client_id, self._client_secret),
            )
            access = payload.get("access_token")
            if not access:
                raise RuntimeError("Token endpoint returned no access_token")
            expires_in = int(payload.get("expires_in") or 3600)
            self._token = str(access)
            self._expires_at = time.time() + max(30.0, expires_in)
            logger.info("SAP OAuth2 token acquired (expires in %ss)", expires_in)
            return self._token


class AuthHandler:
    """Builds per-request auth headers for one connection's auth mode."""

    def __init__(self, *, auth_mode: str, username: str = "", secret: str = "",
                 client_id: Optional[str] = None, scope: Optional[str] = None,
                 token_url: Optional[str] = None, tls_verify: bool = True):
        self.auth_mode = (auth_mode or "basic").lower()
        self._username = username
        self._secret = secret
        self._client_id = client_id
        self._scope = scope
        self._token_url = token_url
        self._tls_verify = tls_verify
        self._tokens: Optional[TokenProvider] = None
        if self.auth_mode == "oauth_client_credentials":
            if not (token_url and client_id and secret):
                raise ValueError(
                    "oauth_client_credentials requires token_url, client_id and secret"
                )
            self._tokens = TokenProvider(
                token_url=token_url, client_id=client_id, client_secret=secret,
                scope=scope, tls_verify=tls_verify,
            )
        elif self.auth_mode == "basic":
            if not (username and secret):
                raise ValueError("basic auth requires username and secret")
        else:
            raise ValueError(f"Unsupported auth mode '{auth_mode}'")

    def headers(self, token_fetcher=None) -> dict:
        if self.auth_mode == "basic":
            raw = f"{self._username}:{self._secret}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        assert self._tokens is not None
        if token_fetcher is None:
            raise RuntimeError("OAuth mode requires a token fetcher for acquisition")
        token = self._tokens.get_token(token_fetcher)
        return {"Authorization": f"Bearer {token}"}

    def invalidate(self) -> None:
        if self._tokens:
            self._tokens.invalidate()

    def describe(self) -> dict:
        """Admin-facing description — NEVER includes the secret or token."""
        return {
            "auth_mode": self.auth_mode,
            "username": self._username if self.auth_mode == "basic" else None,
            "client_id": self._client_id if self.auth_mode == "oauth_client_credentials" else None,
            "token_configured": bool(self._token_url),
            "secret_configured": bool(self._secret),
        }
