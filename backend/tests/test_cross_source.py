"""Automated tests for Feature 5 (Cross-System Intelligence).

Two tiers:
- Pure-logic (no DB): type normalization, join-key candidate scoring and the
  controlled application-side join (prefixing, join types, truncation).
- Integration (two live PostgreSQL sources): sources are listed independently,
  catalogs respect per-role authorization, candidate product_id relationships are
  inferred and must be confirmed before use, a confirmed join produces bounded
  results with source-level lineage, and per-source RLS prevents cross-region
  inventory leakage for a restricted requestor. Skips gracefully when the
  secondary 'querypilot_inventory' source is not provisioned.
"""

import pytest


def _app_db_available() -> bool:
    try:
        from app.database import init_app_db
        init_app_db()
        return True
    except Exception:
        return False


def _two_sources_available() -> bool:
    """Both the primary sales target and the secondary inventory source reachable."""
    try:
        from app.database import create_target_engine, get_default_target_engine
        from sqlalchemy import text
        with get_default_target_engine().connect() as c:
            c.execute(text("SELECT 1"))
        eng = create_target_engine(
            host="localhost", port=5433, dbname="querypilot_inventory",
            user="inventory_readonly", password="inventory_readonly_dev",
        )
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


def _col(name, dtype, pk=False, fk=False):
    return {"name": name, "data_type": dtype, "is_primary_key": pk, "is_foreign_key": fk}


# ---------------------------------------------------------------------------
# Pure-logic
# ---------------------------------------------------------------------------
def test_norm_type_categories():
    from app.services.cross_source_service import _norm_type
    assert _norm_type("SERIAL") == "int"
    assert _norm_type("INTEGER") == "int"
    assert _norm_type("NUMERIC(10,2)") == "num"
    assert _norm_type("VARCHAR(200)") == "str"
    assert _norm_type("TIMESTAMP WITH TIME ZONE") == "temporal"


def test_score_pk_fk_identical_name_is_auto_joinable():
    from app.services.cross_source_service import score_join_candidate
    conf, ev, requires = score_join_candidate(
        _col("product_id", "INTEGER", pk=True), _col("product_id", "INTEGER", fk=True)
    )
    assert conf >= 0.9
    assert requires is False
    assert ev["compatible"] is True


def test_score_incompatible_types_rejected():
    from app.services.cross_source_service import score_join_candidate
    conf, ev, requires = score_join_candidate(
        _col("phone", "VARCHAR(30)"), _col("region_id", "INTEGER")
    )
    assert conf == 0.0
    assert ev["compatible"] is False
    assert requires is True


def test_score_name_only_requires_confirmation():
    from app.services.cross_source_service import score_join_candidate
    conf, ev, requires = score_join_candidate(
        _col("region_id", "INTEGER"), _col("region_id", "INTEGER")
    )
    assert conf == 0.8
    assert requires is True  # uncertain mapping must be explicitly confirmed


def test_appside_join_inner_with_prefixes():
    from app.services.cross_source_service import appside_join
    left = [
        {"product_id": 1, "product_name": "A", "region_id": 1},
        {"product_id": 2, "product_name": "B", "region_id": 2},
    ]
    right = [
        {"product_id": 1, "units_on_hand": 10, "region_id": 1},
        {"product_id": 3, "units_on_hand": 5, "region_id": 3},
    ]
    joined, truncated = appside_join(left, right, "product_id", "product_id", "inner")
    assert truncated is False
    assert len(joined) == 1
    row = joined[0]
    # both sides carry region_id -> must be namespaced, not overwritten
    assert row["L.product_id"] == 1 and row["R.product_id"] == 1
    assert row["L.region_id"] == 1 and row["R.region_id"] == 1
    assert row["L.product_name"] == "A" and row["R.units_on_hand"] == 10


def test_appside_join_left_preserves_unmatched_and_truncates():
    from app.services.cross_source_service import appside_join
    left = [{"k": i} for i in range(5)]
    right = [{"k": 0, "v": "x"}]
    joined, truncated = appside_join(left, right, "k", "k", "left")
    assert len(joined) == 5  # all left rows preserved
    assert truncated is False

    capped, truncated2 = appside_join(left, right, "k", "k", "left", max_rows=2)
    assert len(capped) == 2
    assert truncated2 is True


# ---------------------------------------------------------------------------
# Integration: two live PostgreSQL sources
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.skipif(not (_app_db_available() and _two_sources_available()),
                    reason="two live PostgreSQL sources not available")
def test_sources_listed_independently(client):
    resp = client.get("/api/v1/cross-source/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_count"] >= 2
    assert data["healthy_count"] >= 2
    assert data["strategy"] == "controlled_application_side_join"
    ids = {s["connection_id"] for s in data["sources"]}
    assert "default" in ids


@pytest.mark.skipif(not (_app_db_available() and _two_sources_available()),
                    reason="two live PostgreSQL sources not available")
