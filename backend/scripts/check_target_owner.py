import sys
from sqlalchemy import create_engine, text

def test_user(username, password):
    url = f"postgresql+psycopg://{username}:{password}@localhost:5433/querypilot_target"
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            owner = conn.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname = 'sales' LIMIT 1")).scalar()
            is_super = conn.execute(text("SELECT usesuper FROM pg_user WHERE usename = CURRENT_USER")).scalar()
            print(f"User {username}: SUCCESS (owner={owner}, is_superuser={is_super})")
            return True
    except Exception as e:
        print(f"User {username}: FAILED ({e})")
        return False

if __name__ == "__main__":
    test_user("querypilot", "querypilot_dev")
    test_user("target_readonly", "target_readonly_dev")
    test_user("postgres", "postgres")
