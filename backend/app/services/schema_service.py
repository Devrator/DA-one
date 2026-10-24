"""Schema discovery service.

Retrieves table structures, columns, relationships, and metadata
from target databases to provide context for SQL generation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import create_engine, text, inspect

from app.schemas import TableInfo, ColumnInfo, SchemaResponse

logger = logging.getLogger(__name__)


class SchemaService:
    """Discovers and caches database schema information."""

    def __init__(self):
        self._cache: dict[str, SchemaResponse] = {}

    def discover_schema(
        self,
        engine,
        connection_id: str,
        schema_name: str = "sales",
        force_refresh: bool = False,
    ) -> SchemaResponse:
        """Discover the schema of a target database.

        Args:
            engine: SQLAlchemy engine connected to the target DB.
            connection_id: Identifier for this connection (for caching).
            schema_name: Database schema to inspect.
            force_refresh: If True, bypass cache.

        Returns:
            SchemaResponse with all tables, columns, and relationships.
        """
        cache_key = f"{connection_id}:{schema_name}"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        tables: list[TableInfo] = []
        relationships: list[dict] = []

        try:
            insp = inspect(engine)

            # Get all table names in the schema
            table_names = insp.get_table_names(schema=schema_name)

            for table_name in table_names:
                columns: list[ColumnInfo] = []
                pk_columns: set[str] = set()

                # Get primary key columns
                try:
                    pk_info = insp.get_pk_constraint(table_name, schema=schema_name)
                    pk_columns = set(pk_info.get("constrained_columns", []))
                except Exception:
                    pass

                # Get foreign keys
                fk_map: dict[str, str] = {}
                try:
                    fks = insp.get_foreign_keys(table_name, schema=schema_name)
                    for fk in fks:
                        ref_schema = fk.get("referred_schema", schema_name) or schema_name
                        ref_table = fk.get("referred_table", "")
                        ref_cols = fk.get("referred_columns", [])
                        for i, col in enumerate(fk.get("constrained_columns", [])):
                            ref_col = ref_cols[i] if i < len(ref_cols) else ""
                            fk_map[col] = f"{ref_schema}.{ref_table}.{ref_col}"
                            relationships.append({
                                "from_table": f"{schema_name}.{table_name}",
                                "from_column": col,
                                "to_table": f"{ref_schema}.{ref_table}",
                                "to_column": ref_col,
                                "type": "foreign_key",
                            })
                except Exception:
                    pass

                # Get columns
                try:
                    col_infos = insp.get_columns(table_name, schema=schema_name)
                    for col in col_infos:
                        col_name = col["name"]
                        col_type = str(col["type"])
                        is_nullable = col.get("nullable", True)
                        comment = col.get("comment")

                        columns.append(ColumnInfo(
                            name=col_name,
                            data_type=col_type,
                            is_nullable=is_nullable,
                            is_primary_key=col_name in pk_columns,
                            is_foreign_key=col_name in fk_map,
                            foreign_key_ref=fk_map.get(col_name),
                            description=comment,
                        ))
                except Exception as e:
                    logger.warning("Failed to get columns for %s.%s: %s", schema_name, table_name, e)

                # Get table comment
                table_comment = None
                try:
                    table_comment = insp.get_table_comment(table_name, schema=schema_name).get("text")
                except Exception:
                    pass

                # Get approximate row count
                row_count = None
                try:
                    with engine.connect() as conn:
                        result = conn.execute(text(
                            f"SELECT reltuples::bigint FROM pg_class "
                            f"WHERE relname = :table AND relnamespace = "
                            f"(SELECT oid FROM pg_namespace WHERE nspname = :schema)"
                        ), {"table": table_name, "schema": schema_name})
                        row = result.fetchone()
                        if row and row[0] > 0:
                            row_count = int(row[0])
                except Exception:
                    pass

                tables.append(TableInfo(
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                    row_count=row_count,
                    description=table_comment,
                ))

            schema_response = SchemaResponse(
                connection_id=connection_id,
                tables=tables,
                relationships=relationships,
            )
            self._cache[cache_key] = schema_response
            return schema_response

        except Exception as e:
            logger.error("Schema discovery failed: %s", str(e))
            raise

    def format_schema_for_llm(
        self,
        schema: SchemaResponse,
        relevant_tables: list[str] | None = None,
    ) -> str:
        """Format schema information as a concise prompt context for the LLM.

        Args:
            schema: The discovered schema.
            relevant_tables: If provided, only include these tables.

        Returns:
            A formatted string suitable for the LLM prompt.
        """
        lines = ["DATABASE SCHEMA:", ""]

        for table in schema.tables:
            full_name = f"{table.schema_name}.{table.table_name}"

            # Filter to relevant tables if specified
            if relevant_tables and full_name not in relevant_tables and table.table_name not in relevant_tables:
                continue

            desc = f"  -- {table.description}" if table.description else ""
            lines.append(f"TABLE {full_name}{desc}")

            for col in table.columns:
                markers = []
                if col.is_primary_key:
                    markers.append("PK")
                if col.is_foreign_key:
                    markers.append(f"FK -> {col.foreign_key_ref}")
                if not col.is_nullable:
                    markers.append("NOT NULL")

                marker_str = f" [{', '.join(markers)}]" if markers else ""
                col_desc = f"  -- {col.description}" if col.description else ""
                lines.append(f"  {col.name} {col.data_type}{marker_str}{col_desc}")

            lines.append("")

        if schema.relationships:
            lines.append("RELATIONSHIPS:")
            seen = set()
            for rel in schema.relationships:
                key = f"{rel['from_table']}.{rel['from_column']} -> {rel['to_table']}.{rel['to_column']}"
                if key not in seen:
                    lines.append(f"  {key}")
                    seen.add(key)
            lines.append("")

        return "\n".join(lines)

    def clear_cache(self, connection_id: str | None = None):
        """Clear the schema cache."""
        if connection_id:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{connection_id}:")]
            for k in keys_to_remove:
                del self._cache[k]
        else:
            self._cache.clear()
