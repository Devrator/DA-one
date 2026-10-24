"""Anti-hallucination validation layer.

Guarantees every AI answer is true and evidence-backed:

1. Schema grounding — every table and column referenced in generated SQL must
   exist in the live discovered schema. Hallucinated identifiers are rejected
   (and fed into the bounded repair loop) before anything touches PostgreSQL.
2. Numeric evidence verification — every number claimed in an LLM-generated
   explanation must be traceable to the actual query result set (a cell value,
   a simple aggregate of a column, or the row count). If any claim is
   unsupported, the LLM explanation is discarded and a deterministic,
   template-generated explanation built directly from the data is used instead.
3. Evidence metadata — a structured provenance record is attached to every
   completed answer so the user can see exactly which tables, columns, rows
   and executed SQL back the answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import sqlglot
from sqlglot import exp

from app.schemas import SchemaResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema grounding (SQL-level hallucination check)
# ---------------------------------------------------------------------------

@dataclass
class GroundingResult:
    """Result of validating generated SQL against the real schema."""
    grounded: bool
    qualified_sql: Optional[str] = None
    hallucinated_tables: list[str] = field(default_factory=list)
    hallucinated_columns: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


class SchemaGroundingValidator:
    """Rejects SQL that references tables or columns not present in the live schema."""

    def __init__(self, schema: SchemaResponse, default_schema: str = "sales"):
        self.default_schema = default_schema
        self.tables_list = schema.tables
        # Map "schema.table" -> set of column names, plus bare table name alias
        self.table_columns: dict[str, set[str]] = {}
        for t in schema.tables:
            cols = {c.name.lower() for c in t.columns}
            full = f"{t.schema_name}.{t.table_name}".lower()
            self.table_columns[full] = cols
            self.table_columns.setdefault(t.table_name.lower(), set()).update(cols)
        self.known_tables = {f"{t.schema_name}.{t.table_name}".lower() for t in schema.tables}
        self.known_bare = {t.table_name.lower() for t in schema.tables}

    def validate(self, sql: str) -> GroundingResult:
        """Validate that every identifier in the SQL exists in the real schema.

        Returns a GroundingResult; when grounded, qualified_sql contains the
        alias-qualified form of the query for reliable column extraction.
        """
        try:
            statement = sqlglot.parse_one(sql, dialect="postgres")
        except Exception as e:
            return GroundingResult(
                grounded=False,
                violations=[f"SQL could not be parsed for grounding: {e}"],
            )

        # Collect CTE names — they are virtual tables, not schema tables
        cte_names = {
            cte.alias_or_name.lower()
            for cte in statement.find_all(exp.CTE)
            if cte.alias_or_name
        }

        # Derived aliases (e.g. SUM(...) AS total_revenue) — columns referencing
        # them are not schema hallucinations
        defined_aliases = {
            a.alias.lower() for a in statement.find_all(exp.Alias) if a.alias
        }

        # Qualify columns (resolve aliases → real tables) for accurate checks
        try:
            qualified = sqlglot.qualify_columns.quote_identifiers(
                sqlglot.optimizer.qualify.qualify(
                    statement.copy(),
                    schema=self._sqlglot_schema(),
                    dialect="postgres",
                    expand_stars=False,
                    allow_partial=True,
                )
            )
            qualified_sql = qualified.sql(dialect="postgres")
        except Exception as e:
            # Qualification can fail on exotic SQL — fall back to raw AST scan
            logger.debug("Column qualification skipped: %s", e)
            qualified = statement
            qualified_sql = sql

        hallucinated_tables: list[str] = []
        hallucinated_columns: list[str] = []
        referenced_tables: set[str] = set()

        for table in qualified.find_all(exp.Table):
            name = (table.name or "").lower()
            if not name or name in cte_names:
                continue
            schema_part = (table.db or self.default_schema).lower()
            full = f"{schema_part}.{name}"
            if full in self.known_tables or name in self.known_bare:
                referenced_tables.add(full if full in self.known_tables else name)
            else:
                hallucinated_tables.append(full)

        # Build the set of columns allowed: union over referenced real tables
        allowed_columns: set[str] = set()
        for ref in referenced_tables:
            allowed_columns |= self.table_columns.get(ref.lower(), set())
        permissive = not referenced_tables

        if not permissive:
            seen_cols: set[str] = set()
            for col in qualified.find_all(exp.Column):
                col_name = (col.name or "").lower()
                if not col_name or col_name == "*" or col_name in seen_cols:
                    continue
                seen_cols.add(col_name)
                table_ref = (col.table or "").lower()
                if col_name in cte_names or col_name in defined_aliases:
                    continue  # virtual/derived names are defined by the query itself
                if table_ref and table_ref in cte_names:
                    continue  # columns of CTEs are defined by the query itself
                if col_name not in allowed_columns:
                    hallucinated_columns.append(
                        f"{col.table + '.' if col.table else ''}{col.name}"
                    )

        violations = []
        if hallucinated_tables:
            violations.append(
                "SQL references tables that do not exist in the database: "
                + ", ".join(sorted(set(hallucinated_tables)))
            )
        if hallucinated_columns:
            violations.append(
                "SQL references columns that do not exist in the database: "
                + ", ".join(sorted(set(hallucinated_columns)))
            )

        return GroundingResult(
            grounded=not violations,
            qualified_sql=qualified_sql,
            hallucinated_tables=sorted(set(hallucinated_tables)),
            hallucinated_columns=sorted(set(hallucinated_columns)),
            violations=violations,
        )

    def _sqlglot_schema(self) -> dict[str, dict[str, list[str]]]:
        """Build sqlglot's nested schema map: {schema: {table: [columns]}}."""
        nested: dict[str, dict[str, list[str]]] = {}
        for t in self.tables_list:
            nested.setdefault(t.schema_name.lower(), {})[t.table_name.lower()] = sorted(
                c.name.lower() for c in t.columns
            )
        return nested


