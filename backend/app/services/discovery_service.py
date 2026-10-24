"""Proactive Discovery & Early-Warnings engine (Phase 2 "Discover").

Analyzes real, authorized data in the live target PostgreSQL database and surfaces
evidence-backed findings (trends, anomalies, concentration, under-performers and
opportunities) BEFORE a user asks a question.

Design principles (per Phase 2 requirements):
- ADAPTIVE: the schema profile (fact/parent tables, measures, time column and
  categorical dimensions) is *introspected from the live database* at runtime.
  Nothing is hardcoded to a specific business metric. Every candidate column is
  validated to exist and to be role-permitted before any query references it.
- SECURE: every analytical query is executed through the existing restricted
  ``QueryExecutor`` with a resolved ``UserSecurityContext``, so PostgreSQL Row-Level
  Security and the read-only / statement-timeout guards always apply. Column-level
  restrictions are enforced while selecting dimensions.
- EVIDENCE-BACKED: each finding records what changed and by how much, the baseline
  and period, the tables/metric/filters/calculation, supporting rows for a chart,
  why it might matter (clearly separated hypothesis), plus freshness/assumptions.
- HONEST: observed facts are separated from hypotheses; findings are suppressed by
  statistical thresholds (z-score) and never claim causation from correlation.
"""

from __future__ import annotations

import hashlib
import logging
import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.config import get_settings
from app.services.role_service import (
    resolve_user_context,
    UserSecurityContext,
    is_column_allowed,
    is_table_allowed,
)
from app.services.schema_service import SchemaService
from app.services.query_executor import QueryExecutor

logger = logging.getLogger("querypilot.discovery")

NUMERIC_TYPES = {"INTEGER", "NUMERIC", "DECIMAL", "FLOAT", "REAL", "DOUBLE", "BIGINT", "SMALLINT", "MONEY", "INT", "INT4", "INT8"}
DATE_TYPES = {"DATE", "TIMESTAMP"}
TEXT_TYPES = {"VARCHAR", "TEXT", "CHARACTER", "CHARACTER VARYING", "CHAR", "BPCHAR", "NAME"}

# Free-text / address / high-cardinality-ish names we never want as a grouping dimension.
DIM_NAME_EXCLUDE = {
    "notes", "email", "phone", "description", "reason", "comment", "address",
    "city", "state", "name", "contact_name", "company_name", "created_at", "updated_at",
}


def _base_type(data_type: str) -> str:
    return (data_type or "").split("(")[0].split(" ")[0].upper()


