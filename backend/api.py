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
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# SUPABASE HTTP CLIENT (No SDK needed)
# ============================================================================

class SupabaseClient:
    """Simple Supabase REST API client using httpx."""
    
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL", "")
        self.key = os.environ.get("SUPABASE_KEY", "")
        if not self.url or not self.key:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        self.rest_url = f"{self.url}/rest/v1"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
    
    def table(self, name: str):
        return SupabaseTable(self, name)


class SupabaseTable:
    """Simple table operations for Supabase REST API."""
    
    def __init__(self, client: SupabaseClient, table_name: str):
        self.client = client
        self.table_name = table_name
        self.url = f"{client.rest_url}/{table_name}"
        self._filters = []
        self._select = "*"
        self._insert_data = None
        self._update_data = None
        self._is_delete = False
    
    def select(self, columns: str = "*"):
        self._select = columns
        return self
    
    def eq(self, column: str, value):
        self._filters.append(f"{column}=eq.{value}")
        return self
    
    def insert(self, data: dict):
        """Queue an insert operation."""
        self._insert_data = data
        return self
    
    def update(self, data: dict):
        """Queue an update operation."""
        self._update_data = data
        return self
    
    def delete(self):
        """Queue a delete operation."""
        self._is_delete = True
        return self
    
    def execute(self):
        """Execute the queued operation."""
        url = self.url
        
        # Add filters to URL
        if self._filters:
            url += "?" + "&".join(self._filters)
        
        with httpx.Client() as http:
            if self._insert_data is not None:
                # INSERT
                response = http.post(self.url, headers=self.client.headers, json=self._insert_data)
            elif self._update_data is not None:
                # UPDATE
                response = http.patch(url, headers=self.client.headers, json=self._update_data)
            elif self._is_delete:
                # DELETE
                response = http.delete(url, headers=self.client.headers)
            else:
                # SELECT
                params = {"select": self._select}
                response = http.get(url, headers=self.client.headers, params=params)
            
            if response.status_code >= 400:
                raise Exception(f"Supabase error: {response.text}")
            
            data = response.json() if response.text else None
            return type('Response', (), {'data': data})()


def get_supabase() -> SupabaseClient:
    """Get Supabase client."""
    return SupabaseClient()


# ============================================================================
# AUTHENTICATION
# ============================================================================

