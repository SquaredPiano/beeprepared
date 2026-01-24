import os
import asyncio
import json
from uuid import UUID
from datetime import datetime
from typing import Dict, Any, Optional

from supabase import create_client, Client
from dotenv import load_dotenv

from backend.models.jobs import JobModel, JobType, JobStatus

load_dotenv()

class JobRunner:
    def __init__(self):
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        self.supabase: Client = create_client(url, key)

    async def claim_job(self) -> Optional[JobModel]:
        """
        Atomically claims the next pending job using DB RPC.
        Returns JobModel or None if no jobs pending.
        """
        try:
            # RPC call to 'claim_next_job'
            response = self.supabase.rpc("claim_next_job", {}).execute()
            
            if not response.data:
                return None
                
            # Response is a list with one item if successful
            job_data = response.data[0]
            
            # Map RPC return columns (j_...) to JobModel fields
            # The RPC returns with prefix j_ to avoid ambiguity in PLPGSQL,
            # but usually Supabase maps generic names well. 
            # Let's adjust based on the schema output: 
            # The schema defines returns as j_id, j_project_id...
            
            model_data = {
                "id": job_data['j_id'],
                "project_id": job_data['j_project_id'],
                "type": job_data['j_type'],
                "status": job_data['j_status'],
                "payload": job_data['j_payload'],
                "result": job_data['j_result'] or {},
                "created_at": job_data['j_created_at'],
                "started_at": job_data['j_started_at'],
                "completed_at": job_data['j_completed_at'],
                "error_message": job_data['j_error_message']
            }
            
            return JobModel(**model_data)

        except Exception as e:
            print(f"Error claiming job: {e}")
            return None

    async def update_job_status(self, job_id: UUID, status: JobStatus, result: Dict[str, Any] = None, error: str = None):
        """
        Updates job status, result, and timestamps.
        """
        update_data = {
            "status": status.value,
        }
        
        if status == JobStatus.RUNNING:
            update_data["started_at"] = datetime.now().isoformat()
            
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_data["completed_at"] = datetime.now().isoformat()
            
        if result is not None:
            update_data["result"] = result
            
        if error is not None:
            update_data["error_message"] = error

        self.supabase.table("jobs").update(update_data).eq("id", str(job_id)).execute()

    async def run_pending_jobs(self):
        """
        Polls for pending jobs and executes them.
        (This will be the main loop)
        """
        # Fetch pending jobs
        response = self.supabase.table("jobs").select("*").eq("status", "pending").execute()
        jobs = response.data
        
        for job_data in jobs:
            job = JobModel(**job_data)
            await self.execute_job(job)

    async def execute_job(self, job: JobModel):
        """
        Executes a job by dispatching to the appropriate handler and committing atomically.
        """
        print(f"Starting job {job.id} type={job.type}")
        
        try:
            # --- Dispatcher (Route to Handler) ---
            # Step 1: Stub Handlers (Fake Bundles)
            # This ensures we validate the 'commit_job_bundle' RPC before adding complexity.
            
            bundle = await self._dispatch_job(job)
            
            # --- Atomic Commit ---
            # Call 'commit_job_bundle' RPC with the returned bundle
            
            response = self.supabase.rpc("commit_job_bundle", {
                "_job_id": str(job.id),
                "_project_id": str(job.project_id),
                "_artifacts": bundle['artifacts'],
                "_edges": bundle['edges'],
                "_renderings": bundle['renderings'],
                "_result": bundle['result']
            }).execute()
            
            print(f"Job {job.id} COMPLETED and Committed Atomically.")
            
        except Exception as e:
            # --- Failure Path ---
            print(f"Job {job.id} FAILED: {e}")
            await self.update_job_status(job.id, JobStatus.FAILED, error=str(e))

    async def _dispatch_job(self, job: JobModel) -> Dict[str, Any]:
        """
        Routes the job to the correct handler based on type.
        Returns a 'Commit Bundle' dictionary.
        """
        # For Phase 1 (Stubbing), we route everything to the stub handler.
        # In Phase 2, we will add:
        # if job.type == JobType.INGEST: return await self._handle_ingest(job)
        # elif job.type == JobType.GENERATE: return await self._handle_generate(job)
        
        return await self._handle_stub(job)

    async def _handle_stub(self, job: JobModel) -> Dict[str, Any]:
        """
        STUB HANDLER: Returns a valid but fake commit bundle.
        Used to validate the DB transaction pipeline.
        """
        print(f"STUBBING execution for job {job.id}")
        
        # Simulate work
        await asyncio.sleep(0.5)
        
        # Create a fake artifact
        fake_artifact_id = str(UUID(int=1)) # Just a valid UUID string, or generate one
        # Actually, let's generate a real random UUID so constraints don't fail on uniqueness if run twice
        import uuid
        fake_artifact_id = str(uuid.uuid4())
        
        # Bundle Structure
        return {
            "artifacts": [
                {
                    "id": fake_artifact_id,
                    "project_id": str(job.project_id),
                    "type": "text", # Root type, safe for stub (no parent needed)
                    "content": {"text": "This is a stub artifact."}
                }
            ],
            "edges": [], # No edges for root type
            "renderings": [], # No renderings
            "result": {
                "status": "success", 
                "stubbed": True,
                "msg": "Pipeline validation successful"
            }
        }


# Singleton instance
job_runner = JobRunner()
