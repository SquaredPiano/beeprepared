import os
import pg8000.native
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load explicitly from backend/.env
env_path = "backend/.env"
print(f"DEBUG: CWD={os.getcwd()}")
if os.path.exists(env_path):
    print(f"DEBUG: Found {env_path}")
    # Read file manually
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
        print(f"DEBUG: File size: {len(content)} bytes")
        print(f"DEBUG: Content peek: {content[:500]!r}")



    load_dotenv(env_path) # Now it should be UTF-8 if fixed

    keys = [k for k in os.environ.keys() if 'DATABASE' in k or 'SUPABASE' in k]
    print(f"DEBUG: Env keys: {keys}")
    db_url_val = os.getenv("DATABASE_URL")
    print(f"DEBUG: DATABASE_URL value: {db_url_val!r}")


else:
    print(f"DEBUG: NOT FOUND {env_path}")
    # Try absolute path
    abs_path = os.path.abspath(env_path)
    print(f"DEBUG: Abs path {abs_path}")



def apply_migration():
    db_url = os.getenv("DATABASE_URL")
    # Adjust path if running from root or scripts dir
    migration_file = "backend/db/migration_001_add_project_canvas_state.sql"
    
    if not os.path.exists(migration_file):
        # Try relative to script if running from backend folder
        migration_file = "db/migration_001_add_project_canvas_state.sql"

    print(f"--- 🛠️ Applying Migration {migration_file} using pg8000 ---")
    
    if not db_url:
        print("[FAIL] DATABASE_URL missing")
        return False

    try:
        # Parse DATABASE_URL
        # postgresql://user:password@host:port/dbname
        p = urlparse(db_url)
        user = p.username
        password = p.password
        host = p.hostname
        port = p.port or 5432
        database = p.path.lstrip('/')
        
        print(f"DEBUG: Parsed Host={host}, Port={port}, User={user}, DB={database}")
        print(f"DEBUG: Password len={len(password) if password else 0}")

        
        # Connect
        con = pg8000.native.Connection(
            user=user, 
            password=password, 
            host=host, 
            port=port, 
            database=database,
            ssl_context=True # Supabase requires SSL usually
        )
        
        with open(migration_file, "r") as f:
            sql = f.read()
        
        # Execute
        # pg8000 native run method
        con.run(sql)
        print("[OK] Migration applied successfully!")
        con.close()
        return True
    except Exception as e:
        print(f"[FAIL] SQL execution failed: {e}")
        return False

if __name__ == "__main__":
    apply_migration()
