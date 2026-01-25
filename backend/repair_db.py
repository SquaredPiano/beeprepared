import os
import pg8000.native
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv

# Load explicitly from backend/.env
env_path = "backend/.env"
if os.path.exists(env_path):
    load_dotenv(env_path)

def repair():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL missing")
        return
    
    try:
        p = urlparse(db_url)
        # DECODE the password! urlparse keeps %28, but pg8000 needs the raw chars
        password = unquote(p.password) if p.password else None
        
        print(f"Connecting to {p.hostname} as {p.username}...")
        
        con = pg8000.native.Connection(
            user=p.username,
            password=password,
            host=p.hostname,
            port=p.port or 5432,
            database=p.path.lstrip('/'),
            ssl_context=True
        )
        
        print("🛠️  Repairing Schema & Adding Knowledge Vault...")
        
        # 1. FIX PROJECTS (Persistence)
        con.run("ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS user_id UUID;")
        con.run("ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS canvas_state JSONB DEFAULT '{}'::jsonb;")
        
        # 2. GLOBAL KNOWLEDGE VAULT (File System)
        # Allow artifacts to exist without a project (Global Assets)
        con.run("ALTER TABLE public.artifacts ALTER COLUMN project_id DROP NOT NULL;")
        
        # Add owner to artifacts (for global access)
        con.run("ALTER TABLE public.artifacts ADD COLUMN IF NOT EXISTS user_id UUID;")
        
        # Add folder support
        con.run("ALTER TABLE public.artifacts ADD COLUMN IF NOT EXISTS folder_path TEXT DEFAULT '/';")
        
        # 3. RLS & POLICIES
        con.run("ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;")
        con.run("ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;")
        
        # Create/Update Service Role Bypass
        con.run("""
        DO $$ 
        BEGIN
            -- PROJECTS
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role bypass' AND tablename = 'projects') THEN
                CREATE POLICY "Service role bypass" ON public.projects FOR ALL USING (auth.jwt()->>'role' = 'service_role');
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can CRUD own projects' AND tablename = 'projects') THEN
                CREATE POLICY "Users can CRUD own projects" ON public.projects FOR ALL USING (auth.uid() = user_id);
            END IF;

            -- ARTIFACTS
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role bypass artifacts' AND tablename = 'artifacts') THEN
                CREATE POLICY "Service role bypass artifacts" ON public.artifacts FOR ALL USING (auth.jwt()->>'role' = 'service_role');
            END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can CRUD own artifacts' AND tablename = 'artifacts') THEN
                CREATE POLICY "Users can CRUD own artifacts" ON public.artifacts FOR ALL USING (auth.uid() = user_id);
            END IF;
        END $$;
        """)

        con.close()
        print("🎉 Database repair & upgrade complete!")
    except Exception as e:
        print(f"❌ Repair failed: {e}")
        
        print("🛠️  Repairing public.projects table...")
        
        # 1. Ensure user_id exists
        con.run("ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS user_id UUID;")
        print("✅ Column 'user_id' verified.")

        # 2. Ensure canvas_state exists
        con.run("ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS canvas_state JSONB DEFAULT '{}'::jsonb;")
        print("✅ Column 'canvas_state' verified.")
        
        # 3. Ensure RLS is on
        con.run("ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;")
        print("✅ RLS enabled.")
        
        # 4. Add bypass policy for service role if missing
        con.run("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role bypass' AND tablename = 'projects') THEN
                CREATE POLICY "Service role bypass" ON public.projects FOR ALL USING (auth.jwt()->>'role' = 'service_role');
            END IF;
        END $$;
        """)
        print("✅ Service role bypass policy verified.")

        con.close()
        print("🎉 Database repair complete!")
    except Exception as e:
        print(f"❌ Repair failed: {e}")

if __name__ == "__main__":
    repair()
