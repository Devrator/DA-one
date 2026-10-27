"""What-If Decision Simulator (Feature 2).

Turns a *real observed baseline* (pulled from the live, role-authorized
PostgreSQL database through the existing restricted executor) into a
deterministic, transparent scenario calculator. A user nudges business
assumptions (order volume, unit price, discount depth, unit cost) and the
outcome is recomputed with explicit arithmetic — never dressed up as a
predictive-AI forecast.

Honesty contract (spec Feature 2 "Accuracy requirements"):
- Observed data, user assumptions and calculated outcomes are stored and
  returned in three clearly separated buckets.
- Every result carries the exact formula, the inputs, units, the source
  metric and a calculation timestamp.
- A lever is only offered when the underlying column actually exists in the
  connected schema; when it does not (e.g. no cost column) the dependent
  output is reported as *unavailable with a reason*, never invented.
- Nothing implies a guaranteed outcome: this is arithmetic on assumptions, not
  a statistical forecast, and that is stated in every response.

The whole engine is schema-adaptive: it reads the fact table, the quantity /
price / discount / cost columns and the measure expression from the same
runtime ``SchemaProfile`` the Discover engine introspects. No 'sales'/'revenue'
/'region' names are hardcoded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.discovery_service import DiscoveryService
from app.services.role_service import resolve_user_context

logger = logging.getLogger("querypilot.scenario")


# ---------------------------------------------------------------------------
# Lever metadata: definition + which schema feature gates its availability.
# ---------------------------------------------------------------------------
LEVER_DEFS = [
    {
        "key": "order_volume_pct",
        "label": "Order / unit volume",
        "unit": "% change",
        "min": -80.0, "max": 200.0, "step": 1.0, "default": 0.0,
        "requires": "qty",
        "help": "Scales the number of units sold up or down.",
    },
    {
        "key": "unit_price_pct",
        "label": "Average unit price",
        "unit": "% change",
        "min": -50.0, "max": 100.0, "step": 0.5, "default": 0.0,
        "requires": "price",
        "help": "Scales the average realized price per unit.",
    },
    {
        "key": "discount_change_points",
        "label": "Discount depth",
        "unit": "percentage points",
        "min": -50.0, "max": 50.0, "step": 1.0, "default": 0.0,
        "requires": "disc",
        "help": "Adds (or removes) discount points on every line.",
    },
    {
        "key": "unit_cost_pct",
        "label": "Unit cost",
        "unit": "% change",
        "min": -50.0, "max": 100.0, "step": 0.5, "default": 0.0,
        "requires": "cost",
        "help": "Scales the per-unit cost of goods used for the margin view.",
    },
]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def compute_scenario(baseline: Dict[str, Any], assumptions: Dict[str, float]) -> Dict[str, Any]:
    """Pure, deterministic scenario math on an observed baseline.

    ``baseline`` keys (all floats / None when the column was unavailable):
      units, gross, net, realized_factor, avg_unit_price, unit_cost, orders

    Returns the calculated baseline, the calculated scenario and the deltas,
    together with the exact formula strings used. No database access, no LLM:
    this is the reproducible arithmetic core the tests assert against.
    """
    units = float(baseline.get("units") or 0.0)
    gross = float(baseline.get("gross") or 0.0)
    net = float(baseline.get("net") or 0.0)
    orders = float(baseline.get("orders") or 0.0)
    realized = float(baseline.get("realized_factor") or 0.0)
    avg_price = float(baseline.get("avg_unit_price") or 0.0)
    unit_cost = baseline.get("unit_cost")
    unit_cost = float(unit_cost) if unit_cost is not None else None

    vol = float(assumptions.get("order_volume_pct", 0.0) or 0.0)
    price = float(assumptions.get("unit_price_pct", 0.0) or 0.0)
    disc_pts = float(assumptions.get("discount_change_points", 0.0) or 0.0)
    cost_pct = float(assumptions.get("unit_cost_pct", 0.0) or 0.0)

    # --- scenario components -------------------------------------------------
    s_units = units * (1.0 + vol / 100.0)
    s_price = avg_price * (1.0 + price / 100.0)
    s_realized = _clamp(realized - disc_pts / 100.0, 0.0, 1.0)
    s_gross = s_units * s_price
    s_net = s_gross * s_realized
    s_orders = orders * (1.0 + vol / 100.0)

    # --- baseline recomputed with the SAME formulas at zero assumptions ------
    b_gross = units * avg_price
    b_net = b_gross * realized
    b_orders = orders

    formulas = {
        "gross": "gross = units * avg_unit_price",
        "net": "net = gross * realized_factor",
        "realized_factor": "realized_factor = (net / gross) = mean(1 - discount_pct/100)",
        "avg_unit_price": "avg_unit_price = gross / units",
        "scenario_units": "scenario_units = units * (1 + order_volume_pct/100)",
        "scenario_price": "scenario_price = avg_unit_price * (1 + unit_price_pct/100)",
        "scenario_realized": "scenario_realized = clamp(realized_factor - discount_change_points/100, 0, 1)",
        "scenario_gross": "scenario_gross = scenario_units * scenario_price",
        "scenario_net": "scenario_net = scenario_gross * scenario_realized",
    }

    def _delta(b_val, s_val):
        d_abs = s_val - b_val
        d_pct = (d_abs / b_val * 100.0) if b_val else 0.0
        return {"baseline": round(b_val, 2), "scenario": round(s_val, 2),
                "delta_abs": round(d_abs, 2), "delta_pct": round(d_pct, 2)}

    metrics_out = {
        "gross_revenue": _delta(b_gross, s_gross),
        "net_revenue": _delta(b_net, s_net),
        "units": _delta(units, s_units),
        "orders": _delta(b_orders, s_orders),
    }

    # --- margin view (only when a real cost column fed the baseline) ---------
    limitations: List[str] = [
        "This is deterministic arithmetic on user-supplied assumptions, not a "
        "statistical forecast. It does not guarantee any outcome.",
        "Levers apply uniformly across the whole baseline period; they do not "
        "model per-segment elasticity or demand constraints.",
    ]
    if unit_cost is not None:
        s_unit_cost = unit_cost * (1.0 + cost_pct / 100.0)
        b_cogs = units * unit_cost
        s_cogs = s_units * s_unit_cost
        b_margin = b_net - b_cogs
        s_margin = s_net - s_cogs
        metrics_out["contribution_margin"] = _delta(b_margin, s_margin)
        formulas["cogs"] = "cogs = units * unit_cost"
        formulas["margin"] = "contribution_margin = net_revenue - cogs"
        formulas["scenario_cogs"] = "scenario_cogs = scenario_units * unit_cost * (1 + unit_cost_pct/100)"
    else:
        metrics_out["contribution_margin"] = None
        limitations.append(
            "No cost column exists in the connected schema, so cost/unit-cost "
            "levers and the margin view are unavailable; nothing was invented."
        )

    return {
        "components": {
            "scenario_units": round(s_units, 4),
            "scenario_price": round(s_price, 4),
            "scenario_realized_factor": round(s_realized, 6),
            "avg_unit_price": round(avg_price, 4),
            "realized_factor": round(realized, 6),
            "unit_cost": (round(unit_cost, 4) if unit_cost is not None else None),
        },
        "metrics": metrics_out,
        "formulas": formulas,
        "limitations": limitations,
    }


class ScenarioService:
    def __init__(self, role: Optional[str] = None, discovery: Optional[DiscoveryService] = None) -> None:
        self.role = role or "executive"
        self.discovery = discovery or DiscoveryService(role=self.role)

    # ------------------------------------------------------------------
    def capabilities(self) -> Dict[str, Any]:
        """Introspect the live schema and report which levers + views are
        actually available, so the UI only renders real controls."""
        user_ctx = resolve_user_context(self.role)
        profile = self.discovery._build_profile(user_ctx)
        return self._capabilities_from_profile(profile)

    def _capabilities_from_profile(self, profile) -> Dict[str, Any]:
        features = {
            "qty": bool(profile.qty_col),
            "price": bool(profile.price_col),
            "disc": bool(profile.disc_col),
            "cost": bool(profile.cost_col),
        }
        can_model_revenue = features["qty"] and features["price"]
        levers = [
            {**d, "available": features.get(d["requires"], False)}
            for d in LEVER_DEFS
        ]
        unavailable_reasons: List[str] = []
        if not can_model_revenue:
            unavailable_reasons.append(
                "The fact table does not expose both a quantity and a price column, "
                "so a revenue baseline cannot be decomposed from real data."
            )
        if not features["cost"]:
            unavailable_reasons.append(
                "No cost column was detected, so the contribution-margin view and the "
                "unit-cost lever are disabled."
            )
        measure = None
        if can_model_revenue:
            measure = next((m for m in profile.measures if m["key"] == "net_revenue"), None) \
                or (profile.measures[0] if profile.measures else None)
        return {
            "can_simulate": can_model_revenue,
            "features": features,
            "levers": levers,
            "unavailable_reasons": unavailable_reasons,
            "schema_name": profile.schema_name,
            "fact_table": profile.fact_table,
            "parent_table": profile.parent_table,
            "time_column": profile.time_column,
            "metric": ({"key": measure["key"], "label": measure["label"], "expr": measure["expr"]}
                       if measure else None),
        }

    # ------------------------------------------------------------------
    def build_baseline(self, period: Optional[str] = None) -> Dict[str, Any]:
        """Pull the observed baseline components from the live database under
        the role's RLS. This is the ONLY place real numbers are read; the
        scenario math downstream is pure arithmetic on these facts."""
        user_ctx = resolve_user_context(self.role)
        profile = self.discovery._build_profile(user_ctx)
        caps = self._capabilities_from_profile(profile)
        if not caps["can_simulate"]:
            return {"ok": False, "capabilities": caps,
                    "reason": "No quantity+price columns available to build a revenue baseline."}

        q, p = profile.qty_col, profile.price_col
        disc = profile.disc_col
        cost = profile.cost_col
        where = profile.where_clause()
        extra = ""
        period_label = "all periods"
        if period and profile.time_column:
            safe = period.replace("'", "''")
            extra = (f" AND TO_CHAR(DATE_TRUNC('month', p.{profile.time_column}), 'YYYY-MM') = '{safe}'")
            period_label = period

        select = [
            f"SUM(f.{q}) AS units",
            f"SUM(f.{q} * f.{p}) AS gross",
            (f"SUM(f.{q} * f.{p} * (1 - COALESCE(f.{disc}, 0) / 100.0)) AS net"
             if disc else f"SUM(f.{q} * f.{p}) AS net"),
            f"COUNT(DISTINCT p.{profile.parent_pk}) AS orders",
        ]
        if cost:
            select.append(f"SUM(f.{q} * f.{cost}) AS cogs")
        sql = f"SELECT {', '.join(select)} FROM {profile.from_base()} {where}{extra}"

        res = self.discovery.executor.execute(sql, user_context=user_ctx)
        if not res.success or not res.rows:
            return {"ok": False, "capabilities": caps, "sql": sql,
                    "reason": (res.error or "Baseline query returned no rows.")[:200]}

        row = res.rows[0]
        units = float(row.get("units") or 0.0)
        gross = float(row.get("gross") or 0.0)
        net = float(row.get("net") or 0.0)
        orders = float(row.get("orders") or 0.0)
        cogs = row.get("cogs")
        unit_cost = (float(cogs) / units) if (cogs is not None and units > 0) else None

        baseline = {
            "units": round(units, 4),
            "gross": round(gross, 2),
            "net": round(net, 2),
            "orders": round(orders, 2),
            "realized_factor": round((net / gross), 6) if gross else 1.0,
            "avg_unit_price": round((gross / units), 4) if units else 0.0,
            "unit_cost": (round(unit_cost, 4) if unit_cost is not None else None),
            "period_label": period_label,
            "source_metric": caps["metric"],
            "source_tables": sorted(set(
                f"{profile.schema_name}.{t}" for t in
                [profile.fact_table, profile.parent_table] if t
            )),
            "columns": {"qty": q, "price": p, "disc": disc, "cost": cost},
            "status_filter": profile.where_clause().strip() or "none",
            "evidence_sql": sql,
            "classification": "observed_actual",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "role": self.role,
        }
        return {"ok": True, "baseline": baseline, "capabilities": caps}

    # ------------------------------------------------------------------
    def simulate(self, baseline: Dict[str, Any], assumptions: Dict[str, float],
                 name: Optional[str] = None) -> Dict[str, Any]:
        """Deterministically compute a scenario from an observed baseline.

        Validates lever values against their declared ranges before computing,
        so invalid assumptions are rejected rather than silently misapplied.
        """
        errors = self._validate(assumptions, baseline)
        if errors:
            return {"ok": False, "errors": errors}
        calc = compute_scenario(baseline, assumptions)
        return {
            "ok": True,
            "name": name or "Scenario",
            "classification": "calculated_scenario",
            "inputs": {"observed_baseline": baseline, "user_assumptions": assumptions},
            "computed_at": datetime.now(timezone.utc).isoformat(),
            **calc,
        }

    def _validate(self, assumptions: Dict[str, float], baseline: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        by_key = {d["key"]: d for d in LEVER_DEFS}
        has_cost = baseline.get("unit_cost") is not None
        for k, raw in (assumptions or {}).items():
            d = by_key.get(k)
            if not d:
                errors.append(f"Unknown assumption lever '{k}'.")
                continue
            if k == "unit_cost_pct" and not has_cost:
                errors.append("unit_cost_pct is not available: no cost metric in the baseline.")
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                errors.append(f"Assumption '{k}' must be a number.")
                continue
            if v < d["min"] or v > d["max"]:
                errors.append(f"Assumption '{k}'={v} is outside the allowed range "
                              f"[{d['min']}, {d['max']}].")
        return errors