def test_catalog_respects_per_role_authorization(client):
    # regional manager must not see cost_price (a sales-restricted column)
    cat = client.get("/api/v1/cross-source/sources/default/catalog?role=regional_manager").json()
    pc = next((t for t in cat["tables"] if t["table"] == "product_catalog"), None)
    assert pc is not None
    colnames = {c["name"] for c in pc["columns"]}
    assert "unit_price" in colnames
    assert "cost_price" not in colnames


@pytest.mark.skipif(not (_app_db_available() and _two_sources_available()),
                    reason="two live PostgreSQL sources not available")
def _inventory_connection_id(client) -> str:
    data = client.get("/api/v1/cross-source/sources").json()
    for s in data["sources"]:
        if s.get("schema") == "inventory":
            return s["connection_id"]
    pytest.skip("inventory source not registered")


@pytest.mark.skipif(not (_app_db_available() and _two_sources_available()),
                    reason="two live PostgreSQL sources not available")
def test_candidate_infer_confirm_join_e2e(client):
    inv_id = _inventory_connection_id(client)

    cand = client.post("/api/v1/cross-source/relationships/candidates", json={
        "left": {"connection_id": "default", "schema_name": "sales", "table_name": "product_catalog"},
        "right": {"connection_id": inv_id, "schema_name": "inventory", "table_name": "product_stock"},
        "role": "executive",
    })
    assert cand.status_code == 200, cand.text
    candidates = cand.json()["candidates"]
    pid = [c for c in candidates if c["left_column"] == "product_id" and c["right_column"] == "product_id"]
    assert pid, "product_id relationship should be inferred"
    top = pid[0]
    assert top["requires_confirmation"] is True

    saved = client.post("/api/v1/cross-source/relationships", json={
        "left_connection_id": "default", "left_schema": "sales", "left_table": "product_catalog",
        "left_column": "product_id",
        "right_connection_id": inv_id, "right_schema": "inventory", "right_table": "product_stock",
        "right_column": "product_id",
        "confidence": top["confidence"], "evidence": top["evidence"], "created_by": "executive",
    })
    assert saved.status_code == 200, saved.text
    mid = saved.json()["id"]
    assert saved.json()["status"] == "candidate"

    join = client.post("/api/v1/cross-source/join", json={
        "mapping_id": mid, "requestor": "executive",
        "left_columns": ["product_name", "unit_price"],
        "right_columns": ["warehouse_code", "units_on_hand"], "join_type": "inner",
    })
    # an unconfirmed candidate must not be joined
    assert join.status_code == 400, join.text
    assert "CONFIRMED" in join.text or "confirm" in join.text.lower()

    confirmed = client.post(f"/api/v1/cross-source/relationships/{mid}/confirm", json={"confirmed_by": "executive"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    join2 = client.post("/api/v1/cross-source/join", json={
        "mapping_id": mid, "requestor": "executive",
        "left_columns": ["product_name", "unit_price"],
        "right_columns": ["warehouse_code", "units_on_hand"], "join_type": "inner",
    })
    assert join2.status_code == 200, join2.text
    out = join2.json()
    assert out["ok"] is True
    assert out["row_count"] > 0
    assert out["columns"][:1] == ["L.product_id"]
    lin = out["lineage"]
    assert lin["left_source"]["connection_id"] == "default"
    assert lin["right_source"]["connection_id"] == inv_id
    assert any("application" in lim for lim in out["limitations"])
    # cleanup
    client.delete(f"/api/v1/cross-source/relationships/{mid}")


@pytest.mark.skipif(not (_app_db_available() and _two_sources_available()),
                    reason="two live PostgreSQL sources not available")
def test_join_applies_per_source_rls_no_region_leak(client):
    inv_id = _inventory_connection_id(client)
    saved = client.post("/api/v1/cross-source/relationships", json={
        "left_connection_id": "default", "left_schema": "sales", "left_table": "product_catalog",
        "left_column": "product_id",
        "right_connection_id": inv_id, "right_schema": "inventory", "right_table": "product_stock",
        "right_column": "product_id", "confidence": 0.8, "created_by": "executive",
    })
    mid = saved.json()["id"]
    client.post(f"/api/v1/cross-source/relationships/{mid}/confirm", json={"confirmed_by": "executive"})

    # regional manager (North, region 1) must only receive region-1 inventory rows
    join = client.post("/api/v1/cross-source/join", json={
        "mapping_id": mid, "requestor": "regional_manager_north",
        "left_columns": ["product_name"],
        "right_columns": ["region_id", "warehouse_code", "units_on_hand"], "join_type": "inner",
    })
    assert join.status_code == 200, join.text
    out = join.json()
    assert out["ok"] is True
    assert all(r["R.region_id"] == 1 for r in out["rows"]), "cross-region inventory leak"

    client.delete(f"/api/v1/cross-source/relationships/{mid}")


@pytest.mark.skipif(not _app_db_available(), reason="live app DB not available")
def test_unknown_source_returns_404(client):
    resp = client.get("/api/v1/cross-source/sources/does-not-exist/catalog")
    assert resp.status_code == 404
