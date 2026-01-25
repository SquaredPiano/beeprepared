from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import os
import asyncio
import tempfile
import logging
from backend.dependencies import get_current_user, supabase, SUPABASE_URL, SUPABASE_KEY

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="BeePrepared API", description="Knowledge Architecture Pipeline")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# MODELS
# ============================================================================

class Node(BaseModel):
    id: str
    type: str
    data: Any
    position: dict

class Edge(BaseModel):
    id: str
    source: str
    target: str

class RunRequest(BaseModel):
    project_id: str
    nodes: List[Node]
    edges: List[Edge]

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    canvas_state: Optional[dict] = None

# ============================================================================
# STARTUP: SCHEMA REPAIR
# ============================================================================

@app.on_event("startup")
async def repair_schema():
    """Ensure the database schema is consistent with the app expectations."""
    logger.info("🛠️ Checking database schema consistency...")
    if not supabase:
        logger.error("❌ Cannot repair schema: Supabase client not initialized")
        return

    try:
        # Check if 'projects' table exists and has 'user_id'
        # Using a raw select to trigger a potential 404 or 400
        test = supabase.table("projects").select("id, name").limit(1).execute()
        
        # If we got here, table exists. Let's check for user_id and canvas_state
        # We'll just try to select them. If they fail, we suggest running migration.
        try:
            supabase.table("projects").select("user_id, canvas_state").limit(1).execute()
        except Exception as e:
            logger.warning(f"⚠️ Schema mismatch detected: {e}. Attempting to apply migration...")
            # Ideally we'd run raw SQL here, but Supabase SDK doesn't support it directly.
            # We assume the user will run the apply_migration.py script.
            logger.error("❌ DATABASE INCONSISTENCY: Please run 'python -m backend.scripts.apply_migration'")
            
    except Exception as e:
        logger.error(f"❌ CRITICAL: 'projects' table missing or inaccessible: {e}")

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {"status": "operational", "service": "BeePrepared API"}

