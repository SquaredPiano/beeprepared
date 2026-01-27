import asyncio
import os
import sys
from uuid import UUID

# Add current dir to path
sys.path.append(os.getcwd())

from services.ingestion import get_ingestion_service

# Mock user for testing
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000000")

async def test_real_file_ingestion(filename: str):
    service = get_ingestion_service()
    if not os.path.exists(filename):
        print(f"[FAIL] File {filename} not found")
        return

    print(f"--- 🚀 Starting Ingestion: {filename} ---")
    with open(filename, "rb") as f:
        file_data = f.read()
    
    try:
        lecture = await service.ingest_file(file_data=file_data, filename=filename, user_id=TEST_USER_ID)
        print(f"✅ SUCCESS! Lecture ID: {lecture.id}")
        return lecture
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return None

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    asyncio.run(test_real_file_ingestion(target))
