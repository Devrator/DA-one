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
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=5432)
    database_name = Column(String(200), nullable=False)
    username = Column(String(200), nullable=False)
    encrypted_password = Column(Text, nullable=False)  # Encrypted at rest
    schema_name = Column(String(200), default="public")
    is_active = Column(Boolean, default=True)
    owner_user = Column(String(200), nullable=False, default="demo")
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    test_status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

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
