import pytest
from decimal import Decimal
from datetime import date
from app.services.eval_comparator import compare_query_results, BENCHMARK_REFERENCE_SPECS


def test_comparator_exact_match():
    act = [{"name": "North", "val": 100}, {"name": "South", "val": 200}]
    exp = [{"name": "North", "val": 100}, {"name": "South", "val": 200}]
    res = compare_query_results(act, exp, ordered=False)
    assert res.is_match is True


def test_comparator_unordered_match():
    act = [{"name": "South", "val": 200}, {"name": "North", "val": 100}]
    exp = [{"name": "North", "val": 100}, {"name": "South", "val": 200}]
    res = compare_query_results(act, exp, ordered=False)
    assert res.is_match is True


def test_comparator_ordered_mismatch():
    act = [{"name": "South", "val": 200}, {"name": "North", "val": 100}]
    exp = [{"name": "North", "val": 100}, {"name": "South", "val": 200}]
    res = compare_query_results(act, exp, ordered=True)
    assert res.is_match is False
    assert "Rank order mismatch" in res.reason


def test_comparator_decimal_tolerance():
    act = [{"revenue": 906240.785759}]
    exp = [{"revenue": Decimal("906240.79")}]
    res = compare_query_results(act, exp)
    assert res.is_match is True


def test_comparator_null_handling():
    act = [{"name": "Alice", "mgr": None}]
    exp = [{"name": "Alice", "mgr": None}]
    assert compare_query_results(act, exp).is_match is True

    act_not_null = [{"name": "Alice", "mgr": "Bob"}]
    assert compare_query_results(act_not_null, exp).is_match is False


def test_comparator_different_column_aliases():
    act = [{"total_customers": 30}]
    exp = [{"count": 30}]
    res = compare_query_results(act, exp)
    assert res.is_match is True


def test_comparator_row_count_mismatch():
    act = [{"id": 1}]
    exp = [{"id": 1}, {"id": 2}]
    res = compare_query_results(act, exp)
    assert res.is_match is False
    assert "Row count mismatch" in res.reason


def test_all_31_benchmark_specs_defined():
    assert len(BENCHMARK_REFERENCE_SPECS) == 31
    analytical = [s for s in BENCHMARK_REFERENCE_SPECS.values() if s["expected_behavior"] == "success"]
    assert len(analytical) == 24
    assert all(s["reference_sql"] is not None for s in analytical)
    safety = [s for s in BENCHMARK_REFERENCE_SPECS.values() if s["expected_behavior"] == "reject"]
    assert len(safety) == 6
    clarification = [s for s in BENCHMARK_REFERENCE_SPECS.values() if s["expected_behavior"] == "clarification"]
    assert len(clarification) == 1
