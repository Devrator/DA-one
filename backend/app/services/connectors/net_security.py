"""URL safety for the SAP connector: SSRF protection + host allowlisting.

The spec requires that the connector only ever reaches administrator-approved
SAP hosts, never cloud-metadata / arbitrary internal services, and that it
VALIDATES every URL it is about to fetch — including server-supplied OData
pagination `@odata.nextLink` / `__next` continuation URLs — so a malicious SAP
response cannot redirect QueryPilot to an unapproved destination.

Everything here is pure and dependency-free so it can be unit-tested directly.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

# Endpoints that must NEVER be reachable, even if an admin tries to allowlist them.
_HARD_BLOCKED_HOSTS = {
    "169.254.169.254",       # AWS/GCP/OpenStack metadata
    "metadata.google",       # GCP metadata (name form)
    "metadata.goog",
    "100.100.100.200",       # Alibaba Cloud metadata
    "fd00:ec2::254",         # IPv6 metadata
}

_ALLOWED_SCHEMES = {"https", "http"}


class UnsafeURLError(ValueError):
    """Raised when a URL fails SSRF / allowlist validation."""


def parse_allowed_hosts(raw: str) -> list[str]:
    """Parse a comma-separated allowlist into normalized lowercase entries."""
    return [h.strip().lower() for h in (raw or "").split(",") if h.strip()]


def is_hard_blocked_host(host: str) -> bool:
    h = host.lower().strip().rstrip(".")
    return h in _HARD_BLOCKED_HOSTS


def host_is_allowed(host: str, allowed_hosts: list[str]) -> bool:
    """Exact match or a `*.suffix` wildcard match (case-insensitive)."""
    h = host.lower().strip().rstrip(".")
    for pattern in allowed_hosts:
        p = pattern.lower().strip()
        if not p:
            continue
        if p.startswith("*."):
            suffix = p[2:]
            if h == suffix or h.endswith("." + suffix):
                return True
        elif h == p:
            return True
    return False


def _is_internal_ip(host: str) -> bool:
    """True for loopback / private / link-local / metadata-ish IPv4/IPv6 literals."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP literal
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def validate_url(
    url: str,
    allowed_hosts: list[str],
    *,
    allow_localhost: bool = False,
) -> str:
    """Return a canonical URL, or raise UnsafeURLError.

    Rules:
    - scheme must be http/https (SAP over TLS in production; http only for the
      local protocol-fixture tests when allow_localhost is set).
    - host must not be a hard-blocked metadata endpoint.
    - a raw internal/private IP literal is refused UNLESS the host is explicitly
      allowlisted (a private SAP reachable over VPN is legitimate once approved)
      or allow_localhost is set for loopback test hosts.
    - otherwise the host must appear in the administrator allowlist
      (fail-closed: an empty allowlist rejects every external host).
    """
    if not url:
        raise UnsafeURLError("Empty URL")
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Unsupported scheme: {scheme or '(none)'}")
    host = (parts.hostname or "").lower().strip().rstrip(".")
    if not host:
        raise UnsafeURLError("URL has no host")

    if is_hard_blocked_host(host):
        raise UnsafeURLError("Target host is a protected metadata endpoint")

    localhost = host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")

    if host_is_allowed(host, allowed_hosts):
        return _canonical(parts)

    # Fail-closed for internal IPs and anything not explicitly approved.
    if _is_internal_ip(host):
        if allow_localhost and localhost:
            return _canonical(parts)
        raise UnsafeURLError(f"Refusing to reach internal address '{host}' (not allowlisted)")

    if allow_localhost and localhost:
        return _canonical(parts)

    raise UnsafeURLError(f"Host '{host}' is not in the approved SAP allowlist")


def _canonical(parts) -> str:
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def validate_continuation_url(
    next_link: str,
    service_url: str,
    allowed_hosts: list[str],
    *,
    allow_localhost: bool = False,
) -> str:
    """Validate a pagination continuation URL before following it.

    The continuation MUST be same-origin (scheme + host + port) as the approved
    service URL and independently pass allowlist validation. This stops a hostile
    SAP payload from pivoting the connector to an unapproved host.
    """
    if not next_link:
        raise UnsafeURLError("Empty continuation URL")
    base = urlsplit(service_url)
    nxt = urlsplit(next_link)
    base_netloc = (base.netloc or "").lower()
    nxt_netloc = (nxt.netloc or "").lower()
    if nxt_netloc != base_netloc:
        raise UnsafeURLError(
            f"Continuation URL host '{nxt_netloc}' does not match the approved service host"
        )
    return validate_url(next_link, allowed_hosts, allow_localhost=allow_localhost)


def extract_location(headers: dict) -> str | None:
    """Pull a redirect Location header (case-insensitive) if present."""
    for k, v in (headers or {}).items():
        if k.lower() == "location":
            return v
    return None
