"""Unit tests for Chart and Explanation Services."""

import pytest
from app.services.chart_service import select_chart_type
from app.services.explanation_service import ExplanationService


def test_chart_recommendation_bar():
    columns = ["region_name", "total_sales"]
    data = [
        {"region_name": "North", "total_sales": 1000},
        {"region_name": "South", "total_sales": 2000},
    ]
    chart = select_chart_type(columns, data, "Show total sales by region")
    assert chart is not None
    assert chart["type"] in ["bar", "pie"]
    assert chart["x_axis"] == "region_name"
    assert chart["y_axis"] == "total_sales"


def test_chart_recommendation_line_time_series():
    columns = ["order_date", "revenue"]
    data = [
        {"order_date": "2024-01-01", "revenue": 500},
        {"order_date": "2024-02-01", "revenue": 800},
        {"order_date": "2024-03-01", "revenue": 1200},
    ]
    chart = select_chart_type(columns, data, "Monthly revenue trend")
    assert chart is not None
    assert chart["type"] == "line"
    assert chart["x_axis"] == "order_date"


def test_grounded_explanation_fallback():
    # Test fallback explanation without LLM
    svc = ExplanationService(llm=None)
    columns = ["region_name", "total_sales"]
    data = [
        {"region_name": "South", "total_sales": 1826025.82},
        {"region_name": "West", "total_sales": 1153145.69},
    ]
    exp = svc._fallback_explanation("Show sales by region", columns, data)
    assert exp is not None
    assert "2 rows" in exp
    assert "region_name" in exp