@app.get("/api/projects", response_model=List[Any])
async def list_projects(user_id: str = Depends(get_current_user)):
    """List all projects for the current user."""
    try:
        response = supabase.table("projects").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
        return response.data or []
    except Exception as e:
        logger.error(f"Project list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

@app.post("/api/projects")
async def create_project(req: ProjectCreate, user_id: str = Depends(get_current_user)):
    """Create a new project for the current user."""
    try:
        data = {
            "name": req.name,
            "description": req.description,
            "user_id": user_id,
            "canvas_state": {
                "viewport": {"x": 0, "y": 0, "zoom": 1},
                "nodes": [],
                "edges": []
            }
        }
        response = supabase.table("projects").insert(data).execute()
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create project")
        return response.data[0]
    except Exception as e:
        logger.error(f"Project create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user)):
    """Delete a project if owned by the user."""
    try:
        # Check ownership
        proj = supabase.table("projects").select("user_id").eq("id", project_id).execute()
        if not proj.data:
            raise HTTPException(status_code=404, detail="Project not found")
        if proj.data[0].get('user_id') != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
            
        supabase.table("projects").delete().eq("id", project_id).execute()
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Project delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run")
async def run_pipeline(
    request: RunRequest, 
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """Activates the architectural pipeline for a project."""
    logger.info(f"🚀 Activating pipeline for project: {request.project_id}")
    
    # Verify ownership
    proj = supabase.table("projects").select("*").eq("id", request.project_id).execute()
    if not proj.data:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check ownership (manual check to ensure RLS-bypass service role works correctly)
    owner_id = proj.data[0].get('user_id')
    if owner_id and owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Start background processing
    background_tasks.add_task(process_pipeline, request.project_id, request.nodes, request.edges, user_id)

    return {
        "message": "Pipeline activation initiated",
        "activated_nodes": len([n for n in request.nodes if n.type == 'process']),
        "project_id": request.project_id
    }

@app.get("/api/points")
async def get_points(user_id: str = Depends(get_current_user)):
    """Get the current point balance for the user."""
    try:
        # For now, return a mock balance or fetch from a 'profiles' table if it exists
        # Let's assume there's a profiles table with a 'points' column
        res = supabase.table("profiles").select("points").eq("id", user_id).single().execute()
        if res.data:
            return res.data["points"]
        return 500  # Default starting points
    except Exception:
        return 500

@app.get("/api/projects/{project_id}/artifacts")
async def list_project_artifacts(
    project_id: str,
    user_id: str = Depends(get_current_user)
):
    """List all artifacts and edges for a project."""
    logger.info(f"🔍 Fetching artifacts for project: {project_id}")
    
    # Verify ownership
    proj = supabase.table("projects").select("*").eq("id", project_id).execute()
    if not proj.data:
        raise HTTPException(status_code=404, detail="Project not found")
    
    owner_id = proj.data[0].get('user_id')
    if owner_id and owner_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    artifacts = supabase.table("artifacts").select("*").eq("project_id", project_id).execute()
    edges = supabase.table("artifact_edges").select("*").eq("project_id", project_id).execute()
    
    return {
        "artifacts": artifacts.data or [],
        "edges": edges.data or [],
    }

@app.get("/api/vault")
async def list_vault(
    path: str = "/", 
    user_id: str = Depends(get_current_user)
):
    """List global assets in the user's Knowledge Vault."""
    try:
        # Fetch all artifacts owned by user
        # In a real file system, we'd filter by folder_path, but for now we fetch all and let frontend organize, or basic filter
        query = supabase.table("artifacts").select("*").eq("user_id", user_id)
        if path != "/":
            query = query.eq("folder_path", path)
            
        artifacts = query.execute()
        return {"files": artifacts.data or []}
    except Exception as e:
        logger.error(f"Vault list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/upload")
async def upload_and_ingest(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    folder: str = Form("/"),
    user_id: str = Depends(get_current_user)
):
    """Upload a file to the project AND global vault."""
    logger.info(f"📂 Upload request: project={project_id}, folder={folder}, file={file.filename}")
    
    # Verify ownership
    proj = supabase.table("projects").select("*").eq("id", project_id).execute()
    if not proj.data:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if proj.data[0].get('user_id') != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        # 1. Save file temporarily
        suffix = f".{file.filename.split('.')[-1]}" if '.' in file.filename else ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # 2. Create ingest job
        # We pass user_id so the worker knows who owns the resulting artifact
        job_response = supabase.table("jobs").insert({
            "project_id": project_id,
            "type": "ingest",
            "status": "pending",
            "payload": {
                "source_type": sourceType_map(source_type),
                "source_ref": tmp_path,
                "original_name": file.filename,
                "user_id": user_id,
                "folder_path": folder
            }
        }).execute()
        
        if not job_response.data:
            raise HTTPException(status_code=500, detail="Failed to create ingest job")
        
        return {"job_id": job_response.data[0]["id"], "status": "pending"}
    except Exception as e:
        logger.error(f"❌ Upload processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    user_id: str = Depends(get_current_user)
):
    """Get status of a background job."""
    job = supabase.table("jobs").select("*").eq("id", job_id).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job.data[0]

# ============================================================================
# HELPERS
# ============================================================================

def sourceType_map(t: str) -> str:
    """Standardizes source types."""
    mapping = {
        "pdf": "pdf",
        "pptx": "pptx",
        "audio": "audio",
        "video": "video",
        "md": "md",
        "txt": "md"
    }
    return mapping.get(t.lower(), "pdf")

async def process_pipeline(project_id: str, nodes: List[Node], edges: List[Edge], user_id: str):
    """Universal process runner (Mock)."""
    # Simply marks process nodes as ready for now
    updated_nodes = []
    for node in nodes:
        n_dict = node.dict()
        if n_dict['type'] == 'process':
            n_dict['data']['status'] = 'ready'
            n_dict['data']['progress'] = 100
        updated_nodes.append(n_dict)
    
    supabase.table("projects").update({"canvas_state": {"nodes": updated_nodes, "edges": [e.dict() for e in edges]}}).eq("id", project_id).execute()

