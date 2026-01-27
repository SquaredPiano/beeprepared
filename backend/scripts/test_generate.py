"""
Quick test: Generate Quiz from Knowledge Core

This exercises the GenerateHandler to complete the backend readiness audit.
"""

import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from backend.job_runner import JobRunner

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


async def main():
    supabase = get_supabase()
    
    # Find the knowledge_core from our last test
    response = supabase.table("artifacts").select("id").eq("type", "knowledge_core").limit(1).execute()
    
    if not response.data:
        logger.error("No knowledge_core found. Run verify_live_job.py first.")
        return
    
    core_id = response.data[0]["id"]
    logger.info(f"Found knowledge_core: {core_id}")
    
    # Create generate job
    PROJECT_ID = "00000000-0000-0000-0000-000000000001"
    
    job_response = supabase.table("jobs").insert({
        "project_id": PROJECT_ID,
        "type": "generate",
        "status": "pending",
        "payload": {
            "source_artifact_id": core_id,
            "target_type": "quiz"
        }
    }).execute()
    
    job_id = job_response.data[0]["id"]
    logger.info(f"Created generate job: {job_id}")
    
    # Run job through runner
    runner = JobRunner()
    db = runner.db
    
    job = db.claim_job()
    if not job:
        logger.error("No job to claim")
        return
    
    logger.info(f"Processing: {job.id} (type: {job.type})")
    
    try:
        handler = runner.handlers.get(job.type)
        bundle = await handler.run(job)
        db.commit_bundle(bundle)
        logger.info("✅ Generate job completed successfully!")
        logger.info(f"Created artifact: {bundle.result.get('artifact_id')}")
        logger.info(f"Artifact type: {bundle.result.get('artifact_type')}")
    except Exception as e:
        logger.error(f"❌ Generate job failed: {e}")
        import traceback
        traceback.print_exc()
        db.fail_job(job.id, str(e))


if __name__ == "__main__":
    asyncio.run(main())
