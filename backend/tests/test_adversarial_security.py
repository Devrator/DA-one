"""Adversarial security tests for QueryPilot AI.

Verifies SQLGlot AST safety policy, target database read-only enforcement,
system catalog restrictions, prohibited function blocking, and prompt injection defense.
"""

import pytest
from sqlalchemy import text
from app.services.sql_safety import SQLPolicyEngine
from app.database import get_default_target_engine
from app.services.query_executor import QueryExecutor
from app.services.eval_comparator import compare_query_results, BENCHMARK_REFERENCE_SPECS


@pytest.fixture
def policy_engine():
    return SQLPolicyEngine.from_settings()


@pytest.fixture
def target_engine():
    return get_default_target_engine()


@pytest.fixture
def query_executor():
    return QueryExecutor.from_settings()


class TestASTPolicyEngineAdversarial:
    """Test AST-level SQL validation against malicious inputs."""

    @pytest.mark.parametrize("query,expected_keyword", [
        ("DELETE FROM sales.customers WHERE customer_id = 1", "DELETE"),
        ("UPDATE sales.sales_orders SET status = 'cancelled'", "UPDATE"),
        ("INSERT INTO sales.customers (name) VALUES ('Hacker')", "INSERT"),
        ("DROP TABLE sales.customers CASCADE", "DROP"),
        ("ALTER TABLE sales.customers ADD COLUMN hacked text", "ALTER"),
        ("CREATE TABLE evil (id int)", "CREATE"),
        ("TRUNCATE sales.sales_orders", "TRUNCATE"),
    ])
    def test_blocks_ddl_and_dml(self, policy_engine, query, expected_keyword):
        res = policy_engine.validate(query)
        assert not res.allowed
        assert any(expected_keyword in v.upper() for v in res.violations) or "SELECT" in str(res.violations)

    def test_blocks_multi_statements(self, policy_engine):
        evil_multi = "SELECT 1; DROP TABLE sales.customers;"
        res = policy_engine.validate(evil_multi)
        assert not res.allowed
        assert any("multiple" in v.lower() or "statement" in v.lower() or "drop" in v.lower() for v in res.violations)

    def test_blocks_prohibited_system_catalogs(self, policy_engine):
        queries = [
            "SELECT * FROM pg_shadow",
            "SELECT * FROM pg_authid",
            "SELECT usename, passwd FROM pg_shadow",
        ]
        for q in queries:
            res = policy_engine.validate(q)
            assert not res.allowed
            assert any("pg_shadow" in v.lower() or "pg_authid" in v.lower() or "prohibited" in v.lower() or "schema" in v.lower() for v in res.violations)

    def test_blocks_dangerous_functions(self, policy_engine):
        queries = [
            "SELECT pg_sleep(10)",
            "SELECT pg_read_file('etc/passwd')",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
        ]
        for q in queries:
            res = policy_engine.validate(q)
            assert not res.allowed
            assert any("function" in v.lower() or "sleep" in v.lower() or "pg_" in v.lower() for v in res.violations)

    def test_blocks_comment_obfuscation(self, policy_engine):
        obfuscated = "SELECT /* harmless comment */ 1; /* sneaky */ DELETE FROM sales.regions;"
        res = policy_engine.validate(obfuscated)
        assert not res.allowed


class TestDatabaseLevelReadOnlyEnforcement:
    """Independent database role defense-in-depth verification.
    
    Verifies that even if a query bypassed AST validation, the target_readonly
    PostgreSQL role enforces read-only transactions at the database engine level.
    """

    def test_db_blocks_direct_insert(self, target_engine):
        with pytest.raises(Exception) as exc_info:
            with target_engine.connect() as conn:
                conn.execute(text("INSERT INTO sales.customers (customer_id, company_name) VALUES (999999, 'Attacker')"))
                conn.commit()
        err = str(exc_info.value).lower()
        assert "read-only" in err or "permission denied" in err


    def test_db_blocks_direct_update(self, target_engine):
        with pytest.raises(Exception) as exc_info:
            with target_engine.connect() as conn:
                conn.execute(text("UPDATE sales.sales_orders SET status = 'fraud' WHERE order_id = 1"))
                conn.commit()
        err = str(exc_info.value).lower()
        assert "read-only" in err or "permission denied" in err

    def test_db_blocks_direct_delete(self, target_engine):
        with pytest.raises(Exception) as exc_info:
            with target_engine.connect() as conn:
                conn.execute(text("DELETE FROM sales.product_catalog WHERE product_id = 1"))
                conn.commit()
        err = str(exc_info.value).lower()
        assert "read-only" in err or "permission denied" in err

    def test_db_blocks_direct_drop(self, target_engine):
        with pytest.raises(Exception) as exc_info:
            with target_engine.connect() as conn:
                conn.execute(text("DROP TABLE sales.returns"))
                conn.commit()
        err = str(exc_info.value).lower()
        assert "read-only" in err or "permission denied" in err

    def test_db_blocks_pg_shadow_access(self, target_engine):
        with pytest.raises(Exception) as exc_info:
            with target_engine.connect() as conn:
                conn.execute(text("SELECT * FROM pg_shadow"))
        err = str(exc_info.value).lower()
        assert "permission denied" in err or "insufficientprivilege" in err or "pg_shadow" in err


class TestSalesReportGroundingRegression:
    """Regression test for Case 21: 'Which sales rep has generated the most revenue?'"""

    def test_sales_rep_reference_answer(self, target_engine, query_executor):
        spec = BENCHMARK_REFERENCE_SPECS[21]
        assert spec["question"] == "Which sales rep has generated the most revenue?"

        # Reference execution
        ref_res = query_executor.execute(target_engine, spec["reference_sql"])
        assert ref_res.success
        assert len(ref_res.rows) == 1
        assert ref_res.rows[0]["sales_rep"] == "Carol Chen"

        # Valid candidate query with table-qualified alias
        candidate_sql = (
            "SELECT o.sales_rep, SUM(s.quantity * s.unit_price * (1 - s.discount_pct / 100)) AS total_revenue "
            "FROM sales.sales_order_items s "
            "JOIN sales.sales_orders o ON s.order_id = o.order_id "
            "GROUP BY o.sales_rep ORDER BY total_revenue DESC LIMIT 1"
        )
        cand_res = query_executor.execute(target_engine, candidate_sql)
        assert cand_res.success

        cmp = compare_query_results(cand_res.rows, ref_res.rows, spec)
        assert cmp.is_match, f"Expected match on sales rep regression test, got: {cmp.reason}"
