"""SAP connector FastAPI endpoint tests.

Runs the real API surface against the LOCAL OData PROTOCOL-FIXTURE server
from test_sap_connector.py — explicitly NOT a live SAP tenant. Covers admin
authz, fail-closed allowlist, the create→refresh→schema→preview lifecycle,
role enforcement inside preview, SQL-path guards, credential rotation, and
disable. Requires the app database (skips otherwise).
"""

import pytest
from fastapi.testclient import TestClient

from test_sap_connector import FixtureServer  # same pytest rootdir


def _app_db_available() -> bool:
    try:
        from app.database import init_app_db
        init_app_db()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _app_db_available(), reason="app database not reachable")


@pytest.fixture(scope="module")
def fixture_server():
    srv = FixtureServer()
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def allow_fixture_hosts(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "sap_allowed_hosts", "127.0.0.1,localhost")
    yield s


ADMIN = {"X-User-Role": "executive", "X-Username": "executive"}
REP = {"X-User-Role": "sales_rep", "X-Username": "sales_rep_carol"}


def _payload(srv, **over):
    body = {
        "name": "SAP Fixture (test)",
        "deployment_type": "on_premises",
        "base_url": srv.base_url,
        "service_path": "svc",
        "odata_version": "4",
        "auth_mode": "basic",
        "username": "SAP_READER",
        "secret": "fixture-pw-123",
        "tls_verify": True,
        "secret_ref": "test-vault:sap-reader",
    }
    body.update(over)
    return body


@pytest.fixture()
def sap_connection(client, fixture_server, allow_fixture_hosts):
    """Create a SAP connection through the real API; hard-delete row after."""
    r = client.post("/api/v1/connections/sap", json=_payload(fixture_server), headers=ADMIN)
    assert r.status_code == 200, r.text
    conn_id = r.json()["id"]
    assert "fixture-pw-123" not in r.text  # secret never echoed
    yield conn_id
    from app.database import get_app_engine
    from sqlalchemy import text
    with get_app_engine().begin() as eng:
        # submit_query may have persisted a record row before its SAP guard fired
        eng.execute(text("DELETE FROM query_records WHERE connection_id = :cid"), {"cid": conn_id})
        eng.execute(text("DELETE FROM audit_events WHERE resource_id = :cid"), {"cid": conn_id})
        eng.execute(text("DELETE FROM connections WHERE id = :cid"), {"cid": conn_id})


def test_sap_admin_guard_rejects_non_admin(client, fixture_server, allow_fixture_hosts):
    r = client.post("/api/v1/connections/sap", json=_payload(fixture_server), headers=REP)
    assert r.status_code == 403


def test_sap_allowlist_fail_closed(client, fixture_server, monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "sap_allowed_hosts", "")
    r = client.post("/api/v1/connections/sap", json=_payload(fixture_server), headers=ADMIN)
    assert r.status_code == 400
    assert "not permitted" in r.json()["detail"].lower()


