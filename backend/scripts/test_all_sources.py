"""
Test All Input Sources

Tests all 6 ingestion paths with real files to ensure the pipeline works
regardless of input source.

Sources:
1. YouTube
2. Audio (MP3)
3. Video (MP4)
4. PDF
5. PPTX
6. Markdown
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

# Test files - adjust paths as needed
TEST_FILES = {
    "youtube": {
        "source_type": "youtube",
        "source_ref": "https://www.youtube.com/watch?v=R9OCA6UFE-0",
        "original_name": "TED-Ed Stoicism Video"
    },
    "audio": {
        "source_type": "audio",
        "source_ref": "/Users/vishnu/Downloads/Maroon 5 - One More Night (Lyric Video).mp3",
        "original_name": "Maroon 5 - One More Night.mp3"
    },
    "video": {
        "source_type": "video",
        "source_ref": '/Users/vishnu/Movies/CYC Video.mp4',
        "original_name": "CYC Video.mp4"
    },
    "pdf": {
        "source_type": "pdf",
        "source_ref": "/Users/vishnu/Documents/_CSResumesInspo/Shayan_Syed_Resume.pdf",
        "original_name": "Resume.pdf"
    },
    "pptx": {
        "source_type": "pptx",
        "source_ref": "/Users/vishnu/Documents/Google Takeout/Takeout/Drive/95942_Vishnu_Sai_Aleksandar_Srnec_1419951_12367456.pptx",
        "original_name": "Presentation.pptx"
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


async def test_source(runner, supabase, source_name: str, payload: dict) -> bool:
    """Test a single source type. Returns True if successful."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing: {source_name}")
    logger.info(f"{'='*60}")
    
    # Check if file exists (for local files)
    if source_name != "youtube":
        if not os.path.exists(payload["source_ref"]):
            logger.warning(f"⏭️ SKIP: File not found: {payload['source_ref']}")
            return None  # Skipped
    
    # Create job
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
    
    # Claim and run
    db = runner.db
    job = db.claim_job()
    
    if not job or str(job.id) != job_id:
        logger.error(f"❌ FAIL: Could not claim job")
        return False
    
    try:
        handler = runner.handlers.get(job.type)
        bundle = await handler.run(job)
        db.commit_bundle(bundle)
        
        # Verify artifacts created
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
    logger.info("ALL INPUT SOURCES TEST")
    logger.info("=" * 60)
    
    supabase = get_supabase()
    runner = JobRunner()
    
    results = {}
    
    # Test each source
    for source_name, payload in TEST_FILES.items():
        result = await test_source(runner, supabase, source_name, payload)
        results[source_name] = result
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = [k for k, v in results.items() if v is True]
    failed = [k for k, v in results.items() if v is False]
    skipped = [k for k, v in results.items() if v is None]
    
    print(f"\n✅ Passed ({len(passed)}):")
    for p in passed:
        print(f"   - {p}")
    
    if failed:
        print(f"\n❌ Failed ({len(failed)}):")
        for f in failed:
            print(f"   - {f}")
    
    if skipped:
        print(f"\n⏭️ Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"   - {s} (file not found)")
    
    print("\n" + "=" * 60)
    if not failed:
        print("🎉 ALL AVAILABLE SOURCES WORK")
    else:
        print(f"⚠️ {len(failed)} SOURCES FAILED - NEEDS ATTENTION")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
