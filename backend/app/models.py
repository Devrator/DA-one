"""SQLAlchemy models for application persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, String, Integer, Text, Boolean, DateTime, Float,
    JSON, Enum as SAEnum, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Connection(Base):
    """Registered database connection / data source."""
    __tablename__ = "connections"

    id = Column(String(36), primary_key=True, default=new_uuid)
    name = Column(String(200), nullable=False)
    db_type = Column(String(50), nullable=False, default="postgresql")
    connector_type = Column(String(30), nullable=False, default="postgresql")  # postgresql | sap_s4hana
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=5432)
    database_name = Column(String(200), nullable=False)
    username = Column(String(200), nullable=False)
    encrypted_password = Column(Text, nullable=False)  # Encrypted at rest (Fernet envelope)
    schema_name = Column(String(200), default="public")
    is_active = Column(Boolean, default=True)
    owner_user = Column(String(200), nullable=False, default="demo")
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    test_status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # --- SAP S/4HANA connector metadata (nullable for non-SAP sources) ---
    deployment_type = Column(String(30), nullable=True)   # public_cloud | private_cloud | on_premises | hybrid
    base_url = Column(String(500), nullable=True)          # approved SAP host root
    service_path = Column(String(500), nullable=True)      # OData service document path
    odata_version = Column(String(5), nullable=True)       # 2 | 4
    auth_mode = Column(String(30), nullable=True)          # basic | oauth_client_credentials | mtls
    secret_ref = Column(String(300), nullable=True)        # non-secret reference/label for admins
    tls_verify = Column(Boolean, default=True)
    lifecycle_status = Column(String(20), default="configured")  # configured/testing/connected/degraded/disconnected/disabled
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, nullable=True)            # cached discovered services/entities
    metadata_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(String(200), nullable=True)

    queries = relationship("QueryRecord", back_populates="connection")


class QueryRecord(Base):
    """Persisted record of a natural-language query execution."""
    __tablename__ = "query_records"

    id = Column(String(36), primary_key=True, default=new_uuid)
    connection_id = Column(String(36), ForeignKey("connections.id"), nullable=True)
    user_id = Column(String(200), nullable=False, default="demo")
    user_role = Column(String(50), nullable=True, default="executive")
    session_id = Column(String(100), nullable=True)
    natural_language_query = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    validated_sql = Column(Text, nullable=True)
    status = Column(
        String(30), nullable=False, default="pending"
    )  # pending, planning, generating, validating, executing, verifying, completed, failed, blocked
    error_message = Column(Text, nullable=True)
    error_category = Column(String(100), nullable=True)

    # Execution metadata
    result_row_count = Column(Integer, nullable=True)
    result_truncated = Column(Boolean, default=False)
    execution_time_ms = Column(Float, nullable=True)
    total_time_ms = Column(Float, nullable=True)
    model_name = Column(String(200), nullable=True)
    model_version = Column(String(100), nullable=True)

    # Result data (stored as JSON for history replay)
    result_columns = Column(JSON, nullable=True)
    result_data = Column(JSON, nullable=True)
    chart_spec = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    assumptions = Column(JSON, nullable=True)
    query_plan = Column(JSON, nullable=True)

    # Anti-hallucination evidence provenance (grounding + verification results)
    evidence = Column(JSON, nullable=True)

    # Feedback
    feedback_rating = Column(Integer, nullable=True)  # 1-5
    feedback_comment = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    connection = relationship("Connection", back_populates="queries")

    __table_args__ = (
        Index("idx_query_records_user", "user_id"),
        Index("idx_query_records_created", "created_at"),
        Index("idx_query_records_status", "status"),
    )


class EvaluationRun(Base):
    """Record of a benchmark evaluation run."""
    __tablename__ = "evaluation_runs"

    id = Column(String(36), primary_key=True, default=new_uuid)
    dataset_name = Column(String(200), nullable=False)
    model_name = Column(String(200), nullable=False)
    model_version = Column(String(100), nullable=True)
    status = Column(String(30), default="running")  # running, completed, failed
    total_cases = Column(Integer, default=0)
    successful_executions = Column(Integer, default=0)
    correct_results = Column(Integer, default=0)
    unsafe_rejected = Column(Integer, default=0)
    clarification_correct = Column(Integer, default=0)
    repair_successes = Column(Integer, default=0)
    median_latency_ms = Column(Float, nullable=True)
    p95_latency_ms = Column(Float, nullable=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    config = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    results = relationship("EvaluationResult", back_populates="run")


class EvaluationResult(Base):
    """Individual test case result within an evaluation run."""
    __tablename__ = "evaluation_results"

    id = Column(String(36), primary_key=True, default=new_uuid)
    run_id = Column(String(36), ForeignKey("evaluation_runs.id"), nullable=False)
    question = Column(Text, nullable=False)
    expected_behavior = Column(String(50), nullable=False)  # success, clarification, reject, empty
    expected_sql = Column(Text, nullable=True)
    generated_sql = Column(Text, nullable=True)
    execution_success = Column(Boolean, nullable=True)
    result_correct = Column(Boolean, nullable=True)
    policy_outcome = Column(String(50), nullable=True)
    latency_ms = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    difficulty = Column(String(50), nullable=True)
    category = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    run = relationship("EvaluationRun", back_populates="results")

    __table_args__ = (
        Index("idx_eval_results_run", "run_id"),
    )


class AuditEvent(Base):
    """Audit log entry."""
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=new_uuid)
    event_type = Column(String(100), nullable=False)
    user_id = Column(String(200), nullable=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(36), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_audit_events_type", "event_type"),
        Index("idx_audit_events_created", "created_at"),
    )


class BusinessGlossary(Base):
    """Semantic layer: business-friendly definitions for database objects."""
    __tablename__ = "business_glossary"

    id = Column(String(36), primary_key=True, default=new_uuid)
    connection_id = Column(String(36), ForeignKey("connections.id"), nullable=True)
    term = Column(String(200), nullable=False)
    definition = Column(Text, nullable=False)
    sql_expression = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)  # metric, dimension, filter, etc.
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConversationSession(Base):
    """Multi-turn conversation session tracking semantic state."""
    __tablename__ = "conversation_sessions"

    id = Column(String(36), primary_key=True, default=new_uuid)
    user_id = Column(String(200), nullable=False, default="demo")
    user_role = Column(String(50), nullable=False, default="executive")
    title = Column(String(200), nullable=True)
    turns = Column(JSON, default=list)  # list of {turn_number, question, sql, result_summary, active_filters, metric}
    active_metric = Column(String(100), nullable=True)
    active_grouping = Column(String(100), nullable=True)
    active_filters = Column(JSON, default=dict)
    last_sql = Column(Text, nullable=True)
    turn_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_conversation_user", "user_id"),
        Index("idx_conversation_updated", "updated_at"),
    )


class DiscoveryRun(Base):
    """A single proactive discovery job execution over the live target schema."""
    __tablename__ = "discovery_runs"

    id = Column(String(36), primary_key=True, default=new_uuid)
    status = Column(String(30), nullable=False, default="running")  # running, completed, failed
    trigger = Column(String(30), nullable=False, default="manual")  # manual, scheduled
    role = Column(String(50), nullable=False, default="executive")
    schema_name = Column(String(200), nullable=True)
    metrics_analyzed = Column(Integer, default=0)
    dimensions_analyzed = Column(Integer, default=0)
    findings_new = Column(Integer, default=0)
    findings_deduped = Column(Integer, default=0)
    findings_total = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    detail = Column(JSON, nullable=True)  # introspected schema profile + detector diagnostics

    findings = relationship("DiscoveryFinding", back_populates="run")

    __table_args__ = (
        Index("idx_discovery_run_status", "status"),
        Index("idx_discovery_run_started", "started_at"),
    )


class DiscoveryFinding(Base):
    """An evidence-backed proactive insight derived from real executed read-only queries."""
    __tablename__ = "discovery_findings"

    id = Column(String(36), primary_key=True, default=new_uuid)
    run_id = Column(String(36), ForeignKey("discovery_runs.id"), nullable=True)
    signature = Column(String(64), nullable=False)  # stable hash for dedup across runs
    severity = Column(String(20), nullable=False, default="info")  # info, watch, warning, critical
    score = Column(Float, nullable=False, default=0.0)  # ranking strength
    finding_type = Column(String(40), nullable=False)  # trend, anomaly, concentration, underperformer, opportunity
    title = Column(String(300), nullable=False)
    narrative = Column(Text, nullable=True)  # observed facts (what changed + by how much)
    hypothesis = Column(Text, nullable=True)  # clearly separated 'why it might matter'
    suggested_next_steps = Column(Text, nullable=True)

    metric_name = Column(String(100), nullable=True)
    dimension_name = Column(String(100), nullable=True)
    segment = Column(String(200), nullable=True)
    baseline_value = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    delta_abs = Column(Float, nullable=True)
    delta_pct = Column(Float, nullable=True)
    comparison_label = Column(String(200), nullable=True)  # e.g. 'Aug 2026 vs prior 8-mo mean'
    period_label = Column(String(120), nullable=True)

    source_tables = Column(JSON, default=list)
    calculation = Column(JSON, default=dict)   # measure expr, filters, group-by
    supporting_data = Column(JSON, default=list)  # rows for chart / drill-down
    chart_spec = Column(JSON, default=dict)
    assumptions = Column(JSON, default=list)
    limitations = Column(JSON, default=list)
    explore_question = Column(Text, nullable=True)  # prefill for chat 'Explore Further'

    data_freshness_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(String(50), nullable=False, default="executive")

    status = Column(String(20), nullable=False, default="new")  # new, dismissed, saved
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    run = relationship("DiscoveryRun", back_populates="findings")

    __table_args__ = (
        Index("idx_discovery_finding_sig", "signature"),
        Index("idx_discovery_finding_status", "status"),
        Index("idx_discovery_finding_created", "created_at"),
    )


# ===========================================================================
# FEATURE 1 + 3: Multi-Thread Investigation Workspace + Root-Cause Engine
# ===========================================================================

class Investigation(Base):
    """An investigation opened from a Discover finding (or free-form).

    Holds a tree of parallel branches, each with its own conversational
    context (via a linked ``ConversationSession``), executions and evidence.
    """
    __tablename__ = "investigations"

    id = Column(String(36), primary_key=True, default=new_uuid)
    finding_id = Column(String(36), ForeignKey("discovery_findings.id"), nullable=True)
    title = Column(String(300), nullable=False)
    root_question = Column(Text, nullable=True)
    narrative = Column(Text, nullable=True)  # snapshot of the originating finding facts
    role = Column(String(50), nullable=False, default="executive")
    status = Column(String(20), nullable=False, default="open")  # open, archived
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    branches = relationship(
        "InvestigationBranch",
        back_populates="investigation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_investigation_status", "status"),
        Index("idx_investigation_created", "created_at"),
    )


class InvestigationBranch(Base):
    """A single hypothesis/line of enquiry inside an investigation.

    Branches are connected via ``parent_branch_id`` to form a tree and are kept
    independent: each owns its own ``session_id`` (multi-turn context) so a
    follow-up in one branch never pollutes another.
    """
    __tablename__ = "investigation_branches"

    id = Column(String(36), primary_key=True, default=new_uuid)
    investigation_id = Column(String(36), ForeignKey("investigations.id"), nullable=False)
    parent_branch_id = Column(String(36), ForeignKey("investigation_branches.id"), nullable=True)
    title = Column(String(300), nullable=False)
    seed_question = Column(Text, nullable=True)  # opening question of this branch
    session_id = Column(String(36), nullable=True)  # linked ConversationSession.id (own context)
    origin = Column(String(30), nullable=False, default="manual")  # manual, root_cause, finding
    contributor_segment = Column(String(200), nullable=True)  # when spawned by root-cause
    status = Column(String(20), nullable=False, default="open")  # open, archived
    conclusion = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    investigation = relationship("Investigation", back_populates="branches")

    __table_args__ = (
        Index("idx_branch_investigation", "investigation_id"),
        Index("idx_branch_parent", "parent_branch_id"),
    )


class RootCauseRun(Base):
    """A schema-adaptive decomposition of a detected change into ranked,
    measurable segment contributions. Records reproducible evidence and keeps
    measured contributions distinct from possible explanations (no causation)."""
    __tablename__ = "root_cause_runs"

    id = Column(String(36), primary_key=True, default=new_uuid)
    investigation_id = Column(String(36), ForeignKey("investigations.id"), nullable=True)
    finding_id = Column(String(36), ForeignKey("discovery_findings.id"), nullable=True)
    metric_name = Column(String(120), nullable=True)
    measure_expr = Column(Text, nullable=True)
    dimension_label = Column(String(120), nullable=True)
    dimension_column = Column(String(200), nullable=True)
    baseline_period = Column(String(60), nullable=True)
    current_period = Column(String(60), nullable=True)
    baseline_total = Column(Float, nullable=True)
    current_total = Column(Float, nullable=True)
    total_change_abs = Column(Float, nullable=True)
    total_change_pct = Column(Float, nullable=True)
    reconciles = Column(Boolean, default=False)  # contributions sum ~ total change
    contributions = Column(JSON, default=list)  # ranked segment contributions
    evidence = Column(JSON, default=dict)  # sql, tables, filters, sample size, limitations
    role = Column(String(50), nullable=False, default="executive")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_rootcause_finding", "finding_id"),
        Index("idx_rootcause_investigation", "investigation_id"),
    )


# ===========================================================================
# FEATURE 2: WHAT-IF DECISION SIMULATOR
# ===========================================================================

class Scenario(Base):
    """A deterministic what-if scenario built on a real observed baseline.

    ``baseline``   : observed component values pulled from the live,
                     role-authorized database (units, avg unit price, realized
                     discount factor, optional per-unit cost, source metric,
                     period, executed SQL and tables). These are FACTS.
    ``assumptions``: user-supplied lever values (volume/price/discount/cost
                     deltas). These are ASSUMPTIONS, never observed data.
    ``results``    : the scenario outcome deterministically recomputed from
                     baseline + assumptions, with the exact formula strings,
                     units, absolute/percent deltas and a calculated-at
                     timestamp. Never presented as a guaranteed forecast.
    """
    __tablename__ = "scenarios"

    id = Column(String(36), primary_key=True, default=new_uuid)
    name = Column(String(200), nullable=False, default="Untitled scenario")
    role = Column(String(50), nullable=False, default="executive")
    source = Column(String(30), nullable=False, default="manual")  # manual, finding, workspace
    finding_id = Column(String(36), ForeignKey("discovery_findings.id"), nullable=True)
    metric_key = Column(String(60), nullable=True)     # which detected measure forms the baseline
    metric_label = Column(String(120), nullable=True)
    period_label = Column(String(80), nullable=True)
    baseline = Column(JSON, default=dict)              # observed facts
    assumptions = Column(JSON, default=dict)           # user-supplied levers
    results = Column(JSON, default=dict)               # calculated scenario + formulas + deltas
    status = Column(String(20), nullable=False, default="draft")  # draft, saved
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_scenario_finding", "finding_id"),
        Index("idx_scenario_status", "status"),
        Index("idx_scenario_created", "created_at"),
    )


# ===========================================================================
# FEATURE 4: PERSONALIZED EXECUTIVE BRIEFINGS
# ===========================================================================

class Briefing(Base):
    """A scheduled, role-scoped briefing digest for one recipient.

    Generated ONLY from findings the recipient's own authorization scope can
    see (never an executive digest forwarded to a restricted user). ``items``
    is a ranked, de-duplicated list referencing persisted Discover findings
    plus a link to open each in an investigation. ``signature`` dedups repeated
    generation for the same recipient + period + finding set.
    """
    __tablename__ = "briefings"

    id = Column(String(36), primary_key=True, default=new_uuid)
    signature = Column(String(64), nullable=True)          # dedup key
    recipient_username = Column(String(80), nullable=False)
    recipient_role = Column(String(50), nullable=False)
    cadence = Column(String(20), nullable=False, default="daily")  # daily, weekly, manual
    period_label = Column(String(80), nullable=True)
    subject = Column(String(300), nullable=True)
    summary = Column(Text, nullable=True)                   # concise headline
    items = Column(JSON, default=list)                      # ranked finding refs
    item_count = Column(Integer, default=0)
    suppressed_count = Column(Integer, default=0)          # duplicates/stale/dismissed/low-value hidden
    source_data_freshness_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="generated")  # generated, empty, delivered, read, failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    generated_at = Column(DateTime(timezone=True), default=utcnow)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_briefing_recipient", "recipient_username"),
        Index("idx_briefing_status", "status"),
        Index("idx_briefing_sig", "signature"),
        Index("idx_briefing_generated", "generated_at"),
    )


class BriefingPreference(Base):
    """Per-user briefing cadence + enabled insight categories."""
    __tablename__ = "briefing_preferences"

    id = Column(String(36), primary_key=True, default=new_uuid)
    username = Column(String(80), nullable=False, unique=True)
    role = Column(String(50), nullable=False, default="executive")
    frequency = Column(String(20), nullable=False, default="daily")  # daily, weekly, disabled
    enabled_categories = Column(JSON, default=list)                 # finding_type keys the user wants
    delivery_channel = Column(String(30), nullable=False, default="in_app")
    last_generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ===========================================================================
# FEATURE 5: CROSS-SYSTEM INTELLIGENCE
# ===========================================================================

class CrossSourceMapping(Base):
    """A relationship between a column in one source and a column in another.

    Candidate mappings are inferred from compatible names/types/key hints and
    start in ``status='candidate'`` (never auto-joined). A user must explicitly
    confirm a mapping (``status='confirmed'``) before it is used to join bounded,
    independently-authorized result sets. Sources are referenced by connection
    id ('default' for the primary target, otherwise a Connection row).
    """
    __tablename__ = "cross_source_mappings"

    id = Column(String(36), primary_key=True, default=new_uuid)
    left_connection_id = Column(String(36), nullable=False)
    left_schema = Column(String(120), nullable=False)
    left_table = Column(String(200), nullable=False)
    left_column = Column(String(200), nullable=False)
    right_connection_id = Column(String(36), nullable=False)
    right_schema = Column(String(120), nullable=False)
    right_table = Column(String(200), nullable=False)
    right_column = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="candidate")  # candidate, confirmed
    confidence = Column(Float, nullable=False, default=0.0)
    evidence = Column(JSON, default=dict)      # why the candidate was proposed
    created_by = Column(String(80), nullable=False, default="executive")
    confirmed_by = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_csm_left", "left_connection_id", "left_table"),
        Index("idx_csm_right", "right_connection_id", "right_table"),
        Index("idx_csm_status", "status"),
    )
