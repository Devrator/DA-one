"""OData HTTP client: guarded transport for the SAP connector.

Responsibilities (spec §4, §7, §14):
  * validate EVERY outbound URL against the admin allowlist (SSRF fail-closed),
    including server-supplied pagination continuation URLs;
  * do NOT follow redirects automatically (a hostile Location is refused);
  * bounded pagination: page size, max records, max pages, overall deadline;
  * retry only idempotent GETs on transient failures (429/5xx/network) with
    exponential backoff + jitter, honoring Retry-After;
  * cap response size before buffering;
  * classify failures (DNS/network vs TLS vs authn vs authz vs API) with
    credential-redacted messages.
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlsplit

import httpx

from app.services.connectors.base import (
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ConnectivityError,
    ConnectorError,
)
from app.services.connectors.net_security import (
    UnsafeURLError,
    validate_continuation_url,
    validate_url,
)
from app.services.connectors.sap_s4hana.auth import AuthHandler, redact
from app.services.connectors.sap_s4hana.odata import parse_page, strip_odata_annotations

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 502, 503, 504}
_MAX_PAGES_HARD_CAP = 100


class ODataClient:
    def __init__(self, ctx, auth: AuthHandler):
        self.ctx = ctx
        self.auth = auth

    # -- low level ----------------------------------------------------------

    def _safe_url(self, url: str) -> str:
        try:
            return validate_url(url, self.ctx.allowed_hosts)
        except UnsafeURLError as exc:
            raise ConfigurationError(f"Blocked by URL policy: {redact(str(exc))}") from exc

    def _client(self) -> httpx.Client:
        return httpx.Client(
            verify=self.ctx.tls_verify,
            follow_redirects=False,   # we classify redirects, never chase them
            timeout=httpx.Timeout(self.ctx.timeout_seconds, connect=min(10.0, self.ctx.timeout_seconds)),
        )

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json", "DataServiceVersion": "2.0"}
        if self.auth.auth_mode == "oauth_client_credentials":
            headers.update(self.auth.headers(token_fetcher=self._token_fetcher))
        else:
            headers.update(self.auth.headers())
        if extra:
            headers.update(extra)
        return headers

    def _token_fetcher(self, url: str, body: dict, tls_verify: bool, auth: tuple) -> dict:
        """OAuth2 token acquisition (called by AuthHandler). Not retried."""
        self._safe_url(url)
        try:
            with httpx.Client(verify=tls_verify, timeout=self.ctx.timeout_seconds,
                              follow_redirects=False) as client:
                resp = client.post(url, data=body, auth=auth)
        except httpx.HTTPError as exc:
            raise ConnectivityError(f"Token endpoint unreachable: {redact(str(exc))}") from exc
        if resp.status_code == 401:
            raise AuthenticationError("Token endpoint rejected credentials (HTTP 401)")
        if resp.status_code >= 400:
            raise AuthenticationError(f"Token endpoint returned HTTP {resp.status_code}")
        return resp.json()

    def _classify(self, resp: httpx.Response, url: str) -> ConnectorError:
        loc = f"{urlsplit(url).netloc}{urlsplit(url).path}"
        if resp.status_code in (401,):
            return AuthenticationError(f"SAP rejected credentials (HTTP 401 at {loc})")
        if resp.status_code in (403, 405):
            return AuthorizationError(f"SAP denied authorization for this resource (HTTP {resp.status_code} at {loc})")
        if resp.status_code == 404:
            return ConnectorError(f"SAP resource not found (HTTP 404 at {loc})", category="not_found")
        body_snippet = redact(resp.text or "")[:400]
        return ConnectorError(
            f"SAP API error HTTP {resp.status_code} at {loc}: {body_snippet}",
            category="api_error",
        )

    def _check_redirect(self, resp: httpx.Response, url: str) -> None:
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            raise ConfigurationError(
                f"Refusing to follow redirect from {urlsplit(url).netloc} to "
                f"{redact(location) or '(empty)'} — redirect targets must be "
                "explicitly approved by an administrator"
            )

    def _read_capped(self, resp: httpx.Response) -> bytes:
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.ctx.max_response_bytes:
            raise ConnectorError(
                f"Response declares {declared} bytes over the {self.ctx.max_response_bytes} cap",
                category="size_limit",
            )
        data = resp.content  # httpx already buffered (we do not stream metadata)
        if len(data) > self.ctx.max_response_bytes:
            raise ConnectorError(
                f"Response exceeded size cap ({self.ctx.max_response_bytes} bytes)",
                category="size_limit",
            )
        return data

    # -- GET with retry ------------------------------------------------------

    def get(self, url: str, *, params: dict | None = None, accept: str = "application/json") -> httpx.Response:
        full = url
        if params:
            from app.services.connectors.sap_s4hana.odata import append_params
            full = append_params(url, params)
        self._safe_url(full)

        attempt = 0
        while True:
            try:
                with self._client() as client:
                    resp = client.get(full, headers=self._headers({"Accept": accept}))
            except httpx.TimeoutException as exc:
                raise ConnectivityError(f"SAP request timed out: {redact(str(exc))}") from exc
            except httpx.TLSViolation as exc:  # cert problems are NOT transient
                raise ConnectivityError(f"TLS verification failed: {redact(str(exc))}") from exc
            except httpx.HTTPError as exc:
                if attempt < self.ctx.max_retries:
                    delay = self._backoff(attempt, None)
                    logger.warning("SAP network error (attempt %s/%s), retrying in %.2fs: %s",
                                   attempt + 1, self.ctx.max_retries, delay, redact(str(exc)))
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise ConnectivityError(f"SAP host unreachable: {redact(str(exc))}") from exc

            if resp.status_code in _RETRYABLE_STATUS and attempt < self.ctx.max_retries:
                delay = self._backoff(attempt, resp.headers.get("retry-after"))
                logger.warning("SAP returned HTTP %s (attempt %s/%s), retrying in %.2fs",
                               resp.status_code, attempt + 1, self.ctx.max_retries, delay)
                time.sleep(delay)
                attempt += 1
                continue

            self._check_redirect(resp, full)
            if resp.status_code >= 400:
                raise self._classify(resp, full)
            return resp

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.ctx.backoff_max)
            except ValueError:
                pass
        base = min(self.ctx.backoff_base * (2 ** attempt), self.ctx.backoff_max)
        return base + random.uniform(0, base * 0.25)  # full-ish jitter

    # -- typed helpers -------------------------------------------------------

    def get_json(self, url: str, *, params: dict | None = None) -> dict:
        resp = self.get(url, params=params, accept="application/json")
        data = self._read_capped(resp)
        try:
            import json as _json
            return _json.loads(data.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ConnectorError(f"SAP returned non-JSON payload: {redact(str(exc))}",
                                 category="protocol_error") from exc

    def get_text(self, url: str, *, params: dict | None = None) -> str:
        resp = self.get(url, params=params, accept="application/xml")
        data = self._read_capped(resp)
        return data.decode("utf-8", errors="replace")

    def fetch_collection(self, url: str, *, params: dict, version: str,
                         max_records: int, page_size: int,
                         deadline_seconds: float) -> tuple[list[dict], bool, int | None]:
        """Bounded incremental pagination.

        Returns (rows, truncated, total_count). Follows continuation URLs ONLY
        after same-origin + allowlist validation. Stops on max_records, page
        cap, or deadline — and says so honestly via `truncated`.
        """
        rows: list[dict] = []
        total: int | None = None
        deadline = time.monotonic() + deadline_seconds
        max_pages = min((max_records + page_size - 1) // max(1, page_size) + 1, _MAX_PAGES_HARD_CAP)
        current = url
        current_params: dict | None = dict(params)

        for _page in range(max_pages):
            if time.monotonic() >= deadline:
                return rows, True, total
            payload = self.get_json(current, params=current_params)
            page_rows, next_link, count = parse_page(payload, version)
            if count is not None:
                total = count
            for r in page_rows:
                rows.append(strip_odata_annotations(r))
            if len(rows) >= max_records:
                return rows[:max_records], bool(next_link) or len(rows) > max_records, total
            if not next_link:
                return rows, False, total
            try:
                current = validate_continuation_url(next_link, url, self.ctx.allowed_hosts)
            except UnsafeURLError as exc:
                raise ConfigurationError(
                    f"Refusing untrusted continuation URL: {redact(str(exc))}") from exc
            current_params = None  # continuation URL carries its own query
        return rows, True, total
