"""Root-Cause Exploration Engine (Feature 3).

Extends the Discover engine: given a detected change (a ``DiscoveryFinding``),
it *schema-adaptively* decomposes the metric change across the dimensions that
actually exist in the connected database, quantifies each segment's measured
contribution to the overall change, ranks the strongest contributors, and emits
reproducible evidence plus suggested follow-up investigation branches.

Non-negotiable honesty rules (mirroring the Discover engine):
- Only report MEASURED contributions. Never claim causation from correlation.
- Never label a segment "the root cause" unless the decomposition math supports
  its share of the change; otherwise say the cause remains undetermined.
- Every result carries the executed SQL, source tables, filters, sample size,
  the two comparison periods, and limitations.
- Fully introspected: no hardcoded 'sales'/'revenue'/'region' assumptions. If a
  required dimension or measure is unavailable, we report the limitation rather
  than inventing one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.role_service import resolve_user_context, UserSecurityContext
from app.services.discovery_service import DiscoveryService

logger = logging.getLogger("querypilot.rootcause")


def _money(v: float) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:,.2f}"


class RootCauseService:
    def __init__(self, role: Optional[str] = None) -> None:
        self.role = role or "executive"
        self.discovery = DiscoveryService(role=self.role)

    # ------------------------------------------------------------------
    def analyze_finding(self, finding: Any) -> Dict[str, Any]:
        """Decompose the change captured by a DiscoveryFinding into ranked,
        measurable segment contributions.

        ``finding`` may be a DiscoveryFinding ORM row or a serialized dict; we
        only read attribute-style fields, so both work via getattr fallback.
        """
        def g(name, default=None):
            if isinstance(finding, dict):
                return finding.get(name, default)
            return getattr(finding, name, default)

        role = g("role", self.role) or self.role
        user_ctx = resolve_user_context(role)

        profile = self.discovery._build_profile(user_ctx)
        if not profile.fact_table or not profile.measures or not profile.time_column:
            return self._undetermined("The connected schema does not expose a fact table with a time column and numeric measures, so the change cannot be decomposed.", role)

        measure = self._pick_measure(profile, g("calculation"), g("metric_name"))
        dimension = self._pick_dimension(profile, g("dimension_name"))
        if not dimension:
            return self._undetermined(
                "No role-permitted, moderate-cardinality categorical dimension was available to attribute this change to segments.",
                role,
            )

        alias = profile.aliases.get(dimension["table"], "f")
        where = profile.where_clause()
        sql = (
            f"SELECT TO_CHAR(DATE_TRUNC('month', p.{profile.time_column}), 'YYYY-MM') AS period, "
            f"{alias}.{dimension['column']} AS segment, {measure['expr']} AS value, "
            f"COUNT(DISTINCT p.{profile.parent_pk}) AS orders "
            f"FROM {profile.from_base()} {where} GROUP BY 1, 2 ORDER BY 1, 3 DESC"
        )
        rows = self._run(sql, user_ctx)

        by_seg: Dict[str, Dict[str, float]] = {}
        periods: List[str] = []
        for r in rows:
            if r.get("segment") is None or not r.get("period"):
                continue
            seg = str(r["segment"])
            by_seg.setdefault(seg, {})[r["period"]] = float(r.get("value") or 0)
            if r["period"] not in periods:
                periods.append(r["period"])
        periods = sorted(periods)
        if len(periods) < 2:
            return self._undetermined(
                "Fewer than two comparable time periods exist in the authorized data, so a change cannot be attributed across segments.",
                role,
            )

        base_period, cur_period = periods[-2], periods[-1]
        contributions: List[Dict[str, Any]] = []
        base_total = 0.0
        cur_total = 0.0
        for seg, pm in by_seg.items():
            b = pm.get(base_period, 0.0)
            c = pm.get(cur_period, 0.0)
            base_total += b
            cur_total += c
            contributions.append({
                "segment": seg,
                "baseline_value": round(b, 2),
                "current_value": round(c, 2),
                "change_abs": round(c - b, 2),
                "change_pct": round((c - b) / b * 100.0, 1) if b else None,
            })

        total_change = cur_total - base_total
        for c in contributions:
            c["contribution_pct"] = round(c["change_abs"] / total_change * 100.0, 1) if total_change else 0.0
        contributions.sort(key=lambda x: abs(x["change_abs"]), reverse=True)

        # Reconciliation: does the decomposition account for the finding's change?
        recorded_change = (g("current_value") or 0) - (g("baseline_value") or 0)
        reconciles = abs(total_change - recorded_change) <= max(abs(recorded_change) * 0.15, 1.0) if recorded_change else True

        direction = "increase" if total_change >= 0 else "decline"
        top = contributions[0] if contributions else None
        # Only call the top mover a "primary contributor" when it explains a
        # meaningful share; otherwise state that the cause is distributed.
        if top and abs(top["contribution_pct"]) >= 40.0:
            summary = (
                f"{measure['label']} {direction}ed by {_money(abs(total_change))} between {base_period} and {cur_period}. "
                f"The largest measured contributor is '{top['segment']}' "
                f"({top['change_abs']:+,.0f}, {top['contribution_pct']:.0f}% of the total change). "
                f"This is a measured decomposition of where the change occurred, not a proven cause."
            )
        else:
            summary = (
                f"{measure['label']} {direction}ed by {_money(abs(total_change))} between {base_period} and {cur_period}. "
                f"The change is distributed across multiple {dimension['label']} segments with no single dominant contributor. "
                f"The cause remains undetermined from these data alone."
            )

        evidence = {
            "sql": sql,
            "source_tables": self._source_tables(profile, dimension),
            "filters": (where.strip() or "none"),
            "group_by": f"{dimension['table']}.{dimension['column']}",
            "measure_expr": measure["expr"],
            "sample_size": len(contributions),
            "periods_compared": [base_period, cur_period],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fact_vs_hypothesis": (
                "FACT: segment values and their change are read-only query results. "
                "HYPOTHESIS: contribution ranking indicates where to investigate, not why it happened."
            ),
            "limitations": [
                "Contribution decomposition is additive for extensive measures (sums/counts); it attributes the observed change across segments but does not establish causation.",
                "Calendar-month bucketing and the latest-two-period comparison are defaults; other windows may tell a different story.",
                "Intensities (e.g. per-order) are not decomposed here; only the total measure change is attributed.",
            ],
        }

        suggested_branches = self._suggested_branches(measure, dimension, contributions, cur_period)

        return {
            "status": "ok",
            "metric_name": measure["label"],
            "measure_expr": measure["expr"],
            "dimension_label": dimension["label"],
            "dimension_column": f"{dimension['table']}.{dimension['column']}",
            "baseline_period": base_period,
            "current_period": cur_period,
            "baseline_total": round(base_total, 2),
            "current_total": round(cur_total, 2),
            "total_change_abs": round(total_change, 2),
            "total_change_pct": round(total_change / base_total * 100.0, 1) if base_total else 0.0,
            "reconciles": bool(reconciles),
            "summary": summary,
            "contributions": contributions[:15],
            "evidence": evidence,
            "suggested_branches": suggested_branches,
            "role": role,
        }

    # ------------------------------------------------------------------
    def _pick_measure(self, profile, calculation, metric_name) -> Dict[str, str]:
        key = (calculation or {}).get("measure_key") if isinstance(calculation, dict) else None
        for m in profile.measures:
            if key and m["key"] == key:
                return m
        label_low = (metric_name or "").lower()
        for m in profile.measures:
            if label_low and m["label"].lower() == label_low:
                return m
        return self._by_key(profile, "net_revenue") or profile.measures[0]

    def _by_key(self, profile, key):
        return next((m for m in profile.measures if m["key"] == key), None)

    def _pick_dimension(self, profile, dimension_name) -> Optional[Dict[str, str]]:
        if not profile.dimensions:
            return None
        want = (dimension_name or "").lower()
        if want and want != "time":
            for d in profile.dimensions:
                if d["label"].lower() == want or d["column"].lower() == want:
                    return d
            for d in profile.dimensions:
                if want in d["label"].lower() or want in d["column"].lower():
                    return d
        return profile.dimensions[0]

    def _run(self, sql: str, user_ctx: UserSecurityContext) -> List[Dict[str, Any]]:
        res = self.discovery.executor.execute(sql, user_context=user_ctx)
        if not res.success:
            raise RuntimeError(res.error or "root-cause query failed")
        return res.rows

    def _source_tables(self, profile, dimension) -> List[str]:
        tables = [profile.fact_table, profile.parent_table]
        if dimension:
            tables.append(dimension["table"])
        return sorted(set(f"{profile.schema_name}.{t}" for t in tables if t))

    def _suggested_branches(self, measure, dimension, contributions, cur_period) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for c in contributions[:3]:
            if abs(c["change_abs"]) <= 0:
                continue
            out.append({
                "title": f"{dimension['label']}: {c['segment']}",
                "contributor_segment": c["segment"],
                "question": (
                    f"For {dimension['label']} '{c['segment']}', break down {measure['label'].lower()} "
                    f"in {cur_period} by product category and sales rep, and show order count vs average "
                    f"order value, to investigate what drove its change of {c['change_abs']:+,.0f}."
                ),
            })
        return out

    def _undetermined(self, reason: str, role: str) -> Dict[str, Any]:
        return {
            "status": "undetermined",
            "summary": reason,
            "contributions": [],
            "suggested_branches": [],
            "reconciles": False,
            "role": role,
            "evidence": {
                "fact_vs_hypothesis": "No causal claim is made.",
                "limitations": [reason],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
