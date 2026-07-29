"""Jobs: queue work, watch it, and cancel it."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.deps import get_current_user, get_db, require_project, require_project_artifact
from backend.api.schemas import (
    GenerateRequest,
    IngestRequest,
    JobAccepted,
    JobRequest,
    JobStatus,
    RefineRequest,
)
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.events import JOB_CANCELLED, JOB_CREATED, publish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

REQUEST_MODELS: Dict[str, type[BaseModel]] = {
    "ingest": IngestRequest,
    "generate": GenerateRequest,
    "refine": RefineRequest,
}

IN_FLIGHT = ("pending", "running")
DEDUPLICATION_WINDOW = 50


@router.post("", response_model=JobAccepted, status_code=202)
def create_job(
    request: JobRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> JobAccepted:
    """
    Queue a job.

    Every artifact id in the payload goes through `require_project_artifact`
    before the row is written. Owning the project isn't enough by itself. This
    route used to check the project and stop there, so you could queue a generate
    naming ids out of someone else's project, and the handler would read their
    content and write it into a new artifact in yours. That's a cross-tenant
    read, laundered through the generator.

    Writing the row comes before dispatch, so a broker outage delays the work
    without losing it.
    """
    require_project(request.project_id, user_id, database)

    try:
        payload = REQUEST_MODELS[request.type](**request.payload)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Invalid {request.type} payload: {error}") from error

    for artifact_id in _source_ids(payload):
        require_project_artifact(artifact_id, request.project_id, user_id, database)

    if isinstance(payload, GenerateRequest):
        duplicate = _find_in_flight_duplicate(database, request.project_id, payload)
        if duplicate:
            logger.info("Reusing in-flight job %s", duplicate["id"])
            return JobAccepted(
                job_id=duplicate["id"], status=duplicate["status"], dispatch="reused", reused=True
            )

    stored = _normalise(payload)
    rows = database.insert("jobs", {
        "project_id": request.project_id,
        "type": request.type,
        "status": "pending",
        "payload": stored,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Could not create the job")

    job_id = rows[0]["id"]
    logger.info("Queued %s job %s", request.type, job_id)
    publish(request.project_id, JOB_CREATED, {"job_id": job_id, "type": request.type})

    return JobAccepted(job_id=job_id, dispatch=enqueue(job_id))


@router.get("")
def list_jobs(
    project_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Recent jobs for one project, or across every project the caller owns."""
    if project_id:
        require_project(project_id, user_id, database)
        return database.select(
            "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=limit
        )

    projects = database.select("projects", [("user_id", f"eq.{user_id}")], columns="id")
    if not projects:
        return []

    ids = ",".join(project["id"] for project in projects)
    return database.select("jobs", [("project_id", f"in.({ids})")], order="created_at.desc", limit=limit)


@router.get("/{job_id}", response_model=JobStatus)
def get_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> JobStatus:
    """One job's current state and result."""
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    require_project(job["project_id"], user_id, database)
    return JobStatus(**{field: job.get(field) for field in JobStatus.model_fields})


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> Dict[str, str]:
    """Cancel a job that hasn't finished yet."""
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    require_project(job["project_id"], user_id, database)

    if not database.cancel_job(job_id):
        raise HTTPException(status_code=409, detail=f"Job is already {job['status']}")

    publish(job["project_id"], JOB_CANCELLED, {"job_id": job_id})
    return {"status": "cancelled", "id": job_id}


def _source_ids(payload: BaseModel) -> List[str]:
    """Every artifact this job will read, so we can check ownership before queueing it."""
    if isinstance(payload, GenerateRequest):
        return payload.sources()
    if isinstance(payload, RefineRequest):
        return [payload.source_artifact_id]
    return []


def _normalise(payload: BaseModel) -> Dict[str, Any]:
    """Store a generate payload in its multi-source form, whichever shape arrived."""
    if isinstance(payload, GenerateRequest):
        stored = payload.model_dump(exclude_none=True, exclude={"source_artifact_id"})
        stored["source_artifact_ids"] = payload.sources()
        return stored
    return payload.model_dump(exclude_none=True)


def _find_in_flight_duplicate(
    database: Database,
    project_id: str,
    payload: GenerateRequest,
) -> Optional[Dict[str, Any]]:
    """
    Find a job already in flight that does exactly this work.

    Only `pending` and `running` jobs count. Hand back a completed one and the
    regenerate button quietly returns the artifact the user already had, which
    looks like a broken button while the logs claim success. A steered request is
    never a duplicate either, because different instructions are different work.
    """
    if payload.instructions:
        return None

    wanted = sorted(payload.sources())
    candidates = database.select(
        "jobs",
        [("project_id", f"eq.{project_id}"), ("type", "eq.generate"),
         ("status", f"in.({','.join(IN_FLIGHT)})")],
        order="created_at.desc",
        limit=DEDUPLICATION_WINDOW,
    )

    for job in candidates:
        stored = job.get("payload") or {}
        if stored.get("target_type") != payload.target_type or stored.get("instructions"):
            continue
        if sorted(str(value) for value in stored.get("source_artifact_ids") or []) == wanted:
            return job

    return None
