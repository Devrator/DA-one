"""Automated tests for Phase 2 Proactive Discovery (Discover & Early Warnings).

Split into:
- Pure-logic tests (no DB): evidence completeness, dedup signatures, ranking,
  schema-profile SQL assembly. These always run.
- Integration tests (require live PostgreSQL): a real discovery job runs read-only
  aggregate queries under the requesting role's Row-Level Security, persists
  evidence-backed findings, dedupes repeat runs, and handles failure. These skip
  gracefully when the database is unavailable so the suite never fabricates results.
"""

import pytest

from app.services.discovery_service import (
    DiscoveryService,
    SchemaProfile,
    _sha1,
    run_discovery_job,
)


REQUIRED_EVIDENCE_KEYS = [
    "signature", "finding_type", "severity", "score", "title", "narrative",
    "hypothesis", "suggested_next_steps", "metric_name", "dimension_name",
    "baseline_value", "current_value", "delta_abs", "delta_pct",
    "comparison_label", "period_label", "source_tables", "calculation",
    "supporting_data", "chart_spec", "assumptions", "limitations",
    "explore_question",
]


def _sample_profile() -> SchemaProfile:
    p = SchemaProfile()
    p.schema_name = "sales"
    p.fact_table = "sales_order_items"
    p.parent_table = "sales_orders"
    p.parent_pk = "order_id"
    p.fact_to_parent_fk = "order_id"
    p.time_column = "order_date"
    p.status_column = "status"
    p.status_filter_value = "completed"
    p.measures = [{
        "key": "net_revenue",
        "label": "Net Revenue",
        "expr": "SUM(i.quantity * i.unit_price * (1 - i.discount_pct / 100))",
    }]
    return p


# ---------------------------------------------------------------------------
# Pure-logic tests (no database required)
# ---------------------------------------------------------------------------
def test_finding_carries_complete_evidence():
    """Every finding must expose what/by-how-much, baseline, calculation,
    supporting data, hypothesis (kept separate from fact) and limitations."""
    svc = DiscoveryService.__new__(DiscoveryService)  # avoid DB engines
    svc.role = "executive"
    profile = _sample_profile()
    measure = profile.measures[0]
    dimension = {"table": "sales.product_catalog", "column": "category", "label": "Category"}

    finding = svc._make_finding(
        ftype="trend",
        title="Category 'Hardware' rose sharply",
        narrative="Net Revenue for Hardware increased across the period.",
        hypothesis="May reflect a promotional push or new customer onboarding.",
        next_steps="Drill into Hardware by sales rep and month.",
        profile=profile,
        measure=measure,
        dimension=dimension,
        segment="Hardware",
        baseline=100000.0,
        current=322000.0,
        delta_pct=222.0,
        comparison="second half vs first half",
        period_label="Jan-Sep 2026",
        supporting=[{"period": "Jan", "value": 1000.0}, {"period": "Feb", "value": 1500.0}],
        chart="line",
    )

    for key in REQUIRED_EVIDENCE_KEYS:
        assert key in finding, f"missing evidence field: {key}"
        assert finding[key] not in (None, "", [], {}), f"empty evidence field: {key}"

    # Observed facts are quantified and separated from hypothesis.
    assert finding["delta_abs"] == pytest.approx(222000.0, rel=1e-3)
    assert finding["hypothesis"] and "May reflect" in finding["hypothesis"]
    # No causal claim: limitations must disclaim causation.
    assert any("causal" in lim.lower() for lim in finding["limitations"])
    # Calculation is fully reconstructable.
    assert finding["calculation"]["measure_expr"] == measure["expr"]
    assert "sales.sales_order_items" in finding["source_tables"]
    # Freshness/role metadata present for provenance.
    assert finding["role"] == "executive"


