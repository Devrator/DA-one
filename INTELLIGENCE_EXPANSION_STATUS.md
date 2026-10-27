# QueryPilot AI — Intelligence Expansion: Implementation Status

Honest, evidence-backed progress report for the five-feature master prompt.
All five features are now delivered as **working vertical slices**: **Feature 1 +
Feature 3**, **Feature 2**, **Feature 4** and **Feature 5**. Nothing below is
claimed unless it runs.

**Verification baseline:** `cd backend && pytest -q` → **103 passed** (92 prior +
11 new for Feature 5). `cd frontend && npm run build` → **1955 modules, built
clean**. Feature 5 was additionally smoke-tested end-to-end over live HTTP against
two real PostgreSQL sources (see below).

---

## Feature-by-feature status

| # | Feature | Status | Evidence |
| :- | :--- | :--- | :--- |
| 1 | Multi-Thread Investigation Workspace | ✅ **DONE (end-to-end)** | Models, 8 endpoints, `InvestigationView.jsx`, Discover→Investigate wiring, 2 integration tests pass against live DB |
| 3 | Root-Cause Exploration Engine | ✅ **DONE (end-to-end)** | `root_cause_service.py` schema-adaptive decomposition; contributions reconcile & rank; 3 pure-logic tests + live run |
| 2 | What-If Decision Simulator | ✅ **DONE (end-to-end)** | `Scenario` model, deterministic `scenario_service` (observed/assumption/calculated separation, schema-gated levers, explicit formulas), 11 endpoints, `ScenarioSimulatorView.jsx`, Discover→Simulate + Scenario→Investigation wiring, 12 tests pass (8 pure-logic + 4 live-DB) |
| 4 | Personalized Executive Briefings | ✅ **DONE (end-to-end)** | `Briefing` + `BriefingPreference` models; `briefing_service` (role-scoped generation, rank by materiality/severity/novelty/relevance, dismiss/stale/dup/low-value suppression, signature dedup, honest empty state); 6 endpoints + scheduler; `BriefingInboxView.jsx`; 9 tests (6 pure-logic + 3 live-DB) incl. a no-cross-role-leak test |
| 5 | Cross-System Intelligence | ✅ **DONE (end-to-end)** | Provisioned a **second real PostgreSQL source** (`querypilot_inventory`, own schema + `inventory_readonly` role + independent RLS); `CrossSourceMapping` model; `cross_source_service` (independent introspection, candidate-key inference, explicit confirmation gate, bounded application-side join with per-source RLS + lineage); 8 endpoints; `DataSourcesView.jsx`; 11 tests (6 pure-logic + 5 live two-source) incl. a no-cross-region-leak test |

---

## What was built this pass (Features 1 + 3)

### Data model (`backend/app/models.py`, auto-created via `create_all`)
- **`Investigation`** — an investigation opened from a Discover finding (or free-form). Fields: `finding_id`, `title`, `root_question`, `narrative`, `role`, `status`, timestamps.
- **`InvestigationBranch`** — a node in a branching tree. Fields: `parent_branch_id` (self-FK → tree), `session_id` (**its own `ConversationSession`, so branch context is fully independent**), `origin` (`manual`/`root_cause`/`finding`), `contributor_segment`, `status`, `conclusion`.
- **`RootCauseRun`** — a persisted decomposition: metric, dimension, baseline/current periods & totals, `total_change_abs/pct`, `reconciles`, ranked `contributions`, and full `evidence`.

Reuses existing `ConversationSession` + `QueryRecord` — **no duplicate conversation system** (per the prompt).

### Root-cause engine (`backend/app/services/root_cause_service.py`)
- Rebuilds the **runtime-introspected** schema profile via `DiscoveryService` (no hardcoded sales/revenue/region).
- Decomposes the latest-two-period change of the finding's measure across a role-permitted dimension; computes each segment's **measured contribution** and ranks by impact.
- **Honesty enforced:** reports `undetermined` when there is no dimension or <2 periods; only names a "primary contributor" when it explains ≥40% of the change; always labels decomposition as "where", never "why"; records SQL, tables, filters, sample size, limitations, and a fact-vs-hypothesis note.

