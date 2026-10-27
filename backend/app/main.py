"""FastAPI main application.

Central entry point for the QueryPilot AI backend.
Configures middleware, routes, startup/shutdown, and error handling.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, HTTPException, Depends, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings, Settings
from app.database import (
    get_app_engine, get_app_db, init_app_db,
    get_default_target_engine, check_db_health, create_target_engine,
)
from app.models import (
    Connection, QueryRecord, EvaluationRun, EvaluationResult,
    AuditEvent, BusinessGlossary, ConversationSession,
    DiscoveryRun, DiscoveryFinding,
    Investigation, InvestigationBranch, RootCauseRun, Scenario, new_uuid,
    Briefing, BriefingPreference, CrossSourceMapping,
)
from app.schemas import (
    HealthResponse, ReadinessResponse,
    ConnectionCreate, ConnectionTest, ConnectionResponse, ConnectionTestResult,
    QueryRequest, QueryStatus, QueryFeedback,
    QueryHistoryItem, QueryHistoryResponse,
    SchemaResponse, TableInfo,
    EvaluationRunCreate, EvaluationRunResponse, EvaluationRunDetailResponse, EvaluationResultResponse,
    AuditEventResponse, ErrorResponse,
    TargetDbSettingsUpdate, LlmSettingsUpdate, SettingsApplyResult,
    SAPConnectionPayload, SAPConnectionCreate, SAPConnectionPatch, SAPPreviewRequest,
)
from app.services.llm_provider import LLMProvider
from app.services.schema_service import SchemaService
from app.services.sql_generator import SQLGenerator
from app.services.sql_safety import SQLPolicyEngine
from app.services.query_executor import QueryExecutor, ExecutionResult
from app.services.chart_service import select_chart_type
from app.services.explanation_service import ExplanationService
from app.services.role_service import resolve_user_context, UserSecurityContext
from app.services.crypto import encrypt_secret, decrypt_secret, reencrypt_if_needed
from app.services.connectors.base import ConnectorContext, ConnectorError
from app.services.connectors.net_security import UnsafeURLError, parse_allowed_hosts, validate_url
from app.services.connectors.registry import build_connector
from app.services.validation_service import (
    SchemaGroundingValidator, GroundingResult, build_evidence,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("querypilot")


# ---------------------------------------------------------------------------
# Singletons (initialized at startup)
# ---------------------------------------------------------------------------

_llm: Optional[LLMProvider] = None
_schema_service: Optional[SchemaService] = None
_sql_policy: Optional[SQLPolicyEngine] = None
_sql_generator: Optional[SQLGenerator] = None
_query_executor: Optional[QueryExecutor] = None
_explanation_service: Optional[ExplanationService] = None
_target_engine = None
_active_schema_name: str = "sales"


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = LLMProvider.from_settings()
    return _llm


def get_schema_service() -> SchemaService:
    global _schema_service
    if _schema_service is None:
        _schema_service = SchemaService()
    return _schema_service


def get_sql_policy() -> SQLPolicyEngine:
    global _sql_policy
    if _sql_policy is None:
        _sql_policy = SQLPolicyEngine.from_settings()
    return _sql_policy


def get_sql_generator() -> SQLGenerator:
    global _sql_generator
    if _sql_generator is None:
        _sql_generator = SQLGenerator(llm=get_llm(), policy_engine=get_sql_policy())
    return _sql_generator


def get_query_executor() -> QueryExecutor:
    global _query_executor
    if _query_executor is None:
        _query_executor = QueryExecutor.from_settings()
    return _query_executor


def get_explanation_service() -> ExplanationService:
    global _explanation_service
    if _explanation_service is None:
        _explanation_service = ExplanationService(llm=get_llm())
    return _explanation_service


def get_target_engine():
    global _target_engine
    if _target_engine is None:
        _target_engine = get_default_target_engine()
    return _target_engine


def _ensure_startup_migrations():
    """Additively migrate app DB columns created after initial deployment."""
    from sqlalchemy import inspect as sa_inspect
    engine = get_app_engine()
    insp = sa_inspect(engine)
    if "query_records" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("query_records")}
        if "evidence" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE query_records ADD COLUMN IF NOT EXISTS evidence JSON"
                ))
            logger.info("Migrated: added query_records.evidence column")

    # SAP connector + credential-encryption columns on an existing connections table.
    if "connections" in insp.get_table_names():
        conn_cols = {c["name"] for c in insp.get_columns("connections")}
        additive = {
            "connector_type": "VARCHAR(30) NOT NULL DEFAULT 'postgresql'",
            "deployment_type": "VARCHAR(30)",
            "base_url": "VARCHAR(500)",
            "service_path": "VARCHAR(500)",
            "odata_version": "VARCHAR(5)",
            "auth_mode": "VARCHAR(30)",
            "secret_ref": "VARCHAR(300)",
            "tls_verify": "BOOLEAN DEFAULT TRUE",
            "lifecycle_status": "VARCHAR(20) DEFAULT 'configured'",
            "last_success_at": "TIMESTAMP WITH TIME ZONE",
            "metadata_json": "JSON",
            "metadata_refreshed_at": "TIMESTAMP WITH TIME ZONE",
            "updated_by": "VARCHAR(200)",
        }
        with engine.begin() as conn:
            for col, ddl in additive.items():
                if col not in conn_cols:
                    conn.execute(text(f"ALTER TABLE connections ADD COLUMN IF NOT EXISTS {col} {ddl}"))
                    logger.info("Migrated: added connections.%s column", col)
        # Upgrade any legacy plaintext credentials to encrypted-at-rest form.
        _upgrade_legacy_credentials()


def _upgrade_legacy_credentials():
    """Re-encrypt connection passwords that are still stored as plaintext."""
    from app.database import get_app_session_factory
    factory = get_app_session_factory()
    db = factory()
    try:
        upgraded = 0
        for c in db.query(Connection).all():
            new_val = reencrypt_if_needed(c.encrypted_password)
            if new_val != c.encrypted_password:
                c.encrypted_password = new_val
                upgraded += 1
        if upgraded:
            db.commit()
            logger.info("Credential migration: encrypted %d connection secret(s)", upgraded)
    except Exception as exc:  # pragma: no cover - defensive at startup
        db.rollback()
        logger.warning("Credential upgrade skipped: %s", exc)
    finally:
        db.close()


def _ensure_secondary_source():
    """Register the bootstrap second PostgreSQL source so the two-source
    cross-system demo works out of the box. Admins can manage additional sources
    through the Connections registry; this is idempotent and failure-tolerant.
    """
    settings = get_settings()
    if not (settings.cross_source_enabled and settings.cross_source_secondary_enabled):
        return
    from app.database import get_app_session_factory
    factory = get_app_session_factory()
    db = factory()
    try:
        existing = db.query(Connection).filter(
            Connection.database_name == settings.cross_source_secondary_db,
            Connection.schema_name == settings.cross_source_secondary_schema,
            Connection.is_active == True,  # noqa: E712
        ).first()
        if existing:
            return
        conn = Connection(
            name=settings.cross_source_secondary_name,
            db_type="postgresql",
            host=settings.cross_source_secondary_host,
            port=settings.cross_source_secondary_port,
            database_name=settings.cross_source_secondary_db,
            username=settings.cross_source_secondary_user,
            encrypted_password=encrypt_secret(settings.cross_source_secondary_password),  # encrypted at rest
            schema_name=settings.cross_source_secondary_schema,
            owner_user="system",
        )
        db.add(conn)
        db.commit()
        logger.info("Registered secondary cross-source: %s", conn.name)
    except Exception as exc:  # pragma: no cover - defensive at startup
        db.rollback()
        logger.warning("Secondary source bootstrap skipped: %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    settings = get_settings()
    logger.info("Starting %s [env=%s]", settings.app_name, settings.app_env)

    # Initialize application database tables
    try:
        init_app_db()
        _ensure_startup_migrations()
        logger.info("Application database initialized")
    except Exception as e:
        logger.error("Failed to initialize app database: %s", e)

    # Start proactive discovery scheduler (Discover & Early Warnings)
    _start_discovery_scheduler()

    # Start personalized briefing scheduler (Feature 4)
    _start_briefing_scheduler()

    # Register the bootstrap second data source (Feature 5 Cross-System Intelligence)
    try:
        _ensure_secondary_source()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Cross-source bootstrap failed: %s", e)

    yield

    # Cleanup
    logger.info("Shutting down %s", settings.app_name)
    if _llm:
        _llm.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Intelligent analytics workspace — natural language to SQL",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Correlation ID middleware
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(
        "%s %s %d %.1fms [%s]",
        request.method, request.url.path, response.status_code, elapsed, correlation_id[:8],
    )
    return response


# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": None},
    )


# ============================================================================
# HEALTH ENDPOINTS
# ============================================================================

@app.get("/api/v1/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Liveness check."""
    s = get_settings()
    return HealthResponse(status="ok", app_name=s.app_name, environment=s.app_env)


@app.get("/api/v1/readiness", response_model=ReadinessResponse, tags=["Health"])
async def readiness():
    """Readiness check — verifies database and model availability."""
    db_health = check_db_health(get_app_engine())
    llm_health = get_llm().check_health()
    overall = "ready" if db_health["status"] == "healthy" and llm_health["status"] == "healthy" else "not_ready"
    return ReadinessResponse(status=overall, database=db_health, inference=llm_health)


# ============================================================================
# CONNECTION ENDPOINTS
# ============================================================================

@app.post("/api/v1/connections/test", response_model=ConnectionTestResult, tags=["Connections"])
async def test_connection(req: ConnectionTest):
    """Test database connectivity without persisting the connection."""
    try:
        engine = create_target_engine(
            host=req.host,
            port=req.port,
            dbname=req.database_name,
            user=req.username,
            password=req.password,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # Count tables
            result = conn.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema"
            ), {"schema": req.schema_name})
            table_count = result.scalar() or 0
        engine.dispose()
        return ConnectionTestResult(success=True, message="Connection successful", tables_found=table_count)
    except Exception as e:
        return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)[:200]}")


@app.post("/api/v1/connections", response_model=ConnectionResponse, tags=["Connections"])
async def create_connection(req: ConnectionCreate, db: Session = Depends(get_app_db)):
    """Register a new database connection."""
    conn = Connection(
        name=req.name,
        db_type=req.db_type,
        host=req.host,
        port=req.port,
        database_name=req.database_name,
        username=req.username,
        encrypted_password=encrypt_secret(req.password),  # encrypted at rest (Fernet envelope)
        schema_name=req.schema_name,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    # Audit
    _audit(db, "connection.created", "connection", conn.id, {"name": req.name})

    return ConnectionResponse.model_validate(conn)


@app.get("/api/v1/connections", response_model=list[ConnectionResponse], tags=["Connections"])
async def list_connections(db: Session = Depends(get_app_db)):
    """List all registered connections."""
    conns = db.query(Connection).filter(Connection.is_active == True).all()
    return [ConnectionResponse.model_validate(c) for c in conns]


@app.delete("/api/v1/connections/{conn_id}", tags=["Connections"])
async def delete_connection(conn_id: str, db: Session = Depends(get_app_db)):
    """Soft-delete a connection."""
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.is_active = False
    db.commit()
    _audit(db, "connection.deleted", "connection", conn_id, {})
    return {"status": "deleted"}


@app.get("/api/v1/connections/{conn_id}/schema", response_model=SchemaResponse, tags=["Connections"])
async def get_connection_schema(conn_id: str, db: Session = Depends(get_app_db)):
    """Retrieve the schema for a connection."""
    conn = db.query(Connection).filter(Connection.id == conn_id, Connection.is_active == True).first()

    if conn_id == "default":
        # Use the default target database
        engine = get_target_engine()
        schema_name = "sales"
    elif conn:
        if getattr(conn, "connector_type", "postgresql") == "sap_s4hana":
            # SAP rows expose their cached OData descriptor through the SAME
            # schema endpoint, so the Schema Catalog stays source-neutral.
            cached = conn.metadata_json or {}
            if "entities" not in cached:
                raise HTTPException(status_code=409, detail="Schema not discovered yet — use POST /schema/refresh")
            return JSONResponse({
                "connection_id": conn.id,
                "name": conn.name,
                "connector_type": "sap_s4hana",
                "schema_label": "sap",
                "source_version": cached.get("source_version", ""),
                "discovered_at": str(conn.metadata_refreshed_at or ""),
                "entity_count": len(cached.get("entities", [])),
                "entities": cached.get("entities", []),
                "notes": cached.get("notes", []),
            })
        engine = create_target_engine(
            host=conn.host,
            port=conn.port,
            dbname=conn.database_name,
            user=conn.username,
            password=decrypt_secret(conn.encrypted_password),
        )
        schema_name = conn.schema_name or "public"
    else:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_svc = get_schema_service()
    return schema_svc.discover_schema(engine, conn_id, schema_name)


# ============================================================================
# SAP S/4HANA CONNECTOR ENDPOINTS
# ============================================================================

_SAP_PREVIEW_WINDOW_SECONDS = 60.0
_SAP_PREVIEW_MAX_PER_WINDOW = 30
_sap_preview_hits: dict[str, list[float]] = {}


def _require_sap_admin(request: Request) -> UserSecurityContext:
    """Server-side authz for SAP connection management: executive/admin only.
    Frontend hiding is NOT a control — every admin endpoint checks here."""
    role_header = request.headers.get("X-User-Role")
    user_header = request.headers.get("X-Username")
    ctx = resolve_user_context(role_or_username=(user_header or role_header or "executive"),
                               explicit_role=role_header)
    if ctx.role != "executive":
        raise HTTPException(status_code=403, detail="Only administrators may manage SAP connections")
    return ctx


def _sap_settings_guard(base_url: str, service_path: str, token_url: Optional[str]) -> None:
    """Fail-closed allowlist validation at the API surface (belt + suspenders:
    the connector client re-validates every final URL including redirects)."""
    settings = get_settings()
    allowed = parse_allowed_hosts(settings.sap_allowed_hosts)
    joined = base_url.rstrip("/") + ("/" + service_path.strip("/") if service_path.strip("/") else "")
    try:
        validate_url(joined, allowed)
        if token_url:
            validate_url(token_url, allowed)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=f"SAP target not permitted: {exc}")


