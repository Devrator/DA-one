"""Verify PostgreSQL Row-Level Security (RLS) enforcement for target_readonly user."""
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

def test_rls():
    url = "postgresql+psycopg://target_readonly:target_readonly_dev@localhost:5433/querypilot_target"
    engine = create_engine(url)
    
    print("=== Testing Database-Level RLS Enforcement (Role: target_readonly) ===")
    
    with engine.connect() as conn:
        # Test 1: Executive Role (sees all orders)
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_role = 'executive';"))
            exec_orders = conn.execute(text("SELECT count(*) FROM sales.sales_orders;")).scalar()
            exec_targets = conn.execute(text("SELECT count(*) FROM sales.regional_targets;")).scalar()
            print(f"[Executive] Total orders visible: {exec_orders}, Regional targets visible: {exec_targets}")
            assert exec_orders >= 300, f"Executive should see all orders, got {exec_orders}"
            assert exec_targets == 45, f"Executive should see all 45 targets, got {exec_targets}"
        
        # Test 2: Regional Manager (Region 1)
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_role = 'regional_manager';"))
            conn.execute(text("SET LOCAL app.region_id = '1';"))
            rm1_orders = conn.execute(text("SELECT count(*) FROM sales.sales_orders;")).scalar()
            rm1_non_r1 = conn.execute(text("SELECT count(*) FROM sales.sales_orders WHERE region_id != 1;")).scalar()
            rm1_targets = conn.execute(text("SELECT count(*) FROM sales.regional_targets;")).scalar()
            print(f"[Regional Manager R1] Orders visible: {rm1_orders}, Non-region-1 orders visible: {rm1_non_r1}, Targets: {rm1_targets}")
            assert rm1_orders > 0 and rm1_orders < exec_orders, "RM should see subset of orders"
            assert rm1_non_r1 == 0, f"RM Region 1 must NOT see other regions! Leak count: {rm1_non_r1}"
            assert rm1_targets == 9, f"RM Region 1 should see only 9 targets for Region 1, got {rm1_targets}"

        # Test 3: Regional Manager (Region 2)
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_role = 'regional_manager';"))
            conn.execute(text("SET LOCAL app.region_id = '2';"))
            rm2_orders = conn.execute(text("SELECT count(*) FROM sales.sales_orders;")).scalar()
            rm2_r1 = conn.execute(text("SELECT count(*) FROM sales.sales_orders WHERE region_id = 1;")).scalar()
            print(f"[Regional Manager R2] Orders visible: {rm2_orders}, Region-1 orders visible: {rm2_r1}")
            assert rm2_r1 == 0, f"RM Region 2 must NOT see Region 1 orders! Leak count: {rm2_r1}"

        # Test 4: Sales Rep (Carol Chen)
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_role = 'sales_rep';"))
            conn.execute(text("SET LOCAL app.sales_rep = 'Carol Chen';"))
            conn.execute(text("SET LOCAL app.region_id = '1';"))
            rep_orders = conn.execute(text("SELECT count(*) FROM sales.sales_orders;")).scalar()
            rep_other_orders = conn.execute(text("SELECT count(*) FROM sales.sales_orders WHERE sales_rep != 'Carol Chen';")).scalar()
            rep_targets = conn.execute(text("SELECT count(*) FROM sales.regional_targets;")).scalar()
            print(f"[Sales Rep Carol Chen] Orders visible: {rep_orders}, Competitor rep orders visible: {rep_other_orders}, Targets visible: {rep_targets}")
            assert rep_orders > 0 and rep_orders < rm1_orders, "Rep should only see their own orders"
            assert rep_other_orders == 0, f"Rep must NEVER see other reps' orders! Leak count: {rep_other_orders}"
            assert rep_targets == 0, f"Rep must NEVER see management regional targets! Got: {rep_targets}"

        # Test 5: Cross-Tenant Injection Simulation
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_role = 'sales_rep';"))
            conn.execute(text("SET LOCAL app.sales_rep = 'Carol Chen';"))
            # Attacker writes: SELECT * FROM sales.sales_orders WHERE 1=1 OR sales_rep = 'Bob Smith'
            attack_result = conn.execute(text("SELECT count(*) FROM sales.sales_orders WHERE 1=1;")).scalar()
            print(f"[Adversarial Test] Rep Carol Chen running 'WHERE 1=1': returns {attack_result} rows (strictly Carol Chen orders)")
            assert attack_result == rep_orders, "Adversarial WHERE 1=1 must still be constrained by RLS!"

        # Test 6: Pool Isolation Verification
        # When transaction ends, SET LOCAL is automatically discarded!
        with conn.begin():
            # In a fresh transaction without SET LOCAL, check current_setting
            val = conn.execute(text("SELECT current_setting('app.user_role', true);")).scalar()
            print(f"[Pool Isolation] Fresh transaction role setting: '{val}' (cleanly reset, no leak)")
            assert val is None or val == "", "Connection must not retain previous transaction's session variables!"

    print("\n>>> ALL 6 DATABASE-LEVEL RLS TESTS PASSED WITH ZERO LEAKS! <<<")

if __name__ == "__main__":
    test_rls()
