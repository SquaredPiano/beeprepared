import asyncio
import time
from typing import Dict, Any, Type
from uuid import UUID

from backend.models.jobs import JobModel
from backend.models.protocol import JobBundle
from backend.services.db_interface import DBInterface

# --- Abstract Handler Pattern ---

class JobHandler:
    """
    Abstract Base Class for Job Handlers.
    
    ARCHITECTURAL HARD CONSTRAINT:
    Handlers are responsible for:
    1. Fetching the *content* of input artifact IDs (from DB or R2).
    2. Passing content to the pure services (generators.py).
    3. Generating **new UUIDs** for output artifacts.
    4. Creating the **EdgePayload** linking Input ID -> Output ID.
    
    Handlers MUST return a JobBundle. They MUST NOT commit to DB.
    """
    async def run(self, job: JobModel) -> JobBundle:
        raise NotImplementedError("Handlers must implement run()")

# --- Stub Handler (for verification) ---
class StubHandler(JobHandler):
    async def run(self, job: JobModel) -> JobBundle:
        print(f"[StubHandler] Processing {job.id}")
        import uuid
        
        # Fake Artifact
        new_art_id = uuid.uuid4()
        
        from backend.models.protocol import ArtifactPayload
        
        # Create bundle
        bundle = JobBundle(
            job_id=job.id,
            project_id=job.project_id,
            artifacts=[
                ArtifactPayload(
                    id=new_art_id,
                    project_id=job.project_id,
                    type="text",
                    content={"text": "Stubbed Content from backbone"},
                    # storage_url not mandatory in protocol if content is inline JSON
                )
            ],
            edges=[],
            renderings=[],
            result={"status": "success", "handler": "StubHandler"}
        )
        return bundle

# --- Dispatcher ---

class JobRunner:
    def __init__(self):
        self.db = DBInterface()
        self.handlers: Dict[str, Type[JobHandler]] = {
            "ingest": StubHandler(), # Wiring Stub
            # "generate": GenerateHandler(),
            # "render": RenderHandler() 
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
                    print(f"JobRunner: Job {job.id} FAILED during execution: {e}")
                    import traceback
                    traceback.print_exc()
                    self.db.fail_job(job.id, str(e))

            except Exception as loop_e:
                print(f"JobRunner: Critical Loop Error: {loop_e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    runner = JobRunner()
    asyncio.run(runner.run_loop())
