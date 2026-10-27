# SAP S/4HANA Enterprise Connector — Architecture, Admin Guide & Verification Report

> **Scope**: Read-only integration of SAP S/4HANA (Public Cloud, Private Cloud, on-premise,
> hybrid) into QueryPilot AI via **released OData APIs (V2 and V4)**. The connector extends the
> existing architecture — it does not replace the SQL engine, the role model, or the audit trail.
> **Nothing about SAP data is ever mocked, sampled, or invented.**

---

## 1. Architecture & Request Flow

### 1.1 Where the connector lives

```
Natural-language question
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ Existing NL→SQL pipeline (LLM + SQLGlot AST policy + QueryExecutor)
│   — unchanged; SQLGlot remains exclusively for SQL sources.
│   — SAP connections are explicitly rejected by POST /api/v1/queries.
└─────────────────────────────────────────────────────────────────┘

Cross-source intelligence (SAP as a selectable source)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ cross_source_service                                          │
│   ├─ source catalog: SAP entity sets appear under label "sap" │
│   ├─ role authorization (role_service) — per table + column   │
│   ├─ bounded fetch via connector (never SQL, never raw URLs)  │
│   └─ app-side join over independently-authorized subsets      │
└─────────────────────────────────────────────────────────────────┘
        │  structured plan: {entity, select[], filter{}, orderby, top}
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ SAP connector policy boundary (NOT SQLGlot)                   │
│   connectors/sap_s4hana/policy.py                             │
│   ├─ entity & fields must exist in discovered $metadata       │
│   ├─ operators restricted to eq/ne/gt/ge/lt/le + string ops   │
│   ├─ role authz (prohibited entity sets / restricted columns) │
│   ├─ binary/stream properties excluded; top clamped           │
│   └─ typed literal encoding — quote-escaped, injection-safe   │
└─────────────────────────────────────────────────────────────────┘
        │  validated OData query params ($select/$filter/$orderby/$top)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ OData client (client.py)                                      │
│   ├─ EVERY URL re-validated vs admin allowlist (fail-closed)  │
│   ├─ redirects never followed (3xx refused and classified)    │
│   ├─ retries only idempotent GETs: 429/502/503/504 + network  │
│   │    exponential backoff + jitter, Retry-After honored      │
│   ├─ response byte cap; bounded pagination via $skiptoken/    │
│   │    @odata.nextLink (continuation URL re-validated,        │
│   │    same-origin enforced, hard page cap of 100)           │
│   └─ error redaction (no secrets/headers ever surface)        │
└─────────────────────────────────────────────────────────────────┘
        │  HTTPS (TLS verify configurable)
        ▼
   SAP S/4HANA OData service  ──  SAP-side authorizations of the read-only
                                   integration user apply IN ADDITION to
                                   every QueryPilot policy above.
```

**Key principle**: the LLM and the browser never emit URLs, SQL, or raw OData
expressions for SAP. They may only produce a *structured request plan*, which is
validated against discovered metadata and role policy **before any HTTP call is made**.

### 1.2 Code map

| Area | Files |
| :--- | :--- |
| Connector abstraction + registry | `backend/app/services/connectors/base.py`, `registry.py`, `net_security.py` |
| SAP connector package | `backend/app/services/connectors/sap_s4hana/` — `metadata.py` (EDMX V2/V4 parser), `odata.py` (query build/parse), `auth.py` (Basic + OAuth2 client-credentials, token cache, redaction), `client.py` (hardened HTTP/OData client), `policy.py` (structured-plan policy boundary), `adapter.py` (SourceConnector implementation) |
| Credential store | `backend/app/services/crypto.py` (Fernet envelope, `fernet:v1:` marker, legacy passthrough, rotation support) |
| Persistence | `backend/app/models.py` (`Connection` — additive SAP columns), `backend/app/schemas.py` (SAP payload/create/patch/preview models) |
| API surface | `backend/app/main.py` — `/api/v1/connections/sap*` endpoints (tags: *SAP Connector*) |
| Cross-source integration | `backend/app/services/cross_source_service.py` (SAP branches, `_fetch_bounded_sap`) |
| Role policy | `backend/app/services/role_service.py` (SAP entity/column restrictions for `regional_manager`, `sales_rep`) |
| Frontend | `frontend/src/components/SapConnectorPanel.jsx` (wizard + management + entity browser), `DataSourcesView.jsx` |
| Tests | `backend/tests/test_sap_connector.py` (protocol + adapter vs local OData fixture server), `backend/tests/test_sap_endpoints.py` (API lifecycle, security, cross-source SAP joins) |

---

## 2. Endpoint Reference (server-side role enforced)

