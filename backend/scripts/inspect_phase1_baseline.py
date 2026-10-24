import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_default_target_engine
from sqlalchemy import text

def main():
    engine = get_default_target_engine()
    with engine.connect() as conn:
        tables = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'sales' ORDER BY table_name")).fetchall()
        print("Target Database Tables in sales schema:")
        for t in tables:
            tname = t[0]
            cnt = conn.execute(text(f'SELECT count(*) FROM sales."{tname}"')).scalar()
            cols = conn.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'sales' AND table_name = '{tname}' ORDER BY ordinal_position")).fetchall()
            col_str = ", ".join([f"{c[0]} ({c[1]})" for c in cols])
            print(f"  - {tname} ({cnt} rows): {col_str}")

if __name__ == "__main__":
    main()
