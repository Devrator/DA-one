"""Automated tests for Feature 2 (What-If Decision Simulator).

Two tiers, mirroring the Feature 1+3 tests:
- Pure-logic (no DB): the deterministic scenario math asserted against
  independently hand-computed expected values, invalid-assumption rejection,
  and honest handling of a missing cost metric. These always run.
- Integration (live PostgreSQL): capabilities probe, a real role-authorized
  baseline pulled from the database, save/duplicate/compare and a
  send-to-investigation round trip. These skip gracefully when the DB is down
  so the suite never fabricates results.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers / availability
# ---------------------------------------------------------------------------
def _target_db_available() -> bool:
    try:
        from app.services.query_executor import QueryExecutor
        from app.services.role_service import resolve_user_context
        res = QueryExecutor.from_settings().execute(
            "SELECT 1 AS ok", user_context=resolve_user_context("executive"))
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


# A synthetic OBSERVED baseline (facts). realized_factor = net/gross.
BASELINE = {
    "units": 1000.0,
    "gross": 50000.0,            # 1000 units * avg_unit_price 50
    "net": 45000.0,              # realized_factor = 0.9
    "orders": 200.0,
    "realized_factor": 0.9,
    "avg_unit_price": 50.0,
    "unit_cost": 30.0,           # cogs baseline = 1000 * 30 = 30000
    "period_label": "all periods",
    "source_metric": {"key": "net_revenue", "label": "Net revenue"},
    "classification": "observed_actual",
}


# ---------------------------------------------------------------------------
# Pure-logic tests: the deterministic math must match hand-computed values
# ---------------------------------------------------------------------------
def test_compute_no_assumptions_reproduces_baseline():
    """At zero assumptions the scenario equals the observed baseline."""
    from app.services.scenario_service import compute_scenario
    r = compute_scenario(BASELINE, {})
    assert r["metrics"]["net_revenue"]["scenario"] == pytest.approx(45000.0, rel=1e-6)
    assert r["metrics"]["gross_revenue"]["scenario"] == pytest.approx(50000.0, rel=1e-6)
    assert r["metrics"]["net_revenue"]["delta_pct"] == pytest.approx(0.0, abs=1e-6)
    # margin baseline = net - cogs = 45000 - 30000 = 15000
    assert r["metrics"]["contribution_margin"]["baseline"] == pytest.approx(15000.0, rel=1e-6)


def test_compute_volume_growth_scales_linearly():
    """+20% volume with nothing else changes scales revenue components by 1.2."""
    from app.services.scenario_service import compute_scenario
    r = compute_scenario(BASELINE, {"order_volume_pct": 20})
    m = r["metrics"]
    assert m["units"]["scenario"] == pytest.approx(1200.0, rel=1e-6)
    assert m["net_revenue"]["scenario"] == pytest.approx(54000.0, rel=1e-6)  # 45000*1.2
    assert m["net_revenue"]["delta_pct"] == pytest.approx(20.0, rel=1e-6)
    # margin scales with volume too (cost is per-unit, revenue net scales): 54000 - 36000 = 18000
    assert m["contribution_margin"]["scenario"] == pytest.approx(18000.0, rel=1e-6)


def test_compute_price_and_discount_combined():
    """Hand-computed: +10% price and +5 discount points.

    units=1000, price=55, gross=55000, realized=0.9-0.05=0.85, net=46750.
    """
    from app.services.scenario_service import compute_scenario
    r = compute_scenario(BASELINE, {"unit_price_pct": 10, "discount_change_points": 5})
    assert r["components"]["scenario_price"] == pytest.approx(55.0, rel=1e-6)
    assert r["components"]["scenario_realized_factor"] == pytest.approx(0.85, rel=1e-6)
    assert r["metrics"]["net_revenue"]["scenario"] == pytest.approx(46750.0, rel=1e-3)


def test_compute_discount_clamped_to_valid_range():
    """A discount increase beyond the realized factor cannot go below 0."""
    from app.services.scenario_service import compute_scenario
    r = compute_scenario(BASELINE, {"discount_change_points": 95})  # 0.9 - 0.95 < 0
    assert r["components"]["scenario_realized_factor"] == pytest.approx(0.0, abs=1e-9)
    assert r["metrics"]["net_revenue"]["scenario"] == pytest.approx(0.0, abs=1e-6)


def test_compute_cost_lever_affects_margin_only():
    """Unit cost +10% lowers margin but leaves net revenue unchanged."""
    from app.services.scenario_service import compute_scenario
    r = compute_scenario(BASELINE, {"unit_cost_pct": 10})
    # cogs = 1000 * 33 = 33000; net unchanged 45000; margin = 12000
    assert r["metrics"]["net_revenue"]["scenario"] == pytest.approx(45000.0, rel=1e-6)
    assert r["metrics"]["contribution_margin"]["scenario"] == pytest.approx(12000.0, rel=1e-6)


def test_missing_cost_is_honest_not_invented():
    """Without a cost metric, margin is None and the limitation is reported."""
    from app.services.scenario_service import compute_scenario
    no_cost = dict(BASELINE)
    no_cost["unit_cost"] = None
    r = compute_scenario(no_cost, {"order_volume_pct": 10})
    assert r["metrics"]["contribution_margin"] is None
    assert any("cost" in lim.lower() for lim in r["limitations"])


def test_simulation_output_distinguishes_facts_assumptions_result():
    """The response must clearly separate observed / assumed / calculated."""
    from app.services.scenario_service import ScenarioService
    svc = ScenarioService.__new__(ScenarioService)  # no DB engines needed
    svc.role = "executive"
    res = svc.simulate(BASELINE, {"order_volume_pct": 15}, name="Upside")
    assert res["ok"] is True
    assert res["classification"] == "calculated_scenario"
    assert res["inputs"]["observed_baseline"]["classification"] == "observed_actual"
    assert res["inputs"]["user_assumptions"] == {"order_volume_pct": 15}
    assert "formulas" in res and "gross" in res["formulas"]
    assert "computed_at" in res


def test_invalid_assumptions_are_rejected():
    from app.services.scenario_service import ScenarioService
    svc = ScenarioService.__new__(ScenarioService)
    svc.role = "executive"
    # out of range volume, unknown lever, and cost lever without cost metric
    bad = dict(BASELINE); bad["unit_cost"] = None
    res = svc.simulate(bad, {"order_volume_pct": 5000, "made_up_lever": 5, "unit_cost_pct": 10})
    assert res["ok"] is False
    joined = " ".join(res["errors"]).lower()
    assert "range" in joined
    assert "made_up_lever" in joined
    assert "unit_cost_pct" in joined


# ---------------------------------------------------------------------------
# Integration tests (live databases)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_capabilities_reports_only_real_levers():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        r = client.get("/api/v1/scenarios/capabilities?role=executive")
        assert r.status_code == 200, r.text
        caps = r.json()
        assert "can_simulate" in caps and "levers" in caps
        keys = {l["key"]: l for l in caps["levers"]}
        # cost lever availability must match whether a cost column was detected
        assert keys["unit_cost_pct"]["available"] == caps["features"]["cost"]
        assert keys["discount_change_points"]["available"] == caps["features"]["disc"]


@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_baseline_uses_real_data_under_role():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        caps = client.get("/api/v1/scenarios/capabilities?role=executive").json()
        if not caps["can_simulate"]:
            pytest.skip("connected schema has no qty+price columns; nothing to baseline")
        r = client.post("/api/v1/scenarios/baseline", json={"role": "executive"})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["ok"] is True
        bl = b["baseline"]
        assert bl["classification"] == "observed_actual"
        assert bl["units"] >= 0 and bl["gross"] >= 0
        assert bl["evidence_sql"].lower().startswith("select")
        # realized factor is a valid ratio derived from the real net/gross
        assert 0.0 <= bl["realized_factor"] <= 1.0


@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_save_duplicate_compare_and_send_to_investigation():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        caps = client.get("/api/v1/scenarios/capabilities?role=executive").json()
        if not caps["can_simulate"]:
            pytest.skip("connected schema has no qty+price columns; nothing to simulate")
        baseline = client.post("/api/v1/scenarios/baseline", json={"role": "executive"}).json()["baseline"]

        # save a scenario
        save = client.post("/api/v1/scenarios", json={
            "name": "Volume +10% / Price +5%", "role": "executive",
            "baseline": baseline, "assumptions": {"order_volume_pct": 10, "unit_price_pct": 5},
        })
        assert save.status_code == 200, save.text
        s = save.json()
        assert s["status"] == "saved"
        assert s["results"]["classification"] == "calculated_scenario"

        # save a second scenario to enable comparison
        save2 = client.post("/api/v1/scenarios", json={
            "name": "Discount +3pts", "role": "executive",
            "baseline": baseline, "assumptions": {"discount_change_points": 3},
        })
        assert save2.status_code == 200
        s2 = save2.json()

        # list
        lst = client.get("/api/v1/scenarios")
        assert lst.status_code == 200
        ids = {x["id"] for x in lst.json()["scenarios"]}
        assert s["id"] in ids and s2["id"] in ids

        # duplicate
        dup = client.post(f"/api/v1/scenarios/{s['id']}/duplicate")
        assert dup.status_code == 200
        assert dup.json()["name"].endswith("copy")
        assert dup.json()["status"] == "draft"

        # compare
        cmp_ = client.post("/api/v1/scenarios/compare", json={"scenario_ids": [s["id"], s2["id"]]})
        assert cmp_.status_code == 200
        assert cmp_.json()["compared"] == 2

        # rename
        ren = client.patch(f"/api/v1/scenarios/{s['id']}", json={"name": "Renamed scenario"})
        assert ren.status_code == 200 and ren.json()["name"] == "Renamed scenario"

        # open an investigation to send the scenario into
        fr = client.get("/api/v1/discover/findings?status=active&limit=5").json().get("findings", [])
        if fr:
            inv = client.post("/api/v1/investigations",
                              json={"finding_id": fr[0]["id"], "role": "executive", "run_root_cause": False}).json()
            send = client.post(f"/api/v1/scenarios/{s['id']}/send-to-investigation",
                               json={"investigation_id": inv["id"]})
            assert send.status_code == 200, send.text
            assert send.json()["branch"]["session_id"]

        # cleanup
        client.delete(f"/api/v1/scenarios/{s['id']}")
        client.delete(f"/api/v1/scenarios/{s2['id']}")
        client.delete(f"/api/v1/scenarios/{dup.json()['id']}")


@pytest.mark.skipif(not (_target_db_available() and _app_db_available()),
                    reason="live PostgreSQL target/app DB not available")
def test_rejects_invalid_and_unknown_scenarios():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        sim = client.post("/api/v1/scenarios/simulate",
                          json={"baseline": BASELINE, "assumptions": {"order_volume_pct": 99999}})
        assert sim.status_code == 422
        g = client.get("/api/v1/scenarios/nonexistent-id")
        assert g.status_code == 404