def _sap_error_status(exc: ConnectorError) -> int:
    return {
        "configuration_error": 400,
        "policy_violation": 403,
        "permission_denied": 403,
        "authentication_error": 502,
        "connection_error": 502,
        "not_found": 404,
        "size_limit": 413,
        "api_error": 502,
        "protocol_error": 502,
    }.get(exc.category, 500)


def _get_sap_connection(conn_id: str, db: Session) -> Connection:
    conn = db.query(Connection).filter(
        Connection.id == conn_id, Connection.is_active == True  # noqa: E712
    ).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    if getattr(conn, "connector_type", "postgresql") != "sap_s4hana":
        raise HTTPException(status_code=400, detail="Not a SAP S/4HANA connection")
    return conn


def _sap_context_from_payload(payload: SAPConnectionPayload, connection_id: str) -> ConnectorContext:
    settings = get_settings()
    return ConnectorContext(
        connection_id=connection_id,
        name=payload.secret_ref or connection_id,
        deployment_type=payload.deployment_type,
        base_url=payload.base_url.rstrip("/"),
        service_path=payload.service_path or "",
        odata_version=payload.odata_version,
        auth_mode=payload.auth_mode,
        username=payload.username or "",
        secret=payload.secret,
        client_id=payload.oauth_client_id,
        scope=payload.oauth_scope,
        token_url=payload.oauth_token_url,
        tls_verify=payload.tls_verify,
        allowed_hosts=parse_allowed_hosts(settings.sap_allowed_hosts),
        timeout_seconds=min(settings.sap_default_timeout_seconds, settings.sap_max_timeout_seconds),
        max_records=settings.sap_max_records_fetched,
        page_size=settings.sap_default_page_size,
        max_response_bytes=settings.sap_max_response_bytes,
        max_retries=settings.sap_max_retries,
        backoff_base=settings.sap_backoff_base_seconds,
        backoff_max=settings.sap_backoff_max_seconds,
    )


def _sap_adapter(ctx: ConnectorContext):
    from app.services.connectors.sap_s4hana.adapter import SAPS4hanaConnector
    return SAPS4hanaConnector(ctx)


def _rate_limit_preview(conn_id: str) -> None:
    now = time.time()
    hits = [t for t in _sap_preview_hits.get(conn_id, []) if now - t < _SAP_PREVIEW_WINDOW_SECONDS]
    if len(hits) >= _SAP_PREVIEW_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="SAP preview rate limit exceeded; try again shortly")
    hits.append(now)
    _sap_preview_hits[conn_id] = hits


@app.post("/api/v1/connections/sap/test", tags=["SAP Connector"])
async def sap_test_connection(req: SAPConnectionPayload, request: Request):
    """Ad-hoc connectivity + auth probe. Nothing is persisted; secrets are
    never echoed back."""
    _require_sap_admin(request)
    _sap_settings_guard(req.base_url, req.service_path, req.oauth_token_url)
    adapter = _sap_adapter(_sap_context_from_payload(req, "ad-hoc"))
    result = adapter.test_connection()
    return result


@app.post("/api/v1/connections/sap", response_model=ConnectionResponse, tags=["SAP Connector"])
async def create_sap_connection(req: SAPConnectionCreate, request: Request, db: Session = Depends(get_app_db)):
    """Register a SAP S/4HANA connection in the shared Connection registry."""
    user = _require_sap_admin(request)
    _sap_settings_guard(req.base_url, req.service_path, req.oauth_token_url)
    parts = urlsplit(req.base_url)
    conn = Connection(
        name=req.name,
        db_type="sap_odata",
        connector_type="sap_s4hana",
        host=(parts.hostname or "").lower(),
        port=parts.port or (443 if parts.scheme == "https" else 80),
        database_name=(req.service_path or "/")[:200],
        username=req.username or (req.oauth_client_id or ""),
        encrypted_password=encrypt_secret(req.secret),  # encrypted at rest
        schema_name="sap",
        deployment_type=req.deployment_type,
        base_url=req.base_url.rstrip("/"),
        service_path=req.service_path,
        odata_version=req.odata_version,
        auth_mode=req.auth_mode,
        secret_ref=req.secret_ref or "credential-store",
        tls_verify=req.tls_verify,
        lifecycle_status="configured",
        owner_user=user.username,
        updated_by=user.username,
        metadata_json={"options": {
            "oauth_client_id": req.oauth_client_id,
            "oauth_scope": req.oauth_scope,
            "oauth_token_url": req.oauth_token_url,
        }},
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    _audit(db, "connection.sap.created", "connection", conn.id,
           {"name": req.name, "deployment": req.deployment_type, "auth_mode": req.auth_mode,
            "odata_version": req.odata_version})
    return ConnectionResponse.model_validate(conn)


@app.get("/api/v1/connections/{conn_id}/health", tags=["SAP Connector"])
async def sap_health(conn_id: str, request: Request, db: Session = Depends(get_app_db)):
    """Live health probe; persists the resulting lifecycle state."""
    _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    try:
        connector = build_connector(conn)
        connector.hydrate_from_cache(conn.metadata_json)
        status = connector.get_health_status()
    except ConnectorError as exc:
        raise HTTPException(status_code=_sap_error_status(exc), detail=exc.message)
    conn.test_status = "ok" if status["healthy"] else "degraded"
    conn.lifecycle_status = "connected" if status["healthy"] else "degraded"
    if status["healthy"]:
        conn.last_success_at = datetime.now(timezone.utc)
    conn.last_tested_at = datetime.now(timezone.utc)
    db.commit()
    return status


@app.get("/api/v1/connections/{conn_id}/services", tags=["SAP Connector"])
async def sap_services(conn_id: str, request: Request, db: Session = Depends(get_app_db)):
    """Discovered OData services from the metadata cache."""
    _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    cached = conn.metadata_json or {}
    if "entities" not in cached:
        raise HTTPException(status_code=409, detail="Schema not discovered yet — use POST /schema/refresh")
    return {"services": cached.get("services", []), "refreshed_at": str(conn.metadata_refreshed_at or "")}


@app.post("/api/v1/connections/{conn_id}/schema/refresh", tags=["SAP Connector"])
async def sap_schema_refresh(conn_id: str, request: Request, db: Session = Depends(get_app_db)):
    """Admin-triggered live discovery: parse $metadata, cache it, and report
    changes versus the previous snapshot."""
    user = _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    try:
        connector = build_connector(conn)
        descriptor = connector.discover_schema(force_refresh=True)
    except ConnectorError as exc:
        conn.lifecycle_status = "degraded"
        db.commit()
        raise HTTPException(status_code=_sap_error_status(exc), detail=exc.message)

    from app.services.connectors.sap_s4hana.metadata import descriptor_to_dict
    payload = descriptor_to_dict(descriptor.services, descriptor.entities,
                                 descriptor.source_version, descriptor.notes)
    options = (conn.metadata_json or {}).get("options")
    payload["options"] = options or {}

    previous = conn.metadata_json or {}
    prev_names = {e.get("name") for e in previous.get("entities", [])}
    new_names = {e.name for e in descriptor.entities}
    changes = {
        "added": sorted(new_names - prev_names),
        "removed": sorted(prev_names - new_names),
        "unchanged": len(new_names & prev_names),
    }

    conn.metadata_json = payload
    conn.metadata_refreshed_at = datetime.now(timezone.utc)
    conn.lifecycle_status = "connected"
    conn.last_success_at = datetime.now(timezone.utc)
    conn.updated_by = user.username
    db.commit()
    _audit(db, "connection.sap.schema_refresh", "connection", conn.id,
           {"entities": len(new_names), "added": changes["added"], "removed": changes["removed"]})
    return {
        "connection_id": conn.id,
        "entity_count": len(new_names),
        "service_count": len(descriptor.services),
        "source_version": descriptor.source_version,
        "changes": changes,
        "refreshed_at": str(conn.metadata_refreshed_at),
    }


@app.get("/api/v1/connections/{conn_id}/entities", tags=["SAP Connector"])
async def sap_entities(conn_id: str, request: Request, db: Session = Depends(get_app_db)):
    """Entity summaries (name, keys, field count) from the cache."""
    _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    cached = conn.metadata_json or {}
    if "entities" not in cached:
        raise HTTPException(status_code=409, detail="Schema not discovered yet — use POST /schema/refresh")
    return {
        "entities": [
            {
                "name": e["name"],
                "entity_type": e.get("entity_type", ""),
                "keys": e.get("keys", []),
                "field_count": len(e.get("properties", [])),
                "navigation": e.get("navigation", []),
                "count": e.get("count"),
            } for e in cached["entities"]
        ]
    }


@app.get("/api/v1/connections/{conn_id}/entities/{entity}/metadata", tags=["SAP Connector"])
async def sap_entity_metadata(conn_id: str, entity: str, request: Request, db: Session = Depends(get_app_db)):
    """Full property table for one entity set (no live call, no secrets)."""
    _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    cached = conn.metadata_json or {}
    meta = next((e for e in cached.get("entities", []) if e.get("name") == entity), None)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity}' not in discovered SAP metadata")
    return meta


@app.post("/api/v1/connections/{conn_id}/entities/{entity}/preview", tags=["SAP Connector"])
async def sap_entity_preview(conn_id: str, entity: str, req: SAPPreviewRequest,
                             request: Request, db: Session = Depends(get_app_db)):
    """Bounded, role-authorized record preview. The structured plan is
    validated against metadata + role policy BEFORE any HTTP call."""
    role_header = request.headers.get("X-User-Role")
    user_header = request.headers.get("X-Username")
    user_ctx = resolve_user_context(role_or_username=(user_header or role_header or "executive"),
                                    explicit_role=role_header)
    conn = _get_sap_connection(conn_id, db)
    _rate_limit_preview(conn_id)
    try:
        connector = build_connector(conn)
        if not connector.hydrate_from_cache(conn.metadata_json):
            connector.discover_schema()
        result = connector.fetch_records(
            entity,
            select=req.select,
            filter_plan=req.filter,
            orderby=req.orderby,
            top=min(req.top or 50, get_settings().sap_max_records_fetched),
            role=user_ctx.role,
        )
    except ConnectorError as exc:
        _audit(db, "connection.sap.preview_blocked", "connection", conn.id,
               {"entity": entity, "role": user_ctx.role, "category": exc.category})
        raise HTTPException(status_code=_sap_error_status(exc), detail=exc.message)
    _audit(db, "connection.sap.preview", "connection", conn.id,
           {"entity": entity, "role": user_ctx.role, "rows": result.row_count,
            "truncated": result.truncated, "user": user_ctx.username})
    return {
        "success": result.success,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "execution_time_ms": result.execution_time_ms,
        "source": {"connection_id": conn.id, "name": conn.name, "entity": entity},
        "applied": {"select": req.select, "filter": req.filter, "orderby": req.orderby,
                    "role": user_ctx.role},
        "limitations": (
            "Preview shows a bounded, role-authorized subset retrieved from SAP — "
            "it is not the complete entity, and SAP-side authorizations of the "
            "integration identity were applied IN ADDITION to QueryPilot policy."
        ),
    }


@app.patch("/api/v1/connections/{conn_id}", response_model=ConnectionResponse, tags=["SAP Connector"])
async def patch_sap_connection(conn_id: str, req: SAPConnectionPatch, request: Request,
                               db: Session = Depends(get_app_db)):
    """Admin update of non-secret settings; `secret` rotates the credential."""
    user = _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    if req.secret:
        conn.encrypted_password = encrypt_secret(req.secret)
    if req.service_path is not None:
        conn.service_path = req.service_path
    if req.odata_version is not None:
        conn.odata_version = req.odata_version
    if req.auth_mode is not None:
        conn.auth_mode = req.auth_mode
    if req.username is not None:
        conn.username = req.username
    if req.tls_verify is not None:
        conn.tls_verify = req.tls_verify
    if req.secret_ref is not None:
        conn.secret_ref = req.secret_ref
    options = dict((conn.metadata_json or {}).get("options") or {})
    if req.oauth_client_id is not None:
        options["oauth_client_id"] = req.oauth_client_id
    if req.oauth_scope is not None:
        options["oauth_scope"] = req.oauth_scope
    if req.oauth_token_url is not None:
        _sap_settings_guard(conn.base_url, conn.service_path or "", req.oauth_token_url)
        options["oauth_token_url"] = req.oauth_token_url
    cached = dict(conn.metadata_json or {})
    cached["options"] = options
    conn.metadata_json = cached
    conn.updated_by = user.username
    db.commit()
    db.refresh(conn)
    _audit(db, "connection.sap.patched", "connection", conn.id,
           {"fields": [k for k, v in req.model_dump().items() if v is not None and k != "secret"],
            "secret_rotated": bool(req.secret)})
    return ConnectionResponse.model_validate(conn)


