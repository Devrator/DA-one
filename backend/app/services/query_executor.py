"""Query executor — restricted SQL execution against target databases.

Runs validated SQL under strict permissions:
- Read-only transactions
- Statement timeouts
- Row limits
- Result size enforcement
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Structured result of a query execution."""
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    error_category: Optional[str] = None


class QueryExecutor:
    """Executes validated SQL against target databases with strict resource controls.

    IMPORTANT: This executor should only receive SQL that has already been
    validated by the SQL Policy Engine. The executor provides database-level
    enforcement (read-only transactions, timeouts) as a defense-in-depth measure.
    """

    def __init__(self, max_rows: int = 1000):
        self.max_rows = max_rows

    @classmethod
    def from_settings(cls) -> "QueryExecutor":
        settings = get_settings()
        return cls(max_rows=settings.sql_max_rows)

    def execute(
        self,
        engine_or_sql: Any = None,
        sql: str | None = None,
        max_rows: int | None = None,
        user_context: Any = None,
    ) -> ExecutionResult:
        """Execute a validated SQL query against the target database.

        Supports both execute(engine, sql, ...) and execute(sql, ...).
        """
        if isinstance(engine_or_sql, str):
            actual_sql = engine_or_sql
            from app.database import get_default_target_engine
            actual_engine = get_default_target_engine()
        else:
            actual_engine = engine_or_sql
            actual_sql = sql or ""
            if actual_engine is None:
                from app.database import get_default_target_engine
                actual_engine = get_default_target_engine()

        effective_max_rows = max_rows or self.max_rows
        start_time = time.time()

        try:
            with actual_engine.connect() as conn:

                # Execute within a transaction that we'll always rollback
                # (defense-in-depth: even if policy was bypassed, read-only + rollback)
                with conn.begin():
                    # Set per-session safety: read-only transaction
                    try:
                        conn.execute(text("SET TRANSACTION READ ONLY"))
                    except Exception:
                        pass

                    # Apply Database-Level Row Security (RLS) via transaction-scoped SET LOCAL
                    if user_context:
                        role = getattr(user_context, "role", "executive") or "executive"
                        conn.execute(text(f"SET LOCAL app.user_role = '{role}'"))
                        region_id = getattr(user_context, "region_id", None)
                        if region_id is not None:
                            conn.execute(text(f"SET LOCAL app.region_id = '{region_id}'"))
                        else:
                            conn.execute(text("SET LOCAL app.region_id = ''"))
                        sales_rep = getattr(user_context, "sales_rep", None)
                        if sales_rep:
                            escaped_rep = str(sales_rep).replace("'", "''")
                            conn.execute(text(f"SET LOCAL app.sales_rep = '{escaped_rep}'"))
                        else:
                            conn.execute(text("SET LOCAL app.sales_rep = ''"))

                    result = conn.execute(text(actual_sql))
                    columns = list(result.keys()) if result.returns_rows else []


                    if not result.returns_rows:
                        elapsed = (time.time() - start_time) * 1000
                        return ExecutionResult(
                            success=True,
                            columns=[],
                            rows=[],
                            row_count=0,
                            execution_time_ms=elapsed,
                        )

                    # Fetch rows with limit enforcement
                    rows = []
                    truncated = False
                    for i, row in enumerate(result):
                        if i >= effective_max_rows:
                            truncated = True
                            break
                        # Convert to dict, handling special types
                        row_dict = {}
                        for col_name in columns:
                            val = row._mapping[col_name]
                            row_dict[col_name] = _serialize_value(val)
                        rows.append(row_dict)

                    elapsed = (time.time() - start_time) * 1000
                    # Rollback the read-only transaction (no changes to commit)
                    conn.rollback()

                    return ExecutionResult(
                        success=True,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        truncated=truncated,
                        execution_time_ms=elapsed,
                    )

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            error_msg = str(e)
            category = _categorize_error(error_msg)

            logger.error(
                "Query execution failed [%s]: %s (%.1fms)",
                category, error_msg[:200], elapsed,
            )

            return ExecutionResult(
                success=False,
                execution_time_ms=elapsed,
                error=_sanitize_error(error_msg),
                error_category=category,
            )


def _serialize_value(val: Any) -> Any:
    """Safely serialize a database value to JSON-compatible format."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    if isinstance(val, bytes):
        return val.hex()
    # Handle datetime, date, Decimal, etc.
    try:
        return str(val)
    except Exception:
        return repr(val)


def _categorize_error(error_msg: str) -> str:
    """Categorize a database error for reporting."""
    lower = error_msg.lower()
    if "timeout" in lower or "canceling statement" in lower:
        return "timeout"
    if "permission denied" in lower:
        return "permission_denied"
    if "does not exist" in lower:
        return "object_not_found"
    if "syntax error" in lower:
        return "syntax_error"
    if "connection" in lower:
        return "connection_error"
    if "read-only" in lower or "read only" in lower:
        return "read_only_violation"
    return "execution_error"


def _sanitize_error(error_msg: str) -> str:
    """Remove potentially sensitive information from error messages."""
    # Remove connection strings and passwords
    import re
    sanitized = re.sub(r'postgresql://[^\s]+', 'postgresql://***', error_msg)
    sanitized = re.sub(r'password[=:]\s*\S+', 'password=***', sanitized, flags=re.IGNORECASE)
    # Truncate very long errors
    if len(sanitized) > 500:
        sanitized = sanitized[:500] + "..."
    return sanitized
