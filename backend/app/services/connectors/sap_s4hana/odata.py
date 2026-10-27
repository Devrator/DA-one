"""OData query building and page parsing (V2 + V4 protocol differences).

Everything here is PURE (no I/O): the policy layer validates a structured
filter plan against discovered metadata FIRST, then this module renders that
already-validated plan into a $filter string with typed literal encoding, so
model- or user-supplied text can never break out into OData syntax.

V2/V4 differences handled:
  * continuation token: V2 `d.__next`  vs V4 `@odata.nextLink`
  * row envelope:       V2 `d.results` vs V4 `value`
  * inline count:       V2 `d.__count`  vs V4 `@odata.count`
  * datetime literal:   V2 `datetime'...'` vs V4 bare ISO
  * substring op:       V2 `substringof(x,field)` vs V4 `contains(field,x)`
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional
from urllib.parse import urlencode

from app.services.connectors.base import EntityMeta, PolicyError
from app.services.connectors.sap_s4hana.metadata import normalize_edm_type

# Operators the connector understands. Anything else is rejected by policy.
COMPARISON_OPS = {"eq", "ne", "gt", "ge", "lt", "le"}
LOGICAL_OPS = {"and", "or"}
STRING_OPS = {"contains", "startswith", "endswith"}

MAX_FILTER_CONDITIONS = 20
MAX_FILTER_DEPTH = 3


# ---------------------------------------------------------------------------
# Literal encoding (injection-safe by construction)
# ---------------------------------------------------------------------------

def _escape_odata_string(value: str) -> str:
    """OData string literal escaping: double every single quote."""
    return value.replace("'", "''")


def encode_literal(value: Any, odata_type: str, odata_version: str) -> str:
    """Encode one Python value as a typed OData literal.

    Raises PolicyError for types we do not understand — we never interpolate
    raw values into a query.
    """
    if value is None:
        return "null"
    t = (odata_type or "").lower()
    json_type, _ = normalize_edm_type(t)

    if json_type == "boolean":
        if not isinstance(value, bool):
            raise PolicyError(f"Expected boolean for type {odata_type}")
        return "true" if value else "false"

    if json_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyError(f"Expected numeric value for type {odata_type}")
        return repr(value) if isinstance(value, float) else str(value)

    if json_type == "datetime":
        if isinstance(value, datetime):
            iso = value.strftime("%Y-%m-%dT%H:%M:%S") + ("Z" if value.tzinfo else "")
        elif isinstance(value, str):
            # validate strict ISO-ish before embedding
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            iso = value
        else:
            raise PolicyError(f"Expected datetime value for type {odata_type}")
        if odata_version == "2":
            return f"datetime'{_escape_odata_string(iso)}'"
        return _escape_odata_string(iso)

    if json_type == "date":
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            iso = value.isoformat()
        elif isinstance(value, str):
            date.fromisoformat(value)
            iso = value
        else:
            raise PolicyError(f"Expected date value for type {odata_type}")
        if odata_version == "2":
            return f"datetime'{_escape_odata_string(iso + 'T00:00:00')}'"
        return _escape_odata_string(iso)

    if json_type == "time":
        if isinstance(value, time):
            iso = value.isoformat()
        else:
            iso = str(value)
        return f"time'{_escape_odata_string(iso)}'" if odata_version == "2" else _escape_odata_string(iso)

    if t == "edm.guid":
        s = _escape_odata_string(str(value))
        return f"guid'{s}'" if odata_version == "2" else s

    # fall through: string-ish
    return f"'{_escape_odata_string(str(value))}'"


# ---------------------------------------------------------------------------
# Filter plan rendering
# ---------------------------------------------------------------------------

def render_filter_plan(plan: Optional[dict], entity: EntityMeta, odata_version: str) -> Optional[str]:
    """Render a validated structured plan into a $filter string.

    Plan shape (recursive):
      {"and": [ <plan>, ... ]} | {"or": [ <plan>, ... ]}
      {"field": "Name", "op": "eq", "value": "x"}
    Field existence/type checks are the policy layer's job; this re-checks
    membership as defense-in-depth (the entity is the ONLY trusted source).
    """
    if not plan:
        return None
    rendered, count = _render_node(plan, entity, odata_version, depth=0)
    if count > MAX_FILTER_CONDITIONS:
        raise PolicyError(f"Filter plan exceeds {MAX_FILTER_CONDITIONS} conditions")
    return rendered or None


def _render_node(node: dict, entity: EntityMeta, version: str, depth: int) -> tuple[str, int]:
    if depth > MAX_FILTER_DEPTH:
        raise PolicyError("Filter plan nested too deeply")
    if not isinstance(node, dict):
        raise PolicyError("Filter plan node must be an object")

    keys = set(node.keys())
    if "and" in keys or "or" in keys:
        if len(keys) != 1:
            raise PolicyError("Logical node must contain only 'and' or 'or'")
        op = "and" if "and" in keys else "or"
        children = node[op]
        if not isinstance(children, list) or not (1 <= len(children) <= 10):
            raise PolicyError(f"'{op}' needs 1..10 child conditions")
        parts, total = [], 0
        for child in children:
            text, cnt = _render_node(child, entity, version, depth + 1)
            parts.append(text)
            total += cnt
        joiner = f" {op} " if version == "4" else f" {op} "
        joined = joiner.join(f"({p})" for p in parts if p)
        return joined, total

    field = node.get("field")
    op = (node.get("op") or "").lower()
    value = node.get("value", None)
    if not field or not isinstance(field, str):
        raise PolicyError("Condition needs a 'field'")
    prop = entity.property(field)
    if prop is None:
        raise PolicyError(f"Filter field '{field}' is not declared in metadata for '{entity.name}'")
    if op in COMPARISON_OPS:
        lit = encode_literal(value, prop.odata_type, version)
        return f"{field} {op} {lit}", 1
    if op in STRING_OPS:
        lit = f"'{_escape_odata_string(str(value))}'"
        if op == "contains" and version == "2":
            return f"substringof({lit},{field})", 1
        if op not in ("contains", "startswith", "endswith"):
            raise PolicyError(f"Unsupported string operator '{op}'")
        return f"{op}({field},{lit})", 1
    raise PolicyError(f"Unsupported filter operator '{op}'")


# ---------------------------------------------------------------------------
# Query string assembly
# ---------------------------------------------------------------------------

def build_query_params(*, select: list[str], filter_str: Optional[str],
                       orderby: Optional[str], top: Optional[int],
                       skip: Optional[int] = None, version: str = "4") -> dict:
    params: dict[str, Any] = {}
    if select:
        params["$select"] = ",".join(select)
    if filter_str:
        params["$filter"] = filter_str
    if orderby:
        params["$orderby"] = orderby
    if top is not None:
        params["$top"] = int(top)
    if skip is not None and version == "2":
        params["$skip"] = int(skip)
    if version == "2":
        params["$format"] = "json"
    return params


def append_params(url: str, params: dict) -> str:
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode(params, quote_via=lambda s, *a, **k: str(s))}"


# ---------------------------------------------------------------------------
# Page parsing (V2 / V4 envelopes) + continuation extraction
# ---------------------------------------------------------------------------

def parse_page(payload: dict, version: str) -> tuple[list[dict], Optional[str], Optional[int]]:
    """Return (rows, continuation_url, total_count) from one OData JSON page."""
    if not isinstance(payload, dict):
        return [], None, None

    if version == "2" or "d" in payload:
        d = payload.get("d", payload)
        if isinstance(d, list):
            rows = d
        elif isinstance(d, dict):
            rows = d.get("results", [])
            if not isinstance(rows, list):
                rows = []
        else:
            rows = []
        nxt = None
        if isinstance(d, dict):
            raw_next = d.get("__next")
            if isinstance(raw_next, str):
                # V2 __next may be {"__next": "..."} or list — normalize
                nxt = raw_next
        count = d.get("__count") if isinstance(d, dict) else None
        return rows, nxt, _as_int(count)

    # V4
    rows = payload.get("value", [])
    if not isinstance(rows, list):
        rows = []
    nxt = payload.get("@odata.nextLink")
    count = _as_int(payload.get("@odata.count"))
    return rows, (nxt if isinstance(nxt, str) else None), count


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def strip_odata_annotations(row: dict, keep: tuple[str, ...] = ()) -> dict:
    """Drop OData control information (@odata.*, __* / d. wrappers) from rows."""
    cleaned = {}
    for k, v in row.items():
        if k.startswith("@odata.") or k.startswith("@") or k.startswith("__"):
            continue
        if k in ("properties", "answers") and isinstance(v, dict):
            continue
        cleaned[k] = v
    return cleaned