All management endpoints require `X-User-Role: executive` and check it **server-side**
(hiding UI is not a control). Secrets are write-only fields — never returned, never logged.

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/connections/sap/test` | Ad-hoc live connectivity + auth probe. Persists nothing. |
| `POST` | `/api/v1/connections/sap` | Register connection (credential encrypted at rest). |
| `GET` | `/api/v1/connections/{id}/health` | Live health probe; persists lifecycle state. |
| `GET` | `/api/v1/connections/{id}/services` | Advertised OData services (from cache). |
| `POST` | `/api/v1/connections/{id}/schema/refresh` | Live `$metadata` discovery; caches descriptor; reports added/removed/unchanged. |
| `GET` | `/api/v1/connections/{id}/entities` | Entity summaries from cache. |
| `GET` | `/api/v1/connections/{id}/entities/{entity}/metadata` | Full typed property table (no live call). |
| `POST` | `/api/v1/connections/{id}/entities/{entity}/preview` | Bounded, role-authorized preview (structured plan; rate-limited 30/60s per connection; blocked attempts audited). |
| `PATCH` | `/api/v1/connections/{id}` | Update non-secret settings; `secret` field rotates the credential. |
| `POST` | `/api/v1/connections/{id}/disable` | Soft-disable (revokes QueryPilot-side availability; audited). |
| `GET` | `/api/v1/connections/{id}/schema` | Source-neutral schema catalog — serves the cached SAP descriptor for SAP rows. |

Lifecycle states: `configured → connected → degraded → disabled` (plus `test_status`,
`last_tested_at`, `last_success_at`, `metadata_refreshed_at`).

---

## 3. Setup & Administrator Guide

### 3.1 Configuration (`.env`)

```ini
# Credential encryption (required for production; dev key derives from APP_SECRET_KEY otherwise)
CREDENTIAL_ENCRYPTION_KEY=<Fernet key>            # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=<old key>      # only during rotation