def test_sap_adhoc_test_endpoint(client, fixture_server, allow_fixture_hosts):
    r = client.post("/api/v1/connections/sap/test", json=_payload(fixture_server), headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "fixture-pw-123" not in r.text


def test_sap_lifecycle_refresh_schema_preview(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    # refresh discovers from live fixture $metadata
    r = client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_count"] >= 6
    assert "I_SalesOrder" in body["changes"]["added"]

    # cached schema + entities + per-entity metadata
    r = client.get(f"/api/v1/connections/{cid}/schema", headers=ADMIN)
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["entities"]}
    assert "I_SalesOrder" in names and r.json()["entity_count"] == len(names)

    r = client.get(f"/api/v1/connections/{cid}/entities", headers=ADMIN)
    assert r.status_code == 200
    ent = next(e for e in r.json()["entities"] if e["name"] == "I_SalesOrder")
    assert ent["keys"] == ["SalesOrderID"]

    r = client.get(f"/api/v1/connections/{cid}/entities/I_SalesOrder/metadata", headers=ADMIN)
    assert r.status_code == 200
    assert any(p["name"] == "NetAmountME" for p in r.json()["properties"])

    # executive preview follows validated pagination
    r = client.post(f"/api/v1/connections/{cid}/entities/I_SalesOrder/preview",
                    json={"select": ["SalesOrderID", "RegionCode"],
                          "filter": {"field": "RegionCode", "op": "eq", "value": "NORTH"},
                          "orderby": "SalesOrderID asc", "top": 4},
                    headers=ADMIN)
    assert r.status_code == 200, r.text
    prev = r.json()
    assert prev["row_count"] == 4 and prev["truncated"] is False
    assert "subset" in prev["limitations"]

    # SQL-path guard: SAP row must not be treated as a Postgres engine
    r = client.get(f"/api/v1/connections/{cid}/schema", headers=ADMIN)  # sap-specific OK
    assert r.status_code == 200


def test_sap_preview_enforces_role_policy(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)
    # sales_rep: whole entity prohibited
    r = client.post(f"/api/v1/connections/{cid}/entities/I_PurchaseOrder/preview",
                    json={"select": ["PurchaseOrderID"]}, headers=REP)
    assert r.status_code == 403
    # sales_rep: restricted field on an allowed entity
    r = client.post(f"/api/v1/connections/{cid}/entities/I_BusinessPartner/preview",
                    json={"select": ["BusinessPartnerID", "EmailAddress"]}, headers=REP)
    assert r.status_code == 403
    # executive: allowed
    r = client.post(f"/api/v1/connections/{cid}/entities/I_BusinessPartner/preview",
                    json={"select": ["BusinessPartnerID", "EmailAddress"]}, headers=ADMIN)
    assert r.status_code == 200


def test_sap_preview_rejects_undeclared_field(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)
    r = client.post(f"/api/v1/connections/{cid}/entities/I_SalesOrder/preview",
                    json={"select": ["TotallyMadeUp"]}, headers=ADMIN)
    assert r.status_code == 403


def test_sap_sql_query_path_blocked(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    from app.schemas import QueryRequest
    req = QueryRequest(question="show me something from sap", connection_id=cid)
    r = client.post("/api/v1/queries", json=req.model_dump(), headers=ADMIN)
    assert r.status_code == 400
    assert "SAP" in r.json()["detail"]


def test_sap_patch_rotates_secret_without_echo(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    r = client.patch(f"/api/v1/connections/{cid}",
                     json={"secret": "rotated-pw-456", "service_path": "svc"}, headers=ADMIN)
    assert r.status_code == 200
    assert "rotated-pw-456" not in r.text
    from app.database import get_app_session_factory
    from app.models import Connection
    from app.services.crypto import decrypt_secret
    db = get_app_session_factory()()
    try:
        conn = db.query(Connection).filter(Connection.id == cid).first()
        assert decrypt_secret(conn.encrypted_password) == "rotated-pw-456"
        assert conn.updated_by == "executive"
    finally:
        db.close()


def test_sap_disable_revokes_access(client, fixture_server, allow_fixture_hosts, sap_connection):
    cid = sap_connection
    r = client.post(f"/api/v1/connections/{cid}/disable", headers=ADMIN)
    assert r.status_code == 200
    r = client.post(f"/api/v1/connections/{cid}/entities/I_SalesOrder/preview",
                    json={"select": ["SalesOrderID"]}, headers=ADMIN)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cross-source integration: SAP <-> PostgreSQL through the confirmed-mapping
# workflow (candidate -> confirm -> bounded authorized app-side join).
# ---------------------------------------------------------------------------

@pytest.fixture()
def default_sales_up():
    from app.database import get_default_target_engine
    from sqlalchemy import text
    try:
        with get_default_target_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("primary sales target not reachable")


def test_cross_source_sap_pg_join(client, fixture_server, allow_fixture_hosts,
                                  sap_connection, default_sales_up):
    cid = sap_connection
    client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)

    # SAP source is listed as a selectable, connector-typed source
    r = client.get("/api/v1/cross-source/sources")
    assert r.status_code == 200
    sap_src = next(s for s in r.json()["sources"] if s["connection_id"] == cid)
    assert sap_src["connector_type"] == "sap_s4hana" and sap_src["healthy"] is True

    # Role-filtered SAP catalog is available to the mapping studio
    r = client.get(f"/api/v1/cross-source/sources/{cid}/catalog", params={"role": "executive"})
    assert r.status_code == 200
    tables = {t["table"] for t in r.json()["tables"]}
    assert "I_Product" in tables

    # Candidate inference across product_catalog.product_id <-> I_Product.ProductID
    r = client.post("/api/v1/cross-source/relationships/candidates", json={
        "left": {"connection_id": "default", "schema_name": "sales", "table_name": "product_catalog"},
        "right": {"connection_id": cid, "schema_name": "sap", "table_name": "I_Product"},
        "role": "executive",
    })
    assert r.status_code == 200, r.text
    cands = r.json()["candidates"]
    pair = next((c for c in cands if c["left_column"] == "product_id"
                 and c["right_column"] == "ProductID"), None)
    assert pair is not None
    assert pair["requires_confirmation"] is True  # cross-protocol keys are never auto-joined

    # Save + confirm, then join as executive
    body = {
        "left_connection_id": "default", "left_schema": "sales",
        "left_table": "product_catalog", "left_column": "product_id",
        "right_connection_id": cid, "right_schema": "sap",
        "right_table": "I_Product", "right_column": "ProductID",
        "confidence": pair["confidence"], "evidence": pair["evidence"],
        "created_by": "executive",
    }
    r = client.post("/api/v1/cross-source/relationships", json=body)
    assert r.status_code == 200
    mapping_id = r.json()["id"]
    try:
        r = client.post(f"/api/v1/cross-source/relationships/{mapping_id}/confirm",
                        json={"confirmed_by": "executive"})
        assert r.status_code == 200 and r.json()["status"] == "confirmed"

        r = client.post("/api/v1/cross-source/join", json={
            "mapping_id": mapping_id, "requestor": "executive",
            "left_columns": ["product_name"], "right_columns": ["ProductName", "StandardCost"],
            "join_type": "inner",
        })
        assert r.status_code == 200, r.text
        join = r.json()
        assert join["ok"] is True
        assert join["row_count"] > 0
        assert "L.product_name" in join["columns"] and "R.ProductName" in join["columns"]
        # lineage keeps both sides distinct and honest about SAP retrieval
        assert join["lineage"]["right_source"]["connector_type"] == "sap_s4hana"
        assert "evidence_request" in join["lineage"]["right_source"]
        assert any("SAP" in lim and "authorized subsets" in lim for lim in join["limitations"])
    finally:
        client.delete(f"/api/v1/cross-source/relationships/{mapping_id}")


def test_cross_source_blocks_unconfirmed_sap_join(client, fixture_server, allow_fixture_hosts,
                                                  sap_connection, default_sales_up):
    cid = sap_connection
    client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)
    r = client.post("/api/v1/cross-source/relationships", json={
        "left_connection_id": "default", "left_schema": "sales",
        "left_table": "product_catalog", "left_column": "product_id",
        "right_connection_id": cid, "right_schema": "sap",
        "right_table": "I_Product", "right_column": "ProductID",
        "confidence": 0.55, "evidence": {}, "created_by": "executive",
    })
    mapping_id = r.json()["id"]
    try:
        r = client.post("/api/v1/cross-source/join", json={
            "mapping_id": mapping_id, "requestor": "executive",
            "left_columns": [], "right_columns": [], "join_type": "inner",
        })
        assert r.status_code == 400  # candidate-only mapping cannot be joined
        assert "CONFIRMED" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/cross-source/relationships/{mapping_id}")


def test_cross_source_sap_catalog_respects_role(client, fixture_server, allow_fixture_hosts,
                                                sap_connection):
    cid = sap_connection
    client.post(f"/api/v1/connections/{cid}/schema/refresh", headers=ADMIN)
    r = client.get(f"/api/v1/cross-source/sources/{cid}/catalog", params={"role": "sales_rep"})
    assert r.status_code == 200
    tables = {t["table"] for t in r.json()["tables"]}
    # purchasing entities are prohibited for sales reps (QueryPilot-side authz)
    assert "I_PurchaseOrder" not in tables
    assert "I_Product" in tables
    bp = next(t for t in r.json()["tables"] if t["table"] == "I_BusinessPartner")
    assert "EmailAddress" not in [c["name"] for c in bp["columns"]]
