"""
Quick test to verify Supabase connection and schema are working.
"""
import os
import sys
from uuid import uuid4

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

def test_direct_postgres():
    """Test direct PostgreSQL connection via psycopg2."""
    import psycopg2
    
    db_url = os.getenv("DATABASE_URL")
    print(f"\n{'='*50}")
    print("TEST 1: Direct PostgreSQL Connection (psycopg2)")
    print(f"{'='*50}")
    
    if not db_url:
        print("[FAIL] DATABASE_URL not set")
        return False
    
    # Mask password in output
    masked_url = db_url.split('@')[-1] if '@' in db_url else db_url
    print(f"Connecting to: {masked_url}")
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Test query
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        print(f"[OK] Connected! PostgreSQL version: {version[:50]}...")
        
        # Check tables exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('lectures', 'transcripts', 'processing_tasks')
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"[OK] Found tables: {tables}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        return False


def test_supabase_client():
    """Test Supabase Python client."""
    from supabase import create_client, Client
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    print(f"\n{'='*50}")
    print("TEST 2: Supabase Client Connection")
    print(f"{'='*50}")
    
    if not url or not key:
        print("[FAIL] SUPABASE_URL or SUPABASE_KEY not set")
        return False
    
    print(f"Connecting to: {url}")
    
    try:
        supabase: Client = create_client(url, key)
        
        # Test read from lectures table
        result = supabase.table("lectures").select("*").limit(1).execute()
        print(f"[OK] Supabase client connected!")
        print(f"[OK] Lectures table accessible (found {len(result.data)} rows)")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Supabase client error: {e}")
        return False


def test_insert_and_read():
    """Test inserting and reading a test lecture."""
    from supabase import create_client, Client
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    print(f"\n{'='*50}")
    print("TEST 3: Insert & Read Operations")
    print(f"{'='*50}")
    
    try:
        supabase: Client = create_client(url, key)
        
        # Create test lecture
        test_id = str(uuid4())
        test_user_id = str(uuid4())
        
        lecture_data = {
            "id": test_id,
            "user_id": test_user_id,
            "filename": "test_connection.pdf",
            "file_type": "pdf",
            "file_url": "https://example.com/test.pdf",
            "file_size_bytes": 12345,
            "status": "processing"
        }
        
        # Insert
        insert_result = supabase.table("lectures").insert(lecture_data).execute()
        print(f"[OK] Inserted test lecture: {test_id[:8]}...")
        
        # Read back
        read_result = supabase.table("lectures").select("*").eq("id", test_id).single().execute()
        print(f"[OK] Read back: filename={read_result.data['filename']}, status={read_result.data['status']}")
        
        # Create associated task
        task_data = {
            "lecture_id": test_id,
            "status": "queued",
            "current_stage": "uploading",
            "progress": 0,
            "bee_worker": "forager"
        }
        
        task_result = supabase.table("processing_tasks").insert(task_data).execute()
        task_id = task_result.data[0]["id"]
        print(f"[OK] Created processing task: {task_id[:8]}...")
        
        # Update task progress
        supabase.table("processing_tasks").update({
            "status": "processing",
            "progress": 50,
            "current_stage": "transcribing",
            "bee_worker": "transcriber"
        }).eq("id", task_id).execute()
        print(f"[OK] Updated task progress to 50%")
        
        # Clean up - delete test data
        supabase.table("processing_tasks").delete().eq("id", task_id).execute()
        supabase.table("lectures").delete().eq("id", test_id).execute()
        print(f"[OK] Cleaned up test data")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] CRUD operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*60)
    print("  BeePrepared - Supabase Connection Test")
    print("="*60)
    
    results = {
        "PostgreSQL Direct": test_direct_postgres(),
        "Supabase Client": test_supabase_client(),
        "CRUD Operations": test_insert_and_read(),
    }
    
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        emoji = "✅" if passed else "❌"
        print(f"{emoji} {test_name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🐝 All tests passed! Database is ready for BeePrepared!")
    else:
        print("⚠️  Some tests failed. Check your .env configuration.")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