def get_current_user(authorization: str = Header(None)) -> str:
    """
    Validates the Bearer Token sent by the Frontend.
    Returns the User ID if valid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    try:
        token = authorization.replace("Bearer ", "")
        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_KEY", "")
        
        if not supabase_url or not supabase_key:
            raise HTTPException(status_code=500, detail="Missing Supabase configuration")
        
        # Verify token via Supabase Auth API
        auth_url = f"{supabase_url}/auth/v1/user"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {token}"
        }
        
        with httpx.Client() as http:
            response = http.get(auth_url, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            
            user_data = response.json()
            user_id = user_data.get("id")
            
            if not user_id:
                raise HTTPException(status_code=401, detail="Could not extract user ID")
            
            return user_id
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


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


class ProjectResponse(BaseModel):
    """Response for project creation."""
    id: str
    name: str
    description: Optional[str] = None
    user_id: Optional[str] = None
    canvas_state: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "BeePrepared Hive API"}


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


@app.get("/api/projects")
async def list_projects(user_id: str = Depends(get_current_user)):
    """
    List all projects for the authenticated user.
    
    Returns projects ordered by updated_at descending.
    """
    logger.info(f"Listing projects for user: {user_id}")
    
    try:
        supabase = get_supabase()
        
        # Fetch projects for this user, ordered by most recent
        response = supabase.table("projects").select("*").eq("user_id", user_id).execute()
        
        projects = response.data or []
        
        # Sort by updated_at desc (in Python since our simple client doesn't support order)
        projects.sort(key=lambda p: p.get("updated_at", p.get("created_at", "")), reverse=True)
        
        logger.info(f"Found {len(projects)} projects for user")
        return projects
        
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(get_current_user)):
    """
    Get a single project by ID.
    
    Verifies the project belongs to the authenticated user.
    """
    try:
        supabase = get_supabase()
        response = supabase.table("projects").select("*").eq("id", project_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project = response.data[0]
        
        # Verify ownership
        if project.get("user_id") and project.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return project
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects", response_model=ProjectResponse)
async def create_project(request: ProjectCreate, user_id: str = Depends(get_current_user)):
    """
    Create a new project for the authenticated user.
    
    Requires valid Bearer token in Authorization header.
    """
    logger.info(f"Creating project: {request.name} for user: {user_id}")
    
    try:
        supabase = get_supabase()
        
        # Build insert data - always include user_id and canvas_state
        # (requires migration to be applied, but is necessary for proper multi-tenancy)
        insert_data = {
            "name": request.name,
            "description": request.description,
            "user_id": user_id,
            "canvas_state": {
                "viewport": {"x": 0, "y": 0, "zoom": 1},
                "nodes": [],
                "edges": []
            }
        }
        
        try:
            response = supabase.table("projects").insert(insert_data).execute()
        except Exception as insert_error:
            # If insert failed (possibly due to missing columns), try minimal insert
            logger.warning(f"Full insert failed: {insert_error}. Trying minimal insert (migration may not be applied)")
            minimal_data = {
                "name": request.name,
                "description": request.description
            }
            response = supabase.table("projects").insert(minimal_data).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create project - no data returned")
        
        project = response.data[0]
        logger.info(f"Created project: {project['id']}")
        
        return ProjectResponse(
            id=project["id"],
            name=project["name"],
            description=project.get("description"),
            user_id=project.get("user_id"),
            canvas_state=project.get("canvas_state"),
            created_at=project.get("created_at"),
            updated_at=project.get("updated_at")
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
    source_type: str = Form(...),
    user_id: str = Depends(get_current_user)
):
    """
    Upload a file and create an ingest job.
    
    This endpoint:
    1. Verifies project ownership
    2. Saves the uploaded file temporarily
    3. Creates an ingest job with the file path
    4. Returns the job_id for polling
    
    source_type must be one of: audio, video, pdf, pptx, md
    """
    logger.info(f"Upload request: project={project_id}, file={file.filename}, type={source_type}, user={user_id}")
    
    if source_type not in {"audio", "video", "pdf", "pptx", "md"}:
        raise HTTPException(status_code=400, detail=f"Invalid source_type: {source_type}")
    
    try:
        supabase = get_supabase()
        
        # Verify project ownership
        proj_response = supabase.table("projects").select("user_id").eq("id", project_id).execute()
        if not proj_response.data or len(proj_response.data) == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project_owner = proj_response.data[0].get("user_id")
        if project_owner and project_owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Save file to temp directory
        suffix = f".{file.filename.split('.')[-1]}" if '.' in file.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"Saved uploaded file to: {tmp_path}")
        
        # Create ingest job
        response = supabase.table("jobs").insert({
            "project_id": project_id,
            "type": "ingest",
            "status": "pending",
            "payload": {
                "source_type": source_type,
                "source_ref": tmp_path,
                "original_name": file.filename,
                "user_id": user_id
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


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user)):
    """
    Delete a project and all related artifacts.
    
    Verifies ownership before deletion.
    Note: Cascade delete is handled by PostgreSQL foreign keys.
    """
    logger.info(f"Deleting project: {project_id} for user: {user_id}")
    
    try:
        supabase = get_supabase()
        
        # Verify ownership first
        response = supabase.table("projects").select("user_id").eq("id", project_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project_owner = response.data[0].get("user_id")
        if project_owner and project_owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Delete the project
        supabase.table("projects").delete().eq("id", project_id).execute()
        logger.info(f"Deleted project: {project_id}")
        return {"status": "deleted", "id": project_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProjectUpdate(BaseModel):
    """Request body for PATCH /api/projects/{project_id}."""
    name: Optional[str] = None
    description: Optional[str] = None
    canvas_state: Optional[dict] = None


@app.patch("/api/projects/{project_id}")
async def update_project(
    project_id: str, 
    request: ProjectUpdate, 
    user_id: str = Depends(get_current_user)
):
    """
    Update a project's name, description, or canvas state.
    
    Verifies ownership before update.
    """
    logger.info(f"Updating project: {project_id} for user: {user_id}")
    
    try:
        supabase = get_supabase()
        
        # Verify ownership first
        response = supabase.table("projects").select("user_id").eq("id", project_id).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project_owner = response.data[0].get("user_id")
        if project_owner and project_owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Build update data (only include non-None fields)
        update_data = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.canvas_state is not None:
            update_data["canvas_state"] = request.canvas_state
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No update fields provided")
        
        # Perform update
        update_response = supabase.table("projects").update(update_data).eq("id", project_id).execute()
        
        if not update_response.data or len(update_response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to update project")
        
        logger.info(f"Updated project: {project_id}")
        return update_response.data[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
