# 🚀 QueryPilot AI — Autonomous Data-Analyst Agent
### Production-Grade Hackathon Submission | AI-02 Problem Statement | Manipal University

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev/)
[![LLM](https://img.shields.io/badge/Model-Qwen2.5--Coder--7B-indigo)](https://ollama.com/library/qwen2.5-coder)
[![Tests](https://img.shields.io/badge/Tests-9%2F9%20Passing-emerald)](#automated-testing)

---

## 🌟 Executive Summary

**QueryPilot AI** is an enterprise-grade, autonomous Data-Analyst Agent designed to bridge the gap between plain-English business inquiries and production relational databases. Rather than offering static prototypes or mock data, QueryPilot delivers a fully wired, production-ready system where users can pose complex analytical questions, have them translated into dialect-accurate PostgreSQL queries via a compliant open-weight model (`qwen2.5-coder:7b`), safely execute those queries against a realistic relational schema, and receive:

1. **Grounded Explanations**: Business narratives strictly grounded in the returned data rows—guaranteeing zero fabricated numbers.
2. **Dynamic Visualizations**: Auto-selected and interactive charts (Bar, Line, Area, Donut/Pie) tailored to the result schema.
3. **Interactive Data Tables**: Paginated, sortable, searchable tables with one-click CSV export.
4. **Defense-in-Depth Security**: Multi-tier SQL validation (SQLGlot AST parser, DDL/DML blocking, connection-level read-only mode, and 30-second statement timeouts).
5. **Live Benchmark Suite**: Built-in runner evaluating 31 curated real-world scenarios across joins, aggregations, window functions, and security injection attacks.

---

## 🏛️ System Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │               User Interface                 │
                    │   React 18 + Vite + Cyber-Dark Custom CSS    │
                    │ (Prompt Bar, Visualizations, Schema, Audit)  │
                    └──────────────────────┬───────────────────────┘
                                           │ HTTP / JSON
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │             FastAPI Backend (8001)           │
                    │   Orchestration • Middleware • Audit Logging │
                    └──────┬───────────────┬────────────────┬──────┘
                           │               │                │
            1. Schema Disc │               │ 2. NL-to-SQL   │ 3. Explanation
                           ▼               ▼                ▼
            ┌──────────────────┐  ┌────────────────┐  ┌──────────────┐
            │  Schema Service  │  │ Local Ollama   │  │ Explanation  │
            │ Catalog & Types  │  │ Qwen2.5-Coder  │  │ Service      │
            └──────────────────┘  └───────┬────────┘  └──────────────┘
                                          │ Generated SQL
                                          ▼
                               ┌──────────────────────┐
                               │  SQL Policy Engine   │
                               │  SQLGlot AST Parser  │
                               │ • Reject DDL/DML     │
                               │ • Enforce LIMIT 1000 │
                               │ • Block Prohibited fn│
                               └──────────┬───────────┘
                                          │ Verified SQL
                                          ▼
                               ┌──────────────────────┐
                               │ PostgreSQL 16 Target │
                               │ • Least-privilege DB │
                               │ • Read-Only Mode     │
                               │ • 30s Timeout        │
                               └──────────────────────┘
```

---

## 🛡️ Multi-Tier Security & Governance

QueryPilot AI implements a strict **defense-in-depth** model to guarantee that arbitrary user questions or malicious prompt injections never mutate database state or leak unauthorized information:

| Security Layer | Implementation | Protection |
| :--- | :--- | :--- |
| **AST Parser** | SQLGlot syntax tree parsing | Rejects multi-statement injection (`SELECT 1; DROP TABLE...`), syntax malformations, and non-SELECT roots. |
| **Policy Engine** | AST traversal & whitelist | Strictly forbids DDL (`DROP`, `ALTER`, `CREATE`) and DML (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`). Enforces automatic `LIMIT 1000`. |
| **Database Privileges** | PostgreSQL Dedicated Role | Connects as `target_readonly` with exclusively `GRANT SELECT ON ALL TABLES IN SCHEMA sales`. |
| **Connection Defaults** | `default_transaction_read_only=on` | Database-enforced session state prevents any write transaction even if an AST bypass occurred. |
| **DoS Protection** | `statement_timeout=30000` | Aborts long-running runaway queries after 30 seconds. |
| **Audit Logging** | SQLite/PostgreSQL `audit_events` | Immutable chronological trail of query text, AST validation decisions, timestamps, and execution timings. |

---

## 📊 Realistic Benchmark Dataset (Sales Operations)

The target database (`querypilot_target`) is provisioned with a normalized relational schema (`sales`) containing realistic synthetic enterprise data:

- `sales.regions`: Sales territories, codes, regional managers.
- `sales.customers`: B2B accounts, contact details, assigned regions, tiers.
- `sales.product_catalog`: SKUs, product lines, base costs, unit prices.
- `sales.sales_orders`: Orders, statuses (`completed`, `shipped`, `pending`, `cancelled`), timestamps.
- `sales.sales_order_items`: Order line items, quantities, unit prices, discounts applied.
- `sales.returns`: Return transactions, reasons, refund amounts.
- `sales.regional_targets`: Quotas and targets per quarter.

---

## 🚀 Quickstart Guide

### Prerequisites
- **Docker Desktop** (or Docker Engine)
- **Python 3.11+**
- **Node.js 18+** & `npm`
- **Ollama** with `qwen2.5-coder:7b` (`ollama pull qwen2.5-coder:7b`)

### 1. Clone & Start Database
```bash
# Clone the repository
git clone https://github.com/your-org/querypilot-ai.git
cd querypilot-ai

# Start PostgreSQL 16 via Docker (runs on port 5433)
docker compose up -d postgres
```

### 2. Configure & Start Backend
```bash
# Set up virtual environment
python -m venv .venv
.\.venv\Scripts\activate      # On Windows
# source .venv/bin/activate    # On Linux/macOS

# Install dependencies
pip install -r backend/requirements.txt
pip install pytest pytest-asyncio

# Start the FastAPI server (runs on port 8001)
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Start Frontend
```bash
# In a new terminal:
cd frontend
npm install
npm run dev
```
Open **[http://localhost:5173](http://localhost:5173)** in your browser to access the workspace.

---

## 🧪 Automated Testing

The backend includes a comprehensive `pytest` suite validating the core AST safety engine, chart selection heuristics, and grounded explanations:

```bash
cd backend
pytest -v
```

**Results:**
```
tests/test_services.py::test_chart_recommendation_bar PASSED             [ 11%]
tests/test_services.py::test_chart_recommendation_line_time_series PASSED [ 22%]
tests/test_services.py::test_grounded_explanation_fallback PASSED        [ 33%]
tests/test_sql_safety.py::test_valid_select_queries_pass PASSED          [ 44%]
tests/test_sql_safety.py::test_reject_drop_table PASSED                  [ 55%]
tests/test_sql_safety.py::test_reject_delete_and_update PASSED           [ 66%]
tests/test_sql_safety.py::test_reject_sql_injection_multi_statement PASSED [ 77%]
tests/test_sql_safety.py::test_enforce_limit_clause PASSED               [ 88%]
tests/test_sql_safety.py::test_query_length_limit PASSED                 [100%]

============================== 9 passed in 0.66s ==============================
```

---

## 🌐 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/health` | Service liveness probe. |
| `GET` | `/api/v1/readiness` | Checks target DB and local Ollama model availability. |
| `POST` | `/api/v1/queries` | Orchestrates NL-to-SQL generation, safety checks, execution, and grounded explanation. |
| `GET` | `/api/v1/queries/{id}` | Fetches detailed execution record and results. |
| `GET` | `/api/v1/connections/default/schema` | Discovers schemas, tables, columns, row counts, and keys. |
| `POST` | `/api/v1/evaluations/run` | Executes the 31-case benchmark suite and records real accuracy metrics. |
| `GET` | `/api/v1/evaluations` | Returns history of evaluation runs. |
| `GET` | `/api/v1/audit` | Retrieves security and query execution audit trail. |

---

## 📂 Repository Layout

```
agent_db/
├── backend/
│   ├── app/
│   │   ├── config.py              # Environment configuration & settings
│   │   ├── database.py            # Dual engine management (app DB & target DB)
│   │   ├── main.py                # FastAPI routes & lifecycle middleware
│   │   ├── models.py              # SQLAlchemy persistence models
│   │   ├── schemas.py             # Pydantic input/output schemas
│   │   └── services/
│   │       ├── chart_service.py   # Heuristic-based dynamic chart selector
│   │       ├── evaluation_runner.py# 31-case empirical evaluation harness
│   │       ├── explanation_service.py # Grounded business explanation generator
│   │       ├── llm_provider.py    # Robust HTTP client for local Ollama inference
│   │       ├── query_executor.py  # Restricted query executor with timeout guards
│   │       ├── schema_service.py  # Introspection & LLM context formatting
│   │       └── sql_safety.py      # SQLGlot AST parser & security policy engine
│   ├── requirements.txt           # Python dependencies
│   └── tests/                     # Automated pytest suite
├── database/
│   ├── init.sql                   # Database & role bootstrap
│   └── seed_clean.sql             # Relational sales schema & deterministic seed
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── AuditLog.jsx       # Security audit log viewer
│   │   │   ├── BenchmarkRunner.jsx# Live 31-case evaluation dashboard
│   │   │   ├── ChartWidget.jsx    # Interactive Bar, Line, and Donut visualizations
│   │   │   ├── DataTable.jsx      # Sortable, searchable table with CSV export
│   │   │   ├── SchemaBrowser.jsx  # Interactive schema catalog with table preview
│   │   │   └── SqlViewer.jsx      # Syntax-styled SQL display with safety badges
│   │   ├── App.jsx                # Main workspace application shell
│   │   ├── index.css              # Cyber-dark design system & styling
│   │   └── main.jsx               # React DOM entrypoint
│   ├── index.html                 # HTML template with Google Fonts
│   ├── package.json               # Node.js dependencies
│   └── vite.config.js             # Vite configuration with proxy to port 8001
├── docker-compose.yml             # PostgreSQL 16 container definition
└── README.md                      # Comprehensive project documentation
```

---

## 🏆 Evaluation Benchmark Highlights

The built-in evaluation suite (`/api/v1/evaluations/run`) tests 31 scenarios covering:
- **Simple Selects & Filters**: Single-table queries with conditional clauses.
- **Aggregations & Group By**: Multi-level rollups, sums, averages, and group by filters.
- **Multi-Table Joins**: Joins across 3 to 4 tables (regions, customers, orders, items).
- **Ranking & Analytics**: Window functions, `ORDER BY ... LIMIT`, top-N analyses.
- **Adversarial & Safety Rejection**: Injection attacks (`DROP TABLE`, `DELETE`, `pg_sleep`, stacked queries) are 100% intercepted and rejected by the AST policy engine.
- **Ambiguity & Clarification**: Detection of underspecified queries requiring clarification.

---

*Engineered with precision for the AI-02 Data-Analyst Agent Hackathon Submission.*
