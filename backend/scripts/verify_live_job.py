"""
Live Job Verification: End-to-End Pipeline Test

This script tests the full job pipeline:
1. Insert an ingest job into the DB
2. Run the JobRunner to process it
3. Verify artifacts and edges are created correctly
4. Optionally trigger a generate job

This replaces test_real_youtube.py for testing the wired system.
"""

import asyncio
import os
import sys
import time
import logging
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from backend.job_runner import JobRunner

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_supabase():
    """Get Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE credentials")
    return create_client(url, key)


def get_or_create_project(supabase):
    """
    Get a project ID to use.
    
    NOTE: The projects table may not be deployed to Supabase yet.
    Using a hardcoded UUID that we'll reference across all artifacts.
    """
    # Use a fixed project ID for testing consistency
    project_id = "00000000-0000-0000-0000-000000000001"
    logger.info(f"Using test project: {project_id}")
    return project_id




def create_ingest_job(supabase, project_id: str):
    """Create an ingest job for a YouTube video."""
    
    # Using the same TED-Ed Stoicism video from earlier tests
    job_payload = {
        "source_type": "youtube",
        "source_ref": "https://www.youtube.com/watch?v=R9OCA6UFE-0",
        "original_name": "TED-Ed: The Philosophy of Stoicism"
    }
    
    response = supabase.table("jobs").insert({
        "project_id": project_id,
        "type": "ingest",
        "status": "pending",
        "payload": job_payload,
    }).execute()
    
    if not response.data:
        raise RuntimeError("Failed to create ingest job")
    
    job_id = response.data[0]["id"]
    logger.info(f"Created ingest job: {job_id}")
    return job_id


def wait_for_job_completion(supabase, job_id: str, timeout: int = 300):
    """Poll job status until completion or timeout."""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = supabase.table("jobs").select("*").eq("id", job_id).execute()
        
        if not response.data:
            raise RuntimeError(f"Job {job_id} not found")
        
        job = response.data[0]
        status = job["status"]
        
        logger.info(f"Job {job_id} status: {status}")
        
        if status == "completed":
            logger.info(f"Job completed successfully!")
            return job
        elif status == "failed":
            error = job.get("error_message", "Unknown error")
            raise RuntimeError(f"Job failed: {error}")
        
        time.sleep(5)
    
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


def verify_artifacts(supabase, project_id: str):
    """Verify that artifacts were created correctly."""
    
    # Fetch artifacts
    artifacts_response = supabase.table("artifacts").select("*").eq("project_id", project_id).execute()
    artifacts = artifacts_response.data or []
    
    # Fetch edges
    edges_response = supabase.table("artifact_edges").select("*").eq("project_id", project_id).execute()
    edges = edges_response.data or []
    
    logger.info(f"Found {len(artifacts)} artifacts and {len(edges)} edges")
    
    # Verify counts
    assert len(artifacts) == 2, f"Expected 2 artifacts, got {len(artifacts)}"
    assert len(edges) == 0, f"Expected 0 edges for ingest (Core is root), got {len(edges)}"
    
    # Verify types
    types = {a["type"] for a in artifacts}
    assert "youtube" in types, "Missing source artifact (type=youtube)"
    assert "knowledge_core" in types, "Missing knowledge_core artifact"
    
    # Find knowledge_core
    core_artifact = next(a for a in artifacts if a["type"] == "knowledge_core")
    content = core_artifact.get("content", {})
    
    # Verify kind
    assert content.get("kind") == "core", "knowledge_core artifact missing kind=core"
    
    # Verify core data
    core_data = content.get("core", {})
    assert core_data.get("title"), "Knowledge Core missing title"
    assert core_data.get("concepts"), "Knowledge Core missing concepts"
    
    logger.info("✅ All artifact verifications passed!")
    
    return artifacts, edges


async def run_single_job_cycle(runner: JobRunner):
    """Run the runner for one job cycle only."""
    db = runner.db
    
    # Claim one job
    job = db.claim_job()
    if not job:
        logger.info("No pending jobs found")
        return False
    
    logger.info(f"Processing job: {job.id} (type: {job.type})")
    
    try:
        handler = runner.handlers.get(job.type)
        if not handler:
            raise ValueError(f"No handler for job type: {job.type}")
        
        bundle = await handler.run(job)
        db.commit_bundle(bundle)
        logger.info(f"Job {job.id} completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Job {job.id} failed: {e}")
        import traceback
        traceback.print_exc()
        db.fail_job(job.id, str(e))
        raise


async def main():
    """Main verification flow."""
    logger.info("=" * 60)
    logger.info("LIVE JOB VERIFICATION")
    logger.info("=" * 60)
    
    supabase = get_supabase()
    
    # Step 1: Get or create project
    logger.info("\n--- Step 1: Get or Create Project ---")
    project_id = get_or_create_project(supabase)
    
    # Step 2: Create ingest job
    logger.info("\n--- Step 2: Create Ingest Job ---")
    job_id = create_ingest_job(supabase, project_id)
    
    # Step 3: Run job through runner
    logger.info("\n--- Step 3: Process Job via JobRunner ---")
    runner = JobRunner()
    await run_single_job_cycle(runner)
    
    # Step 4: Verify artifacts
    logger.info("\n--- Step 4: Verify Artifacts in DB ---")
    artifacts, edges = verify_artifacts(supabase, project_id)
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Project ID: {project_id}")
    logger.info(f"Job ID: {job_id}")
    logger.info(f"Artifacts: {len(artifacts)}")
    logger.info(f"Edges: {len(edges)}")
    
    # Print artifact details
    for a in artifacts:
        logger.info(f"  - {a['type']}: {a['id']}")
    
    return project_id, job_id


if __name__ == "__main__":
    asyncio.run(main())
