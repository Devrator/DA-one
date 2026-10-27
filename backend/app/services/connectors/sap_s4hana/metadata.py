"""EDMX ($metadata) parsing for OData V2 and V4.

We parse the REAL metadata document the SAP gateway returns and normalize it
into EntityMeta/PropertyMeta structures. We never invent entities or fields:
anything not declared in EDMX is marked as NOT declared (there is no inference
in the parser itself).

V2 and V4 use different XML namespaces but the same CSDL element names, so we
match on element LOCAL NAMES and ignore namespaces entirely — one parser,
both protocol versions.
"""

from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from typing import Optional

from app.services.connectors.base import EntityMeta, PropertyMeta, ServiceInfo

# ---------------------------------------------------------------------------
# Edm.* type normalization
# ---------------------------------------------------------------------------

_EDM_TYPE_MAP = {
    "edm.string": ("string", False),
    "edm.char": ("string", False),
    "edm.text": ("string", False),
    "edm.guid": ("guid", False),
    "edm.boolean": ("boolean", False),
    "edm.byte": ("number", True),
    "edm.sbyte": ("number", True),
    "edm.int16": ("number", True),
    "edm.int32": ("number", True),
    "edm.int64": ("number", True),
    "edm.single": ("number", True),
    "edm.double": ("number", True),
    "edm.decimal": ("number", True),
    "edm.date": ("date", False),
    "edm.time": ("time", False),
    "edm.datetime": ("datetime", False),        # V2
    "edm.datetimeoffset": ("datetime", False),  # V4
}

# Types that must never be shown in analytical $select lists by default
# (large binary payloads).
_LARGE_BINARY_PREFIXES = ("edm.binary",)


def normalize_edm_type(edm_type: str) -> tuple[str, bool]:
    """Map an Edm type to (json_type, is_numeric). Collection<T> unwrapped."""
    t = (edm_type or "").strip().lower()
    if t.startswith("collection(") and t.endswith(")"):
        t = t[len("collection("):-1].strip()
    if t in _EDM_TYPE_MAP:
        json_type, numeric = _EDM_TYPE_MAP[t]
        return json_type, numeric
    if t.startswith(_LARGE_BINARY_PREFIXES):
        return "binary", False
    # Complex types / enums: keep as string-ish, declared by real metadata.
    return "string", False


def is_large_binary(edm_type: str) -> bool:
    return (edm_type or "").strip().lower().startswith(_LARGE_BINARY_PREFIXES)


# ---------------------------------------------------------------------------
# EDMX parsing (namespace-agnostic, V2 + V4)
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Strip {namespace} from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


# XML documents from a remote gateway are UNTRUSTED input. A hardened guard
# rejects DTDs / entity declarations up-front (legitimate EDMX never contains
# them), which neutralizes entity-expansion and external-entity attacks without
# an extra dependency. Combined with the per-response byte cap in the client,
# resource exhaustion stays bounded.
_DTD_GUARD = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _assert_no_dtd(xml_text: str) -> None:
    if _DTD_GUARD.search(xml_text):
        raise ValueError("$metadata document contains a DTD/entity declaration — refused")


def _attr(elem: ET.Element, name: str) -> Optional[str]:
    """Find an attribute by local name (namespaces vary between V2/V4/SAP)."""
    for k, v in elem.attrib.items():
        if _local(k) == name:
            return v
    return None


def _findall_local(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _local(c.tag) == name]


def _iter_local(root: ET.Element, name: str) -> list[ET.Element]:
    """All elements with this local name at ANY depth (Edmx > DataServices >
    Schema nesting differs between producer toolkits, so we never assume)."""
    return [c for c in root.iter() if _local(c.tag) == name]


