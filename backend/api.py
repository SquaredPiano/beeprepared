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
import tempfile
from uuid import UUID
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
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


class ProjectCreate(BaseModel):
    """Request body for POST /api/projects."""
    name: str
    description: Optional[str] = None
    user_id: str


class ProjectResponse(BaseModel):
    """Response for project creation."""
    id: str
    name: str
    description: Optional[str] = None
    user_id: str


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
    2. Inserts job into DB with status='pending'
    3. Returns job_id
    
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
    
    # Insert job
    try:
        supabase = get_supabase()
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


@app.post("/api/projects", response_model=ProjectResponse)
async def create_project(request: ProjectCreate):
    """
    Create a new project.
    """
    logger.info(f"Creating project: {request.name} for user {request.user_id}")
    
    try:
        supabase = get_supabase()
        response = supabase.table("projects").insert({
            "name": request.name,
            "description": request.description,
            "user_id": request.user_id,
            "canvas_state": {
                "viewport": {"x": 0, "y": 0, "zoom": 1},
                "node_positions": {}
            }
        }).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create project")
        
        project = response.data[0]
        logger.info(f"Created project: {project['id']}")
        
        return ProjectResponse(
            id=project["id"],
            name=project["name"],
            description=project.get("description"),
            user_id=project["user_id"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/upload")
async def upload_and_ingest(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...)
):
    """
    Upload a file and create an ingest job.
    
    This endpoint:
    1. Saves the uploaded file temporarily
    2. Creates an ingest job with the file path
    3. Returns the job_id for polling
    
    source_type must be one of: audio, video, pdf, pptx, md
    """
    logger.info(f"Upload request: project={project_id}, file={file.filename}, type={source_type}")
    
    if source_type not in {"audio", "video", "pdf", "pptx", "md"}:
        raise HTTPException(status_code=400, detail=f"Invalid source_type: {source_type}")
    
    try:
        # Save file to temp directory
        suffix = f".{file.filename.split('.')[-1]}" if '.' in file.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"Saved uploaded file to: {tmp_path}")
        
        # Create ingest job
        supabase = get_supabase()
        response = supabase.table("jobs").insert({
            "project_id": project_id,
            "type": "ingest",
            "status": "pending",
            "payload": {
                "source_type": source_type,
                "source_ref": tmp_path,
                "original_name": file.filename
            }
        }).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create ingest job")
        
        job_id = response.data[0]["id"]
        logger.info(f"Created ingest job: {job_id}")
        
        return {"job_id": job_id, "filename": file.filename}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