### API endpoints (`backend/app/main.py`)
- `POST /api/v1/investigations` — open finding (auto-runs root-cause + spawns a branch per top contributor).
- `GET /api/v1/investigations`, `GET /api/v1/investigations/{id}`
- `POST /api/v1/investigations/{id}/branches` — parallel branch (own session).
- `GET /api/v1/investigations/{id}/branches/{bid}/turns` — evidence panel (SQL/rows/chart/explanation).
- `PATCH .../branches/{bid}` — rename / archive-reopen.
- `POST .../branches/{bid}/conclusion` — save conclusion.
- `POST /api/v1/investigations/{id}/compare` — side-by-side branch results.
- `POST /api/v1/root-cause/runs` — standalone decomposition + optional branch spawn.

All branch analysis runs through the **existing `/api/v1/queries` pipeline**, so the
SQLGlot AST policy, read-only role, RLS, timeouts and row limits are fully preserved.

### Frontend
- **`InvestigationView.jsx`** — investigation list, branching tree (root-cause children indented under the root), per-branch chat (asks through `/queries` with the branch's own session), evidence panel with inline bar + SQL + result table, rename/archive/conclusion/add-branch, and a Root-Cause panel showing ranked contributions + reconciliation badge + limitations.
- **Discover integration** — every finding card now has **"Open Investigation"**, which creates the investigation and jumps to the workspace.
- New **Investigations** nav tab; wired in `App.jsx`; reuses the existing design system + dark theme.

### Tests (`backend/tests/test_investigations.py`)
- Pure-logic (always run): contributions **sum to the total change**, rank by impact, percentages ≈ 100%, no-causation language; `undetermined` when no dimension / <2 periods.
- Live-DB (skip gracefully if down): open investigation from a real finding → **each branch has a unique session (independent context)**, add parallel branch, evidence turns, rename/archive, compare, and a real root-cause run that reconciles; 404 handling.

---

## Live-demo sequence (judges)
1. **Discover** tab → Run Discovery (or use existing findings) → open a finding's evidence.
2. Click **Open Investigation** → lands in **Investigations**; note the Root-Cause panel (ranked, reconciling contributors) and auto-spawned branches.
3. In the **Original investigation** branch, ask a follow-up → watch generated SQL + rows + grounded explanation (read-only, role-scoped).
4. Click **+** on a branch to add a **parallel hypothesis**; confirm it has its own context (independent session).
5. **Rename**, **Archive**, save a **Conclusion**; use **Add branch** for a new line of enquiry.
6. Switch persona (profile → Role Matrix) to a Regional Manager and confirm the investigation only surfaces that role's authorized data.

---

## What was built for Feature 5 — Cross-System Intelligence

### Second data source (provisioned, real)
- `backend/scripts/setup_inventory_source.py` creates an **independent PostgreSQL
  database** `querypilot_inventory` with its own `inventory` schema
  (`product_stock`, `suppliers`), a dedicated least-privilege `inventory_readonly`
  role, seeded deterministic data (25 products × 5 regions), and **its own RLS
  policies** (region-scoped). `product_id` / `region_id` intentionally share names
  and types with the sales source so cross-system relationships can be inferred.
- The primary sales source is reused as-is; the inventory source is registered
  automatically at startup into the existing **`Connection` registry**
  (`_ensure_secondary_source()`, idempotent) so admins manage it like any source.

### Data model (`backend/app/models.py`, auto-created via `create_all`)
- **`CrossSourceMapping`** — one column in one source ↔ one column in another, with
  `status` (`candidate`/`confirmed`), `confidence`, `evidence` (why proposed), and
  creator/confirmer. A candidate is **never auto-joined**; only a confirmed mapping
  can drive a join.

### Engine (`backend/app/services/cross_source_service.py`)
- **Independent introspection:** each source gets its own engine + schema catalog,
  filtered by the requesting role's table/column authorization.
- **Candidate inference** (`score_join_candidate`, pure): compatible type category +
  identical names + PK/FK hints produce a 0–1 confidence; anything below 0.9 is
  flagged `requires_confirmation`. Incompatible types are rejected (never guessed).
- **Controlled application-side join** (`appside_join`, pure + `run_join`): each side
  is a bounded read-only SELECT run through the shared `QueryExecutor` under the
  requestor's **own** security context, so **each source's RLS applies
  independently**; results are namespaced `L.`/`R.` and joined in-app. Supports
  inner/left/right/full with row caps.
- **Source-level lineage + limitations:** every result records connections, tables,
  columns, per-source SQL, returned/truncated rows, applied role, and explicit
  limitations. A partial failure aborts the join rather than returning misleading
  partial data.

### API endpoints (`backend/app/main.py`, 8 routes)
- `GET /cross-source/sources`, `GET /cross-source/sources/{id}/catalog`,
  `POST /cross-source/relationships/candidates`, `GET/POST /cross-source/relationships`,
  `POST /cross-source/relationships/{id}/confirm`, `DELETE /cross-source/relationships/{id}`,
  `POST /cross-source/join`. All significant actions are audited.

### Frontend (`DataSourcesView.jsx`, new **Data Sources** nav tab)
- Source cards with independent health + expandable role-filtered catalogs; a
  relationship studio (pick two tables → ranked candidates → **Confirm mapping**);
  confirmed-mapping list; and a join configurator (column chips, join type, run) that
  renders the joined table with `L.`/`R.` lineage and the limitations panel.

### Tests (`backend/tests/test_cross_source.py`, 11)
- Pure-logic: type normalization, candidate scoring (PK/FK auto-joinable, incompatible
  rejected, name-only requires confirmation), application-side join (prefixing, all four
  join types, truncation).
- Live two-source: sources listed independently; catalog respects per-role column authz;
  a **product_id candidate is inferred, must be confirmed, then joined** end-to-end;
  joining an unconfirmed candidate is blocked (400); **per-source RLS prevents a
  regional manager from seeing another region's inventory** (only `region_id = 1`); 404
  handling. Verified live over HTTP: exec join = 125 rows, regional-manager join = 25 rows
  (region 1 only).

### Setup for the second source
```powershell
.\.venv\Scripts\python.exe backend/scripts/setup_inventory_source.py
```
(One-time. It is idempotent, and the backend auto-registers the source into the
Connections registry on next start.)

### Live-demo sequence (Feature 5)
1. **Data Sources** tab → see two healthy sources; expand each to inspect its
   independently-introspected, role-filtered catalog.
2. Under **Discover Relationships**, pick `product_catalog` (sales) and
   `product_stock` (inventory) → **Find candidate relationships** → the `product_id`
   candidate shows 80% and *needs confirm*.
3. **Confirm mapping** → it moves to confirmed relationships.
4. **Configure join** → tick columns, choose a join type, **Run cross-system query** →
   joined rows with `L.`/`R.` lineage + per-source SQL + limitations.
5. Switch persona to **Regional Manager (North)** and re-run → results contain only
   region-1 inventory, proving each source's authorization is applied independently.

---

## Known limitations & security considerations (this pass)
- Dataset is the seeded demo (`init.sql` + `seed_clean.sql` + the inventory setup
  script); the engine runs real queries — point it at production and it analyzes real data.
- Root-cause decomposition is additive for **extensive** measures (sums/counts); it attributes *where* a change occurred, not *why*. Intensities (per-order) are not decomposed.
- Comparison window is latest-two-calendar-months by default (matches the trend detector); other windows may differ.
- Investigation branches execute via the existing pipeline, so they inherit all current security guarantees; no new execution path bypasses the AST policy or RLS.
- **Cross-source joins are application-side over bounded, independently-authorized result
  sets — not a server-side cross-database federated join.** This is deliberate: it keeps
  each source's RLS/least-privilege boundary intact and never copies unrestricted rows
  across systems. Practical consequences: join output is capped by per-source and joined
  row limits (truncation is reported), and only equality joins on a confirmed key are
  supported in this first version. Mappings below 0.9 confidence always require explicit
  human confirmation before any data is combined.
- Connection passwords reuse the existing `Connection` storage (plaintext column with a
  `# TODO: encrypt with Fernet` marker, unchanged from prior phases); credentials are never
  returned by any endpoint — only host/schema/table/column metadata and health are exposed.

---

## What was built for Feature 2 — What-If Decision Simulator

### Data model (`backend/app/models.py`, auto-created via `create_all`)
- **`Scenario`** — persists a `baseline` (observed facts), `assumptions` (user levers) and `results` (calculated scenario + formulas + deltas + `computed_at`), plus metric/period/role/source and a `finding_id` link. Lifecycle `draft`/`saved`.

### Deterministic engine (`backend/app/services/scenario_service.py`)
- **Schema-gated levers:** order volume, unit price, discount points and unit cost are each offered **only if** the introspected fact table actually exposes the matching column (`qty`/`price`/`disc`/`cost`). No column → lever disabled + explicit reason. On the current demo schema cost is absent, so the unit-cost lever and the contribution-margin view are honestly reported as unavailable (never invented).
- **Observed baseline:** one read-only, role-authorized aggregate (`SUM(qty)`, `SUM(qty*price)`, discount-adjusted net, distinct orders, optional COGS) through the existing `QueryExecutor`, storing the executed SQL + source tables + filters as evidence.
- **Pure `compute_scenario`:** transparent arithmetic — units, avg price, realized factor → scenario gross/net/units/orders/(margin). At zero assumptions it reproduces the baseline exactly; verified independently (+15% vol, +5% price, +2 disc pts ⇒ **+18.25%** net).
- **Honesty contract:** every response carries `classification` (observed / assumption / calculated), the exact formula strings, units, source metric, `computed_at`, and a standing limitation that this is arithmetic on assumptions, **not a statistical forecast or guarantee**. Invalid / out-of-range / unavailable levers are rejected with clear errors.

### API endpoints (`backend/app/main.py`, 11 routes)
- `GET /api/v1/scenarios/capabilities`, `POST /api/v1/scenarios/baseline`, `POST /api/v1/scenarios/simulate` (live preview), and full save / list / get / rename / duplicate / delete / `compare` / `send-to-investigation`.

### Frontend (`ScenarioSimulatorView.jsx`, new **What-If Simulator** nav tab)
- Data-gated sliders + numeric inputs, live deterministic recalc, baseline-vs-scenario metric cards (net/gross/margin/units) with abs + % deltas, formula + SQL evidence panel, and **Save / Rename / Duplicate / Compare / Delete**.
- **Discover → "Simulate What-If"** opens a scenario seeded from a finding; **"Send to Investigation"** persists the scenario, creates an investigation and links it as a branch — closing the loop between Features 1, 2 and 3.

### Tests (`backend/tests/test_scenarios.py`, 12)
- Pure-logic: zero-assumption reproduction, linear volume scaling, combined price+discount, discount clamped to [0,1], cost lever affects margin only, missing-cost honesty, facts/assumptions/result separation, invalid-assumption rejection.
- Live-DB: capabilities reflect real columns, baseline pulled under role RLS, full save→duplicate→compare→rename→send-to-investigation round trip, 422/404 handling.

---

## What was built for Feature 4 — Personalized Executive Briefings

### Data model (`backend/app/models.py`, auto-created via `create_all`)
- **`Briefing`** — a role-scoped digest: recipient, `recipient_role`, `cadence`, `period_label`, `subject`, `summary`, ranked `items`, `item_count`, `suppressed_count`, `source_data_freshness_at`, lifecycle `status` (generated/empty/delivered/read), `retry_count`, `signature` (dedup) and timestamps.
- **`BriefingPreference`** — per-user `frequency` (daily/weekly/disabled), `enabled_categories`, delivery channel, `last_generated_at`.

### Engine (`backend/app/services/briefing_service.py`)
- **Role-aware by construction:** reads only persisted findings whose `role` equals the recipient's resolved role (themselves produced under that role's RLS); optionally refreshes by running the Discover engine **as that role**. An executive digest is never forwarded to a restricted user — verified live (`sales_rep_carol` → `empty`, not the executive's 8 org-wide items).
- **Ranking** (`score_finding`, pure): severity × materiality(log of |Δ%|) × novelty × category relevance.
- **Suppression** (`build_items`, pure): drops dismissed / stale (default >48h) / duplicate-by-signature / low-value, caps to top-N, records the suppressed count.
- **Dedup + idempotency:** briefing `signature` = recipient + period + finding-signature set; repeats return `deduped`. **Honest empty:** no material findings → `empty` briefing with a clear explanation, never fabricated.

### API + scheduler (`backend/app/main.py`)
- `GET /briefings/inbox`, `GET /briefings/{id}`, `POST /briefings/{id}/status/{read|delivered}`, `GET/PUT /briefings/preferences`, `POST /briefings/generate` (same path the scheduler uses). `_start_briefing_scheduler()` mirrors the Discover scheduler (cadence via config, off by default).

### Frontend (`BriefingInboxView.jsx`, new **Briefings** nav tab)
- Inbox of expandable briefing cards (severity-colored items, deltas, next steps), **Open in Investigation** per finding (reuses the Feature 1 flow), **Generate now**, and a **Preferences** panel (frequency + category toggles). Clear empty state.

### Tests (`backend/tests/test_briefings.py`, 9)
- Pure-logic: ranking (critical/large moves, category relevance), suppression of dismissed/stale/dup/low-value, cap+sort, honest empty text, stable order-independent signature.
- Live-DB: **role-scoped no-leak** (restricted recipient only gets own-role findings), dedup-on-repeat, preference persistence + inbox + 404/422 handling.

