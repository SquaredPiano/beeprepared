"""
Test only video and markdown sources.
"""

import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from backend.job_runner import JobRunner

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TEST_PROJECT_ID = "00000000-0000-0000-0000-000000000001"

TEST_FILES = {
    "video": {
        "source_type": "video",
        "source_ref": "/Users/vishnu/Movies/CYC Video.mp4",
        "original_name": "CYC Video.mp4"
    },
    "md": {
        "source_type": "md",
        "source_ref": "/Users/vishnu/Documents/Lumen/lumen/BACKEND_IMPLEMENTATION_PLAN.md",
        "original_name": "BACKEND_IMPLEMENTATION_PLAN.md"
    }
}


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


async def test_source(runner, supabase, source_name: str, payload: dict):
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing: {source_name}")
    logger.info(f"{'='*60}")
    
    if not os.path.exists(payload["source_ref"]):
        logger.warning(f"⏭️ SKIP: File not found: {payload['source_ref']}")
        return None
    
    try:
        response = supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "ingest",
            "status": "pending",
            "payload": payload,
        }).execute()
        
        job_id = response.data[0]["id"]
        logger.info(f"Created job: {job_id}")
    except Exception as e:
        logger.error(f"❌ FAIL: Could not create job: {e}")
        return False
    
    db = runner.db
    job = db.claim_job()
    
    if not job or str(job.id) != job_id:
        logger.error(f"❌ FAIL: Could not claim job")
        return False
    
    try:
        handler = runner.handlers.get(job.type)
        bundle = await handler.run(job)
        db.commit_bundle(bundle)
        
        core_id = bundle.result.get("core_artifact_id")
        if not core_id:
            logger.error(f"❌ FAIL: No knowledge_core artifact created")
            return False
        
        logger.info(f"✅ PASS: {source_name} → knowledge_core")
        logger.info(f"   Source ID: {bundle.result.get('source_artifact_id')}")
        logger.info(f"   Core ID: {core_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ FAIL: {source_name} - {e}")
        import traceback
        traceback.print_exc()
        db.fail_job(job.id, str(e))
        return False


async def main():
    logger.info("=" * 60)
    logger.info("TESTING VIDEO + MD ONLY")
    logger.info("=" * 60)
    
    supabase = get_supabase()
    runner = JobRunner()
    
    results = {}
    
    for source_name, payload in TEST_FILES.items():
        result = await test_source(runner, supabase, source_name, payload)
        results[source_name] = result
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for source, result in results.items():
        if result is True:
            print(f"✅ {source}: PASS")
        elif result is False:
            print(f"❌ {source}: FAIL")
        else:
            print(f"⏭️ {source}: SKIPPED")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
