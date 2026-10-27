"""Automated tests for Feature 4 (Personalized Executive Briefings).

Two tiers:
- Pure-logic (no DB): ranking, suppression (dismissed / stale / duplicate /
  low-value), capping and honest empty handling. Always run.
- Integration (live PostgreSQL/app DB): a role-scoped briefing generated for a
  restricted identity contains ONLY that role's findings, dedup on repeat,
  preference persistence and the inbox. Skips gracefully when a DB is down.
"""

import pytest
from datetime import datetime, timedelta, timezone


def _app_db_available() -> bool:
    try:
        from app.database import init_app_db
        init_app_db()
        return True
    except Exception:
        return False


def _target_db_available() -> bool:
    try:
        from app.services.query_executor import QueryExecutor
        from app.services.role_service import resolve_user_context
        res = QueryExecutor.from_settings().execute("SELECT 1 AS ok", user_context=resolve_user_context("executive"))
        return bool(res.success)
    except Exception:
        return False


def _f(**kw):
    base = {
        "id": kw.get("id", "f1"), "signature": kw.get("sig", kw.get("id", "f1")),
        "severity": kw.get("severity", "warning"), "finding_type": kw.get("ftype", "trend"),
        "delta_pct": kw.get("delta_pct", 30.0), "status": kw.get("status", "new"),
        "title": kw.get("title", "A change"), "narrative": "n", "metric_name": "Net revenue",
        "data_freshness_at": kw.get("fresh", datetime.now(timezone.utc)),
        "created_at": datetime.now(timezone.utc),
    }
    return base


# ---------------------------------------------------------------------------
# Pure-logic: ranking + suppression
# ---------------------------------------------------------------------------
def test_score_prefers_critical_and_large_moves():
    from app.services.briefing_service import score_finding
    big_crit = score_finding(_f(severity="critical", delta_pct=80), [])
    small_info = score_finding(_f(severity="info", delta_pct=3, status="saved"), [])
    assert big_crit > small_info


def test_relevance_boost_for_enabled_categories():
    from app.services.briefing_service import score_finding
    f = _f(ftype="anomaly")
    on = score_finding(f, ["anomaly"])
    off = score_finding(f, ["trend", "concentration"])
    assert on > off


def test_build_items_suppresses_dismissed_stale_dupes_lowvalue():
    from app.services.briefing_service import build_items
    now = datetime.now(timezone.utc)
    findings = [
        _f(id="keep1", sig="s1", severity="critical", delta_pct=60),
        _f(id="drop_dismissed", sig="s2", status="dismissed"),
        _f(id="drop_stale", sig="s3", fresh=now - timedelta(hours=100)),   # > 48h stale
        _f(id="dupe", sig="s1"),                                            # same signature as keep1
        _f(id="drop_low", sig="s5", severity="info", delta_pct=0.5),       # below low-value floor
    ]
    res = build_items(findings, enabled_categories=[], now=now,
                      stale_after_hours=48, low_value_score=5.0, max_items=8)
    ids = {it["id"] for it in res["items"]}
    assert ids == {"keep1"}, ids
    assert res["suppressed"] >= 3


def test_build_items_caps_and_sorts_by_score():
    from app.services.briefing_service import build_items
    now = datetime.now(timezone.utc)
    findings = [
        _f(id=f"c{i}", sig=f"cs{i}", severity="critical", delta_pct=10 + i * 10) for i in range(6)
    ]
    res = build_items(findings, enabled_categories=[], now=now,
                      stale_after_hours=48, low_value_score=5.0, max_items=3)
    assert len(res["items"]) == 3
    scores = [it["briefing_score"] for it in res["items"]]
    assert scores == sorted(scores, reverse=True)
    assert res["suppressed"] >= 3  # the 3 not shown are counted


def test_empty_selection_is_honest():
    from app.services.briefing_service import build_items, _summary_text
    now = datetime.now(timezone.utc)
    res = build_items([_f(id="x", status="dismissed")], enabled_categories=[], now=now,
                      stale_after_hours=48, low_value_score=5.0, max_items=8)
    assert res["items"] == []
    summary = _summary_text([], "regional_manager", "2026-10-25")
    assert "No material changes" in summary and "Nothing was invented" in summary


def test_signature_is_stable_and_order_independent():
    from app.services.briefing_service import _briefing_signature
    a = _briefing_signature("executive", "2026-10-25", [{"signature": "s1"}, {"signature": "s2"}])
    b = _briefing_signature("executive", "2026-10-25", [{"signature": "s2"}, {"signature": "s1"}])
    c = _briefing_signature("executive", "2026-10-25", [{"signature": "s1"}])
    assert a == b and a != c


# ---------------------------------------------------------------------------
# Integration (live DBs)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not (_app_db_available() and _target_db_available()),
                    reason="live PostgreSQL app/target DB not available")
def test_briefing_is_role_scoped_and_never_leaks():
    """A restricted recipient's briefing must contain only their role's findings."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        # ensure the executive scope has findings
        client.post("/api/v1/discover/runs", json={"role": "executive"})
        import time
        for _ in range(30):
            fr = client.get("/api/v1/discover/findings?status=active&limit=5&role=executive").json().get("findings", [])
            if fr:
                break
            time.sleep(1)

        # generate for a restricted identity (regional manager north)
        gen = client.post("/api/v1/briefings/generate",
                          json={"username": "regional_manager_north", "cadence": "manual", "refresh": False})
        assert gen.status_code == 200, gen.text
        bid = gen.json().get("briefing_id")
        full = client.get(f"/api/v1/briefings/{bid}").json()
        assert full["recipient_role"] == "regional_manager"
        # every item, if any, must originate from that role's own findings
        for it in full.get("items", []):
            fid = it["finding_id"]
            src = client.get(f"/api/v1/discover/findings/{fid}").json()
            assert src["role"] == "regional_manager", "cross-role leak in briefing"


@pytest.mark.skipif(not (_app_db_available() and _target_db_available()),
                    reason="live PostgreSQL app/target DB not available")
def test_briefing_dedups_on_repeat():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        first = client.post("/api/v1/briefings/generate", json={"username": "executive", "cadence": "manual"}).json()
        if first.get("status") in ("failed",):
            pytest.skip("could not generate a briefing")
        second = client.post("/api/v1/briefings/generate", json={"username": "executive", "cadence": "manual"}).json()
        # same period + same finding set => deduped (idempotent scheduler)
        assert second["status"] in ("deduped", "generated", "empty")
        if first.get("item_count"):
            assert second["status"] == "deduped", second


@pytest.mark.skipif(not (_app_db_available() and _target_db_available()),
                    reason="live PostgreSQL app/target DB not available")
def test_briefing_preferences_persist_and_inbox():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        put = client.put("/api/v1/briefings/preferences",
                         json={"username": "executive", "frequency": "weekly", "enabled_categories": ["trend", "anomaly"]})
        assert put.status_code == 200, put.text
        pref = client.get("/api/v1/briefings/preferences?username=executive").json()
        assert pref["frequency"] == "weekly"
        assert set(pref["enabled_categories"]) == {"trend", "anomaly"}

        bad = client.put("/api/v1/briefings/preferences", json={"username": "executive", "frequency": "hourly"})
        assert bad.status_code == 422

        inbox = client.get("/api/v1/briefings/inbox?username=executive")
        assert inbox.status_code == 200
        assert isinstance(inbox.json()["briefings"], list)

        mark = client.post("/api/v1/briefings/does-not-exist/status/read")
        assert mark.status_code == 404
