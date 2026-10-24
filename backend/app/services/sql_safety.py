"""SQL Safety Engine — Critical security boundary.

Parses, validates, and enforces policy on generated SQL before execution.
Uses SQLGlot for AST-based inspection combined with database-enforced permissions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PolicyResult:
    """Result of SQL policy validation."""
    allowed: bool
    sql: str
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables_accessed: list[str] = field(default_factory=list)
    has_limit: bool = False
    modified_sql: Optional[str] = None  # SQL after adding LIMIT if needed


# Prohibited SQL statement types (anything non-SELECT)
PROHIBITED_STATEMENT_TYPES = {
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Grant, exp.Command,
}

# Prohibited function names (side-effecting or dangerous)
PROHIBITED_FUNCTIONS = {
    "pg_sleep", "pg_terminate_backend", "pg_cancel_backend",
    "pg_reload_conf", "pg_rotate_logfile",
    "set_config", "current_setting",
    "lo_import", "lo_export", "lo_unlink",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "pg_stat_file",
    "dblink", "dblink_exec", "dblink_connect",
    "copy", "pg_copy_to", "pg_copy_from",
}

# Prohibited schemas
PROHIBITED_SCHEMAS = {
    "pg_catalog", "information_schema", "pg_toast",
}


class SQLPolicyEngine:
    """Validates SQL against security policies before execution.

    This is a critical security boundary. It must:
    1. Parse the SQL into an AST (reject unparseable SQL)
    2. Verify only SELECT statements
    3. Reject prohibited operations, functions, schemas
    4. Enforce table/schema allowlists
    5. Add LIMIT if missing
    6. Reject multiple statements
    """

    def __init__(
        self,
        allowed_schemas: set[str] | None = None,
        allowed_tables: set[str] | None = None,
        max_rows: int = 1000,
        max_query_length: int = 4096,
        dialect: str = "postgres",
    ):
        self.allowed_schemas = allowed_schemas or {"sales", "public"}
        self.allowed_tables = allowed_tables  # None = all tables in allowed schemas
        self.max_rows = max_rows
        self.max_query_length = max_query_length
        self.dialect = dialect

    @classmethod
    def from_settings(cls, allowed_schemas: set[str] | None = None) -> "SQLPolicyEngine":
        settings = get_settings()
        return cls(
            allowed_schemas=allowed_schemas or {"sales", "public"},
            max_rows=settings.sql_max_rows,
            max_query_length=settings.sql_max_query_length,
        )

    def validate(self, sql: str) -> PolicyResult:
        """Validate SQL against all security policies.

        Args:
            sql: The SQL string to validate.

        Returns:
            PolicyResult with allow/deny decision and details.
        """
        violations: list[str] = []
        warnings: list[str] = []
        tables_accessed: list[str] = []

        # 1. Length check
        if len(sql) > self.max_query_length:
            return PolicyResult(
                allowed=False,
                sql=sql,
                violations=[f"Query exceeds maximum length ({len(sql)} > {self.max_query_length})"],
            )

        # 2. Quick text-level checks for obvious attacks
        sql_stripped = sql.strip().rstrip(";")
        if not sql_stripped:
            return PolicyResult(allowed=False, sql=sql, violations=["Empty query"])

        # 3. Reject multiple statements (semicolon-separated)
        # We strip one trailing semicolon then check for more
        if ";" in sql_stripped:
            return PolicyResult(
                allowed=False,
                sql=sql,
                violations=["Multiple SQL statements are not permitted"],
            )

        # 4. Parse the SQL into an AST
        try:
            parsed = sqlglot.parse(sql_stripped, dialect=self.dialect)
        except ParseError as e:
            return PolicyResult(
                allowed=False,
                sql=sql,
                violations=[f"SQL parsing failed: {str(e)}"],
            )

        if not parsed:
            return PolicyResult(allowed=False, sql=sql, violations=["SQL parsing produced no result"])

        if len(parsed) > 1:
            return PolicyResult(
                allowed=False,
                sql=sql,
                violations=["Multiple SQL statements are not permitted"],
            )

        statement = parsed[0]

        # 5. Verify it's a SELECT statement (including WITH/CTE)
        if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            # Check for CTE (WITH ... SELECT)
            if isinstance(statement, exp.CTE):
                pass  # CTEs are allowed if they contain SELECTs
            else:
                stmt_type = type(statement).__name__
                return PolicyResult(
                    allowed=False,
                    sql=sql,
                    violations=[f"Only SELECT queries are permitted (found: {stmt_type})"],
                )

        # 6. Check for prohibited statement types nested anywhere
        for node in statement.walk():
            if type(node) in PROHIBITED_STATEMENT_TYPES:
                violations.append(f"Prohibited operation: {type(node).__name__}")

        # 7. Check for prohibited functions
        for func in statement.find_all(exp.Anonymous, exp.Func):
            func_name = ""
            if isinstance(func, exp.Anonymous):
                func_name = func.name.lower() if func.name else ""
            elif hasattr(func, "sql_name"):
                func_name = func.sql_name().lower()
            elif hasattr(func, "key"):
                func_name = func.key.lower()

            if func_name in PROHIBITED_FUNCTIONS:
                violations.append(f"Prohibited function: {func_name}")

        # 8. Extract and validate tables accessed
        for table in statement.find_all(exp.Table):
            table_name = table.name
            schema_name = table.db if table.db else None

            # If table has catalog.schema.table, db is schema
            if not schema_name and table.catalog:
                schema_name = table.catalog

            full_name = f"{schema_name}.{table_name}" if schema_name else table_name
            tables_accessed.append(full_name)

            # Check schema allowlist
            if schema_name and schema_name.lower() in PROHIBITED_SCHEMAS:
                violations.append(f"Access to schema '{schema_name}' is not permitted")
            elif schema_name and schema_name.lower() not in {s.lower() for s in self.allowed_schemas}:
                violations.append(f"Schema '{schema_name}' is not in the allowed schemas: {self.allowed_schemas}")

            # Check table allowlist if specified
            if self.allowed_tables is not None:
                if full_name.lower() not in {t.lower() for t in self.allowed_tables}:
                    violations.append(f"Table '{full_name}' is not in the allowed tables")

        # 9. Check for subqueries with prohibited operations
        for subquery in statement.find_all(exp.Subquery):
            for node in subquery.walk():
                if type(node) in PROHIBITED_STATEMENT_TYPES:
                    violations.append(f"Prohibited operation in subquery: {type(node).__name__}")

        # 10. Check for LIMIT and add if missing
        has_limit = statement.find(exp.Limit) is not None
        modified_sql = sql_stripped

        if not has_limit:
            warnings.append(f"No LIMIT clause found; adding LIMIT {self.max_rows}")
            try:
                limited = statement.copy()
                limited = limited.limit(self.max_rows)
                modified_sql = limited.sql(dialect=self.dialect)
            except Exception:
                # Fallback: append LIMIT textually
                modified_sql = f"{sql_stripped}\nLIMIT {self.max_rows}"
        else:
            # Verify existing LIMIT isn't too large
            limit_node = statement.find(exp.Limit)
            if limit_node and limit_node.expression:
                try:
                    limit_val = int(limit_node.expression.this) if hasattr(limit_node.expression, 'this') else None
                    if limit_val is None:
                        limit_val = int(str(limit_node.expression))
                    if limit_val > self.max_rows:
                        warnings.append(f"LIMIT {limit_val} exceeds maximum ({self.max_rows}); capping")
                        try:
                            capped = statement.copy()
                            # Remove existing limit and add capped one
                            for l in capped.find_all(exp.Limit):
                                l.pop()
                            capped = capped.limit(self.max_rows)
                            modified_sql = capped.sql(dialect=self.dialect)
                        except Exception:
                            modified_sql = re.sub(
                                r'LIMIT\s+\d+',
                                f'LIMIT {self.max_rows}',
                                sql_stripped,
                                flags=re.IGNORECASE,
                            )
                except (ValueError, TypeError):
                    pass

        if violations:
            logger.warning(
                "SQL policy violation: %s | Tables: %s",
                "; ".join(violations),
                ", ".join(tables_accessed),
            )
            return PolicyResult(
                allowed=False,
                sql=sql,
                violations=violations,
                warnings=warnings,
                tables_accessed=tables_accessed,
                has_limit=has_limit,
            )

        return PolicyResult(
            allowed=True,
            sql=sql,
            warnings=warnings,
            tables_accessed=tables_accessed,
            has_limit=has_limit,
            modified_sql=modified_sql,
        )
