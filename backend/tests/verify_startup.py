import sys
import os
import asyncio
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(os.getcwd())

load_dotenv()

try:
    from backend.job_runner import JobRunner
    print("Successfully imported JobRunner")
    
    # Try to instantiate to check DB connection/env vars
    try:
        runner = JobRunner()
        print("Successfully instantiated JobRunner")
    except Exception as e:
        print(f"Failed to instantiate JobRunner: {e}")
        sys.exit(1)

except ImportError as e:
    print(f"Failed to import JobRunner: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error: {e}")
    sys.exit(1)

print("Verification passed.")