@app.post("/api/v1/connections/{conn_id}/disable", tags=["SAP Connector"])
async def disable_sap_connection(conn_id: str, request: Request, db: Session = Depends(get_app_db)):
    """Soft-disable a SAP connection (revokes QueryPilot-side availability)."""
    user = _require_sap_admin(request)
    conn = _get_sap_connection(conn_id, db)
    conn.is_active = False
    conn.lifecycle_status = "disabled"
    conn.updated_by = user.username
    db.commit()
    _audit(db, "connection.sap.disabled", "connection", conn_id, {})
    return {"status": "disabled", "connection_id": conn_id}


# ============================================================================
# QUERY ENDPOINTS (Core workflow)
# ============================================================================

@app.post("/api/v1/queries", response_model=QueryStatus, tags=["Queries"])
async def submit_query(req: QueryRequest, request: Request, db: Session = Depends(get_app_db)):
    """Submit a natural language query for execution.

    Orchestrates the full pipeline with Role Security & RLS:
    Identity Resolution → Schema Pruning → SQL Generation → AST Policy → Database RLS Execution → Verification → Grounded Explanation
    """
    start_time = time.time()

    # Resolve user security context on the server (do not trust arbitrary browser roles)
    role_header = request.headers.get("X-User-Role") or req.user_role or "executive"
    user_header = request.headers.get("X-Username") or req.username
    user_ctx = resolve_user_context(role_or_username=user_header or role_header, explicit_role=role_header)

    # Multi-turn conversation session tracking
    conv_session = None
    conversation_turns = req.conversation_context or []
    if req.session_id:
        conv_session = db.query(ConversationSession).filter(ConversationSession.id == req.session_id).first()
        if not conv_session:
            conv_session = ConversationSession(
                id=req.session_id,
                user_id=user_ctx.user_id,
                user_role=user_ctx.role,
                title=req.question[:60],
                turns=[],
            )
            db.add(conv_session)
            db.commit()
        elif not conversation_turns and conv_session.turns:
            conversation_turns = [
                {"question": t["question"], "sql": t.get("sql"), "active_filters": t.get("active_filters")}
                for t in conv_session.turns[-3:]
            ]

    # Create query record
    record = QueryRecord(
        connection_id=req.connection_id if req.connection_id != "default" else None,
        user_id=user_ctx.user_id,
        user_role=user_ctx.role,
        session_id=req.session_id,
        natural_language_query=req.question,
        status="planning",
        model_name=get_settings().llm_model,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    try:
        # 1. Resolve target engine
        record.status = "planning"
        db.commit()

        if req.connection_id == "default":
            engine = get_target_engine()
            schema_name = "sales"
        else:
            conn = db.query(Connection).filter(
                Connection.id == req.connection_id,
                Connection.is_active == True
            ).first()
            if not conn:
                raise HTTPException(status_code=404, detail="Connection not found")
            if getattr(conn, "connector_type", "postgresql") == "sap_s4hana":
                raise HTTPException(status_code=400, detail=(
                    "SAP sources cannot be queried with SQL. Use the SAP entity "
                    "preview/cross-source join endpoints, which enforce the OData "
                    "policy boundary."
                ))
            engine = create_target_engine(
                host=conn.host, port=conn.port, dbname=conn.database_name,
                user=conn.username, password=decrypt_secret(conn.encrypted_password),
            )
            schema_name = conn.schema_name or "public"

        # 2. Discover schema & prune restricted tables/columns for this role
        schema_svc = get_schema_service()
        schema = schema_svc.discover_schema(engine, req.connection_id, schema_name)
        schema_context = schema_svc.format_schema_for_llm(schema, role=user_ctx.role)

        # 3. Generate SQL with role-based AST policy validation
        record.status = "generating"
        db.commit()

        generator = get_sql_generator()
        gen_result = generator.generate(
            question=req.question,
            schema_context=schema_context,
            conversation_context=conversation_turns or None,
            role=user_ctx.role,
        )

        record.model_name = gen_result.model_name
        record.model_version = get_settings().llm_model

        if gen_result.needs_clarification:
            record.status = "clarification_needed"
            record.explanation = gen_result.clarification_question
            record.assumptions = []
            record.total_time_ms = (time.time() - start_time) * 1000
            db.commit()
            db.refresh(record)
            return QueryStatus.model_validate(record)

        if not gen_result.success:
            record.status = "failed"
            record.error_message = gen_result.error
            record.error_category = "generation_failed"
            record.total_time_ms = (time.time() - start_time) * 1000
            db.commit()
            db.refresh(record)
            _audit(db, "query.rejected", "query", record.id, {
                "question": req.question,
                "user_role": user_ctx.role,
                "reason": gen_result.error,
            })
            return QueryStatus.model_validate(record)

        # 3.5 Anti-hallucination grounding gate — every table/column in the SQL
        # must exist in the live discovered schema; hallucinated identifiers are
        # rejected and repaired before anything reaches PostgreSQL.
        grounding = SchemaGroundingValidator(schema, default_schema=schema_name).validate(gen_result.sql)
        grounding_repair_attempts = 0
        while not grounding.grounded and grounding_repair_attempts < 2:
            grounding_repair_attempts += 1
            logger.info(
                "Grounding repair attempt %d: %s",
                grounding_repair_attempts, "; ".join(grounding.violations),
            )
            repair_gen = generator.attempt_execution_repair(
                question=req.question,
                original_sql=gen_result.sql,
                db_error="; ".join(grounding.violations)
                + ". These objects DO NOT exist in the database. Rewrite the query using ONLY tables and columns present in the schema context, or state that the question cannot be answered with available data.",
                schema_context=schema_context,
                role=user_ctx.role,
            )
            if not (repair_gen.success and repair_gen.sql):
                break
            gen_result.sql = repair_gen.sql
            gen_result.tables_used = repair_gen.tables_used or gen_result.tables_used
            gen_result.assumptions = repair_gen.assumptions or gen_result.assumptions
            grounding = SchemaGroundingValidator(schema, default_schema=schema_name).validate(gen_result.sql)

        if not grounding.grounded:
            record.status = "blocked"
            record.generated_sql = gen_result.sql
            record.error_message = (
                "Answer withheld: the generated query referenced data that does not exist in the database. "
                + "; ".join(grounding.violations)
            )
            record.error_category = "hallucinated_schema_objects"
            record.evidence = {
                "verified": False,
                "status": "blocked_hallucination",
                "schema_grounding": {
                    "passed": False,
                    "hallucinated_tables": grounding.hallucinated_tables,
                    "hallucinated_columns": grounding.hallucinated_columns,
                },
            }
            record.total_time_ms = (time.time() - start_time) * 1000
            db.commit()
            db.refresh(record)
            _audit(db, "query.blocked.hallucination", "query", record.id, {
                "question": req.question,
                "user_role": user_ctx.role,
                "violations": grounding.violations,
            })
            return QueryStatus.model_validate(record)

        record.generated_sql = gen_result.sql
        record.validated_sql = gen_result.sql
        record.query_plan = {
            "tables_used": gen_result.tables_used,
            "assumptions": gen_result.assumptions,
            "repair_attempts": gen_result.repair_attempts,
            "grounding_repair_attempts": grounding_repair_attempts,
        }

        # 4. Execute query under PostgreSQL database-level RLS
        record.status = "executing"
        db.commit()

        executor = get_query_executor()
        exec_result = executor.execute(engine, gen_result.sql, user_context=user_ctx)

        record.execution_time_ms = exec_result.execution_time_ms

        if not exec_result.success:
            # Execution failed — bounded repair with database error context and role enforcement
            if gen_result.repair_attempts < 2 and "timeout" not in str(exec_result.error or "").lower():
                record.status = "generating"
                db.commit()

                repair_gen = generator.attempt_execution_repair(
                    question=req.question,
                    original_sql=gen_result.sql,
                    db_error=str(exec_result.error),
                    schema_context=schema_context,
                    role=user_ctx.role,
                )
                if repair_gen.success and repair_gen.sql:
                    rep_exec = executor.execute(engine, repair_gen.sql, user_context=user_ctx)
                    if rep_exec.success:
                        exec_result = rep_exec
                        gen_result.sql = repair_gen.sql
                        record.generated_sql = repair_gen.sql
                        record.validated_sql = repair_gen.sql
                        record.execution_time_ms = rep_exec.execution_time_ms

            if not exec_result.success:
                record.status = "failed"
                record.error_message = exec_result.error
                record.error_category = exec_result.error_category
                record.total_time_ms = (time.time() - start_time) * 1000
                db.commit()
                db.refresh(record)
                _audit(db, "query.failed", "query", record.id, {
                    "question": req.question,
                    "user_role": user_ctx.role,
                    "error": str(exec_result.error),
                })
                return QueryStatus.model_validate(record)

        # 5. Verify and store results
        record.status = "verifying"
        db.commit()

        record.result_columns = exec_result.columns
        record.result_data = exec_result.rows
        record.result_row_count = exec_result.row_count
        record.result_truncated = exec_result.truncated

        # 6. Generate chart spec
        chart_spec = select_chart_type(
            columns=exec_result.columns,
            rows=exec_result.rows,
            question=req.question,
        )
        record.chart_spec = chart_spec
        db.commit()

        # 7. Generate explanation with prompt injection safeguards and
        # numeric evidence verification (anti-hallucination gate)
        explanation_svc = get_explanation_service()
        explanation, explanation_grounding = explanation_svc.generate_explanation(
            question=req.question,
            sql=gen_result.sql,
            columns=exec_result.columns,
            rows=exec_result.rows,
            assumptions=gen_result.assumptions,
        )
        record.explanation = explanation
        record.assumptions = gen_result.assumptions

        # 8. Build evidence provenance record (visible to the user)
        columns_used: list[str] = []
        for t in schema.tables:
            full = f"{t.schema_name}.{t.table_name}".lower()
            if any(full == v or full.endswith("." + v) or v.endswith(full) or v == t.table_name.lower()
                   for v in [x.lower() for x in gen_result.tables_used]):
                columns_used.extend(c.name for c in t.columns)
        record.evidence = build_evidence(
            tables_used=gen_result.tables_used,
            columns_used=columns_used,
            sql=gen_result.sql,
            row_count=exec_result.row_count,
            execution_time_ms=exec_result.execution_time_ms,
            grounding=grounding,
            explanation_grounded=explanation_grounding.get("passed", False),
            unverified_claims=explanation_grounding.get("unverified_claims", []),
            model_name=gen_result.model_name,
        )
        record.evidence["explanation_source"] = explanation_grounding.get("source")

        # 9. Complete
        record.status = "completed"
        record.completed_at = datetime.now(timezone.utc)
        record.total_time_ms = (time.time() - start_time) * 1000
        db.commit()
        db.refresh(record)

        # Update conversation session turn state if session active
        if conv_session:
            new_turn = {
                "turn": (conv_session.turn_count or 0) + 1,
                "question": req.question,
                "sql": gen_result.sql,
                "row_count": exec_result.row_count,
                "explanation": explanation[:250] if explanation else "",
            }
            updated_turns = list(conv_session.turns or [])
            updated_turns.append(new_turn)
            conv_session.turns = updated_turns
            conv_session.last_sql = gen_result.sql
            conv_session.turn_count = len(updated_turns)
            db.commit()

        # Audit with full security metadata
        _audit(db, "query.completed", "query", record.id, {
            "user_role": user_ctx.role,
            "user_id": user_ctx.user_id,
            "execution_time_ms": record.execution_time_ms,
            "row_count": record.result_row_count,
        })

        return QueryStatus.model_validate(record)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Query processing failed: %s", str(e), exc_info=True)
        record.status = "failed"
        record.error_message = f"Processing error: {type(e).__name__}"
        record.error_category = "internal_error"
        record.total_time_ms = (time.time() - start_time) * 1000
        db.commit()
        db.refresh(record)
        return QueryStatus.model_validate(record)


@app.get("/api/v1/queries/{query_id}", response_model=QueryStatus, tags=["Queries"])
async def get_query(query_id: str, db: Session = Depends(get_app_db)):
    """Get query status and results."""
    record = db.query(QueryRecord).filter(QueryRecord.id == query_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    return QueryStatus.model_validate(record)


@app.post("/api/v1/queries/{query_id}/feedback", tags=["Queries"])
async def submit_feedback(query_id: str, feedback: QueryFeedback, db: Session = Depends(get_app_db)):
    """Submit user feedback for a query result."""
    record = db.query(QueryRecord).filter(QueryRecord.id == query_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Query not found")
    record.feedback_rating = feedback.rating
    record.feedback_comment = feedback.comment
    db.commit()
    _audit(db, "query.feedback", "query", query_id, {"rating": feedback.rating})
    return {"status": "recorded"}


# ============================================================================
# QUERY HISTORY
# ============================================================================

@app.get("/api/v1/query-history", response_model=QueryHistoryResponse, tags=["History"])
@app.get("/api/v1/queries", response_model=QueryHistoryResponse, tags=["History"])
async def query_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_app_db),
):
    """Get paginated query history."""
    q = db.query(QueryRecord).order_by(QueryRecord.created_at.desc())
    if status:
        q = q.filter(QueryRecord.status == status)

    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    return QueryHistoryResponse(
        items=[
            QueryHistoryItem(
                id=r.id,
                question=r.natural_language_query,
                status=r.status,
                execution_time_ms=r.execution_time_ms,
                result_row_count=r.result_row_count,
                model_name=r.model_name,
                created_at=r.created_at,
                feedback_rating=r.feedback_rating,
            )
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# ============================================================================
# STATS / OVERVIEW (real aggregates from the live target database)
# ============================================================================

_REVENUE_EXPR = "(i.quantity * i.unit_price * (1 - i.discount_pct / 100))"


@app.get("/api/v1/stats/overview", tags=["Stats"])
async def stats_overview():
    """Compute real business aggregates directly from the live PostgreSQL
    target database. Every number rendered on the Analytics Workspace and
    Executive Reports screens originates here (no hardcoded values)."""
    engine = get_target_engine()
    s = _active_schema_name
    rx = _REVENUE_EXPR
    try:
        with engine.connect() as conn:
            total_sales = float(conn.execute(text(f"""
                SELECT COALESCE(ROUND(SUM({rx})::numeric, 2), 0)
                FROM {s}.sales_orders o
                JOIN {s}.sales_order_items i ON i.order_id = o.order_id
                WHERE o.status = 'completed'
            """))  .scalar() or 0)
            total_orders = int(conn.execute(text(f"SELECT COUNT(*) FROM {s}.sales_orders")).scalar() or 0)
            total_customers = int(conn.execute(text(f"SELECT COUNT(*) FROM {s}.customers")).scalar() or 0)
            total_products = int(conn.execute(text(f"SELECT COUNT(*) FROM {s}.product_catalog")).scalar() or 0)

            region_rows = conn.execute(text(f"""
                SELECT r.region_name,
                       COALESCE(ROUND(SUM({rx})::numeric, 2), 0) AS revenue,
                       COUNT(DISTINCT o.order_id) AS orders,
                       COUNT(DISTINCT c.customer_id) AS customers
                FROM {s}.regions r
                LEFT JOIN {s}.sales_orders o ON o.region_id = r.region_id AND o.status = 'completed'
                LEFT JOIN {s}.sales_order_items i ON i.order_id = o.order_id
                LEFT JOIN {s}.customers c ON c.customer_id = o.customer_id
                GROUP BY r.region_name
                ORDER BY revenue DESC
            """)).fetchall()

            top_customer_rows = conn.execute(text(f"""
                SELECT c.company_name,
                       COUNT(DISTINCT o.order_id) AS orders,
                       COALESCE(ROUND(SUM({rx})::numeric, 2), 0) AS revenue
                FROM {s}.customers c
                JOIN {s}.sales_orders o ON o.customer_id = c.customer_id AND o.status = 'completed'
                JOIN {s}.sales_order_items i ON i.order_id = o.order_id
                GROUP BY c.company_name
                ORDER BY revenue DESC
                LIMIT 5
            """)).fetchall()

            cat_rev_rows = conn.execute(text(f"""
                SELECT p.category,
                       COALESCE(ROUND(SUM({rx})::numeric, 2), 0) AS revenue,
                       COUNT(DISTINCT p.product_id) AS items
                FROM {s}.product_catalog p
                LEFT JOIN {s}.sales_order_items i ON i.product_id = p.product_id
                LEFT JOIN {s}.sales_orders o ON o.order_id = i.order_id AND o.status = 'completed'
                GROUP BY p.category
                ORDER BY revenue DESC
            """)).fetchall()

            cat_margin_rows = conn.execute(text(f"""
                SELECT category,
                       ROUND(AVG((unit_price - cost_price) / NULLIF(unit_price, 0) * 100)::numeric, 1) AS avg_margin
                FROM {s}.product_catalog
                GROUP BY category
            """)).fetchall()
    except Exception as exc:  # target DB unreachable / schema changed
        raise HTTPException(status_code=503, detail=f"Stats unavailable from target DB: {exc}")

    margin_by_cat = {r[0]: float(r[1] or 0) for r in cat_margin_rows}
    denom = total_sales or 1

    return {
        "source": "live_postgresql_target_database",
        "schema": s,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "total_sales": round(total_sales, 2),
            "total_orders": total_orders,
            "total_customers": total_customers,
            "total_products": total_products,
        },
        "regions": [
            {
                "region": r[0],
                "revenue": float(r[1] or 0),
                "orders": int(r[2] or 0),
                "customers": int(r[3] or 0),
                "avg_order_value": round(float(r[1] or 0) / (int(r[2] or 0) or 1), 2),
                "pct": round(float(r[1] or 0) / denom * 100, 1),
            }
            for r in region_rows
        ],
        "top_customers": [
            {"company": tc[0], "orders": int(tc[1] or 0), "revenue": float(tc[2] or 0)}
            for tc in top_customer_rows
        ],
        "product_categories": [
            {
                "category": cr[0],
                "revenue": float(cr[1] or 0),
                "items": int(cr[2] or 0),
                "avg_margin_pct": margin_by_cat.get(cr[0], 0.0),
            }
            for cr in cat_rev_rows
        ],
    }


# ============================================================================
# EVALUATIONS
# ============================================================================

@app.post("/api/v1/evaluations/runs", response_model=EvaluationRunResponse, tags=["Evaluations"])
@app.post("/api/v1/evaluations/run", response_model=EvaluationRunResponse, tags=["Evaluations"])
@app.post("/api/v1/evaluations", response_model=EvaluationRunResponse, tags=["Evaluations"])
async def create_evaluation_run(
    req: EvaluationRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_app_db),
):
    """Start a new evaluation benchmark run."""
    settings = get_settings()
    run = EvaluationRun(
        dataset_name=req.dataset_name,
        model_name=settings.llm_model,
        model_version=settings.llm_model,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Run evaluation in background
    background_tasks.add_task(_run_evaluation, run.id, req.dataset_name, req.connection_id)

    return EvaluationRunResponse.model_validate(run)


@app.get("/api/v1/evaluations/runs", response_model=list[EvaluationRunResponse], tags=["Evaluations"])
@app.get("/api/v1/evaluations", response_model=list[EvaluationRunResponse], tags=["Evaluations"])
async def list_evaluation_runs(db: Session = Depends(get_app_db)):
    """List all evaluation runs."""
    runs = db.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(50).all()
    return [EvaluationRunResponse.model_validate(r) for r in runs]


@app.get("/api/v1/evaluations/runs/{run_id}", response_model=EvaluationRunDetailResponse, tags=["Evaluations"])
@app.get("/api/v1/evaluations/{run_id}", response_model=EvaluationRunDetailResponse, tags=["Evaluations"])
async def get_evaluation_run(run_id: str, db: Session = Depends(get_app_db)):
    """Get evaluation run details with individual test cases."""
    run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    results = db.query(EvaluationResult).filter(EvaluationResult.run_id == run_id).order_by(EvaluationResult.created_at.asc()).all()
    resp = EvaluationRunDetailResponse.model_validate(run)
    resp.results = [EvaluationResultResponse.model_validate(r) for r in results]
    return resp


@app.get("/api/v1/evaluations/runs/{run_id}/results", response_model=list[EvaluationResultResponse], tags=["Evaluations"])
@app.get("/api/v1/evaluations/{run_id}/results", response_model=list[EvaluationResultResponse], tags=["Evaluations"])
async def get_evaluation_results(run_id: str, db: Session = Depends(get_app_db)):
    """Get individual test case results for an evaluation run."""
    results = db.query(EvaluationResult).filter(EvaluationResult.run_id == run_id).order_by(EvaluationResult.created_at.asc()).all()
    return [EvaluationResultResponse.model_validate(r) for r in results]


# ============================================================================
# AUDIT EVENTS
# ============================================================================

@app.get("/api/v1/audit-events", response_model=list[AuditEventResponse], tags=["Audit"])
@app.get("/api/v1/audit", response_model=list[AuditEventResponse], tags=["Audit"])
async def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: Optional[str] = None,
    db: Session = Depends(get_app_db),
):
    """List audit events."""
    q = db.query(AuditEvent).order_by(AuditEvent.created_at.desc())
    if event_type:
        q = q.filter(AuditEvent.event_type == event_type)
    events = q.limit(limit).all()
    return [AuditEventResponse.model_validate(e) for e in events]


# ============================================================================
# OVERVIEW STATS
# ============================================================================

@app.get("/api/v1/stats", tags=["Stats"])
async def get_stats(db: Session = Depends(get_app_db)):
    """Get dashboard overview statistics from real persisted data."""
    total_queries = db.query(QueryRecord).count()
    successful = db.query(QueryRecord).filter(QueryRecord.status == "completed").count()
    failed = db.query(QueryRecord).filter(QueryRecord.status == "failed").count()
    blocked = db.query(QueryRecord).filter(QueryRecord.status == "blocked").count()
    connections = db.query(Connection).filter(Connection.is_active == True).count()

    # Average latency
    from sqlalchemy import func
    avg_latency = db.query(func.avg(QueryRecord.execution_time_ms)).filter(
        QueryRecord.status == "completed"
    ).scalar()

    # Latest eval
    latest_eval = db.query(EvaluationRun).order_by(
        EvaluationRun.started_at.desc()
    ).first()

    # Recent queries
    recent = db.query(QueryRecord).order_by(
        QueryRecord.created_at.desc()
    ).limit(5).all()

    return {
        "total_queries": total_queries,
        "successful_queries": successful,
        "failed_queries": failed,
        "blocked_queries": blocked,
        "active_connections": connections + 1,  # +1 for default
        "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
        "latest_evaluation": EvaluationRunResponse.model_validate(latest_eval) if latest_eval else None,
        "recent_queries": [
            QueryHistoryItem(
                id=r.id, question=r.natural_language_query, status=r.status,
                execution_time_ms=r.execution_time_ms, result_row_count=r.result_row_count,
                model_name=r.model_name, created_at=r.created_at, feedback_rating=r.feedback_rating,
            )
            for r in recent
        ],
    }



# ============================================================================
# SETTINGS: LIVE DATABASE & LLM CONFIGURATION (Settings screen)
# ============================================================================

def _persist_env(updates: dict[str, str]):
    """Update .env values in-place (create-or-replace keys) so config survives restarts."""
    from pathlib import Path
    # Project root = parent of backend/ (workspace .env lives there)
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key and key.upper() in remaining:
            out.append(f"{key.upper()}={remaining.pop(key.upper())}")
        else:
            out.append(line)
    for key, val in remaining.items():
        out.append(f"{key}={val}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


@app.get("/api/v1/settings/runtime", tags=["Settings"])
async def get_runtime_settings():
    """Return the ACTIVE runtime configuration (real values, not defaults)."""
    s = get_settings()
    global _active_schema_name
    return {
        "target_db": {
            "host": s.target_db_host,
            "port": s.target_db_port,
            "database_name": s.target_db_name,
            "username": s.target_db_user,
            "schema_name": _active_schema_name,
            "statement_timeout_ms": s.sql_statement_timeout_ms,
            "has_password": bool(s.target_db_password),
        },
        "llm": {
            "provider": s.llm_provider,
            "model": s.llm_model,
            "base_url": s.llm_base_url,
            "temperature": s.llm_temperature,
        },
        "query_limits": {
            "max_rows": s.sql_max_rows,
            "max_query_length": s.sql_max_query_length,
        },
        "database_url": str(get_app_engine().url).split("@")[0].split("://")[0] + "://***",
    }


@app.post("/api/v1/settings/target-db/test", response_model=SettingsApplyResult, tags=["Settings"])
async def test_target_db_settings(req: TargetDbSettingsUpdate):
    """Real connectivity test against the proposed target PostgreSQL database."""
    try:
        engine = create_target_engine(
            host=req.host, port=req.port, dbname=req.database_name,
            user=req.username, password=req.password,
            statement_timeout_ms=req.statement_timeout_ms,
        )
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
            result = conn.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema"
            ), {"schema": req.schema_name})
            table_count = result.scalar() or 0
        engine.dispose()
        return SettingsApplyResult(
            success=True,
            message=f"Connected to PostgreSQL {version}. Found {table_count} tables in schema '{req.schema_name}'.",
            detail={"server_version": version, "tables_found": table_count, "schema": req.schema_name},
        )
    except Exception as e:
        return SettingsApplyResult(success=False, message=f"Connection failed: {str(e)[:250]}")


