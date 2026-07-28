"""Projects: create, read, update, delete, and upload sources into them."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import IngestRequest, ProjectCreate, ProjectResponse, ProjectUpdate
from backend.core.config import get_settings
from backend.models.artifacts import SOURCE_TYPES
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.events import JOB_CREATED, publish
from backend.services.uploads import StagedUpload, UploadStaging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

EMPTY_CANVAS = {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []}
UPLOAD_CHUNK_BYTES = 1024 * 1024
UPLOADABLE_SOURCE_TYPES = SOURCE_TYPES - {"youtube"}


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

    The upload streams to disk rather than being read into memory, so a large
    lecture recording does not become an equally large resident process, and it
    is staged in the file store rather than in this process's temp directory:
    the job may be run by a Celery worker in another container, and the data
    volume the store sits on is the only thing that container shares with this
    one.

    A `youtube` source is fetched from a URL by the ingest pipeline and is not
    something anybody uploads, so it is refused before a byte is read. Accepting
    one queued a job that named a file on this server and then handed that file
    to the downloader.
    """
    require_project(project_id, user_id, database)

    if source_type not in UPLOADABLE_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(sorted(UPLOADABLE_SOURCE_TYPES))}",
        )

    staging = UploadStaging()
    staged = await _stage_upload(staging, file, project_id)

    try:
        rows = database.insert("jobs", {
            "project_id": project_id,
            "type": "ingest",
            "status": "pending",
            "payload": _ingest_payload(source_type, staged.key, file.filename),
        })
        if not rows:
            raise HTTPException(status_code=500, detail="Could not queue the ingest job")
    except Exception:
        staging.discard(staged.key, project_id)
        raise

    job_id = rows[0]["id"]
    publish(project_id, JOB_CREATED, {"job_id": job_id, "type": "ingest", "filename": file.filename})

    return {
        "job_id": job_id,
        "filename": file.filename,
        "size_bytes": staged.size_bytes,
        "dispatch": enqueue(job_id),
    }


def _ingest_payload(source_type: str, staged_key: str, filename: Optional[str]) -> Dict[str, Any]:
    """
    Build the job payload through the model the other ingest door already uses.

    Hand-writing the dictionary here is what let this route contradict
    `IngestRequest`: the rules about what a source may be lived in that model,
    and an upload never went through it. Sharing the model makes the invariant
    structural rather than something two routes have to remember separately.

    The dump drops what is unset, so the stored payload names the staged key and
    nothing else. `GET /api/jobs` hands that payload back to the caller, and a
    payload that also carried a filesystem path would be disclosing one.
    """
    try:
        request = IngestRequest(
            source_type=source_type,
            staged_key=staged_key,
            original_name=filename or "Untitled",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid ingest payload: {error}") from error

    return request.model_dump(exclude_none=True)


async def _stage_upload(
    staging: UploadStaging,
    file: UploadFile,
    project_id: str,
) -> StagedUpload:
    """
    Stream an upload onto the shared data volume, enforcing the limit as it goes.

    The bytes go through a temporary file so the request never holds the whole
    upload in memory, and that file belongs to this process alone: it is copied
    into the store, which every process that could run the ingest job can read,
    and dropped when the block closes, on the way out of a rejection as much as
    on success.
    """
    limit = get_settings().upload_max_mb * 1024 * 1024
    written = 0

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "").suffix) as buffered:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {get_settings().upload_max_mb} MB limit",
                )
            buffered.write(chunk)

        if written == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty")

        buffered.flush()
        staged = staging.stage(buffered.name, project_id, file.filename)

    logger.info("Staged %s (%d bytes) as %s", file.filename, written, staged.key)
    return staged
