"""SAP S/4HANA read-only connector adapter.

Implements the connector-neutral SourceConnector interface on top of real
OData protocol machinery: $metadata discovery, service documents, structured
request plans (validated by the policy layer), and bounded paginated fetches.

LIFECYCLE NOTE: this adapter performs live calls; discovery results are
returned as typed metadata the caller (endpoints/service) caches into
Connection.metadata_json. Nothing here fabricates data: if a service or
entity is unavailable or unauthorized, we raise a classified, redacted error.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.services.connectors.base import (
    ConfigurationError,
    ConnectorError,
    ConnectorContext,
    EntityMeta,
    ExecutionResult,
    SchemaDescriptor,
    ServiceInfo,
    SourceConnector,
)
from app.services.connectors.sap_s4hana.auth import AuthHandler, redact
from app.services.connectors.sap_s4hana.client import ODataClient
from app.services.connectors.sap_s4hana.metadata import (
    descriptor_to_dict,
    parse_edmx,
    parse_service_document,
)
from app.services.connectors.sap_s4hana.odata import build_query_params, render_filter_plan
from app.services.connectors.sap_s4hana.policy import validate_plan

logger = logging.getLogger(__name__)


class SAPS4hanaConnector(SourceConnector):
    def __init__(self, context: ConnectorContext):
        super().__init__(context)
        if not context.base_url:
            raise ConfigurationError("SAP connection requires a base_url")
        try:
            self._auth = AuthHandler(
                auth_mode=context.auth_mode,
                username=context.username,
                secret=context.secret,
                client_id=context.client_id,
                scope=context.scope,
                token_url=context.token_url,
                tls_verify=context.tls_verify,
            )
        except ValueError as exc:
            raise ConfigurationError(redact(str(exc))) from exc
        self._client = ODataClient(context, self._auth)
        self._entity_cache: dict[str, EntityMeta] = {}
        self._services_cache: list[ServiceInfo] = []
        self._source_version = ""

    # -- helpers -------------------------------------------------------------

    @property
    def service_url(self) -> str:
        base = self.ctx.base_url.rstrip("/")
        path = (self.ctx.service_path or "").strip("/")
        return f"{base}/{path}" if path else base

    @property
    def odata_version(self) -> str:
        return "2" if self.ctx.odata_version == "2" else "4"

    def _metadata_url(self) -> str:
        return self.service_url.rstrip("/") + "/$metadata"

    def hydrate_from_cache(self, metadata_json: dict | None) -> bool:
        """Load previously discovered metadata (from Connection.metadata_json)
        so schema reads work without re-hitting SAP. Returns success."""
        if not metadata_json or "entities" not in metadata_json:
            return False
        try:
            services, entities, version, _notes = _descriptor_from_cache(metadata_json)
            self._services_cache = services
            self._entity_cache = {e.name: e for e in entities}
            self._source_version = version
            return True
        except Exception as exc:  # corrupted cache — force rediscovery
            logger.warning("SAP metadata cache unusable, will rediscover: %s", redact(str(exc)))
            return False

    # -- SourceConnector interface -------------------------------------------

    def test_connection(self) -> dict:
        """Reachability + auth probe against the service document (cheap GET)."""
        started = time.monotonic()
        try:
            payload = self._client.get_json(self.service_url)
            services = parse_service_document(payload, self.service_url)
            elapsed = round((time.monotonic() - started) * 1000, 1)
            return {
                "success": True,
                "message": f"SAP OData service reachable; {len(services)} entity set(s) advertised",
                "entity_sets": len(services),
                "latency_ms": elapsed,
                "auth": self._auth.describe(),
            }
        except ConnectorError as exc:
            return {"success": False, "message": exc.message, "error_category": exc.category,
                    "auth": self._auth.describe()}

    def discover_services(self) -> list[ServiceInfo]:
        payload = self._client.get_json(self.service_url)
        services = parse_service_document(payload, self.service_url)
        self._services_cache = services
        return services

    def discover_schema(self, force_refresh: bool = False) -> SchemaDescriptor:
        if self._entity_cache and not force_refresh:
            entities = list(self._entity_cache.values())
        else:
            xml = self._client.get_text(self._metadata_url())
            parsed = parse_edmx(xml)
            entities = parsed["entities"]
            self._entity_cache = {e.name: e for e in entities}
            self._source_version = parsed["source_version"]
            if parsed["odata_version"] != self.odata_version:
                parsed["notes"].append(
                    f"Service advertises OData v{parsed['odata_version']} but connection is configured v{self.odata_version}"
                )
            self._services_cache = self._services_cache or []
        services = self._services_cache
        if not services:
            try:
                services = self.discover_services()
            except ConnectorError as exc:
                services = []
                logger.info("Service document unavailable; continuing with metadata only: %s", exc.message)
        discovered_at = datetime.now(timezone.utc).isoformat()
        notes = []
        if self._source_version:
            notes.append(f"Metadata parsed from live $metadata ({self._source_version})")
        descriptor = SchemaDescriptor(
            connection_id=self.ctx.connection_id,
            services=services,
            entities=entities,
            discovered_at=discovered_at,
            source_version=self._source_version,
            notes=notes,
        )
        return descriptor

    def list_entities(self) -> list[EntityMeta]:
        if not self._entity_cache:
            self.discover_schema()
        return list(self._entity_cache.values())

    def get_entity_metadata(self, entity: str) -> EntityMeta:
        if not self._entity_cache:
            self.discover_schema()
        meta = self._entity_cache.get(entity)
        if meta is None:
            raise ConnectorError(
                f"SAP entity '{entity}' is not present in discovered metadata",
                category="not_found",
            )
        return meta

    def fetch_records(self, entity: str, *, select: list[str],
                      filter_plan: dict | None = None, orderby: str | None = None,
                      top: int | None = None, role: str = "executive") -> ExecutionResult:
        """Policy-validated, bounded, paginated read → normalized ExecutionResult."""
        started = time.monotonic()
        meta = self.get_entity_metadata(entity)
        plan = validate_plan(
            meta,
            {"entity": entity, "select": select, "filter": filter_plan,
             "orderby": orderby, "top": top},
            role,
            max_records=self.ctx.max_records,
        )
        filter_str = render_filter_plan(plan["filter"], meta, self.odata_version)
        params = build_query_params(
            select=plan["select"], filter_str=filter_str, orderby=plan["orderby"],
            top=min(plan["top"], self.ctx.page_size) if self.odata_version == "2" else plan["top"],
            version=self.odata_version,
        )
        if self.odata_version == "2":
            params["$inlinecount"] = "pagesize"
        entity_url = self.service_url.rstrip("/") + "/" + entity

        rows, truncated, total = self._client.fetch_collection(
            entity_url, params=params, version=self.odata_version,
            max_records=plan["top"], page_size=self.ctx.page_size,
            deadline_seconds=self.ctx.timeout_seconds,
        )
        columns = plan["select"] or (list(rows[0].keys()) if rows else [])
        # Re-order every row onto the selected column set
        normalized = [{c: r.get(c) for c in columns} for r in rows]
        elapsed = round((time.monotonic() - started) * 1000, 1)
        result = ExecutionResult(
            success=True,
            columns=columns,
            rows=normalized,
            row_count=len(normalized),
            truncated=truncated,
            execution_time_ms=elapsed,
        )
        return result

    def get_health_status(self) -> dict:
        status = self.test_connection()
        return {
            "connector": "sap_s4hana",
            "deployment": self.ctx.deployment_type,
            "odata_version": self.odata_version,
            "healthy": bool(status.get("success")),
            "last_check_message": status.get("message"),
            "error_category": status.get("error_category"),
            "entities_cached": len(self._entity_cache),
            "auth": self._auth.describe(),
        }

    # -- serialization for the DB cache --------------------------------------

    def serialize_descriptor(self, descriptor: SchemaDescriptor) -> dict:
        return descriptor_to_dict(
            descriptor.services, descriptor.entities,
            descriptor.source_version, descriptor.notes,
        )


def _descriptor_from_cache(data: dict):
    from app.services.connectors.sap_s4hana.metadata import descriptor_from_dict
    return descriptor_from_dict(data)


# Self-registration with the connector registry.
from app.services.connectors.registry import register_connector_factory  # noqa: E402

register_connector_factory("sap_s4hana", SAPS4hanaConnector)