@app.post("/api/v1/settings/target-db/apply", response_model=SettingsApplyResult, tags=["Settings"])
async def apply_target_db_settings(req: TargetDbSettingsUpdate, db: Session = Depends(get_app_db)):
    """Validate, apply and persist a new target PostgreSQL connection at runtime."""
    global _target_engine, _active_schema_name
    try:
        new_engine = create_target_engine(
            host=req.host, port=req.port, dbname=req.database_name,
            user=req.username, password=req.password,
            statement_timeout_ms=req.statement_timeout_ms,
        )
        with new_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            result = conn.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema"
            ), {"schema": req.schema_name})
            table_count = result.scalar() or 0
        if table_count == 0:
            new_engine.dispose()
            return SettingsApplyResult(
                success=False,
                message=f"Connected, but schema '{req.schema_name}' contains no tables. Aborted — target not applied.",
            )
    except Exception as e:
        return SettingsApplyResult(success=False, message=f"Connection failed — not applied: {str(e)[:250]}")

    # Swap live engine only after successful verification
    if _target_engine is not None:
        try:
            _target_engine.dispose()
        except Exception:
            pass
    _target_engine = new_engine
    _active_schema_name = req.schema_name

    # Update in-memory settings + persist to .env
    s = get_settings()
    s.target_db_host = req.host
    s.target_db_port = req.port
    s.target_db_name = req.database_name
    s.target_db_user = req.username
    s.sql_statement_timeout_ms = req.statement_timeout_ms
    if req.password:
        s.target_db_password = req.password
    get_schema_service().clear_cache()

    try:
        _persist_env({
            "TARGET_DB_HOST": req.host,
            "TARGET_DB_PORT": str(req.port),
            "TARGET_DB_NAME": req.database_name,
            "TARGET_DB_USER": req.username,
            "SQL_STATEMENT_TIMEOUT_MS": str(req.statement_timeout_ms),
        })
    except Exception as e:
        logger.warning("Could not persist target DB settings to .env: %s", e)

    _audit(db, "settings.target_db.applied", "settings", "runtime", {
        "host": req.host, "port": req.port, "database": req.database_name, "schema": req.schema_name,
    })
    return SettingsApplyResult(
        success=True,
        message=f"Target database applied. {table_count} tables in '{req.schema_name}' are now live for analysis.",
        detail={"tables_found": table_count},
    )


