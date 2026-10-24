"""Migrate application database tables for Phase 2."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_app_engine, Base
from sqlalchemy import text

def migrate():
    engine = get_app_engine()
    print("Migrating application database...")
    
    # 1. Add columns to query_records if missing
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("ALTER TABLE query_records ADD COLUMN IF NOT EXISTS user_role VARCHAR(50) DEFAULT 'executive';"))
            conn.execute(text("ALTER TABLE query_records ADD COLUMN IF NOT EXISTS session_id VARCHAR(100);"))
            print("Columns user_role and session_id added to query_records.")
            
    # 2. Create conversation_sessions table
    Base.metadata.create_all(bind=engine)
    print("Table conversation_sessions verified/created.")
    print("Application DB migration complete!")

if __name__ == "__main__":
    migrate()
