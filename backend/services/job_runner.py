import os
import asyncio
import json
from uuid import UUID
from datetime import datetime
from typing import Dict, Any, Optional
import traceback
import logging

from backend.models.jobs import JobModel, JobType, JobStatus
from backend.services.db_interface import DBInterface
from backend.handlers.ingest_handler import IngestHandler
from backend.handlers.generate_handler import GenerateHandler

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class JobRunner:
    def __init__(self):
        self.db = DBInterface()
        self.ingest_handler = IngestHandler()
        self.generate_handler = GenerateHandler()

    async def run_pending_jobs(self):
        """
        Polls for pending jobs and executes them.
        (This will be the main loop)
        """
        logger.info("Checking for pending jobs...")
        
        while True:
            # Claim next job
            try:
                job = self.db.claim_job()
            except Exception as e:
                logger.error(f"Error claiming job: {e}")
                await asyncio.sleep(5)
                continue
                
            if not job:
                # No jobs, wait and poll again
                logger.info("No jobs pending. Sleeping...")
                await asyncio.sleep(2)
                continue
            
            logger.info(f"Claimed Job {job.id} (Type: {job.type})")
            
            # Execute job
            await self.execute_job(job)

    async def execute_job(self, job: JobModel):
        """
        Executes a job by dispatching to the appropriate handler and committing atomically.
        """
        try:
            logger.info(f"Starting execution for Job {job.id}")
            
            # --- Dispatcher (Route to Handler) ---
            bundle = None
            
            if job.type == JobType.INGEST:
                bundle = await self.ingest_handler.run(job)
            elif job.type == JobType.GENERATE:
                bundle = await self.generate_handler.run(job)
            else:
                raise ValueError(f"Unsupported job type: {job.type}")
            
            if not bundle:
                raise RuntimeError("Handler returned no bundle (possibly silent failure)")

            # --- Atomic Commit ---
            logger.info(f"Committing bundle for Job {job.id}...")
            self.db.commit_bundle(bundle)
            logger.info(f"Job {job.id} COMPLETED successfully.")
            
        except Exception as e:
            # --- Failure Path ---
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"Job {job.id} FAILED: {error_msg}")
            
            try:
                self.db.fail_job(job.id, str(e)) # Store just the message, not the stack trace usually
            except Exception as db_err:
                logger.critical(f"Failed to update job status to FAILED: {db_err}")

if __name__ == "__main__":
    runner = JobRunner()
    asyncio.run(runner.run_pending_jobs())
