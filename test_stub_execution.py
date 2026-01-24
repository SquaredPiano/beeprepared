import os
import uuid
from datetime import datetime
from supabase import create_client

# Manual .env loading
env_path = os.path.join(os.path.dirname(__file__), 'backend', '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                os.environ[key] = val

# Init Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    raise ValueError("Missing SUPABASE credentials in .env")

supabase = create_client(url, key)

async def test_stub_flow():
    print("--- Starting Stub Execution Test ---")
    
    # 1. Create a Project
    project_id = str(uuid.uuid4())
    print(f"Creating Project: {project_id}")
    supabase.table("projects").insert({
        "id": project_id,
        "name": "Stub Test Project",
        "description": "Temporary project for validaton"
    }).execute()
    
    # 2. Create a PENDING Job
    job_id = str(uuid.uuid4())
    print(f"Creating PENDING Job: {job_id}")
    supabase.table("jobs").insert({
        "id": job_id,
        "project_id": project_id,
        "type": "ingest", # Type doesn't matter for stub
        "status": "pending",
        "payload": {"test": "stub_payload"}
    }).execute()
    
    # 3. Import JobRunner (Delayed import to pick up env)
    from backend.services.job_runner import job_runner, JobModel, JobStatus
    
    # 4. Claim Job
    print("Claiming Job...")
    claimed_job = await job_runner.claim_job()
    
    if not claimed_job:
        print("FAILED: No job claimed!")
        return
    
    if str(claimed_job.id) != job_id:
        print(f"FAILED: Claimed wrong job {claimed_job.id} (Expected {job_id})")
        return
        
    print(f"Claimed Job: {claimed_job.id} (Status: {claimed_job.status})")
    
    # 5. Execute Job (Stub)
    print("Executing Job (Stub)...")
    await job_runner.execute_job(claimed_job)
    
    # 6. Verify Outcome in DB
    print("Verifying DB State...")
    
    # Check Job Status
    job_res = supabase.table("jobs").select("*").eq("id", job_id).execute()
    final_job = job_res.data[0]
    print(f"Final Job Status: {final_job['status']}")
    
    if final_job['status'] != 'completed':
        print("FAILED: Job status is not 'completed'")
        print(f"Error: {final_job.get('error_message')}")
        return
        
    # Check Artifacts
    art_res = supabase.table("artifacts").select("*").eq("created_by_job_id", job_id).execute()
    artifacts = art_res.data
    print(f"Created Artifacts: {len(artifacts)}")
    
    if len(artifacts) != 1:
        print("FAILED: Expected exactly 1 artifact from stub")
        return
        
    print(f"Artifact Content: {artifacts[0]['content']}")
    
    # Check Result metadata
    print(f"Job Result: {final_job['result']}")
    
    print("\n--- Test Passed Successfully! ---")
    
    # Cleanup (Optional, but good for hygiene)
    print("Cleaning up Project (Cascades deletes)...")
    supabase.table("projects").delete().eq("id", project_id).execute()

if __name__ == "__main__":
    asyncio.run(test_stub_flow())