def _first(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _parse_entity_type(elem: ET.Element) -> tuple[str, EntityMeta]:
    """Parse one <EntityType> into an EntityMeta (entity set name filled later)."""
    type_name = elem.get("Name", "")
    keys: list[str] = []
    props: list[PropertyMeta] = []

    key_elem = _first(elem, "Key")
    if key_elem is not None:
        for pref in _findall_local(key_elem, "PropertyRef"):
            pname = pref.get("Name")
            if pname:
                keys.append(pname)

    for p in _findall_local(elem, "Property"):
        edm_type = p.get("Type", "Edm.String")
        json_type, _numeric = normalize_edm_type(edm_type)
        nullable = (p.get("Nullable", "true") or "true").lower() != "false"
        readonly = False
        updatable = _attr(p, "updatable")   # V2 sap/m:updatable="false"
        readable = _attr(p, "readable")
        if updatable is not None and updatable.lower() == "false":
            readonly = True
        max_len = p.get("MaxLength")
        precision = p.get("Precision")
        scale = p.get("Scale")
        doc = _first(p, "Documentation")
        description = doc.get("Value") if doc is not None else None
        props.append(PropertyMeta(
            name=p.get("Name", ""),
            odata_type=edm_type,
            json_type=json_type,
            nullable=nullable,
            readonly=readonly,
            is_key=p.get("Name", "") in keys,
            max_length=int(max_len) if max_len and max_len.isdigit() else None,
            precision=int(precision) if precision and precision.isdigit() else None,
            scale=int(scale) if scale and scale.isdigit() else None,
            description=description,
        ))
        if readable is not None and readable.lower() == "false":
            props[-1].readonly = True

    navs = [n.get("Name", "") for n in _findall_local(elem, "NavigationProperty") if n.get("Name")]
    for n in _findall_local(elem, "NavigationProperty"):
        # V4 puts Type as attribute; both expose Name.
        if n.get("Name") and n.get("Name") not in navs:
            navs.append(n.get("Name"))

    entity = EntityMeta(
        name="",  # set name assigned from EntityContainer below
        entity_type=type_name,
        keys=keys,
        properties=props,
        navigation=sorted(set(navs)),
        declared=True,
    )
    return type_name, entity


def parse_edmx(xml_text: str) -> dict:
    """Parse a $metadata EDMX document.

    Returns {"entities": [EntityMeta...], "source_version": str,
             "service_version": str} keyed by REAL declarations only.
    Entity sets (the addressable names) come from the EntityContainer; an
    EntityType without a set is NOT addressable and is skipped with a note.
    """
    _assert_no_dtd(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed $metadata XML: {exc}") from exc

    version = root.get("Version", "")  # "1.0" (V2) or "4.0" (V4)
    source_version = f"odata_v{'4' if version.startswith('4') else '2'} (edmx {version or '1.0'})"

    entity_types: dict[str, EntityMeta] = {}
    type_by_name: dict[str, str] = {}
    for schema in _iter_local(root, "Schema"):
        for et_elem in _findall_local(schema, "EntityType"):
            type_name, meta = _parse_entity_type(et_elem)
            if type_name:
                entity_types[type_name] = meta
                type_by_name[type_name.rsplit(".", 1)[-1].lower()] = type_name

    notes: list[str] = []
    entities: list[EntityMeta] = []
    for schema in _iter_local(root, "Schema"):
        for container in _findall_local(schema, "EntityContainer"):
            for es in _findall_local(container, "EntitySet"):
                set_name = es.get("Name", "")
                es_type = es.get("EntityType", "")
                if not set_name:
                    continue
                meta = entity_types.get(es_type)
                if meta is None:
                    # tolerate namespace mismatch: match on short name
                    short = es_type.rsplit(".", 1)[-1].lower()
                    resolved = type_by_name.get(short)
                    if resolved:
                        meta = entity_types.get(resolved)
                if meta is None:
                    notes.append(f"EntitySet '{set_name}' references unknown type '{es_type}' — skipped")
                    continue
                emeta = copy.deepcopy(meta)
                emeta.name = set_name
                sap_count = _attr(es, "count") or _attr(es, "sap:content-count")
                if sap_count and sap_count.isdigit():
                    emeta.count = int(sap_count)
                entities.append(emeta)

    if not entities:
        notes.append("No addressable EntitySets found in metadata document")

    return {"entities": entities, "source_version": source_version,
            "odata_version": "4" if version.startswith("4") else "2", "notes": notes}


# ---------------------------------------------------------------------------
# Service document parsing (both payload flavors)
# ---------------------------------------------------------------------------

def parse_service_document(payload, service_url: str) -> list[ServiceInfo]:
    """Parse an OData service document (V2 'd.results' or V4 'value')."""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    entries = []
    if isinstance(payload, dict):
        if "value" in payload and isinstance(payload["value"], list):
            entries = payload["value"]
        elif "d" in payload and isinstance(payload["d"], dict):
            entries = payload["d"].get("results", [])
    services: list[ServiceInfo] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = e.get("name") or e.get("Name") or ""
        url = e.get("url") or e.get("Uri") or ""
        if name:
            full = url if url.startswith("http") else service_url.rstrip("/") + "/" + url.lstrip("/")
            services.append(ServiceInfo(id=name, name=name, url=full))
    return services


# ---------------------------------------------------------------------------
# Descriptor (de)serialization for caching in Connection.metadata_json
# ---------------------------------------------------------------------------

def descriptor_to_dict(services: list[ServiceInfo], entities: list[EntityMeta],
                       source_version: str, notes: list[str]) -> dict:
    """Serialize discovered metadata for the JSON cache (no secrets, ever)."""
    return {
        "source_version": source_version,
        "services": [{"id": s.id, "name": s.name, "url": s.url, "odata_version": s.odata_version}
                     for s in services],
        "entities": [
            {
                "name": e.name,
                "entity_type": e.entity_type,
                "keys": e.keys,
                "navigation": e.navigation,
                "count": e.count,
                "declared": e.declared,
                "properties": [
                    {
                        "name": p.name, "odata_type": p.odata_type, "json_type": p.json_type,
                        "nullable": p.nullable, "readonly": p.readonly, "is_key": p.is_key,
                        "max_length": p.max_length, "precision": p.precision,
                        "scale": p.scale, "description": p.description,
                    } for p in e.properties
                ],
            } for e in entities
        ],
        "notes": notes,
    }


def descriptor_from_dict(data: dict) -> tuple[list[ServiceInfo], list[EntityMeta], str, list[str]]:
    """Rebuild typed metadata from the cached JSON."""
    services = [ServiceInfo(**s) for s in data.get("services", [])]
    entities: list[EntityMeta] = []
    for e in data.get("entities", []):
        props = [PropertyMeta(**p) for p in e.get("properties", [])]
        entities.append(EntityMeta(
            name=e.get("name", ""), entity_type=e.get("entity_type", ""),
            keys=list(e.get("keys", [])), properties=props,
            navigation=list(e.get("navigation", [])), count=e.get("count"),
            declared=bool(e.get("declared", True)),
        ))
    return services, entities, data.get("source_version", ""), list(data.get("notes", []))
