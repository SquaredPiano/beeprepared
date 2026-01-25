"""
BeePrepared API: FastAPI Entry Point

INVARIANT: This API layer is INTENTIONALLY DUMB.
- Validate input
- Insert job
- Return job_id
- NEVER run core logic

Core logic is executed by JobRunner in async loop.
"""

import os
import logging
from uuid import UUID
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# FROZEN PAYLOAD CONTRACTS
# ============================================================================

class IngestPayload(BaseModel):
    """Frozen payload for 'ingest' jobs."""
    source_type: str  # "youtube | audio | video | pdf | pptx | md"
    source_ref: str   # URL or file path
    original_name: str = "Untitled"


class GeneratePayload(BaseModel):
    """Frozen payload for 'generate' jobs."""
    source_artifact_id: str  # UUID as string
    target_type: str  # "quiz | exam | notes | slides | flashcards"


class JobRequest(BaseModel):
    """Request body for POST /api/jobs."""
    project_id: str
    type: str  # "ingest" | "generate"
    payload: dict


class JobResponse(BaseModel):
    """Response for job creation."""
    job_id: str


class JobStatusResponse(BaseModel):
    """Response for GET /api/jobs/{job_id}."""
    id: str
    project_id: str
    type: str
    status: str
    payload: dict
    result: Optional[dict] = None
    error_message: Optional[str] = None


# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="BeePrepared API",
    description="Backend API for the BeePrepared learning platform",
    version="0.1.0"
)

# CORS (allow all for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_supabase() -> Client:
    """Get Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE credentials")
    return create_client(url, key)


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/jobs", response_model=JobResponse)
async def create_job(request: JobRequest):
    """
    Create a new job.
    
    This endpoint:
    1. Validates input
    2. Checks for idempotency (don't duplicate completed work)
    3. Inserts job into DB with status='pending'
    4. Returns job_id
    
    The JobRunner will pick up the job asynchronously.
    """
    logger.info(f"Creating job: type={request.type}, project={request.project_id}")
    
    # Validate job type
    if request.type not in {"ingest", "generate"}:
        raise HTTPException(status_code=400, detail=f"Invalid job type: {request.type}")
    
    # Validate payload based on type
    if request.type == "ingest":
        try:
            IngestPayload(**request.payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid ingest payload: {e}")
    elif request.type == "generate":
        try:
            GeneratePayload(**request.payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid generate payload: {e}")
    
    supabase = get_supabase()
    
    # =========================================================================
    # IDEMPOTENCY CHECK: Don't duplicate completed work
    # =========================================================================
    if request.type == "generate":
        source_id = request.payload.get("source_artifact_id")
        target_type = request.payload.get("target_type")
        
        # Check if a completed or running job already exists for this exact work
        existing = supabase.table("jobs").select("id,status,result").eq(
            "project_id", request.project_id
        ).eq("type", "generate").in_(
            "status", ["completed", "running", "pending"]
        ).execute()
        
        for job in existing.data:
            payload = job.get("result", {}) if job["status"] == "completed" else {}
            job_source = job.get("payload", {}).get("source_artifact_id") if "payload" in job else None
            job_target = job.get("payload", {}).get("target_type") if "payload" in job else None
            
            # Need to re-fetch to get payload
            if job_source is None:
                full_job = supabase.table("jobs").select("payload").eq("id", job["id"]).execute()
                if full_job.data:
                    job_payload = full_job.data[0].get("payload", {})
                    job_source = job_payload.get("source_artifact_id")
                    job_target = job_payload.get("target_type")
            
            if job_source == source_id and job_target == target_type:
                if job["status"] == "completed":
                    logger.info(f"Idempotency: Returning existing completed job {job['id']}")
                    return JobResponse(job_id=job["id"])
                elif job["status"] in ["running", "pending"]:
                    logger.info(f"Idempotency: Returning existing in-progress job {job['id']}")
                    return JobResponse(job_id=job["id"])
    
    # Insert new job
    try:
        response = supabase.table("jobs").insert({
            "project_id": request.project_id,
            "type": request.type,
            "status": "pending",
            "payload": request.payload,
        }).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to insert job")
        
        job_id = response.data[0]["id"]
        logger.info(f"Created job: {job_id}")
        
        return JobResponse(job_id=job_id)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get job status.
    
    Returns current status and result (if completed).
    """
    try:
        supabase = get_supabase()
        response = supabase.table("jobs").select("*").eq("id", job_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        
        job = response.data[0]
        
        return JobStatusResponse(
            id=job["id"],
            project_id=job["project_id"],
            type=job["type"],
            status=job["status"],
            payload=job["payload"],
            result=job.get("result"),
            error_message=job.get("error_message"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/artifacts")
async def list_project_artifacts(project_id: str):
    """
    List all artifacts for a project.
    
    Returns artifacts and edges (for React Flow rendering).
    """
    try:
        supabase = get_supabase()
        
        # Fetch artifacts
        artifacts_response = supabase.table("artifacts").select("*").eq("project_id", project_id).execute()
        
        # Fetch edges
        edges_response = supabase.table("artifact_edges").select("*").eq("project_id", project_id).execute()
        
        return {
            "artifacts": artifacts_response.data or [],
            "edges": edges_response.data or [],
        }
        
    except Exception as e:
        logger.error(f"Failed to list artifacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