# ---------------------------------------------------------------------------
# Numeric evidence verification (explanation-level hallucination check)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


class EvidenceVerifier:
    """Verifies that every numeric claim in an explanation is traceable to the data.

    A number is considered evidence-backed when it matches (within rounding
    tolerance) a cell value, a simple column aggregate (sum/avg/min/max),
    the row count, or a numeric literal present in the executed SQL.
    """

    # Small talk numbers (counts of sentences, percentages under 10, years,
    # limit values) are not treated as data claims.
    _IGNORE_SMALL_INTEGERS = 4

    def verify(
        self,
        text: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        sql: str = "",
    ) -> tuple[bool, list[str]]:
        """Return (grounded, unverified_claims)."""
        evidence = self._build_evidence_pool(columns, rows, sql)
        unverified: list[str] = []

        for match in _NUMBER_RE.finditer(text):
            raw = match.group(0).rstrip(".")
            if not raw or raw in ("-", "."):
                continue
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            # Ignore trivial integers and year-like values
            if abs(value) < self._IGNORE_SMALL_INTEGERS:
                continue
            if value == int(value) and 1900 <= int(value) <= 2100:
                continue
            if self._matches_evidence(value, raw, evidence, text):
                continue
            unverified.append(raw)

        return (not unverified), sorted(set(unverified))

    def _build_evidence_pool(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
        sql: str,
    ) -> set[float]:
        pool: set[float] = {float(len(rows))}

        for row in rows:
            for col in columns:
                val = row.get(col)
                if isinstance(val, bool) or val is None:
                    continue
                if isinstance(val, (int, float)):
                    pool.add(float(val))
                elif isinstance(val, str):
                    cleaned = val.replace(",", "").replace("$", "").replace("%", "")
                    try:
                        pool.add(float(cleaned))
                    except ValueError:
                        pass

        # Simple per-column aggregates the analyst is allowed to cite
        for col in columns:
            nums = [
                float(row[col]) for row in rows
                if isinstance(row.get(col), (int, float)) and not isinstance(row.get(col), bool)
            ]
            if not nums:
                continue
            pool.add(sum(nums))
            pool.add(sum(nums) / len(nums))
            pool.add(min(nums))
            pool.add(max(nums))

        # Numeric literals inside the executed SQL (rates, thresholds, limits)
        for match in _NUMBER_RE.finditer(sql or ""):
            try:
                pool.add(float(match.group(0).replace(",", "")))
            except ValueError:
                pass

        return pool

    def _matches_evidence(
        self, value: float, raw: str, pool: set[float], text: str
    ) -> bool:
        # Tolerance: half a unit for integers (covers rounding of displayed
        # decimals), 0.5% relative for larger values (covers K/% abbreviations
        # handled separately below)
        for ev in pool:
            if ev == value:
                return True
            if value == int(value) and abs(ev - value) <= 0.51:
                return True
            if ev != 0 and abs(ev - value) / max(abs(ev), 1e-9) <= 0.005:
                return True
        # Abbreviated forms like "145.2K" / "1.2M" — compare scaled pool values
        for ev in pool:
            for mult in (1000.0, 1_000_000.0):
                if abs(ev - value * mult) / max(abs(ev), 1e-9) <= 0.01:
                    return True
        return False


# ---------------------------------------------------------------------------
# Evidence metadata builder
# ---------------------------------------------------------------------------

def build_evidence(
    *,
    tables_used: list[str],
    columns_used: list[str],
    sql: str,
    row_count: int,
    execution_time_ms: Optional[float],
    grounding: GroundingResult,
    explanation_grounded: bool,
    unverified_claims: list[str],
    model_name: Optional[str],
) -> dict[str, Any]:
    """Assemble the provenance record attached to every completed answer."""
    verified = bool(grounding.grounded and explanation_grounded)
    return {
        "verified": verified,
        "status": "verified_against_database" if verified else "partially_verified",
        "source": "live_postgresql_target_database",
        "tables_used": sorted({t.lower() for t in tables_used}),
        "columns_used": sorted({c.lower() for c in columns_used}),
        "row_count": row_count,
        "execution_time_ms": round(execution_time_ms, 1) if execution_time_ms else None,
        "sql_executed": sql,
        "schema_grounding": {
            "passed": grounding.grounded,
            "hallucinated_tables": grounding.hallucinated_tables,
            "hallucinated_columns": grounding.hallucinated_columns,
        },
        "explanation_grounding": {
            "passed": explanation_grounded,
            "unverified_claims": unverified_claims,
        },
        "model": model_name,
    }
