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
)
from app.services.llm_provider import LLMProvider
from app.services.schema_service import SchemaService
from app.services.sql_generator import SQLGenerator
from app.services.sql_safety import SQLPolicyEngine
from app.services.query_executor import QueryExecutor, ExecutionResult
from app.services.chart_service import select_chart_type
from app.services.explanation_service import ExplanationService
from app.services.role_service import resolve_user_context, UserSecurityContext
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
        encrypted_password=req.password,  # TODO: encrypt with Fernet
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
        engine = create_target_engine(
            host=conn.host,
            port=conn.port,
            dbname=conn.database_name,
            user=conn.username,
            password=conn.encrypted_password,
        )
        schema_name = conn.schema_name or "public"
    else:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_svc = get_schema_service()
    return schema_svc.discover_schema(engine, conn_id, schema_name)


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
            engine = create_target_engine(
                host=conn.host, port=conn.port, dbname=conn.database_name,
                user=conn.username, password=conn.encrypted_password,
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