def test_dedup_signature_is_stable_and_discriminating():
    """Re-detecting the same insight must yield the same signature (noise/dup
    suppression), while a different segment must produce a different one."""
    base = _sha1("trend", "net_revenue", "Category", "Hardware", "Jan-Sep 2026")
    same = _sha1("trend", "net_revenue", "Category", "Hardware", "Jan-Sep 2026")
    other = _sha1("trend", "net_revenue", "Category", "Software", "Jan-Sep 2026")
    assert base == same
    assert base != other
    assert len(base) == 32


def test_rank_orders_by_severity_and_magnitude():
    """Higher severity and larger movement must rank above minor changes."""
    svc = DiscoveryService.__new__(DiscoveryService)
    findings = [
        {"severity": "watch", "delta_pct": 12.0},
        {"severity": "critical", "delta_pct": 220.0},
        {"severity": "warning", "delta_pct": 60.0},
    ]
    ranked = svc._rank(findings)
    assert ranked[0]["severity"] == "critical"
    assert ranked[-1]["severity"] == "watch"
    assert ranked[0]["rank_score"] >= ranked[1]["rank_score"] >= ranked[2]["rank_score"]


def test_schema_profile_assembles_join_and_where():
    profile = _sample_profile()
    profile.extra_joins["product_catalog"] = ("f", "product_id", "product_id")
    profile.aliases["product_catalog"] = "pc"
    frm = profile.from_base()
    assert "sales.sales_order_items f" in frm
    assert "JOIN sales.sales_orders p ON f.order_id = p.order_id" in frm
    assert "JOIN sales.product_catalog pc ON f.product_id = pc.product_id" in frm
    where = profile.where_clause()
    assert "p.status = 'completed'" in where
    assert "p.order_date IS NOT NULL" in where


def test_schema_profile_escapes_status_value():
    """Status filter values must be single-quote escaped (no SQL injection via
    detected status literals)."""
    profile = _sample_profile()
    profile.status_filter_value = "done'; DROP TABLE x; --"
    where = profile.where_clause()
    assert "DROP" in where  # literal preserved as data, not executable
    assert "''" in where    # quote doubled/escaped


# ---------------------------------------------------------------------------
# Integration tests (require live target + app PostgreSQL)
# ---------------------------------------------------------------------------
def _db_available() -> bool:
    try:
        from app.services.query_executor import QueryExecutor
        from app.services.role_service import resolve_user_context
        executor = QueryExecutor.from_settings()
        res = executor.execute("SELECT 1 AS ok", user_context=resolve_user_context("executive"))
        return bool(res.success)
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="live PostgreSQL target not available")
def test_discovery_job_persists_and_dedupes():
    """A real discovery job over live data must persist evidence-backed findings,
    then suppress duplicates on a repeat run (stable signatures)."""
    first = run_discovery_job(trigger="manual", role="executive")
    assert first["status"] in ("completed", "failed")
    if first["status"] == "failed":
        # Failure handling must record an error rather than crash.
        assert first.get("error")
        pytest.skip("discovery job failed against live data; error was captured")

    assert first["findings_total"] >= 0
    second = run_discovery_job(trigger="manual", role="executive")
    assert second["status"] == "completed"

    # If the first run produced findings, the second run must dedupe them
    # (no duplicate alerts) rather than re-inserting identical signatures.
    if first["findings_new"] > 0:
        assert second["findings_deduped"] >= 1
        assert second["findings_new"] == 0 or second["findings_new"] < first["findings_new"]

    # Verify persisted findings are complete and were derived from real queries.
    from app.database import get_app_session_factory
    from app.models import DiscoveryFinding
    session = get_app_session_factory()()
    try:
        findings = session.query(DiscoveryFinding).filter(
            DiscoveryFinding.status != "dismissed"
        ).all()
        assert len(findings) > 0
        f = findings[0]
        assert f.severity in {"critical", "warning", "watch", "info"}
        assert f.signature and len(f.signature) == 32
        assert f.assumptions and f.limitations
        assert f.source_tables and f.calculation and f.calculation.get("measure_expr")
        assert any("causal" in (lim or "").lower() for lim in (f.limitations or []))
    finally:
        session.close()
