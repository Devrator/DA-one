"""Cross-System Intelligence service (Feature 5).

Provides a practical, security-preserving first version of multi-source
analytics across two independent PostgreSQL sources:

  * Each source is introspected INDEPENDENTLY (its own engine + schema).
  * Candidate relationships are inferred from compatible column names/types
    and primary/foreign-key hints. Uncertain mappings are NEVER auto-joined —
    they are returned as candidates that require explicit confirmation.
  * A confirmed mapping powers a CONTROLLED APPLICATION-SIDE JOIN of bounded,
    independently-authorized result sets. Each side is queried through the
    shared QueryExecutor under the requesting user's OWN security context so
    every source's Row-Level Security is applied independently. We do not
    pretend a cross-database server-side join happened, and we never copy
    unrestricted rows across sources.
  * Every cross-system result carries source-level lineage (which connections,
    tables, columns, rows, and SQL contributed to it) and explicit limitations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_target_engine, get_default_target_engine, check_db_health
from app.models import Connection, CrossSourceMapping
from app.services.schema_service import SchemaService
from app.services.query_executor import QueryExecutor
from app.services.role_service import resolve_user_context, is_column_allowed, is_table_allowed
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_ID = "default"
SAP_SCHEMA_LABEL = "sap"


class CrossSourceError(Exception):
    """Raised for user-correctable cross-source problems (bad source/table/col)."""


# Map a normalized OData json_type onto a SQL-like type so that the SAME
# cross-source candidate scorer (_norm_type / _compatible_type) works unchanged
# across PostgreSQL and SAP sides. This is a comparison category, not a claim
# that SAP is relational.
_SAP_JSON_TO_SQL_TYPE = {
    "string": "varchar",
    "guid": "uuid",
    "boolean": "boolean",
    "number": "numeric",
    "date": "timestamp",
    "datetime": "timestamp",
    "time": "time",
}


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no I/O)
# ---------------------------------------------------------------------------

def _norm_type(raw: str) -> str:
    """Normalize a DB type string into a broad compatibility category."""
    t = (raw or "").lower()
    if any(k in t for k in ("serial", "int")) and "interval" not in t:
        return "int"
    if any(k in t for k in ("numeric", "decimal", "money")):
        return "num"
    if any(k in t for k in ("double", "float", "real")):
        return "num"
    if any(k in t for k in ("timestamp", "date", "time")):
        return "temporal"
    if any(k in t for k in ("bool",)):
        return "bool"
    if any(k in t for k in ("char", "text", "uuid", "citext")):
        return "str"
    return "other"


def _compatible_type(lt: str, rt: str) -> bool:
    if lt == rt:
        return True
    # integer and numeric families are join-compatible
    return {lt, rt} == {"int", "num"}


def score_join_candidate(left: dict, right: dict) -> tuple[float, dict, bool]:
    """Score a candidate join between two columns (each a column dict).

    Returns (confidence 0..1, evidence, requires_confirmation). A confidence
    below 0.9 always requires explicit human confirmation before joining.
    """
    lt = _norm_type(left.get("data_type", ""))
    rt = _norm_type(right.get("data_type", ""))
    ln = (left.get("name") or "").lower()
    rn = (right.get("name") or "").lower()

    if not _compatible_type(lt, rt):
        return 0.0, {
            "compatible": False,
            "reasons": [f"incompatible types: {left.get('data_type')} vs {right.get('data_type')}"],
            "type": f"{lt}/{rt}",
        }, True

    conf = 0.0
    reasons: list[str] = ["type-compatible"]

    if ln == rn:
        conf = 0.8
        reasons.append(f"identical column name '{left.get('name')}'")

    lpk = bool(left.get("is_primary_key"))
    rpk = bool(right.get("is_primary_key"))
    lfk = bool(left.get("is_foreign_key"))
    rfk = bool(right.get("is_foreign_key"))

    if (lpk and rfk) or (rpk and lfk):
        conf = max(conf, 0.9)
        reasons.append("primary key on one side, foreign key on the other")
    elif lpk and rpk:
        conf = max(conf, 0.55)
        reasons.append("both primary keys")
    elif lfk and rfk:
        conf = max(conf, 0.6)
        reasons.append("both foreign keys")
    elif lpk or rpk:
        conf = max(conf, 0.5 if conf == 0.0 else conf)
        reasons.append("one side is a primary key")

    if conf == 0.0:
        # Type-compatible but no name/key signal: possible but weak.
        conf = 0.3
        reasons.append("no name or key evidence — weak candidate only")

    requires_confirmation = conf < 0.9
    return round(conf, 3), {
        "compatible": True,
        "reasons": reasons,
        "type": lt,
        "left_key": _key_hint(left),
        "right_key": _key_hint(right),
    }, requires_confirmation


def _key_hint(col: dict) -> str:
    if col.get("is_primary_key"):
        return "PK"
    if col.get("is_foreign_key"):
        return "FK"
    return ""


def appside_join(left_rows: list[dict], right_rows: list[dict],
                 left_key: str, right_key: str, join_type: str = "inner",
                 max_rows: int = 1000, left_prefix: str = "L.", right_prefix: str = "R.") -> tuple[list[dict], bool]:
    """Controlled hash-style join of two already-bounded, authorized result sets.

    Columns from each side are namespaced with ``left_prefix``/``right_prefix``
    so lineage stays unambiguous (both sources can share column names). Supports
    inner, left (preserve left source), right (preserve right source) and full.
    """
    index: dict[Any, list[dict]] = {}
    for row in left_rows:
        k = row.get(left_key)
        if k is None:
            continue
        index.setdefault(k, []).append({left_prefix + ck: cv for ck, cv in row.items()})

    joined: list[dict] = []
    truncated = False
    matched_left_keys: set[Any] = set()

    for rrow in right_rows:
        k = rrow.get(right_key)
        rp = {right_prefix + ck: cv for ck, cv in rrow.items()}
        matches = index.get(k)
        if matches:
            for lrow in matches:
                if len(joined) >= max_rows:
                    truncated = True
                    break
                joined.append({**lrow, **rp})
                matched_left_keys.add(k)
            if truncated:
                break
        elif join_type in ("right", "full"):
            if len(joined) >= max_rows:
                truncated = True
                break
            joined.append({**rp})

    if join_type in ("left", "full") and not truncated:
        for row in left_rows:
            k = row.get(left_key)
            if k in matched_left_keys:
                continue
            lp = {left_prefix + ck: cv for ck, cv in row.items()}
            if len(joined) >= max_rows:
                truncated = True
                break
            joined.append({**lp})

    return joined, truncated


# ---------------------------------------------------------------------------
# Data reference helpers
# ---------------------------------------------------------------------------

@dataclass
class TableRef:
    connection_id: str
    schema_name: str
    table_name: str


def _quote_ident(name: str) -> str:
    """Safely double-quote a Postgres identifier (validated elsewhere)."""
    safe = name.replace('"', '""')
    return f'"{safe}"'


class CrossSourceService:
    """Orchestrates independent source introspection and controlled joins."""

    def __init__(self, db: Session, schema_service: SchemaService, executor: QueryExecutor):
        self.db = db
        self.schema_service = schema_service
        self.executor = executor
        self.settings = get_settings()

    # -- source registry ---------------------------------------------------

    def _connection_row(self, connection_id: str) -> Optional[Connection]:
        return self.db.query(Connection).filter(
            Connection.id == connection_id, Connection.is_active == True  # noqa: E712
        ).first()

    # -- SAP (connector-provider) source helpers --------------------------

    def _is_sap(self, connection_id: str) -> bool:
        if connection_id == DEFAULT_SOURCE_ID:
            return False
        conn = self._connection_row(connection_id)
        return conn is not None and getattr(conn, "connector_type", "postgresql") == "sap_s4hana"

    def _sap_connector(self, connection_id: str):
        """Build a connector for a SAP source and hydrate it from the admin's
        CACHED metadata (never re-hit SAP for catalog/candidate reads). Returns
        (connector, Connection). Raises if metadata is not discovered yet."""
        from app.services.connectors.registry import build_connector
        conn = self._connection_row(connection_id)
        if not conn:
            raise CrossSourceError(f"Unknown or inactive SAP source: {connection_id}")
        connector = build_connector(conn)
        if not connector.hydrate_from_cache(conn.metadata_json):
            raise CrossSourceError(
                "SAP schema has not been discovered yet. An administrator must "
                "run POST /connections/{id}/schema/refresh first."
            )
        return connector, conn

    @staticmethod
    def _sap_entity_to_columns(entity, role: str) -> list[dict]:
        """Expose an SAP entity's metadata-declared, role-allowed fields in the
        same column-dict shape PostgreSQL sources use, so scoring is uniform."""
        cols: list[dict] = []
        for p in entity.properties:
            if not is_column_allowed(SAP_SCHEMA_LABEL, entity.name, p.name, role):
                continue
            cols.append({
                "name": p.name,
                "data_type": _SAP_JSON_TO_SQL_TYPE.get(p.json_type, "varchar"),
                "is_primary_key": p.name in (entity.keys or []),
                "is_foreign_key": False,
                "foreign_key_ref": None,
                "description": p.description,
            })
        return cols

    def _resolve_source(self, connection_id: str) -> tuple[Any, str, str]:
        """Return (engine, schema_name, label) for a source id.

        'default' maps to the configured primary target ('sales'). Any other id
        must be an active Connection row. Never expose credentials.
        """
        if connection_id == DEFAULT_SOURCE_ID:
            engine = get_default_target_engine()
            return engine, "sales", "Primary Sales Target"
        conn = self._connection_row(connection_id)
        if not conn:
            raise CrossSourceError(f"Unknown or inactive source: {connection_id}")
        if getattr(conn, "connector_type", "postgresql") == "sap_s4hana":
            raise CrossSourceError(
                "SAP sources are joined through the connector provider, not a SQL engine."
            )
        engine = create_target_engine(
            host=conn.host, port=conn.port, dbname=conn.database_name,
            user=conn.username, password=decrypt_secret(conn.encrypted_password),
            statement_timeout_ms=self.settings.cross_source_statement_timeout_ms,
        )
        return engine, (conn.schema_name or "public"), conn.name

    def list_sources(self) -> dict:
        """Catalog of available sources with health + basic shape (no secrets)."""
        sources: list[dict] = []
        # default primary source
        sources.append(self._source_summary(DEFAULT_SOURCE_ID, "Primary Sales Target", "sales"))
        # registered connections
        rows = self.db.query(Connection).filter(
            Connection.is_active == True  # noqa: E712
        ).order_by(Connection.created_at).all()
        for conn in rows:
            sources.append(self._source_summary(conn.id, conn.name, conn.schema_name or "public"))
        enabled = sum(1 for s in sources if s["healthy"])
        return {
            "sources": sources,
            "source_count": len(sources),
            "healthy_count": enabled,
            "strategy": "controlled_application_side_join",
            "note": (
                "Each source is introspected and authorized independently. "
                "Cross-system results are produced by joining bounded, authorized "
                "result sets in the application — not by an unrestricted server-side "
                "cross-database join."
            ),
        }

    def _source_summary(self, connection_id: str, label: str, schema_name: str) -> dict:
        if self._is_sap(connection_id):
            conn = self._connection_row(connection_id)
            cached = conn.metadata_json or {}
            entities = cached.get("entities", [])
            return {
                "connection_id": connection_id, "name": conn.name,
                "schema": SAP_SCHEMA_LABEL, "connector_type": "sap_s4hana",
                "healthy": bool(entities),
                "error": None if entities else "SAP schema not discovered yet — refresh required",
                "tables": len(entities),
                "total_rows": sum(e.get("count") or 0 for e in entities),
            }
        try:
            engine, resolved_schema, name = self._resolve_source(connection_id)
        except CrossSourceError as exc:
            return {"connection_id": connection_id, "name": label, "schema": schema_name,
                    "healthy": False, "error": str(exc), "tables": 0, "total_rows": 0}
        health = check_db_health(engine)
        tables = 0
        total_rows = 0
        if health["status"] == "healthy":
            try:
                resp = self.schema_service.discover_schema(
                    engine, connection_id=connection_id, schema_name=resolved_schema, force_refresh=True
                )
                tables = len(resp.tables)
                total_rows = sum((t.row_count or 0) for t in resp.tables)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("catalog failed for %s: %s", connection_id, exc)
        return {
            "connection_id": connection_id,
            "name": label,
            "schema": resolved_schema,
            "healthy": health["status"] == "healthy",
            "error": health.get("error"),
            "tables": tables,
            "total_rows": total_rows,
        }

    def get_catalog(self, connection_id: str, role: str = "executive") -> dict:
        """Independently introspect one source, filtered by that role's authz."""
        if self._is_sap(connection_id):
            connector, conn = self._sap_connector(connection_id)
            allowed_tables: list[dict] = []
            for entity in connector.list_entities():
                if not is_table_allowed(SAP_SCHEMA_LABEL, entity.name, role):
                    continue
                allowed_tables.append({
                    "schema": SAP_SCHEMA_LABEL, "table": entity.name,
                    "row_count": entity.count, "description": entity.entity_type,
                    "columns": self._sap_entity_to_columns(entity, role),
                })
            return {
                "connection_id": connection_id, "name": conn.name,
                "schema": SAP_SCHEMA_LABEL, "connector_type": "sap_s4hana", "role": role,
                "healthy": True, "tables": allowed_tables,
                "authz_note": (
                    "Only metadata-declared, role-allowed SAP entities/fields are listed. "
                    "The integration identity's SAP-side authorizations apply IN ADDITION "
                    "to QueryPilot policy."
                ),
            }
        engine, schema_name, label = self._resolve_source(connection_id)
        health = check_db_health(engine)
        resp = self.schema_service.discover_schema(
            engine, connection_id=connection_id, schema_name=schema_name, force_refresh=True
        )
        allowed_tables: list[dict] = []
        for t in resp.tables:
            if not is_table_allowed(t.schema_name, t.table_name, role):
                continue
            cols = [
                {
                    "name": c.name,
                    "data_type": c.data_type,
                    "is_primary_key": c.is_primary_key,
                    "is_foreign_key": c.is_foreign_key,
                    "foreign_key_ref": c.foreign_key_ref,
                    "description": c.description,
                }
                for c in t.columns
                if is_column_allowed(t.schema_name, t.table_name, c.name, role)
            ]
            allowed_tables.append({
                "schema": t.schema_name, "table": t.table_name,
                "row_count": t.row_count, "description": t.description, "columns": cols,
            })
        return {
            "connection_id": connection_id,
            "name": label,
            "schema": schema_name,
            "role": role,
            "healthy": health["status"] == "healthy",
            "tables": allowed_tables,
            "authz_note": "Columns/tables not permitted for this role are omitted.",
        }

    # -- relationship inference -------------------------------------------

    def find_candidates(self, left: TableRef, right: TableRef, role: str) -> dict:
        """Infer candidate join keys between two tables in (possibly) two sources."""
        left_cols = self._authorized_columns(left, role)
        right_cols = self._authorized_columns(right, role)

        candidates: list[dict] = []
        for lc in left_cols:
            for rc in right_cols:
                conf, evidence, requires = score_join_candidate(lc, rc)
                if conf <= 0.0:
                    continue
                candidates.append({
                    "left_connection_id": left.connection_id,
                    "left_schema": left.schema_name,
                    "left_table": left.table_name,
                    "left_column": lc["name"],
                    "right_connection_id": right.connection_id,
                    "right_schema": right.schema_name,
                    "right_table": right.table_name,
                    "right_column": rc["name"],
                    "confidence": conf,
                    "requires_confirmation": requires,
                    "evidence": evidence,
                })
        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        return {
            "left": left.__dict__, "right": right.__dict__, "role": role,
            "candidates": candidates,
            "candidate_count": len(candidates),
            "auto_joinable": [c for c in candidates if not c["requires_confirmation"]],
            "note": "Candidates below 0.9 confidence require explicit confirmation before use.",
        }

    def _authorized_columns(self, ref: TableRef, role: str) -> list[dict]:
        if not is_table_allowed(ref.schema_name, ref.table_name, role):
            raise CrossSourceError(f"Table {ref.schema_name}.{ref.table_name} not permitted for role {role}")
        if self._is_sap(ref.connection_id):
            from app.services.connectors.base import ConnectorError
            connector, _ = self._sap_connector(ref.connection_id)
            try:
                entity = connector.get_entity_metadata(ref.table_name)
            except ConnectorError as exc:
                raise CrossSourceError(f"SAP entity not available: {ref.table_name} ({exc.message})")
            return self._sap_entity_to_columns(entity, role)
        engine, schema_name, _ = self._resolve_source(ref.connection_id)
        resp = self.schema_service.discover_schema(
            engine, connection_id=ref.connection_id, schema_name=schema_name, force_refresh=True
        )
        for t in resp.tables:
            if t.schema_name == ref.schema_name and t.table_name == ref.table_name:
                return [
                    {"name": c.name, "data_type": c.data_type, "is_primary_key": c.is_primary_key,
                     "is_foreign_key": c.is_foreign_key, "foreign_key_ref": c.foreign_key_ref}
                    for c in t.columns
                    if is_column_allowed(t.schema_name, t.table_name, c.name, role)
                ]
        raise CrossSourceError(f"Table not found in source {ref.connection_id}: {ref.schema_name}.{ref.table_name}")

    # -- mapping persistence ----------------------------------------------

    def list_mappings(self) -> list[dict]:
        rows = self.db.query(CrossSourceMapping).order_by(CrossSourceMapping.created_at.desc()).all()
        return [self._mapping_dict(m) for m in rows]

    def _mapping_dict(self, m: CrossSourceMapping) -> dict:
        return {
            "id": m.id,
            "left_connection_id": m.left_connection_id, "left_schema": m.left_schema,
            "left_table": m.left_table, "left_column": m.left_column,
            "right_connection_id": m.right_connection_id, "right_schema": m.right_schema,
            "right_table": m.right_table, "right_column": m.right_column,
            "status": m.status, "confidence": m.confidence, "evidence": m.evidence,
            "created_by": m.created_by, "confirmed_by": m.confirmed_by,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }

    def save_candidate(self, payload: dict, created_by: str) -> dict:
        """Persist an inferred candidate (status='candidate')."""
        m = CrossSourceMapping(
            left_connection_id=payload["left_connection_id"], left_schema=payload["left_schema"],
            left_table=payload["left_table"], left_column=payload["left_column"],
            right_connection_id=payload["right_connection_id"], right_schema=payload["right_schema"],
            right_table=payload["right_table"], right_column=payload["right_column"],
            status="candidate", confidence=float(payload.get("confidence", 0.0)),
            evidence=payload.get("evidence", {}), created_by=created_by,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return self._mapping_dict(m)

    def confirm_mapping(self, mapping_id: str, confirmed_by: str) -> dict:
        m = self.db.query(CrossSourceMapping).filter(CrossSourceMapping.id == mapping_id).first()
        if not m:
            raise CrossSourceError("Mapping not found")
        # Re-validate both endpoints still exist and columns are compatible before confirm.
        lc = [c for c in self._authorized_columns(
            TableRef(m.left_connection_id, m.left_schema, m.left_table), "executive") if c["name"] == m.left_column]
        rc = [c for c in self._authorized_columns(
            TableRef(m.right_connection_id, m.right_schema, m.right_table), "executive") if c["name"] == m.right_column]
        if not lc or not rc:
            raise CrossSourceError("Confirmed columns no longer exist in one of the sources")
        conf, evidence, _ = score_join_candidate(lc[0], rc[0])
        if conf <= 0.0:
            raise CrossSourceError("Columns are no longer type-compatible; cannot confirm")
        m.status = "confirmed"
        m.confidence = max(m.confidence, conf)
        m.evidence = {**(m.evidence or {}), "confirm_validation": evidence}
        m.confirmed_by = confirmed_by
        self.db.commit()
        self.db.refresh(m)
        return self._mapping_dict(m)

    def delete_mapping(self, mapping_id: str) -> None:
        m = self.db.query(CrossSourceMapping).filter(CrossSourceMapping.id == mapping_id).first()
        if not m:
            raise CrossSourceError("Mapping not found")
        self.db.delete(m)
        self.db.commit()

    # -- controlled cross-source join ------------------------------------

    def run_join(self, mapping_id: str, requestor: str,
                 left_columns: list[str], right_columns: list[str],
                 join_type: str = "inner") -> dict:
        """Execute a bounded, independently-authorized application-side join."""
        if not self.settings.cross_source_enabled:
            raise CrossSourceError("Cross-system intelligence is disabled")
        m = self.db.query(CrossSourceMapping).filter(CrossSourceMapping.id == mapping_id).first()
        if not m:
            raise CrossSourceError("Mapping not found")
        if m.status != "confirmed":
            raise CrossSourceError(
                "Only a CONFIRMED mapping can be joined. Confirm this mapping first."
            )

        user_ctx = resolve_user_context(requestor)
        role = user_ctx.role
        max_rows = self.settings.cross_source_max_rows_per_source

        left_ref = TableRef(m.left_connection_id, m.left_schema, m.left_table)
        right_ref = TableRef(m.right_connection_id, m.right_schema, m.right_table)

        left_sql, left_res, left_meta = self._fetch_bounded(left_ref, m.left_column, left_columns, role, user_ctx, max_rows)
        right_sql, right_res, right_meta = self._fetch_bounded(right_ref, m.right_column, right_columns, role, user_ctx, max_rows)

        if not left_res.success:
            return self._failure("left", left_res, left_meta, right_meta)
        if not right_res.success:
            return self._failure("right", right_res, left_meta, right_meta)

        joined, truncated = appside_join(
            left_res.rows, right_res.rows, m.left_column, m.right_column,
            join_type=join_type, max_rows=self.settings.cross_source_max_joined_rows,
        )

        lineage = {
            "strategy": "controlled_application_side_join",
            "mapping_id": m.id,
            "join_key": {"left": f"{m.left_schema}.{m.left_table}.{m.left_column}",
                         "right": f"{m.right_schema}.{m.right_table}.{m.right_column}"},
            "left_source": left_meta,
            "right_source": right_meta,
            "role_applied": role,
            "joined_row_count": len(joined),
            "joined_truncated": truncated,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        limitations = [
            "Join performed in the application over two independently-authorized, "
            "row-bounded result sets — not a server-side cross-database join.",
            "Each source enforced its own Row-Level Security under the requestor's context; "
            "no unrestricted rows were copied between sources.",
            "Results are bounded by per-source and joined row limits; truncated flags indicate "
            "when a limit was reached.",
        ]
        sap_sides = [name for name, m in (("left", left_meta), ("right", right_meta))
                     if m.get("connector_type") == "sap_s4hana"]
        if sap_sides:
            limitations.append(
                f"The {' and '.join(sap_sides)} side is a bounded subset retrieved from SAP "
                "through the OData connector under BOTH QueryPilot role policy and the "
                "integration identity's SAP-side authorizations. The result joins retrieved "
                "authorized subsets — it does not represent complete enterprise data, and no "
                "shared transaction or snapshot semantics are implied across sources."
            )
        if left_res.truncated:
            limitations.append("Left source result hit the per-source row limit.")
        if right_res.truncated:
            limitations.append("Right source result hit the per-source row limit.")
        if truncated:
            limitations.append("Joined result hit the joined-row limit.")

        columns = (
            [f"L.{c}" for c in left_meta["columns"]]
            + [f"R.{c}" for c in right_meta["columns"]]
        )
        return {
            "ok": True,
            "columns": columns,
            "rows": joined,
            "row_count": len(joined),
            "truncated": truncated,
            "join_type": join_type,
            "lineage": lineage,
            "limitations": limitations,
        }

    def _fetch_bounded(self, ref: TableRef, key_column: str, requested_cols: list[str],
                       role: str, user_ctx, max_rows: int):
        """Build + run a safe, bounded, authorized read for one source side."""
        if self._is_sap(ref.connection_id):
            return self._fetch_bounded_sap(ref, key_column, requested_cols, role, max_rows)
        available = {c["name"]: c for c in self._authorized_columns(ref, role)}
        if key_column not in available:
            raise CrossSourceError(
                f"Join column '{key_column}' is not available for role {role} on {ref.table_name}"
            )
        # Whitelist selected columns; always include the key for joining.
        selected: list[str] = []
        for col in ([key_column] + list(requested_cols or [])):
            if col in available and col not in selected:
                selected.append(col)
        engine, schema_name, _ = self._resolve_source(ref.connection_id)
        proj = ", ".join(_quote_ident(c) for c in selected)
        sql = (
            f"SELECT {proj} FROM {_quote_ident(schema_name)}.{_quote_ident(ref.table_name)} "
            f"LIMIT {int(max_rows) + 1}"
        )
        result = self.executor.execute(engine, sql, max_rows=max_rows, user_context=user_ctx)
        meta = {
            "connection_id": ref.connection_id, "schema": schema_name, "table": ref.table_name,
            "columns": selected, "evidence_sql": sql,
            "returned_rows": result.row_count if result.success else 0,
            "truncated": bool(result.truncated),
            "execution_time_ms": round(result.execution_time_ms, 1),
        }
        return sql, result, meta

    def _fetch_bounded_sap(self, ref: TableRef, key_column: str, requested_cols: list[str],
                           role: str, max_rows: int):
        """Connector-provider fetch: the SAME bounded, independently-authorized
        semantics as the SQL side, executed as a policy-validated OData read.
        No SQL, no engine — the normalized ExecutionResult contract is reused."""
        from app.services.connectors.base import ConnectorError
        connector, _ = self._sap_connector(ref.connection_id)
        try:
            entity = connector.get_entity_metadata(ref.table_name)
        except ConnectorError as exc:
            raise CrossSourceError(f"SAP entity not available: {ref.table_name} ({exc.message})")
        available = {c["name"]: c for c in self._sap_entity_to_columns(entity, role)}
        if key_column not in available:
            raise CrossSourceError(
                f"Join column '{key_column}' is not available for role {role} on SAP entity '{ref.table_name}'"
            )
        selected: list[str] = []
        for col in ([key_column] + list(requested_cols or [])):
            if col in available and col not in selected:
                selected.append(col)
        try:
            result = connector.fetch_records(ref.table_name, select=selected,
                                             top=max_rows, role=role)
        except ConnectorError as exc:
            raise CrossSourceError(f"SAP fetch failed: {exc.message}")
        meta = {
            "connection_id": ref.connection_id, "schema": SAP_SCHEMA_LABEL, "table": ref.table_name,
            "connector_type": "sap_s4hana", "columns": selected,
            "evidence_request": {"entity": ref.table_name, "select": selected, "top": max_rows},
            "returned_rows": result.row_count if result.success else 0,
            "truncated": bool(result.truncated),
            "execution_time_ms": round(result.execution_time_ms, 1),
        }
        return None, result, meta

    def _failure(self, side: str, res, left_meta: dict, right_meta: dict) -> dict:
        return {
            "ok": False,
            "failed_side": side,
            "error": res.error,
            "error_category": res.error_category,
            "partial": True,
            "lineage": {"left_source": left_meta, "right_source": right_meta, "strategy": "controlled_application_side_join"},
            "limitations": [
                "One source failed; the join was aborted rather than completed on partial data.",
            ],
            "rows": [], "row_count": 0,
        }

    @staticmethod
    def _joined_columns(left_cols: list[str], right_cols: list[str], lkey: str, rkey: str) -> list[str]:
        cols: list[str] = []
        for c in ([lkey] + [x for x in (left_cols or []) if x != lkey]):
            cols.append(f"L.{c}")
        for c in ([x for x in (right_cols or []) if x != rkey]):
            cols.append(f"R.{c}")
        return cols

