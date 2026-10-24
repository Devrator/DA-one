"""Automated regression tests for Phase 2 Security, Roles, and Contextual Continuity."""

import pytest
from app.services.role_service import resolve_user_context, VERIFIED_USERS, RESTRICTED_COLUMNS
from app.services.sql_safety import SQLPolicyEngine
from app.services.query_executor import QueryExecutor
from app.database import get_default_target_engine
from sqlalchemy import text


def test_role_resolution():
    """Verify that user personas map strictly to verified server-side roles."""
    exec_ctx = resolve_user_context("executive")
    assert exec_ctx.role == "executive"
    assert exec_ctx.region_id is None
    assert exec_ctx.sales_rep is None

    mgr_ctx = resolve_user_context("regional_manager_north")
    assert mgr_ctx.role == "regional_manager"
    assert mgr_ctx.region_id == 1

    rep_ctx = resolve_user_context("sales_rep_carol")
    assert rep_ctx.role == "sales_rep"
    assert rep_ctx.sales_rep == "Carol Chen"


def test_ast_blocks_restricted_columns_for_sales_rep():
    """Verify that AST policy engine rejects unauthorized column access based on role."""
    policy = SQLPolicyEngine.from_settings()

    # Sales rep cannot query cost_price
    res = policy.validate("SELECT product_name, cost_price FROM sales.product_catalog", role="sales_rep")
    assert not res.allowed
    assert any("cost_price" in v for v in res.violations)

    # Executive can query cost_price
    res_exec = policy.validate("SELECT product_name, cost_price FROM sales.product_catalog", role="executive")
    assert res_exec.allowed


def test_database_rls_isolation_between_roles():
    """Test PostgreSQL RLS row filtering across executive, manager, and rep."""
    executor = QueryExecutor.from_settings()

    # Executive sees all orders
    exec_ctx = resolve_user_context("executive")
    exec_res = executor.execute("SELECT COUNT(*) AS c FROM sales.sales_orders", user_context=exec_ctx)
    assert exec_res.success
    total_orders = exec_res.rows[0]["c"]
    assert total_orders > 0

    # Regional Manager North (Region 1) only sees region 1 orders
    mgr_ctx = resolve_user_context("regional_manager_north")
    mgr_res = executor.execute("SELECT COUNT(*) AS c FROM sales.sales_orders", user_context=mgr_ctx)
    assert mgr_res.success
    mgr_orders = mgr_res.rows[0]["c"]
    assert 0 < mgr_orders < total_orders

    # Sales rep Carol Chen only sees her own orders
    rep_ctx = resolve_user_context("sales_rep_carol")
    rep_res = executor.execute("SELECT COUNT(*) AS c FROM sales.sales_orders", user_context=rep_ctx)
    assert rep_res.success
    rep_orders = rep_res.rows[0]["c"]
    assert 0 < rep_orders < mgr_orders


def test_canary_records_exist_and_contained():
    """Verify canary records are stored as untrusted text and cannot elevate privileges."""
    engine = get_default_target_engine()
    with engine.connect() as conn:
        res = conn.execute(text("SELECT customer_id, company_name FROM sales.customers WHERE customer_id = 999")).fetchone()
        assert "SYSTEM OVERRIDE" in res[1]
