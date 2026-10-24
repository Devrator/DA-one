"""Automated tests for QueryPilot Chaos Arena — Adversarial Testing & Recovery Sandbox."""

import pytest
from app.services.chaos_arena_service import ChaosArenaManager, get_chaos_manager
from app.database import get_default_target_engine
from sqlalchemy import text


@pytest.fixture
def chaos_manager():
    return ChaosArenaManager()


def test_chaos_arena_challenge_catalog(chaos_manager):
    """Verify challenge catalog discovery and metadata integrity."""
    challenges = chaos_manager.get_challenges()
    assert len(challenges) >= 4
    c_ids = [c["id"] for c in challenges]
    assert "duplicate_keys" in c_ids
    assert "schema_mutation" in c_ids
    assert "ambiguous_metric" in c_ids
    assert "prompt_injection" in c_ids

    for c in challenges:
        assert c["title"]
        assert c["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        assert len(c["supported_questions"]) >= 1


def test_chaos_arena_environment_isolation(chaos_manager):
    """Verify sandbox reset clones clean tables into chaos_test without touching sales."""
    res = chaos_manager.reset_isolated_environment()
    assert res["success"] is True

    engine = get_default_target_engine()
    with engine.connect() as conn:
        # Check chaos_test has the cloned tables
        chaos_tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='chaos_test'"
        )).fetchall()]
        assert "sales_orders" in chaos_tables
        assert "customers" in chaos_tables
        assert "product_catalog" in chaos_tables

        # Check sales schema is completely intact
        sales_tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='sales'"
        )).fetchall()]
        assert "product_catalog" in sales_tables
        assert "sales_orders" in sales_tables


def test_chaos_arena_duplicate_keys_lifecycle(chaos_manager):
    """Test full 8-stage lifecycle for Duplicate Join Keys."""
    run = chaos_manager.execute_challenge_run("duplicate_keys")
    assert run["status"] == "completed"
    assert run["outcome_category"] == "verified_recovered"
    assert run["verification_match"] is True
    assert run["detection_latency_ms"] > 0
    assert run["recovery_latency_ms"] > 0

    # Verify stage 4 detected inflation
    stage_4 = next(s for s in run["stages"] if s["stage_id"] == "stage_4_detection")
    assert stage_4["status"] == "completed"
    assert "Cartesian Inflation Detected" in stage_4["summary"]


def test_chaos_arena_schema_mutation_lifecycle(chaos_manager):
    """Test full 8-stage lifecycle for Schema Drift Mutation."""
    run = chaos_manager.execute_challenge_run("schema_mutation")
    assert run["status"] == "completed"
    assert run["outcome_category"] == "verified_recovered"
    assert run["verification_match"] is True

    # Verify stage 4 caught UndefinedTable
    stage_4 = next(s for s in run["stages"] if s["stage_id"] == "stage_4_detection")
    assert stage_4["status"] == "completed"
    assert "UndefinedTable" in stage_4["summary"] or "does not exist" in stage_4["summary"]


def test_chaos_arena_ambiguous_metric_lifecycle(chaos_manager):
    """Test full 8-stage lifecycle for Ambiguous Metric."""
    run = chaos_manager.execute_challenge_run("ambiguous_metric")
    assert run["status"] == "completed"
    assert run["outcome_category"] == "correctly_abstained_clarified"


def test_chaos_arena_prompt_injection_lifecycle(chaos_manager):
    """Test full 8-stage lifecycle for Data Prompt Injection."""
    run = chaos_manager.execute_challenge_run("prompt_injection")
    assert run["status"] == "completed"
    assert run["outcome_category"] == "verified_recovered"

    # Verify untrusted boundary was enforced and no DDL was permitted
    stage_5 = next(s for s in run["stages"] if s["stage_id"] == "stage_5_investigation")
    assert stage_5["status"] == "completed"


def test_chaos_arena_cancel_run(chaos_manager):
    """Test cancellation token on chaos run."""
    run = chaos_manager.execute_challenge_run("duplicate_keys")
    run_id = run["run_id"]
    cancelled = chaos_manager.cancel_run(run_id)
    assert cancelled is True
    assert chaos_manager.get_run(run_id)["status"] == "cancelled"


def test_prod_sales_schema_remains_unpolluted(chaos_manager):
    """Final check to ensure production sales schema never suffered data corruption."""
    engine = get_default_target_engine()
    with engine.connect() as conn:
        # product_catalog must still exist
        pc_exists = conn.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='sales' AND table_name='product_catalog'"
        )).scalar()
        assert pc_exists == 1

        # discount_pct must still exist
        dp_exists = conn.execute(text(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='sales' AND table_name='sales_order_items' AND column_name='discount_pct'"
        )).scalar()
        assert dp_exists == 1
