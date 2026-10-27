"""Personalized Executive Briefings (Feature 4).

Turns the persisted Discover findings into scheduled, role-scoped digests so
decision-makers receive relevant intelligence without having to open Discover
manually.

Non-negotiable rules (spec Feature 4):
- ROLE-AWARE BY CONSTRUCTION: every briefing is generated strictly under the
  *recipient's own* authorization scope. We read findings whose ``role`` equals
  the recipient's resolved role (those were themselves produced under that
  role's Row-Level Security) and, when refreshing, run the Discover engine
  *as that role*. An executive digest is therefore never forwarded to a
  restricted user, and a restricted user never sees org-wide facts.
- SUPPRESSION: dismissed, stale, duplicate and low-value findings are filtered
  out; the suppressed count is recorded so the inbox is honest about what was
  hidden.
- DEDUP + IDEMPOTENCY: a briefing's signature (recipient + period + the set of
  finding signatures) prevents duplicate alerts for the same content on retry
  or repeated scheduling.
- EMPTY IS A REAL RESULT: when nothing material exists in scope, an ``empty``
  briefing is recorded with a clear explanation rather than fabricating items.

Ranking blends materiality (magnitude of change), severity, novelty and the
recipient's enabled categories. No causal claims are added; findings keep their
own fact-vs-hypothesis framing from the Discover engine.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.config import get_settings
from app.services.role_service import resolve_user_context, VERIFIED_USERS
from app.services.discovery_service import _sha1, run_discovery_job

logger = logging.getLogger("querypilot.briefing")

DEFAULT_CATEGORIES = ["trend", "anomaly", "concentration", "underperformer", "opportunity"]
_SEV_WEIGHT = {"critical": 3.0, "warning": 2.0, "watch": 1.2, "info": 0.8}


def score_finding(f: Dict[str, Any], enabled_categories: List[str]) -> float:
    """Pure, testable ranking: materiality x severity x novelty x relevance."""
    sev = _SEV_WEIGHT.get(f.get("severity", "info"), 1.0)
    materiality = math.log10(max(abs(float(f.get("delta_pct") or 0.0)), 1.0) + 1) * 10
    novelty = 1.25 if f.get("status") == "new" else 1.0
    relevance = 1.15 if (not enabled_categories or f.get("finding_type") in enabled_categories) else 0.5
    return round(sev * materiality * novelty * relevance, 3)


def build_items(findings: List[Dict[str, Any]], *, enabled_categories: List[str],
                now: datetime, stale_after_hours: int, low_value_score: float,
                max_items: int) -> Dict[str, Any]:
    """Pure selection: filter dismissed/stale/low-value, dedup by signature,
    rank, and cap. Returns kept items + a suppressed count. Never touches a DB,
    so it is directly unit-testable."""
    kept: List[Dict[str, Any]] = []
    seen_sig = set()
    suppressed = 0
    stale_cutoff = now - timedelta(hours=stale_after_hours)
    for f in findings:
        if f.get("status") == "dismissed":
            suppressed += 1
            continue
        sig = f.get("signature")
        if sig and sig in seen_sig:
            suppressed += 1
            continue
        fresh = _parse_dt(f.get("data_freshness_at") or f.get("created_at"))
        if fresh is not None and fresh < stale_cutoff:
            suppressed += 1
            continue
        s = score_finding(f, enabled_categories)
        if s < low_value_score:
            suppressed += 1
            continue
        if sig:
            seen_sig.add(sig)
        item = dict(f)
        item["briefing_score"] = s
        kept.append(item)
    kept.sort(key=lambda x: x["briefing_score"], reverse=True)
    capped = kept[:max_items]
    suppressed += max(0, len(kept) - len(capped))
    return {"items": capped, "suppressed": suppressed}


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _finding_to_dict(f) -> Dict[str, Any]:
    return {
        "id": f.id, "signature": f.signature, "severity": f.severity, "score": f.score,
        "finding_type": f.finding_type, "title": f.title, "narrative": f.narrative,
        "hypothesis": f.hypothesis, "suggested_next_steps": f.suggested_next_steps,
        "metric_name": f.metric_name, "dimension_name": f.dimension_name, "segment": f.segment,
        "baseline_value": f.baseline_value, "current_value": f.current_value,
        "delta_abs": f.delta_abs, "delta_pct": f.delta_pct, "comparison_label": f.comparison_label,
        "period_label": f.period_label, "explore_question": f.explore_question,
        "status": f.status, "data_freshness_at": f.data_freshness_at, "created_at": f.created_at,
    }


def _briefing_signature(username: str, period_label: str, items: List[Dict[str, Any]]) -> str:
    parts = [username, period_label] + sorted([it.get("signature") or it.get("id", "") for it in items])
    return _sha1(*parts)


def _summary_text(items: List[Dict[str, Any]], role: str, period_label: str) -> str:
    if not items:
        return (f"No material changes were detected within your authorized scope for {period_label}. "
                "Nothing was invented to fill this briefing.")
    top = items[0]
    crit = sum(1 for i in items if i.get("severity") == "critical")
    return (f"{len(items)} authorized insight(s) for {role} in {period_label}"
            + (f", {crit} critical." if crit else ".")) + f" Highest: {top.get('title', '')}"


class BriefingService:
    def __init__(self, db) -> None:
        self.db = db
        self.settings = get_settings()

    # ------------------------------------------------------------------
    def preferences_for(self, username: str) -> Dict[str, Any]:
        from app.models import BriefingPreference
        pref = self.db.query(BriefingPreference).filter(BriefingPreference.username == username).first()
        if pref:
            cats = pref.enabled_categories if isinstance(pref.enabled_categories, list) and pref.enabled_categories else DEFAULT_CATEGORIES
            return {"username": username, "role": pref.role, "frequency": pref.frequency,
                    "enabled_categories": cats, "delivery_channel": pref.delivery_channel}
        # default preference derived from the verified identity (least-privilege safe)
        ctx = resolve_user_context(username)
        return {"username": username, "role": ctx.role, "frequency": "daily",
                "enabled_categories": DEFAULT_CATEGORIES, "delivery_channel": "in_app"}

    def save_preference(self, username: str, *, frequency: Optional[str] = None,
                        enabled_categories: Optional[List[str]] = None) -> Dict[str, Any]:
        from app.models import BriefingPreference
        pref = self.db.query(BriefingPreference).filter(BriefingPreference.username == username).first()
        base = self.preferences_for(username)
        if not pref:
            pref = BriefingPreference(username=username, role=base["role"],
                                      frequency=frequency or base["frequency"],
                                      enabled_categories=enabled_categories if enabled_categories is not None else base["enabled_categories"],
                                      delivery_channel="in_app")
            self.db.add(pref)
        else:
            if frequency:
                pref.frequency = frequency
            if enabled_categories is not None:
                pref.enabled_categories = enabled_categories
        self.db.commit()
        return self.preferences_for(username)

    # ------------------------------------------------------------------
    def generate(self, username: str, *, cadence: str = "manual", refresh: bool = False,
                 force: bool = False) -> Dict[str, Any]:
        """Build, dedup and persist one role-scoped briefing for ``username``.

        Returns a dict with status ('generated' | 'empty' | 'deduped' | 'failed').
        """
        from app.models import Briefing, BriefingPreference, DiscoveryFinding, new_uuid
        ctx = resolve_user_context(username)
        role = ctx.role
        pref = self.preferences_for(username)
        cats = pref["enabled_categories"]

        if refresh:
            try:
                run_discovery_job(trigger="briefing_refresh", role=role)
            except Exception as exc:
                logger.warning("Briefing refresh discovery failed (continuing with stored): %s", exc)

        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(hours=self.settings.briefing_stale_after_hours)

        rows = self.db.query(DiscoveryFinding).filter(
            DiscoveryFinding.role == role,
            DiscoveryFinding.status != "dismissed",
        ).order_by(DiscoveryFinding.created_at.desc()).limit(400).all()
        findings = [_finding_to_dict(f) for f in rows]

        selection = build_items(
            findings, enabled_categories=cats, now=now,
            stale_after_hours=self.settings.briefing_stale_after_hours,
            low_value_score=self.settings.briefing_low_value_score,
            max_items=self.settings.briefing_max_items,
        )
        items = selection["items"]
        suppressed = selection["suppressed"]
        period_label = now.strftime("%Y-%m-%d")

        sig = _briefing_signature(username, period_label, items)
        if not force:
            existing = self.db.query(Briefing).filter(Briefing.signature == sig).first()
            if existing:
                return {"status": "deduped", "briefing_id": existing.id,
                        "message": "An identical briefing already exists for this period.",
                        "item_count": existing.item_count}

        freshness = None
        for it in items:
            d = _parse_dt(it.get("data_freshness_at") or it.get("created_at"))
            if d and (freshness is None or d > freshness):
                freshness = d

        status = "generated" if items else "empty"
        # slim item projection for storage/display
        compact = [{
            "finding_id": it.get("id"), "signature": it.get("signature"),
            "finding_type": it.get("finding_type"), "severity": it.get("severity"),
            "title": it.get("title"), "narrative": it.get("narrative"),
            "metric_name": it.get("metric_name"), "delta_pct": it.get("delta_pct"),
            "baseline_value": it.get("baseline_value"), "current_value": it.get("current_value"),
            "comparison_label": it.get("comparison_label"), "period_label": it.get("period_label"),
            "suggested_next_steps": it.get("suggested_next_steps"), "explore_question": it.get("explore_question"),
            "briefing_score": it.get("briefing_score"),
        } for it in items]

        briefing = Briefing(
            id=new_uuid(), signature=sig, recipient_username=username, recipient_role=role,
            cadence=cadence, period_label=period_label,
            subject=(f"Your {cadence} briefing — {period_label}"),
            summary=_summary_text(items, role, period_label),
            items=compact, item_count=len(compact), suppressed_count=suppressed,
            source_data_freshness_at=(stale_cutoff and freshness) or now,
            status=status, generated_at=now,
        )
        self.db.add(briefing)
        # stamp preference last_generated_at
        self.db.execute(text("UPDATE briefing_preferences SET last_generated_at=now() WHERE username=:u"),
                        {"u": username})
        self.db.commit()
        self.db.refresh(briefing)
        return {"status": status, "briefing_id": briefing.id, "item_count": len(compact),
                "suppressed_count": suppressed, "role": role}

    # ------------------------------------------------------------------
    def inbox(self, username: str, limit: int = 30) -> List[Dict[str, Any]]:
        from app.models import Briefing
        rows = self.db.query(Briefing).filter(
            Briefing.recipient_username == username,
        ).order_by(Briefing.generated_at.desc()).limit(limit).all()
        return [_serialize_briefing(b, full=False) for b in rows]

    def get(self, briefing_id: str) -> Optional[Dict[str, Any]]:
        from app.models import Briefing
        b = self.db.query(Briefing).filter(Briefing.id == briefing_id).first()
        return _serialize_briefing(b, full=True) if b else None

    def mark(self, briefing_id: str, status: str) -> Optional[Dict[str, Any]]:
        from app.models import Briefing
        b = self.db.query(Briefing).filter(Briefing.id == briefing_id).first()
        if not b:
            return None
        if status in ("delivered", "read"):
            b.status = status
            if status == "delivered" and not b.delivered_at:
                b.delivered_at = datetime.now(timezone.utc)
        self.db.commit()
        return _serialize_briefing(b, full=True)


def _serialize_briefing(b, *, full: bool) -> Dict[str, Any]:
    d = {
        "id": b.id, "recipient_username": b.recipient_username, "recipient_role": b.recipient_role,
        "cadence": b.cadence, "period_label": b.period_label, "subject": b.subject,
        "summary": b.summary, "item_count": b.item_count, "suppressed_count": b.suppressed_count,
        "status": b.status, "retry_count": b.retry_count,
        "source_data_freshness_at": b.source_data_freshness_at.isoformat() if b.source_data_freshness_at else None,
        "generated_at": b.generated_at.isoformat() if b.generated_at else None,
        "delivered_at": b.delivered_at.isoformat() if b.delivered_at else None,
    }
    if full:
        d["items"] = b.items or []
    return d


def _json(value) -> str:
    import json
    return json.dumps(value)


# ---------------------------------------------------------------------------
# Scheduled job: generate for every enabled recipient, idempotently.
# ---------------------------------------------------------------------------
def run_briefings_job(cadence: str = "daily", refresh: bool = False) -> Dict[str, Any]:
    from app.database import get_app_session_factory
    from app.models import BriefingPreference
    factory = get_app_session_factory()
    db = factory()
    settings = get_settings()
    summary = {"generated": 0, "empty": 0, "deduped": 0, "failed": 0, "recipients": []}
    try:
        svc = BriefingService(db)
        # configured recipients, else fall back to all verified identities
        prefs = db.query(BriefingPreference).filter(BriefingPreference.frequency != "disabled").all()
        if prefs:
            recipients = [(p.username, p.frequency) for p in prefs]
        else:
            recipients = [(uname, cadence) for uname in VERIFIED_USERS.keys()]
        for username, freq in recipients:
            this_cadence = cadence if cadence in ("daily", "weekly") else (freq or "daily")
            try:
                res = svc.generate(username, cadence=this_cadence, refresh=refresh)
                summary[res.get("status", "generated")] = summary.get(res.get("status", "generated"), 0) + 1
                summary["recipients"].append({"username": username, **{k: res.get(k) for k in ("status", "item_count", "briefing_id")}})
            except Exception as exc:
                summary["failed"] += 1
                summary["recipients"].append({"username": username, "status": "failed", "error": str(exc)[:150]})
                logger.exception("Briefing generation failed for %s", username)
        return summary
    finally:
        db.close()
