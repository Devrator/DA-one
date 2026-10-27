"""Connector abstraction layer: registry + execution-provider dispatch.

The existing `QueryExecutor` (SQL path) stays exactly as-is for PostgreSQL
sources. This registry adds a connector-neutral dispatch for non-SQL sources
(SAP S/4HANA) that reuses the same `ExecutionResult` contract, the same
server-side role authorization, and the same Connection registry — no second
query engine, no duplicate registry, no parallel authz.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.config import get_settings
from app.models import Connection
from app.services.connectors.base import ConnectorContext, SourceConnector
from app.services.connectors.net_security import parse_allowed_hosts
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

# connector_type -> factory(ConnectorContext) -> SourceConnector
_FACTORIES: dict[str, Callable[[ConnectorContext], SourceConnector]] = {}


def register_connector_factory(connector_type: str, factory: Callable[[ConnectorContext], SourceConnector]):
    """Idempotent factory registration used by connector packages."""
    _FACTORIES[connector_type] = factory


def available_connector_types() -> list[str]:
    return sorted(_FACTORIES.keys())


def build_context(conn: Connection) -> ConnectorContext:
    """Turn a persisted Connection row into a transient ConnectorContext.

    The secret is decrypted ONLY here and lives only inside the context —
    endpoints never return it and logs never carry it.
    """
    settings = get_settings()
    timeout = min(settings.sap_default_timeout_seconds, settings.sap_max_timeout_seconds)
    # Non-secret connection options live in metadata_json["options"] — never
    # store tokens/secrets here; the secret comes only from encrypted_password.
    options = {}
    if isinstance(getattr(conn, "metadata_json", None), dict):
        opts = conn.metadata_json.get("options")
        if isinstance(opts, dict):
            options = opts
    return ConnectorContext(
        connection_id=conn.id,
        name=conn.name,
        deployment_type=conn.deployment_type or "public_cloud",
        base_url=(conn.base_url or "").rstrip("/"),
        service_path=conn.service_path or "",
        odata_version=conn.odata_version or "4",
        auth_mode=conn.auth_mode or "basic",
        username=conn.username or "",
        secret=decrypt_secret(conn.encrypted_password),
        client_id=options.get("oauth_client_id"),
        scope=options.get("oauth_scope"),
        token_url=options.get("oauth_token_url"),
        tls_verify=True if conn.tls_verify is None else bool(conn.tls_verify),
        allowed_hosts=parse_allowed_hosts(settings.sap_allowed_hosts),
        timeout_seconds=timeout,
        max_records=settings.sap_max_records_fetched,
        page_size=settings.sap_default_page_size,
        max_response_bytes=settings.sap_max_response_bytes,
        max_retries=settings.sap_max_retries,
        backoff_base=settings.sap_backoff_base_seconds,
        backoff_max=settings.sap_backoff_max_seconds,
    )


def build_connector(conn: Connection) -> SourceConnector:
    """Instantiate the right connector for a Connection row.

    Raises ConfigurationError if the connector type is unknown or SAP
    integration is disabled.
    """
    from app.services.connectors.base import ConfigurationError

    connector_type = getattr(conn, "connector_type", None) or "postgresql"
    if connector_type == "postgresql":
        raise ConfigurationError(
            "PostgreSQL sources execute through QueryExecutor directly; "
            "they are not connector-provider sources."
        )
    settings = get_settings()
    if connector_type == "sap_s4hana" and not settings.sap_enabled:
        raise ConfigurationError("SAP connector is disabled (SAP_ENABLED=false).")

    _ensure_builtin_registrations()
    factory = _FACTORIES.get(connector_type)
    if not factory:
        raise ConfigurationError(f"No connector registered for type '{connector_type}'.")
    return factory(build_context(conn))


_REGISTRATION_DONE = False


def _ensure_builtin_registrations():
    """Lazily import built-in connector packages so they self-register."""
    global _REGISTRATION_DONE
    if _REGISTRATION_DONE:
        return
    try:
        import app.services.connectors.sap_s4hana.adapter  # noqa: F401
    except ImportError as exc:  # pragma: no cover - packaging guard
        logger.warning("SAP connector package not importable: %s", exc)
    _REGISTRATION_DONE = True


def connector_for_context(context: ConnectorContext) -> Optional[SourceConnector]:
    """Test helper / direct access: build a connector from a raw context."""
    _ensure_builtin_registrations()
    from app.services.connectors.sap_s4hana.adapter import SAPS4hanaConnector

    return SAPS4hanaConnector(context)
