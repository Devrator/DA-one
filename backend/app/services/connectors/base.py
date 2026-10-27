"""Connector-neutral execution abstractions.

QueryPilot already has a SQL-specific `QueryExecutor`. The SAP spec requires a
connector-neutral execution layer that DISPATCHES to the correct connector,
enforces per-user authorization, applies timeouts/size limits, normalizes results
into a common structure, and returns lineage — WITHOUT making SAP pretend to be
PostgreSQL and WITHOUT breaking the existing SQL path.

So: `ExecutionResult` (from query_executor) is reused as the single normalized
result contract for BOTH SQL and non-SQL sources. That keeps the cross-source
join engine and every existing consumer working unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

# Reuse the existing normalized result structure as the common contract.
from app.services.query_executor import ExecutionResult  # noqa: F401


class ConnectorError(Exception):
    category = "connector_error"

    def __init__(self, message: str, *, category: Optional[str] = None):
        super().__init__(message)
        self.message = message
        if category:
            self.category = category


class ConfigurationError(ConnectorError):
    category = "configuration_error"


class ConnectivityError(ConnectorError):
    category = "connection_error"


class AuthenticationError(ConnectorError):
    category = "authentication_error"


class AuthorizationError(ConnectorError):
    category = "permission_denied"


class PolicyError(ConnectorError):
    category = "policy_violation"


# ---------------------------------------------------------------------------
# Normalized metadata representation (NOT pretending to be relational)
# ---------------------------------------------------------------------------

@dataclass
class ServiceInfo:
    id: str
    name: str
    url: str
    odata_version: str = "4"


@dataclass
class PropertyMeta:
    name: str
    odata_type: str                     # e.g. Edm.String, Edm.Decimal
    json_type: str = "string"           # normalized: string|number|boolean|date|datetime|guid
    nullable: bool = True
    readonly: bool = False
    is_key: bool = False
    max_length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    description: Optional[str] = None


@dataclass
class EntityMeta:
    name: str                           # entity set name (addressable)
    entity_type: str = ""
    keys: list[str] = field(default_factory=list)
    properties: list[PropertyMeta] = field(default_factory=list)
    navigation: list[str] = field(default_factory=list)
    count: Optional[int] = None
    declared: bool = True               # explicitly declared in metadata (not inferred)

    def property(self, name: str) -> Optional[PropertyMeta]:
        for p in self.properties:
            if p.name == name:
                return p
        return None


@dataclass
class SchemaDescriptor:
    connection_id: str
    services: list[ServiceInfo] = field(default_factory=list)
    entities: list[EntityMeta] = field(default_factory=list)
    discovered_at: str = ""
    source_version: str = ""
    notes: list[str] = field(default_factory=list)

    def entity(self, name: str) -> Optional[EntityMeta]:
        for e in self.entities:
            if e.name == name:
                return e
        return None


@dataclass
class ConnectorContext:
    """Everything needed to drive one connector, with the secret decrypted only
    transiently here (never returned by any endpoint or logged)."""
    connection_id: str
    name: str
    deployment_type: str
    base_url: str
    service_path: str
    odata_version: str
    auth_mode: str
    username: str
    secret: str                          # transient, decrypted
    client_id: Optional[str] = None
    scope: Optional[str] = None
    token_url: Optional[str] = None
    tls_verify: bool = True
    allowed_hosts: list[str] = field(default_factory=list)
    timeout_seconds: float = 20.0
    max_records: int = 5000
    page_size: int = 500
    max_response_bytes: int = 8_000_000
    max_retries: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 20.0


class SourceConnector(ABC):
    """Consistent read-only interface every connector must expose."""

    def __init__(self, context: ConnectorContext):
        self.ctx = context

    @abstractmethod
    def test_connection(self) -> dict: ...

    @abstractmethod
    def discover_services(self) -> list[ServiceInfo]: ...

    @abstractmethod
    def discover_schema(self, force_refresh: bool = False) -> SchemaDescriptor: ...

    @abstractmethod
    def list_entities(self) -> list[EntityMeta]: ...

    @abstractmethod
    def get_entity_metadata(self, entity: str) -> EntityMeta: ...

    @abstractmethod
    def fetch_records(self, entity: str, *, select: list[str],
                      filter_plan: Optional[dict] = None, orderby: Optional[str] = None,
                      top: Optional[int] = None, role: str = "executive") -> "ExecutionResult": ...

    @abstractmethod
    def get_health_status(self) -> dict: ...

    def validate_filters(self, entity: str, filter_plan: dict) -> dict:
        """Default: delegate to the concrete policy in fetch; overridable."""
        return {"valid": True}

    def get_pagination_metadata(self, entity: str, top: int) -> dict:
        page = min(max(1, self.ctx.page_size), max(1, top))
        return {"page_size": page, "max_records": self.ctx.max_records}
