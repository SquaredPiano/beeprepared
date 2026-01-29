import asyncio
import time
from typing import Dict, Any, Type
from uuid import UUID

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle
from backend.services.db_interface import DBInterface

# Import real handlers
from backend.handlers.ingest_handler import IngestHandler
from backend.handlers.generate_handler import GenerateHandler
from backend.handlers.base import JobHandler

# --- Dispatcher ---

class JobRunner:
    def __init__(self):
        self.db = DBInterface()
        # Real handlers registered here
        self.handlers: Dict[str, JobHandler] = {
            "ingest": IngestHandler(),
            "generate": GenerateHandler(),
        }


    async def run_loop(self):
        print("JobRunner: Starting Dispatcher Loop...")
        while True:
            try:
                # 1. Claim
                job = self.db.claim_job()
                
                if not job:
                    # Sleep if no job
                    await asyncio.sleep(2) 
                    continue
                
                print(f"JobRunner: Claimed Job {job.id} (Type: {job.type})")
                
                # 2. Process
                try:
                    handler = self.handlers.get(job.type)
                    if not handler:
                        raise ValueError(f"No handler for job type: {job.type}")
                    
                    # Execute Handler (Pure Logic -> Bundle)
                    # Note: We instantiate or use singleton? 
                    # If handlers are stateless, singleton is fine. 
                    # If using `self.handlers` as map of instances:
                    # await handler.run(job)
                    # Let's assume instances in map for now.
                    if isinstance(handler, JobHandler):
                        bundle = await handler.run(job)
                    else:
                        # If class
                        bundle = await handler().run(job)

                    # 3. Commit
                    self.db.commit_bundle(bundle)
                    print(f"JobRunner: Job {job.id} Committed Successfully.")

                except Exception as e:
                    print(f"JobRunner: Job {job.id} FAILED during execution")
                    print(f"Error Type: {type(e)}")
                    print(f"Error Args: {e.args}")
                    print(f"Error Repr: {repr(e)}")
                    import traceback
                    traceback.print_exc()
                    self.db.fail_job(job.id, str(e))

            except Exception as loop_e:
                print(f"JobRunner: Critical Loop Error: {loop_e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    runner = JobRunner()
    asyncio.run(runner.run_loop())
