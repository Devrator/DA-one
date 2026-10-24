"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str = "0.1.0"
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: dict
    inference: dict


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    db_type: str = Field(default="postgresql", pattern=r"^postgresql$")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(..., min_length=1, max_length=200)
    username: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1)
    schema_name: str = Field(default="public", max_length=200)

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Block cloud metadata endpoints and internal addresses."""
        blocked = ["169.254.169.254", "metadata.google", "metadata.aws", "100.100.100.200"]
        lower = v.lower().strip()
        for b in blocked:
            if b in lower:
                raise ValueError(f"Host address not permitted: {v}")
        return v


class ConnectionTest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(..., min_length=1, max_length=200)
    username: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=1)
    schema_name: str = Field(default="public")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        blocked = ["169.254.169.254", "metadata.google", "metadata.aws", "100.100.100.200"]
        lower = v.lower().strip()
        for b in blocked:
            if b in lower:
                raise ValueError(f"Host address not permitted: {v}")
        return v


class ConnectionResponse(BaseModel):
    id: str
    name: str
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    schema_name: str
    is_active: bool
    last_tested_at: Optional[datetime] = None
    test_status: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
    tables_found: int = 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ColumnInfo(BaseModel):
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_ref: Optional[str] = None
    description: Optional[str] = None


class TableInfo(BaseModel):
    schema_name: str
    table_name: str
    columns: list[ColumnInfo]
    row_count: Optional[int] = None
    description: Optional[str] = None


class SchemaResponse(BaseModel):
    connection_id: str
    tables: list[TableInfo]
    relationships: list[dict] = []


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    connection_id: str = "default"
    question: str = Field(..., min_length=3, max_length=2000)
    conversation_context: list[dict] = Field(default_factory=list)


class QueryStatus(BaseModel):
    id: str
    status: str
    natural_language_query: str
    generated_sql: Optional[str] = None
    validated_sql: Optional[str] = None
    error_message: Optional[str] = None
    error_category: Optional[str] = None
    result_row_count: Optional[int] = None
    result_truncated: bool = False
    execution_time_ms: Optional[float] = None
    total_time_ms: Optional[float] = None
    model_name: Optional[str] = None
    result_columns: Optional[list[str]] = None
    result_data: Optional[list[dict]] = None
    chart_spec: Optional[dict] = None
    explanation: Optional[str] = None
    assumptions: Optional[list[str]] = None
    query_plan: Optional[dict] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class QueryFeedback(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# Query History
# ---------------------------------------------------------------------------

class QueryHistoryItem(BaseModel):
    id: str
    question: str
    status: str
    execution_time_ms: Optional[float] = None
    result_row_count: Optional[int] = None
    model_name: Optional[str] = None
    created_at: datetime
    feedback_rating: Optional[int] = None


class QueryHistoryResponse(BaseModel):
    items: list[QueryHistoryItem]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

class EvaluationRunCreate(BaseModel):
    dataset_name: str = Field(default="clean_sales")
    connection_id: Optional[str] = None


class EvaluationRunResponse(BaseModel):
    id: str
    dataset_name: str
    model_name: str
    status: str
    total_cases: int
    successful_executions: int
    correct_results: int
    unsafe_rejected: int
    clarification_correct: int
    repair_successes: int
    median_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    config: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class EvaluationResultResponse(BaseModel):
    id: str
    question: str
    expected_behavior: str
    expected_sql: Optional[str] = None
    generated_sql: Optional[str] = None
    execution_success: Optional[bool] = None
    result_correct: Optional[bool] = None
    policy_outcome: Optional[str] = None
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    difficulty: Optional[str] = None
    category: Optional[str] = None

    model_config = {"from_attributes": True}


class EvaluationRunDetailResponse(EvaluationRunResponse):
    results: list[EvaluationResultResponse] = []



# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    user_id: Optional[str] = None
    resource_type: Optional[str] = None
    action: str
    details: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
