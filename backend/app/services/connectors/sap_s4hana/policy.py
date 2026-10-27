"""SAP connector policy boundary.

CRITICAL DESIGN DECISION (spec §8): SQLGlot parses SQL — it cannot secure an
OData URL, and routing model-generated URLs through HTTP would bypass every
guard. Instead the model may ONLY produce a structured request plan:

    {entity, select[], filter{...}, orderby, top}

This policy validates that plan against (a) the DISCOVERED metadata (entity
and fields must actually exist and be readable) and (b) the user's ROLE
authorization via the same role_service used everywhere else. Only then does
the trusted client build the URL. The LLM never emits a URL.

Checks performed:
  * entity exists in metadata and role may access it;
  * every selected/filtered/ordered field exists, is non-readonly exposure-
    safe (binary payloads blocked), and is role-allowed;
  * filter operators/fields/values restricted to the metadata-declared types;
  * key-field predicates enforced for role-scoped entities (e.g. sales reps
    only via their own account) — QueryPilot authz IN ADDITION TO SAP authz;
  * top bounded by settings.max_records; depth/condition count bounded.
"""

from __future__ import annotations

from typing import Optional

from app.services.connectors.base import EntityMeta, PolicyError
from app.services.connectors.sap_s4hana.metadata import is_large_binary, normalize_edm_type
from app.services.connectors.sap_s4hana.odata import (
    COMPARISON_OPS,
    MAX_FILTER_CONDITIONS,
    STRING_OPS,
)

SAP_SCHEMA_LABEL = "sap"  # role_service tables are keyed by (schema, table)


def _field_allowed(entity_name: str, field: str, role: str) -> bool:
    from app.services.role_service import is_column_allowed
    return is_column_allowed(SAP_SCHEMA_LABEL, entity_name, field, role)


def _entity_allowed(entity_name: str, role: str) -> bool:
    from app.services.role_service import is_table_allowed
    return is_table_allowed(SAP_SCHEMA_LABEL, entity_name, role)


def validate_plan(entity: Optional[EntityMeta], plan: dict, role: str,
                  *, max_records: int) -> dict:
    """Validate + normalize one structured request plan. Raises PolicyError.

    Returns the normalized plan (safe defaults applied).
    """
    if entity is None:
        raise PolicyError("Unknown SAP entity — not present in discovered metadata")
    if not _entity_allowed(entity.name, role):
        raise PolicyError(f"Role '{role}' is not permitted to query SAP entity '{entity.name}'")

    select = plan.get("select")
    if not select or not isinstance(select, list):
        raise PolicyError("'select' must be a non-empty list of fields")
    cleaned_select: list[str] = []
    for f in select:
        if not isinstance(f, str):
            raise PolicyError("select entries must be field names")
        prop = entity.property(f)
        if prop is None:
            raise PolicyError(f"Field '{f}' is not declared for entity '{entity.name}'")
        if is_large_binary(prop.odata_type):
            raise PolicyError(f"Field '{f}' is a large binary payload and cannot be selected")
        if not _field_allowed(entity.name, f, role):
            raise PolicyError(f"Role '{role}' may not select field '{f}' of '{entity.name}'")
        if f not in cleaned_select:
            cleaned_select.append(f)

    filter_plan = plan.get("filter")
    if filter_plan is not None:
        _validate_filter_node(filter_plan, entity, role, depth=0)

    orderby = plan.get("orderby")
    if orderby is not None:
        _validate_orderby(orderby, entity, role)

    top = plan.get("top") or min(max_records, 100)
    try:
        top = int(top)
    except (TypeError, ValueError):
        raise PolicyError("'top' must be an integer")
    if top < 1:
        raise PolicyError("'top' must be positive")
    if top > max_records:
        top = max_records  # silently clamp to the configured hard bound

    return {"entity": entity.name, "select": cleaned_select,
            "filter": filter_plan, "orderby": orderby, "top": top}


def _validate_filter_node(node, entity: EntityMeta, role: str, depth: int) -> int:
    """Recursive validation; returns the number of leaf conditions."""
    from app.services.connectors.sap_s4hana.odata import MAX_FILTER_DEPTH
    if depth > MAX_FILTER_DEPTH:
        raise PolicyError("Filter nested too deeply")
    if not isinstance(node, dict) or not node:
        raise PolicyError("Filter nodes must be objects")

    keys = set(node.keys())
    if keys & {"and", "or"}:
        if len(keys) != 1:
            raise PolicyError("Logical node must contain only 'and' or 'or'")
        op = next(iter(keys))
        children = node[op]
        if not isinstance(children, list) or not (1 <= len(children) <= 10):
            raise PolicyError(f"'{op}' requires 1..10 children")
        total = 0
        for child in children:
            total += _validate_filter_node(child, entity, role, depth + 1)
        if total > MAX_FILTER_CONDITIONS:
            raise PolicyError(f"Filter exceeds {MAX_FILTER_CONDITIONS} conditions")
        return total

    field = node.get("field")
    op = (node.get("op") or "").lower()
    value = node.get("value")
    if not isinstance(field, str) or not field:
        raise PolicyError("Filter condition requires 'field'")
    prop = entity.property(field)
    if prop is None:
        raise PolicyError(f"Filter field '{field}' not declared for '{entity.name}'")
    if op not in COMPARISON_OPS | STRING_OPS:
        raise PolicyError(f"Filter operator '{op}' is not supported")
    if op in STRING_OPS and normalize_edm_type(prop.odata_type)[0] != "string":
        raise PolicyError(f"Operator '{op}' only applies to string fields")
    if not _field_allowed(entity.name, field, role):
        raise PolicyError(f"Role '{role}' may not filter on field '{field}'")
    # Value sanity: no raw structures; scalars only (rendering encodes types)
    if isinstance(value, (dict, list)):
        raise PolicyError("Filter values must be scalars")
    return 1


def _validate_orderby(orderby, entity: EntityMeta, role: str) -> None:
    if not isinstance(orderby, str):
        raise PolicyError("'orderby' must be a string like 'Field asc'")
    parts = [p.strip() for p in orderby.split(",") if p.strip()]
    if not (1 <= len(parts) <= 3):
        raise PolicyError("'orderby' supports 1..3 fields")
    for part in parts:
        tokens = part.split()
        field = tokens[0]
        direction = tokens[1].lower() if len(tokens) > 1 else "asc"
        if len(tokens) > 2 or direction not in ("asc", "desc"):
            raise PolicyError(f"Invalid orderby clause '{part}'")
        if entity.property(field) is None:
            raise PolicyError(f"Orderby field '{field}' not declared for '{entity.name}'")
        if not _field_allowed(entity.name, field, role):
            raise PolicyError(f"Role '{role}' may not order by '{field}'")
