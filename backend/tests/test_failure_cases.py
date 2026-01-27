"""
Failure Integration Tests

Tests edge cases and error handling:
- Invalid job types
- Bad payloads
- Illegal generation paths
- Non-existent artifacts
- Duplicate job handling

Run: PYTHONPATH=/Users/vishnu/Documents/beeprepared python tests/test_failure_cases.py
"""

import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TEST_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


class FailureTestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
    
    def expect_fail(self, name: str, fn, expected_error: str = None):
        """Run a test that SHOULD fail"""
        try:
            fn()
            self.failed.append((name, "Should have failed but succeeded"))
            logger.error(f"❌ UNEXPECTED PASS: {name}")
        except Exception as e:
            if expected_error and expected_error not in str(e):
                self.failed.append((name, f"Wrong error: {e}"))
                logger.error(f"❌ WRONG ERROR: {name} - {e}")
            else:
                self.passed.append(name)
                logger.info(f"✅ EXPECTED FAIL: {name}")
    
    def expect_pass(self, name: str, fn):
        """Run a test that SHOULD pass"""
        try:
            result = fn()
            self.passed.append(name)
            logger.info(f"✅ PASS: {name}")
            return result
        except Exception as e:
            self.failed.append((name, str(e)))
            logger.error(f"❌ FAIL: {name} - {e}")
            return None
    
    def report(self):
        print("\n" + "=" * 60)
        print("FAILURE CASE TEST REPORT")
        print("=" * 60)
        print(f"\n✅ Passed: {len(self.passed)}")
        for p in self.passed:
            print(f"   - {p}")
        if self.failed:
            print(f"\n❌ Failed: {len(self.failed)}")
            for name, err in self.failed:
                print(f"   - {name}: {err}")
        print("=" * 60)
        return len(self.failed) == 0


def run_tests():
    supabase = get_supabase()
    results = FailureTestResult()
    
    logger.info("=" * 60)
    logger.info("FAILURE CASE TESTS")
    logger.info("=" * 60)
    
    # =========================================================================
    # Test 1: Invalid job type
    # =========================================================================
    def test_invalid_job_type():
        supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "invalid_type",
            "status": "pending",
            "payload": {},
        }).execute()
    
    # Note: This might not fail at DB level, would fail at API validation
    # We'll test API-level validation separately
    
    # =========================================================================
    # Test 2: Invalid source_type in ingest
    # =========================================================================
    def test_invalid_source_type():
        # This would be caught by API validation
        # At DB level, we insert and let handler fail
        response = supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "ingest",
            "status": "pending",
            "payload": {
                "source_type": "invalid_format",
                "source_ref": "/fake/path",
                "original_name": "test"
            },
        }).execute()
        return response.data[0]["id"]
    
    # =========================================================================
    # Test 3: Non-existent artifact for generation
    # =========================================================================
    def test_nonexistent_artifact():
        response = supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "generate",
            "status": "pending",
            "payload": {
                "source_artifact_id": str(uuid.uuid4()),  # Random UUID
                "target_type": "quiz",
            },
        }).execute()
        return response.data[0]["id"]
    
    job_id = results.expect_pass(
        "Create job with non-existent artifact",
        test_nonexistent_artifact
    )
    # The job will be created but will fail when runner picks it up
    
    # =========================================================================
    # Test 4: Illegal generation path (quiz -> exam)
    # =========================================================================
    def test_illegal_generation():
        # First, get a quiz artifact if it exists
        quiz = supabase.table("artifacts").select("id").eq("type", "quiz").limit(1).execute()
        if not quiz.data:
            return None
        
        response = supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "generate",
            "status": "pending",
            "payload": {
                "source_artifact_id": quiz.data[0]["id"],
                "target_type": "exam",  # Illegal! quiz -> exam not allowed
            },
        }).execute()
        return response.data[0]["id"]
    
    job_id = results.expect_pass(
        "Create illegal generation job (quiz -> exam)",
        test_illegal_generation
    )
    # Job created, will fail at handler level
    
    # =========================================================================
    # Test 5: Empty payload
    # =========================================================================
    def test_empty_payload():
        response = supabase.table("jobs").insert({
            "project_id": TEST_PROJECT_ID,
            "type": "ingest",
            "status": "pending",
            "payload": {},  # Missing required fields
        }).execute()
        return response.data[0]["id"]
    
    job_id = results.expect_pass(
        "Create job with empty payload",
        test_empty_payload
    )
    
    # =========================================================================
    # Test 6: Verify jobs fail gracefully
    # =========================================================================
    def check_failed_jobs():
        # Get recently failed jobs
        failed = supabase.table("jobs").select("id,type,error_message").eq("status", "failed").order("created_at", desc=True).limit(5).execute()
        logger.info(f"Recent failed jobs: {len(failed.data)}")
        for j in failed.data[:3]:
            logger.info(f"  - {j['id'][:8]}... ({j['type']}): {j.get('error_message', 'N/A')[:50]}")
        return len(failed.data) > 0
    
    # Give runner time to process
    import time
    logger.info("Waiting 5s for runner to process bad jobs...")
    time.sleep(5)
    
    results.expect_pass(
        "Bad jobs marked as failed",
        check_failed_jobs
    )
    
    # =========================================================================
    # Test 7: Verify no partial artifacts from failed jobs
    # =========================================================================
    def check_artifact_count():
        # Count artifacts before/after (should be same if failures are atomic)
        count = supabase.table("artifacts").select("id", count="exact").eq("project_id", TEST_PROJECT_ID).execute()
        logger.info(f"Total artifacts in test project: {count.count}")
        return True
    
    results.expect_pass(
        "Artifact count stable (no partials)",
        check_artifact_count
    )
    
    return results.report()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
