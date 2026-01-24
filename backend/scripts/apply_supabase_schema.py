import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def apply_schema():
    db_url = os.getenv("DATABASE_URL")
    sql_file = "db/init.sql"
    
    print(f"--- 🛠️ Applying Supabase Schema to {db_url.split('@')[-1] if db_url else 'None'} ---")
    
    if not db_url:
        print("[FAIL] DATABASE_URL missing")
        return False

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        with open(sql_file, "r") as f:
            sql = f.read()
        cur.execute(sql)
        conn.commit()
        cur.close()
        conn.close()
        print("[OK] Schema applied successfully!")
        return True
    except Exception as e:
        print(f"[FAIL] SQL execution failed: {e}")
        return False

if __name__ == "__main__":
    apply_schema()