# SAP connector
SAP_ENABLED=true
SAP_ALLOWED_HOSTS=tls.prodapi.com,s4pub-sap.sapesrient.com,*erp.internal.test   # FAIL-CLOSED allowlist
SAP_DEFAULT_TIMEOUT_SECONDS=20
SAP_MAX_TIMEOUT_SECONDS=120
SAP_MAX_RECORDS_FETCHED=5000
SAP_DEFAULT_PAGE_SIZE=500
SAP_MAX_RESPONSE_BYTES=8000000
SAP_MAX_RETRIES=3
SAP_BACKOFF_BASE_SECONDS=0.5
SAP_BACKOFF_MAX_SECONDS=20
```

`SAP_ALLOWED_HOSTS` semantics:
- Comma-separated **exact hostnames** or **`*.suffix` wildcards**. Empty allowlist = no external target permitted (fail-closed).
- Cloud-metadata endpoints (`169.254.169.254`, `metadata.google.internal`, …) are **always** blocked, even if allowlisted.
- Private/internal IPs are blocked **unless explicitly allowlisted** — this is the knob for VPN / private-link hybrid topologies.
- Validation runs on: base URL, token URL, and **every continuation (next-link) URL** — never just once at connect time.

### 3.2 Creating a connection (UI wizard)

Data Sources → *SAP S/4HANA Enterprise Connector* → **New SAP connection**:

1. **Deployment & name** — public/private cloud, on-premise, hybrid.
2. **Endpoint & network** — base URL, optional service path, OData version (V2/V4), TLS verification.
3. **Authentication** — Basic (read-only communication user) or OAuth2 client credentials
   (client ID, token URL — must also be allowlisted — optional scope). The secret is
   encrypted (Fernet) immediately on save; set an optional `secret_ref` label for vault/rotation tracking.
4. **Real test, then create** — the wizard performs a live service-document GET and only
   enables *Create & discover* when the test truly succeeds. It then runs `$metadata`
   discovery and reports the real entity-set count. Failures are shown with their category
   (`authentication_error`, `connection_error`, `policy …`, `api_error`) — never papered over.

### 3.3 Day-2 operations (management card)

- **Health** — live probe; updates lifecycle badge + timestamps.
- **Refresh schema** — admin-triggered re-discovery with **change detection**
  (`+added −removed =unchanged`) and audit event; declared-vs-inferred notes preserved.
- **Entities** — browse cached metadata (typed properties, keys, nullable, max length) and
  run **bounded previews as any role** (`executive` / `regional_manager` / `sales_rep`) to
  verify policy behavior; policy-blocked previews surface the real 403 reason.
- **Rotate credential** — PATCH with new secret; old ciphertext is replaced (see §4).
- **Disable** — soft-disable, audited; source disappears from joins.

### 3.4 Role policy for SAP sources

`role_service.py` ships with clearly-labeled **example defaults** (tune per organization):

| Role | SAP restrictions |
| :--- | :--- |
| `executive` | none beyond SAP-side authorizations |
| `regional_manager` | columns `MaterialEntryPrice` (I_PurchaseOrderItem), `EmailAddress`/`PhoneNumber` (I_BusinessPartner) restricted |
| `sales_rep` | above + `SupplierAccountGroupCode`; entity sets `I_PurchaseOrder`, `I_PurchaseOrderItem`, `I_Supplier` prohibited |

These checks run at: catalog listing, candidate discovery, join column selection, preview,
and the connector policy boundary — consistently, on every request.

---

## 4. Credential Security & Rotation

- **At rest**: Fernet envelope (`fernet:v1:` prefix). Legacy plaintext rows from earlier
  builds are transparently accepted and re-encrypted on next write (`reencrypt_if_needed`).
- **In memory**: decrypted only transiently into `ConnectorContext` for one operation.
- **In responses/logs/errors**: never. `secret` is a write-only Pydantic field; error text
  passes through a `redact()` scrubber (authorization/bearer/client_secret/password markers);
  OAuth discovery is excluded from `describe()` output.
- **Rotation**:
  1. Change the credential in SAP (or your vault).
  2. Management card → *Rotate credential* (or `PATCH` with `secret`). Re-encrypted immediately;
     OAuth token cache invalidates on next use. Old values are not retained.
  3. Encryption-key rotation: set the new `CREDENTIAL_ENCRYPTION_KEY` and move the old key to
     `CREDENTIAL_ENCRYPTION_KEY_PREVIOUS` (comma-separated list) so existing ciphertext still
     decrypts and is rewritten under the new key on next update.
- **OAuth2 client-credentials**: tokens cached thread-safely with expiry (60 s safety skew,
  30 s minimum TTL), invalidated and refetched on 401. Token requests themselves are not retried.

---

## 5. Hybrid Network Prerequisites

For on-premise / private-cloud / hybrid deployments:

1. The **QueryPilot backend host** (not the browser) must have outbound HTTPS to the SAP host
   — allow egress accordingly (NSG / firewall / reverse proxy).
2. Private IP targets (RFC1918 / loopback test rigs) require the host to be **explicitly
   allowlisted** in `SAP_ALLOWED_HOSTS`; otherwise hard-blocked by the SSRF guard.
3. VPN / private link: ensure DNS resolution happens on the server network; verify with a
   *Test connection* from the wizard before creating.
4. TLS: keep `tls_verify=on`. Only disable it for gateways using internal CAs you cannot
   install — the UI and audit trail record this state per connection.
5. SAP-side: create a **read-only** communication user / service manager (system) user;
   authorize only the analytics API business configurations (e.g. `SalesOrder_Query`) that
   this deployment should expose. SAP authorizations are the outer fence; QueryPilot policy
   is the inner fence — both always apply.

---

## 6. Known Limitations (honest)

- **No cross-system transaction semantics**: SAP and PostgreSQL sides are fetched
  independently at slightly different times — joins reflect *authorized point-sample subsets*,
  not a shared snapshot. Results are labeled as such.
- **Bounded reads**: every fetch is capped (`top` ≤ `SAP_MAX_RECORDS_FETCHED`, page size,
  100-page ceiling, response byte cap). Large entity sets are truncated — explicitly flagged
  (`truncated: true`) rather than silently clipped.
- **App-side joins only**: there is no SAP-side pushdown for the join itself; both sides are
  fetched (authorized + bounded) and combined in the application. Very large join keys on the
  SAP side are impractical by design.
- **OData feature subset**: `$select`, `$filter` (comparison + substring string ops),
  `$orderby` (≤3 fields), `$top`, server-driven pagination. **No `$expand`** (navigation
  properties are surfaced in metadata but not auto-joined), no aggregate (`$apply`) support,
  no key-by-predicate path, no writes of any kind.
- **Type mapping is an approximation** (`Edm.*` → normalized JSON kinds → SQL-ish types for
  cross-source scoring); decimal precision/scale are preserved in metadata but not in join
  type coercion.
- **Auth modes**: Basic and OAuth2 client credentials only (no OIDC authorization-code /
  user-propagation flows; the connector acts as a single technical identity).
- **Metadata cache**: entity browser and cross-source catalog use the cached descriptor;
  schema changes in SAP are invisible until an admin refreshes (change detection reports them).
- Cloud metadata/link-local IPs and redirects are refused — a service that *requires*
  redirect following is not supported.

---

## 7. Live SAP Verification Checklist

Per the project rule, live integration **must not be claimed until each item passes against
a real tenant**. Everything below is implemented and covered by protocol-fixture tests; run
this list when an SAP S/4HANA system is reachable:

- [ ] Add the tenant host to `SAP_ALLOWED_HOSTS`; confirm a non-allowlisted host is refused with
      `SAP target not permitted` (400).
- [ ] Wizard **Test connection** against the real service document (Public Cloud endpoint with
      OAuth2 client credentials; on-prem endpoint with Basic) — record `latency_ms`, entity-set count.
- [ ] `POST /schema/refresh` parses real `$metadata` (V4 *and* V2 tenants if available); confirm
      entity counts, keys, and `source_version` (SAP system id string) match SAP GUI / API Business Hub.
- [ ] Preview `I_SalesOrder` / `I_BusinessPartner` (or the equivalents you authorized): confirm
      `$select`/`$filter`/`$orderby` results match an OData client (e.g. Postman) exactly.
- [ ] Pagination: preview an entity larger than `SAP_DEFAULT_PAGE_SIZE`; confirm continuation links
      are followed, `truncated` behaves, and a forged `nextLink` host is refused.
- [ ] Retry behavior: induce a 429/503 (or gateway blip); confirm bounded retries with backoff and
      no duplicate cost on non-idempotent paths (all reads are GET).
- [ ] Auth failures: wrong secret → `authentication_error` surfaced, secret absent from the response,
      audit event written, connection marked `degraded`.
- [ ] OAuth token lifecycle: token fetched once, reused until near expiry, refetched after 401.
- [ ] Role policy: as `sales_rep`, confirm prohibited entity sets (e.g. `I_Supplier`) and restricted
      columns (e.g. `MaterialEntryPrice`) are refused with a clear 403 — *and* that the SAP user's
      own authorizations independently restrict the same data.
- [ ] Cross-source: create and confirm `product_catalog.product_id ↔ I_Product.ProductID`,
      run a join, and verify SAP-side rows/evidence (`evidence_request`) against a direct OData call.
- [ ] Credential rotation in SAP → wizard rotate → health + preview succeed with the new value.
- [ ] Disable connection → disappears from sources/joins; re-enable path (delete row / re-create) documented.

---

## 8. Verification Status — What Has and Has NOT Been Tested

**Verified (automated, `backend/tests`, 150 tests passing — 48 SAP-specific):**
- EDMX V2/V4 parsing against realistic fixture metadata (namespaces, keys, nav props,
  readonly flags, inline counts, Collection/binary types).
- OData query construction and both response envelopes; multi-page continuation merging;
  typed literal rendering incl. quote-escaping (injection-safe by construction).
- SSRF fail-closed allowlist (exact + wildcard), metadata-IP hard block precedence,
  private-IP-only-if-allowlisted, poisoned-continuation refusal, redirect refusal.
- Retry/backoff against a flaky fixture (503 → success), response size cap, error
  classification, secret redaction on error bodies, OAuth token caching/expiry/invalidate.
- Policy boundary: prohibited entity sets, restricted columns per role, undeclared fields,
  unsupported operators, nested-filter limits — all refused **before** any HTTP call.
- Full API lifecycle against a **local OData protocol-fixture server**: test → create →
  refresh → cached schema → entities → metadata → paginated preview → role 403s →
  rotation → disable; SQL endpoint correctly rejects SAP rows.
- Cross-source: SAP appears as a selectable source, role-filtered catalog, candidate
  `product_id ↔ ProductID` (requires confirmation), confirmed app-side join with lineage
  (`evidence_request`, connector type) and honest limitation text.
- Regression: all pre-existing PostgreSQL/SQL-path tests still pass (102 baseline + 48 new).

**NOT verified (honest gaps):**
- ❌ No test has run against a **live SAP S/4HANA tenant** — none was available in this
  environment. The protocol-fixture server emulates OData V2/V4 *wire shapes* (service
  documents, EDMX, envelopes, continuation, 401/403/503/redirect/large payloads) but it is
  **not** SAP, and success here must not be read as live-SAP success. Use §7 to complete that
  verification.
- ❌ Tenant-specific quirks (custom error payloads, session-retry handlers on some gateways,
  `sapesrient`-style auth proxies with intermediate redirects) may require additive tuning.
- ❌ Performance at true enterprise scale (hundreds of thousands of rows, wide entities) is
  unmeasured; bounded-fetch design intentionally caps a single operation, not throughput.
- ❌ The SAP-side example role restrictions (§3.4) are documented defaults — mapping them to a
  real org's authorizations is an administrator task.
