"""Automated tests for Feature 1 (Multi-Thread Investigation) + Feature 3
(Root-Cause Exploration Engine).

Two tiers:
- Pure-logic (no DB): the root-cause decomposition math, ranking, reconciliation
  and honest (no-causation) reporting. These always run.
- Integration (live PostgreSQL): creating an investigation from a real finding,
  parallel branches with independent context, evidence turns, comparison and a
  real root-cause run. These skip gracefully when the DB is unavailable so the
  suite never fabricates results.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers / availability
# ---------------------------------------------------------------------------
def _target_db_available() -> bool:
    try:
        from app.services.query_executor import QueryExecutor
        from app.services.role_service import resolve_user_context
        res = QueryExecutor.from_settings().execute("SELECT 1 AS ok", user_context=resolve_user_context("executive"))
        return bool(res.success)
    except Exception:
        return False


def _app_db_available() -> bool:
    try:
        from app.database import init_app_db
        init_app_db()
        return True
    except Exception:
        return False


def _fake_profile():
    from app.services.discovery_service import SchemaProfile
    p = SchemaProfile()
    p.schema_name = "sales"
    p.fact_table = "sales_order_items"
    p.parent_table = "sales_orders"
    p.parent_pk = "order_id"
    p.fact_to_parent_fk = "order_id"
    p.time_column = "order_date"
    p.status_column = "status"
    p.status_filter_value = "completed"
    p.measures = [{"key": "net_revenue", "label": "Net revenue", "expr": "SUM(f.amount)"}]
    p.dimensions = [{"table": "product_catalog", "column": "category", "label": "Category", "usefulness": 9.0}]
    p.aliases = {"sales_order_items": "f", "sales_orders": "p", "product_catalog": "d0"}
    p.extra_joins = {}
    return p


def _service_with_stubbed_queries(rows):
    """Build a RootCauseService that uses a fixed profile + canned rows (no DB)."""
    from app.services.root_cause_service import RootCauseService
    from app.services.discovery_service import DiscoveryService
    svc = RootCauseService.__new__(RootCauseService)
    svc.role = "executive"
    disc = DiscoveryService.__new__(DiscoveryService)
    disc._build_profile = lambda ctx: _fake_profile()
    svc.discovery = disc
    svc._run = lambda sql, ctx: rows
    return svc


# ---------------------------------------------------------------------------
# Pure-logic tests (no database required)
# ---------------------------------------------------------------------------
def test_root_cause_contributions_reconcile_and_rank():
    """Segment changes must sum to the total change, be ranked by impact, and a
    dominant contributor must be reported WITHOUT a causal claim."""
    rows = [
        # period, segment, value
        {"period": "2026-07", "segment": "Electronics", "value": 1000, "orders": 10},
        {"period": "2026-07", "segment": "Apparel", "value": 800, "orders": 8},
        {"period": "2026-07", "segment": "Home", "value": 500, "orders": 5},
        {"period": "2026-08", "segment": "Electronics", "value": 400, "orders": 4},
        {"period": "2026-08", "segment": "Apparel", "value": 780, "orders": 8},
        {"period": "2026-08", "segment": "Home", "value": 520, "orders": 5},
    ]
    svc = _service_with_stubbed_queries(rows)
    finding = {
        "role": "executive", "metric_name": "Net revenue", "dimension_name": "Category",
        "calculation": {"measure_key": "net_revenue"}, "baseline_value": 2300, "current_value": 1700,
    }
    res = svc.analyze_finding(finding)

    assert res["status"] == "ok"
    contribs = res["contributions"]
    # ranked by absolute change desc
    changes = [abs(c["change_abs"]) for c in contribs]
    assert changes == sorted(changes, reverse=True)
    assert contribs[0]["segment"] == "Electronics"  # biggest mover
    # reconciliation: sum of segment changes == total change
    total = sum(c["change_abs"] for c in contribs)
    assert abs(total - res["total_change_abs"]) < 1e-6
    assert res["total_change_abs"] == pytest.approx(1700 - 2300, abs=1e-6)
    # contribution percentages account for ~100% of the change
    assert abs(sum(c["contribution_pct"] for c in contribs) - 100.0) < 1.0
    # honesty: no causation language
    assert "not a proven cause" in res["summary"].lower() or "cause remains undetermined" in res["summary"].lower()
    assert res["evidence"]["sql"].strip().upper().startswith("SELECT")
    assert res["evidence"]["limitations"]


def test_root_cause_reports_undetermined_without_dimensions():
    """When no analytical dimension is available, the engine must say the cause
    is undetermined rather than inventing one."""
    from app.services.root_cause_service import RootCauseService
    from app.services.discovery_service import DiscoveryService
    svc = RootCauseService.__new__(RootCauseService)
    svc.role = "executive"
    disc = DiscoveryService.__new__(DiscoveryService)
    prof = _fake_profile()
    prof.dimensions = []  # no decomposition axis
    disc._build_profile = lambda ctx: prof
    svc.discovery = disc
    svc._run = lambda sql, ctx: []
    res = svc.analyze_finding({"role": "executive", "dimension_name": "Category"})
    assert res["status"] == "undetermined"
    assert res["contributions"] == []
    assert res["reconciles"] is False


def test_root_cause_insufficient_periods_is_honest():
    """Fewer than two comparable periods must not fabricate a decomposition."""
    rows = [{"period": "2026-07", "segment": "Electronics", "value": 100, "orders": 1}]
    svc = _service_with_stubbed_queries(rows)
    res = svc.analyze_finding({"role": "executive", "dimension_name": "Category"})
    assert res["status"] == "undetermined"


# ---------------------------------------------------------------------------
# Integration tests (live databases)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_investigation_from_finding_parallel_branches_and_rootcause():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # find an existing persisted finding to investigate
        fr = client.get("/api/v1/discover/findings?status=active&limit=10")
        assert fr.status_code == 200
        findings = fr.json().get("findings", [])
        if not findings:
            pytest.skip("no discovery findings available to investigate")
        finding_id = findings[0]["id"]

        # 1) open investigation from the finding (auto runs root-cause)
        r = client.post("/api/v1/investigations", json={"finding_id": finding_id, "role": "executive", "run_root_cause": True})
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["finding_id"] == finding_id
        assert inv["branch_count"] >= 1
        session_ids = [b["session_id"] for b in inv["branches"]]
        assert len(session_ids) == len(set(session_ids)), "each branch must own an independent session"
        assert all(b["session_id"] for b in inv["branches"])
        # authorization preserved
        assert inv["role"] == "executive"

        # 2) add a parallel branch manually
        br = client.post(f"/api/v1/investigations/{inv['id']}/branches",
                         json={"title": "Order volume vs AOV", "question": "Split the change into order count vs average order value."})
        assert br.status_code == 200, br.text
        new_branch = br.json()
        assert new_branch["session_id"] not in session_ids, "new branch needs its own context"

        # 3) fetch evidence turns for a branch (empty until a query runs, but endpoint works)
        tr = client.get(f"/api/v1/investigations/{inv['id']}/branches/{new_branch['id']}/turns")
        assert tr.status_code == 200
        assert tr.json()["branch"]["id"] == new_branch["id"]
        assert isinstance(tr.json()["turns"], list)

        # 4) rename + archive a branch
        pr = client.patch(f"/api/v1/investigations/{inv['id']}/branches/{new_branch['id']}",
                          json={"title": "Renamed branch", "status": "archived"})
        assert pr.status_code == 200
        assert pr.json()["title"] == "Renamed branch"
        assert pr.json()["status"] == "archived"

        # 5) compare branches
        all_ids = [b["id"] for b in inv["branches"]] + [new_branch["id"]]
        cr = client.post(f"/api/v1/investigations/{inv['id']}/compare", json={"branch_ids": all_ids})
        assert cr.status_code == 200
        assert cr.json()["compared"] == len(all_ids)

        # 6) standalone root-cause run returns reconciling contributions or honest undetermined
        rr = client.post("/api/v1/root-cause/runs", json={"finding_id": finding_id, "spawn_branches": False})
        assert rr.status_code == 200, rr.text
        rc = rr.json()
        assert rc["status"] in ("ok", "undetermined") if "status" in rc else True
        contribs = rc.get("contributions", [])
        if contribs and rc.get("total_change_abs") is not None:
            ssum = sum(c["change_abs"] for c in contribs)
            assert abs(ssum - rc["total_change_abs"]) < max(abs(rc["total_change_abs"]) * 0.01, 1.0)


@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_investigation_requires_existing_finding():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/api/v1/investigations", json={"finding_id": "does-not-exist"})
        assert r.status_code == 404
        g = client.get("/api/v1/investigations/nonexistent-id")
        assert g.status_code == 404
