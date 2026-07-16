"""Projects: create, read, update, delete, and upload sources into them."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from backend.core.config import get_settings
from backend.models.artifacts import SOURCE_TYPES
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.events import JOB_CREATED, publish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

EMPTY_CANVAS = {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []}
UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.get("")
def list_projects(
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Every project the caller owns, most recently updated first."""
    return database.select("projects", [("user_id", f"eq.{user_id}")], order="updated_at.desc")


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    request: ProjectCreate,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> ProjectResponse:
    """Create an empty project."""
    rows = database.insert("projects", {
        "name": request.name,
        "description": request.description,
        "user_id": user_id,
        "canvas_state": EMPTY_CANVAS,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Project creation returned no row")

    logger.info("Created project %s", rows[0]["id"])
    return ProjectResponse(**{field: rows[0].get(field) for field in ProjectResponse.model_fields})


@router.get("/{project_id}")
def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """One project, including its saved canvas."""
    return require_project(project_id, user_id, database)


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    request: ProjectUpdate,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """Rename a project or save its canvas layout."""
    require_project(project_id, user_id, database)

    changes = request.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")

    rows = database.update("projects", [("id", f"eq.{project_id}")], changes)
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")
    return rows[0]


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, str]:
    """Delete a project. Its artifacts, edges and jobs cascade with it."""
    require_project(project_id, user_id, database)
    database.delete("projects", [("id", f"eq.{project_id}")])

    logger.info("Deleted project %s", project_id)
    return {"status": "deleted", "id": project_id}


@router.get("/{project_id}/artifacts")
def list_artifacts(
    project_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """The project's knowledge graph: its artifacts and the edges between them."""
    require_project(project_id, user_id, database)
    return {
        "artifacts": database.select(
            "artifacts", [("project_id", f"eq.{project_id}")], order="created_at.asc"
        ),
        "edges": database.select("artifact_edges", [("project_id", f"eq.{project_id}")]),
    }


@router.post("/{project_id}/upload", status_code=202)
async def upload_source(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, Any]:
    """
    Accept a file and queue it for ingestion.

    The upload streams to a temp file rather than being read into memory, so a
    large lecture recording does not become an equally large resident process.
    """
    require_project(project_id, user_id, database)

    if source_type not in SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}",
        )

    temp_path, size = await _buffer_upload(file)

    rows = database.insert("jobs", {
        "project_id": project_id,
        "type": "ingest",
        "status": "pending",
        "payload": {
            "source_type": source_type,
            "source_ref": temp_path,
            "original_name": file.filename or "Untitled",
        },
    })
    if not rows:
        os.unlink(temp_path)
        raise HTTPException(status_code=500, detail="Could not queue the ingest job")

    job_id = rows[0]["id"]
    publish(project_id, JOB_CREATED, {"job_id": job_id, "type": "ingest", "filename": file.filename})

    return {
        "job_id": job_id,
        "filename": file.filename,
        "size_bytes": size,
        "dispatch": enqueue(job_id),
    }


async def _buffer_upload(file: UploadFile) -> tuple[str, int]:
    """Stream an upload to disk, enforcing the size limit as it goes."""
    limit = get_settings().upload_max_mb * 1024 * 1024
    suffix = os.path.splitext(file.filename or "")[1]
    written = 0

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as buffered:
        path = buffered.name
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > limit:
                buffered.close()
                os.unlink(path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {get_settings().upload_max_mb} MB limit",
                )
            buffered.write(chunk)

    if written == 0:
        os.unlink(path)
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    logger.info("Buffered %s (%d bytes)", file.filename, written)
    return path, written
