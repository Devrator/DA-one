"""Provision the SECOND authorized PostgreSQL source for Feature 5.

Creates an independent analytics database `querypilot_inventory` with an
`inventory` schema, a dedicated least-privilege read-only role
(`inventory_readonly`), real seeded data, and its OWN Row-Level Security
policies so each source's authorization is applied independently.

The `product_id` and `region_id` columns intentionally share names and types
with the sales source so cross-source relationship candidates can be inferred.

Run:  .\\.venv\\Scripts\\python.exe backend/scripts/setup_inventory_source.py
"""
from __future__ import annotations

from sqlalchemy import create_engine, text

MAINT_URL = "postgresql+psycopg://querypilot:querypilot_dev@localhost:5433/postgres"
INV_URL = "postgresql+psycopg://querypilot:querypilot_dev@localhost:5433/querypilot_inventory"

INV_USER = "inventory_readonly"
INV_PASSWORD = "inventory_readonly_dev"


def _create_database_if_missing() -> None:
    # CREATE DATABASE cannot run inside a transaction block → AUTOCOMMIT.
    engine = create_engine(MAINT_URL, isolation_level="AUTOCOMMIT", future=True)
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'querypilot_inventory'")
        ).fetchone()
        if not exists:
            conn.execute(text("CREATE DATABASE querypilot_inventory"))
            print("Created database querypilot_inventory")
        else:
            print("Database querypilot_inventory already exists")
    engine.dispose()


def _create_role_if_missing() -> None:
    engine = create_engine(MAINT_URL, isolation_level="AUTOCOMMIT", future=True)
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": INV_USER}
        ).fetchone()
        if not exists:
            conn.execute(
                text(f"CREATE ROLE {INV_USER} WITH LOGIN PASSWORD '{INV_PASSWORD}'")
            )
            print(f"Created role {INV_USER}")
        else:
            print(f"Role {INV_USER} already exists")
        conn.execute(
            text(f"GRANT CONNECT ON DATABASE querypilot_inventory TO {INV_USER}")
        )
    engine.dispose()


def _create_schema_and_tables() -> None:
    engine = create_engine(INV_URL, future=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS inventory"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory.product_stock (
                stock_id         SERIAL PRIMARY KEY,
                product_id       INTEGER NOT NULL,
                warehouse_code   VARCHAR(50) NOT NULL,
                region_id        INTEGER NOT NULL,
                units_on_hand    INTEGER NOT NULL CHECK (units_on_hand >= 0),
                reorder_point    INTEGER NOT NULL CHECK (reorder_point >= 0),
                last_restocked_at DATE
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory.suppliers (
                supplier_id      SERIAL PRIMARY KEY,
                product_id       INTEGER NOT NULL,
                supplier_name    VARCHAR(150) NOT NULL,
                lead_time_days   INTEGER NOT NULL CHECK (lead_time_days >= 0),
                region_id        INTEGER NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_product_stock_product "
            "ON inventory.product_stock(product_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_product_stock_region "
            "ON inventory.product_stock(region_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_suppliers_product "
            "ON inventory.suppliers(product_id)"
        ))
        conn.commit()
    engine.dispose()
    print("inventory schema + tables ready")


def _seed_if_empty() -> None:
    engine = create_engine(INV_URL, future=True)
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM inventory.product_stock")
        ).scalar() or 0
        if count > 0:
            print(f"product_stock already seeded ({count} rows); skipping")
            engine.dispose()
            return

        warehouses = ["WH-N", "WH-S", "WH-E", "WH-W", "WH-C"]
        # Deterministic stock rows for product_id 1..25 across 5 regions.
        for product_id in range(1, 26):
            for region_id in range(1, 6):
                seed = (product_id * 7 + region_id * 13) % 20
                units_on_hand = 40 + seed * 15
                reorder_point = 30 + (seed % 5) * 8
                conn.execute(
                    text(
                        "INSERT INTO inventory.product_stock "
                        "(product_id, warehouse_code, region_id, units_on_hand, "
                        "reorder_point, last_restocked_at) VALUES "
                        "(:pid, :wh, :rid, :uoh, :rop, "
                        "DATE '2026-01-05' + (:lag * INTERVAL '1 day'))"
                    ),
                    {
                        "pid": product_id,
                        "wh": warehouses[region_id - 1],
                        "rid": region_id,
                        "uoh": units_on_hand,
                        "rop": reorder_point,
                        "lag": (product_id + region_id) % 20,
                    },
                )

        # Suppliers: two per product for a subset, sharing product_id key.
        supplier_names = [
            "Northwind Traders", "Contoso Supply", "Fabrikam Components",
            "Tailspin Logistics", "Adventure Parts", "Globex Wholesale",
        ]
        for product_id in range(1, 26, 2):
            for offset in (0, 1):
                conn.execute(
                    text(
                        "INSERT INTO inventory.suppliers "
                        "(product_id, supplier_name, lead_time_days, region_id) "
                        "VALUES (:pid, :name, :lead, :rid)"
                    ),
                    {
                        "pid": product_id,
                        "name": supplier_names[(product_id + offset) % len(supplier_names)],
                        "lead": 3 + ((product_id + offset) % 18),
                        "rid": 1 + ((product_id + offset) % 5),
                    },
                )
        conn.commit()
    engine.dispose()
    print("inventory seed data written")


def _apply_security() -> None:
    engine = create_engine(INV_URL, future=True)
    with engine.connect() as conn:
        conn.execute(text("GRANT USAGE ON SCHEMA inventory TO inventory_readonly"))
        conn.execute(text(
            "GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO inventory_readonly"
        ))
        conn.execute(text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA inventory "
            "GRANT SELECT ON TABLES TO inventory_readonly"
        ))

        # Independent RLS for this source, keyed on region_id.
        for table in ("product_stock", "suppliers"):
            conn.execute(text(f"ALTER TABLE inventory.{table} ENABLE ROW LEVEL SECURITY;"))
            conn.execute(text(f"ALTER TABLE inventory.{table} FORCE ROW LEVEL SECURITY;"))
            conn.execute(text(f"DROP POLICY IF EXISTS {table}_rls_policy ON inventory.{table};"))
            conn.execute(text(f"""
                CREATE POLICY {table}_rls_policy ON inventory.{table}
                FOR SELECT
                TO inventory_readonly, target_readonly, querypilot
                USING (
                    CURRENT_USER = 'querypilot'
                    OR NULLIF(current_setting('app.user_role', true), '') IS NULL
                    OR current_setting('app.user_role', true) = 'executive'
                    OR (
                        current_setting('app.user_role', true) IN ('regional_manager', 'sales_rep')
                        AND region_id = NULLIF(current_setting('app.region_id', true), '')::integer
                    )
                );
            """))
        conn.commit()
    engine.dispose()
    print("inventory RLS policies applied")


if __name__ == "__main__":
    _create_database_if_missing()
    _create_role_if_missing()
    _create_schema_and_tables()
    _seed_if_empty()
    _apply_security()
    print("Second source (querypilot_inventory / inventory) provisioning complete.")