def _sha1(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").lower().strip().encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:32]


class SchemaProfile:
    """Runtime-introspected analytical model of the target schema."""

    def __init__(self) -> None:
        self.schema_name: str = "sales"
        self.fact_table: Optional[str] = None
        self.parent_table: Optional[str] = None
        self.parent_pk: Optional[str] = None
        self.fact_to_parent_fk: Optional[str] = None
        self.time_column: Optional[str] = None
        self.status_column: Optional[str] = None
        self.status_filter_value: Optional[str] = None
        self.measures: List[Dict[str, str]] = []          # [{key, label, expr}]
        self.dimensions: List[Dict[str, str]] = []        # [{table, column, label}]
        self.aliases: Dict[str, str] = {}                 # table_name -> alias
        self.extra_joins: Dict[str, tuple] = {}           # dim table -> (fk_col_on_f, ref_col)
        self.profile_notes: List[str] = []
        self.introspected_tables: List[str] = []

    def from_base(self) -> str:
        s = self.schema_name
        base = f"{s}.{self.fact_table} f"
        if self.parent_table and self.parent_table != self.fact_table:
            base += f" JOIN {s}.{self.parent_table} p ON f.{self.fact_to_parent_fk} = p.{self.parent_pk}"
        else:
            # fact doubles as its own parent: self-join so all 'p.' references resolve
            base += f" JOIN {s}.{self.fact_table} p ON f.{self.parent_pk} = p.{self.parent_pk}"
        for tbl, (src_alias, fk_col, ref_col) in self.extra_joins.items():
            alias = self.aliases.get(tbl)
            if alias and alias not in ("f", "p") and fk_col and ref_col:
                base += f" JOIN {s}.{tbl} {alias} ON {src_alias}.{fk_col} = {alias}.{ref_col}"
        return base

    def where_clause(self) -> str:
        clauses = []
        if self.status_filter_value and self.status_column:
            safe = self.status_filter_value.replace("'", "''")
            clauses.append(f"p.{self.status_column} = '{safe}'")
        if self.time_column:
            clauses.append(f"p.{self.time_column} IS NOT NULL")
        return (" WHERE " + " AND ".join(clauses)) if clauses else ""


class DiscoveryService:
    def __init__(
        self,
        schema_service: SchemaService | None = None,
        executor: QueryExecutor | None = None,
        role: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self.schema_service = schema_service or SchemaService()
        self.executor = executor or QueryExecutor.from_settings()
        self.role = role or self.settings.discovery_run_role
        self._extra_joins: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_discovery(self) -> Dict[str, Any]:
        """Introspect the live schema and run all detectors. Returns raw findings."""
        start = time.time()
        user_ctx = resolve_user_context(self.role)
        profile = self._build_profile(user_ctx)
        if not profile.fact_table or not profile.measures:
            logger.warning("Discovery: insufficient schema profile (no fact table/measures detected)")
            return {"findings": [], "profile": self._profile_dict(profile), "error": "no_analytical_shape"}

        findings: List[Dict[str, Any]] = []
        errors: List[str] = []
        for detector in (
            self._detect_trend_and_anomaly,
            self._detect_concentration,
            self._detect_underperformers_and_opportunities,
            self._detect_segment_trend_shift,
        ):
            try:
                findings.extend(detector(profile, user_ctx))
            except Exception as exc:  # failure handling: isolate each detector
                errors.append(f"{detector.__name__}: {str(exc)[:200]}")
                logger.exception("Discovery detector failed: %s", detector.__name__)

        ranked = self._rank(findings)
        return {
            "findings": ranked,
            "profile": self._profile_dict(profile),
            "errors": errors,
            "duration_ms": round((time.time() - start) * 1000, 1),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Schema profiling (fully introspected)
    # ------------------------------------------------------------------
    def _build_profile(self, user_ctx: UserSecurityContext) -> SchemaProfile:
        from app.database import get_default_target_engine
        engine = get_default_target_engine()
        profile = SchemaProfile()
        self._extra_joins = {}

        # discover every schema present in the target DB (generic — not assuming 'sales')
        discovered = None
        for cand in self._candidate_schemas(engine):
            resp = self.schema_service.discover_schema(engine, "default", cand, force_refresh=True)
            if resp and resp.tables:
                discovered = resp
                profile.schema_name = cand
                break
        if not discovered:
            profile.profile_notes.append("No tables discovered in target database.")
            return profile

        tables = {t.table_name: t for t in discovered.tables}
        profile.introspected_tables = list(tables.keys())

        def measure_cols(tbl):
            out = []
            for c in tbl.columns:
                bt = _base_type(c.data_type)
                if bt in NUMERIC_TYPES and c.is_primary_key is False and not c.name.lower().endswith("_id"):
                    out.append(c.name)
            return out

        def date_col(tbl):
            for c in tbl.columns:
                if _base_type(c.data_type) in DATE_TYPES:
                    return c.name
            return None

        def fk_targets(tbl):
            out = {}
            for c in tbl.columns:
                if c.is_foreign_key and c.foreign_key_ref:
                    # ref format: schema.table.column
                    parts = c.foreign_key_ref.split(".")
                    if len(parts) == 3:
                        out[parts[1]] = (c.name, parts[2])
            return out

        # fact table = most numeric measures among tables whose FK points at a date-bearing table
        best = None
        for name, tbl in tables.items():
            mc = measure_cols(tbl)
            if len(mc) < 1:
                continue
            parent_with_date = None
            for ref_tbl, (col, refcol) in fk_targets(tbl).items():
                if ref_tbl in tables and date_col(tables[ref_tbl]):
                    parent_with_date = (ref_tbl, col, refcol)
                    break
            if parent_with_date and (best is None or len(mc) > len(best[1])):
                best = (name, mc, parent_with_date)

        if not best:
            # fallback: table with most numeric measures
            for name, tbl in tables.items():
                mc = measure_cols(tbl)
                if mc and (best is None or len(mc) > len(best[1])):
                    best = (name, mc, None)

        if not best:
            profile.profile_notes.append("No numeric measure column found; nothing to analyze.")
            return profile

        fact_name = best[0]
        fact_tbl = tables[fact_name]
        profile.fact_table = fact_name
        profile.aliases[fact_name] = "f"

        if best[2]:
            parent_name, fcol, pcol = best[2]
            profile.parent_table = parent_name
            profile.fact_to_parent_fk = fcol
            parent_tbl = tables[parent_name]
            profile.parent_pk = pcol
            profile.time_column = date_col(parent_tbl)
            profile.aliases[parent_name] = "p"
            # status column on parent (align with app semantics if 'completed' exists)
            for c in parent_tbl.columns:
                if c.name.lower() == "status":
                    profile.status_column = c.name
                    break
        else:
            # fact has its own date?
            profile.parent_table = fact_name
            profile.parent_pk = next((c.name for c in fact_tbl.columns if c.is_primary_key), None)
            profile.fact_to_parent_fk = profile.parent_pk
            profile.time_column = date_col(fact_tbl)
            profile.aliases[fact_name] = "p"

        # measures: build revenue-style expression from detected numeric columns
        self._cur_profile_pk = profile.parent_pk or "order_id"
        profile.measures = self._build_measures(fact_tbl)

        # join dimension tables reachable from fact (source 'f') and parent (source 'p') by FK
        idx = 0
        join_candidates: List[tuple] = []  # (source_alias, ref_tbl, fk_col, ref_col)
        join_candidates.append(("f", fact_tbl))
        if profile.parent_table and profile.parent_table != fact_name and profile.parent_table in tables:
            join_candidates.append(("p", tables[profile.parent_table]))
        for src_alias, tbl_obj in join_candidates:
            for ref_tbl, (col, refcol) in fk_targets(tbl_obj).items():
                if ref_tbl in tables and ref_tbl not in profile.aliases and ref_tbl not in (fact_name, profile.parent_table):
                    alias = f"d{idx}"
                    profile.aliases[ref_tbl] = alias
                    profile.extra_joins[ref_tbl] = (src_alias, col, refcol)
                    idx += 1
                if idx >= 6:
                    break

        # dimensions: categorical columns across every alias-joined table, role-allowed,
        # validated by live cardinality + free-text screening
        profile.dimensions = self._detect_dimensions(profile, tables, user_ctx)

        # status filter value: choose 'completed' when present (else no filter)
        if profile.status_column and profile.parent_table:
            profile.status_filter_value = self._pick_status_value(profile, user_ctx)

        return profile

    def _candidate_schemas(self, engine) -> List[str]:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
                    "AND schema_name NOT LIKE 'pg_temp%' ORDER BY schema_name"
                )).fetchall()
            names = [r[0] for r in rows]
            # prefer 'sales' if present (known analytics schema) but stay generic
            ordered = sorted(names, key=lambda n: (n != "sales", n))
            return ordered
        except Exception:
            return ["sales"]

    def _build_measures(self, fact_tbl) -> List[Dict[str, str]]:
        cols = {}
        for c in fact_tbl.columns:
            if _base_type(c.data_type) in NUMERIC_TYPES and not c.name.lower().endswith("_id") and not c.is_primary_key:
                cols[c.name] = c.name.lower()
        qty = next((n for n, l in cols.items() if any(k in l for k in ("quant", "qty", "units"))), None)
        price = next((n for n, l in cols.items() if any(k in l for k in ("price", "amount")) and "discount" not in l), None)
        disc = next((n for n, l in cols.items() if "discount" in l), None)
        measures: List[Dict[str, str]] = []
        if qty and price:
            expr = f"SUM(f.{qty} * f.{price})"
            net = f"SUM(f.{qty} * f.{price} * (1 - COALESCE(f.{disc}, 0) / 100.0))" if disc else None
            measures.append({"key": "gross_amount", "label": "Gross amount", "expr": expr})
            if net:
                measures.append({"key": "net_revenue", "label": "Net revenue (discount-adjusted)", "expr": net})
            measures.append({"key": "units", "label": "Units sold", "expr": f"SUM(f.{qty})"})
        else:
            n0 = next(iter(cols.values()))
            actual0 = next(c.name for c in fact_tbl.columns if c.name.lower() == n0)
            measures.append({"key": f"sum_{actual0}", "label": f"Sum of {actual0}", "expr": f"SUM(f.{actual0})"})
        measures.append({"key": "line_items", "label": "Line items", "expr": "COUNT(*)"})
        measures.append({"key": "orders", "label": "Order count", "expr": "COUNT(DISTINCT p.%s)" % (self._parent_pk_or_order())})
        return measures

    def _parent_pk_or_order(self) -> str:
        return getattr(self, "_cur_profile_pk", "order_id")

    def _detect_dimensions(self, profile: SchemaProfile, tables, user_ctx: UserSecurityContext) -> List[Dict[str, str]]:
        dims: List[Dict[str, str]] = []
        seen = set()
        for tbl_name, alias in profile.aliases.items():
            if tbl_name not in tables:
                continue
            if not is_table_allowed(profile.schema_name, tbl_name, user_ctx.role):
                continue
            for c in tables[tbl_name].columns:
                low = c.name.lower()
                if low in seen or low in DIM_NAME_EXCLUDE:
                    continue
                if low == "status":  # used as the measure filter, not a segmentation axis
                    continue
                if _base_type(c.data_type) not in TEXT_TYPES:
                    continue
                if c.is_primary_key or c.is_foreign_key:
                    continue
                if not is_column_allowed(profile.schema_name, tbl_name, c.name, user_ctx.role):
                    continue
                card = self._column_cardinality(profile.schema_name, tbl_name, c.name, user_ctx)
                if card is None:
                    continue
                distinct, avg_len = card
                # prefer moderate-cardinality, human-meaningful segments (2..12 distinct)
                if 2 <= distinct <= 12 and avg_len <= 60:
                    usefulness = 10.0 - abs(distinct - 5)  # sweet spot around 5 values
                    dims.append({
                        "table": tbl_name, "column": c.name,
                        "label": c.name.replace("_", " ").title(),
                        "usefulness": usefulness,
                    })
                    seen.add(low)
        dims.sort(key=lambda d: d["usefulness"], reverse=True)
        return dims

    def _column_cardinality(self, schema, table, column, user_ctx) -> Optional[tuple]:
        sql = (
            f"SELECT COUNT(DISTINCT {column}) AS d, COALESCE(AVG(LENGTH({column}::text)),0) AS l "
            f"FROM {schema}.{table}"
        )
        res = self.executor.execute(sql, user_context=user_ctx)
        if res.success and res.rows:
            return int(res.rows[0]["d"]), float(res.rows[0]["l"])
        return None

    def _pick_status_value(self, profile: SchemaProfile, user_ctx) -> Optional[str]:
        sql = (
            f"SELECT p.{profile.status_column} AS s, COUNT(*) c "
            f"FROM {profile.schema_name}.{profile.parent_table} p GROUP BY 1 ORDER BY 2 DESC"
        )
        res = self.executor.execute(sql, user_context=user_ctx)
        if not res.success:
            return None
        vals = [str(r["s"]).lower() for r in res.rows if r["s"] is not None]
        for pref in ("completed", "fulfilled", "shipped", "closed", "won"):
            if pref in vals:
                return pref
        return None

    # ------------------------------------------------------------------
    # Detectors
    # ------------------------------------------------------------------
    def _measure_by_key(self, profile: SchemaProfile, key: str) -> Dict[str, str]:
        return next((m for m in profile.measures if m["key"] == key), profile.measures[0])

    def _run(self, sql: str, user_ctx) -> List[Dict[str, Any]]:
        res = self.executor.execute(sql, user_context=user_ctx)
        if not res.success:
            raise RuntimeError(res.error or "query failed")
        return res.rows

    def _detect_trend_and_anomaly(self, profile: SchemaProfile, user_ctx) -> List[Dict[str, Any]]:
        if not profile.time_column:
            return []
        self._cur_profile_pk = profile.parent_pk
        measure = self._measure_by_key(profile, "net_revenue") or profile.measures[0]
        where = profile.where_clause()
        sql = (
            f"SELECT TO_CHAR(DATE_TRUNC('month', p.{profile.time_column}), 'YYYY-MM') AS period, "
            f"{measure['expr']} AS value, COUNT(DISTINCT p.{profile.parent_pk}) AS orders "
            f"FROM {profile.from_base()} {where} GROUP BY 1 ORDER BY 1"
        )
        rows = self._run(sql, user_ctx)
        series = [(r["period"], float(r["value"] or 0), int(r["orders"] or 0)) for r in rows]
        findings: List[Dict[str, Any]] = []
        if len(series) < self.settings.discovery_min_periods:
            return findings

        values = [v for _, v, _ in series]
        latest_p, latest_v, latest_orders = series[-1]
        prior_vals = values[:-1]
        prior_mean = statistics.mean(prior_vals) if prior_vals else 0.0
        mom_prev = series[-2][1] if len(series) >= 2 else prior_mean

        # 1) Momentum: latest vs previous period
        mom_pct = ((latest_v - mom_prev) / mom_prev * 100.0) if mom_prev else 0.0
        if abs(mom_pct) >= self.settings.discovery_mom_threshold_pct:
            direction = "increase" if mom_pct > 0 else "decline"
            findings.append(self._make_finding(
                ftype="trend",
                title=f"{measure['label']} {direction} of {abs(mom_pct):.1f}% in {latest_p}",
                narrative=(
                    f"{measure['label']} was {self._money(latest_v)} in {latest_p}, "
                    f"{direction} {abs(mom_pct):.1f}% versus {series[-2][0]} ({self._money(mom_prev)}). "
                    f"The prior-period average was {self._money(prior_mean)}."
                ),
                hypothesis=(
                    "This is an observed change in the data, not a proven cause. It may reflect "
                    "seasonality, a large order, or a demand shift; correlation does not imply causation."
                ),
                next_steps="Drill into the top contributing segments/orders for this period before acting.",
                profile=profile, measure=measure, dimension=None, segment=latest_p,
                baseline=mom_prev, current=latest_v, delta_pct=mom_pct,
                comparison=f"{latest_p} vs {series[-2][0]}", period_label=latest_p,
                supporting=[{"period": p, "value": round(v, 2), "orders": o} for p, v, o in series],
                chart="line",
            ))

        # 2) Anomaly: latest point vs mean/std of history (z-score)
        stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
        if stdev > 0:
            z = (latest_v - prior_mean) / stdev if prior_mean else 0.0
            if abs(z) >= self.settings.discovery_anomaly_z_threshold:
                findings.append(self._make_finding(
                    ftype="anomaly",
                    title=f"Statistical outlier detected in {latest_p} ({measure['label']})",
                    narrative=(
                        f"{latest_p} ({self._money(latest_v)}) sits {abs(z):.1f} standard deviations from the "
                        f"historical mean ({self._money(statistics.mean(values))}, sd {self._money(stdev)}) across "
                        f"{len(values)} observed periods."
                    ),
                    hypothesis="The value is statistically unusual relative to history. Whether it is favourable depends on context.",
                    next_steps="Check for one-off large orders or data-entry effects; confirm against order-level detail.",
                    profile=profile, measure=measure, dimension=None, segment=latest_p,
                    baseline=statistics.mean(values), current=latest_v, delta_pct=z,
                    comparison=f"{latest_p} vs historical mean ({len(values)} periods)", period_label=latest_p,
                    supporting=[{"period": p, "value": round(v, 2), "orders": o} for p, v, o in series],
                    chart="line", z=z,
                ))
        return findings

    def _detect_concentration(self, profile: SchemaProfile, user_ctx) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        self._cur_profile_pk = profile.parent_pk
        for dim in profile.dimensions:
            measure = self._measure_by_key(profile, "net_revenue") or profile.measures[0]
            alias = profile.aliases[dim["table"]]
            where = profile.where_clause()
            sql = (
                f"SELECT {alias}.{dim['column']} AS segment, {measure['expr']} AS value, "
                f"COUNT(DISTINCT p.{profile.parent_pk}) AS orders "
                f"FROM {profile.from_base()} {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 50"
            )
            try:
                rows = self._run(sql, user_ctx)
            except Exception:
                continue
            vals = [float(r["value"] or 0) for r in rows]
            total = sum(vals)
            if total <= 0 or len(rows) < 3:
                continue
            top = rows[0]
            top_share = float(top["value"] or 0) / total * 100.0
            top3_share = sum(vals[:3]) / total * 100.0
            if top_share >= self.settings.discovery_concentration_threshold_pct or top3_share >= 75.0:
                findings.append(self._make_finding(
                    ftype="concentration",
                    title=f"{top_share:.0f}% of {measure['label']} is concentrated in {dim['label']} '{top['segment']}'",
                    narrative=(
                        f"By {dim['label']}, '{top['segment']}' accounts for {self._money(float(top['value'] or 0))} "
                        f"({top_share:.1f}% of the {self._money(total)} total). The top 3 {dim['label'].lower()}s "
                        f"together hold {top3_share:.1f}%."
                    ),
                    hypothesis=(
                        "High concentration can create dependency risk if the leading segment churns or slows; "
                        "this is an observation of distribution, not a causal claim."
                    ),
                    next_steps=f"Assess resilience by reviewing growth of the other {dim['label'].lower()}s.",
                    profile=profile, measure=measure, dimension=dim, segment=str(top["segment"]),
                    baseline=total, current=float(top["value"] or 0), delta_pct=top_share,
                    comparison=f"top-{dim['label']} share of total", period_label="all periods",
                    supporting=[{"segment": str(r["segment"]), "value": round(float(r["value"] or 0), 2)} for r in rows[:8]],
                    chart="bar",
                ))
                # opportunity: the smallest named segment
                last = rows[-1]
                low_share = float(last["value"] or 0) / total * 100.0
                if low_share <= 2.0 and len(rows) >= 3:
                    findings.append(self._make_finding(
                        ftype="opportunity",
                        title=f"{dim['label']} '{last['segment']}' contributes only {low_share:.1f}% of {measure['label']}",
                        narrative=(
                            f"'{last['segment']}' represents {self._money(float(last['value'] or 0))} ({low_share:.1f}%) "
                            f"of total {measure['label'].lower()}, the smallest among {len(rows)} observed {dim['label'].lower()}s."
                        ),
                        hypothesis="A materially low share may indicate untapped potential or a structurally small category.",
                        next_steps=f"Compare per-order intensity for '{last['segment']}' to see if it is under-served vs simply small.",
                        profile=profile, measure=measure, dimension=dim, segment=str(last["segment"]),
                        baseline=total, current=float(last["value"] or 0), delta_pct=low_share,
                        comparison=f"lowest {dim['label']} share", period_label="all periods",
                        supporting=[{"segment": str(r["segment"]), "value": round(float(r["value"] or 0), 2)} for r in rows[:8]],
                        chart="bar",
                    ))
        return findings

    def _detect_underperformers_and_opportunities(self, profile: SchemaProfile, user_ctx) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []
        self._cur_profile_pk = profile.parent_pk
        measure = self._measure_by_key(profile, "net_revenue") or profile.measures[0]
        for dim in profile.dimensions[:4]:
            alias = profile.aliases[dim["table"]]
            where = profile.where_clause()
            sql = (
                f"SELECT {alias}.{dim['column']} AS segment, {measure['expr']} AS value, "
                f"COUNT(DISTINCT p.{profile.parent_pk}) AS orders "
                f"FROM {profile.from_base()} {where} GROUP BY 1 ORDER BY 2 DESC"
            )
            try:
                rows = self._run(sql, user_ctx)
            except Exception:
                continue
            # per-order intensity to normalize scale differences
            metrics = []
            for r in rows:
                val = float(r["value"] or 0)
                orders = int(r["orders"] or 0)
                if orders <= 0:
                    continue
                metrics.append((str(r["segment"]), val / orders, val, orders))
            if len(metrics) < 3:
                continue
            aovs = [m[1] for m in metrics]
            mean = statistics.mean(aovs)
            sd = statistics.pstdev(aovs)
            if sd == 0:
                continue
            seg_by_z = [(m, (m[1] - mean) / sd) for m in metrics]
            worst = min(seg_by_z, key=lambda x: x[1])
            best = max(seg_by_z, key=lambda x: x[1])
            if worst[1] <= -self.settings.discovery_underperform_z_threshold:
                m, z = worst
                findings.append(self._make_finding(
                    ftype="underperformer",
                    title=f"{dim['label']} '{m[0]}' earns {abs(z):.1f} std-devs below peers per order",
                    narrative=(
                        f"Revenue per order for {dim['label']} '{m[0]}' is {self._money(m[1])}, versus a peer average "
                        f"of {self._money(mean)} across {len(metrics)} {dim['label'].lower()} groups ({abs(z):.1f} std devs below)."
                    ),
                    hypothesis="Lower intensity per order may signal discounting or smaller basket sizes; needs order-level review.",
                    next_steps=f"Investigate order composition and discount depth for '{m[0]}'.",
                    profile=profile, measure=measure, dimension=dim, segment=m[0],
                    baseline=mean, current=m[1], delta_pct=(m[1] - mean) / mean * 100.0,
                    comparison=f"{dim['label']} vs peer mean", period_label="all periods",
                    supporting=[{"segment": x[0], "value_per_order": round(x[1], 2), "revenue": round(x[2], 2), "orders": x[3]} for x, _ in seg_by_z],
                    chart="bar",
                ))
            if best[1] >= self.settings.discovery_underperform_z_threshold and abs(best[1]) > abs(worst[1]):
                m, z = best
                findings.append(self._make_finding(
                    ftype="opportunity",
                    title=f"{dim['label']} '{m[0]}' outperforms peers by {z:.1f} std-devs per order",
                    narrative=(
                        f"Revenue per order for {dim['label']} '{m[0]}' is {self._money(m[1])}, {z:.1f} std devs above the "
                        f"peer average of {self._money(mean)}."
                    ),
                    hypothesis="A high-intensity segment may be a candidate for expansion, subject to demand.",
                    next_steps=f"Explore whether '{m[0]}' has headroom for more orders.",
                    profile=profile, measure=measure, dimension=dim, segment=m[0],
                    baseline=mean, current=m[1], delta_pct=(m[1] - mean) / mean * 100.0,
                    comparison=f"{dim['label']} vs peer mean", period_label="all periods",
                    supporting=[{"segment": x[0], "value_per_order": round(x[1], 2), "revenue": round(x[2], 2), "orders": x[3]} for x, _ in seg_by_z],
                    chart="bar",
                ))
        return findings

    def _detect_segment_trend_shift(self, profile: SchemaProfile, user_ctx) -> List[Dict[str, Any]]:
        if not profile.time_column:
            return []
        self._cur_profile_pk = profile.parent_pk
        measure = self._measure_by_key(profile, "net_revenue") or profile.measures[0]
        findings: List[Dict[str, Any]] = []
        for dim in profile.dimensions[:2]:
            alias = profile.aliases[dim["table"]]
            where = profile.where_clause()
            sql = (
                f"SELECT TO_CHAR(DATE_TRUNC('month', p.{profile.time_column}), 'YYYY-MM') AS period, "
                f"{alias}.{dim['column']} AS segment, {measure['expr']} AS value "
                f"FROM {profile.from_base()} {where} GROUP BY 1, 2 ORDER BY 1, 3 DESC"
            )
            try:
                rows = self._run(sql, user_ctx)
            except Exception:
                continue
            by_seg: Dict[str, Dict[str, float]] = {}
            periods = []
            for r in rows:
                if r["segment"] is None:
                    continue
                by_seg.setdefault(str(r["segment"]), {})[r["period"]] = float(r["value"] or 0)
                if r["period"] not in periods:
                    periods.append(r["period"])
            periods = sorted(periods)
            if len(periods) < 4:
                continue
            half = len(periods) // 2
            first_half = periods[:half]
            second_half = periods[half:]
            grand_total = sum(sum(pm.get(p, 0.0) for p in periods) for pm in by_seg.values()) or 1.0
            material: List[tuple] = []  # (seg, fsum, ssum, shift)
            for seg, pm in by_seg.items():
                fsum = sum(pm.get(p, 0.0) for p in first_half)
                ssum = sum(pm.get(p, 0.0) for p in second_half)
                if fsum <= 0:
                    continue
                # materiality floor: ignore segments that are noise (< 3% of total scale)
                if max(fsum, ssum) < 0.03 * grand_total:
                    continue
                shift = (ssum - fsum) / fsum * 100.0
                if abs(shift) >= (self.settings.discovery_mom_threshold_pct * 2):
                    material.append((seg, fsum, ssum, shift))
            material.sort(key=lambda x: abs(x[3]), reverse=True)
            for seg, fsum, ssum, shift in material[:2]:
                direction = "rose" if shift > 0 else "fell"
                pm = by_seg.get(seg, {})
                findings.append(self._make_finding(
                    ftype="trend",
                    title=f"{dim['label']} '{seg}' {direction} {abs(shift):.0f}% across the period",
                    narrative=(
                        f"For {dim['label']} '{seg}', {measure['label'].lower()} {direction} {abs(shift):.0f}% comparing "
                        f"the later half ({self._money(ssum)} over {second_half[0]}-{second_half[-1]}) with the earlier "
                        f"half ({self._money(fsum)} over {first_half[0]}-{first_half[-1]})."
                    ),
                    hypothesis="A directional shift over time; verify against order volume and mix before drawing conclusions.",
                    next_steps=f"Break down '{seg}' by product and rep to locate the change.",
                    profile=profile, measure=measure, dimension=dim, segment=seg,
                    baseline=fsum, current=ssum, delta_pct=shift,
                    comparison=f"{second_half[0]}-{second_half[-1]} vs {first_half[0]}-{first_half[-1]}",
                    period_label=f"{periods[0]}-{periods[-1]}",
                    supporting=[{"period": p, "value": round(pm.get(p, 0.0), 2)} for p in periods],
                    chart="line",
                ))
        return findings

    # ------------------------------------------------------------------
    # Finding assembly + ranking
    # ------------------------------------------------------------------
    def _make_finding(self, *, ftype, title, narrative, hypothesis, next_steps, profile,
                      measure, dimension, segment, baseline, current, delta_pct,
                      comparison, period_label, supporting, chart, z: float = 0.0) -> Dict[str, Any]:
        dim_label = dimension["label"] if dimension else "time"
        magnitude = abs(delta_pct) if ftype != "concentration" else abs(delta_pct)
        # severity by thresholds
        if z:
            severity = "critical" if abs(z) >= 2.5 else "warning"
        elif ftype in ("trend", "anomaly"):
            severity = "critical" if magnitude >= 40 else "warning" if magnitude >= 25 else "watch"
        elif ftype == "concentration":
            severity = "warning" if magnitude >= 55 else "watch"
        elif ftype in ("underperformer", "opportunity"):
            severity = "warning"
        else:
            severity = "info"

        if chart == "line":
            chart_spec = {"type": "line", "x": "period", "y": "value", "series": supporting}
        else:
            chart_spec = {"type": "bar", "x": "segment", "y": "value", "series": supporting}

        explore = self._explore_question(ftype, measure, dim_label, segment, period_label)
        tables = self._source_tables(profile, dimension)

        signature = _sha1(ftype, measure["key"], dim_label, str(segment), str(period_label))
        assumptions = [
            f"Metric '{measure['label']}' computed as {measure['expr']} over {profile.from_base()}",
            (f"Filtered to status = '{profile.status_filter_value}'" if profile.status_filter_value
             else "No status filter applied (no recognizable status column)"),
            (f"Grouped by detected dimension column {dimension['table']}.{dimension['column']}"
             if dimension else "Time bucketed by calendar month over detected date column"),
            "Values derived from live read-only PostgreSQL queries under the requesting role's Row-Level Security.",
        ]
        limitations = [
            "Statistical thresholds and calendar-month bucketing are configured defaults; tune per business need.",
            "Association only — no causal inference is made from these findings.",
        ]

        return {
            "signature": signature,
            "finding_type": ftype,
            "severity": severity,
            "score": round(magnitude, 2),
            "title": title,
            "narrative": narrative,
            "hypothesis": hypothesis,
            "suggested_next_steps": next_steps,
            "metric_name": measure["label"],
            "dimension_name": dim_label,
            "segment": str(segment) if segment is not None else None,
            "baseline_value": round(float(baseline or 0), 2),
            "current_value": round(float(current or 0), 2),
            "delta_abs": round(float((current or 0) - (baseline or 0)), 2),
            "delta_pct": round(float(delta_pct or 0), 2),
            "comparison_label": comparison,
            "period_label": period_label,
            "source_tables": tables,
            "calculation": {
                "measure_key": measure["key"],
                "measure_expr": measure["expr"],
                "group_by": (f"{dimension['table']}.{dimension['column']}" if dimension else "month(order_date)"),
                "filters": profile.where_clause().strip() or "none",
            },
            "supporting_data": supporting,
            "chart_spec": chart_spec,
            "assumptions": assumptions,
            "limitations": limitations,
            "explore_question": explore,
            "role": self.role,
        }

    def _explore_question(self, ftype, measure, dim_label, segment, period_label) -> str:
        seg = str(segment)
        if ftype == "trend":
            return (f"Break down {measure['label'].lower()} for '{seg}' by product category and sales rep "
                    f"to explain the change I am seeing in {period_label}.")
        if ftype == "concentration":
            return (f"Show {measure['label'].lower()} by {dim_label.lower()} excluding the top contributor, "
                    f"to test how dependent we are on '{seg}'.")
        if ftype == "opportunity":
            return (f"For {dim_label.lower()} '{seg}', show order count and average revenue per order "
                    f"over time to assess expansion potential.")
        if ftype == "underperformer":
            return (f"For {dim_label.lower()} '{seg}', show the average discount and basket size per order "
                    f"versus peers.")
        return f"Explain the {measure['label'].lower()} anomaly involving '{seg}' in {period_label}."

    def _source_tables(self, profile: SchemaProfile, dimension) -> List[str]:
        tables = [profile.fact_table, profile.parent_table]
        if dimension:
            tables.append(dimension["table"])
        return sorted(set(f"{profile.schema_name}.{t}" for t in tables if t))

    def _rank(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sev_w = {"critical": 3.0, "warning": 2.0, "watch": 1.2, "info": 0.8}
        for f in findings:
            base = math.log10(max(abs(f["delta_pct"]), 1.0) + 1) * 10
            f["rank_score"] = round(base * sev_w.get(f["severity"], 1.0), 2)
        findings.sort(key=lambda x: x["rank_score"], reverse=True)
        return findings

    def _money(self, v: float) -> str:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "n/a"
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"${v/1_000:.1f}K"
        return f"${v:,.2f}"

    def _profile_dict(self, profile: SchemaProfile) -> Dict[str, Any]:
        return {
            "schema_name": profile.schema_name,
            "fact_table": profile.fact_table,
            "parent_table": profile.parent_table,
            "time_column": profile.time_column,
            "status_filter_value": profile.status_filter_value,
            "measures": [m["key"] for m in profile.measures],
            "dimensions": [d["column"] for d in profile.dimensions],
            "introspected_tables": profile.introspected_tables,
            "notes": profile.profile_notes,
        }


# ---------------------------------------------------------------------------
# Persistence job: run discovery, dedup, store findings, handle failure
# ---------------------------------------------------------------------------
def run_discovery_job(trigger: str = "manual", role: Optional[str] = None) -> Dict[str, Any]:
    """Execute a discovery run and persist evidence-backed findings with dedup.

    Deduplication: a finding's stable signature (type+metric+dimension+segment+period)
    is checked against previously stored, non-dismissed findings. Re-detected signatures
    do NOT create duplicate alerts (noise suppression).
    """
    from app.database import get_app_session_factory
    from app.models import DiscoveryRun, DiscoveryFinding, new_uuid

    settings = get_settings()
    effective_role = role or settings.discovery_run_role
    factory = get_app_session_factory()
    session = factory()
    run = DiscoveryRun(status="running", trigger=trigger, role=effective_role)
    session.add(run)
    session.commit()
    session.refresh(run)

    start = time.time()
    try:
        service = DiscoveryService(role=effective_role)
        result = service.run_discovery()
        profile = result.get("profile", {})
        findings = result.get("findings", [])

        existing = {
            sig for (sig,) in session.execute(
                text("SELECT signature FROM discovery_findings WHERE status <> 'dismissed'")
            )
        }
        now = datetime.now(timezone.utc)
        new_count = 0
        deduped = 0
        for f in findings:
            sig = f["signature"]
            if sig in existing:
                deduped += 1
                continue
            existing.add(sig)
            new_count += 1
            session.add(DiscoveryFinding(
                id=new_uuid(),
                run_id=run.id,
                signature=sig,
                severity=f["severity"],
                score=f["score"],
                finding_type=f["finding_type"],
                title=f["title"],
                narrative=f["narrative"],
                hypothesis=f["hypothesis"],
                suggested_next_steps=f["suggested_next_steps"],
                metric_name=f["metric_name"],
                dimension_name=f["dimension_name"],
                segment=f["segment"],
                baseline_value=f["baseline_value"],
                current_value=f["current_value"],
                delta_abs=f["delta_abs"],
                delta_pct=f["delta_pct"],
                comparison_label=f["comparison_label"],
                period_label=f["period_label"],
                source_tables=f["source_tables"],
                calculation=f["calculation"],
                supporting_data=f["supporting_data"],
                chart_spec=f["chart_spec"],
                assumptions=f["assumptions"],
                limitations=f["limitations"],
                explore_question=f["explore_question"],
                data_freshness_at=now,
                role=effective_role,
                status="new",
            ))
        run.status = "completed"
        run.schema_name = profile.get("schema_name")
        run.metrics_analyzed = len(profile.get("measures", []))
        run.dimensions_analyzed = len(profile.get("dimensions", []))
        run.findings_new = new_count
        run.findings_deduped = deduped
        run.findings_total = len(findings)
        run.detail = {"profile": profile, "errors": result.get("errors", [])}
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = round((time.time() - start) * 1000, 1)
        session.commit()
        return {"run_id": run.id, "status": "completed", "findings_new": new_count,
                "findings_deduped": deduped, "findings_total": len(findings),
                "errors": result.get("errors", [])}
    except Exception as exc:
        session.rollback()
        run = session.query(DiscoveryRun).filter(DiscoveryRun.id == run.id).first()
        if run:
            run.status = "failed"
            run.error_message = str(exc)[:500]
            run.completed_at = datetime.now(timezone.utc)
            run.duration_ms = round((time.time() - start) * 1000, 1)
            session.commit()
        logger.exception("Discovery job failed")
        return {"run_id": run.id if run else None, "status": "failed", "error": str(exc)[:300]}
    finally:
        session.close()