@app.post("/api/v1/settings/llm/test", response_model=SettingsApplyResult, tags=["Settings"])
async def test_llm_settings(req: LlmSettingsUpdate):
    """Real health check against the proposed Ollama endpoint and model."""
    probe = LLMProvider(model=req.model, base_url=req.base_url)
    try:
        health = probe.check_health()
    finally:
        probe.close()
    if health["status"] == "healthy":
        return SettingsApplyResult(
            success=True,
            message=f"Ollama online. Model '{req.model}' available.",
            detail={"available_models": health.get("available_models", [])},
        )
    return SettingsApplyResult(
        success=False,
        message=f"Model check failed: {health.get('error') or health['status']}. Available: {', '.join(health.get('available_models', [])) or 'none'}",
    )


@app.post("/api/v1/settings/llm/apply", response_model=SettingsApplyResult, tags=["Settings"])
async def apply_llm_settings(req: LlmSettingsUpdate):
    """Verify and hot-swap the active LLM provider used by all AI services."""
    global _llm, _sql_generator, _explanation_service
    probe = LLMProvider(model=req.model, base_url=req.base_url)
    try:
        health = probe.check_health()
    finally:
        probe.close()
    if health["status"] != "healthy":
        return SettingsApplyResult(success=False, message=f"Model '{req.model}' not available: {health.get('error')}")

    s = get_settings()
    s.llm_model = req.model
    s.llm_base_url = req.base_url
    if req.temperature is not None:
        s.llm_temperature = req.temperature

    old_llm = _llm
    _llm = LLMProvider(
        provider=s.llm_provider, model=s.llm_model, base_url=s.llm_base_url,
        temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
        timeout=s.llm_request_timeout,
    )
    if old_llm:
        try:
            old_llm.close()
        except Exception:
            pass
    # Rebind singletons that captured the old provider
    _sql_generator = SQLGenerator(llm=_llm, policy_engine=get_sql_policy())
    _explanation_service = ExplanationService(llm=_llm)

    try:
        _persist_env({
            "LLM_MODEL": req.model,
            "LLM_BASE_URL": req.base_url,
            **({"LLM_TEMPERATURE": str(req.temperature)} if req.temperature is not None else {}),
        })
    except Exception as e:
        logger.warning("Could not persist LLM settings to .env: %s", e)

    return SettingsApplyResult(success=True, message=f"Model '{req.model}' applied and active for all AI services.")


# ============================================================================
# PHASE 2: ROLES & PERMISSION MATRIX
# ============================================================================

@app.get("/api/v1/roles", tags=["Security Roles"])
async def get_roles_and_permissions():
    """Retrieve verified roles, assigned personas, and permission matrix."""
    from app.services.role_service import VERIFIED_USERS, RESTRICTED_COLUMNS, PROHIBITED_TABLES_BY_ROLE
    
    matrix = {
        "roles": [
            {
                "role": "executive",
                "title": "Executive / Admin",
                "row_scope": "Organization-wide unrestricted analytical access",
                "restricted_columns": [],
                "prohibited_tables": [],
            },
            {
                "role": "regional_manager",
                "title": "Regional Manager",
                "row_scope": "Restricted to assigned region (e.g. Region 1 North, Region 2 South) via PostgreSQL RLS",
                "restricted_columns": [f"{s}.{t}.{c}" for s, t, c in RESTRICTED_COLUMNS["regional_manager"]],
                "prohibited_tables": [f"{s}.{t}" for s, t in PROHIBITED_TABLES_BY_ROLE["regional_manager"]],
            },
            {
                "role": "sales_rep",
                "title": "Sales Representative",
                "row_scope": "Restricted to assigned sales rep orders (e.g. Carol Chen) via PostgreSQL RLS",
                "restricted_columns": [f"{s}.{t}.{c}" for s, t, c in RESTRICTED_COLUMNS["sales_rep"]],
                "prohibited_tables": [f"{s}.{t}" for s, t in PROHIBITED_TABLES_BY_ROLE["sales_rep"]],
            },
        ],
        "verified_personas": [
            {
                "username": u.username,
                "role": u.role,
                "region_id": u.region_id,
                "sales_rep": u.sales_rep,
                "description": u.description,
            }
            for u in VERIFIED_USERS.values()
        ],
    }
    return matrix


# ============================================================================
# PHASE 2: CONVERSATION SESSIONS (MULTI-TURN)
# ============================================================================

@app.get("/api/v1/conversations", tags=["Conversations"])
async def list_conversations(limit: int = 20, db: Session = Depends(get_app_db)):
    """List recent conversation sessions."""
    sessions = db.query(ConversationSession).order_by(ConversationSession.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "user_role": s.user_role,
            "turn_count": s.turn_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@app.post("/api/v1/conversations", tags=["Conversations"])
async def create_conversation(
    title: str = Query("New Analysis Session"),
    user_role: str = Query("executive"),
    db: Session = Depends(get_app_db),
):
    """Create a new multi-turn conversation session."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = ConversationSession(
        id=session_id,
        user_role=user_role,
        title=title,
        turn_count=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "title": session.title,
        "user_role": session.user_role,
        "turn_count": session.turn_count,
        "created_at": session.created_at.isoformat(),
    }


@app.get("/api/v1/conversations/{session_id}", tags=["Conversations"])
async def get_conversation_turns(session_id: str, db: Session = Depends(get_app_db)):
    """Retrieve full turn history and metadata for a session."""
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    records = db.query(QueryRecord).filter(
        QueryRecord.session_id == session_id
    ).order_by(QueryRecord.created_at.asc()).all()

    return {
        "id": session.id,
        "title": session.title,
        "user_role": session.user_role,
        "turn_count": session.turn_count,
        "turns": [
            {
                "id": r.id,
                "question": r.natural_language_query,
                "sql": r.generated_sql,
                "status": r.status,
                "execution_time_ms": r.execution_time_ms,
                "result_row_count": r.result_row_count,
                "columns": [c["name"] for c in r.result_columns] if r.result_columns else [],
                "rows": r.result_rows[:10] if r.result_rows else [],
                "explanation": r.explanation,
                "chart_config": r.chart_config,
                "clarification_message": r.error_message if r.status == "clarification_needed" else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


# ============================================================================
# PHASE 2: EVALUATION DASHBOARDS (SECURITY, 50-CONVERSATION, SCHEMA RECOVERY)
# ============================================================================

@app.post("/api/v1/evaluations/security/runs", tags=["Evaluations"])
async def run_security_eval(background_tasks: BackgroundTasks):
    """Trigger adversarial security evaluation suite (35 cases)."""
    import threading
    from app.services.security_evaluator import SecurityEvaluator
    import json
    from pathlib import Path

    def _execute():
        evaluator = SecurityEvaluator()
        res = evaluator.run_suite()
        out_p = Path(__file__).resolve().parent.parent / "data" / "security_attack_results.json"
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

    threading.Thread(target=_execute, daemon=True).start()
    return {"status": "started", "message": "Adversarial security evaluation suite is running."}


@app.get("/api/v1/evaluations/security/latest", tags=["Evaluations"])
async def get_latest_security_eval():
    """Retrieve latest adversarial security evaluation results."""
    import json
    from pathlib import Path
    out_p = Path(__file__).resolve().parent.parent / "data" / "security_attack_results.json"
    if not out_p.exists():
        raise HTTPException(status_code=404, detail="No security evaluation results found")
    with open(out_p, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/v1/evaluations/conversations/runs", tags=["Evaluations"])
async def run_conversations_eval():
    """Trigger 50-scenario multi-turn conversation evaluation."""
    import threading
    from app.services.conversation_evaluator import ConversationEvaluator
    import json
    from pathlib import Path

    def _execute():
        evaluator = ConversationEvaluator()
        res = evaluator.run_suite()
        out_p = Path(__file__).resolve().parent.parent / "data" / "conversations_benchmark_results.json"
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

    threading.Thread(target=_execute, daemon=True).start()
    return {"status": "started", "message": "50-conversation benchmark suite is running."}


@app.get("/api/v1/evaluations/conversations/latest", tags=["Evaluations"])
async def get_latest_conversations_eval():
    """Retrieve latest 50-scenario multi-turn conversation benchmark results."""
    import json
    from pathlib import Path
    out_p = Path(__file__).resolve().parent.parent / "data" / "conversations_benchmark_results.json"
    if not out_p.exists():
        raise HTTPException(status_code=404, detail="No conversation evaluation results found")
    with open(out_p, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/v1/schema-recovery/runs", tags=["Schema Recovery"])
async def run_schema_recovery():
    """Trigger live schema migration recovery evaluation."""
    import threading
    from app.services.schema_recovery import SchemaRecoveryEngine
    import json
    from pathlib import Path

    def _execute():
        engine = SchemaRecoveryEngine()
        res = engine.run_recovery_evaluation()
        out_p = Path(__file__).resolve().parent.parent / "data" / "schema_recovery_results.json"
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

    threading.Thread(target=_execute, daemon=True).start()
    return {"status": "started", "message": "Schema migration recovery evaluation is running."}


@app.get("/api/v1/schema-recovery/latest", tags=["Schema Recovery"])
async def get_latest_schema_recovery():
    """Retrieve latest schema recovery results."""
    import json
    from pathlib import Path
    out_p = Path(__file__).resolve().parent.parent / "data" / "schema_recovery_results.json"
    if not out_p.exists():
        raise HTTPException(status_code=404, detail="No schema recovery results found")
    with open(out_p, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/audit", tags=["Audit"])
async def get_audit_trail(limit: int = 50, db: Session = Depends(get_app_db)):
    """Retrieve audit log entries for security and compliance."""
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "action": e.action,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "details": e.details,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

# ============================================================================
# PHASE 2: DISCOVER & EARLY WARNINGS (proactive intelligence)
# ============================================================================

from pydantic import BaseModel as _DiscoveryBaseModel

_discovery_thread = None
_discovery_stop = None
_discovery_last_run: dict = {"status": "idle"}


def _serialize_finding(f: DiscoveryFinding) -> dict:
    return {
        "id": f.id,
        "run_id": f.run_id,
        "signature": f.signature,
        "severity": f.severity,
        "score": f.score,
        "finding_type": f.finding_type,
        "title": f.title,
        "narrative": f.narrative,
        "hypothesis": f.hypothesis,
        "suggested_next_steps": f.suggested_next_steps,
        "metric_name": f.metric_name,
        "dimension_name": f.dimension_name,
        "segment": f.segment,
        "baseline_value": f.baseline_value,
        "current_value": f.current_value,
        "delta_abs": f.delta_abs,
        "delta_pct": f.delta_pct,
        "comparison_label": f.comparison_label,
        "period_label": f.period_label,
        "source_tables": f.source_tables,
        "calculation": f.calculation,
        "supporting_data": f.supporting_data,
        "chart_spec": f.chart_spec,
        "assumptions": f.assumptions,
        "limitations": f.limitations,
        "explore_question": f.explore_question,
        "role": f.role,
        "status": f.status,
        "data_freshness_at": f.data_freshness_at.isoformat() if f.data_freshness_at else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _run_discovery_and_track(trigger: str, role: str | None) -> None:
    global _discovery_last_run
    from app.services.discovery_service import run_discovery_job
    _discovery_last_run = {"status": "running", "trigger": trigger}
    try:
        result = run_discovery_job(trigger=trigger, role=role)
        _discovery_last_run = {"status": result.get("status", "completed"), "trigger": trigger, **result}
    except Exception as exc:  # defensive; job already records failure status
        _discovery_last_run = {"status": "failed", "trigger": trigger, "error": str(exc)[:300]}


def _start_discovery_scheduler() -> None:
    """Background scheduler that periodically runs discovery on the live DB."""
    global _discovery_thread, _discovery_stop
    settings = get_settings()
    if not (settings.discovery_enabled and settings.discovery_schedule_enabled):
        logger.info("Discovery scheduler disabled by configuration")
        return
    if _discovery_thread and _discovery_thread.is_alive():
        return
    import threading
    _discovery_stop = threading.Event()

    def _loop():
        # initial delay so startup/tests aren't blocked
        if _discovery_stop.wait(settings.discovery_initial_delay_seconds):
            return
        while not _discovery_stop.is_set():
            try:
                _run_discovery_and_track("scheduled", None)
            except Exception as exc:
                logger.error("Scheduled discovery failed: %s", exc)
            if _discovery_stop.wait(settings.discovery_interval_minutes * 60):
                break

    _discovery_thread = threading.Thread(target=_loop, daemon=True, name="discovery-scheduler")
    _discovery_thread.start()
    logger.info("Discovery scheduler started (every %s min)", settings.discovery_interval_minutes)


class DiscoveryRoleRequest(_DiscoveryBaseModel):
    role: Optional[str] = None


@app.post("/api/v1/discover/runs", tags=["Discover"])
async def trigger_discovery_run(req: DiscoveryRoleRequest, background_tasks: BackgroundTasks):
    """Trigger a proactive discovery job in the background (real read-only queries)."""
    settings = get_settings()
    if not settings.discovery_enabled:
        raise HTTPException(status_code=403, detail="Discovery is disabled")
    role = req.role or settings.discovery_run_role
    background_tasks.add_task(_run_discovery_and_track, "manual", role)
    return {"status": "started", "message": "Proactive discovery job is running.", "role": role}


@app.get("/api/v1/discover/runs/latest", tags=["Discover"])
async def latest_discovery_run(db: Session = Depends(get_app_db)):
    """Return the most recent discovery run status + progress."""
    run = db.query(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).first()
    if not run:
        return {"status": "idle", "in_memory": _discovery_last_run, "run": None}
    return {
        "status": run.status,
        "in_memory": _discovery_last_run,
        "run": {
            "id": run.id, "trigger": run.trigger, "role": run.role, "schema_name": run.schema_name,
            "metrics_analyzed": run.metrics_analyzed, "dimensions_analyzed": run.dimensions_analyzed,
            "findings_new": run.findings_new, "findings_deduped": run.findings_deduped,
            "findings_total": run.findings_total, "duration_ms": run.duration_ms,
            "error_message": run.error_message, "detail": run.detail,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
    }


@app.get("/api/v1/discover/findings", tags=["Discover"])
async def list_discovery_findings(
    status: str = Query(default="active"),  # active | all | saved | dismissed
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_app_db),
):
    """List ranked discovery findings. 'active' hides dismissed items."""
    q = db.query(DiscoveryFinding)
    if status == "active":
        q = q.filter(DiscoveryFinding.status != "dismissed")
    elif status in ("saved", "dismissed", "new"):
        q = q.filter(DiscoveryFinding.status == status)
    if severity:
        q = q.filter(DiscoveryFinding.severity == severity)
    items = q.order_by(DiscoveryFinding.score.desc(), DiscoveryFinding.created_at.desc()).limit(limit).all()
    sev_order = {"critical": 0, "warning": 1, "watch": 2, "info": 3}
    items = sorted(items, key=lambda f: (sev_order.get(f.severity, 9), -(f.score or 0)))
    return {
        "count": len(items),
        "summary": {
            "critical": sum(1 for f in items if f.severity == "critical"),
            "warning": sum(1 for f in items if f.severity == "warning"),
            "watch": sum(1 for f in items if f.severity == "watch"),
            "info": sum(1 for f in items if f.severity == "info"),
        },
        "findings": [_serialize_finding(f) for f in items],
    }


@app.get("/api/v1/discover/findings/{finding_id}", tags=["Discover"])
async def get_discovery_finding(finding_id: str, db: Session = Depends(get_app_db)):
    f = db.query(DiscoveryFinding).filter(DiscoveryFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _serialize_finding(f)


@app.post("/api/v1/discover/findings/{finding_id}/dismiss", tags=["Discover"])
async def dismiss_discovery_finding(finding_id: str, db: Session = Depends(get_app_db)):
    f = db.query(DiscoveryFinding).filter(DiscoveryFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    f.status = "dismissed"
    db.commit()
    _audit(db, "discovery.finding_dismissed", "discovery_finding", f.id, {"signature": f.signature})
    return {"status": "dismissed", "id": f.id}


@app.post("/api/v1/discover/findings/{finding_id}/save", tags=["Discover"])
async def save_discovery_finding(finding_id: str, db: Session = Depends(get_app_db)):
    f = db.query(DiscoveryFinding).filter(DiscoveryFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    f.status = "saved"
    db.commit()
    return {"status": "saved", "id": f.id}


# ============================================================================
# FEATURE 1 + 3: MULTI-THREAD INVESTIGATION WORKSPACE + ROOT-CAUSE ENGINE
# ============================================================================

from typing import List as _List


class InvestigationCreate(_DiscoveryBaseModel):
    finding_id: Optional[str] = None
    title: Optional[str] = None
    root_question: Optional[str] = None
    role: Optional[str] = None
    run_root_cause: bool = True


class BranchCreate(_DiscoveryBaseModel):
    title: Optional[str] = None
    question: Optional[str] = None
    parent_branch_id: Optional[str] = None
    origin: str = "manual"
    contributor_segment: Optional[str] = None


class BranchUpdate(_DiscoveryBaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class BranchConclusion(_DiscoveryBaseModel):
    conclusion: str


class CompareRequest(_DiscoveryBaseModel):
    branch_ids: _List[str]


class RootCauseRequest(_DiscoveryBaseModel):
    finding_id: Optional[str] = None
    investigation_id: Optional[str] = None
    spawn_branches: bool = True
    role: Optional[str] = None


def _new_branch(db: Session, inv: Investigation, *, title: str, question: Optional[str],
                origin: str, parent_branch_id: Optional[str], segment: Optional[str],
                role: str) -> InvestigationBranch:
    """Create a branch with its OWN conversation session (independent context)."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    db.add(ConversationSession(
        id=session_id, user_role=role, title=(question or title)[:60], turns=[], turn_count=0,
    ))
    branch = InvestigationBranch(
        id=new_uuid(), investigation_id=inv.id, parent_branch_id=parent_branch_id,
        title=title[:300], seed_question=question, session_id=session_id,
        origin=origin, contributor_segment=segment, status="open",
    )
    db.add(branch)
    return branch


