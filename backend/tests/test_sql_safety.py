"""Unit tests for SQL Safety and AST Validator."""

import pytest
from app.services.sql_safety import SQLPolicyEngine, PolicyResult


@pytest.fixture
def engine():
    return SQLPolicyEngine(max_rows=1000, max_query_length=4096)


def test_valid_select_queries_pass(engine):
    valid_queries = [
        "SELECT * FROM sales.customers",
        "SELECT region_id, SUM(quantity * unit_price) AS total FROM sales.sales_order_items GROUP BY region_id",
        "SELECT c.company_name, COUNT(o.order_id) FROM sales.customers c JOIN sales.sales_orders o ON c.customer_id = o.customer_id GROUP BY c.company_name ORDER BY 2 DESC LIMIT 5",
        "SELECT order_id, order_date, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) as rn FROM sales.sales_orders",
    ]
    for q in valid_queries:
        result = engine.validate(q)
        assert result.allowed is True, f"Expected safe query to pass: {q}. Reason: {result.violations}"
        assert result.modified_sql is not None or result.sql is not None


def test_reject_drop_table(engine):
    malicious = [
        "DROP TABLE sales.customers",
        "DROP TABLE IF EXISTS sales.orders CASCADE",
    ]
    for q in malicious:
        result = engine.validate(q)
        assert result.allowed is False, f"Expected unsafe query to be rejected: {q}"
        assert any("drop" in v.lower() or "select" in v.lower() for v in result.violations)


def test_reject_delete_and_update(engine):
    unsafe = [
        "DELETE FROM sales.customers WHERE 1=1",
        "UPDATE sales.regional_targets SET target_amount = 0",
        "TRUNCATE TABLE sales.returns",
        "INSERT INTO sales.regions (region_name, region_code) VALUES ('Hacked', 'HK')",
    ]
    for q in unsafe:
        result = engine.validate(q)
        assert result.allowed is False, f"Expected mutation query to be rejected: {q}"


def test_reject_sql_injection_multi_statement(engine):
    injections = [
        "SELECT 1; DROP TABLE sales.customers",
        "SELECT * FROM sales.regions; DELETE FROM sales.sales_orders;",
    ]
    for q in injections:
        result = engine.validate(q)
        assert result.allowed is False, f"Expected multi-statement injection to be rejected: {q}"


def test_enforce_limit_clause(engine):
    query_without_limit = "SELECT * FROM sales.customers"
    result = engine.validate(query_without_limit)
    assert result.allowed is True
    sql_to_check = result.modified_sql or result.sql
    assert "LIMIT" in sql_to_check.upper()


def test_query_length_limit(engine):
    long_query = "SELECT " + "a" * 5000
    result = engine.validate(long_query)
    assert result.allowed is False
    assert any("length" in v.lower() for v in result.violations)
