"""Project routes: CRUD, canvas persistence, artifacts and uploads.

Handlers here are plain ``def``, not ``async def``. The data layer is
synchronous, so declaring these ``async`` would run blocking I/O directly on the
event loop and stall every other request - including the WebSocket heartbeats.
Starlette runs sync handlers in a thread pool, which is the correct shape for
this workload.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    VALID_SOURCE_TYPES,
)
from backend.core.config import get_settings
from backend.services.db_interface import DBInterface
from backend.services.dispatcher import enqueue
from backend.services.events import EVENT_JOB_CREATED, publish

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

EMPTY_CANVAS = {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []}


@router.get("")
def list_projects(
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Every project owned by the caller, most recently updated first."""
    return db.select(
        "projects",
        [("user_id", f"eq.{user_id}")],
        order="updated_at.desc",
    )


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    request: ProjectCreate,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> ProjectResponse:
    rows = db.insert("projects", {
        "name": request.name,
        "description": request.description,
        "user_id": user_id,
        "canvas_state": EMPTY_CANVAS,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Project creation returned no row")

    project = rows[0]
    logger.info("Created project %s for %s", project["id"], user_id)
    return ProjectResponse(**{k: project.get(k) for k in ProjectResponse.model_fields})


@router.get("/{project_id}")
def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    return require_project(project_id, user_id, db)


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    request: ProjectUpdate,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    """Rename a project, or save its canvas layout."""
    require_project(project_id, user_id, db)

    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    rows = db.update("projects", [("id", f"eq.{project_id}")], updates)
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")
    return rows[0]


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, str]:
    """Delete a project. Artifacts, edges and jobs cascade with it."""
    require_project(project_id, user_id, db)
    db.delete("projects", [("id", f"eq.{project_id}")])
    logger.info("Deleted project %s", project_id)
    return {"status": "deleted", "id": project_id}


@router.get("/{project_id}/artifacts")
def list_artifacts(
    project_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """The project's knowledge graph: its artifacts and the edges between them."""
    require_project(project_id, user_id, db)
    return {
        "artifacts": db.select("artifacts", [("project_id", f"eq.{project_id}")], order="created_at.asc"),
        "edges": db.select("artifact_edges", [("project_id", f"eq.{project_id}")]),
    }


@router.post("/{project_id}/upload", status_code=202)
async def upload_and_ingest(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> Dict[str, Any]:
    """
    Accept a file and queue it for ingestion.

    The upload is streamed to a temp file rather than read into memory, so a
    600 MB lecture recording does not become 600 MB of resident process memory.
    The ingest job takes ownership of that temp file and the pipeline deletes it
    once the source has been stored.
    """
    require_project(project_id, user_id, db)

    if source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}",
        )

    settings = get_settings()
    max_bytes = settings.upload_max_mb * 1024 * 1024
    suffix = os.path.splitext(file.filename or "")[1]

    written = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                tmp.close()
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.upload_max_mb} MB limit",
                )
            tmp.write(chunk)

    if written == 0:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    logger.info("Buffered upload %s (%d bytes) for project %s", file.filename, written, project_id)

    rows = db.insert("jobs", {
        "project_id": project_id,
        "type": "ingest",
        "status": "pending",
        "payload": {
            "source_type": source_type,
            "source_ref": tmp_path,
            "original_name": file.filename or "Untitled",
            "size_bytes": written,
        },
    })
    if not rows:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail="Failed to queue the ingest job")

    job_id = rows[0]["id"]
    publish(project_id, EVENT_JOB_CREATED, {
        "job_id": job_id, "type": "ingest", "filename": file.filename,
    })
    dispatch = enqueue(job_id)

    return {"job_id": job_id, "filename": file.filename, "size_bytes": written, "dispatch": dispatch}