def _serialize_branch(b: InvestigationBranch) -> dict:
    return {
        "id": b.id, "investigation_id": b.investigation_id, "parent_branch_id": b.parent_branch_id,
        "title": b.title, "seed_question": b.seed_question, "session_id": b.session_id,
        "origin": b.origin, "contributor_segment": b.contributor_segment, "status": b.status,
        "conclusion": b.conclusion,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


def _serialize_rcrun(r: RootCauseRun) -> dict:
    return {
        "id": r.id, "investigation_id": r.investigation_id, "finding_id": r.finding_id,
        "metric_name": r.metric_name, "measure_expr": r.measure_expr,
        "dimension_label": r.dimension_label, "dimension_column": r.dimension_column,
        "baseline_period": r.baseline_period, "current_period": r.current_period,
        "baseline_total": r.baseline_total, "current_total": r.current_total,
        "total_change_abs": r.total_change_abs, "total_change_pct": r.total_change_pct,
        "reconciles": r.reconciles, "contributions": r.contributions or [],
        "evidence": r.evidence or {}, "role": r.role,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _branch_turns(db: Session, branch: InvestigationBranch) -> _List[dict]:
    """Evidence for a branch = the QueryRecords executed under its session."""
    if not branch.session_id:
        return []
    records = db.query(QueryRecord).filter(
        QueryRecord.session_id == branch.session_id
    ).order_by(QueryRecord.created_at.asc()).all()
    return [
        {
            "id": rec.id, "question": rec.natural_language_query, "sql": rec.validated_sql or rec.generated_sql,
            "status": rec.status, "row_count": rec.result_row_count,
            "columns": rec.result_columns or [], "rows": (rec.result_data or [])[:50],
            "explanation": rec.explanation, "chart_spec": rec.chart_spec, "evidence": rec.evidence,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        }
        for rec in records
    ]


def _investigation_payload(db: Session, inv: Investigation) -> dict:
    branches = db.query(InvestigationBranch).filter(
        InvestigationBranch.investigation_id == inv.id
    ).order_by(InvestigationBranch.created_at.asc()).all()
    runs = db.query(RootCauseRun).filter(
        RootCauseRun.investigation_id == inv.id
    ).order_by(RootCauseRun.created_at.desc()).all()
    return {
        "id": inv.id, "finding_id": inv.finding_id, "title": inv.title,
        "root_question": inv.root_question, "narrative": inv.narrative,
        "role": inv.role, "status": inv.status,
        "branch_count": len(branches),
        "branches": [_serialize_branch(b) for b in branches],
        "root_cause_runs": [_serialize_rcrun(r) for r in runs],
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
    }


@app.post("/api/v1/investigations", tags=["Investigations"])
async def create_investigation(req: InvestigationCreate, db: Session = Depends(get_app_db)):
    """Open a finding (or a free-form question) as a new multi-branch investigation."""
    finding = None
    if req.finding_id:
        finding = db.query(DiscoveryFinding).filter(DiscoveryFinding.id == req.finding_id).first()
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")

    role = req.role or (finding.role if finding else None) or "executive"
    title = req.title or (f"Investigation: {finding.title[:80]}" if finding else "New Investigation")
    root_q = req.root_question or (finding.explore_question if finding and finding.explore_question else (finding.title if finding else title))

    inv = Investigation(
        id=new_uuid(), finding_id=(finding.id if finding else None), title=title[:300],
        root_question=root_q, narrative=(finding.narrative if finding else None), role=role, status="open",
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    root_branch = _new_branch(db, inv, title="Original investigation", question=root_q,
                              origin="finding" if finding else "manual",
                              parent_branch_id=None, segment=None, role=role)
    db.commit()

    rc_summary = None
    if finding and req.run_root_cause:
        try:
            from app.services.root_cause_service import RootCauseService
            result = RootCauseService(role=role).analyze_finding(finding)
            run = RootCauseRun(
                id=new_uuid(), investigation_id=inv.id, finding_id=finding.id,
                metric_name=result.get("metric_name"), measure_expr=result.get("measure_expr"),
                dimension_label=result.get("dimension_label"), dimension_column=result.get("dimension_column"),
                baseline_period=result.get("baseline_period"), current_period=result.get("current_period"),
                baseline_total=result.get("baseline_total"), current_total=result.get("current_total"),
                total_change_abs=result.get("total_change_abs"), total_change_pct=result.get("total_change_pct"),
                reconciles=bool(result.get("reconciles")), contributions=result.get("contributions", []),
                evidence={**result.get("evidence", {}), "summary": result.get("summary")}, role=role,
            )
            db.add(run)
            db.commit()
            rc_summary = result
            if result.get("status") == "ok":
                for sb in result.get("suggested_branches", []):
                    _new_branch(db, inv, title=sb["title"], question=sb["question"], origin="root_cause",
                                parent_branch_id=root_branch.id, segment=sb.get("contributor_segment"), role=role)
                db.commit()
        except Exception as exc:
            logger.error("Root-cause on investigation create failed: %s", exc, exc_info=True)
            db.rollback()

    _audit(db, "investigation.created", "investigation", inv.id,
           {"finding_id": inv.finding_id, "role": role, "branch_count": inv and len(inv.branches or [])})
    payload = _investigation_payload(db, inv)
    payload["root_cause_summary"] = rc_summary.get("summary") if rc_summary else None
    return payload


@app.get("/api/v1/investigations", tags=["Investigations"])
async def list_investigations(status: str = Query(default="active"), limit: int = Query(default=50, ge=1, le=200),
                              db: Session = Depends(get_app_db)):
    q = db.query(Investigation)
    if status == "active":
        q = q.filter(Investigation.status != "archived")
    elif status in ("archived",):
        q = q.filter(Investigation.status == status)
    items = q.order_by(Investigation.updated_at.desc()).limit(limit).all()
    return {
        "count": len(items),
        "investigations": [
            {
                "id": i.id, "title": i.title, "finding_id": i.finding_id, "role": i.role,
                "status": i.status, "branch_count": len(i.branches or []),
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            }
            for i in items
        ],
    }


@app.get("/api/v1/investigations/{inv_id}", tags=["Investigations"])
async def get_investigation(inv_id: str, db: Session = Depends(get_app_db)):
    inv = db.query(Investigation).filter(Investigation.id == inv_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return _investigation_payload(db, inv)


@app.post("/api/v1/investigations/{inv_id}/branches", tags=["Investigations"])
async def add_branch(inv_id: str, req: BranchCreate, db: Session = Depends(get_app_db)):
    """Create a parallel branch (independent context) under an investigation."""
    inv = db.query(Investigation).filter(Investigation.id == inv_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if req.parent_branch_id:
        parent = db.query(InvestigationBranch).filter(InvestigationBranch.id == req.parent_branch_id).first()
        if not parent or parent.investigation_id != inv.id:
            raise HTTPException(status_code=404, detail="Parent branch not found in this investigation")
    title = req.title or (req.question[:60] if req.question else "New hypothesis")
    branch = _new_branch(db, inv, title=title, question=req.question, origin=req.origin,
                         parent_branch_id=req.parent_branch_id, segment=req.contributor_segment, role=inv.role)
    inv.updated_at = datetime.now(timezone.utc)
    db.commit()
    _audit(db, "investigation.branch_added", "investigation", inv.id, {"branch_id": branch.id, "origin": req.origin})
    return _serialize_branch(branch)


@app.get("/api/v1/investigations/{inv_id}/branches/{branch_id}/turns", tags=["Investigations"])
async def get_branch_turns(inv_id: str, branch_id: str, db: Session = Depends(get_app_db)):
    """Evidence panel for a branch: SQL, source, filters, result rows, chart."""
    branch = db.query(InvestigationBranch).filter(
        InvestigationBranch.id == branch_id, InvestigationBranch.investigation_id == inv_id
    ).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return {"branch": _serialize_branch(branch), "turns": _branch_turns(db, branch)}


@app.patch("/api/v1/investigations/{inv_id}/branches/{branch_id}", tags=["Investigations"])
async def update_branch(inv_id: str, branch_id: str, req: BranchUpdate, db: Session = Depends(get_app_db)):
    branch = db.query(InvestigationBranch).filter(
        InvestigationBranch.id == branch_id, InvestigationBranch.investigation_id == inv_id
    ).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    if req.title:
        branch.title = req.title[:300]
    if req.status in ("open", "archived"):
        branch.status = req.status
    db.commit()
    return _serialize_branch(branch)


@app.post("/api/v1/investigations/{inv_id}/branches/{branch_id}/conclusion", tags=["Investigations"])
async def save_branch_conclusion(inv_id: str, branch_id: str, req: BranchConclusion, db: Session = Depends(get_app_db)):
    branch = db.query(InvestigationBranch).filter(
        InvestigationBranch.id == branch_id, InvestigationBranch.investigation_id == inv_id
    ).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.conclusion = req.conclusion
    db.commit()
    return _serialize_branch(branch)


@app.post("/api/v1/investigations/{inv_id}/compare", tags=["Investigations"])
async def compare_branches(inv_id: str, req: CompareRequest, db: Session = Depends(get_app_db)):
    """Side-by-side comparison of the latest completed result per branch."""
    inv = db.query(Investigation).filter(Investigation.id == inv_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    comparison = []
    for bid in req.branch_ids:
        branch = db.query(InvestigationBranch).filter(
            InvestigationBranch.id == bid, InvestigationBranch.investigation_id == inv_id
        ).first()
        if not branch:
            continue
        turns = _branch_turns(db, branch)
        completed = [t for t in turns if t["status"] == "completed"]
        latest = completed[-1] if completed else (turns[-1] if turns else None)
        comparison.append({
            "branch_id": branch.id, "title": branch.title, "conclusion": branch.conclusion,
            "turn_count": len(turns),
            "latest": None if not latest else {
                "question": latest["question"], "sql": latest["sql"], "status": latest["status"],
                "row_count": latest["row_count"], "columns": latest["columns"], "rows": latest["rows"][:5],
            },
        })
    return {"investigation_id": inv_id, "compared": len(comparison), "branches": comparison}


@app.post("/api/v1/root-cause/runs", tags=["Root Cause"])
async def run_root_cause(req: RootCauseRequest, db: Session = Depends(get_app_db)):
    """Run a schema-adaptive decomposition for a finding; persist ranked
    contributions and (optionally) spawn follow-up branches."""
    if not req.finding_id:
        raise HTTPException(status_code=400, detail="finding_id is required")
    finding = db.query(DiscoveryFinding).filter(DiscoveryFinding.id == req.finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    role = req.role or finding.role or "executive"
    try:
        from app.services.root_cause_service import RootCauseService
        result = RootCauseService(role=role).analyze_finding(finding)
    except Exception as exc:
        logger.error("Root-cause run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Root-cause analysis failed: {str(exc)[:200]}")

    run = RootCauseRun(
        id=new_uuid(), investigation_id=req.investigation_id, finding_id=finding.id,
        metric_name=result.get("metric_name"), measure_expr=result.get("measure_expr"),
        dimension_label=result.get("dimension_label"), dimension_column=result.get("dimension_column"),
        baseline_period=result.get("baseline_period"), current_period=result.get("current_period"),
        baseline_total=result.get("baseline_total"), current_total=result.get("current_total"),
        total_change_abs=result.get("total_change_abs"), total_change_pct=result.get("total_change_pct"),
        reconciles=bool(result.get("reconciles")), contributions=result.get("contributions", []),
        evidence={**result.get("evidence", {}), "summary": result.get("summary")}, role=role,
    )
    db.add(run)
    spawned = []
    if req.investigation_id and req.spawn_branches and result.get("status") == "ok":
        inv = db.query(Investigation).filter(Investigation.id == req.investigation_id).first()
        if inv:
            root_branch = db.query(InvestigationBranch).filter(
                InvestigationBranch.investigation_id == inv.id, InvestigationBranch.parent_branch_id.is_(None)
            ).order_by(InvestigationBranch.created_at.asc()).first()
            for sb in result.get("suggested_branches", []):
                b = _new_branch(db, inv, title=sb["title"], question=sb["question"], origin="root_cause",
                                parent_branch_id=(root_branch.id if root_branch else None),
                                segment=sb.get("contributor_segment"), role=role)
                spawned.append(_serialize_branch(b))
    db.commit()
    _audit(db, "rootcause.run", "root_cause_run", run.id,
           {"finding_id": finding.id, "status": result.get("status"), "role": role})
    payload = _serialize_rcrun(run)
    payload["summary"] = result.get("summary")
    payload["suggested_branches"] = result.get("suggested_branches", [])
    payload["spawned_branches"] = spawned
    return payload


# ============================================================================
# FEATURE 2: WHAT-IF DECISION SIMULATOR
# ============================================================================


class ScenarioBaselineRequest(_DiscoveryBaseModel):
    role: Optional[str] = None
    period: Optional[str] = None
    finding_id: Optional[str] = None


class ScenarioSimulateRequest(_DiscoveryBaseModel):
    role: Optional[str] = None
    baseline: dict
    assumptions: dict
    name: Optional[str] = None


class ScenarioSave(_DiscoveryBaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    source: str = "manual"
    finding_id: Optional[str] = None
    baseline: dict
    assumptions: dict


class ScenarioRename(_DiscoveryBaseModel):
    name: str


class ScenarioCompare(_DiscoveryBaseModel):
    scenario_ids: _List[str]


class ScenarioToInvestigation(_DiscoveryBaseModel):
    investigation_id: str


def _scenario_summary(s: Scenario) -> dict:
    return {
        "id": s.id, "name": s.name, "role": s.role, "source": s.source,
        "finding_id": s.finding_id, "metric_key": s.metric_key, "metric_label": s.metric_label,
        "period_label": s.period_label, "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _scenario_full(s: Scenario) -> dict:
    d = _scenario_summary(s)
    d.update({"baseline": s.baseline or {}, "assumptions": s.assumptions or {},
              "results": s.results or {}})
    return d


@app.get("/api/v1/scenarios/capabilities", tags=["Scenarios"])
async def scenario_capabilities(role: str = Query(default="executive")):
    """Report which levers/views the connected schema actually supports, so the
    UI renders only real, data-backed controls (nothing hardcoded)."""
    from app.services.scenario_service import ScenarioService
    try:
        return ScenarioService(role=role).capabilities()
    except Exception as exc:
        logger.error("Scenario capabilities failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Capabilities probe failed: {str(exc)[:200]}")


@app.post("/api/v1/scenarios/baseline", tags=["Scenarios"])
async def scenario_baseline(req: ScenarioBaselineRequest):
    """Pull a real, role-authorized observed baseline from the live database."""
    from app.services.scenario_service import ScenarioService
    try:
        return ScenarioService(role=req.role or "executive").build_baseline(period=req.period)
    except Exception as exc:
        logger.error("Scenario baseline build failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Baseline build failed: {str(exc)[:200]}")


@app.post("/api/v1/scenarios/simulate", tags=["Scenarios"])
async def scenario_simulate(req: ScenarioSimulateRequest):
    """Deterministically recompute a scenario from an observed baseline + user
    assumptions. Not persisted: this is the live-preview math."""
    from app.services.scenario_service import ScenarioService
    res = ScenarioService(role=req.role or "executive").simulate(req.baseline, req.assumptions, req.name)
    if not res.get("ok"):
        raise HTTPException(status_code=422, detail=res.get("errors", ["invalid assumptions"]))
    return res


@app.post("/api/v1/scenarios", tags=["Scenarios"])
async def save_scenario(req: ScenarioSave, db: Session = Depends(get_app_db)):
    """Validate, compute and persist a scenario (baseline facts + assumptions +
    calculated results) for later comparison."""
    from app.services.scenario_service import ScenarioService
    svc = ScenarioService(role=req.role or "executive")
    res = svc.simulate(req.baseline, req.assumptions, req.name)
    if not res.get("ok"):
        raise HTTPException(status_code=422, detail=res.get("errors", ["invalid assumptions"]))
    s = Scenario(
        id=new_uuid(), name=(req.name or "Scenario")[:200], role=req.role or "executive",
        source=req.source, finding_id=req.finding_id,
        metric_key=((req.baseline or {}).get("source_metric") or {}).get("key"),
        metric_label=((req.baseline or {}).get("source_metric") or {}).get("label"),
        period_label=(req.baseline or {}).get("period_label"),
        baseline=req.baseline, assumptions=req.assumptions, results=res, status="saved",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    _audit(db, "scenario.saved", "scenario", s.id, {"assumptions": req.assumptions, "role": s.role})
    return _scenario_full(s)


@app.get("/api/v1/scenarios", tags=["Scenarios"])
async def list_scenarios(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_app_db)):
    items = db.query(Scenario).order_by(Scenario.updated_at.desc()).limit(limit).all()
    return {"count": len(items), "scenarios": [_scenario_summary(s) for s in items]}


@app.get("/api/v1/scenarios/{scenario_id}", tags=["Scenarios"])
async def get_scenario(scenario_id: str, db: Session = Depends(get_app_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _scenario_full(s)


@app.patch("/api/v1/scenarios/{scenario_id}", tags=["Scenarios"])
async def rename_scenario(scenario_id: str, req: ScenarioRename, db: Session = Depends(get_app_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    s.name = req.name[:200]
    db.commit()
    return _scenario_summary(s)


@app.post("/api/v1/scenarios/{scenario_id}/duplicate", tags=["Scenarios"])
async def duplicate_scenario(scenario_id: str, db: Session = Depends(get_app_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    dup = Scenario(
        id=new_uuid(), name=(s.name + " copy")[:200], role=s.role, source=s.source,
        finding_id=s.finding_id, metric_key=s.metric_key, metric_label=s.metric_label,
        period_label=s.period_label, baseline=s.baseline, assumptions=s.assumptions,
        results=s.results, status="draft",
    )
    db.add(dup)
    db.commit()
    db.refresh(dup)
    _audit(db, "scenario.duplicated", "scenario", dup.id, {"from": s.id})
    return _scenario_full(dup)


@app.delete("/api/v1/scenarios/{scenario_id}", tags=["Scenarios"])
async def delete_scenario(scenario_id: str, db: Session = Depends(get_app_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    db.delete(s)
    db.commit()
    _audit(db, "scenario.deleted", "scenario", scenario_id, {})
    return {"status": "deleted", "id": scenario_id}


@app.post("/api/v1/scenarios/compare", tags=["Scenarios"])
async def compare_scenarios(req: ScenarioCompare, db: Session = Depends(get_app_db)):
    """Side-by-side comparison of saved scenarios (net-revenue, margin, deltas)."""
    out = []
    for sid in req.scenario_ids:
        s = db.query(Scenario).filter(Scenario.id == sid).first()
        if not s:
            continue
        metrics = (s.results or {}).get("metrics", {})
        net = metrics.get("net_revenue") or {}
        margin = metrics.get("contribution_margin") or {}
        out.append({
            "id": s.id, "name": s.name, "assumptions": s.assumptions or {},
            "net_revenue": net,
            "contribution_margin": (margin or None),
            "calculated_at": (s.results or {}).get("computed_at"),
        })
    return {"compared": len(out), "scenarios": out}


@app.post("/api/v1/scenarios/{scenario_id}/send-to-investigation", tags=["Scenarios"])
async def scenario_to_investigation(scenario_id: str, req: ScenarioToInvestigation,
                                    db: Session = Depends(get_app_db)):
    """Open a scenario as a new investigation branch carrying its assumptions."""
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    inv = db.query(Investigation).filter(Investigation.id == req.investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    metrics = (s.results or {}).get("metrics", {})
    net = metrics.get("net_revenue") or {}
    assumptions_txt = ", ".join(f"{k}={v}" for k, v in (s.assumptions or {}).items()) or "no changes"
    question = (
        f"Validate this what-if on {s.metric_label or 'the baseline'} ({s.period_label or 'all periods'}): "
        f"assumptions [{assumptions_txt}] project net revenue "
        f"{'up' if net.get('delta_abs', 0) >= 0 else 'down'} {abs(net.get('delta_pct', 0)):.1f}% "
        f"(from {net.get('baseline')} to {net.get('scenario')}). Show the real per-segment detail "
        f"that would need to hold for this to be true."
    )
    root_branch = db.query(InvestigationBranch).filter(
        InvestigationBranch.investigation_id == inv.id, InvestigationBranch.parent_branch_id.is_(None)
    ).order_by(InvestigationBranch.created_at.asc()).first()
    branch = _new_branch(db, inv, title=f"Scenario: {s.name}"[:300], question=question, origin="manual",
                         parent_branch_id=(root_branch.id if root_branch else None), segment=None, role=s.role)
    db.commit()
    _audit(db, "scenario.sent_to_investigation", "scenario", s.id, {"investigation_id": inv.id, "branch_id": branch.id})
    return {"investigation_id": inv.id, "branch": _serialize_branch(branch)}


# ============================================================================
# FEATURE 4: PERSONALIZED EXECUTIVE BRIEFINGS
# ============================================================================

_briefing_thread = None
_briefing_stop = None


def _start_briefing_scheduler() -> None:
    """Background scheduler that generates role-scoped briefings on a cadence.
    Idempotent: the briefing signature prevents duplicate alerts per period."""
    global _briefing_thread, _briefing_stop
    settings = get_settings()
    if not (settings.briefings_enabled and settings.briefing_schedule_enabled):
        logger.info("Briefing scheduler disabled by configuration")
        return
    if _briefing_thread and _briefing_thread.is_alive():
        return
    import threading
    _briefing_stop = threading.Event()

    def _loop():
        if _briefing_stop.wait(settings.briefing_initial_delay_seconds):
            return
        while not _briefing_stop.is_set():
            try:
                from app.services.briefing_service import run_briefings_job
                run_briefings_job(cadence="daily", refresh=False)
            except Exception as exc:
                logger.error("Scheduled briefing job failed: %s", exc)
            if _briefing_stop.wait(settings.briefing_interval_minutes * 60):
                break

    _briefing_thread = threading.Thread(target=_loop, daemon=True, name="briefing-scheduler")
    _briefing_thread.start()
    logger.info("Briefing scheduler started (every %s min)", settings.briefing_interval_minutes)


class BriefingGenerateRequest(_DiscoveryBaseModel):
    username: Optional[str] = None
    cadence: str = "manual"
    refresh: bool = False


class BriefingPreferenceUpdate(_DiscoveryBaseModel):
    username: Optional[str] = None
    frequency: Optional[str] = None
    enabled_categories: Optional[_List[str]] = None


@app.get("/api/v1/briefings/inbox", tags=["Briefings"])
async def briefing_inbox(username: str = Query(default="executive"), limit: int = Query(default=30, ge=1, le=100),
                         db: Session = Depends(get_app_db)):
    """The recipient's in-app briefing inbox (role-scoped, newest first)."""
    from app.services.briefing_service import BriefingService
    return {"username": username, "briefings": BriefingService(db).inbox(username, limit=limit)}


@app.get("/api/v1/briefings/preferences", tags=["Briefings"])
async def get_briefing_preferences(username: str = Query(default="executive"), db: Session = Depends(get_app_db)):
    from app.services.briefing_service import BriefingService
    return BriefingService(db).preferences_for(username)


@app.put("/api/v1/briefings/preferences", tags=["Briefings"])
async def update_briefing_preferences(req: BriefingPreferenceUpdate, db: Session = Depends(get_app_db)):
    from app.services.briefing_service import BriefingService, DEFAULT_CATEGORIES
    uname = req.username or "executive"
    if req.frequency and req.frequency not in ("daily", "weekly", "disabled"):
        raise HTTPException(status_code=422, detail="frequency must be daily, weekly or disabled")
    if req.enabled_categories is not None:
        bad = [c for c in req.enabled_categories if c not in DEFAULT_CATEGORIES]
        if bad:
            raise HTTPException(status_code=422, detail=f"unknown categories: {bad}")
    pref = BriefingService(db).save_preference(uname, frequency=req.frequency, enabled_categories=req.enabled_categories)
    _audit(db, "briefing.preference_updated", "briefing_preference", uname, {"frequency": pref["frequency"], "categories": pref["enabled_categories"]})
    return pref


@app.post("/api/v1/briefings/generate", tags=["Briefings"])
async def generate_briefing(req: BriefingGenerateRequest, db: Session = Depends(get_app_db)):
    """Generate one role-scoped briefing now (the same path the scheduler uses)."""
    settings = get_settings()
    if not settings.briefings_enabled:
        raise HTTPException(status_code=403, detail="Briefings are disabled")
    from app.services.briefing_service import BriefingService
    uname = req.username or "executive"
    try:
        res = BriefingService(db).generate(uname, cadence=req.cadence, refresh=req.refresh)
    except Exception as exc:
        logger.error("Briefing generate failed: %s", exc, exc_info=True)
        _audit(db, "briefing.generate_failed", "briefing", uname, {"error": str(exc)[:200]})
        raise HTTPException(status_code=500, detail=f"Briefing generation failed: {str(exc)[:200]}")
    _audit(db, "briefing.generated", "briefing", res.get("briefing_id", ""),
           {"username": uname, "status": res.get("status"), "item_count": res.get("item_count")})
    return res


@app.get("/api/v1/briefings/{briefing_id}", tags=["Briefings"])
async def get_briefing(briefing_id: str, db: Session = Depends(get_app_db)):
    from app.services.briefing_service import BriefingService
    b = BriefingService(db).get(briefing_id)
    if not b:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return b


@app.post("/api/v1/briefings/{briefing_id}/status/{status}", tags=["Briefings"])
async def mark_briefing(briefing_id: str, status: str, db: Session = Depends(get_app_db)):
    from app.services.briefing_service import BriefingService
    if status not in ("delivered", "read"):
        raise HTTPException(status_code=422, detail="status must be delivered or read")
    b = BriefingService(db).mark(briefing_id, status)
    if not b:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return b


# ============================================================================
# FEATURE 5: CROSS-SYSTEM INTELLIGENCE ENDPOINTS
# ============================================================================

from pydantic import BaseModel as _CSBaseModel


class CrossSourceTableRef(_CSBaseModel):
    connection_id: str
    schema_name: str
    table_name: str


class CrossSourceCandidateQuery(_CSBaseModel):
    left: CrossSourceTableRef
    right: CrossSourceTableRef
    role: str = "executive"


class CrossSourceCandidateCreate(_CSBaseModel):
    left_connection_id: str
    left_schema: str
    left_table: str
    left_column: str
    right_connection_id: str
    right_schema: str
    right_table: str
    right_column: str
    confidence: float = 0.0
    evidence: dict | None = None
    created_by: str = "executive"


class CrossSourceConfirmRequest(_CSBaseModel):
    confirmed_by: str = "executive"


class CrossSourceJoinRequest(_CSBaseModel):
    mapping_id: str
    requestor: str = "executive"
    left_columns: list[str] = []
    right_columns: list[str] = []
    join_type: str = "inner"


def _cross_service(db: Session):
    from app.services.cross_source_service import CrossSourceService
    return CrossSourceService(db, get_schema_service(), get_query_executor())


@app.get("/api/v1/cross-source/sources", tags=["Cross-Source"])
async def cross_source_list_sources(db: Session = Depends(get_app_db)):
    """Admin-visible catalog of configured sources with independent health."""
    from app.services.cross_source_service import CrossSourceError
    try:
        return _cross_service(db).list_sources()
    except CrossSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/cross-source/sources/{connection_id}/catalog", tags=["Cross-Source"])
async def cross_source_catalog(connection_id: str, role: str = Query(default="executive"),
                               db: Session = Depends(get_app_db)):
    """Introspect one source independently, filtered by the role's authorization."""
    from app.services.cross_source_service import CrossSourceError
    try:
        return _cross_service(db).get_catalog(connection_id, role=role)
    except CrossSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/v1/cross-source/relationships/candidates", tags=["Cross-Source"])
async def cross_source_candidates(req: CrossSourceCandidateQuery,
                                  db: Session = Depends(get_app_db)):
    """Infer candidate join keys between two tables across sources."""
    from app.services.cross_source_service import CrossSourceService, TableRef, CrossSourceError
    try:
        svc = CrossSourceService(db, get_schema_service(), get_query_executor())
        return svc.find_candidates(
            TableRef(req.left.connection_id, req.left.schema_name, req.left.table_name),
            TableRef(req.right.connection_id, req.right.schema_name, req.right.table_name),
            role=req.role,
        )
    except CrossSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/cross-source/relationships", tags=["Cross-Source"])
async def cross_source_list_mappings(db: Session = Depends(get_app_db)):
    return {"mappings": _cross_service(db).list_mappings()}


@app.post("/api/v1/cross-source/relationships", tags=["Cross-Source"])
async def cross_source_save_candidate(req: CrossSourceCandidateCreate, db: Session = Depends(get_app_db)):
    from app.services.cross_source_service import CrossSourceError
    try:
        m = _cross_service(db).save_candidate(req.model_dump(), req.created_by)
    except CrossSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, "cross_source.candidate_saved", "cross_source_mapping", m["id"],
           {"left": m["left_column"], "right": m["right_column"], "confidence": m["confidence"]})
    return m


@app.post("/api/v1/cross-source/relationships/{mapping_id}/confirm", tags=["Cross-Source"])
async def cross_source_confirm(mapping_id: str, req: CrossSourceConfirmRequest, db: Session = Depends(get_app_db)):
    from app.services.cross_source_service import CrossSourceError
    try:
        m = _cross_service(db).confirm_mapping(mapping_id, req.confirmed_by)
    except CrossSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, "cross_source.mapping_confirmed", "cross_source_mapping", mapping_id,
           {"confirmed_by": req.confirmed_by})
    return m


@app.delete("/api/v1/cross-source/relationships/{mapping_id}", tags=["Cross-Source"])
async def cross_source_delete_mapping(mapping_id: str, db: Session = Depends(get_app_db)):
    from app.services.cross_source_service import CrossSourceError
    try:
        _cross_service(db).delete_mapping(mapping_id)
    except CrossSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _audit(db, "cross_source.mapping_deleted", "cross_source_mapping", mapping_id, {})
    return {"status": "deleted"}


@app.post("/api/v1/cross-source/join", tags=["Cross-Source"])
async def cross_source_join(req: CrossSourceJoinRequest, db: Session = Depends(get_app_db)):
    """Run a controlled, independently-authorized application-side join."""
    from app.services.cross_source_service import CrossSourceError
    if req.join_type not in ("inner", "left", "right", "full"):
        raise HTTPException(status_code=422, detail="join_type must be inner, left, right or full")
    try:
        res = _cross_service(db).run_join(
            req.mapping_id, req.requestor, req.left_columns, req.right_columns, req.join_type,
        )
    except CrossSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, "cross_source.join_executed", "cross_source_mapping", req.mapping_id,
           {"requestor": req.requestor, "ok": res.get("ok"), "rows": res.get("row_count")})
    return res


# ============================================================================
# QUERYPILOT CHAOS ARENA ENDPOINTS
# ============================================================================

from pydantic import BaseModel

class ChaosRunRequest(BaseModel):
    challenge_id: str
    question: Optional[str] = None
    sync: Optional[bool] = False


@app.get("/api/v1/chaos/challenges", tags=["Chaos Arena"])
async def get_chaos_challenges():
    """Discover available live adversarial challenges."""
    from app.services.chaos_arena_service import get_chaos_manager
    return get_chaos_manager().get_challenges()


@app.post("/api/v1/chaos/reset", tags=["Chaos Arena"])
async def reset_chaos_environment():
    """Safely reset and clone the isolated chaos_test sandbox environment."""
    from app.services.chaos_arena_service import get_chaos_manager
    res = get_chaos_manager().reset_isolated_environment()
    return res


@app.post("/api/v1/chaos/runs", tags=["Chaos Arena"])
async def create_chaos_run(req: ChaosRunRequest, background_tasks: BackgroundTasks):
    """Trigger a live 8-stage adversarial challenge run in the isolated sandbox."""
    from app.services.chaos_arena_service import get_chaos_manager
    manager = get_chaos_manager()

    if req.sync:
        result = manager.execute_challenge_run(req.challenge_id, req.question)
        return result
    else:
        # Launch execution in background thread
        def _bg_run():
            try:
                manager.execute_challenge_run(req.challenge_id, req.question)
            except Exception as e:
                logger.error("Background chaos run failed: %s", e)

        background_tasks.add_task(_bg_run)
        
        # Give it a moment to initialize the run record
        import asyncio
        await asyncio.sleep(0.15)
        runs = manager.list_runs(limit=1)
        if runs:
            return runs[0]
        return {"status": "running", "challenge_id": req.challenge_id}


@app.get("/api/v1/chaos/runs", tags=["Chaos Arena"])
async def list_chaos_runs(limit: int = 10):
    """List recent Chaos Arena challenge runs."""
    from app.services.chaos_arena_service import get_chaos_manager
    return get_chaos_manager().list_runs(limit=limit)


@app.get("/api/v1/chaos/runs/{run_id}", tags=["Chaos Arena"])
async def get_chaos_run_status(run_id: str):
    """Retrieve full run details, live timeline stages, and recovery evidence."""
    from app.services.chaos_arena_service import get_chaos_manager
    record = get_chaos_manager().get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Chaos run not found")
    return record


@app.post("/api/v1/chaos/runs/{run_id}/cancel", tags=["Chaos Arena"])
async def cancel_chaos_run(run_id: str):
    """Pause or cancel an active Chaos Arena run."""
    from app.services.chaos_arena_service import get_chaos_manager
    success = get_chaos_manager().cancel_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Run not found or already completed")
    return {"status": "cancelled", "run_id": run_id}


# ============================================================================
# HELPERS
# ============================================================================


def _audit(db: Session, event_type: str, resource_type: str, resource_id: str, details: dict):
    """Record an audit event."""
    try:
        event = AuditEvent(
            event_type=event_type,
            user_id="demo",
            resource_type=resource_type,
            resource_id=resource_id,
            action=event_type.split(".")[-1],
            details=details,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.warning("Failed to record audit event: %s", e)


def _run_evaluation(run_id: str, dataset_name: str, connection_id: str | None):
    """Execute evaluation benchmark (runs in background threadpool)."""
    from app.services.evaluation_runner import run_benchmark
    try:
        run_benchmark(run_id, dataset_name, connection_id)
    except Exception as e:
        logger.error("Evaluation run %s failed: %s", run_id, e)
        try:
            from app.database import get_app_session_factory
            factory = get_app_session_factory()
            session = factory()
            run = session.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(e)[:500]
                session.commit()
            session.close()
        except Exception:
            pass
