"""Chart specification service — selects appropriate visualizations from result data.

Generates constrained chart specs (not arbitrary code) based on result schema and data.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Data type classification helpers
NUMERIC_KEYWORDS = {"int", "float", "numeric", "decimal", "double", "real", "bigint", "smallint", "money"}
DATE_KEYWORDS = {"date", "time", "timestamp", "interval"}
TEXT_KEYWORDS = {"char", "varchar", "text", "string", "name"}


def infer_column_type(col_name: str, sample_values: list[Any]) -> str:
    """Infer column type from name and sample values."""
    name_lower = col_name.lower()

    # Date heuristics
    if any(kw in name_lower for kw in ["date", "month", "year", "quarter", "week", "time", "period"]):
        return "temporal"

    # Check actual values
    numeric_count = 0
    for v in sample_values[:10]:
        if v is None:
            continue
        if isinstance(v, (int, float)):
            numeric_count += 1
        elif isinstance(v, str):
            try:
                float(v.replace(",", ""))
                numeric_count += 1
            except (ValueError, AttributeError):
                pass

    if numeric_count > len(sample_values) * 0.7:
        return "numeric"

    return "categorical"


def select_chart_type(
    columns: list[str],
    rows: list[dict[str, Any]],
    question: str = "",
) -> dict | None:
    """Select the most appropriate chart type based on the result data.

    Returns a chart specification dict or None if no chart is appropriate.
    """
    if not columns or not rows:
        return None

    n_rows = len(rows)
    n_cols = len(columns)

    # Classify columns
    col_types = {}
    for col in columns:
        sample = [row.get(col) for row in rows[:20]]
        col_types[col] = infer_column_type(col, sample)

    temporal_cols = [c for c, t in col_types.items() if t == "temporal"]
    numeric_cols = [c for c, t in col_types.items() if t == "numeric"]
    categorical_cols = [c for c, t in col_types.items() if t == "categorical"]

    question_lower = question.lower()

    # === Single value → KPI card ===
    if n_rows == 1 and n_cols == 1 and numeric_cols:
        return {
            "type": "kpi",
            "title": _humanize(columns[0]),
            "value_column": columns[0],
            "value": rows[0][columns[0]],
        }

    # === Single row, few numeric columns → KPI cards ===
    if n_rows == 1 and len(numeric_cols) <= 4 and numeric_cols:
        return {
            "type": "kpi_group",
            "title": "Summary",
            "metrics": [
                {"label": _humanize(c), "value_column": c, "value": rows[0][c]}
                for c in numeric_cols
            ],
        }

    # === Time series → Line chart ===
    if temporal_cols and numeric_cols:
        return {
            "type": "line",
            "title": f"{_humanize(numeric_cols[0])} over {_humanize(temporal_cols[0])}",
            "x_axis": temporal_cols[0],
            "y_axis": numeric_cols[0],
            "x_label": _humanize(temporal_cols[0]),
            "y_label": _humanize(numeric_cols[0]),
            "series": numeric_cols[:3],  # Max 3 series
        }

    # === Ranking / Top-N → Horizontal bar ===
    if (categorical_cols and numeric_cols and
        n_rows <= 20 and
        any(kw in question_lower for kw in ["top", "highest", "best", "most", "rank", "bottom", "worst", "least"])):
        return {
            "type": "bar_horizontal",
            "title": f"{_humanize(numeric_cols[0])} by {_humanize(categorical_cols[0])}",
            "x_axis": numeric_cols[0],
            "y_axis": categorical_cols[0],
            "x_label": _humanize(numeric_cols[0]),
            "y_label": _humanize(categorical_cols[0]),
        }

    # === Category comparison → Bar chart ===
    if categorical_cols and numeric_cols and n_rows <= 30:
        # Pie chart for small categorical distributions (2-7 items)
        if (n_rows <= 7 and len(numeric_cols) == 1 and
            any(kw in question_lower for kw in ["distribution", "breakdown", "proportion", "share", "percentage"])):
            return {
                "type": "pie",
                "title": f"{_humanize(numeric_cols[0])} by {_humanize(categorical_cols[0])}",
                "name_column": categorical_cols[0],
                "value_column": numeric_cols[0],
            }

        return {
            "type": "bar",
            "title": f"{_humanize(numeric_cols[0])} by {_humanize(categorical_cols[0])}",
            "x_axis": categorical_cols[0],
            "y_axis": numeric_cols[0],
            "x_label": _humanize(categorical_cols[0]),
            "y_label": _humanize(numeric_cols[0]),
            "series": numeric_cols[:3],
        }

    # === Two numeric columns → Scatter plot ===
    if len(numeric_cols) >= 2 and n_rows >= 5:
        return {
            "type": "scatter",
            "title": f"{_humanize(numeric_cols[0])} vs {_humanize(numeric_cols[1])}",
            "x_axis": numeric_cols[0],
            "y_axis": numeric_cols[1],
            "x_label": _humanize(numeric_cols[0]),
            "y_label": _humanize(numeric_cols[1]),
        }

    # Default: table only (no chart)
    return {
        "type": "table",
        "title": "Query Results",
        "columns": columns,
    }


def _humanize(col_name: str) -> str:
    """Convert column_name to Human Name."""
    return col_name.replace("_", " ").title()
